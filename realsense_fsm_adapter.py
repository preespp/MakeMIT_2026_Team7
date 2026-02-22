from __future__ import annotations

import os
import time
from typing import Any

import requests


class RealSenseFSMAdapter:
    """
    Bridges local RealSense events to the Flask FSM API.

    Safe-by-default:
    - network errors are swallowed (returns None/False)
    - duplicate events are throttled
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        enabled: bool | None = None,
        timeout_s: float = 0.35,
        distance_push_interval_s: float = 0.20,
        recognition_push_cooldown_s: float = 3.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("FSM_API_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")
        if enabled is None:
            env = os.getenv("FSM_API_BRIDGE_ENABLED", "1").strip().lower()
            enabled = env not in {"0", "false", "no", "off"}
        self.enabled = bool(enabled)
        self.timeout_s = max(0.1, float(timeout_s))
        self.distance_push_interval_s = max(0.05, float(distance_push_interval_s))
        self.recognition_push_cooldown_s = max(0.2, float(recognition_push_cooldown_s))

        self._session = requests.Session()
        self._last_distance_push_at = 0.0
        self._last_distance_value: float | None = None
        self._monitoring_started = False
        self._last_recognition_key = ""
        self._last_recognition_at = 0.0

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            response = self._session.post(
                f"{self.base_url}{path}",
                json=payload or {},
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def ensure_monitoring(self) -> dict[str, Any] | None:
        if self._monitoring_started:
            return None
        data = self._post("/api/start-monitoring", {})
        if data and data.get("ok"):
            self._monitoring_started = True
        elif data and str(data.get("message", "")).lower().startswith("system is already running"):
            self._monitoring_started = True
        return data

    def reset_session_hint(self) -> None:
        self._monitoring_started = False
        self._last_recognition_key = ""
        self._last_recognition_at = 0.0
        self._last_distance_push_at = 0.0
        self._last_distance_value = None

    def push_distance(self, distance_m: float) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            value = round(float(distance_m), 2)
        except (TypeError, ValueError):
            return None

        now = time.time()
        if self._last_distance_value is not None:
            if abs(value - self._last_distance_value) < 0.03 and (now - self._last_distance_push_at) < self.distance_push_interval_s:
                return None
        if (now - self._last_distance_push_at) < self.distance_push_interval_s:
            return None

        self.ensure_monitoring()
        data = self._post("/api/distance", {"distance_m": value})
        if data and not data.get("ok"):
            msg = str(data.get("message", "")).lower()
            if "monitoring distance" in msg or "distance updates are only accepted" in msg:
                self._monitoring_started = False
                self.ensure_monitoring()
                data = self._post("/api/distance", {"distance_m": value})
        self._last_distance_push_at = now
        self._last_distance_value = value
        return data

    def report_recognition_existing(self, user_id: str, confidence: float | None = None) -> dict[str, Any] | None:
        uid = str(user_id or "").strip()
        if not uid:
            return None
        key = f"existing:{uid}"
        now = time.time()
        if key == self._last_recognition_key and (now - self._last_recognition_at) < self.recognition_push_cooldown_s:
            return None
        self.ensure_monitoring()
        payload: dict[str, Any] = {
            "match_type": "existing",
            "user_id": uid,
            "source": "REALSENSE_LOCAL",
        }
        if confidence is not None:
            try:
                payload["confidence"] = float(confidence)
            except (TypeError, ValueError):
                pass
        data = self._post("/api/recognition/local", payload)
        if data and data.get("ok"):
            self._last_recognition_key = key
            self._last_recognition_at = now
            # Recognition ends the monitoring phase in the FSM, so force a fresh start next session.
            self._monitoring_started = False
        return data

    def report_recognition_new(self, confidence: float | None = None) -> dict[str, Any] | None:
        key = "new"
        now = time.time()
        if key == self._last_recognition_key and (now - self._last_recognition_at) < self.recognition_push_cooldown_s:
            return None
        self.ensure_monitoring()
        payload: dict[str, Any] = {
            "match_type": "new",
            "source": "REALSENSE_LOCAL",
        }
        if confidence is not None:
            try:
                payload["confidence"] = float(confidence)
            except (TypeError, ValueError):
                pass
        data = self._post("/api/recognition/local", payload)
        if data and data.get("ok"):
            self._last_recognition_key = key
            self._last_recognition_at = now
            self._monitoring_started = False
        return data

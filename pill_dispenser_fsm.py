from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from advice_engine import generate_advice_payload
from shared_user_storage import SharedUserStorage

try:
    import serial  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    serial = None


class WorkflowState(str, Enum):
    WAITING_FOR_USER = "WAITING_FOR_USER"
    MONITORING_DISTANCE = "MONITORING_DISTANCE"
    FACE_RECOGNITION = "FACE_RECOGNITION"
    REGISTER_NEW_USER = "REGISTER_NEW_USER"
    REGISTRATION_SUCCESS = "REGISTRATION_SUCCESS"
    DISPENSING_PILL = "DISPENSING_PILL"
    GENERATING_ADVICE = "GENERATING_ADVICE"
    SPEAKING_ADVICE = "SPEAKING_ADVICE"
    SESSION_SUCCESS = "SESSION_SUCCESS"
    ERROR = "ERROR"


class PillDispenserFSM:
    """
    Central controller for the smart home pill dispenser workflow.
    ESP32, RealSense, and Gemini calls are represented with placeholders.
    """

    def __init__(
        self,
        distance_threshold_m: float = 0.7,
        success_display_seconds: int = 8,
        speech_duration_seconds: int = 12,
        dispense_display_seconds: float = 4.0,
        advice_generation_seconds: float = 1.2,
    ) -> None:
        self._lock = RLock()
        self._state = WorkflowState.WAITING_FOR_USER
        self._last_error = ""
        self._history: list[dict[str, str]] = []

        self._distance_threshold_m = distance_threshold_m
        self._success_display_seconds = success_display_seconds
        self._speech_duration_seconds = speech_duration_seconds
        self._dispense_display_seconds = max(0.0, float(dispense_display_seconds))
        self._advice_generation_seconds = max(0.0, float(advice_generation_seconds))

        self._current_distance_m: float | None = None
        self._active_user_id = ""
        self._active_user_profile: dict[str, Any] = {}
        self._last_recognition: dict[str, Any] = {}
        self._last_uart_command: dict[str, Any] = {}
        self._last_uart_result: dict[str, Any] = {}
        self._last_dispense_plan: dict[str, Any] = {}
        self._advice_text = ""
        self._last_advice_payload: dict[str, Any] = {}
        self._is_speaking = False
        self._speech_ends_at: datetime | None = None
        self._auto_return_at: datetime | None = None
        self._dispense_stage_ends_at: datetime | None = None
        self._advice_generation_ends_at: datetime | None = None

        self._compute_node = "JETSON_LOCAL"
        self._camera_source = "REALSENSE_LOCAL"
        self._uart_transport = "USB_UART"
        self._uart_port = "/dev/ttyUSB0"
        self._uart_baud = 115200
        self._uart_protocol = (str(os.getenv("UART_PROTOCOL", "json")).strip().lower() or "json")
        self._uart_timeout_s = max(0.5, float(os.getenv("UART_TIMEOUT_S", "6") or "6"))
        self._uart_serial_enabled = str(os.getenv("UART_SERIAL_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
        self._uart_offline_fallback = str(os.getenv("UART_OFFLINE_FALLBACK", "1")).strip().lower() not in {"0", "false", "no", "off"}
        self._motor_power = "EXTERNAL_BATTERY"

        self._base_dir = Path(__file__).resolve().parent
        self._users_dir = self._base_dir / "data" / "users"
        self._faces_dir = self._base_dir / "data" / "faces"
        self._logs_dir = self._base_dir / "data" / "logs"
        self._runtime_dir = self._base_dir / "data" / "runtime"
        self._users_dir.mkdir(parents=True, exist_ok=True)
        self._faces_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        self._dispense_log_file = self._logs_dir / "dispense_log.jsonl"
        self._session_log_file = self._logs_dir / "session_log.jsonl"
        self._shared_store = SharedUserStorage(self._base_dir)
        self._pending_realsense_embedding_file = self._runtime_dir / "realsense_pending_embedding.json"
        self._session_context: dict[str, Any] = {}
        self._last_session_summary: dict[str, Any] = {}
        self._manual_override_available = False

        self._record_event("INIT", self._state.value, "FSM initialized.")

    def status(self) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            return self._snapshot()

    def list_users(self) -> list[dict[str, str]]:
        with self._lock:
            self._maybe_auto_progress()
            return self._list_known_users()

    def start_monitoring(self) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            if self._state != WorkflowState.WAITING_FOR_USER:
                return self._response(False, "System is already running.")

            self._clear_runtime_context(clear_error=True)
            self._start_session_context()
            self._transition(
                WorkflowState.MONITORING_DISTANCE,
                "Monitoring for user distance from camera.",
            )
            return self._response(
                True,
                "Monitoring started. Waiting for user to move within threshold distance.",
            )

    def update_distance(self, distance_m: float) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            if self._state != WorkflowState.MONITORING_DISTANCE:
                return self._response(
                    False,
                    "Distance updates are only accepted while monitoring distance.",
                )

            if distance_m <= 0:
                return self._response(False, "Distance must be a positive number.")

            self._current_distance_m = round(distance_m, 2)
            if self._current_distance_m <= self._distance_threshold_m:
                self._transition(
                    WorkflowState.FACE_RECOGNITION,
                    f"User reached {self._current_distance_m}m. Running local RealSense face recognition.",
                )
                return self._response(
                    True,
                    "User is close enough. Submit local recognition result (new or existing).",
                )

            remaining = round(self._current_distance_m - self._distance_threshold_m, 2)
            return self._response(
                True,
                f"User detected at {self._current_distance_m}m. Move {remaining}m closer.",
            )

    def set_recognition_result(
        self,
        match_type: str,
        user_id: str | None = None,
        source: str = "REALSENSE_LOCAL",
        confidence: float | None = None,
    ) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            if self._state != WorkflowState.FACE_RECOGNITION:
                return self._response(
                    False,
                    "Recognition selection is only valid in FACE_RECOGNITION state.",
                )

            normalized = (match_type or "").strip().lower()
            safe_source = self._clean_text(source).upper() or "REALSENSE_LOCAL"
            normalized_confidence: float | None = None
            if confidence is not None:
                try:
                    normalized_confidence = round(float(confidence), 4)
                except (TypeError, ValueError):
                    normalized_confidence = None

            if normalized == "new":
                self._ensure_session_context()
                self._last_recognition = {
                    "match_type": "new",
                    "user_id": "",
                    "source": safe_source,
                    "confidence": normalized_confidence,
                }
                self._session_context["recognition"] = dict(self._last_recognition)
                self._transition(
                    WorkflowState.REGISTER_NEW_USER,
                    "Local face recognition did not match. Switching to new user registration.",
                )
                return self._response(
                    True,
                    "New user path selected from local recognition. Fill in details and capture a face photo.",
                )

            if normalized != "existing":
                return self._response(False, "match_type must be either 'new' or 'existing'.")

            resolved_user_id = self._resolve_existing_user_id(user_id)
            if not resolved_user_id:
                return self._response(
                    False,
                    "No existing user selected. Register a user first or pick one from the list.",
                )

            profile = self._load_user_profile(resolved_user_id)
            if not profile:
                return self._response(False, "Selected user profile was not found on disk.")

            # Same-name overwrite mode can leave duplicate historical user IDs on disk.
            # If the recognition layer returns an older duplicate ID, prefer the most recently
            # updated profile for that same normalized name so dispense/advice uses the latest data.
            preferred_profile = self._find_existing_user_profile_by_name(str(profile.get("name", "")))
            if preferred_profile:
                preferred_user_id = self._safe_user_id(str(preferred_profile.get("id", "")))
                if preferred_user_id and preferred_user_id != resolved_user_id:
                    resolved_user_id = preferred_user_id
                    profile = preferred_profile

            self._active_user_id = resolved_user_id
            self._active_user_profile = profile
            self._ensure_session_context()
            self._last_recognition = {
                "match_type": "existing",
                "user_id": resolved_user_id,
                "source": safe_source,
                "confidence": normalized_confidence,
            }
            self._session_context["user_id"] = resolved_user_id
            self._session_context["recognition"] = dict(self._last_recognition)
            self._transition(
                WorkflowState.DISPENSING_PILL,
                f"Local recognition matched existing user: {profile.get('name', resolved_user_id)}.",
            )

            if not self._dispense_pill(profile):
                self._append_dispense_log(
                    user_id=resolved_user_id,
                    medication=str(profile.get("medication", "")),
                    result="FAILED",
                    details=f"uart={self._uart_transport} status={self._last_uart_result.get('status', 'UNKNOWN')}",
                )
                return self._to_error("Failed to dispense pill for existing user.")

            self._append_dispense_log(
                user_id=resolved_user_id,
                medication=str(profile.get("medication", "")),
                result="SKIPPED" if str(self._last_uart_result.get("status", "")).upper() == "NO_DUE" else "SUCCESS",
                details=f"uart={self._uart_transport} status={self._last_uart_result.get('status', 'UNKNOWN')}",
            )
            self._dispense_stage_ends_at = self._now() + timedelta(
                seconds=self._dispense_display_seconds
            )
            return self._response(
                True,
                "Existing user recognized locally. Dispensing UI active; advice will start after dispense stage completes.",
            )

    def register_new_user(self, payload: dict[str, Any]) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            if self._state != WorkflowState.REGISTER_NEW_USER:
                return self._response(
                    False,
                    "User registration is only available in REGISTER_NEW_USER state.",
                )

            name = self._clean_text(payload.get("name"))
            medication = self._clean_text(payload.get("medication"))
            dosage = self._clean_text(payload.get("dosage"))
            notes = self._clean_text(payload.get("notes"))
            age = self._clean_text(payload.get("age"))
            language = self._clean_text(payload.get("language")) or "en-US"
            user_timezone = self._clean_text(payload.get("timezone"))
            servo_channel = self._parse_servo_channel(payload.get("servo_channel"), default=1)
            photo_data_url = payload.get("photo_data_url", "")
            raw_medications = payload.get("medications")
            raw_schedule_times = payload.get("schedule_times")

            medications: list[dict[str, Any]] = []
            if isinstance(raw_medications, list):
                for item in raw_medications:
                    if not isinstance(item, dict):
                        continue
                    med_name = self._clean_text(item.get("name"))
                    if not med_name:
                        continue
                    times = item.get("times")
                    if not isinstance(times, list):
                        times = []
                    medications.append(
                        {
                            "id": self._safe_user_id(item.get("id") or med_name.lower().replace(" ", "-")) or "",
                            "name": med_name,
                            "times": [self._clean_text(t) for t in times if self._clean_text(t)],
                            "dosage": self._clean_text(item.get("dosage") or ""),
                            "servo_channel": self._parse_servo_channel(item.get("servo_channel"), default=servo_channel),
                            "active": bool(item.get("active", True)),
                            "meal_relation": self._clean_text(item.get("meal_relation")),
                            "warning_tags": [
                                self._clean_text(tag)
                                for tag in (item.get("warning_tags") or [])
                                if self._clean_text(tag)
                            ][:6],
                        }
                    )
                    if len(medications) >= 4:
                        break

            schedule_times: list[str] = []
            if isinstance(raw_schedule_times, list):
                schedule_times = [self._clean_text(t) for t in raw_schedule_times if self._clean_text(t)]

            if not medication and medications:
                medication = self._clean_text(medications[0].get("name"))
            if not dosage and medications:
                dosage = self._clean_text(medications[0].get("dosage")) or dosage
            if not schedule_times and medications:
                first_times = medications[0].get("times")
                if isinstance(first_times, list):
                    schedule_times = [self._clean_text(t) for t in first_times if self._clean_text(t)]

            if medications:
                channels_seen: set[int] = set()
                for med in medications:
                    if not med.get("active", True):
                        continue
                    ch = self._parse_servo_channel(med.get("servo_channel"), default=1)
                    if ch in channels_seen:
                        return self._response(
                            False,
                            "Each active medication must use a unique servo channel (1-4).",
                        )
                    channels_seen.add(ch)
                if len(medications) > 4:
                    return self._response(False, "This prototype supports at most 4 medications per profile.")

            if not name:
                return self._response(False, "Name is required for registration.")
            if not medication:
                return self._response(False, "Medication field is required.")
            if not isinstance(photo_data_url, str) or not photo_data_url:
                return self._response(
                    False,
                    "A captured face photo is required. Capture or upload an image first.",
                )

            existing_profile = self._find_existing_user_profile_by_name(name)
            is_overwrite = bool(existing_profile)
            existing_user_id = self._safe_user_id((existing_profile or {}).get("id", "")) if existing_profile else ""
            user_id = existing_user_id or self._build_user_id(name)
            try:
                face_file = self._save_face_photo(user_id, photo_data_url)
            except ValueError as exc:
                return self._response(False, str(exc))

            now_iso = self._now().isoformat()
            profile = {
                "id": user_id,
                "name": name,
                "age": age,
                "language": language,
                "timezone": user_timezone or self._default_timezone_name(),
                "medication": medication,
                "dosage": dosage,
                "servo_channel": servo_channel,
                "notes": notes,
                "image_path": str(face_file.relative_to(self._base_dir)),
                "created_at": str((existing_profile or {}).get("created_at", "")).strip() or now_iso,
                "updated_at": now_iso,
            }
            if medications:
                profile["medications"] = medications
            if schedule_times:
                profile["schedule_times"] = schedule_times
            self._save_user_profile(profile)
            self._try_attach_pending_realsense_embedding(user_id)

            self._active_user_id = user_id
            self._active_user_profile = profile
            self._ensure_session_context()
            self._session_context["user_id"] = user_id
            self._session_context["registration"] = {
                "source": "touchscreen_ui",
                "overwrite": is_overwrite,
                "servo_channel": servo_channel,
                "medication": medication,
                "dosage": dosage,
            }
            self._transition(
                WorkflowState.REGISTRATION_SUCCESS,
                (f"Updated existing user profile for {name}." if is_overwrite else f"Registered new user {name}."),
            )
            self._auto_return_at = self._now() + timedelta(
                seconds=self._success_display_seconds
            )
            self._finalize_session_record(
                result="REGISTRATION_SUCCESS",
                note=(f"Updated existing user {user_id} by same-name overwrite." if is_overwrite else f"Registered new user {user_id}."),
            )
            return self._response(
                True,
                ("Profile updated (same-name overwrite). Returning to start screen shortly." if is_overwrite
                 else "Registration successful. Returning to start screen shortly."),
            )

    def stop_advice(self) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            if self._state != WorkflowState.SPEAKING_ADVICE:
                return self._response(
                    False,
                    "Advice can only be stopped while SPEAKING_ADVICE is active.",
                )

            self._stop_speaking()
            self._is_speaking = False
            self._speech_ends_at = None
            self._transition(
                WorkflowState.SESSION_SUCCESS,
                "Advice stopped by user. Session complete.",
            )
            self._auto_return_at = self._now() + timedelta(
                seconds=self._success_display_seconds
            )
            self._finalize_session_record(
                result="SESSION_SUCCESS",
                note="Advice stopped by user.",
            )
            return self._response(
                True,
                "Advice stopped. Session complete. Returning to start screen shortly.",
            )

    def manual_override_dispense(self, payload: dict[str, Any] | None = None) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            payload = payload if isinstance(payload, dict) else {}
            profile = self._active_user_profile or self._resolve_profile_for_api(payload.get("user_id"))
            if not profile:
                return self._response(False, "No active user profile is available for manual override.")

            # Allow override during/after recognition flow as long as the session has not been fully reset.
            if self._state == WorkflowState.WAITING_FOR_USER:
                return self._response(False, "Manual override is only available during an active session.")

            mode = self._clean_text(payload.get("mode")).lower() or "all_active"
            requested_channels = payload.get("channels")
            channels: list[int] = []
            if isinstance(requested_channels, list):
                for raw in requested_channels[:4]:
                    channels.append(self._parse_servo_channel(raw, default=1))

            if not self._dispense_pill(profile, override=True, override_mode=mode, override_channels=channels):
                return self._to_error("Manual override dispense failed.")

            self._append_dispense_log(
                user_id=str(profile.get("id", "")),
                medication=str(profile.get("medication", "")),
                result="SUCCESS",
                details=f"manual_override uart={self._uart_transport} status={self._last_uart_result.get('status', 'UNKNOWN')}",
            )
            self._manual_override_available = False
            return self._response(True, "Manual override dispense executed.")

    def reset(self) -> dict:
        with self._lock:
            if self._session_context:
                self._finalize_session_record(
                    result="MANUAL_RESET",
                    note="User/operator reset the workflow.",
                )
            self._clear_runtime_context(clear_error=True)
            self._transition(WorkflowState.WAITING_FOR_USER, "Manual reset.")
            return self._response(True, "Reset to initial start screen.")

    def record_dispense(self, payload: dict[str, Any]) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            profile = self._resolve_profile_for_api(payload.get("user_id"))
            if not profile:
                return self._response(False, "User profile not found for dispense logging.")

            medication = self._clean_text(payload.get("medication")) or str(
                profile.get("medication", "")
            )
            result = self._clean_text(payload.get("result")) or "SUCCESS"
            details = self._clean_text(payload.get("details")) or "manual dispense endpoint"

            self._append_dispense_log(
                user_id=str(profile.get("id", "")),
                medication=medication,
                result=result,
                details=details,
            )
            return self._response(True, "Dispense event logged.")

    def get_advice_payload(self, payload: dict[str, Any]) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            profile = self._resolve_profile_for_api(payload.get("user_id"))
            if not profile:
                return self._response(False, "User profile not found for advice generation.")

            advice_profile = self._build_advice_profile_context(profile)
            advice_payload = generate_advice_payload(
                advice_profile,
                fallback_builder=self._build_local_advice_payload,
            )
            self._last_advice_payload = advice_payload if isinstance(advice_payload, dict) else {}
            self._ensure_session_context()
            self._session_context["advice"] = {
                "source": str(self._last_advice_payload.get("source", "unknown")),
                "model": str(self._last_advice_payload.get("model", "")),
                "side_effects": list(self._last_advice_payload.get("side_effects", []) or []),
                "environment_summary": dict(self._last_advice_payload.get("environment_summary", {}) or {}),
                "schedule_summary": dict(self._last_advice_payload.get("schedule_summary", {}) or {}),
            }
            response = self._response(True, "Advice payload generated.")
            response["advice_payload"] = advice_payload
            return response

    # Integration placeholders
    def _dispense_pill(
        self,
        profile: dict[str, Any],
        *,
        override: bool = False,
        override_mode: str = "all_active",
        override_channels: list[int] | None = None,
    ) -> bool:
        user_id = str(profile.get("id", self._active_user_id))
        request_id = f"disp-{self._now().strftime('%Y%m%d%H%M%S')}"
        dispense_plan = self._build_dispense_plan(
            profile,
            override=override,
            override_mode=override_mode,
            override_channels=override_channels or [],
        )
        self._last_dispense_plan = dispense_plan
        self._manual_override_available = bool(dispense_plan.get("manual_override_available", False))

        self._ensure_session_context()
        self._session_context["user_id"] = user_id
        self._session_context["dispense_payload"] = dict(dispense_plan)

        if not dispense_plan.get("should_dispense", False):
            status = str(dispense_plan.get("status", "NO_DUE")).upper()
            self._last_uart_command = {
                "cmd": "DISPENSE",
                "request_id": request_id,
                "user_id": user_id,
                "skipped": True,
                "reason": status,
                "transport": self._uart_transport,
                "port": self._uart_port,
                "baud": self._uart_baud,
                "protocol": self._uart_protocol,
                "dispense_plan": dispense_plan,
            }
            self._last_uart_result = {
                "ack": True,
                "status": status,
                "hardware_online": False,
                "degraded": False,
                "message": str(dispense_plan.get("message", "No medication due now.")),
                "transport": self._uart_transport,
                "port": self._uart_port,
                "baud": self._uart_baud,
                "protocol": self._uart_protocol,
                "channel_counts": list(dispense_plan.get("channel_counts", [0, 0, 0, 0])),
                "power_domain": self._motor_power,
            }
            self._session_context["uart_ack"] = dict(self._last_uart_result)
            return True

        channel_counts = list(dispense_plan.get("channel_counts", [0, 0, 0, 0]))
        frame = self._build_uart_dispense_frame_from_channel_counts(channel_counts)
        command = {
            "cmd": "DISPENSE",
            "request_id": request_id,
            "user_id": user_id,
            "channel": int(dispense_plan.get("primary_channel", 1) or 1),
            "dose": str(dispense_plan.get("primary_dose", "1 unit")),
            "dose_count": int(dispense_plan.get("total_actions", 1) or 1),
            "medication": str(dispense_plan.get("summary_medications_text", profile.get("medication", "unknown_medication"))),
            "transport": self._uart_transport,
            "port": self._uart_port,
            "baud": self._uart_baud,
            "frame_format": "SAURON_UART_V1",
            "channel_counts": channel_counts,
            "frame_hex": frame["frame_hex"],
            "frame_bytes": frame["frame_bytes"],
            "dispense_plan": dispense_plan,
        }
        self._last_uart_command = command

        plan_for_session = dict(dispense_plan)
        plan_for_session.update(
            {
                "request_id": request_id,
                "transport": self._uart_transport,
                "protocol": self._uart_protocol,
                "frame_format": "SAURON_UART_V1",
                "frame_hex": frame["frame_hex"],
            }
        )
        self._session_context["dispense_payload"] = plan_for_session

        response = self._send_uart_dispense_command(command)
        self._last_uart_result = response
        self._session_context["uart_ack"] = dict(response)
        return bool(response.get("ack", False))

    def _generate_health_advice(self, profile: dict[str, Any]) -> str:
        advice_profile = self._build_advice_profile_context(profile)
        payload = generate_advice_payload(
            advice_profile,
            fallback_builder=self._build_local_advice_payload,
        )
        self._last_advice_payload = payload if isinstance(payload, dict) else {}
        self._ensure_session_context()
        self._session_context["advice"] = {
            "source": str(self._last_advice_payload.get("source", "unknown")),
            "model": str(self._last_advice_payload.get("model", "")),
            "side_effects": list(self._last_advice_payload.get("side_effects", []) or []),
            "environment_summary": dict(self._last_advice_payload.get("environment_summary", {}) or {}),
            "schedule_summary": dict(self._last_advice_payload.get("schedule_summary", {}) or {}),
        }
        name = str(profile.get("name", "there"))
        medication = payload.get("medication", "your medication")
        effects = ", ".join(payload.get("side_effects", []))
        advice = payload.get("advice", "")
        return (
            f"Hi {name}. You just received {medication}. "
            f"Common side effects: {effects}. {advice}"
        )

    def _compose_advice_speech_text(self) -> str:
        payload = self._last_advice_payload if isinstance(self._last_advice_payload, dict) else {}
        active = self._active_user_profile if isinstance(self._active_user_profile, dict) else {}
        name = str(active.get("name", "")).strip()
        medication = str(payload.get("medication", active.get("medication", ""))).strip()
        side_effects = payload.get("side_effects") if isinstance(payload.get("side_effects"), list) else []
        schedule_guidance = payload.get("schedule_guidance") if isinstance(payload.get("schedule_guidance"), list) else []
        environment_guidance = payload.get("environment_guidance") if isinstance(payload.get("environment_guidance"), list) else []
        advice = str(payload.get("advice", self._advice_text)).strip()

        parts: list[str] = []
        if name:
            parts.append(f"Hello {name}.")
        if medication:
            parts.append(f"You just received {medication}.")
        normalized_effects = [self._clean_text(x) for x in side_effects if self._clean_text(x)]
        if normalized_effects:
            parts.append(f"Common side effects may include {', '.join(normalized_effects[:3])}.")
        if advice:
            parts.append(advice)
        normalized_schedule = [self._clean_text(x) for x in schedule_guidance if self._clean_text(x)]
        if normalized_schedule:
            parts.append("Timing reminder: " + " ".join(normalized_schedule[:3]))
        normalized_env = [self._clean_text(x) for x in environment_guidance if self._clean_text(x)]
        if normalized_env:
            parts.append("Today: " + " ".join(normalized_env[:3]))
        return self._clean_text(" ".join(parts)) or self._clean_text(self._advice_text)

    def _estimate_advice_speech_seconds(self) -> int:
        text = self._compose_advice_speech_text()
        if not text:
            return max(6, int(self._speech_duration_seconds))
        words = len([w for w in re.split(r"\s+", text) if w])
        # Conservative speech estimate to avoid server-side timeout beating browser TTS.
        estimated = int((words / 2.2) + 3)
        return max(int(self._speech_duration_seconds), min(estimated, 90))

    def _build_advice_profile_context(self, profile: dict[str, Any]) -> dict[str, Any]:
        out = dict(profile or {})
        meds = self._normalize_profile_medications(profile or {})
        out["medications"] = meds
        schedule_ctx = self._build_schedule_context(profile or {})
        out["schedule_context"] = schedule_ctx
        out["schedule_times"] = out.get("schedule_times") or [m.get("matched_time") or "" for m in schedule_ctx.get("due_now", [])]
        if self._last_dispense_plan:
            out["dispense_plan"] = dict(self._last_dispense_plan)
        return out

    def _speak_advice(self, advice_text: str) -> bool:
        # TODO: pass advice_text into speaker/TTS module.
        _ = advice_text
        return True

    def _stop_speaking(self) -> None:
        # TODO: stop speaker/TTS playback module.
        return

    # Internal helpers
    def _send_uart_dispense_command(self, command: dict[str, Any]) -> dict[str, Any]:
        base = {
            "ack": False,
            "request_id": command.get("request_id", ""),
            "status": "UNKNOWN",
            "frame_format": command.get("frame_format", "SAURON_UART_V1"),
            "channel_counts": command.get("channel_counts", []),
            "dose_count": command.get("dose_count", 1),
            "frame_hex": command.get("frame_hex", ""),
            "transport": self._uart_transport,
            "port": self._uart_port,
            "baud": self._uart_baud,
            "power_domain": self._motor_power,
            "protocol": self._uart_protocol,
            "hardware_online": False,
            "degraded": False,
        }

        if not self._uart_serial_enabled:
            base.update(
                {
                    "ack": True,
                    "status": "SIMULATED_DISABLED",
                    "degraded": True,
                    "message": "UART serial transport disabled by UART_SERIAL_ENABLED=0",
                }
            )
            return base

        if serial is None:
            if self._uart_offline_fallback:
                base.update(
                    {
                        "ack": True,
                        "status": "SIMULATED_OFFLINE",
                        "degraded": True,
                        "message": "pyserial not available; hardware offline fallback enabled.",
                    }
                )
                return base
            base.update({"status": "SERIAL_MODULE_MISSING", "message": "pyserial is not installed."})
            return base

        try:
            response = self._send_uart_via_serial(command)
            if isinstance(response, dict):
                if not bool(response.get("ack", False)) and self._uart_offline_fallback:
                    merged_fallback = dict(base)
                    merged_fallback.update(
                        {
                            "ack": True,
                            "status": "SIMULATED_OFFLINE",
                            "degraded": True,
                            "hardware_online": False,
                            "message": str(response.get("message", "")).strip()
                            or "UART ACK timeout/error; simulated dispense used.",
                            "uart_attempt": response,
                        }
                    )
                    return merged_fallback
                merged = dict(base)
                merged.update(response)
                return merged
        except Exception as exc:
            if self._uart_offline_fallback:
                base.update(
                    {
                        "ack": True,
                        "status": "SIMULATED_OFFLINE",
                        "degraded": True,
                        "message": f"UART unavailable ({type(exc).__name__}); simulated dispense used.",
                    }
                )
                return base
            base.update(
                {
                    "status": "UART_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
            return base

        if self._uart_offline_fallback:
            base.update(
                {
                    "ack": True,
                    "status": "SIMULATED_OFFLINE",
                    "degraded": True,
                    "message": "Empty UART response; simulated dispense used.",
                }
            )
            return base
        base.update({"status": "NO_UART_RESPONSE", "message": "UART returned no response."})
        return base

    def _send_uart_via_serial(self, command: dict[str, Any]) -> dict[str, Any]:
        if serial is None:
            raise RuntimeError("pyserial unavailable")

        proto = (self._uart_protocol or "json").strip().lower()
        timeout_s = max(0.5, float(self._uart_timeout_s))
        channel_counts = command.get("channel_counts", [0, 0, 0, 0])
        if not isinstance(channel_counts, list):
            channel_counts = [0, 0, 0, 0]

        with serial.Serial(self._uart_port, self._uart_baud, timeout=timeout_s) as ser:  # type: ignore[attr-defined]
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass

            if proto == "frame":
                frame_bytes = command.get("frame_bytes")
                if not isinstance(frame_bytes, list) or not frame_bytes:
                    raise ValueError("Missing frame_bytes for UART frame protocol.")
                ser.write(bytes(int(b) & 0xFF for b in frame_bytes))
            else:
                payload = {
                    "pill1": int(channel_counts[0] or 0),
                    "pill2": int(channel_counts[1] or 0),
                    "pill3": int(channel_counts[2] or 0),
                    "pill4": int(channel_counts[3] or 0),
                }
                ser.write((json.dumps(payload) + "\n").encode("utf-8"))

            ser.flush()
            raw = ser.readline()
            if not raw:
                return {
                    "ack": False,
                    "status": "TIMEOUT",
                    "message": f"No ACK within {timeout_s:.1f}s",
                    "hardware_online": False,
                }

            text = raw.decode("utf-8", errors="replace").strip()
            parsed: dict[str, Any] = {}
            if text.startswith("{") and text.endswith("}"):
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    obj = {}
                if isinstance(obj, dict):
                    parsed = obj

            ack_status = str(parsed.get("status", text or "ACK")).strip()
            ack_ok = ack_status.lower() in {"done", "ok", "success", "ack"} or bool(parsed)

            return {
                "ack": bool(ack_ok),
                "status": ack_status or "ACK",
                "raw_ack": text,
                "protocol": proto,
                "hardware_online": True,
                "degraded": False,
                "ack_payload": parsed,
                "ack_counts": parsed.get("counts") if isinstance(parsed.get("counts"), list) else [],
            }

    def _phase_for_state(self, state: WorkflowState) -> str:
        if state == WorkflowState.WAITING_FOR_USER:
            return "IDLE"
        if state in {
            WorkflowState.MONITORING_DISTANCE,
            WorkflowState.FACE_RECOGNITION,
            WorkflowState.REGISTER_NEW_USER,
        }:
            return "AUTHENTICATION"
        if state == WorkflowState.DISPENSING_PILL:
            return "DISPENSING"
        if state in {
            WorkflowState.GENERATING_ADVICE,
            WorkflowState.SPEAKING_ADVICE,
            WorkflowState.SESSION_SUCCESS,
            WorkflowState.REGISTRATION_SUCCESS,
        }:
            return "ADVICE_COMPLETION"
        return "FAULT"

    def _parse_servo_channel(self, value: Any, default: int) -> int:
        try:
            channel = int(value)
        except (TypeError, ValueError):
            return default
        if channel < 1:
            return 1
        if channel > 4:
            return 4
        return channel

    def _parse_dose_count(self, value: Any) -> int:
        text = self._clean_text(value)
        match = re.search(r"(\d+)", text)
        if not match:
            return 1
        try:
            count = int(match.group(1))
        except (TypeError, ValueError):
            return 1
        return max(1, min(20, count))

    def _build_uart_dispense_frame(self, *, channel: int, dose_count: int) -> dict[str, Any]:
        """
        Placeholder UART frame contract for ESP32 firmware integration.
        The frame carries counts for all 4 channels; ESP32 executes count per channel.

        Byte layout (SAURON_UART_V1):
          [0] 0xAA                start
          [1] 0x01                version
          [2] ch1_count
          [3] ch2_count
          [4] ch3_count
          [5] ch4_count
          [6] checksum            sum(bytes[1:6]) & 0xFF
          [7] 0x55                end
        """
        ch = self._parse_servo_channel(channel, default=1)
        count = max(1, min(20, int(dose_count or 1)))
        channel_counts = [0, 0, 0, 0]
        channel_counts[ch - 1] = count
        return self._build_uart_dispense_frame_from_channel_counts(channel_counts)

    def _build_uart_dispense_frame_from_channel_counts(self, channel_counts: list[int]) -> dict[str, Any]:
        counts = [0, 0, 0, 0]
        if isinstance(channel_counts, list):
            for idx in range(min(4, len(channel_counts))):
                try:
                    counts[idx] = max(0, min(20, int(channel_counts[idx] or 0)))
                except (TypeError, ValueError):
                    counts[idx] = 0
        frame_body = [0x01, *counts]
        checksum = sum(frame_body) & 0xFF
        frame_bytes = [0xAA, *frame_body, checksum, 0x55]
        frame_hex = " ".join(f"{b:02X}" for b in frame_bytes)
        return {
            "channel_counts": counts,
            "checksum": checksum,
            "frame_bytes": frame_bytes,
            "frame_hex": frame_hex,
        }

    def _default_timezone_name(self) -> str:
        try:
            tzname = datetime.now().astimezone().tzinfo
            key = getattr(tzname, "key", None)
            if isinstance(key, str) and key.strip():
                return key.strip()
        except Exception:
            pass
        # Fallback for Windows/system tz labels that are not IANA.
        return "America/New_York"

    def _now_for_profile(self, profile: dict[str, Any]) -> datetime:
        tz_name = self._clean_text(profile.get("timezone"))
        if tz_name:
            try:
                return datetime.now(ZoneInfo(tz_name))
            except Exception:
                pass
        # Fall back to local system timezone if profile timezone is missing/invalid.
        try:
            return datetime.now().astimezone()
        except Exception:
            return self._now()

    def _normalize_profile_medications(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        meds: list[dict[str, Any]] = []
        raw = profile.get("medications")
        if isinstance(raw, list):
            for idx, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                name = self._clean_text(item.get("name"))
                if not name:
                    continue
                times = item.get("times")
                if not isinstance(times, list):
                    times = []
                warning_tags_raw = item.get("warning_tags")
                if not isinstance(warning_tags_raw, list):
                    warning_tags_raw = []
                meds.append(
                    {
                        "id": self._safe_user_id(item.get("id", "")) or f"med-{idx+1}",
                        "name": name,
                        "dosage": self._clean_text(item.get("dosage")) or self._clean_text(profile.get("dosage")) or "1 unit",
                        "servo_channel": self._parse_servo_channel(item.get("servo_channel"), default=self._parse_servo_channel(profile.get("servo_channel"), default=(idx + 1))),
                        "times": [self._clean_text(t) for t in times if self._clean_text(t)],
                        "active": bool(item.get("active", True)),
                        "meal_relation": self._clean_text(item.get("meal_relation")),
                        "warning_tags": [self._clean_text(t) for t in warning_tags_raw if self._clean_text(t)][:6],
                    }
                )
                if len(meds) >= 4:
                    break
        if meds:
            return meds
        # Backward compatibility: synthesize a single-med list.
        name = self._clean_text(profile.get("medication"))
        if not name:
            return []
        times = profile.get("schedule_times")
        if not isinstance(times, list):
            times = []
        return [
            {
                "id": "med-1",
                "name": name,
                "dosage": self._clean_text(profile.get("dosage")) or "1 unit",
                "servo_channel": self._parse_servo_channel(profile.get("servo_channel"), default=1),
                "times": [self._clean_text(t) for t in times if self._clean_text(t)],
                "active": True,
                "meal_relation": "",
                "warning_tags": [],
            }
        ]

    def _parse_time_hhmm(self, value: str) -> tuple[int, int] | None:
        text = self._clean_text(value)
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return (hh, mm)

    def _build_schedule_context(self, profile: dict[str, Any]) -> dict[str, Any]:
        local_now = self._now_for_profile(profile)
        now_minutes = local_now.hour * 60 + local_now.minute
        due_window_min = 30
        upcoming_window_min = 120

        meds = self._normalize_profile_medications(profile)
        due_now: list[dict[str, Any]] = []
        upcoming: list[dict[str, Any]] = []
        all_active: list[dict[str, Any]] = []

        for med in meds:
            if not med.get("active", True):
                continue
            all_active.append(med)
            matched_due = False
            best_upcoming_delta: int | None = None
            best_upcoming_time = ""
            for raw_t in med.get("times", []):
                parsed = self._parse_time_hhmm(str(raw_t))
                if not parsed:
                    continue
                hh, mm = parsed
                target_min = hh * 60 + mm
                diff = target_min - now_minutes
                if abs(diff) <= due_window_min:
                    item = dict(med)
                    item["matched_time"] = f"{hh:02d}:{mm:02d}"
                    item["minutes_delta"] = diff
                    due_now.append(item)
                    matched_due = True
                    break
                if 0 < diff <= upcoming_window_min:
                    if best_upcoming_delta is None or diff < best_upcoming_delta:
                        best_upcoming_delta = diff
                        best_upcoming_time = f"{hh:02d}:{mm:02d}"
            if (not matched_due) and best_upcoming_delta is not None:
                item = dict(med)
                item["matched_time"] = best_upcoming_time
                item["minutes_delta"] = best_upcoming_delta
                upcoming.append(item)

        due_now.sort(key=lambda x: (int(x.get("servo_channel", 99)), str(x.get("name", ""))))
        upcoming.sort(key=lambda x: (int(x.get("minutes_delta", 9999)), int(x.get("servo_channel", 99))))
        return {
            "datetime_local": local_now.isoformat(),
            "timezone": self._clean_text(profile.get("timezone")) or self._default_timezone_name(),
            "due_now": due_now[:4],
            "upcoming": upcoming[:4],
            "all_active": all_active[:4],
        }

    def _build_dispense_plan(
        self,
        profile: dict[str, Any],
        *,
        override: bool,
        override_mode: str,
        override_channels: list[int],
    ) -> dict[str, Any]:
        schedule_ctx = self._build_schedule_context(profile)
        due_now = list(schedule_ctx.get("due_now", []))
        upcoming = list(schedule_ctx.get("upcoming", []))
        all_active = list(schedule_ctx.get("all_active", []))
        selected: list[dict[str, Any]] = []
        reason = "scheduled_due_now"
        mode = (override_mode or "all_active").strip().lower()

        if due_now and not override:
            selected = due_now
        elif override:
            reason = "manual_override"
            if override_channels:
                channel_set = {self._parse_servo_channel(ch, default=1) for ch in override_channels}
                selected = [m for m in all_active if self._parse_servo_channel(m.get("servo_channel"), default=1) in channel_set]
            elif mode in {"primary", "due_or_primary"}:
                selected = due_now[:1] if due_now else all_active[:1]
            else:  # all_active / default
                selected = all_active or due_now
        else:
            selected = []

        channel_counts = [0, 0, 0, 0]
        plan_items: list[dict[str, Any]] = []
        for med in selected[:4]:
            ch = self._parse_servo_channel(med.get("servo_channel"), default=1)
            dose_text = self._clean_text(med.get("dosage")) or "1 unit"
            dose_count = self._parse_dose_count(dose_text)
            channel_counts[ch - 1] += dose_count
            plan_items.append(
                {
                    "med_id": self._safe_user_id(med.get("id", "")) or "",
                    "name": self._clean_text(med.get("name")),
                    "dosage": dose_text,
                    "dose_count": dose_count,
                    "servo_channel": ch,
                    "matched_time": self._clean_text(med.get("matched_time")),
                    "minutes_delta": med.get("minutes_delta"),
                }
            )

        total_actions = sum(channel_counts)
        summary_meds = [str(i.get("name", "")) for i in plan_items if str(i.get("name", "")).strip()]
        primary = plan_items[0] if plan_items else {}
        should_dispense = total_actions > 0
        status = "READY" if should_dispense else "NO_DUE"
        message = "Dispense plan ready."
        manual_override_available = not should_dispense
        if not should_dispense:
            message = "No medication due right now. Manual override is available."

        return {
            "status": status,
            "message": message,
            "should_dispense": should_dispense,
            "reason": reason,
            "manual_override_available": manual_override_available,
            "channel_counts": channel_counts,
            "total_actions": total_actions,
            "items": plan_items,
            "primary_channel": int(primary.get("servo_channel", 1) or 1),
            "primary_dose": str(primary.get("dosage", "1 unit") or "1 unit"),
            "summary_medications_text": ", ".join(summary_meds) if summary_meds else "no_medication_due",
            "summary_medications": summary_meds,
            "schedule_context": {
                "datetime_local": schedule_ctx.get("datetime_local"),
                "timezone": schedule_ctx.get("timezone"),
                "due_now": [
                    {
                        "name": m.get("name"),
                        "servo_channel": m.get("servo_channel"),
                        "matched_time": m.get("matched_time"),
                        "minutes_delta": m.get("minutes_delta"),
                    }
                    for m in due_now
                ],
                "upcoming": [
                    {
                        "name": m.get("name"),
                        "servo_channel": m.get("servo_channel"),
                        "matched_time": m.get("matched_time"),
                        "minutes_delta": m.get("minutes_delta"),
                    }
                    for m in upcoming
                ],
            },
        }

    def _resolve_profile_for_api(self, user_id: Any) -> dict[str, Any] | None:
        safe_user_id = self._safe_user_id(str(user_id or ""))
        if safe_user_id:
            profile = self._load_user_profile(safe_user_id)
            if not profile:
                return None
            preferred = self._find_existing_user_profile_by_name(str(profile.get("name", "")))
            if preferred:
                return preferred
            return profile
        if self._active_user_profile:
            preferred = self._find_existing_user_profile_by_name(str(self._active_user_profile.get("name", "")))
            if preferred:
                return preferred
            return self._active_user_profile
        known = self._list_known_users()
        if not known:
            return None
        return self._load_user_profile(known[0]["id"])

    def _build_local_advice_payload(self, profile: dict[str, Any]) -> dict[str, Any]:
        medication = str(profile.get("medication", "your medication")).strip()
        med_lower = medication.lower()
        schedule_ctx = profile.get("schedule_context") if isinstance(profile.get("schedule_context"), dict) else {}
        due_now = schedule_ctx.get("due_now") if isinstance(schedule_ctx.get("due_now"), list) else []
        upcoming = schedule_ctx.get("upcoming") if isinstance(schedule_ctx.get("upcoming"), list) else []

        side_effects = ["drowsiness", "stomach discomfort", "mild headache"]
        advice = "Drink more water and avoid intense activity if you feel unwell."
        schedule_guidance: list[str] = []
        environment_guidance: list[str] = []

        if "ibuprofen" in med_lower:
            side_effects = ["stomach discomfort", "nausea", "dizziness"]
            advice = "Take with food and avoid alcohol today."
        elif "loratadine" in med_lower:
            side_effects = ["dry mouth", "mild drowsiness", "headache"]
            advice = "Avoid driving if you feel sleepy and stay hydrated."
        elif "amoxicillin" in med_lower:
            side_effects = ["stomach upset", "diarrhea", "skin rash"]
            advice = "Finish the full course and contact a doctor if rash worsens."

        if due_now:
            names = [str(m.get("name", "")).strip() for m in due_now if str(m.get("name", "")).strip()]
            if names:
                schedule_guidance.append(f"Due now: {', '.join(names[:4])}.")
        else:
            schedule_guidance.append("No medication is due right now. Use manual override only if needed.")
        if upcoming:
            nxt = upcoming[0] if isinstance(upcoming[0], dict) else {}
            nxt_name = str(nxt.get("name", "medication")).strip() or "medication"
            nxt_time = str(nxt.get("matched_time", "")).strip() or "later"
            schedule_guidance.append(f"Next scheduled dose: {nxt_name} at {nxt_time}.")

        return {
            "medication": medication,
            "side_effects": side_effects[:3],
            "advice": advice,
            "schedule_guidance": schedule_guidance[:3],
            "environment_guidance": environment_guidance[:3],
            "source": "local_rule_engine",
        }

    def _append_dispense_log(
        self, user_id: str, medication: str, result: str, details: str
    ) -> None:
        entry = {
            "timestamp": self._now().isoformat(),
            "user_id": self._safe_user_id(user_id),
            "medication": self._clean_text(medication),
            "result": self._clean_text(result).upper(),
            "details": self._clean_text(details),
        }
        if not entry["user_id"]:
            return
        serialized = json.dumps(entry, ensure_ascii=True)
        with self._dispense_log_file.open("a", encoding="utf-8") as fh:
            fh.write(serialized + "\n")

    def _try_attach_pending_realsense_embedding(self, user_id: str) -> None:
        path = self._pending_realsense_embedding_file
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            return
        try:
            self._shared_store.save_embedding(
                user_id,
                [float(v) for v in embedding],
                model=str(payload.get("model", "insightface_arcface")),
                source="realsense_pending_registration",
            )
            try:
                path.unlink()
            except OSError:
                pass
        except (TypeError, ValueError):
            return

    def _to_error(self, message: str) -> dict:
        self._last_error = message
        self._is_speaking = False
        self._speech_ends_at = None
        self._auto_return_at = None
        self._dispense_stage_ends_at = None
        self._advice_generation_ends_at = None
        self._finalize_session_record(result="ERROR", note=message)
        self._transition(WorkflowState.ERROR, message)
        return self._response(False, message)

    def _maybe_auto_progress(self) -> None:
        now = self._now()
        if self._state == WorkflowState.DISPENSING_PILL and self._dispense_stage_ends_at:
            if now >= self._dispense_stage_ends_at:
                self._dispense_stage_ends_at = None
                # Clear previous advice payload before entering the generation stage so the
                # frontend cannot briefly render stale advice from an earlier session.
                self._advice_text = ""
                self._last_advice_payload = {}
                self._ensure_session_context()
                self._session_context["advice"] = {}
                self._transition(
                    WorkflowState.GENERATING_ADVICE,
                    "Dispense completed. Preparing health advice.",
                )
                self._advice_generation_ends_at = now + timedelta(
                    seconds=self._advice_generation_seconds
                )

        if self._state == WorkflowState.GENERATING_ADVICE and self._advice_generation_ends_at:
            if now >= self._advice_generation_ends_at:
                self._advice_generation_ends_at = None
                profile = self._active_user_profile or {}
                self._advice_text = self._generate_health_advice(profile)
                self._is_speaking = self._speak_advice(self._advice_text)
                self._speech_ends_at = now + timedelta(
                    seconds=self._estimate_advice_speech_seconds()
                )
                self._transition(
                    WorkflowState.SPEAKING_ADVICE,
                    "Health advice ready and speaking has started.",
                )

        if self._state == WorkflowState.SPEAKING_ADVICE and self._speech_ends_at:
            if now >= self._speech_ends_at:
                self._is_speaking = False
                self._speech_ends_at = None
                self._transition(
                    WorkflowState.SESSION_SUCCESS,
                    "Advice playback finished. Session complete.",
                )
                self._auto_return_at = now + timedelta(
                    seconds=self._success_display_seconds
                )
                self._finalize_session_record(
                    result="SESSION_SUCCESS",
                    note="Advice playback completed.",
                )

        if self._state in {
            WorkflowState.REGISTRATION_SUCCESS,
            WorkflowState.SESSION_SUCCESS,
        } and self._auto_return_at:
            if now >= self._auto_return_at:
                self._clear_runtime_context(clear_error=True)
                self._transition(
                    WorkflowState.WAITING_FOR_USER,
                    "Returned to initial start screen.",
                )

    def _resolve_existing_user_id(self, user_id: str | None) -> str:
        candidate = self._safe_user_id(user_id or "")
        if candidate:
            return candidate
        known = self._list_known_users()
        if not known:
            return ""
        return known[0]["id"]

    def _save_user_profile(self, profile: dict[str, Any]) -> None:
        user_id = self._safe_user_id(profile.get("id", ""))
        if not user_id:
            raise ValueError("Invalid user id.")
        out_file = self._users_dir / f"{user_id}.json"
        out_file.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    def _load_user_profile(self, user_id: str) -> dict[str, Any] | None:
        safe_id = self._safe_user_id(user_id)
        if not safe_id:
            return None
        in_file = self._users_dir / f"{safe_id}.json"
        if not in_file.exists():
            return None
        try:
            data = json.loads(in_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _list_known_users(self) -> list[dict[str, str]]:
        users: list[dict[str, str]] = []
        for user_file in sorted(self._users_dir.glob("*.json")):
            try:
                data = json.loads(user_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            user_id = self._safe_user_id(str(data.get("id", user_file.stem)))
            if not user_id:
                continue
            users.append(
                {
                    "id": user_id,
                    "name": str(data.get("name", user_id)),
                    "medication": str(data.get("medication", "")),
                    "servo_channel": str(data.get("servo_channel", "")),
                }
            )
        return users

    def _canonical_name_key(self, value: Any) -> str:
        return self._clean_text(value).casefold()

    def _find_existing_user_profile_by_name(self, name: str) -> dict[str, Any] | None:
        target_key = self._canonical_name_key(name)
        if not target_key:
            return None

        best_profile: dict[str, Any] | None = None
        best_sort_key: tuple[str, float] = ("", -1.0)
        for user_file in self._users_dir.glob("*.json"):
            try:
                data = json.loads(user_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            if self._canonical_name_key(data.get("name", "")) != target_key:
                continue
            user_id = self._safe_user_id(str(data.get("id", user_file.stem)))
            if not user_id:
                continue
            sort_ts = str(data.get("updated_at") or data.get("created_at") or "")
            try:
                mtime = user_file.stat().st_mtime
            except OSError:
                mtime = -1.0
            candidate_key = (sort_ts, float(mtime))
            if best_profile is None or candidate_key > best_sort_key:
                data["id"] = user_id
                best_profile = data
                best_sort_key = candidate_key
        return best_profile

    def _save_face_photo(self, user_id: str, photo_data_url: str) -> Path:
        if "," not in photo_data_url:
            raise ValueError("Invalid image payload.")
        header, encoded = photo_data_url.split(",", 1)
        if "base64" not in header:
            raise ValueError("Image payload must be base64 encoded.")
        if not header.startswith("data:image/"):
            raise ValueError("Image payload must be an image.")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Could not decode image payload.") from exc
        if not image_bytes:
            raise ValueError("Image payload is empty.")

        out_file = self._faces_dir / f"{user_id}.jpg"
        out_file.write_bytes(image_bytes)
        return out_file

    def _build_user_id(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug:
            slug = "user"
        timestamp = self._now().strftime("%Y%m%d%H%M%S")
        return f"{slug}-{timestamp}"

    def _safe_user_id(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "", str(value)).strip()

    def _clean_text(self, value: Any) -> str:
        text = str(value or "").strip()
        return re.sub(r"\s+", " ", text)

    def _clear_runtime_context(self, clear_error: bool) -> None:
        self._current_distance_m = None
        self._active_user_id = ""
        self._active_user_profile = {}
        self._last_recognition = {}
        self._last_uart_command = {}
        self._last_uart_result = {}
        self._last_dispense_plan = {}
        self._advice_text = ""
        self._last_advice_payload = {}
        self._is_speaking = False
        self._speech_ends_at = None
        self._auto_return_at = None
        self._dispense_stage_ends_at = None
        self._advice_generation_ends_at = None
        self._session_context = {}
        self._manual_override_available = False
        if clear_error:
            self._last_error = ""

    def _transition(self, to_state: WorkflowState, note: str) -> None:
        from_state = self._state.value
        self._state = to_state
        self._record_event(from_state, to_state.value, note)

    def _record_event(self, from_state: str, to_state: str, note: str) -> None:
        event = {
            "timestamp": self._now().isoformat(),
            "from": from_state,
            "to": to_state,
            "note": note,
        }
        self._history.append(event)
        if self._session_context:
            timeline = self._session_context.setdefault("timeline", [])
            if isinstance(timeline, list):
                timeline.append(event)
                if len(timeline) > 50:
                    del timeline[:-50]

    def _start_session_context(self) -> None:
        now = self._now()
        self._session_context = {
            "session_id": f"sess-{now.strftime('%Y%m%d%H%M%S%f')}",
            "started_at": now.isoformat(),
            "finalized": False,
            "user_id": "",
            "recognition": {},
            "dispense_payload": {},
            "uart_ack": {},
            "advice": {},
            "timeline": [],
        }

    def _ensure_session_context(self) -> None:
        if not self._session_context:
            self._start_session_context()

    def _build_session_summary(self, *, result: str, note: str) -> dict[str, Any]:
        self._ensure_session_context()
        ctx = self._session_context if isinstance(self._session_context, dict) else {}
        recognition = ctx.get("recognition") if isinstance(ctx.get("recognition"), dict) else {}
        advice = ctx.get("advice") if isinstance(ctx.get("advice"), dict) else {}
        summary = {
            "timestamp": self._now().isoformat(),
            "session_id": str(ctx.get("session_id", "")),
            "started_at": str(ctx.get("started_at", "")),
            "ended_at": self._now().isoformat(),
            "result": self._clean_text(result),
            "note": self._clean_text(note),
            "user_id": self._safe_user_id(ctx.get("user_id", "")),
            "recognition_source": str(recognition.get("source", self._last_recognition.get("source", ""))),
            "recognition": recognition,
            "dispense_payload": ctx.get("dispense_payload", {}),
            "uart_ack": ctx.get("uart_ack", {}),
            "advice_source": str(advice.get("source", self._last_advice_payload.get("source", ""))),
            "advice": advice,
            "timeline": ctx.get("timeline", []),
        }
        return summary

    def _finalize_session_record(self, *, result: str, note: str) -> None:
        if not self._session_context:
            return
        if bool(self._session_context.get("finalized")):
            return
        summary = self._build_session_summary(result=result, note=note)
        self._last_session_summary = summary
        self._session_context["finalized"] = True
        try:
            with self._session_log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _seconds_until(self, when: datetime | None, now: datetime) -> int | None:
        if when is None:
            return None
        delta = int((when - now).total_seconds())
        return max(0, delta)

    def _snapshot(self) -> dict:
        now = self._now()
        active_user = None
        if self._active_user_profile:
            active_user = {
                "id": self._active_user_profile.get("id", self._active_user_id),
                "name": self._active_user_profile.get("name", ""),
                "medication": self._active_user_profile.get("medication", ""),
                "servo_channel": self._active_user_profile.get("servo_channel", ""),
            }
        return {
            "state": self._state.value,
            "phase": self._phase_for_state(self._state),
            "last_error": self._last_error,
            "distance_threshold_m": self._distance_threshold_m,
            "dispense_display_seconds_total": self._dispense_display_seconds,
            "advice_generation_seconds_total": self._advice_generation_seconds,
            "current_distance_m": self._current_distance_m,
            "active_user": active_user,
            "last_recognition": self._last_recognition,
            "uart_transport": self._uart_transport,
            "uart_port": self._uart_port,
            "uart_baud": self._uart_baud,
            "motor_power_domain": self._motor_power,
            "compute_node": self._compute_node,
            "camera_source": self._camera_source,
            "last_uart_command": self._last_uart_command,
            "last_uart_result": self._last_uart_result,
            "last_dispense_plan": self._last_dispense_plan,
            "advice_text": self._advice_text,
            "last_advice_payload": self._last_advice_payload,
            "is_speaking": self._is_speaking,
            "speech_seconds_remaining": self._seconds_until(self._speech_ends_at, now),
            "auto_return_seconds": self._seconds_until(self._auto_return_at, now),
            "dispense_seconds_remaining": self._seconds_until(self._dispense_stage_ends_at, now),
            "advice_generation_seconds_remaining": self._seconds_until(self._advice_generation_ends_at, now),
            "known_users": self._list_known_users(),
            "can_start_monitoring": self._state == WorkflowState.WAITING_FOR_USER,
            "can_submit_distance": self._state == WorkflowState.MONITORING_DISTANCE,
            "can_choose_recognition": self._state == WorkflowState.FACE_RECOGNITION,
            "can_register_user": self._state == WorkflowState.REGISTER_NEW_USER,
            "can_stop_advice": self._state == WorkflowState.SPEAKING_ADVICE,
            "manual_override_available": bool(self._manual_override_available),
            "can_reset": self._state != WorkflowState.WAITING_FOR_USER,
            "history": self._history[-30:],
            "session_context": self._session_context,
            "last_session_summary": self._last_session_summary,
            "hardware_degrade_mode": bool(self._uart_offline_fallback),
            "uart_protocol": self._uart_protocol,
            "uart_serial_enabled": bool(self._uart_serial_enabled),
        }

    def _response(self, ok: bool, message: str) -> dict:
        response = self._snapshot()
        response["ok"] = ok
        response["message"] = message
        return response

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

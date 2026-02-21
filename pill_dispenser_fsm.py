from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any


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
        distance_threshold_m: float = 1.2,
        success_display_seconds: int = 4,
        speech_duration_seconds: int = 12,
    ) -> None:
        self._lock = RLock()
        self._state = WorkflowState.WAITING_FOR_USER
        self._last_error = ""
        self._history: list[dict[str, str]] = []

        self._distance_threshold_m = distance_threshold_m
        self._success_display_seconds = success_display_seconds
        self._speech_duration_seconds = speech_duration_seconds

        self._current_distance_m: float | None = None
        self._active_user_id = ""
        self._active_user_profile: dict[str, Any] = {}
        self._advice_text = ""
        self._is_speaking = False
        self._speech_ends_at: datetime | None = None
        self._auto_return_at: datetime | None = None

        self._base_dir = Path(__file__).resolve().parent
        self._users_dir = self._base_dir / "data" / "users"
        self._faces_dir = self._base_dir / "data" / "faces"
        self._users_dir.mkdir(parents=True, exist_ok=True)
        self._faces_dir.mkdir(parents=True, exist_ok=True)

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
                    f"User reached {self._current_distance_m}m. Running face recognition.",
                )
                return self._response(
                    True,
                    "User is close enough. Choose whether this is a new or existing user.",
                )

            remaining = round(self._current_distance_m - self._distance_threshold_m, 2)
            return self._response(
                True,
                f"User detected at {self._current_distance_m}m. Move {remaining}m closer.",
            )

    def set_recognition_result(self, match_type: str, user_id: str | None = None) -> dict:
        with self._lock:
            self._maybe_auto_progress()
            if self._state != WorkflowState.FACE_RECOGNITION:
                return self._response(
                    False,
                    "Recognition selection is only valid in FACE_RECOGNITION state.",
                )

            normalized = (match_type or "").strip().lower()
            if normalized == "new":
                self._transition(
                    WorkflowState.REGISTER_NEW_USER,
                    "Face not found. Switching to new user registration.",
                )
                return self._response(
                    True,
                    "New user selected. Fill in details and capture a face photo.",
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

            self._active_user_id = resolved_user_id
            self._active_user_profile = profile
            self._transition(
                WorkflowState.DISPENSING_PILL,
                f"Recognized existing user: {profile.get('name', resolved_user_id)}.",
            )

            if not self._dispense_pill(profile):
                return self._to_error("Failed to dispense pill for existing user.")

            self._transition(
                WorkflowState.GENERATING_ADVICE,
                "Dispense completed. Requesting Gemini health advice.",
            )

            self._advice_text = self._generate_health_advice(profile)
            self._is_speaking = self._speak_advice(self._advice_text)
            self._speech_ends_at = self._now() + timedelta(
                seconds=self._speech_duration_seconds
            )

            self._transition(
                WorkflowState.SPEAKING_ADVICE,
                "Health advice ready and speaking has started.",
            )
            return self._response(
                True,
                "Existing user recognized, pill dispensed, and health advice speaking.",
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
            photo_data_url = payload.get("photo_data_url", "")

            if not name:
                return self._response(False, "Name is required for registration.")
            if not medication:
                return self._response(False, "Medication field is required.")
            if not isinstance(photo_data_url, str) or not photo_data_url:
                return self._response(
                    False,
                    "A captured face photo is required. Capture or upload an image first.",
                )

            user_id = self._build_user_id(name)
            try:
                face_file = self._save_face_photo(user_id, photo_data_url)
            except ValueError as exc:
                return self._response(False, str(exc))

            profile = {
                "id": user_id,
                "name": name,
                "age": age,
                "medication": medication,
                "dosage": dosage,
                "notes": notes,
                "image_path": str(face_file.relative_to(self._base_dir)),
                "created_at": self._now().isoformat(),
            }
            self._save_user_profile(profile)

            self._active_user_id = user_id
            self._active_user_profile = profile
            self._transition(
                WorkflowState.REGISTRATION_SUCCESS,
                f"Registered new user {name}.",
            )
            self._auto_return_at = self._now() + timedelta(
                seconds=self._success_display_seconds
            )
            return self._response(
                True,
                "Registration successful. Returning to start screen shortly.",
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
            return self._response(
                True,
                "Advice stopped. Session complete. Returning to start screen shortly.",
            )

    def reset(self) -> dict:
        with self._lock:
            self._clear_runtime_context(clear_error=True)
            self._transition(WorkflowState.WAITING_FOR_USER, "Manual reset.")
            return self._response(True, "Reset to initial start screen.")

    # Integration placeholders
    def _dispense_pill(self, profile: dict[str, Any]) -> bool:
        # TODO: call ESP32 and motor control module with this user's med info.
        _ = profile
        return True

    def _generate_health_advice(self, profile: dict[str, Any]) -> str:
        # TODO: call Gemini API with weather/context and patient details.
        medication = profile.get("medication", "your medication")
        name = profile.get("name", "there")
        return (
            f"Hi {name}. You just received {medication}. Stay hydrated today, "
            "avoid skipping meals, and rest if you feel dizzy."
        )

    def _speak_advice(self, advice_text: str) -> bool:
        # TODO: pass advice_text into speaker/TTS module.
        _ = advice_text
        return True

    def _stop_speaking(self) -> None:
        # TODO: stop speaker/TTS playback module.
        return

    # Internal helpers
    def _to_error(self, message: str) -> dict:
        self._last_error = message
        self._is_speaking = False
        self._speech_ends_at = None
        self._auto_return_at = None
        self._transition(WorkflowState.ERROR, message)
        return self._response(False, message)

    def _maybe_auto_progress(self) -> None:
        now = self._now()
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
                }
            )
        return users

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
        self._advice_text = ""
        self._is_speaking = False
        self._speech_ends_at = None
        self._auto_return_at = None
        if clear_error:
            self._last_error = ""

    def _transition(self, to_state: WorkflowState, note: str) -> None:
        from_state = self._state.value
        self._state = to_state
        self._record_event(from_state, to_state.value, note)

    def _record_event(self, from_state: str, to_state: str, note: str) -> None:
        self._history.append(
            {
                "timestamp": self._now().isoformat(),
                "from": from_state,
                "to": to_state,
                "note": note,
            }
        )

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
            }
        return {
            "state": self._state.value,
            "last_error": self._last_error,
            "distance_threshold_m": self._distance_threshold_m,
            "current_distance_m": self._current_distance_m,
            "active_user": active_user,
            "advice_text": self._advice_text,
            "is_speaking": self._is_speaking,
            "speech_seconds_remaining": self._seconds_until(self._speech_ends_at, now),
            "auto_return_seconds": self._seconds_until(self._auto_return_at, now),
            "known_users": self._list_known_users(),
            "can_start_monitoring": self._state == WorkflowState.WAITING_FOR_USER,
            "can_submit_distance": self._state == WorkflowState.MONITORING_DISTANCE,
            "can_choose_recognition": self._state == WorkflowState.FACE_RECOGNITION,
            "can_register_user": self._state == WorkflowState.REGISTER_NEW_USER,
            "can_stop_advice": self._state == WorkflowState.SPEAKING_ADVICE,
            "can_reset": self._state != WorkflowState.WAITING_FOR_USER,
            "history": self._history[-30:],
        }

    def _response(self, ok: bool, message: str) -> dict:
        response = self._snapshot()
        response["ok"] = ok
        response["message"] = message
        return response

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

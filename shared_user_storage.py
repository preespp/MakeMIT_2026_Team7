from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SharedUserStorage:
    """
    Canonical user storage shared by:
    - Flask FSM / touchscreen frontend (profiles + face photos)
    - RealSense local recognizer (profiles + embeddings)

    Canonical files:
      data/users/<user_id>.json
      data/faces/<user_id>.jpg          (optional for RealSense-only records)
      data/embeddings/<user_id>.json    (optional for frontend-only records)

    Legacy compatibility:
      data/users.json                   (old RealSense format)
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.data_dir = self.base_dir / "data"
        self.users_dir = self.data_dir / "users"
        self.faces_dir = self.data_dir / "faces"
        self.embeddings_dir = self.data_dir / "embeddings"
        self.logs_dir = self.data_dir / "logs"
        self.legacy_users_file = self.data_dir / "users.json"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.faces_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def safe_user_id(self, value: Any) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or "")).strip()

    def build_user_id(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
        if not slug:
            slug = "user"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{slug}-{ts}"

    def _profile_path(self, user_id: str) -> Path:
        return self.users_dir / f"{self.safe_user_id(user_id)}.json"

    def _embedding_path(self, user_id: str) -> Path:
        return self.embeddings_dir / f"{self.safe_user_id(user_id)}.json"

    def load_profile(self, user_id: str) -> dict[str, Any] | None:
        safe_id = self.safe_user_id(user_id)
        if not safe_id:
            return None
        path = self._profile_path(safe_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def save_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize_profile(profile)
        path = self._profile_path(normalized["id"])
        path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
        return normalized

    def list_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for user_file in sorted(self.users_dir.glob("*.json")):
            try:
                data = json.loads(user_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            try:
                profiles.append(self.normalize_profile(data))
            except ValueError:
                continue
        return profiles

    def normalize_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, dict):
            raise ValueError("Profile must be an object.")

        name = str(profile.get("name", "")).strip()
        if not name:
            raise ValueError("Profile name is required.")

        raw_id = self.safe_user_id(profile.get("id"))
        user_id = raw_id or self.build_user_id(name)

        medication = str(profile.get("medication", "")).strip()
        dosage = str(profile.get("dosage", "")).strip()
        age = str(profile.get("age", "")).strip()
        notes = str(profile.get("notes", "")).strip()

        try:
            servo_channel = int(profile.get("servo_channel", 1))
        except (TypeError, ValueError):
            servo_channel = 1
        servo_channel = min(4, max(1, servo_channel))

        medications = profile.get("medications")
        if not isinstance(medications, list):
            medications = []

        schedule_times = profile.get("schedule_times")
        if not isinstance(schedule_times, list):
            schedule_times = []

        face_image_path = str(profile.get("image_path", "")).strip()
        face_embedding_path = str(profile.get("face_embedding_path", "")).strip()
        created_at = str(profile.get("created_at", "")).strip() or self._now_iso()

        out: dict[str, Any] = {
            "id": user_id,
            "name": name,
            "age": age,
            "medication": medication,
            "dosage": dosage,
            "servo_channel": servo_channel,
            "notes": notes,
            "created_at": created_at,
        }
        if medications:
            out["medications"] = medications
        if schedule_times:
            out["schedule_times"] = [str(v).strip() for v in schedule_times if str(v).strip()]
        if face_image_path:
            out["image_path"] = face_image_path
        if face_embedding_path:
            out["face_embedding_path"] = face_embedding_path
        if "face_embedding_dim" in profile:
            try:
                out["face_embedding_dim"] = int(profile["face_embedding_dim"])
            except (TypeError, ValueError):
                pass
        if "face_embedding_model" in profile and str(profile["face_embedding_model"]).strip():
            out["face_embedding_model"] = str(profile["face_embedding_model"]).strip()
        if "legacy_source" in profile and str(profile["legacy_source"]).strip():
            out["legacy_source"] = str(profile["legacy_source"]).strip()
        return out

    def load_embedding(self, user_id: str) -> list[float] | None:
        safe_id = self.safe_user_id(user_id)
        if not safe_id:
            return None
        path = self._embedding_path(safe_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        emb = data.get("embedding")
        if not isinstance(emb, list):
            return None
        out: list[float] = []
        for item in emb:
            try:
                out.append(float(item))
            except (TypeError, ValueError):
                return None
        return out or None

    def save_embedding(
        self,
        user_id: str,
        embedding: list[float] | tuple[float, ...],
        *,
        model: str = "insightface_arcface",
        source: str = "realsense_local",
    ) -> dict[str, Any]:
        safe_id = self.safe_user_id(user_id)
        if not safe_id:
            raise ValueError("Invalid user id for embedding.")
        emb = [float(v) for v in embedding]
        payload = {
            "user_id": safe_id,
            "embedding": emb,
            "dim": len(emb),
            "model": str(model or "insightface_arcface"),
            "source": str(source or "realsense_local"),
            "updated_at": self._now_iso(),
        }
        path = self._embedding_path(safe_id)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        profile = self.load_profile(safe_id)
        if profile:
            profile["face_embedding_path"] = str(path.relative_to(self.base_dir))
            profile["face_embedding_dim"] = len(emb)
            profile["face_embedding_model"] = payload["model"]
            self.save_profile(profile)
        return payload

    def upsert_profile_and_embedding(
        self,
        profile: dict[str, Any],
        embedding: list[float] | None = None,
        *,
        embedding_model: str = "insightface_arcface",
        embedding_source: str = "realsense_local",
    ) -> dict[str, Any]:
        saved = self.save_profile(profile)
        if embedding:
            self.save_embedding(
                saved["id"],
                embedding,
                model=embedding_model,
                source=embedding_source,
            )
        return self.load_profile(saved["id"]) or saved

    def import_legacy_users_json(self) -> int:
        """
        Import old RealSense users.json records into canonical storage.
        Safe to call repeatedly; upserts by stable/derived user id.
        """
        if not self.legacy_users_file.exists():
            return 0
        try:
            raw = json.loads(self.legacy_users_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        if not isinstance(raw, dict):
            return 0
        legacy_users = raw.get("users")
        if not isinstance(legacy_users, list):
            return 0

        imported = 0
        for idx, legacy in enumerate(legacy_users):
            if not isinstance(legacy, dict):
                continue
            name = str(legacy.get("name", "")).strip() or f"LegacyUser{idx+1}"
            user_id = self.safe_user_id(legacy.get("id")) or self.build_user_id(name)
            existing = self.load_profile(user_id) or {}

            meds = legacy.get("medications")
            if not isinstance(meds, list):
                meds = []
            first_med = meds[0] if meds and isinstance(meds[0], dict) else {}
            medication = str(existing.get("medication") or first_med.get("name") or "").strip()
            schedule_times = first_med.get("times") if isinstance(first_med, dict) else []
            if not isinstance(schedule_times, list):
                schedule_times = []

            profile = {
                "id": user_id,
                "name": name,
                "age": str(legacy.get("age", existing.get("age", "")) or "").strip(),
                "medication": medication,
                "dosage": str(existing.get("dosage", "") or first_med.get("dosage", "") or "1 unit").strip(),
                "servo_channel": existing.get("servo_channel", 1),
                "notes": existing.get("notes", ""),
                "medications": meds,
                "schedule_times": existing.get("schedule_times") or schedule_times,
                "created_at": str(existing.get("created_at") or legacy.get("created") or self._now_iso()),
                "legacy_source": "data/users.json",
                "image_path": str(existing.get("image_path", "")).strip(),
                "face_embedding_path": str(existing.get("face_embedding_path", "")).strip(),
                "face_embedding_dim": existing.get("face_embedding_dim", 0),
                "face_embedding_model": existing.get("face_embedding_model", "insightface_arcface"),
            }
            try:
                self.save_profile(profile)
            except ValueError:
                continue

            raw_encoding = legacy.get("face_encoding")
            if isinstance(raw_encoding, list) and raw_encoding:
                try:
                    self.save_embedding(
                        user_id,
                        [float(v) for v in raw_encoding],
                        model="insightface_arcface",
                        source="legacy_realsense_users_json",
                    )
                except (TypeError, ValueError):
                    pass
            imported += 1

        if imported:
            self.write_legacy_users_cache(import_legacy=False)
        return imported

    def list_realsense_users(self, *, import_legacy: bool = True) -> list[dict[str, Any]]:
        """
        RealSense compatibility view. Keeps old keys (`face_encoding`, `medications`)
        while sourcing from canonical per-user files.
        """
        if import_legacy:
            self.import_legacy_users_json()
        out: list[dict[str, Any]] = []
        for profile in self.list_profiles():
            user_id = self.safe_user_id(profile.get("id"))
            if not user_id:
                continue
            medications = profile.get("medications")
            if not isinstance(medications, list) or not medications:
                med_name = str(profile.get("medication", "")).strip()
                times = profile.get("schedule_times")
                if not isinstance(times, list):
                    times = []
                if med_name:
                    medications = [{"name": med_name, "times": [str(t) for t in times if str(t).strip()]}]
                else:
                    medications = []

            entry: dict[str, Any] = {
                "id": user_id,
                "name": str(profile.get("name", user_id)),
                "age": str(profile.get("age", "")),
                "medication": str(profile.get("medication", "")),
                "dosage": str(profile.get("dosage", "")),
                "servo_channel": int(profile.get("servo_channel", 1) or 1),
                "medications": medications,
                "created": str(profile.get("created_at", self._now_iso())),
            }
            embedding = self.load_embedding(user_id)
            if embedding:
                entry["face_encoding"] = embedding
            out.append(entry)
        return out

    def save_realsense_users(self, payload: dict[str, Any]) -> None:
        """
        Upsert RealSense compatibility payload back into canonical storage.
        Does not delete existing canonical users that are absent from payload.
        """
        users = payload.get("users") if isinstance(payload, dict) else None
        if not isinstance(users, list):
            return

        for idx, rec in enumerate(users):
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("name", "")).strip() or f"User{idx+1}"
            user_id = self.safe_user_id(rec.get("id")) or self.build_user_id(name)
            existing = self.load_profile(user_id) or {}

            meds = rec.get("medications")
            if not isinstance(meds, list):
                meds = []
            first_med = meds[0] if meds and isinstance(meds[0], dict) else {}
            medication = str(rec.get("medication") or existing.get("medication") or first_med.get("name") or "").strip()
            dosage = str(rec.get("dosage") or existing.get("dosage") or first_med.get("dosage") or "1 unit").strip()
            try:
                servo_channel = int(rec.get("servo_channel") or existing.get("servo_channel") or 1)
            except (TypeError, ValueError):
                servo_channel = 1

            schedule_times = existing.get("schedule_times")
            if not isinstance(schedule_times, list):
                schedule_times = []
            if isinstance(first_med, dict) and isinstance(first_med.get("times"), list):
                schedule_times = [str(t) for t in first_med["times"] if str(t).strip()]

            profile = {
                "id": user_id,
                "name": name,
                "age": str(rec.get("age") or existing.get("age") or "").strip(),
                "medication": medication,
                "dosage": dosage,
                "servo_channel": min(4, max(1, servo_channel)),
                "notes": str(existing.get("notes", "")).strip(),
                "medications": meds or existing.get("medications", []),
                "schedule_times": schedule_times,
                "created_at": str(existing.get("created_at") or rec.get("created") or self._now_iso()),
                "image_path": str(existing.get("image_path", "")).strip(),
                "legacy_source": "realsense_upsert",
                "face_embedding_path": str(existing.get("face_embedding_path", "")).strip(),
                "face_embedding_dim": existing.get("face_embedding_dim", 0),
                "face_embedding_model": existing.get("face_embedding_model", "insightface_arcface"),
            }
            try:
                self.save_profile(profile)
            except ValueError:
                continue

            raw_encoding = rec.get("face_encoding")
            if isinstance(raw_encoding, list) and raw_encoding:
                try:
                    self.save_embedding(user_id, [float(v) for v in raw_encoding])
                except (TypeError, ValueError):
                    pass

        self.write_legacy_users_cache(import_legacy=False)

    def write_legacy_users_cache(self, *, import_legacy: bool = True) -> None:
        if import_legacy:
            self.import_legacy_users_json()
        cache = {"users": self.list_realsense_users(import_legacy=False)}
        self.legacy_users_file.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )

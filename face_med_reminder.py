"""
Medication Reminder Robot - InsightFace (ArcFace) Version
==========================================================
High-accuracy face recognition using InsightFace ONNX models.
Designed for Jetson Orin Nano + RealSense D435i.

Requirements:
  pip install pyrealsense2 opencv-python numpy insightface onnxruntime
  # On Jetson (aarch64) with GPU:
  #   pip install --extra-index-url https://pypi.jetson-ai-lab.io/jp6/cu126 onnxruntime-gpu

Usage:
  python face_med_reminder.py

Detection distance: 1.2m (configurable, aligned with FSM/UI)
Max users: 10
Storage: canonical profiles in data/users/*.json + embeddings in data/embeddings/*.json
         (legacy cache data/users.json maintained for compatibility)

Architecture:
  - SCRFD for face detection (fast, accurate)
  - ArcFace for 512-d face embedding (state-of-the-art accuracy)
  - Cosine similarity matching with dual thresholds to avoid false pos/neg
  - Multi-frame confirmation to prevent single-frame errors
"""

import cv2
import numpy as np
import pyrealsense2 as rs
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "4"

import insightface
from insightface.app import FaceAnalysis

from realsense_fsm_adapter import RealSenseFSMAdapter
from shared_user_storage import SharedUserStorage

# ======================= Configuration =======================

USERS_JSON = os.path.join("data", "users.json")  # legacy compatibility cache
MAX_USERS = 10
DETECTION_DISTANCE_M = 1.2        # aligned with FSM / frontend wake threshold (meters)

# --- Recognition thresholds (ArcFace cosine similarity) ---
# Same person typically > 0.4, different person < 0.2
MATCH_THRESHOLD = 0.35             # >= this = matched
UNKNOWN_CEILING = 0.25             # <  this = definitely unknown
# Between the two = uncertain -> do nothing, keep watching

# --- Multi-frame confirmation ---
CONFIRM_FRAMES_NEEDED = 3          # Need 3 consistent matches
CONFIRM_WINDOW_FRAMES = 5          # Within last 5 frames
UNKNOWN_CONFIRM_FRAMES = 5         # Need 5 "unknown" before registration

RECOGNITION_COOLDOWN_S = 8
REGISTER_COOLDOWN_S = 5

# InsightFace model: "buffalo_s" (fast) or "buffalo_l" (more accurate)
INSIGHTFACE_MODEL = "buffalo_s"
REALSENSE_RUNTIME_DIR = Path("data") / "runtime"
REALSENSE_FRAME_FILE = REALSENSE_RUNTIME_DIR / "realsense_latest.jpg"
REALSENSE_FRAME_META_FILE = REALSENSE_RUNTIME_DIR / "realsense_meta.json"
REALSENSE_PENDING_EMBED_FILE = REALSENSE_RUNTIME_DIR / "realsense_pending_embedding.json"
REALSENSE_JPEG_QUALITY = 85


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}

# ======================= User Data =======================

_SHARED_STORE = SharedUserStorage(Path(__file__).resolve().parent)


def load_users():
    """
    RealSense compatibility loader backed by canonical per-user storage.
    Returns legacy-shaped payload: {"users": [...]} for minimal code changes below.
    """
    _SHARED_STORE.import_legacy_users_json()
    return {"users": _SHARED_STORE.list_realsense_users(import_legacy=False)}


def save_users(data):
    _SHARED_STORE.save_realsense_users(data if isinstance(data, dict) else {"users": []})


def find_matching_user(embedding, data):
    """
    Match embedding against stored users via cosine similarity.
    Returns (user_dict, index, score) or (None, -1, best_score).
    """
    if not data["users"]:
        return None, -1, 0.0

    query = np.array(embedding, dtype=np.float32).flatten()
    if query.size == 0:
        return None, -1, 0.0
    query /= (np.linalg.norm(query) + 1e-8)

    best_score = -1.0
    best_idx = -1

    for i, u in enumerate(data["users"]):
        raw_encoding = u.get("face_encoding")
        if raw_encoding is None:
            continue

        stored = np.array(raw_encoding, dtype=np.float32).flatten()
        # Skip incompatible/legacy encodings (e.g., older 128-d vectors).
        if stored.size != query.size or stored.size == 0:
            continue
        stored /= (np.linalg.norm(stored) + 1e-8)
        score = float(np.dot(query, stored))
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx == -1:
        return None, -1, 0.0

    if best_score >= MATCH_THRESHOLD:
        return data["users"][best_idx], best_idx, best_score
    return None, -1, best_score


def get_pending_meds(user):
    """Return medication reminders based on current time."""
    now = datetime.now()
    now_min = now.hour * 60 + now.minute
    reminders = []

    for med in user.get("medications", []):
        for t in med["times"]:
            parts = t.split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            diff = (h * 60 + m) - now_min
            if abs(diff) <= 30:
                reminders.append(f"  >>> {t} - {med['name']}  [NOW!]")
            elif 0 < diff <= 120:
                reminders.append(f"  {t} - {med['name']}  (upcoming)")

    if not reminders:
        reminders.append("  (No medication due soon)")
        reminders.append("  Full schedule:")
        for med in user.get("medications", []):
            for t in med["times"]:
                reminders.append(f"    {t} - {med['name']}")
    return reminders


# ======================= Depth Helper =======================

def median_depth_at(depth_frame, x, y, k=7):
    h, w = depth_frame.get_height(), depth_frame.get_width()
    x, y = int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1))
    vals = []
    for yy in range(max(0, y - k // 2), min(h, y + k // 2 + 1)):
        for xx in range(max(0, x - k // 2), min(w, x + k // 2 + 1)):
            d = depth_frame.get_distance(xx, yy)
            if 0.05 < d < 2.0:
                vals.append(d)
    return float(np.median(vals)) if vals else 0.0


# ======================= Multi-Frame Tracker =======================

class FaceTracker:
    """
    Requires N consistent identity matches in M frames before confirming.
    Prevents single-frame false positives and false negatives.
    """
    def __init__(self):
        self.history = []
        self.last_seen = 0

    def update(self, identity, score, now):
        if identity == "uncertain":
            return
        self.last_seen = now
        self.history.append((identity, score, now))
        self.history = self.history[-CONFIRM_WINDOW_FRAMES:]

    def get_confirmed(self):
        if len(self.history) < CONFIRM_FRAMES_NEEDED:
            return None
        counts = {}
        for name, _, _ in self.history:
            counts[name] = counts.get(name, 0) + 1
        for name, count in counts.items():
            if name == "unknown" and count >= UNKNOWN_CONFIRM_FRAMES:
                return "unknown"
            elif name != "unknown" and count >= CONFIRM_FRAMES_NEEDED:
                return name
        return None

    def reset(self):
        self.history.clear()

    def is_stale(self, now, timeout=2.0):
        return (now - self.last_seen) > timeout


# ======================= Registration GUI =======================

class RegistrationGUI:
    def __init__(self):
        self.state = "idle"
        self.buf = ""
        self.name = ""
        self.age = ""
        self.medications = []
        self.cur_med = ""
        self.msg = ""
        self.done = False
        self.result = None

    def start(self):
        self.state = "name"
        self.buf = ""
        self.msg = "Type NAME, press ENTER"
        self.done = False
        self.result = None

    def handle_key(self, key):
        if self.done or key == -1:
            return
        if key in (13, 10):
            self._enter()
        elif key in (8, 127):
            self.buf = self.buf[:-1]
        elif key == 27:
            self.done = True
            self.result = None
            self.msg = "Cancelled"
        else:
            ch = chr(key & 0xFF) if 0 <= (key & 0xFF) < 128 else ""
            if ch.isprintable() and len(self.buf) < 50:
                self.buf += ch

    def _enter(self):
        if self.state == "name":
            if self.buf.strip():
                self.name = self.buf.strip()
                self.buf = ""
                self.state = "age"
                self.msg = "Type AGE, press ENTER"
            else:
                self.msg = "Name cannot be empty!"
        elif self.state == "age":
            self.age = self.buf.strip() or "N/A"
            self.buf = ""
            self.state = "med_name"
            self.msg = "Med name (empty ENTER = finish)"
        elif self.state == "med_name":
            if self.buf.strip():
                self.cur_med = self.buf.strip()
                self.buf = ""
                self.state = "med_times"
                self.msg = f"Times for '{self.cur_med}' (e.g. 8:00,12:00,20:00)"
            else:
                self.done = True
                self.result = {"name": self.name, "age": self.age, "medications": self.medications}
                self.msg = f"Registered: {self.name}!"
        elif self.state == "med_times":
            times = [t.strip() for t in self.buf.split(",") if t.strip()]
            if times:
                self.medications.append({"name": self.cur_med, "times": times})
            self.buf = ""
            self.state = "med_name"
            self.msg = "Next med (empty ENTER = finish)"

    def draw(self, frame):
        if self.state == "idle" and not self.done:
            return frame
        h, w = frame.shape[:2]
        ov = frame.copy()
        cv2.rectangle(ov, (20, 20), (w - 20, h - 20), (15, 15, 15), -1)
        cv2.addWeighted(ov, 0.88, frame, 0.12, 0, frame)

        y = 70
        cv2.putText(frame, "=== NEW USER REGISTRATION ===", (40, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2)

        y += 48
        ntxt = (self.buf + "|") if self.state == "name" else self.name
        cv2.putText(frame, f"Name: {ntxt}", (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if self.state != "name":
            y += 36
            atxt = (self.buf + "|") if self.state == "age" else self.age
            cv2.putText(frame, f"Age:  {atxt}", (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if self.medications or self.state in ("med_name", "med_times"):
            y += 36
            cv2.putText(frame, "Medications:", (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 255), 2)
            for med in self.medications:
                y += 28
                cv2.putText(frame, f"  * {med['name']} @ {', '.join(med['times'])}",
                            (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 255, 150), 1)

        if not self.done:
            y += 35
            if self.state == "med_name":
                cv2.putText(frame, f"Med: {self.buf}|", (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            elif self.state == "med_times":
                cv2.putText(frame, f"Times: {self.buf}|", (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        y += 42
        cv2.putText(frame, self.msg, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
        cv2.putText(frame, "ESC=cancel", (40, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 120, 120), 1)
        return frame


# ======================= Main System =======================

class MedReminderVision:
    def __init__(self):
        print("[INFO] Loading InsightFace (first run downloads ~30MB models)...")
        self.face_app = FaceAnalysis(
            name=INSIGHTFACE_MODEL,
            root="./insightface_models",
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        self.face_app.prepare(ctx_id=0, det_size=(640, 480))
        print("[INFO] InsightFace ready.")

        print("[INFO] Starting RealSense D435i...")
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
        cfg.enable_stream(rs.stream.color, 848, 480, rs.format.bgr8, 30)
        self.profile = self.pipe.start(cfg)
        self.align = rs.align(rs.stream.color)
        for _ in range(20):
            self.pipe.wait_for_frames(5000)
        print("[INFO] Camera ready.")

        self.data = load_users()
        print(f"[INFO] {len(self.data['users'])} registered users.")

        self.tracker = FaceTracker()
        self.last_reminder = {}
        self.last_register = 0
        self.registering = False
        self.reg_gui = RegistrationGUI()
        self.pending_emb = None
        self.overlay_lines = []
        self.overlay_color = (0, 255, 0)
        self.overlay_expire = 0
        self.fsm_bridge = RealSenseFSMAdapter()
        self.legacy_debug_ui_enabled = _env_flag("REALSENSE_LEGACY_DEBUG_UI", default=False)
        self.legacy_registration_ui_enabled = _env_flag("REALSENSE_LEGACY_REGISTRATION_UI", default=False)
        self.publish_web_stream_enabled = _env_flag("REALSENSE_WEB_STREAM_ENABLED", default=True)
        self.runtime_dir = Path(__file__).resolve().parent / REALSENSE_RUNTIME_DIR
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.frame_file = Path(__file__).resolve().parent / REALSENSE_FRAME_FILE
        self.frame_meta_file = Path(__file__).resolve().parent / REALSENSE_FRAME_META_FILE
        self.pending_embed_file = Path(__file__).resolve().parent / REALSENSE_PENDING_EMBED_FILE
        self._last_frame_publish = 0.0
        self._frame_publish_interval_s = 0.10  # ~10 FPS for web stream
        self._last_user_reload_check = 0.0
        self._user_reload_check_interval_s = 1.0
        self._user_store_signature = self._compute_user_store_signature()

        if not self.legacy_debug_ui_enabled:
            print("[INFO] Legacy OpenCV window UI disabled (REALSENSE_LEGACY_DEBUG_UI=0).")
        if not self.legacy_registration_ui_enabled:
            print("[INFO] Legacy OpenCV registration input disabled; use touchscreen registration UI.")

    def set_overlay(self, lines, color=(0, 255, 0), dur=6.0):
        self.overlay_lines = lines
        self.overlay_color = color
        self.overlay_expire = time.time() + dur

    def run(self):
        print(f"\n{'='*55}")
        print(f"  Med Reminder | {DETECTION_DISTANCE_M*100:.0f}cm | "
              f"{len(self.data['users'])}/{MAX_USERS} users | 'q' quit")
        print(f"{'='*55}\n")

        try:
            while True:
                frames = self.pipe.wait_for_frames(5000)
                self._maybe_reload_users()
                aligned = self.align.process(frames)
                depth_f = aligned.get_depth_frame()
                color_f = aligned.get_color_frame()
                if not depth_f or not color_f:
                    continue

                img = np.asanyarray(color_f.get_data())
                disp = img.copy()
                now = time.time()

                # --- Registration mode ---
                if self.registering:
                    key = -1
                    if self.legacy_debug_ui_enabled:
                        key = cv2.waitKey(1) & 0xFFFF
                    self.reg_gui.handle_key(key)
                    disp = self.reg_gui.draw(disp)
                    if self.reg_gui.done:
                        r = self.reg_gui.result
                        if r and self.pending_emb is not None and len(self.data["users"]) < MAX_USERS:
                            first_med = r["medications"][0] if r.get("medications") else {}
                            user_id = _SHARED_STORE.build_user_id(r["name"])
                            self.data["users"].append({
                                "id": user_id,
                                "name": r["name"], "age": r["age"],
                                "medication": str(first_med.get("name", "")),
                                "dosage": str(first_med.get("dosage", "1 unit") or "1 unit"),
                                "servo_channel": int(first_med.get("servo_channel", 1) or 1),
                                "medications": r["medications"],
                                "face_encoding": self.pending_emb.tolist(),
                                "created": datetime.now().isoformat(),
                            })
                            save_users(self.data)
                            self.set_overlay([f"Registered: {r['name']}",
                                              f"Users: {len(self.data['users'])}/{MAX_USERS}"], (0,255,0), 5)
                            print(f"[REGISTERED] {r['name']}")
                        elif r and len(self.data["users"]) >= MAX_USERS:
                            self.set_overlay(["Max 10 users reached!"], (0,0,255), 4)
                        else:
                            self.set_overlay(["Registration cancelled."], (100,100,255), 3)
                        self.registering = False
                        self.pending_emb = None
                        self.tracker.reset()
                        self.fsm_bridge.reset_session_hint()
                    self._draw_hud(disp)
                    self._publish_web_frame(disp)
                    if self.legacy_debug_ui_enabled:
                        cv2.imshow("Med Reminder", disp)
                    continue

                # --- Detection ---
                faces = self.face_app.get(img)

                # Pick closest in-range face
                best_face = None
                best_dist = 999.0
                for face in faces:
                    bx = face.bbox.astype(int)
                    cx, cy = (bx[0]+bx[2])//2, (bx[1]+bx[3])//2
                    d = median_depth_at(depth_f, cx, cy, k=9)

                    # Draw all faces
                    if 0 < d <= DETECTION_DISTANCE_M:
                        cv2.rectangle(disp, (bx[0],bx[1]), (bx[2],bx[3]), (0,255,0), 2)
                        cv2.putText(disp, f"{d:.2f}m", (bx[0], bx[1]-8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,0), 2)
                        if d < best_dist:
                            best_face = face
                            best_dist = d
                    elif d > DETECTION_DISTANCE_M:
                        cv2.rectangle(disp, (bx[0],bx[1]), (bx[2],bx[3]), (100,100,100), 1)
                        cv2.putText(disp, f"{d:.2f}m (far)", (bx[0], bx[1]-8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100,100,100), 1)

                if best_face is not None and best_face.embedding is not None:
                    if 0 < best_dist <= DETECTION_DISTANCE_M:
                        self.fsm_bridge.push_distance(best_dist)
                    emb = best_face.embedding
                    bx = best_face.bbox.astype(int)
                    user, idx, score = find_matching_user(emb, self.data)

                    if user and score >= MATCH_THRESHOLD:
                        name = user["name"]
                        self.tracker.update(name, score, now)
                        cv2.rectangle(disp, (bx[0],bx[1]), (bx[2],bx[3]), (0,255,0), 3)
                        cv2.putText(disp, f"{name} ({score:.2f})", (bx[0], bx[3]+22),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
                    elif score < UNKNOWN_CEILING:
                        self.tracker.update("unknown", score, now)
                        cv2.rectangle(disp, (bx[0],bx[1]), (bx[2],bx[3]), (0,165,255), 3)
                        cv2.putText(disp, f"Unknown ({score:.2f})", (bx[0], bx[3]+22),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,165,255), 2)
                    else:
                        # Uncertain zone - keep watching
                        cv2.rectangle(disp, (bx[0],bx[1]), (bx[2],bx[3]), (0,255,255), 2)
                        cv2.putText(disp, f"Checking ({score:.2f})", (bx[0], bx[3]+22),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)

                    # Multi-frame confirmation
                    confirmed = self.tracker.get_confirmed()
                    if confirmed and confirmed != "unknown":
                        if now - self.last_reminder.get(confirmed, 0) > RECOGNITION_COOLDOWN_S:
                            self.last_reminder[confirmed] = now
                            for u in self.data["users"]:
                                if u["name"] == confirmed:
                                    user_id = str(u.get("id", "")).strip()
                                    if user_id:
                                        self.fsm_bridge.report_recognition_existing(user_id, score)
                                    meds = get_pending_meds(u)
                                    self.set_overlay(
                                        [f"Hello, {confirmed}! (age: {u.get('age','?')})",
                                         "-"*30, "Medication Schedule:"] + meds,
                                        (0,255,0), 8)
                                    print(f"[REMINDER] {confirmed}: {meds}")
                                    break
                            self.tracker.reset()
                    elif confirmed == "unknown":
                        if now - self.last_register > REGISTER_COOLDOWN_S:
                            self.last_register = now
                            self.fsm_bridge.report_recognition_new(score)
                            self._publish_pending_embedding(emb, score)
                            if self.legacy_registration_ui_enabled and self.legacy_debug_ui_enabled:
                                self.pending_emb = emb.copy()
                                self.registering = True
                                self.reg_gui = RegistrationGUI()
                                self.reg_gui.start()
                                print("[NEW FACE] Starting legacy OpenCV registration...")
                            else:
                                self.pending_emb = emb.copy()
                                self.set_overlay(
                                    [
                                        "Unknown face detected.",
                                        "Touchscreen registration required.",
                                        "Use web UI to enter profile and capture data.",
                                    ],
                                    (0, 165, 255),
                                    4,
                                )
                                print("[NEW FACE] Routed to touchscreen registration UI (legacy reg disabled).")
                            self.tracker.reset()
                else:
                    if self.tracker.is_stale(now):
                        self.tracker.reset()

                self._draw_overlay(disp)
                self._draw_hud(disp)
                self._publish_web_frame(disp)
                if self.legacy_debug_ui_enabled:
                    cv2.imshow("Med Reminder", disp)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        finally:
            self.pipe.stop()
            if self.legacy_debug_ui_enabled:
                cv2.destroyAllWindows()
            print("[INFO] Stopped.")

    def _compute_user_store_signature(self):
        """
        Lightweight signature of canonical user/embedding JSON files so we can hot-reload
        when the touchscreen frontend registers a new user while this process is running.
        """
        latest_mtime_ns = 0
        json_count = 0
        for folder in (_SHARED_STORE.users_dir, _SHARED_STORE.embeddings_dir):
            try:
                paths = folder.glob("*.json")
            except OSError:
                continue
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                json_count += 1
                latest_mtime_ns = max(latest_mtime_ns, int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))))
        return (json_count, latest_mtime_ns)

    def _maybe_reload_users(self):
        now = time.time()
        if (now - self._last_user_reload_check) < self._user_reload_check_interval_s:
            return
        self._last_user_reload_check = now

        sig = self._compute_user_store_signature()
        if sig == self._user_store_signature:
            return

        old_count = len(self.data.get("users", []))
        self.data = load_users()
        self._user_store_signature = sig
        new_count = len(self.data.get("users", []))
        print(f"[INFO] Reloaded user store: {old_count} -> {new_count} users.")

    def _publish_web_frame(self, frame):
        if not self.publish_web_stream_enabled:
            return
        now = time.time()
        if (now - self._last_frame_publish) < self._frame_publish_interval_s:
            return
        self._last_frame_publish = now

        ok, buf = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(REALSENSE_JPEG_QUALITY)],
        )
        if not ok:
            return

        tmp_frame = self.frame_file.with_suffix(".jpg.tmp")
        tmp_frame.write_bytes(buf.tobytes())
        try:
            tmp_frame.replace(self.frame_file)
        except PermissionError:
            self.frame_file.write_bytes(buf.tobytes())
            try:
                if tmp_frame.exists():
                    tmp_frame.unlink()
            except OSError:
                pass

        meta = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "legacy_debug_ui_enabled": self.legacy_debug_ui_enabled,
            "legacy_registration_ui_enabled": self.legacy_registration_ui_enabled,
            "publish_web_stream_enabled": self.publish_web_stream_enabled,
            "tracking_count": len(self.tracker.history),
            "registering": bool(self.registering),
            "users_count": len(self.data.get("users", [])),
            "distance_threshold_m": DETECTION_DISTANCE_M,
            "pending_embedding_available": bool(self.pending_emb is not None or self.pending_embed_file.exists()),
        }
        tmp_meta = self.frame_meta_file.with_suffix(".json.tmp")
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        try:
            tmp_meta.replace(self.frame_meta_file)
        except PermissionError:
            self.frame_meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            try:
                if tmp_meta.exists():
                    tmp_meta.unlink()
            except OSError:
                pass

    def _publish_pending_embedding(self, embedding, score):
        if embedding is None:
            return
        try:
            emb = [float(v) for v in np.asarray(embedding, dtype=np.float32).flatten().tolist()]
        except Exception:
            return
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "realsense_unknown_face",
            "model": INSIGHTFACE_MODEL,
            "score": float(score) if score is not None else None,
            "embedding": emb,
            "dim": len(emb),
        }
        tmp = self.pending_embed_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            tmp.replace(self.pending_embed_file)
        except PermissionError:
            self.pending_embed_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    def _draw_overlay(self, disp):
        if not self.overlay_lines or time.time() >= self.overlay_expire:
            return
        h, w = disp.shape[:2]
        n = len(self.overlay_lines)
        ph = 30 + 28 * n
        py = h - ph - 12
        ov = disp.copy()
        cv2.rectangle(ov, (12, py), (w-12, h-12), (20,20,20), -1)
        cv2.rectangle(ov, (12, py), (w-12, h-12), self.overlay_color, 2)
        cv2.addWeighted(ov, 0.85, disp, 0.15, 0, disp)
        for i, line in enumerate(self.overlay_lines):
            cv2.putText(disp, line, (28, py+26+i*28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, self.overlay_color, 2)

    def _draw_hud(self, disp):
        h, w = disp.shape[:2]
        cv2.putText(disp, f"Users: {len(self.data['users'])}/{MAX_USERS} | "
                          f"Range: {DETECTION_DISTANCE_M*100:.0f}cm",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,200,255), 2)
        nh = len(self.tracker.history)
        if nh:
            cv2.putText(disp, f"Tracking: {nh}/{CONFIRM_FRAMES_NEEDED} frames",
                        (8, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180,180,180), 1)
        cv2.putText(disp, "'q' quit", (w-100, h-8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100,100,100), 1)


if __name__ == "__main__":
    MedReminderVision().run()

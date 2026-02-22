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

Detection distance: 65cm (configurable)
Max users: 10
Storage: data/users.json

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
from datetime import datetime

os.environ["OMP_NUM_THREADS"] = "4"

import insightface
from insightface.app import FaceAnalysis

# ======================= Configuration =======================

USERS_JSON = os.path.join("data", "users.json")
MAX_USERS = 10
DETECTION_DISTANCE_M = 0.65       # 65cm

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

# ======================= User Data =======================

def load_users():
    if os.path.exists(USERS_JSON):
        with open(USERS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": []}


def save_users(data):
    os.makedirs(os.path.dirname(USERS_JSON), exist_ok=True)
    with open(USERS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
                    key = cv2.waitKey(1) & 0xFFFF
                    self.reg_gui.handle_key(key)
                    disp = self.reg_gui.draw(disp)
                    if self.reg_gui.done:
                        r = self.reg_gui.result
                        if r and self.pending_emb is not None and len(self.data["users"]) < MAX_USERS:
                            self.data["users"].append({
                                "name": r["name"], "age": r["age"],
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
                    self._draw_hud(disp)
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
                            self.pending_emb = emb.copy()
                            self.registering = True
                            self.reg_gui = RegistrationGUI()
                            self.reg_gui.start()
                            self.tracker.reset()
                            print("[NEW FACE] Starting registration...")
                else:
                    if self.tracker.is_stale(now):
                        self.tracker.reset()

                self._draw_overlay(disp)
                self._draw_hud(disp)
                cv2.imshow("Med Reminder", disp)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            self.pipe.stop()
            cv2.destroyAllWindows()
            print("[INFO] Stopped.")

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

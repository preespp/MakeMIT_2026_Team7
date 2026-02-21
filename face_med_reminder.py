"""
Medication Reminder Robot - Face Recognition System
====================================================
Uses RealSense D435i for face detection + depth, and face_recognition library
for identity matching.

Requirements:
  pip install pyrealsense2 opencv-python numpy face-recognition

Usage:
  python face_med_reminder.py

Flow:
  1) Detect faces in RGB frame
  2) If a face is within 20cm of camera, start recognition
  3) Known user  → show medication reminder based on schedule
  4) Unknown user → prompt to register (name, age, meds, schedule)

User data is stored in users.json (max 10 users).
"""

import cv2
import numpy as np
import pyrealsense2 as rs
import face_recognition
import json
import os
import time
from datetime import datetime

# ============ Config ============
USERS_JSON = "users.json"
MAX_USERS = 10
DETECTION_DISTANCE_M = 0.65  # 65 cm
RECOGNITION_COOLDOWN_S = 5   # seconds between repeated reminders for same user
FACE_MATCH_TOLERANCE = 0.45  # lower = stricter matching

# ============ User Data Management ============

def load_users():
    if os.path.exists(USERS_JSON):
        with open(USERS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": []}


def save_users(data):
    with open(USERS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_matching_user(face_encoding, data):
    """
    Compare face_encoding against all stored users.
    Returns (user_dict, index) or (None, -1).
    """
    if not data["users"]:
        return None, -1

    stored_encodings = []
    for u in data["users"]:
        stored_encodings.append(np.array(u["face_encoding"]))

    distances = face_recognition.face_distance(stored_encodings, face_encoding)
    best_idx = int(np.argmin(distances))
    best_dist = distances[best_idx]

    if best_dist < FACE_MATCH_TOLERANCE:
        return data["users"][best_idx], best_idx
    return None, -1


def get_pending_meds(user):
    """
    Check user's medication schedule and return what they should take now.
    Returns list of strings like ["8:00 - Aspirin", "12:00 - VitaminD"]
    """
    now = datetime.now()
    current_hour = now.hour
    current_min = now.minute
    reminders = []

    for med in user.get("medications", []):
        med_name = med["name"]
        for t in med["times"]:
            parts = t.split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            # Show meds that are due within +/- 30 min window
            med_total_min = h * 60 + m
            now_total_min = current_hour * 60 + current_min
            diff = abs(med_total_min - now_total_min)
            if diff <= 30:
                reminders.append(f"{t} - {med_name} (NOW!)")
            elif med_total_min > now_total_min:
                reminders.append(f"{t} - {med_name} (upcoming)")

    if not reminders:
        # Show full schedule if nothing is due soon
        for med in user.get("medications", []):
            for t in med["times"]:
                reminders.append(f"{t} - {med['name']}")

    return reminders


# ============ New User Registration (terminal-based) ============

def register_new_user_terminal(face_encoding, face_image, data):
    """
    Interactive terminal-based registration for a new user.
    """
    if len(data["users"]) >= MAX_USERS:
        print("\n[WARNING] Maximum 10 users reached! Cannot add more.")
        return None

    print("\n" + "=" * 50)
    print("  NEW FACE DETECTED - CREATE NEW USER")
    print("=" * 50)

    name = input("  Name: ").strip()
    if not name:
        print("  Registration cancelled.")
        return None

    age = input("  Age: ").strip()

    medications = []
    print("  Enter medications (empty name to finish):")
    while True:
        med_name = input("    Medication name: ").strip()
        if not med_name:
            break
        times_str = input("    Times (comma-separated, e.g. 8:00,12:00,20:00): ").strip()
        times = [t.strip() for t in times_str.split(",") if t.strip()]
        if times:
            medications.append({"name": med_name, "times": times})

    new_user = {
        "name": name,
        "age": age,
        "medications": medications,
        "face_encoding": face_encoding.tolist(),
        "created": datetime.now().isoformat(),
    }

    data["users"].append(new_user)
    save_users(data)

    print(f"\n  [OK] User '{name}' registered successfully!")
    print(f"  Total users: {len(data['users'])}/{MAX_USERS}")
    print("=" * 50 + "\n")

    return new_user


# ============ OpenCV GUI Registration ============

class RegistrationGUI:
    """
    Simple OpenCV-based GUI for registering a new user.
    Uses keyboard input overlaid on the camera feed.
    """
    def __init__(self):
        self.state = "idle"  # idle, name, age, med_name, med_times, confirm
        self.input_buffer = ""
        self.name = ""
        self.age = ""
        self.medications = []
        self.current_med_name = ""
        self.message = ""
        self.done = False
        self.result = None  # final user dict or None

    def start(self):
        self.state = "name"
        self.input_buffer = ""
        self.message = "Type name, press ENTER to confirm"
        self.done = False

    def handle_key(self, key):
        if self.done:
            return

        if key == -1:
            return

        char = chr(key & 0xFF) if 0 <= (key & 0xFF) < 128 else ""

        # ENTER
        if key in (13, 10):
            self._on_enter()
            return

        # BACKSPACE
        if key in (8, 127):
            self.input_buffer = self.input_buffer[:-1]
            return

        # ESC -> cancel
        if key == 27:
            self.state = "idle"
            self.done = True
            self.result = None
            self.message = "Registration cancelled"
            return

        # Normal character
        if char.isprintable() and len(self.input_buffer) < 40:
            self.input_buffer += char

    def _on_enter(self):
        if self.state == "name":
            if self.input_buffer.strip():
                self.name = self.input_buffer.strip()
                self.input_buffer = ""
                self.state = "age"
                self.message = "Type age, press ENTER"
            else:
                self.message = "Name cannot be empty!"

        elif self.state == "age":
            self.age = self.input_buffer.strip()
            self.input_buffer = ""
            self.state = "med_name"
            self.message = "Medication name (empty + ENTER to finish)"

        elif self.state == "med_name":
            if self.input_buffer.strip():
                self.current_med_name = self.input_buffer.strip()
                self.input_buffer = ""
                self.state = "med_times"
                self.message = f"Times for '{self.current_med_name}' (e.g. 8:00,12:00)"
            else:
                # No more meds -> done
                self.state = "idle"
                self.done = True
                self.result = {
                    "name": self.name,
                    "age": self.age,
                    "medications": self.medications,
                }
                self.message = f"User '{self.name}' registered!"

        elif self.state == "med_times":
            times_str = self.input_buffer.strip()
            times = [t.strip() for t in times_str.split(",") if t.strip()]
            if times:
                self.medications.append({
                    "name": self.current_med_name,
                    "times": times
                })
            self.input_buffer = ""
            self.state = "med_name"
            self.message = "Next medication name (empty + ENTER to finish)"

    def draw(self, frame):
        """Draw registration overlay on frame."""
        if self.state == "idle" and not self.done:
            return frame

        overlay = frame.copy()
        h, w = overlay.shape[:2]

        # Dark panel
        cv2.rectangle(overlay, (40, 40), (w - 40, h - 40), (30, 30, 30), -1)
        cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)

        y = 90
        cv2.putText(frame, "=== NEW USER REGISTRATION ===", (60, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        y += 40
        cv2.putText(frame, f"Name: {self.name if self.state != 'name' else self.input_buffer + '_'}",
                    (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        y += 35
        if self.state in ("age", "med_name", "med_times") or self.done:
            cv2.putText(frame, f"Age: {self.age if self.state != 'age' else self.input_buffer + '_'}",
                        (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        y += 35
        if self.medications or self.state in ("med_name", "med_times"):
            cv2.putText(frame, "Medications:", (60, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 255), 2)
            y += 30
            for med in self.medications:
                times_str = ", ".join(med["times"])
                cv2.putText(frame, f"  {med['name']} @ {times_str}",
                            (80, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 255, 180), 1)
                y += 28

        # Current input field
        if not self.done:
            y += 10
            if self.state == "med_name":
                cv2.putText(frame, f"Med name: {self.input_buffer}_",
                            (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            elif self.state == "med_times":
                cv2.putText(frame, f"Times: {self.input_buffer}_",
                            (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Message
        y += 40
        cv2.putText(frame, self.message, (60, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        # Instructions
        cv2.putText(frame, "ESC to cancel", (60, h - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

        return frame


# ============ Median Depth Helper ============

def median_depth_at(depth_frame, x, y, k=5):
    """Get median depth in meters from kxk region around (x,y)."""
    h, w = depth_frame.get_height(), depth_frame.get_width()
    x0, y0 = max(0, x - k // 2), max(0, y - k // 2)
    x1, y1 = min(w, x + k // 2 + 1), min(h, y + k // 2 + 1)
    vals = []
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            d = depth_frame.get_distance(xx, yy)
            if d > 0:
                vals.append(d)
    return float(np.median(vals)) if vals else 0.0


# ============ Main Vision Loop ============

class MedReminderVision:
    def __init__(self):
        # RealSense setup
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
        cfg.enable_stream(rs.stream.color, 848, 480, rs.format.bgr8, 30)

        print("[INFO] Starting RealSense pipeline...")
        self.profile = self.pipe.start(cfg)
        self.align = rs.align(rs.stream.color)

        # Warm up
        for _ in range(15):
            self.pipe.wait_for_frames(5000)
        print("[INFO] Camera ready.")

        # User data
        self.data = load_users()
        print(f"[INFO] Loaded {len(self.data['users'])} users from {USERS_JSON}")

        # State
        self.last_reminder = {}  # user_name -> timestamp
        self.registration_gui = RegistrationGUI()
        self.registering = False
        self.pending_encoding = None  # encoding for user being registered

        # Display state
        self.overlay_lines = []
        self.overlay_color = (0, 255, 0)
        self.overlay_time = 0

    def set_overlay(self, lines, color=(0, 255, 0), duration=5.0):
        self.overlay_lines = lines
        self.overlay_color = color
        self.overlay_time = time.time() + duration

    def run(self):
        print("[INFO] Starting medication reminder system.")
        print(f"[INFO] Detection distance: {DETECTION_DISTANCE_M*100:.0f} cm")
        print("[INFO] Press 'q' to quit.\n")

        try:
            while True:
                # Get frames
                frames = self.pipe.wait_for_frames(5000)
                aligned = self.align.process(frames)
                depth_frame = aligned.get_depth_frame()
                color_frame = aligned.get_color_frame()

                if not depth_frame or not color_frame:
                    continue

                color_img = np.asanyarray(color_frame.get_data())
                display = color_img.copy()

                # If we're in registration mode, handle that
                if self.registering:
                    key = cv2.waitKey(1) & 0xFFFF
                    self.registration_gui.handle_key(key)
                    display = self.registration_gui.draw(display)

                    if self.registration_gui.done:
                        result = self.registration_gui.result
                        if result and self.pending_encoding is not None:
                            # Check max users
                            if len(self.data["users"]) < MAX_USERS:
                                new_user = {
                                    "name": result["name"],
                                    "age": result["age"],
                                    "medications": result["medications"],
                                    "face_encoding": self.pending_encoding.tolist(),
                                    "created": datetime.now().isoformat(),
                                }
                                self.data["users"].append(new_user)
                                save_users(self.data)
                                self.set_overlay(
                                    [f"User '{result['name']}' registered!",
                                     f"Total: {len(self.data['users'])}/{MAX_USERS}"],
                                    (0, 255, 0), 4.0
                                )
                                print(f"[OK] Registered user: {result['name']}")
                            else:
                                self.set_overlay(["Max 10 users reached!"], (0, 0, 255), 3.0)

                        self.registering = False
                        self.pending_encoding = None

                    cv2.imshow("Med Reminder", display)
                    if key in (ord('q'), 27) and not self.registering:
                        break
                    continue

                # ---- Normal detection mode ----

                # Convert to RGB for face_recognition
                rgb_small = cv2.cvtColor(color_img, cv2.COLOR_BGR2RGB)

                # Detect faces
                face_locations = face_recognition.face_locations(rgb_small, model="hog")

                for (top, right, bottom, left) in face_locations:
                    # Get face center depth
                    face_cx = (left + right) // 2
                    face_cy = (top + bottom) // 2
                    dist_m = median_depth_at(depth_frame, face_cx, face_cy, k=9)

                    # Draw face box (always)
                    color_box = (100, 100, 100)
                    label = f"Face {dist_m:.2f}m"

                    if dist_m > 0 and dist_m <= DETECTION_DISTANCE_M:
                        # Close enough - do recognition
                        color_box = (0, 255, 0)

                        encodings = face_recognition.face_encodings(rgb_small, [(top, right, bottom, left)])
                        if encodings:
                            enc = encodings[0]
                            user, idx = find_matching_user(enc, self.data)

                            if user is not None:
                                # Known user!
                                name = user["name"]
                                color_box = (0, 255, 0)
                                label = f"{name} ({dist_m:.2f}m)"

                                # Check cooldown
                                now = time.time()
                                last = self.last_reminder.get(name, 0)
                                if now - last > RECOGNITION_COOLDOWN_S:
                                    self.last_reminder[name] = now
                                    meds = get_pending_meds(user)
                                    lines = [f"Hello, {name}!",
                                             f"Age: {user.get('age', '?')}",
                                             "--- Medication Schedule ---"]
                                    lines.extend(meds if meds else ["No medications set."])
                                    self.set_overlay(lines, (0, 255, 0), 6.0)
                                    print(f"[REMINDER] {name}: {meds}")
                            else:
                                # Unknown face within 20cm
                                color_box = (0, 165, 255)
                                label = f"Unknown ({dist_m:.2f}m)"

                                # Start registration
                                now = time.time()
                                if now - self.last_reminder.get("__new__", 0) > 3.0:
                                    self.last_reminder["__new__"] = now
                                    self.pending_encoding = enc
                                    self.registering = True
                                    self.registration_gui = RegistrationGUI()
                                    self.registration_gui.start()
                                    print("[NEW FACE] Starting registration...")

                    elif dist_m > DETECTION_DISTANCE_M:
                        color_box = (128, 128, 128)
                        label = f"Too far ({dist_m:.2f}m)"

                    # Draw
                    cv2.rectangle(display, (left, top), (right, bottom), color_box, 2)
                    cv2.putText(display, label, (left, top - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_box, 2)

                # Draw overlay messages
                if self.overlay_lines and time.time() < self.overlay_time:
                    h, w = display.shape[:2]
                    panel_h = 40 + 30 * len(self.overlay_lines)
                    panel_y = h - panel_h - 20
                    overlay = display.copy()
                    cv2.rectangle(overlay, (20, panel_y), (w - 20, h - 20), (30, 30, 30), -1)
                    cv2.addWeighted(overlay, 0.8, display, 0.2, 0, display)

                    for i, line in enumerate(self.overlay_lines):
                        cv2.putText(display, line, (40, panel_y + 30 + i * 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, self.overlay_color, 2)

                # FPS & status
                cv2.putText(display, f"Users: {len(self.data['users'])}/{MAX_USERS}",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
                cv2.putText(display, "Press 'q' to quit",
                            (10, display.shape[0] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

                cv2.imshow("Med Reminder", display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break

        finally:
            self.pipe.stop()
            cv2.destroyAllWindows()
            print("[INFO] System stopped.")


# ============ Entry Point ============

if __name__ == "__main__":
    system = MedReminderVision()
    system.run()
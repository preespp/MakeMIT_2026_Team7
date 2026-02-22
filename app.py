import json
import time
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, url_for

from pill_dispenser_fsm import PillDispenserFSM

app = Flask(__name__)
fsm = PillDispenserFSM()
BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "data" / "runtime"
REALSENSE_FRAME_FILE = RUNTIME_DIR / "realsense_latest.jpg"
REALSENSE_META_FILE = RUNTIME_DIR / "realsense_meta.json"

SCENE_TEMPLATES = {
    "idle": "Idle Welcome.html",
    "wake": "Wake and Detection Transition.html",
    "recognition": "Local Face Recognition.html",
    "register": "New User Registration.html",
    "dispense": "Dispensing & Greeting.html",
    "advice": "Advice and Voice Playback.html",
    "completion": "Completion Return to Idle.html",
    "fault": "Fault and Recovery.html",
}

STATE_TO_SCENE = {
    "WAITING_FOR_USER": "idle",
    "MONITORING_DISTANCE": "wake",
    "FACE_RECOGNITION": "recognition",
    "REGISTER_NEW_USER": "register",
    "DISPENSING_PILL": "dispense",
    "GENERATING_ADVICE": "advice",
    "SPEAKING_ADVICE": "advice",
    "REGISTRATION_SUCCESS": "completion",
    "SESSION_SUCCESS": "completion",
    "ERROR": "fault",
}


def _handle_local_recognition(payload: dict) -> dict:
    match_type = str(payload.get("match_type", "")).strip().lower()
    user_id = payload.get("user_id")
    if user_id is not None:
        user_id = str(user_id)
    if not match_type:
        match_type = "existing" if user_id else "new"
    source = str(payload.get("source", "REALSENSE_LOCAL"))
    raw_confidence = payload.get("confidence")
    confidence = None
    if raw_confidence is not None:
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = None
    return fsm.set_recognition_result(
        match_type=match_type,
        user_id=user_id,
        source=source,
        confidence=confidence,
    )


@app.get("/")
def home():
    state = str(fsm.status().get("state", "WAITING_FOR_USER"))
    slug = STATE_TO_SCENE.get(state, "idle")
    return redirect(url_for("ui_scene", slug=slug))


@app.get("/dashboard")
def dashboard_shell():
    return render_template("index.html")


@app.get("/ui-scene/<slug>")
def ui_scene(slug: str):
    template_name = SCENE_TEMPLATES.get(str(slug).strip().lower())
    if not template_name:
        return jsonify(ok=False, message="Unknown scene slug."), 404
    return render_template(template_name)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/status")
def api_status():
    return jsonify(fsm.status())


@app.get("/api/users")
def api_users():
    return jsonify(users=fsm.list_users())


@app.get("/api/realsense/meta")
def api_realsense_meta():
    if not REALSENSE_META_FILE.exists():
        return jsonify(
            available=False,
            message="No RealSense stream metadata yet. Start face_med_reminder.py first.",
        ), 404
    try:
        payload = json.loads(REALSENSE_META_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["available"] = True
    return jsonify(payload)


@app.get("/api/realsense/frame.jpg")
def api_realsense_frame():
    if not REALSENSE_FRAME_FILE.exists():
        return jsonify(
            available=False,
            message="No RealSense frame yet. Start face_med_reminder.py first.",
        ), 404
    return send_file(str(REALSENSE_FRAME_FILE), mimetype="image/jpeg", conditional=False, max_age=0)


@app.get("/api/realsense/stream.mjpg")
def api_realsense_stream():
    def generate():
        last_mtime_ns = None
        while True:
            try:
                if not REALSENSE_FRAME_FILE.exists():
                    time.sleep(0.15)
                    continue
                stat = REALSENSE_FRAME_FILE.stat()
                mtime_ns = getattr(stat, "st_mtime_ns", None)
                if mtime_ns is not None and last_mtime_ns == mtime_ns:
                    time.sleep(0.05)
                    continue
                frame_bytes = REALSENSE_FRAME_FILE.read_bytes()
                if not frame_bytes:
                    time.sleep(0.05)
                    continue
                last_mtime_ns = mtime_ns
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Pragma: no-cache\r\n\r\n"
                    + frame_bytes
                    + b"\r\n"
                )
                time.sleep(0.03)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.1)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.post("/api/start")
@app.post("/api/start-monitoring")
def api_start_monitoring():
    return jsonify(fsm.start_monitoring())


@app.post("/api/distance")
def api_distance():
    payload = request.get_json(silent=True) or {}
    raw_distance = payload.get("distance_m")
    try:
        distance_m = float(raw_distance)
    except (TypeError, ValueError):
        return jsonify(fsm.status() | {"ok": False, "message": "distance_m must be numeric."}), 400
    return jsonify(fsm.update_distance(distance_m))


@app.post("/api/recognition")
@app.post("/api/recognition/local")
def api_recognition():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(fsm.status() | {"ok": False, "message": "Request JSON must be an object."}), 400
    return jsonify(_handle_local_recognition(payload))


@app.post("/api/register")
def api_register():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(fsm.status() | {"ok": False, "message": "Request JSON must be an object."}), 400
    return jsonify(fsm.register_new_user(payload))


@app.post("/api/stop-advice")
def api_stop_advice():
    return jsonify(fsm.stop_advice())


@app.post("/api/med/dispense")
def api_med_dispense():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(fsm.status() | {"ok": False, "message": "Request JSON must be an object."}), 400
    return jsonify(fsm.record_dispense(payload))


@app.post("/api/advice/gemini")
@app.post("/api/advice")
def api_advice_gemini():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(fsm.status() | {"ok": False, "message": "Request JSON must be an object."}), 400
    return jsonify(fsm.get_advice_payload(payload))


@app.post("/api/reset")
def api_reset():
    return jsonify(fsm.reset())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

# routes.md

## Route Map (Flask)

- `/` -> `home()` -> renders `templates/index.html`
- `/health` -> `health()`
- `/api/status` -> `api_status()`
- `/api/users` -> `api_users()`
- `/api/start` and `/api/start-monitoring` -> `api_start_monitoring()`
- `/api/distance` -> `api_distance()`
- `/api/recognition` and `/api/recognition/local` -> `api_recognition()`
- `/api/register` -> `api_register()`
- `/api/stop-advice` -> `api_stop_advice()`
- `/api/med/dispense` -> `api_med_dispense()`
- `/api/advice/gemini` -> `api_advice_gemini()`
- `/api/reset` -> `api_reset()`

## Full Router Source

### `app.py`

```python
from flask import Flask, jsonify, render_template, request

from pill_dispenser_fsm import PillDispenserFSM

app = Flask(__name__)
fsm = PillDispenserFSM()


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
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/status")
def api_status():
    return jsonify(fsm.status())


@app.get("/api/users")
def api_users():
    return jsonify(users=fsm.list_users())


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


```

from flask import Flask, jsonify, render_template, request

from pill_dispenser_fsm import PillDispenserFSM

app = Flask(__name__)
fsm = PillDispenserFSM()


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
def api_recognition():
    payload = request.get_json(silent=True) or {}
    match_type = str(payload.get("match_type", ""))
    user_id = payload.get("user_id")
    if user_id is not None:
        user_id = str(user_id)
    return jsonify(fsm.set_recognition_result(match_type=match_type, user_id=user_id))


@app.post("/api/register")
def api_register():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(fsm.status() | {"ok": False, "message": "Request JSON must be an object."}), 400
    return jsonify(fsm.register_new_user(payload))


@app.post("/api/stop-advice")
def api_stop_advice():
    return jsonify(fsm.stop_advice())


@app.post("/api/reset")
def api_reset():
    return jsonify(fsm.reset())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

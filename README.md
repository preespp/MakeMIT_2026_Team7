# MakeMIT_2026_Team7

Healthcare - Sauron - MLH (Gemini API) Track

## Quick Start (Flask Prototype)

### 1) Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Run the server

```bash
python app.py
```

Server URL: `http://localhost:5000`  
Runtime assumption: access the app via `http://127.0.0.1:5000` (HTTP, not HTTPS).

## Confirmed System Architecture

- Jetson runs local RealSense-based face recognition.
- Face recognition result is local, not from cloud auth API.
- ESP32 connects to Jetson over USB serial (`UART`).
- Motors use external battery power rail.
- ESP32 logic path is powered through USB from Jetson.
- Gemini is optional post-dispense advice enhancement.

## FSM Workflow (Current Code)

Detailed states:

1. `WAITING_FOR_USER`
2. `MONITORING_DISTANCE`
3. `FACE_RECOGNITION`
4. `REGISTER_NEW_USER`
5. `REGISTRATION_SUCCESS`
6. `DISPENSING_PILL`
7. `GENERATING_ADVICE`
8. `SPEAKING_ADVICE`
9. `SESSION_SUCCESS`
10. `ERROR`

High-level grouped stages:

1. `IDLE`
2. `AUTHENTICATION`
3. `DISPENSING`
4. `ADVICE_COMPLETION`
5. `FAULT`

## Local Storage (Prototype)

- Face images: `data/faces/<user_id>.jpg`
- User profiles: `data/users/<user_id>.json`
- Dispense logs: `data/logs/dispense_log.jsonl`

Folders are created automatically and gitignored.

## API Routes (Implemented)

- `GET /`: frontend dashboard
- `GET /health`: health check
- `GET /api/status`: full FSM snapshot for UI
- `GET /api/users`: list users
- `POST /api/start-monitoring`: begin monitoring phase
- `POST /api/distance`: update distance (`distance_m`)
- `POST /api/recognition`: submit local recognition branch (`new` or `existing`)
- `POST /api/recognition/local`: alias for local recognition submission
- `POST /api/register`: save user + photo
- `POST /api/med/dispense`: append dispense log payload
- `POST /api/advice/gemini`: return structured advice payload
- `POST /api/stop-advice`: stop speaking flow
- `POST /api/reset`: reset FSM

## Integration Placeholders

In `pill_dispenser_fsm.py`:

- `_dispense_pill(profile)`: replace simulation with real UART command to ESP32
- `_send_uart_dispense_command(...)`: connect to actual serial port/protocol
- `_generate_health_advice(profile)`: replace local fallback with Gemini-backed flow if needed

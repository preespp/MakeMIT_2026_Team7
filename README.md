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

### Windows (PowerShell, no activation script required)

```powershell
python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe app.py
```

### Jetson (recommended target runtime)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Confirmed System Architecture

- Jetson runs local RealSense-based face recognition.
- Face recognition result is local, not from cloud auth API.
- ESP32 connects to Jetson over USB serial (`UART`).
- Motors use external battery power rail.
- ESP32 logic path is powered through USB from Jetson.
- Gemini is optional post-dispense advice enhancement.

## Current Integration Status (Important)

- `Flask + FSM + touchscreen web UI` are integrated and drive the 8 scene pages.
- `face_med_reminder.py` (RealSense + InsightFace) now aligns to the same user storage schema and can bridge events to the Flask FSM API.
- RealSense registration UI is still OpenCV-based (separate from touchscreen registration UI).
- Gemini advice is optional and backend-side with strict JSON parsing + fallback to local rule engine.

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
- Face embeddings (RealSense/InsightFace): `data/embeddings/<user_id>.json`
- Dispense logs: `data/logs/dispense_log.jsonl`
- Legacy RealSense cache (compatibility only): `data/users.json`

Folders are created automatically and gitignored.

## API Routes (Implemented)

- `GET /`: scene router (redirects to current FSM scene at `/ui-scene/<slug>`)
- `GET /dashboard`: legacy shell/debug dashboard (fallback only)
- `GET /health`: health check
- `GET /api/status`: full FSM snapshot for UI
- `GET /api/users`: list users
- `POST /api/start-monitoring`: begin monitoring phase
- `POST /api/distance`: update distance (`distance_m`)
- `POST /api/recognition`: submit local recognition branch (`new` or `existing`)
- `POST /api/recognition/local`: alias for local recognition submission
- `POST /api/register`: save user + photo
- `POST /api/med/dispense`: append dispense log payload
- `POST /api/advice/gemini`: return structured advice payload (Gemini + fallback)
- `POST /api/advice`: neutral alias for advice payload
- `POST /api/stop-advice`: stop speaking flow
- `POST /api/reset`: reset FSM

## RealSense -> FSM Adapter (Jetson / Windows)

`face_med_reminder.py` can bridge local RealSense events to the Flask FSM API:

- `/api/start-monitoring`
- `/api/distance`
- `/api/recognition/local`

Env vars:

- `FSM_API_BASE_URL` (default: `http://127.0.0.1:5000`)
- `FSM_API_BRIDGE_ENABLED` (default: `1`)

This keeps the FSM/UI flow synchronized while preserving local InsightFace model inference on Jetson.

## Gemini Advice Contract (Backend)

The backend now builds a strict JSON prompt using:

- local medication/profile data
- local environment JSON from `general_data/` (weather, air quality, sun/moon, alerts, time)

Expected normalized advice payload shape:

```json
{
  "medication": "Ibuprofen",
  "side_effects": ["stomach discomfort", "nausea", "dizziness"],
  "advice": "Take with food and avoid alcohol today. AQI is elevated, consider limiting outdoor exertion.",
  "source": "gemini",
  "environment_summary": {}
}
```

If Gemini is unavailable or response JSON is invalid, the backend automatically falls back to the local rule engine.

## Integration Placeholders

In `pill_dispenser_fsm.py`:

- `_send_uart_dispense_command(...)`: connect to actual serial port/protocol (currently placeholder ACK)
- ESP32 firmware parser: consume `SAURON_UART_V1` frame (`4` channel counts + checksum)
- Speaker/audio playback module: current TTS is frontend browser-side for kiosk demo

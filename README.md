# MakeMIT_2026_Team7
Healthcare - Sauron - MLH (Gemini API) Track

## Flask App Setup

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

The app will run on `http://localhost:5000`.

## Current Workflow (Web + FSM)

1. Start screen waits in `WAITING_FOR_USER`.
2. `Start Monitoring` enters distance monitoring and shows camera feed.
3. Distance updates keep UI in monitor mode until threshold is reached.
4. Face recognition branch:
   - `new`: open registration form, capture/upload face image, save local JSON + JPG.
   - `existing`: load saved profile, run pill dispense placeholder, then Gemini advice placeholder + speaking.
5. User can press `Stop Advice` to finish early.
6. Success screen appears briefly, then FSM auto-returns to start.

## Local Storage

- Face images are stored as `data/faces/<user_id>.jpg`
- User profiles are stored as `data/users/<user_id>.json`

These folders are gitignored and created automatically.

## API Routes

- `GET /`: frontend dashboard
- `GET /health`: health check
- `GET /api/status`: complete FSM snapshot for UI
- `GET /api/users`: list registered users
- `POST /api/start-monitoring`: enter distance monitoring
- `POST /api/distance`: update detected/simulated distance (`distance_m`)
- `POST /api/recognition`: choose branch (`match_type`: `new` or `existing`, optional `user_id`)
- `POST /api/register`: save new user profile + face image
- `POST /api/stop-advice`: stop spoken advice and complete session
- `POST /api/reset`: manual reset to start state

## Integration Placeholders To Replace Later

In `pill_dispenser_fsm.py`:

- `dispense_pill(profile)` for ESP32 + motor control
- `generate_health_advice(profile)` for Gemini API + context (weather/conditions)
- `speak_advice(advice_text)` and `stop_speaking()` for speaker/TTS control

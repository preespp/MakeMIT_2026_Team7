# pages.md

## / (Main Dashboard + FSM UI)
Entry: `templates/index.html`
Dependencies:
- `templates/index.html`
  - `static/css/style.css`
  - `static/js/app.js`
    - calls API routes defined in `app.py`
- `app.py`
  - `/` route rendering
  - `/api/*` endpoints for state transitions and data

## Key UI States represented on this page
- `WAITING_FOR_USER`
- `MONITORING_DISTANCE`
- `FACE_RECOGNITION`
- `REGISTER_NEW_USER`
- `DISPENSING_PILL` / `GENERATING_ADVICE` / `SPEAKING_ADVICE`
- `SESSION_SUCCESS` / `REGISTRATION_SUCCESS`
- `ERROR`

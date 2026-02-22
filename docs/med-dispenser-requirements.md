# Smart Medication Dispenser Requirements

Draft version: v0.3  
Date: 2026-02-21  
Updated from: clarified hardware constraints and FSM alignment request

## 1. Product Goal

Build a medication dispenser where identity is verified locally on Jetson using RealSense camera input, and dispensing is executed by ESP32-controlled motors with deterministic state-machine control.

## 2. Confirmed Architecture Constraints

1. Face recognition runs locally on Jetson using RealSense camera data.
2. Face authentication is not delegated to external cloud auth APIs.
3. ESP32 is connected to Jetson over USB serial (`UART`).
4. Motor/servo power comes from an external battery rail.
5. ESP32 logic power comes from Jetson USB.
6. Gemini API is used only for post-dispense advice enrichment.

## 3. Hardware Requirements

- Compute node: Jetson (local CV + FSM orchestration + UI/backend service).
- Camera: Intel RealSense for presence/depth and face pipeline input.
- Motor controller: ESP32 (receives dispense commands over UART).
- Actuators: 4 servo/motor channels for medication bins.
- Display: touchscreen for local interaction.
- Power architecture:
1. Jetson + ESP32 control path powered by USB/system supply.
2. Motors powered by separate battery/driver power path.
3. Common ground required between ESP32 and motor driver domain.

## 4. Software Architecture

### 4.1 Jetson Local Services

- RealSense capture and local face recognition.
- FSM controller.
- Touchscreen/web UI service.
- Local data storage and logs.
- Optional Gemini and weather API requests.

### 4.2 ESP32 Firmware

- UART command parser from Jetson.
- Motor channel dispatch and completion ACK/NACK.
- Fault reporting (timeout/jam/channel error).

### 4.3 Backend Responsibilities (Python Service on Jetson)

- Persist users, medication mapping, schedules, and logs.
- Provide UI status endpoints.
- Provide optional advice endpoint (Gemini or local fallback rules).

### 4.4 Prototype vs Target (Implementation Status)

Current prototype (implemented):

- FSM + Flask API + touchscreen web scenes are integrated.
- RealSense/InsightFace local recognition exists and is local-first.
- RealSense-to-FSM API adapter exists for `start/distance/recognition` event bridging.
- User storage is unified at `data/users/*.json` (profiles) and `data/embeddings/*.json` (embeddings).
- Gemini advice endpoint supports strict JSON parsing with local fallback.

Target (not fully implemented yet):

- Full RealSense registration flow posting directly into FSM `/api/register` with camera photo payload.
- Production UART serial transport + ACK/NACK error handling against ESP32 firmware.
- Full prescription scheduling data model and multi-med dispense planning.

## 5. FSM Logic (Code-Aligned)

Detailed internal states:

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

Primary transition logic:

- `WAITING_FOR_USER -> MONITORING_DISTANCE`: user/session starts.
- `MONITORING_DISTANCE -> FACE_RECOGNITION`: RealSense distance threshold reached.
- `FACE_RECOGNITION -> REGISTER_NEW_USER`: local recognition result is `new`.
- `FACE_RECOGNITION -> DISPENSING_PILL`: local recognition result is `existing`.
- `REGISTER_NEW_USER -> REGISTRATION_SUCCESS -> WAITING_FOR_USER`.
- `DISPENSING_PILL -> GENERATING_ADVICE -> SPEAKING_ADVICE -> SESSION_SUCCESS -> WAITING_FOR_USER`.
- `Any state -> ERROR`: safety/hardware/validation failure.

User-facing grouped states:

1. `IDLE` = `WAITING_FOR_USER`
2. `AUTHENTICATION` = `MONITORING_DISTANCE + FACE_RECOGNITION + REGISTER_NEW_USER`
3. `DISPENSING` = `DISPENSING_PILL`
4. `ADVICE_COMPLETION` = `GENERATING_ADVICE + SPEAKING_ADVICE + SESSION_SUCCESS`
5. `FAULT` = `ERROR`

## 6. Frontend Alignment Requirements

- UI must explicitly label recognition as "Jetson local RealSense recognition".
- Recognition screen is an operator simulation/control surface for now:
1. simulate `new user`
2. simulate `existing user`
- Registration form should include medication-to-servo mapping (channel 1-4).
- Dispensing status should show UART/ESP32 context in text feedback.

Implementation note:

- The current 8 exported SuperDesign pages are the primary UI path (`/ui-scene/*`).
- `templates/index.html` / `static/js/app.js` is a legacy shell/debug path (`/dashboard`) and not the primary kiosk flow.

## 7. Interface Contracts

### 7.1 Jetson UI/API (Prototype)

- `POST /api/recognition` (and optional alias `/api/recognition/local`):
accept local recognition result (`new` or `existing` + optional user id).
- `POST /api/register`: store user profile and face snapshot metadata.
- `POST /api/med/dispense`: write dispense log and result.
- `POST /api/advice/gemini`: return structured advice payload.
- `POST /api/advice`: alias of the above for provider-neutral frontend integration.

### 7.1.1 Canonical Registration Schema (Current Prototype)

Canonical profile fields currently used by Flask FSM + frontend:

- required: `name`, `medication`, `servo_channel`, `photo_data_url`
- optional: `age`, `dosage`, `notes`, `schedule_times`, `medications`

Canonical storage:

- profile: `data/users/<user_id>.json`
- face photo: `data/faces/<user_id>.jpg`
- embedding (RealSense/InsightFace): `data/embeddings/<user_id>.json`

Compatibility note:

- Legacy `data/users.json` (RealSense old format) is imported/upserted into canonical storage.

### 7.1.2 RealSense -> Flask Event Payload (Current Bridge)

`POST /api/recognition/local`

- existing user:
  - `{"match_type":"existing","user_id":"<user_id>","source":"REALSENSE_LOCAL","confidence":0.93}`
- new user:
  - `{"match_type":"new","source":"REALSENSE_LOCAL","confidence":0.20}`

### 7.2 Jetson -> ESP32 UART Contract (Target)

Suggested command payload fields:

- `cmd`: `DISPENSE`
- `user_id`
- `channel` (1-4)
- `dose`
- `request_id`

Expected ESP32 response fields:

- `ack`: `true/false`
- `request_id`
- `status`: `OK` or error code (`JAM`, `TIMEOUT`, `BAD_CHANNEL`, `LOW_POWER`)

Prototype frame contract (implemented placeholder in FSM):

- `SAURON_UART_V1`
- 4 channel count fields in one frame (one count per servo channel)
- checksum byte
- allows ESP32 to execute per-channel action counts derived from `servo_channel` + `dosage`

## 8. Data Model (Prototype)

`users`

- `user_id`, `name`, `face_encoding_or_path`, `created_at`

`medications`

- `med_id`, `name`, `servo_channel`, `inventory`

`prescriptions`

- `user_id`, `med_id`, `dosage`, `schedule_time`

`logs`

- `timestamp`, `user_id`, `medication`, `result`, `details`

`embeddings` (prototype extension)

- `user_id`, `embedding[]`, `dim`, `model`, `source`, `updated_at`

## 9. Safety and Reliability Requirements

- No dispense without successful local authentication.
- No dispense if servo channel mapping is missing/invalid.
- UART command must require ACK; failed ACK transitions to error handling.
- API failures (Gemini/weather) must not block dispensing.
- All dispense attempts must be logged.

## 10. Acceptance Criteria

- Local RealSense recognition branch can route `new` and `existing` paths correctly.
- Existing user path triggers UART dispense command logic and logs result.
- Registration stores channel mapping and profile data.
- RealSense local script and Flask FSM share user profile semantics (`id`, `medication`, `dosage`, `servo_channel`) via canonical storage.
- Frontend texts and workflow match the FSM states above.
- Advice flow works with local fallback even if Gemini is unavailable.

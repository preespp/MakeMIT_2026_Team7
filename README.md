# MakeMIT_2026_Team7
Healthcare - Sauron - MLH (Gemini API) Track

## Flask Server Setup

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

Useful routes:
- `GET /` returns a plain text response.
- `GET /health` returns a JSON health check.

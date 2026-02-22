import requests
import json
import os
from datetime import datetime
import pytz
from bs4 import BeautifulSoup  # pip install beautifulsoup4
from zoneinfo import ZoneInfo

# CONFIG
LAT = 42.3600
LON = -71.0925


def detect_default_timezone():
    env_tz = str(os.getenv("TIMEZONE", "")).strip()
    if env_tz:
        return env_tz
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        key = getattr(tzinfo, "key", None)
        if isinstance(key, str) and key.strip():
            return key.strip()
    except Exception:
        pass
    return "America/New_York"


TIMEZONE = detect_default_timezone()

BASE_DIR = "general_data"

FILES = {
    "weather": f"{BASE_DIR}/weather.json",
    "air": f"{BASE_DIR}/air_quality.json",
    "sun": f"{BASE_DIR}/sun.json",
    "moon": f"{BASE_DIR}/moon.json",
    "alerts": f"{BASE_DIR}/alerts.json",
    "time": f"{BASE_DIR}/time.json"
}

def ensure_dir():
    os.makedirs(BASE_DIR, exist_ok=True)

def save_json(data, path):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# 1. WEATHER + WIND (Open-Meteo)
def get_weather():
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": LAT,
            "longitude": LON,
            "current": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation"
        }
        r = requests.get(url, params=params)
        return r.json()
    except Exception as e:
        print("Weather API failed:", e)
        return {}

# 2. AIR QUALITY (Open-Meteo)
def get_air_quality():
    try:
        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params = {
            "latitude": LAT,
            "longitude": LON,
            "current": "pm10,pm2_5,us_aqi"
        }
        r = requests.get(url, params=params)
        return r.json()
    except Exception as e:
        print("Air Quality API failed:", e)
        return {}

# 3. SUNRISE / SUNSET
def get_sun():
    try:
        url = "https://api.sunrise-sunset.org/json"
        params = {
            "lat": LAT,
            "lng": LON,
            "formatted": 0
        }
        r = requests.get(url, params=params)
        return r.json()
    except Exception as e:
        print("Sun API failed:", e)
        return {}

# 4. MOON PHASE (Met.no)
def get_moon():
    try:
        url = "https://api.met.no/weatherapi/sunrise/2.0/.xml"
        params = {
            "lat": LAT,
            "lon": LON,
            "date": datetime.utcnow().date().isoformat(),
            "offset": "+00:00"
        }
        headers = {"User-Agent": "robot-env-monitor"}
        r = requests.get(url, params=params, headers=headers)
        soup = BeautifulSoup(r.content, "xml")
        moon = soup.find("moonphase")
        if moon:
            return {"moonphase": moon.get("value")}
        return {"moonphase": None}
    except Exception as e:
        print("Moon API failed:", e)
        return {"moonphase": None}

# 5. NWS ALERTS (USA)
def get_alerts():
    try:
        url = f"https://api.weather.gov/alerts/active?point={LAT},{LON}"
        headers = {"User-Agent": "robot-env-monitor"}
        r = requests.get(url, headers=headers)
        return r.json()
    except Exception as e:
        print("NWS Alerts API failed:", e)
        return {}

# 6. TIME (local)
def get_time_local():
    try:
        try:
            tz = ZoneInfo(TIMEZONE)
        except Exception:
            tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        return {"datetime": now.isoformat(), "timezone": TIMEZONE}
    except Exception as e:
        print("Time fetch failed:", e)
        return {}

# MAIN
if __name__ == "__main__":
    ensure_dir()
    save_json(get_weather(), FILES["weather"])
    save_json(get_air_quality(), FILES["air"])
    save_json(get_sun(), FILES["sun"])
    save_json(get_moon(), FILES["moon"])
    save_json(get_alerts(), FILES["alerts"])
    save_json(get_time_local(), FILES["time"])
    print("All general environment data saved to general_data/")

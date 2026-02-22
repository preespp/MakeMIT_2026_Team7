import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load .env file
load_dotenv()

# Get API key from environment
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("API key not found!")

genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content("Hello Gemini")

print(response.text)

import json
import os

BASE_DIR = "general_data"

def load_json(filename):
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

weather = load_json("weather.json")
air = load_json("air_quality.json")
sun = load_json("sun.json")
moon = load_json("moon.json")
alerts = load_json("alerts.json")
time_info = load_json("time.json")

prompt = f"""
Hello Gemini! Here is the current environment information:

- Date/Time: {time_info.get('datetime', 'N/A')}
- Temperature: {weather.get('current_weather', {}).get('temperature_2m', 'N/A')} °C
- Wind: {weather.get('current_weather', {}).get('wind_speed_10m', 'N/A')} m/s, {weather.get('current_weather', {}).get('wind_direction_10m', 'N/A')}°
- Precipitation: {weather.get('current_weather', {}).get('precipitation', 'N/A')} mm
- Air Quality Index (US AQI): {air.get('current', {}).get('us_aqi', 'N/A')}
- PM2.5: {air.get('current', {}).get('pm2_5', 'N/A')}
- PM10: {air.get('current', {}).get('pm10', 'N/A')}
- Sunrise: {sun.get('results', {}).get('sunrise', 'N/A')}
- Sunset: {sun.get('results', {}).get('sunset', 'N/A')}
- Moon Phase: {moon.get('moonphase', 'N/A')}
- Alerts: {alerts.get('features', [])[:3]}  # show up to 3 alerts

Please provide **general advice for their daily general health and well-being for this user** based on the current environment (e.g., outdoor safety, visibility, allergies, or general precautions).
"""

# Load API key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("API key not found!")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-flash")

# Generate advice
response = model.generate_content(prompt)
print(response.text)

# import os
# from dotenv import load_dotenv
# import google.generativeai as genai

# # Load API key
# load_dotenv()
# api_key = os.getenv("GEMINI_API_KEY")
# if not api_key:
#     raise ValueError("API key not found!")

# genai.configure(api_key=api_key)
# model = genai.GenerativeModel("gemini-2.5-flash")

# # Generate advice
# response = model.generate_content(prompt)
# print("=== Gemini Advice ===")
# print(response.text)
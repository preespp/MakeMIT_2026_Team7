# Environment Data + Gemini Health Advisor

This project collects **real-time environment data** (weather, air quality, sun/moon info, alerts, local time) for a given location and generates **daily general health advice** using Google Gemini AI.

## Files

### 1. `test_general_info.py`

This script fetches real-time environmental information and saves it locally as JSON files.

**Data collected:**

* **Weather**: Temperature, wind speed & direction, precipitation (from Open-Meteo)
* **Air Quality**: PM2.5, PM10, US AQI (from Open-Meteo Air Quality API)
* **Sun**: Sunrise and sunset times (from sunrise-sunset.org)
* **Moon**: Moon phase (from Met.no XML API)
* **Alerts**: Active weather alerts (from NWS API)
* **Time**: Current local date/time (using `pytz`)

**Output:** JSON files stored in `general_data/`:

```
general_data/
├─ weather.json
├─ air_quality.json
├─ sun.json
├─ moon.json
├─ alerts.json
└─ time.json
```

**Usage:**

```bash
python test_general_info.py
```

This will create the `general_data` folder (if not already present) and populate it with the latest environment data.

---

### 2. `test_gemini.py`

This script now reuses the same backend advice logic as the Flask API (`advice_engine.py`):

- builds the same strict JSON Gemini prompt (`strict_json_v1`)
- loads environment JSON from `general_data/`
- attempts Gemini generation (if configured)
- validates/parses strict JSON
- falls back to local rule-based advice if Gemini is unavailable or invalid

**Steps performed:**

1. Load a sample user profile (from `data/users/*.json` if available).
2. Load environment JSON files from `general_data/`.
3. Build the backend Gemini prompt with strict JSON output requirements.
4. Generate and print a normalized advice payload.

**Usage:**

1. Install project requirements (includes `google-genai`; backend also supports fallback local advice if no key is set):

```bash
pip install -r requirements.txt
```

2. Create a `.env` file with your Gemini API key:

```
GEMINI_API_KEY=your_api_key_here
```

3. Run the script:

```bash
python test_gemini.py
```

4. Output:

- generated prompt (for inspection)
- normalized JSON advice payload (`gemini` source or `local_rule_engine` fallback)

---

## Requirements

* Python 3.9+
* Libraries (project-level):

```bash
pip install -r requirements.txt
```

---

## How It Works Together

1. Run `test_general_info.py` to **fetch and save environment data**.
2. Run `test_gemini.py` to validate the backend-style prompt + JSON parsing flow.
3. You can schedule `test_general_info.py` via cron or Windows Task Scheduler to keep your JSON data updated.

---

## Configuration

* **Location**: Update latitude and longitude in `test_general_info.py`:

```python
LAT = 42.3600
LON = -71.0925
TIMEZONE = "America/New_York"
```

* **Gemini API Key**: Stored in `.env` as `GEMINI_API_KEY`.
* **Optional flags**:
  * `ENABLE_GEMINI_ADVICE=0` to force local fallback
  * `GEMINI_MODEL=gemini-2.5-flash` (default)

---

## Example Output

```
Hello! Here's some general health and well-being advice based on your current environment:

The most critical information is the **Blizzard Warning** that will be in effect for your area from **4 PM EST on Sunday, February 22nd, until 7 AM EST on Tuesday, February 24th.** This is a severe weather event requiring significant precautions.

**Key Advice for Your Health and Well-being:**

1.  **Prepare for and Prioritize Safety During the Blizzard:**
    *   **Stay Indoors:** The warning describes "Blizzard conditions expected," "visibilities may drop below 1/4 mile," and "whiteout conditions." Travel will be "treacherous and potentially life-threatening." **Strongly consider restricting travel to emergencies only.**
    *   **Prepare for Power Outages:** Winds gusting as high as 60 mph and heavy snow (1 to 2 feet) can down power lines. Ensure you have:
        *   Flashlights and extra batteries.
        *   Blankets or sleeping bags.
        *   A charged cell phone and portable chargers.
        *   An emergency kit with non-perishable food and water for at least 72 hours.
        *   Any necessary medications.
    *   **Stay Warm:** If power is lost, dress in layers, and know how to safely use alternative heating sources if you have them, ensuring proper ventilation to prevent carbon monoxide poisoning.
    *   **Avoid Overexertion:** If you must shovel snow after the blizzard, be aware of the heavy nature of snow and avoid overexertion, especially if you have heart conditions.
    *   **Clear Exhaust Vents:** If snow accumulates, ensure your furnace, dryer, and water heater exhaust vents are not blocked to prevent carbon monoxide buildup.

2.  **Current Air Quality is Good:**
    *   Your Air Quality Index (AQI) is 48, which is in the "Good" category. PM2.5 and PM10 levels are also low.
    *   There are no immediate concerns regarding outdoor air quality at this time. However, once the blizzard starts, the primary concern will shift to the extreme weather conditions rather than ambient air quality.

**In Summary:**

The most urgent recommendation is to **prepare diligently for the impending blizzard.** Focus on securing your home, stocking essential supplies, and making arrangements to stay safely indoors during the storm. Your health and well-being will be best protected by avoiding the hazardous conditions outdoors.
```

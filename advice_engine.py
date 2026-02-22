from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import
    load_dotenv = None  # type: ignore

if load_dotenv:
    try:
        load_dotenv()
    except Exception:
        pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_general_context(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parent)
    d = root / "general_data"
    return {
        "weather": _load_json(d / "weather.json"),
        "air_quality": _load_json(d / "air_quality.json"),
        "sun": _load_json(d / "sun.json"),
        "moon": _load_json(d / "moon.json"),
        "alerts": _load_json(d / "alerts.json"),
        "time": _load_json(d / "time.json"),
    }


def _read_env_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    weather = ctx.get("weather", {}) if isinstance(ctx.get("weather"), dict) else {}
    air = ctx.get("air_quality", {}) if isinstance(ctx.get("air_quality"), dict) else {}
    sun = ctx.get("sun", {}) if isinstance(ctx.get("sun"), dict) else {}
    moon = ctx.get("moon", {}) if isinstance(ctx.get("moon"), dict) else {}
    alerts = ctx.get("alerts", {}) if isinstance(ctx.get("alerts"), dict) else {}
    time_info = ctx.get("time", {}) if isinstance(ctx.get("time"), dict) else {}

    weather_current = weather.get("current") or weather.get("current_weather") or {}
    if not isinstance(weather_current, dict):
        weather_current = {}
    air_current = air.get("current") or {}
    if not isinstance(air_current, dict):
        air_current = {}
    sun_results = sun.get("results") or {}
    if not isinstance(sun_results, dict):
        sun_results = {}

    features = alerts.get("features")
    if not isinstance(features, list):
        features = []
    alert_titles: list[str] = []
    for feature in features[:3]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        headline = str(props.get("headline") or props.get("event") or "").strip()
        if headline:
            alert_titles.append(headline)

    return {
        "datetime": time_info.get("datetime"),
        "temperature_c": weather_current.get("temperature_2m"),
        "wind_speed": weather_current.get("wind_speed_10m"),
        "wind_direction": weather_current.get("wind_direction_10m"),
        "precipitation_mm": weather_current.get("precipitation"),
        "aqi_us": air_current.get("us_aqi"),
        "pm25": air_current.get("pm2_5"),
        "pm10": air_current.get("pm10"),
        "sunrise": sun_results.get("sunrise"),
        "sunset": sun_results.get("sunset"),
        "moon_phase": moon.get("moonphase"),
        "alerts": alert_titles,
    }


def _fallback_environment_note(env: dict[str, Any]) -> str:
    alerts = env.get("alerts")
    if isinstance(alerts, list) and alerts:
        return "A weather alert is active today, so follow local safety guidance and avoid unnecessary travel."

    notes: list[str] = []
    try:
        aqi = float(env.get("aqi_us")) if env.get("aqi_us") is not None else None
    except (TypeError, ValueError):
        aqi = None
    try:
        temp_c = float(env.get("temperature_c")) if env.get("temperature_c") is not None else None
    except (TypeError, ValueError):
        temp_c = None
    try:
        precip = float(env.get("precipitation_mm")) if env.get("precipitation_mm") is not None else None
    except (TypeError, ValueError):
        precip = None

    if aqi is not None and aqi >= 100:
        notes.append("Air quality is elevated, so limit strenuous outdoor activity if you feel sensitive.")
    if temp_c is not None and temp_c <= 0:
        notes.append("It is cold outside today, so dress warmly before going out.")
    if precip is not None and precip > 0:
        notes.append("There is precipitation today, so be careful on slippery surfaces.")

    return " ".join(notes[:2]).strip()


def build_gemini_advice_prompt(
    profile: dict[str, Any],
    general_context: dict[str, Any] | None = None,
) -> str:
    profile = profile or {}
    env = _read_env_summary(general_context or {})
    medication = str(profile.get("medication", "unknown medication")).strip() or "unknown medication"
    name = str(profile.get("name", "user")).strip() or "user"
    dosage = str(profile.get("dosage", "")).strip()
    schedule_times = profile.get("schedule_times")
    if not isinstance(schedule_times, list):
        schedule_times = []

    return (
        "You are a professional medication safety assistant for a smart pill dispenser.\n"
        "Return ONLY strict JSON. No markdown. No extra text.\n"
        "JSON schema:\n"
        "{\"side_effects\": [\"...\", \"...\", \"...\"], \"advice\": \"...\"}\n\n"
        "Constraints:\n"
        "- side_effects: array of 1-3 short common side effects in plain English\n"
        "- advice: 1-2 concise sentences that combine medication safety + today's environment context\n"
        "- Keep language simple and safe; do not diagnose\n\n"
        f"User name: {name}\n"
        f"Medication: {medication}\n"
        f"Dosage: {dosage or 'unknown'}\n"
        f"Schedule times: {', '.join([str(t) for t in schedule_times]) or 'unknown'}\n\n"
        "Today's environment context (from local weather/time APIs):\n"
        f"- Local datetime: {env.get('datetime', 'N/A')}\n"
        f"- Temperature (C): {env.get('temperature_c', 'N/A')}\n"
        f"- Wind speed: {env.get('wind_speed', 'N/A')}\n"
        f"- Wind direction: {env.get('wind_direction', 'N/A')}\n"
        f"- Precipitation (mm): {env.get('precipitation_mm', 'N/A')}\n"
        f"- Air Quality US AQI: {env.get('aqi_us', 'N/A')}\n"
        f"- PM2.5: {env.get('pm25', 'N/A')}\n"
        f"- PM10: {env.get('pm10', 'N/A')}\n"
        f"- Sunrise: {env.get('sunrise', 'N/A')}\n"
        f"- Sunset: {env.get('sunset', 'N/A')}\n"
        f"- Moon phase: {env.get('moon_phase', 'N/A')}\n"
        f"- Active alerts (up to 3): {json.dumps(env.get('alerts', []), ensure_ascii=False)}\n"
    )


def _extract_json_candidate(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    # direct parse
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # fenced block
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fence:
        try:
            obj = json.loads(fence.group(1))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

    # first {...}
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        snippet = raw[start : end + 1]
        try:
            obj = json.loads(snippet)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_gemini_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    side_effects = obj.get("side_effects")
    advice = obj.get("advice")

    if isinstance(side_effects, str):
        side_effects = [s.strip() for s in re.split(r"[,\n;]+", side_effects) if s.strip()]
    if not isinstance(side_effects, list):
        return None
    normalized_side_effects: list[str] = []
    for item in side_effects[:3]:
        txt = str(item or "").strip()
        if txt:
            normalized_side_effects.append(txt)
    if not normalized_side_effects:
        return None

    advice_text = str(advice or "").strip()
    if not advice_text:
        return None

    return {
        "side_effects": normalized_side_effects[:3],
        "advice": advice_text,
    }


def _gemini_text_with_google_genai(prompt: str, api_key: str, model_name: str) -> str | None:
    try:
        # New SDK (`google-genai`) path.
        from google import genai  # type: ignore
    except Exception:
        return None
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model_name, contents=prompt)
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text
        # Fallback for alternate response shapes.
        if hasattr(response, "candidates"):
            for cand in getattr(response, "candidates", []) or []:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if parts:
                    combined = "".join(str(getattr(p, "text", "")) for p in parts)
                    if combined.strip():
                        return combined
        return None
    except Exception:
        return None


def _gemini_text_with_google_generativeai(prompt: str, api_key: str, model_name: str) -> str | None:
    try:
        import google.generativeai as genai  # type: ignore
    except Exception:
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text
        return None
    except Exception:
        return None


def generate_advice_payload(
    profile: dict[str, Any],
    *,
    fallback_builder: Callable[[dict[str, Any]], dict[str, Any]],
    general_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns normalized payload:
      {
        "medication": "...",
        "side_effects": [...],
        "advice": "...",
        "source": "gemini" | "local_rule_engine",
        "environment_summary": {...}
      }
    """
    base_fallback = fallback_builder(profile)
    if not isinstance(base_fallback, dict):
        base_fallback = {
            "medication": str(profile.get("medication", "your medication")),
            "side_effects": ["drowsiness"],
            "advice": "Stay hydrated.",
            "source": "local_rule_engine",
        }
    ctx = general_context or load_general_context()
    env_summary = _read_env_summary(ctx)

    api_key = str(os.getenv("GEMINI_API_KEY", "")).strip()
    enabled_env = str(os.getenv("ENABLE_GEMINI_ADVICE", "1")).strip().lower()
    gemini_enabled = enabled_env not in {"0", "false", "no", "off"}
    model_name = str(os.getenv("GEMINI_MODEL", "gemini-2.5-flash")).strip() or "gemini-2.5-flash"

    if not gemini_enabled or not api_key:
        payload = dict(base_fallback)
        env_note = _fallback_environment_note(env_summary)
        if env_note:
            advice_text = str(payload.get("advice", "")).strip()
            payload["advice"] = (f"{advice_text} {env_note}" if advice_text else env_note).strip()
        payload["environment_summary"] = env_summary
        payload.setdefault("source", "local_rule_engine")
        return payload

    prompt = build_gemini_advice_prompt(profile, ctx)
    text = (
        _gemini_text_with_google_genai(prompt, api_key, model_name)
        or _gemini_text_with_google_generativeai(prompt, api_key, model_name)
    )
    parsed = _normalize_gemini_payload(_extract_json_candidate(text or "") or {})
    if not parsed:
        payload = dict(base_fallback)
        env_note = _fallback_environment_note(env_summary)
        if env_note:
            advice_text = str(payload.get("advice", "")).strip()
            payload["advice"] = (f"{advice_text} {env_note}" if advice_text else env_note).strip()
        payload["environment_summary"] = env_summary
        payload.setdefault("source", "local_rule_engine")
        payload["gemini_error"] = "invalid_or_empty_response"
        return payload

    return {
        "medication": str(profile.get("medication", base_fallback.get("medication", "your medication"))),
        "side_effects": parsed["side_effects"],
        "advice": parsed["advice"],
        "source": "gemini",
        "environment_summary": env_summary,
        "model": model_name,
        "prompt_format": "strict_json_v1",
    }

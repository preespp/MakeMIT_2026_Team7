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
        "timezone": time_info.get("timezone"),
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
    language = str(profile.get("language", "en-US")).strip() or "en-US"
    timezone_name = str(profile.get("timezone", "")).strip() or str(env.get("timezone", "")).strip() or "unknown"
    schedule_times = profile.get("schedule_times")
    if not isinstance(schedule_times, list):
        schedule_times = []
    medications = profile.get("medications")
    if not isinstance(medications, list):
        medications = []
    schedule_ctx = profile.get("schedule_context")
    if not isinstance(schedule_ctx, dict):
        schedule_ctx = {}
    due_now = schedule_ctx.get("due_now") if isinstance(schedule_ctx.get("due_now"), list) else []
    upcoming = schedule_ctx.get("upcoming") if isinstance(schedule_ctx.get("upcoming"), list) else []
    dispense_plan = profile.get("dispense_plan")
    if not isinstance(dispense_plan, dict):
        dispense_plan = {}
    dispense_items = dispense_plan.get("items") if isinstance(dispense_plan.get("items"), list) else []
    dispensed_lines: list[str] = []
    for item in dispense_items[:4]:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("name", "")).strip() or str(item.get("medication", "")).strip() or "unknown"
        dispensed_lines.append(
            f"- {item_name} | channel={item.get('servo_channel', '?')} | "
            f"count={item.get('count', item.get('dose_count', '?'))} | "
            f"dosage={str(item.get('dosage','')).strip() or str(item.get('dose','')).strip() or 'unknown'}"
        )
    multi_med_event = len([x for x in dispensed_lines if x]) >= 2 or len([m for m in due_now if isinstance(m, dict)]) >= 2

    meds_lines: list[str] = []
    for med in medications[:4]:
        if not isinstance(med, dict):
            continue
        med_name = str(med.get("name", "")).strip()
        if not med_name:
            continue
        meds_lines.append(
            f"- {med_name} | dosage={str(med.get('dosage','')).strip() or 'unknown'} | "
            f"channel={med.get('servo_channel','?')} | times={json.dumps(med.get('times', []), ensure_ascii=False)}"
        )
    due_lines = []
    for med in due_now[:4]:
        if not isinstance(med, dict):
            continue
        due_lines.append(
            f"- {med.get('name','unknown')} @ {med.get('matched_time','?')} "
            f"(channel {med.get('servo_channel','?')}, delta {med.get('minutes_delta','?')} min)"
        )
    upcoming_lines = []
    for med in upcoming[:4]:
        if not isinstance(med, dict):
            continue
        upcoming_lines.append(
            f"- {med.get('name','unknown')} @ {med.get('matched_time','?')} "
            f"(channel {med.get('servo_channel','?')}, in {med.get('minutes_delta','?')} min)"
        )

    return (
        "You are a professional medication safety assistant for a smart pill dispenser.\n"
        "This response is shown once immediately after the dispenser has dispensed medication for the current session.\n"
        "Return ONLY strict JSON. No markdown. No extra text.\n"
        "JSON schema:\n"
        "{\"side_effects\": [\"...\", \"...\", \"...\"], "
        "\"advice\": \"...\", "
        "\"schedule_guidance\": [\"...\"], "
        "\"environment_guidance\": [\"...\"]}\n\n"
        "Constraints:\n"
        "- side_effects: array of 1-3 short common side effects in plain English\n"
        "- advice: 2-4 concise sentences for THIS medication-taking event only (immediate, practical, context-aware)\n"
        "- advice must combine: medication type/dose + likely side effects + today's environment/time context when relevant\n"
        "- advice should include at least one immediate action and/or one avoid/do-not-do suggestion when appropriate\n"
        "- If drowsiness/lightheadedness is plausible, mention avoiding driving, machinery, or risky activity until the user knows how they feel\n"
        "- If due_now is empty, treat this as a possible manual/unscheduled dose and include a brief timing caution in schedule_guidance or advice\n"
        "- If 2 or more medications are dispensed now OR due now in the same session, explicitly consider combination effects / additive side effects (for example: drowsiness, dizziness, stomach irritation, dehydration risk) and mention the most relevant caution(s)\n"
        "- In multi-medication situations, prioritize practical safety guidance over exhaustive lists, and note uncertainty conservatively if exact interaction data is not provided\n"
        "- If a potentially risky combination effect is plausible, say what the user should avoid/do right now (e.g., avoid driving, alcohol, or strenuous activity; monitor for worsening symptoms)\n"
        "- Do NOT use assistant persona/filler phrases (e.g., 'I'll be waiting for your next cycle')\n"
        "- Do NOT make strong pharmacokinetic claims (e.g., 'maximum absorption') unless the provided context explicitly supports it\n"
        "- schedule_guidance: 0-3 short actionable bullets about timing / due-now / next doses\n"
        "- environment_guidance: 0-3 short actionable bullets about weather/air/alerts\n"
        "- Keep language simple, safe, and non-diagnostic\n\n"
        f"User name: {name}\n"
        f"Preferred language: {language}\n"
        f"Profile timezone: {timezone_name}\n"
        f"Medication: {medication}\n"
        f"Dosage: {dosage or 'unknown'}\n"
        f"Schedule times: {', '.join([str(t) for t in schedule_times]) or 'unknown'}\n\n"
        "Current dispense event (this session):\n"
        f"- Multi-medication session likely: {'yes' if multi_med_event else 'no'}\n"
        f"- Dispense summary text: {dispense_plan.get('summary_medications_text', 'N/A')}\n"
        f"- Dispense items:\n{chr(10).join(dispensed_lines) if dispensed_lines else '- No structured dispense item list available'}\n\n"
        "Registered medication schedule (up to 4 chambers):\n"
        f"{chr(10).join(meds_lines) if meds_lines else '- No structured medication list available'}\n\n"
        "Current schedule context:\n"
        f"- Local datetime (schedule engine): {schedule_ctx.get('datetime_local', 'N/A')}\n"
        "- This advice should reflect what is due now vs upcoming and the current local time context.\n"
        f"- Due now medications:\n{chr(10).join(due_lines) if due_lines else '- None due now'}\n"
        f"- Upcoming medications (next 120 min):\n{chr(10).join(upcoming_lines) if upcoming_lines else '- None upcoming'}\n\n"
        "Today's environment context (from local weather/time APIs):\n"
        f"- Local datetime: {env.get('datetime', 'N/A')}\n"
        f"- Local timezone: {env.get('timezone', 'N/A')}\n"
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
    schedule_guidance = obj.get("schedule_guidance")
    environment_guidance = obj.get("environment_guidance")

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

    def _normalize_short_list(value: Any) -> list[str]:
        if isinstance(value, str):
            value = [s.strip() for s in re.split(r"[,\n;]+", value) if s.strip()]
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value[:3]:
            txt = str(item or "").strip()
            if txt:
                out.append(txt)
        return out

    return {
        "side_effects": normalized_side_effects[:3],
        "advice": advice_text,
        "schedule_guidance": _normalize_short_list(schedule_guidance),
        "environment_guidance": _normalize_short_list(environment_guidance),
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
        "schedule_guidance": [...],
        "environment_guidance": [...],
        "schedule_summary": {...},
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
    schedule_ctx = profile.get("schedule_context") if isinstance(profile.get("schedule_context"), dict) else {}
    schedule_summary = {
        "datetime_local": schedule_ctx.get("datetime_local"),
        "timezone": profile.get("timezone") or schedule_ctx.get("timezone"),
        "due_now": schedule_ctx.get("due_now", []),
        "upcoming": schedule_ctx.get("upcoming", []),
    }

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
        payload["schedule_summary"] = schedule_summary
        payload.setdefault("source", "local_rule_engine")
        payload.setdefault("schedule_guidance", [])
        payload.setdefault("environment_guidance", [])
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
        payload["schedule_summary"] = schedule_summary
        payload.setdefault("source", "local_rule_engine")
        payload.setdefault("schedule_guidance", [])
        payload.setdefault("environment_guidance", [])
        payload["gemini_error"] = "invalid_or_empty_response"
        return payload

    return {
        "medication": str(profile.get("medication", base_fallback.get("medication", "your medication"))),
        "side_effects": parsed["side_effects"],
        "advice": parsed["advice"],
        "schedule_guidance": parsed.get("schedule_guidance", []),
        "environment_guidance": parsed.get("environment_guidance", []),
        "source": "gemini",
        "environment_summary": env_summary,
        "schedule_summary": schedule_summary,
        "model": model_name,
        "prompt_format": "strict_json_v1",
    }

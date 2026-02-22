import json
from pathlib import Path

from advice_engine import build_gemini_advice_prompt, generate_advice_payload, load_general_context


def local_fallback(profile):
    medication = str(profile.get("medication", "your medication")).strip() or "your medication"
    return {
        "medication": medication,
        "side_effects": ["drowsiness", "stomach discomfort", "mild headache"],
        "advice": "Drink more water and avoid intense activity if you feel unwell.",
        "source": "local_rule_engine",
    }


def load_sample_profile():
    users_dir = Path("data") / "users"
    for path in sorted(users_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {
        "id": "demo-user",
        "name": "Demo User",
        "age": "65",
        "medication": "Ibuprofen",
        "dosage": "2 pills",
        "servo_channel": 1,
        "schedule_times": ["08:00"],
    }


if __name__ == "__main__":
    profile = load_sample_profile()
    ctx = load_general_context()

    prompt = build_gemini_advice_prompt(profile, ctx)
    print("=== Gemini Prompt (strict_json_v1) ===")
    print(prompt)
    print()

    payload = generate_advice_payload(profile, fallback_builder=local_fallback, general_context=ctx)
    print("=== Advice Payload ===")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


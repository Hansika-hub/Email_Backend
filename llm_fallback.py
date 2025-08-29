import os
import json
from typing import Optional, Dict

import google.generativeai as genai


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash")


def _configure_model():
    if not GOOGLE_API_KEY:
        return None
    genai.configure(api_key=GOOGLE_API_KEY)
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL_ID,
        system_instruction=(
            "You extract event info from emails. "
            "Output ONLY valid JSON: "
            '{"event_name": string|null, "date": "YYYY-MM-DD"|null, "time": "HH:MM"|null, "venue": string|null}. '
            "No extra text."
        ),
    )


_MODEL = _configure_model()


def extract_with_gemini(subject: str, cleaned_text: str, timeout_seconds: float = 4.0) -> Optional[Dict[str, object]]:
    if not _MODEL:
        return None
    prompt = f"Subject: {subject or ''}\n\nBody:\n{(cleaned_text or '')[:6000]}"
    try:
        resp = _MODEL.generate_content(
            prompt,
            generation_config={
                "temperature": 0,
                "response_mime_type": "application/json",
            },
            request_options={"timeout": timeout_seconds},
        )
        text = (resp.text or "").strip().strip("`")
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return {
            "event_name": data.get("event_name"),
            "date": data.get("date"),
            "time": data.get("time"),
            "venue": data.get("venue"),
            "source": "gemini",
            "confidence": 0.8,
        }
    except Exception:
        return None



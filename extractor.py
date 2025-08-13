import os
import re
import json
from typing import Any, Dict, List, Optional
import logging
from datetime import datetime, timedelta, timezone
import google.generativeai as genai

# Debug logging toggle
DEBUG_EXTRACT = os.getenv("DEBUG_NER", "0") not in (None, "", "0", "false", "False")
logger = logging.getLogger("extract")
if DEBUG_EXTRACT:
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        _h = logging.StreamHandler()
        _h.setLevel(logging.INFO)
        _h.setFormatter(logging.Formatter("[EXTRACT] %(message)s"))
        logger.addHandler(_h)
    logger.propagate = False


def _dlog(msg: str):
    if DEBUG_EXTRACT:
        logger.info(msg)


# ---------- Event Name Extraction from Subject ----------
def clean_event_name(subject: Optional[str]) -> Optional[str]:
    if subject is None:
        return None
    s = subject.strip()
    s = re.sub(r'^(re:|fwd:|fw:)\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ---------- Gemini configuration and call ----------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


def _configure_gemini() -> bool:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        _dlog("Gemini API key not set")
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        _dlog(f"Failed to configure Gemini: {e}")
        return False


def _call_gemini(subject: str, body: str) -> Optional[Dict[str, Optional[str]]]:
    if not _configure_gemini():
        return None
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={
            "temperature": 0,
            "response_mime_type": "application/json"
        }
    )
    system = (
        "Extract event details from the email. Use the subject as the event name. "
        "Return STRICT JSON object with exactly these keys: "
        "event_name (string), date (YYYY-MM-DD or 'na'), time (HH:MM 24h or 'na'), venue (string or 'na'). "
        "If a value is missing/unknown, use 'na'. Do not include any other keys or text."
    )
    content = f"Subject: {subject}\n\nBody: {body[:5000]}"
    try:
        resp = model.generate_content([system, content])
        txt = (resp.text or "").strip()
        # Strip code fences if present
        if txt.startswith("```"):
            txt = txt.strip("`\n ")
            if txt.lower().startswith("json"):
                txt = txt[4:].strip()
        data = json.loads(txt)

        def norm(val: Optional[str]) -> str:
            if val is None:
                return "na"
            s = str(val).strip()
            return "na" if s.lower() in {"", "na", "n/a", "null", "none"} else s

        return {
            "event_name": norm(data.get("event_name")),
            "date": norm(data.get("date")),
            "time": norm(data.get("time")),
            "venue": norm(data.get("venue")),
        }
    except Exception as e:
        try:
            _dlog(f"Gemini generation failed: {e}; raw= {(resp.text if 'resp' in locals() else '')[:500]}")
        except Exception:
            _dlog(f"Gemini generation failed: {e}")
        return None


def _build_gcal_event(event_name: Optional[str], date_str: Optional[str], time_str: Optional[str], venue: Optional[str], tz: str = "UTC") -> Optional[Dict[str, Any]]:
    if not (event_name and date_str and time_str):
        return None
    if str(date_str).lower() == "na" or str(time_str).lower() == "na":
        return None
    try:
        time_full = time_str if len(time_str) > 5 else f"{time_str}:00"
        start_dt = datetime.fromisoformat(f"{date_str}T{time_full}")
        end_dt = start_dt + timedelta(hours=1)
        start_iso = start_dt.replace(tzinfo=timezone.utc).isoformat()
        end_iso = end_dt.replace(tzinfo=timezone.utc).isoformat()
        return {
            "summary": event_name,
            "location": None if (venue is None or str(venue).lower() == "na") else venue,
            "start": {"dateTime": start_iso, "timeZone": tz},
            "end": {"dateTime": end_iso, "timeZone": tz},
        }
    except Exception as e:
        _dlog(f"Failed building gcal event: {e}")
        return None


# ---------- Main Extraction Function ----------
def extract_event_details(subject: Optional[str], body: Optional[str]) -> Dict[str, Optional[str]]:
    subj = clean_event_name(subject or "")
    text = (body or "").strip()
    extracted = _call_gemini(subj, text) or {
        "event_name": subj,
        "date": "na",
        "time": "na",
        "venue": "na",
    }
    if not extracted.get("event_name"):
        extracted["event_name"] = subj
    # Attach Google Calendar event only when both date and time are present (not 'na')
    if extracted.get("date", "na").lower() != "na" and extracted.get("time", "na").lower() != "na":
        extracted["gcal_event"] = _build_gcal_event(
            extracted.get("event_name"), extracted.get("date"), extracted.get("time"), extracted.get("venue")
        )
    else:
        extracted["gcal_event"] = None
    return extracted


def count_event_fields(details: Dict[str, Optional[str]]) -> int:
    present = 0
    for key in ("date", "time", "venue"):
        value = details.get(key)
        if value and str(value).strip() and str(value).lower() != "na":
            present += 1
    return present


def is_event_like(details: Dict[str, Optional[str]], minimum_required: int = 2) -> bool:
    return count_event_fields(details) >= max(0, int(minimum_required))


def count_all_fields(details: Dict[str, Optional[str]]) -> int:
    present = 0
    # Include event_name in count in addition to date/time/venue
    for key in ("event_name", "date", "time", "venue"):
        value = details.get(key)
        if value and str(value).strip() and str(value).lower() != "na":
            present += 1
    return present


def has_date_and_time(details: Dict[str, Optional[str]]) -> bool:
    d = details.get("date")
    t = details.get("time")
    return bool(d and t and str(d).lower() != "na" and str(t).lower() != "na")


def should_remind(details: Dict[str, Optional[str]]) -> bool:
    # Always treat as a potential event; caller can decide calendar by has_date_and_time
    return True


# ---------- Test ----------
if __name__ == "__main__":
    subj = "Re: [Reminder] Climate Action 2025 - 19 Nov 2025 10:00 AM"
    body = "Join us for the Climate Action 2025 conference on 19 Nov 2025 at 10:00 AM at Global Sustainability Center."
    print(extract_event_details(subj, body))

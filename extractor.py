import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple
import requests
import logging

# Debug logging toggle
DEBUG_NER = os.getenv("DEBUG_NER", "0") not in (None, "", "0", "false", "False")
logger = logging.getLogger("ner")
if DEBUG_NER:
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        _h = logging.StreamHandler()
        _h.setLevel(logging.INFO)
        _h.setFormatter(logging.Formatter("[NER] %(message)s"))
        logger.addHandler(_h)
    logger.propagate = False

def _dlog(msg: str):
    if DEBUG_NER:
        logger.info(msg)

# ---------- Event Name Extraction from Subject ----------
def clean_event_name(subject):
    if not subject:
        return None
    
    # Remove common prefixes
    subject = re.sub(r'^(re:|fwd:|\[.*?\])\s*', '', subject, flags=re.IGNORECASE)
    
    # Remove trailing date/time if present
    subject = re.sub(
        r'\b(\d{1,2}(\s|-|/)\d{1,2}(\s|-|/)\d{2,4}|\d{1,2}:\d{2}(\s?(AM|PM))?)$',
        '',
        subject,
        flags=re.IGNORECASE
    )
    
    # Remove excessive spaces
    subject = re.sub(r'\s+', ' ', subject).strip()
    
    # Capitalize properly
    return subject.title()


# ---------- Regex Date & Time Extraction (lightweight fallback) ----------
DATE_REGEX = r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{2,4})?)\b"
TIME_REGEX = r"\b(?:\d{1,2}:[0-5]\d|\d{1,2}\s?(?:AM|PM|am|pm))\b"

def extract_date_time(text):
    dates = re.findall(DATE_REGEX, text)
    times = re.findall(TIME_REGEX, text)
    return dates[0] if dates else None, times[0] if times else None


# ---------- Venue Extraction Using Regex (fallback) ----------
VENUE_KEYWORDS = [
    "hall", "auditorium", "room", "centre", "center", "complex",
    "stadium", "building", "block", "lab", "library", "theatre",
    "theater", "gym", "campus", "conference room", "banquet", "park",
    "ground", "lawn"
]

VENUE_REGEX = re.compile(
    r"\b(?:Hall|Room|Block|Building|Centre|Center|Auditorium|Stadium|Theatre|Theater|Lab|Library|Gym|Campus|Park|Ground|Lawn)"
    r"(?:\s+[A-Za-z0-9&\-]+){0,5}",
    re.IGNORECASE
)

def extract_venue(text: str) -> Optional[str]:
    candidates: List[str] = []
    for match in VENUE_REGEX.findall(text or ""):
        cleaned = match.strip()
        if cleaned:
            candidates.append(cleaned)
    # Keyword-based simple scan
    for line in (text or "").splitlines():
        l = line.strip()
        if len(l) < 200 and any(kw in l.lower() for kw in VENUE_KEYWORDS):
            candidates.append(l)
    if candidates:
        v = candidates[0]
        v = re.sub(r"\bat\s+\d{1,2}(:[0-5]\d)?\s?(AM|PM|am|pm)\b", "", v)
        v = re.sub(r"\b\d{1,2}(:[0-5]\d)?\s?(AM|PM|am|pm)\b", "", v)
        v = v.strip(",;:- ")
        return v or candidates[0]
    return None


# ---------- Hugging Face Inference API (primary) ----------
HF_MODEL_ID = os.getenv("HF_MODEL_ID", "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction")
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL_ID}"

def _call_hf_ner(text: str, timeout_seconds: int = 8) -> Optional[List[Dict[str, Any]]]:
    token = os.getenv("HUGGINGFACE_API_TOKEN") or os.getenv("HF_TOKEN")
    try:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            _dlog("Calling HF Inference API with token")
        else:
            _dlog("Calling HF Inference API anonymously (no token)")
        payload = {"inputs": text, "options": {"wait_for_model": True}}
        resp = requests.post(HF_API_URL, headers=headers, json=payload, timeout=timeout_seconds)
        _dlog(f"HF response status: {resp.status_code}")
        if resp.status_code != 200:
            try:
                err = resp.json()
                _dlog(f"HF error body: {err}")
            except Exception:
                _dlog("HF error: non-JSON response")
            return None
        data = resp.json()
        # API can return a list or nested list depending on the pipeline; normalize to list
        if isinstance(data, dict) and data.get("error"):
            _dlog(f"HF returned error: {data.get('error')}")
            return None
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
            return data[0]
        if isinstance(data, list):
            return data
        return None
    except Exception:
        _dlog("HF call raised exception; falling back")
        return None


def _aggregate_entities(entities: List[Dict[str, Any]]) -> Dict[str, str]:
    # Merge adjacent tokens of the same entity_group
    if not entities:
        return {}
    # Some APIs use 'entity' like 'B-DATE', others 'entity_group' like 'DATE'
    normalized: List[Dict[str, Any]] = []
    for ent in entities:
        group = ent.get("entity_group") or (ent.get("entity") or "").split("-")[-1]
        normalized.append({
            "group": group,
            "start": ent.get("start"),
            "end": ent.get("end"),
            "word": ent.get("word") or ent.get("token") or "",
            "score": ent.get("score", 0.0)
        })

    normalized.sort(key=lambda e: (e.get("start") is None, e.get("start", 0)))

    merged: List[Dict[str, Any]] = []
    for ent in normalized:
        if not merged:
            merged.append(ent.copy())
            continue
        last = merged[-1]
        if ent["group"] == last["group"] and last.get("end") == ent.get("start"):
            last["end"] = ent.get("end")
            last["word"] = (last.get("word") or "") + ("" if ent.get("word", "").startswith("##") else " ") + ent.get("word", "")
        else:
            merged.append(ent.copy())

    # Map groups to fields
    fields: Dict[str, str] = {}
    def assign_first(key: str, value: str):
        if value and key not in fields:
            fields[key] = value.replace("##", "").strip()

    for m in merged:
        g = (m.get("group") or "").upper()
        text_val = (m.get("word") or "").replace("##", "").strip()
        if not text_val:
            continue
        if g in {"DATE", "DATETIME"}:
            assign_first("date", text_val)
        elif g in {"TIME"}:
            assign_first("time", text_val)
        elif g in {"LOC", "LOCATION", "VENUE", "FAC", "GPE"}:
            assign_first("venue", text_val)

    return fields


# ---------- Main Extraction Function ----------
def extract_event_details(subject: Optional[str], body: Optional[str]) -> Dict[str, Optional[str]]:
    text = (body or "").strip()
    event_name = clean_event_name(subject)

    # Primary: Hugging Face Inference API NER
    ner_entities = _call_hf_ner(text)
    if ner_entities:
        ner_fields = _aggregate_entities(ner_entities)
        date = ner_fields.get("date")
        time = ner_fields.get("time")
        venue = ner_fields.get("venue")
        _dlog(f"Using HF NER fields: date='{date}', time='{time}', venue='{venue}'")
    else:
        # Fallback: lightweight regex extractor
        date, time = extract_date_time(text)
        venue = extract_venue(text)
        _dlog(f"Using regex fallback: date='{date}', time='{time}', venue='{venue}'")

    # Light normalization of time strings
    if time:
        t = str(time).strip()
        if re.fullmatch(r"\d{1,2}", t):
            t = f"{t}:00"
        t = t.upper().replace(".", "")
        t = re.sub(r"\s+", " ", t)
        time = t

    return {
        "event_name": event_name,
        "date": date,
        "time": time,
        "venue": venue
    }


# ---------- Test ----------
if __name__ == "__main__":
    subj = "Re: [Reminder] Climate Action 2025 - 19 Nov 2025 10:00 AM"
    body = "Join us for the Climate Action 2025 conference on 19 Nov 2025 at 10:00 AM at Global Sustainability Center."
    print(extract_event_details(subj, body))

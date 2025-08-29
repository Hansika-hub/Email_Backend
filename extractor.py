import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from dateparser.search import search_dates
import datetime as _dt
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


def _normalize_date(d: _dt.date) -> str:
    return d.strftime("%Y-%m-%d")

def _normalize_time(t: _dt.time) -> str:
    return t.strftime("%H:%M")

def _clean_text(html_or_text: Optional[str]) -> str:
    if not html_or_text:
        return ""
    # If it looks like HTML, strip tags conservatively
    txt = html_or_text
    if "<" in txt and ">" in txt:
        try:
            soup = BeautifulSoup(txt, "html.parser")
            txt = soup.get_text(" ")
        except Exception:
            pass
    # Collapse whitespace
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def _pick_best_datetime(text: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Return (date_str, time_str, best_index) using dateparser.search_dates.
    Picks the first plausible future occurrence if available; otherwise first occurrence.
    best_index is the index in the tokenized lines for proximity heuristics.
    """
    if not text:
        return None, None, None
    # We'll also keep line indices to help venue proximity
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    joined = "\n".join(lines)
    try:
        results = search_dates(joined, settings={
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
        }) or []
    except Exception:
        results = []

    if not results:
        return None, None, None

    # Build candidates with positions by mapping match string to nearest line index
    candidates: List[Tuple[_dt.datetime, int, str]] = []
    for match_text, dt in results:
        # Find a line that contains match_text
        idx = next((i for i, l in enumerate(lines) if match_text in l), -1)
        candidates.append((dt, idx, match_text))

    # Prefer future datetimes, then first
    now = _dt.datetime.now()
    future = [c for c in candidates if c[0] >= now]
    best = future[0] if future else candidates[0]
    best_dt, best_idx, best_text = best

    date_str = _normalize_date(best_dt.date())

    # Only consider time if the matched text appears to include a time token
    def _contains_time_token(s: str) -> bool:
        return bool(re.search(r"(\d{1,2}:\d{2})|(\b\d{1,2}\s?(AM|PM)\b)", s, flags=re.IGNORECASE))

    time_str = None
    if _contains_time_token(best_text):
        # Convert to 24h string
        time_str = _normalize_time(best_dt.time())
    return date_str, time_str, (best_idx if best_idx >= 0 else None)

def _extract_time_near_anchor(text: str, anchor_line_index: Optional[int]) -> Optional[str]:
    if anchor_line_index is None:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    start = max(0, anchor_line_index - 3)
    end = min(len(lines), anchor_line_index + 4)
    time_pattern = re.compile(r"\b(\d{1,2})(?::([0-5]\d))?\s*(AM|PM)?\b", re.IGNORECASE)
    for i in range(start, end):
        line = lines[i]
        # skip lines that look like dates-only (e.g., 2025-08-29)
        if re.search(r"\d{4}-\d{2}-\d{2}", line):
            continue
        m = time_pattern.search(line)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            ampm = (m.group(3) or "").upper()
            if ampm == "PM" and hh < 12:
                hh += 12
            if ampm == "AM" and hh == 12:
                hh = 0
            return f"{hh:02d}:{mm:02d}"
    # handle ranges like 4–6pm by finding the first time-like number with pm/am suffix elsewhere in line
    range_pattern = re.compile(r"\b(\d{1,2})(?:[:][0-5]\d)?\s*[\-–—to]+\s*(\d{1,2})(?:[:][0-5]\d)?\s*(AM|PM)\b", re.IGNORECASE)
    for i in range(start, end):
        line = lines[i]
        r = range_pattern.search(line)
        if r:
            hh = int(r.group(1))
            ampm = r.group(3).upper()
            if ampm == "PM" and hh < 12:
                hh += 12
            if ampm == "AM" and hh == 12:
                hh = 0
            return f"{hh:02d}:00"
    return None


# ---------- Venue Extraction Using Regex (fallback) ----------
VENUE_KEYWORDS = [
    "hall", "auditorium", "room", "centre", "center", "complex",
    "stadium", "building", "block", "lab", "library", "theatre",
    "theater", "gym", "campus", "conference room", "banquet", "park",
    "ground", "lawn"
]

VENUE_REGEX = re.compile(
    r"\b(?:Hall|Room|Block|Building|Centre|Center|Auditorium|Stadium|Theatre|Theater|Lab|Library|Gym|Campus|Park|Ground|Lawn|Conference Room|Seminar Hall)"
    r"(?:\s+[A-Za-z0-9&\-]+){0,5}",
    re.IGNORECASE
)

def extract_venue(text: str, anchor_line_index: Optional[int] = None) -> Optional[str]:
    candidates: List[str] = []
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    # 1) Explicit labels
    label_prefixes = ("venue:", "where:", "location:", "address:")
    for l in lines:
        lower = l.lower()
        if any(lower.startswith(p) for p in label_prefixes):
            val = re.sub(r"^(venue:|where:|location:|address:)\s*", "", lower, flags=re.IGNORECASE)
            candidates.append(val.strip())
    # 2) Regex place-like
    for match in VENUE_REGEX.findall(text or ""):
        cleaned = match.strip()
        if cleaned:
            candidates.append(cleaned)
    # 3) Proximity heuristic near date/time line
    if anchor_line_index is not None and 0 <= anchor_line_index < len(lines):
        start = max(0, anchor_line_index - 3)
        end = min(len(lines), anchor_line_index + 4)
        for l in lines[start:end]:
            if any(kw in l.lower() for kw in VENUE_KEYWORDS):
                candidates.append(l.strip())
    # Post-clean
    for i in range(len(candidates)):
        v = candidates[i]
        v = re.sub(r"\bat\s+\d{1,2}(:[0-5]\d)?\s?(AM|PM|am|pm)\b", "", v)
        v = re.sub(r"\b\d{1,2}(:[0-5]\d)?\s?(AM|PM|am|pm)\b", "", v)
        v = v.strip(",;:- ")
        candidates[i] = v
    # Return the first reasonable candidate
    for v in candidates:
        if v and len(v) >= 2:
            return v
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


# ---------- Main Extraction Function (order toggled by env: LLM_FIRST) ----------
def extract_event_details(subject: Optional[str], body: Optional[str]) -> Dict[str, Optional[str]]:
    raw = body or ""
    text = _clean_text(raw)
    event_name = clean_event_name(subject)
    llm_first = os.getenv("LLM_FIRST", "false").lower() == "true"

    date_str: Optional[str] = None
    time_str: Optional[str] = None
    venue_rule: Optional[str] = None
    source = ""
    confidence = 0.0

    def _apply_rules():
        nonlocal date_str, time_str, venue_rule, source, confidence
        d, t, anchor_idx = _pick_best_datetime(text)
        # If date was found but time missing, search nearby lines explicitly
        if d and not t:
            near_t = _extract_time_near_anchor(text, anchor_idx)
            if near_t:
                t = near_t
        v = extract_venue(text, anchor_line_index=anchor_idx)
        date_str = date_str or d
        time_str = time_str or t
        venue_rule = venue_rule or v
        source = "rules" if not source else f"{source}+rules"
        confidence = max(confidence, 0.85 if (date_str and time_str) else 0.6 if (date_str or time_str) else 0.4)

    def _apply_llm():
        nonlocal date_str, time_str, venue_rule, source, confidence
        if os.getenv("LLM_FALLBACK_ENABLED", "false").lower() != "true":
            return
        try:
            from llm_fallback import extract_with_gemini
            llm = extract_with_gemini(subject or "", text)
            if llm:
                date_str = date_str or llm.get("date")
                time_str = time_str or llm.get("time")
                venue_rule = venue_rule or llm.get("venue")
                source = "gemini" if not source else f"{source}+gemini"
                confidence = max(confidence, 0.8)
        except Exception:
            pass

    def _apply_ner():
        nonlocal date_str, time_str, venue_rule, source, confidence
        ner_entities = _call_hf_ner(text)
        if ner_entities:
            ner_fields = _aggregate_entities(ner_entities)
            date_str = date_str or ner_fields.get("date")
            time_str = time_str or ner_fields.get("time")
            venue_rule = venue_rule or ner_fields.get("venue")
            source = "ner" if not source else f"{source}+ner"
            confidence = max(confidence, 0.7 if count_event_fields({"date": date_str, "time": time_str, "venue": venue_rule}) >= 2 else 0.5)

    if llm_first:
        _apply_llm()
        if count_event_fields({"date": date_str, "time": time_str, "venue": venue_rule}) < 2:
            _apply_rules()
        if count_event_fields({"date": date_str, "time": time_str, "venue": venue_rule}) < 2:
            _apply_ner()
    else:
        _apply_rules()
        if count_event_fields({"date": date_str, "time": time_str, "venue": venue_rule}) < 2:
            _apply_llm()
        if count_event_fields({"date": date_str, "time": time_str, "venue": venue_rule}) < 2:
            _apply_ner()

    # Light normalization of time strings in case text extraction produced variants
    if time_str:
        t = str(time_str).strip()
        if re.fullmatch(r"\d{1,2}", t):
            t = f"{t}:00"
        t = t.upper().replace(".", "")
        t = re.sub(r"\s+", " ", t)
        # Try to coerce to HH:MM
        m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", t, flags=re.IGNORECASE)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            ampm = (m.group(3) or "").upper()
            if ampm == "PM" and hh < 12:
                hh += 12
            if ampm == "AM" and hh == 12:
                hh = 0
            time_str = f"{hh:02d}:{mm:02d}"
        else:
            time_str = t

    result: Dict[str, Optional[str]] = {
        "event": event_name,
        "event_name": event_name,
        "date": date_str,
        "time": time_str,
        "venue": venue_rule,
        "source": source,
        "confidence": confidence,
    }
    return result


def count_event_fields(details: Dict[str, Optional[str]]) -> int:
    present = 0
    for key in ("date", "time", "venue"):
        value = details.get(key)
        if value and str(value).strip():
            present += 1
    return present


def is_event_like(details: Dict[str, Optional[str]], minimum_required: int = 2) -> bool:
    return count_event_fields(details) >= max(0, int(minimum_required))


# ---------- Test ----------
if __name__ == "__main__":
    subj = "Re: [Reminder] Climate Action 2025 - 19 Nov 2025 10:00 AM"
    body = "Join us for the Climate Action 2025 conference on 19 Nov 2025 at 10:00 AM at Global Sustainability Center."
    print(extract_event_details(subj, body))

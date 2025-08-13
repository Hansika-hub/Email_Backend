import os
import re
import spacy
from datetime import datetime

# ---------- Load spaCy small model ----------
nlp = spacy.load("en_core_web_sm")

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


# ---------- Email body cleanup ----------
FORWARDED_MARKERS = [
    r"^[-_]{2,}\s*Forwarded message\s*[-_]{2,}$",
    r"^Begin forwarded message:$",
    r"^-----Original Message-----$",
    r"^On .+wrote:$",
]

HEADER_LIKE_PREFIXES = [
    r"^From:\s",
    r"^To:\s",
    r"^Cc:\s",
    r"^Bcc:\s",
    r"^Subject:\s",
    r"^Date:\s",
    r"^Sent:\s",
]

QUOTE_PREFIX = re.compile(r"^>+")

def strip_forwarded_and_quoted_sections(body: str) -> str:
    if not body:
        return body

    lines = body.splitlines()
    cleaned_lines = []
    skip_rest = False

    forwarded_markers_regexes = [re.compile(pat, re.IGNORECASE) for pat in FORWARDED_MARKERS]
    header_prefix_regexes = [re.compile(pat, re.IGNORECASE) for pat in HEADER_LIKE_PREFIXES]

    for line in lines:
        if skip_rest:
            continue

        # Skip quoted reply lines
        if QUOTE_PREFIX.match(line.strip()):
            continue

        # Stop at forwarded/original markers
        if any(r.match(line.strip()) for r in forwarded_markers_regexes):
            skip_rest = True
            continue

        # Drop header-like lines that often carry sent/forwarded timestamps
        if any(r.match(line) for r in header_prefix_regexes):
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    return cleaned


# ---------- Regex Date & Time Extraction ----------
MONTH_NAMES = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
DATE_REGEX = rf"\b(?:\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|(?:{MONTH_NAMES})[a-z]*\s+\d{{1,2}}(?:,\s*\d{{4}})?)\b"
TIME_REGEX = r"\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?\b"

KEYWORD_LINE = re.compile(r"\b(when|date|time|starts?|schedule|on|at)\b", re.IGNORECASE)

def normalize_date(date_str: str) -> str | None:
    if not date_str:
        return None
    candidates = [
        "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
        "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
        "%m/%d/%y", "%d/%m/%y", "%m-%d-%y", "%d-%m-%y",
    ]
    s = date_str.replace("Sept", "Sep").replace("sept", "sep").replace(",", "").strip()
    for fmt in candidates:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    # Fallback: return original if cannot normalize
    return date_str

def normalize_time(time_str: str) -> str | None:
    if not time_str:
        return None
    candidates = ["%I:%M %p", "%I:%M%p", "%H:%M"]
    s = time_str.strip().upper().replace(".", "")
    for fmt in candidates:
        try:
            tm = datetime.strptime(s, fmt)
            return tm.strftime("%H:%M")
        except Exception:
            continue
    return time_str

def extract_date_time(text: str):
    if not text:
        return None, None

    cleaned = strip_forwarded_and_quoted_sections(text)

    # Prefer lines that mention keywords like When/Date/Time and exclude obvious headers
    priority_lines = []
    other_lines = []
    for line in cleaned.splitlines():
        if KEYWORD_LINE.search(line) and not re.match(r"^(Date|Sent):", line, flags=re.IGNORECASE):
            priority_lines.append(line)
        else:
            other_lines.append(line)

    def find_in_lines(lines):
        joined = "\n".join(lines)
        dates = re.findall(DATE_REGEX, joined)
        times = re.findall(TIME_REGEX, joined)
        return (dates[0] if dates else None, times[0] if times else None)

    date_raw, time_raw = find_in_lines(priority_lines)
    if not date_raw and not time_raw:
        date_raw, time_raw = find_in_lines(other_lines)

    return normalize_date(date_raw), normalize_time(time_raw)


# ---------- Venue Extraction Using spaCy + Regex ----------
VENUE_KEYWORDS = [
    "hall", "auditorium", "room", "centre", "center", "complex",
    "stadium", "building", "block", "lab", "library", "theatre",
    "theater", "gym", "campus", "conference room", "banquet"
]

VENUE_REGEX = re.compile(
    r"\b(?:Hall|Room|Block|Building|Centre|Center|Auditorium|Stadium|Theatre|Theater|Lab|Library|Gym|Campus)"
    r"(?:\s+\w+){0,3}",
    re.IGNORECASE
)

def extract_venue(text):
    venues = set()

    # spaCy entity detection
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in {"FAC", "ORG", "GPE", "LOC"}:
            if any(kw in ent.text.lower() for kw in VENUE_KEYWORDS):
                venues.add(ent.text.strip())

    # Regex matching
    for match in VENUE_REGEX.findall(text):
        venues.add(match.strip())

    return list(venues)[0] if venues else None


# ---------- Main Extraction Function ----------
def extract_event_details(subject, body):
    event_name = clean_event_name(subject)
    date, time = extract_date_time(body)
    venue = extract_venue(body)

    return {
        "event": event_name,
        "date": date,
        "time": time,
        "venue": venue
    }


# ---------- Test ----------
if __name__ == "__main__":
    subj = "Re: [Reminder] Climate Action 2025 - 19 Nov 2025 10:00 AM"
    body = "Join us for the Climate Action 2025 conference on 19 Nov 2025 at 10:00 AM at Global Sustainability Center."
    print(extract_event_details(subj, body))

import os
import re
import spacy

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


# ---------- Regex Date & Time Extraction ----------
DATE_REGEX = r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?)\b"
TIME_REGEX = r"\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?\b"

def extract_date_time(text):
    dates = re.findall(DATE_REGEX, text)
    times = re.findall(TIME_REGEX, text)
    return dates[0] if dates else None, times[0] if times else None


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

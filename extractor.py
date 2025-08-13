import os
import re
import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline

# ✅ Hugging Face model (lightweight)
MODEL_NAME = "dslim/bert-base-NER"
CACHE_DIR = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")

# Load tokenizer & model once
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
model = AutoModelForTokenClassification.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)

# Use CPU to avoid Render GPU OOM
device = -1
ner_pipeline = pipeline("ner", model=model, tokenizer=tokenizer, grouped_entities=True, device=device)


# ---------- Event Name Extraction from Subject ----------
def clean_event_name(subject):
    if not subject:
        return None
    
    # Remove common prefixes
    subject = re.sub(r'^(re:|fwd:|\[.*?\])\s*', '', subject, flags=re.IGNORECASE)
    
    # Remove trailing date/time if present
    subject = re.sub(r'\b(\d{1,2}(\s|-|/)\d{1,2}(\s|-|/)\d{2,4}|\d{1,2}:\d{2}(\s?(AM|PM))?)$', '', subject, flags=re.IGNORECASE)
    
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


# ---------- Venue Extraction Using NER ----------
def extract_venue(text):
    ner_results = ner_pipeline(text)
    for entity in ner_results:
        if entity["entity_group"] in ["LOC", "ORG", "FAC"]:  # Possible venue labels
            return entity["word"]
    return None


# ---------- Main Extraction Function ----------
def extract_event_details(subject, body):
    event_name = clean_event_name(subject)
    
    # Extract date/time from body
    date, time = extract_date_time(body)
    
    # Extract venue from body
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

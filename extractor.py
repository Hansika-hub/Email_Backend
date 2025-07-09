import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
import os
import re
from bs4 import BeautifulSoup
import base64

model_name = "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction"
cache_dir = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")

tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
model = AutoModelForTokenClassification.from_pretrained(model_name, cache_dir=cache_dir)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device set to: {device}")
model.to(device)
model.eval()

id2label = model.config.id2label

def clean_token(token):
    return token.replace("##", "")

def clean_email_content(raw_email_body: str) -> str:
    # Step 1: Convert HTML to plain text if needed
    cleaned = BeautifulSoup(raw_email_body, "html.parser").get_text()

    # Step 2: Collapse whitespace
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)

    # Step 3: Soft-trim disclaimers/footers (without cutting vital info)
    disclaimer_keywords = [
        "DISCLAIMER", "This email is confidential", 
        "On .* wrote:", "Sent from my", "Regards,", "Thanks,"
    ]
    pattern = re.compile("|".join(disclaimer_keywords), re.IGNORECASE)

    split_body = re.split(pattern, cleaned)
    if len(split_body[0].split()) >= 50:  # Keep only if main body is long
        return split_body[0].strip()

    return cleaned.strip()

# ✅ Main extraction function
def extract_event_entities(text: str):
    cleaned_text = clean_email_content(text)
    words = cleaned_text.split()
    encoding = tokenizer(words, is_split_into_words=True, return_tensors="pt", truncation=True, padding=True)

    input_ids = encoding["input_ids"].to(device)
    attention_mask = encoding["attention_mask"].to(device)

    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)

    predictions = torch.argmax(outputs.logits, dim=2)[0]
    tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
    labels = [id2label[p.item()] for p in predictions]

    result = {"event_name": "", "date": "", "time": "", "venue": ""}

    for token, label in zip(tokens, labels):
        label = label.lower()

        if token in ["[CLS]", "[SEP]", "[PAD]"]:
            continue

        token = clean_token(token)

        if "event" in label:
            result["event_name"] += token + " "
        elif "date" in label:
            result["date"] += token + " "
        elif "time" in label:
            result["time"] += token + " "
        elif "venue" in label:
            result["venue"] += token + " "

    return {k: v.strip() for k, v in result.items()}

if __name__ == "__main__":   
    encoded_email = base64.urlsafe_b64encode(b"""
    <html>
    <body>
    <h2>Hackathon 2025 Announcement</h2>
    <p>Join us on 8 October 2026 at 10:00 AM in Tech Auditorium for the most awaited Hackathon event.</p>
    <p>Best regards,<br>Organizing Team</p>
    </body>
    </html>
    """).decode("utf-8")

    # Decode and extract
    decoded_email = base64.urlsafe_b64decode(encoded_email).decode("utf-8")
    output = extract_event_entities(decoded_email)

    print("\n🧠 Extracted Event Details:")
    for key, value in output.items():
        print(f"{key:12}: {value}")

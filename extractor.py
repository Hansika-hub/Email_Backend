import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
import os
import re
from bs4 import BeautifulSoup
import base64
from email_reply_parser import EmailReplyParser

# ✅ Load model and tokenizer
model_name = "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction"
cache_dir = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")

tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
model = AutoModelForTokenClassification.from_pretrained(model_name, cache_dir=cache_dir)

# ✅ Device setup
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device set to: {device}")
model.to(device)
model.eval()

id2label = model.config.id2label

def clean_token(token: str) -> str:
    return token.replace("##", "")

# ✅ Step 1: Strip replies and forwarded content

def extract_sender_message(raw_email: str) -> str:
    # Remove quoted replies/forwards using email-reply-parser
    text = EmailReplyParser.parse_reply(raw_email)

    # Remove standard forwarded headers (for extra safety)
    forward_patterns = [
        r"-{2,}\s*forwarded message\s*-{2,}",
        r"from:.*@.*", r"sent:.*", r"subject:.*", r"to:.*"
    ]
    forward_re = re.compile("|".join(forward_patterns), re.IGNORECASE)
    text = re.split(forward_re, text)[0]

    return text.strip()

# ✅ Step 2: Clean HTML, collapse whitespace

def clean_email_content(raw_email_body: str) -> str:
    # Convert HTML to plain text
    plain = BeautifulSoup(raw_email_body, "html.parser").get_text()

    # Normalize whitespace
    plain = re.sub(r"\n{2,}", "\n", plain)
    plain = re.sub(r"\s{2,}", " ", plain)

    return plain.strip()

# ✅ Step 3: Run NER to extract event info

def extract_event_entities(text: str):
    words = text.split()
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

# ✅ Final callable method
def extract_cleaned_event(raw_email_base64: str) -> dict:
    try:
        decoded_email = base64.urlsafe_b64decode(raw_email_base64).decode("utf-8", errors="ignore")
        sender_text_only = extract_sender_message(decoded_email)
        cleaned_text = clean_email_content(sender_text_only)
        return extract_event_entities(cleaned_text)
    except Exception as e:
        print("❌ Extraction error:", str(e))
        return {"event_name": "", "date": "", "time": "", "venue": ""}

# ✅ Test
if __name__ == "__main__":
    example_email = base64.urlsafe_b64encode(b"""
    <html>
    <body>
    <p>Dear SPOC,</p>
    <p>We invite you to the NPTEL Workshop on Ansys Maxwell on 9 August 2025 at 10:00 AM in Seminar Hall 3, IIT Madras.</p>
    <p>Best regards,<br>NPTEL Team</p>
    <p>::Disclaimer:: This message is confidential.</p>
    <br><br>---------- Forwarded message ----------
    From: ...
    </body>
    </html>
    """).decode("utf-8")

    print("🧪 Testing email extraction:")
    results = extract_cleaned_event(example_email)
    for k, v in results.items():
        print(f"{k:12}: {v}")

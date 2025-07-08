import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
import os
import re
from bs4 import BeautifulSoup

# ✅ Load model and tokenizer from Hugging Face
model_name = "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction"
cache_dir = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")

tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
model = AutoModelForTokenClassification.from_pretrained(model_name, cache_dir=cache_dir)

# ✅ Device config
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"✅ Device set to: {device}")
model.to(device)
model.eval()

# ✅ Get label map
id2label = model.config.id2label

def clean_token(token):
    return token.replace("##", "")

# ✅ Clean raw email content before model inference
def clean_email_text(raw_text: str) -> str:
    # Remove HTML if any
    text = BeautifulSoup(raw_text, "html.parser").get_text()
    
    # Remove common disclaimers, replies, signatures
    text = re.split(
        r"(Disclaimer:|This email is confidential|Regards,|Thanks,|On .+ wrote:|Sent from my iPhone)",
        text
    )[0]
    
    return text.strip().lower()  # Lowercasing improves consistency

# ✅ Main extraction function
def extract_event_entities(text: str):
    cleaned = clean_email_text(text)
    words = cleaned.split()

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

# ✅ Example usage for testing
if __name__ == "__main__":
    sample_text = """
    <html>
    <body>
    <p>You're invited to the <b>AI Symposium</b> on <b>July 25</b> at <b>10:30 AM</b> in <b>IIT Madras, Chennai</b>.</p>
    <p>Regards,<br>Organizer Team</p>
    </body>
    </html>
    """
    output = extract_event_entities(sample_text)
    print("\n🧠 Extracted Event Details:")
    for key, value in output.items():
        print(f"{key:12}: {value}")

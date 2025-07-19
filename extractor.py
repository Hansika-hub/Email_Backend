import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
import os
import replicate  # ✅ Added for Replicate integration
import json       # ✅ For parsing Mistral output

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

# ✅ Your original DistilBERT extractor
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

        # Skip special tokens
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


# ✅ Mistral-based fallback/extractor using Replicate
def extract_with_mistral(text: str):
    prompt = f"""
    Extract the following details from this email:
    - Event Name
    - Date
    - Time
    - Venue

    Respond ONLY in JSON format:
    {{
      "event_name": "...",
      "date": "...",
      "time": "...",
      "venue": "..."
    }}

    Email:
    \"\"\"{text}\"\"\"
    """

    try:
        output = replicate.run(
            "mistralai/mistral-7b-instruct-v0.1",
            input={
                "prompt": prompt,
                "temperature": 0.2,
                "max_new_tokens": 300
            }
        )
        result_text = ''.join(output)
        json_start = result_text.find("{")
        json_output = json.loads(result_text[json_start:])

        # ✅ Ensure all keys exist even if Mistral misses some
        return {
            "event_name": json_output.get("event_name", "").strip(),
            "date": json_output.get("date", "").strip(),
            "time": json_output.get("time", "").strip(),
            "venue": json_output.get("venue", "").strip()
        }

    except Exception as e:
        print("⚠️ Mistral fallback failed:", e)
        return {"event_name": "", "date": "", "time": "", "venue": ""}


# ✅ Combined extractor: first try BERT, fallback to Mistral if <3 fields
def extract_event(text: str):
    first_pass = extract_event_entities(text)
    filled_fields = sum(1 for v in first_pass.values() if v.strip())

    if filled_fields >= 3:
        return first_pass
    else:
        print("🔄 Using Mistral fallback due to incomplete extraction...")
        return extract_with_mistral(text)


# ✅ Example usage
if __name__ == "__main__":
    sample_text = "Join us for TechTalk on 25 July at 10:30 AM in Anna Auditorium, Chennai."

    # Run full pipeline with fallback
    output = extract_event(sample_text)

    print("\n🧠 Final Extracted Event Details:")
    for key, value in output.items():
        print(f"{key:12}: {value}")

import os
import replicate
import json
import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification

# ✅ Mapping label IDs to actual tags will be constant
ID2LABEL = {
    0: 'O', 1: 'B-date', 2: 'I-date', 3: 'B-event', 4: 'I-event',
    5: 'B-time', 6: 'I-time', 7: 'B-venue', 8: 'I-venue'
}

def clean_token(token):
    return token.replace("##", "")

# ✅ Lazy loading DistilBERT inside the function to save memory
def extract_event_entities(text: str):
    model_name = "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction"
    cache_dir = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")

    tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
    model = AutoModelForTokenClassification.from_pretrained(model_name, cache_dir=cache_dir)
    model.to("cpu")
    model.eval()

    words = text.split()
    encoding = tokenizer(words, is_split_into_words=True, return_tensors="pt", truncation=True, padding=True)

    input_ids = encoding["input_ids"]
    attention_mask = encoding["attention_mask"]

    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)

    predictions = torch.argmax(outputs.logits, dim=2)[0]
    tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
    labels = [ID2LABEL[p.item()] for p in predictions]

    result = {"event_name": "", "date": "", "time": "", "venue": ""}

    for token, label in zip(tokens, labels):
        if token in ["[CLS]", "[SEP]", "[PAD]"]:
            continue
        token = clean_token(token)
        label = label.lower()

        if "event" in label:
            result["event_name"] += token + " "
        elif "date" in label:
            result["date"] += token + " "
        elif "time" in label:
            result["time"] += token + " "
        elif "venue" in label:
            result["venue"] += token + " "

    return {k: v.strip() for k, v in result.items()}

# ✅ Mistral fallback using Replicate API (no memory issues here)
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

        return {
            "event_name": json_output.get("event_name", "").strip(),
            "date": json_output.get("date", "").strip(),
            "time": json_output.get("time", "").strip(),
            "venue": json_output.get("venue", "").strip()
        }

    except Exception as e:
        print("⚠️ Mistral fallback failed:", e)
        return {"event_name": "", "date": "", "time": "", "venue": ""}

# ✅ Combined extractor with fallback
def extract_event(text: str):
    first_pass = extract_event_entities(text)
    filled_fields = sum(1 for v in first_pass.values() if v.strip())

    if filled_fields >= 3:
        return first_pass
    else:
        print("🔄 Using Mistral fallback due to incomplete extraction...")
        return extract_with_mistral(text)

# ✅ Test if needed
if __name__ == "__main__":
    sample_text = "Join us for TechTalk on 25 July at 10:30 AM in Anna Auditorium, Chennai."
    result = extract_event(sample_text)
    print(json.dumps(result, indent=2))

import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from transformers import AutoTokenizer, AutoModelForTokenClassification
import os

model_name = "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction"
cache_dir = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")  # Use /tmp/cache if set
tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
model = AutoModelForTokenClassification.from_pretrained(model_name, cache_dir=cache_dir)


# ✅ Move model to CPU or GPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"✅ Device set to: {device}")
model.to(device)
model.eval()

# ✅ Get label map
id2label = model.config.id2label

# ✅ Main extraction function
def extract_event_entities(text: str):
    # Tokenize input
    encoding = tokenizer(text.split(),is_split_into_words=True,return_tensors="pt",truncation=True,padding=True)

    input_ids = encoding["input_ids"].to(device)
    attention_mask = encoding["attention_mask"].to(device)

    # Run model
    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)

    # Get predicted labels
    predictions = torch.argmax(outputs.logits, dim=2)[0]
    tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
    labels = [id2label[p.item()] for p in predictions]

    # Map labels to fields
    result = {"event_name": "", "date": "", "time": "", "venue": ""}
    for token, label in zip(tokens, labels):
        label = label.lower()
        if "event" in label:
            result["event_name"] += token + " "
        elif "date" in label:
            result["date"] += token + " "
        elif "time" in label:
            result["time"] += token + " "
        elif "venue" in label:
            result["venue"] += token + " "

    # Clean up extra spaces
    return {k: v.strip().replace(" ##", "") for k, v in result.items()}

# ✅ Example usage (you can delete this block when importing in app.py)
if __name__ == "__main__":
    sample_text = "Join us at AI Summit on 25 July at 10 AM in Delhi Tech Park."
    output = extract_event_entities(sample_text)
    print("\n🧠 Extracted Event Details:")
    for key, value in output.items():
        print(f"{key:12}: {value}")

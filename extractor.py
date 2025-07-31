import re
import os
import replicate
import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from torch.nn.functional import softmax

# Load REPLICATE API token from environment
replicate.api_token = os.getenv("REPLICATE_API_TOKEN")

# Global model and tokenizer
tokenizer = None
model = None

def load_model():
    global tokenizer, model
    if tokenizer is None or model is None:
        model_name = "Thiyaga158/Distilbert_Ner_Model_For_Email_Event_Extraction"
        cache_dir  = os.getenv("TRANSFORMERS_CACHE", "/tmp/cache")

        # 1) tokenizer loading stays the same
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            cache_dir=cache_dir
        )

        # 2) model loading with memory-saving flags
        model = AutoModelForTokenClassification.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            load_in_8bit=True,         # 8-bit quantization
            device_map="auto",         # auto-shard across CPU/GPU
            low_cpu_mem_usage=True,    # reduce peak CPU RAM
            torch_dtype="auto"         # FP16 if supported
        )

        model.eval()
        print("✅ Model and tokenizer loaded successfully.")

def extract_event_entities(email_text):
    load_model()

    inputs = tokenizer(
        email_text,
        return_tensors="pt",
        truncation=True,
        max_length=512
    )
    with torch.no_grad():
        outputs = model(**inputs)

    predictions = torch.argmax(outputs.logits, dim=2)
    predicted_labels = [
        model.config.id2label[label_id.item()]
        for label_id in predictions[0]
    ]

    entities = {"event_name": "", "date": "", "time": "", "venue": ""}
    current_entity = None

    # Get the exact tokens the model saw
    tokens = tokenizer.convert_ids_to_tokens(inputs.input_ids[0])

    for token, label in zip(tokens, predicted_labels):
        if label.startswith("B-"):
            raw = label[2:].lower()                  # e.g. "event", "date"
            key = "event_name" if raw == "event" else raw
            current_entity = key
            entities[key] += token.replace("▁", " ")
        elif label.startswith("I-") and current_entity:
            entities[current_entity] += token.replace("▁", " ")
        else:
            current_entity = None

    # Strip off any extra whitespace
    return {k: v.strip() for k, v in entities.items()}


def extract_with_mistral(email_text):
    prompt = (
        f"Extract the event name, date, time, and venue from the email below.\n"
        f"Only return plain JSON with the keys 'event_name', 'date', 'time', and 'venue'.\n\n"
        f"Email:\n{email_text}"
    )

    try:
        output = replicate.run(
            "mistralai/mistral-7b-instruct-v0.1",
            input={
                "prompt": prompt,
                "temperature": 0.2,
                "max_new_tokens": 300,
            }
        )
        response_text = "".join(output)
        print("🔍 Mistral Output:", response_text)

        json_pattern = r"\{[^}]*\}"
        match = re.search(json_pattern, response_text)
        if match:
            import json
            data = json.loads(match.group())
            return {k.lower(): v.strip() for k, v in data.items()}
    except Exception as e:
        print("❌ Error in Mistral extraction:", e)

    return {"event_name": "", "date": "", "time": "", "venue": ""}

def extract_event(email_text):
    first_pass = extract_event_entities(email_text)
    print("🧪 First pass:", first_pass)

    filled_fields = [k for k, v in first_pass.items() if v]
    if len(filled_fields) >= 3:
        print("✅ Using first pass result.")
        return first_pass

    second_pass = extract_with_mistral(email_text)
    print("🔁 Second pass (Mistral):", second_pass)

    result = {
        "event_name": first_pass.get("event_name") or second_pass.get("event_name") or "",
        "date": first_pass.get("date") or second_pass.get("date") or "",
        "time": first_pass.get("time") or second_pass.get("time") or "",
        "venue": first_pass.get("venue") or second_pass.get("venue") or ""
    }

    print("✅ Final extracted event:", result)
    return result

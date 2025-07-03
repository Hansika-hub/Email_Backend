import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from pathlib import Path

# ✅ Define the local model path (adjust if needed)
model_path = Path(r"C:\Users\DELL\OneDrive\Desktop\Thambu\EEE_website\checkpoint-3546").resolve()

# ✅ Load tokenizer and model from local folder
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForTokenClassification.from_pretrained(model_path)

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
# import torch
# from transformers import AutoTokenizer, AutoModelForTokenClassification
# from pathlib import Path

# # ✅ Load local model and tokenizer
# model_path = Path(r"C:\Users\DELL\OneDrive\Desktop\Thambu\EEE_website\checkpoint-3546").resolve()
# tokenizer = AutoTokenizer.from_pretrained(model_path)
# model = AutoModelForTokenClassification.from_pretrained(model_path)

# # ✅ Set device
# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# print(f"✅ Device set to: {device}")
# model.to(device)
# model.eval()

# # ✅ Label mapping
# id2label = model.config.id2label

# # ✅ Entity extraction function
# def extract_event_entities(text: str):
#     encoding = tokenizer(text.split(),is_split_into_words=True,return_tensors="pt",truncation=True,padding=True)

#     input_ids = encoding["input_ids"].to(device)
#     attention_mask = encoding["attention_mask"].to(device)

#     with torch.no_grad():
#         outputs = model(input_ids=input_ids, attention_mask=attention_mask)

#     predictions = torch.argmax(outputs.logits, dim=2)[0]
#     tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
#     labels = [id2label[p.item()].lower() for p in predictions]

#     # Initialize storage
#     result = {"event_name": [], "date": [], "time": [], "venue": []}
#     current_label = None
#     current_word = ""

#     for token, label in zip(tokens, labels):
#         if label == "o":
#             if current_word and current_label:
#                 result[current_label].append(current_word)
#             current_word = ""
#             current_label = None
#             continue

#         entity_field = None
#         for key in result.keys():
#             if key.split("_")[0] in label:
#                 entity_field = key
#                 break

#         if not entity_field:
#             continue

#         # Merge WordPieces
#         if token.startswith("##"):
#             current_word += token[2:]
#         else:
#             if current_word and current_label:
#                 result[current_label].append(current_word)
#             current_word = token
#             current_label = entity_field

#     # Catch any last token
#     if current_word and current_label:
#         label = current_label.lower()
#         if "event" in label:
#             result["event_name"] += token + " "
#         elif "date" in label:
#             result["date"] += token + " "
#         elif "time" in label:
#             result["time"] += token + " "
#         elif "venue" in label:
#             result["venue"] += token + " "

#     # Join words, clean up formatting
#     final_result = {
#         key: " ".join(tokens).replace(" .", ".").replace(" ,", ",").replace(" ##", "").strip()
#         for key, tokens in result.items()
#     }

#     return final_result

# # ✅ Test run
# if __name__ == "__main__":
#     text = "Join us at AI Research Meetup EEE on July 10, 2025 at 2:30 PM in Conference Hall B."
#     output = extract_event_entities(text)

#     print("\n🧠 Extracted Event Details:\n")
#     for key, value in output.items():
#         print(f"{key.capitalize():12}: {value}")

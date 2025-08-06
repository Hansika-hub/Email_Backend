import re
import os
import replicate
import json

# Load REPLICATE API token from environment
replicate.api_token = os.getenv("REPLICATE_API_TOKEN")

def extract_event(email_text):
    prompt = (
        f"Extract the event name, date, time, and venue from the email below.\n"
        f"Only return plain JSON with the keys 'event', 'date', 'time', and 'venue'.\n\n"
        f"Email:\n{email_text}"
    )

    try:
        output = replicate.run(
            "meta/meta-llama-3-8b-instruct",
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
            data = json.loads(match.group())
            return {k.lower(): v.strip() for k, v in data.items()}
    except Exception as e:
        print("❌ Error in Mistral extraction:", e)

    return {"event": "", "date": "", "time": "", "venue": ""}


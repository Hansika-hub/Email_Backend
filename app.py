from flask import Flask, redirect, request, jsonify, session
from gmail_utils import get_gmail_service
from extractor import extract_event_details
from flask_cors import CORS
import os
from db_utils import save_to_db
import logging
import base64
import re
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = Flask(__name__)
app.secret_key = "super_secret"

# ✅ Secure session settings (if ever needed)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None'
)

# ✅ CORS config for Vercel
CORS(app, supports_credentials=True, origins=["https://email-mu-eight.vercel.app"])

all_events = []
# ---- Helpers to extract readable body text from Gmail payload ----
def _decode_base64_to_text(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    except Exception:
        return ""

def _strip_html(html: str) -> str:
    if not html:
        return ""
    # Remove script/style
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    # Replace breaks with newlines
    html = re.sub(r"<(br|/p|/div)>", "\n", html, flags=re.IGNORECASE)
    # Strip tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    return re.sub(r"\s+", " ", text).strip()

def _walk_parts_for_text(payload: dict) -> str:
    if not payload:
        return ""
    # Prefer text/plain
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_base64_to_text(payload["body"]["data"]) or ""
    # Fallback text/html
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        html = _decode_base64_to_text(payload["body"]["data"]) or ""
        return _strip_html(html)
    # Recurse into parts
    for part in (payload.get("parts") or []):
        text = _walk_parts_for_text(part)
        if text:
            return text
    # Last resort: body at this level
    if payload.get("body", {}).get("data"):
        return _decode_base64_to_text(payload["body"]["data"]) or ""
    return ""

# Optional logging configuration
if os.getenv("DEBUG_NER", "0") not in (None, "", "0", "false", "False"):
    logging.basicConfig(level=logging.INFO, format='%(message)s')

# ✅ Optional: Block non-JSON POST requests
@app.before_request
def block_non_json_post():
    if request.method == 'POST' and not request.is_json:
        return jsonify({"error": "Only JSON POST requests allowed"}), 415


@app.route("/", methods=["POST"])
def authenticate():
    data = request.get_json()
    id_token_str = data.get("token")

    if not id_token_str:
        return jsonify({"error": "Missing ID token"}), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            "721040422695-9m0ge0d19gqaha28rse2le19ghran03u.apps.googleusercontent.com"
        )

        session["email"] = idinfo["email"]

        return jsonify({
            "status": "authenticated",
            "user": idinfo["email"],
            "accessToken": id_token_str
        }), 200

    except Exception as e:
        print("❌ Token verification error:", str(e))
        return jsonify({"error": "Token verification failed"}), 400


@app.route("/fetch_emails", methods=["GET"])
def fetch_emails():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    access_token = auth_header.split(" ")[1]

    try:
        creds = Credentials(token=access_token)
        service = build("gmail", "v1", credentials=creds)

        results = service.users().messages().list(userId="me", maxResults=10, q="is:unread").execute()
        messages = results.get("messages", [])

        email_list = []
        for msg in messages:
            msg_detail = service.users().messages().get(userId="me", id=msg['id'], format='metadata', metadataHeaders=['Subject']).execute()
            headers = msg_detail.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
            email_list.append({
                "id": msg["id"],
                "subject": subject
            })

        return jsonify(email_list)
    except Exception as e:
        print("📡 Gmail API error:", str(e))
        return jsonify({"error": "Failed to fetch emails from Gmail"}), 500

@app.route("/process_emails", methods=["GET"])
def process_all_emails():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    access_token = auth_header.split(" ")[1]

    try:
        creds = Credentials(token=access_token)
        service = build("gmail", "v1", credentials=creds)
        results = service.users().messages().list(
            userId="me", maxResults=20, q="is:unread"
        ).execute()
        messages = results.get("messages", [])
        print(f"📥 Fetched unread messages: {len(messages)}")
        extracted = []

        for msg in messages:
            try:
                msg_detail = service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()

                # ✅ Extract Subject
                headers = msg_detail.get("payload", {}).get("headers", [])
                subject = next(
                    (h["value"] for h in headers if h["name"] == "Subject"),
                    "No Subject"
                )

                # ✅ Extract Body text (handles nested parts and HTML)
                body_data = _walk_parts_for_text(msg_detail.get("payload", {}))

                # ✅ Call the new extractor
                result = extract_event_details(subject, body_data)

                if sum(1 for v in result.values() if v and str(v).strip()) >= 3:
                    result["attendees"] = 1
                    extracted.append(result)
                    save_to_db(result)
                else:
                    print(f"ℹ️ Skipping low-signal extraction for subject='{subject}' -> {result}")

            except Exception as e:
                print(f"⚠️ Skipping email due to error: {e}")
                continue

        print(f"✅ Extracted events: {len(extracted)}")
        return jsonify(extracted)

    except Exception as e:
        print("📡 Gmail API error:", str(e))
        return jsonify({"error": "Failed to process emails"}), 500


@app.route("/cleanup_reminders", methods=["POST"])
def cleanup():
    from db_utils import delete_expired_events
    deleted = delete_expired_events()
    return jsonify({"deleted": deleted})


# ✅ Main runner
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))



from flask import Flask, redirect, request, jsonify, session
from gmail_utils import get_gmail_service
from extractor import extract_event_details
from flask_cors import CORS
import os
from db_utils import save_to_db
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import base64
import re

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

                # ✅ Extract Body text (prefer text/plain, fallback to text/html). Also parse text/calendar (ICS)
                def iter_parts(payload):
                    if not payload:
                        return
                    if "parts" in payload:
                        for p in payload["parts"]:
                            # Some parts nest deeper
                            if p.get("parts"):
                                for sub in iter_parts(p):
                                    yield sub
                            else:
                                yield p
                    else:
                        yield payload

                plain_text = ""
                html_text = ""
                calendar_text = ""

                for part in iter_parts(msg_detail.get("payload", {})):
                    mime = part.get("mimeType", "")
                    data = part.get("body", {}).get("data")
                    if not data:
                        continue
                    decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    if mime.startswith("text/plain") and not plain_text:
                        plain_text = decoded
                    elif mime.startswith("text/html") and not html_text:
                        html_text = decoded
                    elif mime.startswith("text/calendar") and not calendar_text:
                        calendar_text = decoded

                # Fallback to payload body if needed
                if not (plain_text or html_text):
                    data = msg_detail.get("payload", {}).get("body", {}).get("data")
                    if data:
                        plain_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

                # Crude HTML to text if needed
                def html_to_text(html):
                    if not html:
                        return ""
                    # remove scripts/styles and tags
                    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
                    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
                    text = re.sub(r"<[^>]+>", " ", html)
                    text = re.sub(r"\s+", " ", text)
                    return text.strip()

                body_data = plain_text or html_to_text(html_text)

                # ✅ Call the extractor
                result = extract_event_details(subject, body_data)

                # ✅ If ICS invite present, prefer DTSTART/DTEND over anything parsed from body
                if calendar_text:
                    # DTSTART;TZID=Asia/Kolkata:20250813T153000 or DTSTART:20250813T093000Z
                    dtstart_match = re.search(r"^DTSTART(?:;[^:]+)?:([0-9TzZ]+)", calendar_text, flags=re.MULTILINE)
                    if dtstart_match:
                        v = dtstart_match.group(1)
                        # normalize like YYYYMMDDTHHMM or YYYYMMDD
                        y = v[0:4]
                        m = v[4:6]
                        d = v[6:8]
                        date_norm = f"{y}-{m}-{d}"
                        time_norm = None
                        if len(v) >= 13 and ("T" in v or v.isdigit()):
                            # try HHMM
                            hhmm = v.split("T")[1][:4]
                            if len(hhmm) == 4:
                                time_norm = f"{hhmm[0:2]}:{hhmm[2:4]}"
                        if date_norm:
                            result["date"] = date_norm
                        if time_norm:
                            result["time"] = time_norm

                if sum(1 for v in result.values() if v and str(v).strip()) >= 3:
                    result["attendees"] = 1
                    extracted.append(result)
                    save_to_db(result)

            except Exception as e:
                print(f"⚠️ Skipping email due to error: {e}")
                continue

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



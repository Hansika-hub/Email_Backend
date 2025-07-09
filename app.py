from flask import Flask, request, jsonify, session
from flask_cors import CORS
from gmail_utils import get_gmail_service
from extractor import extract_event_entities, clean_email_content
from db_utils import save_to_db, delete_expired_events
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import os
import base64

app = Flask(__name__)
app.secret_key = "super_secret"

# ✅ Secure session settings
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None'
)

# ✅ CORS config (for Vercel frontend)
CORS(app, supports_credentials=True, origins=["https://email-mu-eight.vercel.app"])

all_events = []  # Optional in-memory backup (used only in-session)

@app.before_request
def block_non_json_post():
    if request.method == 'POST' and not request.is_json:
        return jsonify({"error": "Only JSON POST requests allowed"}), 415


# ✅ Google One Tap Authentication
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


# ✅ Fetch email subjects
@app.route("/fetch_emails", methods=["GET"])
def fetch_emails():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    access_token = auth_header.split(" ")[1]

    try:
        service = get_gmail_service(access_token)
        results = service.users().messages().list(userId="me", maxResults=10, q="is:unread").execute()
        messages = results.get("messages", [])

        email_list = []
        for msg in messages:
            msg_detail = service.users().messages().get(
                userId="me", id=msg['id'], format='metadata', metadataHeaders=['Subject']
            ).execute()

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


# ✅ Process and extract event from a specific email
@app.route("/process_emails", methods=["POST"])
def process_email():
    data = request.get_json()
    email_id = data.get("emailId")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    access_token = auth_header.split(" ")[1]

    if not email_id:
        return jsonify({"error": "Missing email ID"}), 400

    try:
        service = get_gmail_service(access_token)
        msg_detail = service.users().messages().get(userId="me", id=email_id, format='full').execute()
        payload = msg_detail.get("payload", {})
        parts = payload.get("parts", [])

        body = ""
        for part in parts:
            if part.get("mimeType") == "text/html":
                body = part["body"].get("data", "")
                break
            elif part.get("mimeType") == "text/plain":
                body = part["body"].get("data", "")

        if not body:
            return jsonify({"error": "Email body is empty"}), 400

        decoded_email = base64.urlsafe_b64decode(body).decode("utf-8", errors="ignore")
        clean_text = clean_email_content(decoded_email)
        result = extract_event_entities(clean_text)

        if sum(1 for v in result.values() if v.strip()) >= 3:
            result["attendees"] = 1
            all_events.append(result)
            save_to_db(result)
            return jsonify([result])

        return jsonify([])

    except Exception as e:
        print("📡 Gmail API error:", str(e))
        return jsonify({"error": "Failed to process email"}), 500


# ✅ Delete expired reminders
@app.route("/cleanup_reminders", methods=["POST"])
def cleanup():
    deleted = delete_expired_events()
    return jsonify({"deleted": deleted})


# ✅ Fetch all saved reminders from memory (or DB, if needed)
@app.route("/get_events", methods=["GET"])
def get_events():
    return jsonify(all_events)


# ✅ Run the app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

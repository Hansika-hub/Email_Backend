from flask import Flask, redirect, request, jsonify, session
from gmail_utils import get_gmail_service
from extractor import extract_event_entities
from flask_cors import CORS
import os
from db_utils import save_to_db
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = Flask(__name__)  # ✅ fixed
app.secret_key = "super_secret"
CORS(app, supports_credentials=True, origins=["https://email-mu-eight.vercel.app"])

all_events = []

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

    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)

    msg_detail = service.users().messages().get(userId="me", id=email_id, format='full').execute()
    snippet = msg_detail.get("snippet", "")

    result = extract_event_entities(snippet)
    if sum(1 for v in result.values() if v.strip()) >= 3:
        result["attendees"] = 1
        all_events.append(result)
        save_to_db(result)  # ✅ Save to DB
        return jsonify([result])

    return jsonify([])

@app.route("/cleanup_reminders", methods=["POST"])
def cleanup():
    from db_utils import delete_expired_events
    deleted = delete_expired_events()
    return jsonify({"deleted": deleted})


# ✅ Correct main block
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

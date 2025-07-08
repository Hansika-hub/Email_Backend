# ✅ app.py (updated to use cleaned content and full email body)

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
from bs4 import BeautifulSoup
import base64
import re

app = Flask(__name__)
app.secret_key = "super_secret"

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None'
)

CORS(app, supports_credentials=True, origins=["https://email-mu-eight.vercel.app"])

all_events = []

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
        creds = Credentials(token=access_token)
        service = build("gmail", "v1", credentials=creds)

        msg_detail = service.users().messages().get(userId="me", id=email_id, format='full').execute()
        payload = msg_detail.get("payload", {})

        # ✅ Extract full body
        def get_body(part):
            if part.get("mimeType") == "text/plain" or part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            elif "parts" in part:
                for p in part["parts"]:
                    content = get_body(p)
                    if content:
                        return content
            return ""

        body = get_body(payload)
        result = extract_event_entities(body)

        if sum(1 for v in result.values() if v.strip()) >= 3:
            result["attendees"] = 1
            all_events.append(result)
            save_to_db(result)
            return jsonify([result])

        return jsonify([])

    except Exception as e:
        print("📡 Gmail API error:", str(e))
        return jsonify({"error": "Failed to process email"}), 500

@app.route("/cleanup_reminders", methods=["POST"])
def cleanup():
    from db_utils import delete_expired_events
    deleted = delete_expired_events()
    return jsonify({"deleted": deleted})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

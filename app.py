from flask import Flask, redirect, request, jsonify, session
from gmail_utils import get_gmail_service
from extractor import extract_event_entities
from flask_cors import CORS
import os

app = Flask(__name__)
app.secret_key = "super_secret"
CORS(app)  # Allow frontend to call API

# Dummy in-memory DB
all_events = []

@app.route("/", methods=["POST"])
def authenticate():
    data = request.get_json()
    access_token = data.get("accessToken")

    if not access_token:
        return jsonify({"error": "Missing access token"}), 400

    session["access_token"] = access_token
    return jsonify({"status": "authenticated"}), 200


@app.route("/fetch_emails", methods=["GET"])
def fetch_emails():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "Not authenticated"}), 401

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
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    data = request.get_json()
    email_id = data.get("emailId")

    access_token = session.get("access_token")
    if not access_token or not email_id:
        return jsonify({"error": "Missing token or email ID"}), 400

    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)

    msg_detail = service.users().messages().get(userId="me", id=email_id, format='full').execute()
    snippet = msg_detail.get("snippet", "")

    result = extract_event_entities(snippet)
    if sum(1 for v in result.values() if v.strip()) >= 3:
        result["attendees"] = 1  # Dummy for now
        all_events.append(result)
        return jsonify([result])

    return jsonify([])

if __name__ == "__main__":
    app.run(debug=True)
if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)


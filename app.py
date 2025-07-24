from flask import Flask, redirect, request, jsonify, session
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import os
import logging
from extractor import extract_event
from db_utils import save_to_db, delete_expired_events

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret")

# Secure session settings
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None'
)

# Enhanced CORS configuration
CORS(app, supports_credentials=True, origins=["https://email-mu-eight.vercel.app"], 
     allow_headers=["Content-Type", "Authorization"], 
     methods=["GET", "POST", "OPTIONS"])

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Store refresh tokens (replace with database in production)
user_tokens = {}

all_events = []

@app.route("/<path:path>", methods=["OPTIONS"])
def handle_options(path):
    return jsonify({"status": "ok"}), 200

@app.before_request
def block_non_json_post():
    if request.method == 'POST' and not request.is_json and request.endpoint != 'handle_options':
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
        logging.error(f"Token verification error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Token verification failed: {str(e)}"}), 400

@app.route("/store-tokens", methods=["POST"])
def store_tokens():
    data = request.get_json()
    user_email = data.get("userEmail")
    refresh_token = data.get("refreshToken")

    if not user_email or not refresh_token:
        return jsonify({"error": "Missing userEmail or refreshToken"}), 400

    user_tokens[user_email] = refresh_token
    logging.info(f"Stored refresh token for {user_email}")
    return jsonify({"status": "success"}), 200

def get_credentials(user_email, access_token):
    refresh_token = user_tokens.get(user_email)
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/calendar.events"]
    )

@app.route("/fetch_emails", methods=["GET"])
def fetch_emails():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized: Missing or invalid Authorization header"}), 401

    access_token = auth_header.split(" ")[1]
    user_email = session.get("email")

    if not user_email:
        return jsonify({"error": "User email not found in session"}), 401

    try:
        creds = get_credentials(user_email, access_token)
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

        return jsonify(email_list), 200
    except Exception as e:
        logging.error(f"Gmail API error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to fetch emails from Gmail: {str(e)}"}), 500

@app.route("/process_emails", methods=["POST"])
def process_email():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized: Missing or invalid Authorization header"}), 401

    access_token = auth_header.split(" ")[1]
    user_email = session.get("email")
    data = request.get_json()
    email_id = data.get("emailId")

    if not email_id or not isinstance(email_id, str) or len(email_id) < 16:
        return jsonify({"error": "Invalid email ID"}), 400

    if not user_email:
        return jsonify({"error": "User email not found in session"}), 401

    try:
        creds = get_credentials(user_email, access_token)
        service = build("gmail", "v1", credentials=creds)

        msg_detail = service.users().messages().get(userId="me", id=email_id, format='full').execute()
        snippet = msg_detail.get("snippet", "")

        result = extract_event(snippet)
        if sum(1 for v in result.values() if v.strip()) >= 3:
            result["attendees"] = 1
            all_events.append(result)
            save_to_db(result)
            return jsonify([result]), 200

        return jsonify([]), 200
    except Exception as e:
        logging.error(f"Gmail API error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to process email: {str(e)}"}), 500

@app.route("/add_to_calendar", methods=["POST"])
def add_to_calendar():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized: Missing or invalid Authorization header"}), 401

    access_token = auth_header.split(" ")[1]
    user_email = session.get("email")
    event = request.get_json()

    if not user_email:
        return jsonify({"error": "User email not found in session"}), 401

    try:
        if not all(k in event for k in ("event_name", "date", "time", "venue")):
            logging.warning(f"Missing fields in event: {event}")
            return jsonify({"error": "Missing required event fields"}), 400

        credentials = get_credentials(user_email, access_token)
        service = build("calendar", "v3", credentials=credentials)

        start_datetime = f"{event['date']}T{event['time']}:00"
        event_body = {
            "summary": event["event_name"],
            "location": event["venue"],
            "start": {
                "dateTime": start_datetime,
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": start_datetime,  # Consider adding duration logic
                "timeZone": "Asia/Kolkata",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 1440},
                    {"method": "popup", "minutes": 300},
                    {"method": "popup", "minutes": 60},
                    {"method": "popup", "minutes": 30},
                ],
            },
        }

        event_created = service.events().insert(calendarId="primary", body=event_body).execute()
        logging.info(f"Calendar Event Created: {event_created['id']}")
        return jsonify({"message": "Event added to calendar", "event_id": event_created["id"]}), 200
    except Exception as e:
        logging.error(f"Calendar Add Error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to add event to calendar: {str(e)}"}), 500

@app.route("/cleanup_reminders", methods=["POST"])
def cleanup():
    try:
        deleted = delete_expired_events()
        return jsonify({"deleted": deleted}), 200
    except Exception as e:
        logging.error(f"Cleanup Error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to cleanup reminders: {str(e)}"}), 500

# Removed if __name__ == '__main__' block for production use with Gunicorn

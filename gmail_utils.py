from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os, pickle

# Only readonly Gmail scope is needed
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service(access_token):
    """
    Given an access_token from the frontend, build and return a Gmail API service object.
    """
    creds = Credentials(token=access_token, scopes=SCOPES)
def get_gmail_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = Flow.from_client_secrets_file('credentials.json', scopes=SCOPES, redirect_uri='http://localhost:5000/oauth2callback')
        auth_url, _ = flow.authorization_url(prompt='consent')
        return auth_url, flow

    service = build('gmail', 'v1', credentials=creds)
    return service

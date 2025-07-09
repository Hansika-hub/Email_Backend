from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Only readonly Gmail scope is needed
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service(access_token):
    """
    Given an access_token from the frontend, build and return a Gmail API service object.
    """
    creds = Credentials(token=access_token, scopes=SCOPES)
    service = build('gmail', 'v1', credentials=creds)
    return service

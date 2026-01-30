from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.config import settings

def get_calendar_service(tokens: dict):
    creds = Credentials(
        token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    return build("calendar", "v3", credentials=creds)

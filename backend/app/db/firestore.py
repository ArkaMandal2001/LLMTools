import firebase_admin
from firebase_admin import credentials, firestore
from app.config import settings

if not firebase_admin._apps:
    # Use environment variables for Firebase credentials
    if not settings.FIREBASE_PROJECT_ID or not settings.FIREBASE_PRIVATE_KEY:
        raise ValueError(
            "Firebase credentials not found. Please set FIREBASE_* environment variables."
        )
    
    # Construct credentials dict from environment variables
    cred_dict = {
        "type": "service_account",
        "project_id": settings.FIREBASE_PROJECT_ID,
        "private_key_id": settings.FIREBASE_PRIVATE_KEY_ID,
        "private_key": settings.FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
        "client_email": settings.FIREBASE_CLIENT_EMAIL,
        "client_id": settings.FIREBASE_CLIENT_ID,
        "auth_uri": settings.FIREBASE_AUTH_URI,
        "token_uri": settings.FIREBASE_TOKEN_URI,
        "auth_provider_x509_cert_url": settings.FIREBASE_AUTH_PROVIDER_X509_CERT_URL,
        "client_x509_cert_url": settings.FIREBASE_CLIENT_X509_CERT_URL,
        "universe_domain": settings.FIREBASE_UNIVERSE_DOMAIN,
    }
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client(database_id="voicecalendar")

def get_user_google_tokens(user_id: str) -> dict:
    doc = db.document(f"users/{user_id}").get()
    if not doc.exists:
        raise ValueError("User not found")

    data = doc.to_dict()
    return data["google_tokens"]


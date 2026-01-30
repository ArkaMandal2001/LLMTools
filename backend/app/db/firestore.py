import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
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


def save_conversation_message(user_id: str, role: str, content: str) -> None:
    """Save a message to the user's conversation history"""
    conversation_ref = db.collection("conversations").document(user_id)
    
    message = {
        "role": role,  # "user" or "assistant"
        "content": content,
        "timestamp": datetime.utcnow()
    }
    
    # Check if document exists, if not create it first
    if not conversation_ref.get().exists:
        conversation_ref.set({
            "messages": [message],
            "created_at": datetime.utcnow()
        })
    else:
        # Add message to the array
        conversation_ref.update({
            "messages": firestore.ArrayUnion([message])
        })


def get_conversation_history(user_id: str, limit: int = 10) -> list:
    """Get the last N messages from conversation history"""
    conversation_ref = db.collection("conversations").document(user_id)
    doc = conversation_ref.get()
    
    if not doc.exists:
        return []
    
    data = doc.to_dict()
    messages = data.get("messages", [])
    
    # Return the last 'limit' messages
    return messages[-limit:]


def clear_conversation_history(user_id: str) -> None:
    """Clear conversation history for a user"""
    conversation_ref = db.collection("conversations").document(user_id)
    conversation_ref.set({
        "messages": [],
        "created_at": datetime.utcnow()
    })
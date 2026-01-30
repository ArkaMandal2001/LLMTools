from typing import Dict

def user_doc(user_id: str) -> str:
    return f"users/{user_id}"

def session_doc(session_id: str) -> str:
    return f"sessions/{session_id}"

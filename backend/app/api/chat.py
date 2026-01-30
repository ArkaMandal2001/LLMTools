from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Optional
from app.auth.middleware import require_auth
from app.llm.graph import run_graph

router = APIRouter()


class ChatMessage(BaseModel):
    message: str
    timezone: Optional[str] = None  # Timezone offset in format "+05:30" or "-05:00"


@router.post("/chat", dependencies=[Depends(require_auth)])
def chat(payload: ChatMessage, request: Request):
    user_id = request.state.user_id
    message = payload.message
    user_timezone = payload.timezone or "+00:00"  # Use UTC offset if not provided
    
    print(f"\n[CHAT] Received message from user {user_id}: {message} (timezone: {user_timezone})")
    response = run_graph(user_id, message, user_timezone=user_timezone)
    print(f"[CHAT] Sending response back to user: {response}")
    return {"response": response}

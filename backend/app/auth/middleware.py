from fastapi import Request, HTTPException
from app.auth.sessions import verify_session_token

async def require_auth(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth.split(" ")[1]
    try:
        user_id = verify_session_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    request.state.user_id = user_id

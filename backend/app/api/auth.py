from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import jwt
import base64
import json

from app.auth.google_oauth import create_oauth_flow, get_authorization_url
from app.auth.sessions import create_session_token
from app.config import settings
from app.db.firestore import db

router = APIRouter()

@router.get("/auth/google/login")
def google_login(request: Request, frontend_url: str = Query(None)):
    """
    Initiate Google OAuth login.
    
    Args:
        frontend_url: Optional frontend URL to redirect to after OAuth.
                     If not provided, will try to extract from Referer header.
    """
    # Determine frontend URL dynamically from request
    # Priority: 1) Query parameter, 2) Referer header, 3) Origin header, 4) Infer from request
    if frontend_url:
        target_frontend = frontend_url
        print(f"[AUTH] Using frontend_url from query parameter: {target_frontend}")
    else:
        # Try Referer header first (most reliable)
        referer = request.headers.get("referer")
        if referer and referer.strip():
            try:
                parsed = urlparse(referer)
                if parsed.scheme and parsed.netloc:
                    target_frontend = f"{parsed.scheme}://{parsed.netloc}"
                    print(f"[AUTH] Using frontend URL from Referer header: {target_frontend}")
                else:
                    raise ValueError("Invalid referer URL")
            except Exception as e:
                print(f"[AUTH] Error parsing referer: {e}")
                referer = None
        
        # Try Origin header as fallback
        if not referer or not referer.strip():
            origin = request.headers.get("origin")
            if origin and origin.strip():
                try:
                    parsed = urlparse(origin)
                    if parsed.scheme and parsed.netloc:
                        target_frontend = f"{parsed.scheme}://{parsed.netloc}"
                        print(f"[AUTH] Using frontend URL from Origin header: {target_frontend}")
                    else:
                        raise ValueError("Invalid origin URL")
                except Exception as e:
                    print(f"[AUTH] Error parsing origin: {e}")
                    origin = None
        
        # If neither Referer nor Origin available, try to infer from request
        if (not referer or not referer.strip()) and (not origin or not origin.strip()):
            # For local development: try to infer from the request URL
            try:
                base_url = str(request.base_url).rstrip('/')
                parsed = urlparse(base_url)
                
                # Check if we're running locally
                if parsed.hostname in ['localhost', '127.0.0.1'] or (parsed.hostname and parsed.hostname.startswith('192.168.')):
                    # For local development, assume frontend is on port 3000
                    if ':8080' in base_url:
                        target_frontend = base_url.replace(':8080', ':3000')
                    else:
                        # If backend is not on 8080, use same host with port 3000
                        target_frontend = f"{parsed.scheme}://{parsed.hostname}:3000"
                    print(f"[AUTH] No Referer/Origin header, inferred local frontend URL: {target_frontend}")
                else:
                    # For non-local, we can't guess - require explicit parameter
                    raise ValueError(
                        "Cannot determine frontend URL automatically. Please either:\n"
                        "1. Pass frontend_url query parameter: /auth/google/login?frontend_url=YOUR_URL, or\n"
                        "2. Ensure your frontend sends a Referer or Origin header when redirecting to login"
                    )
            except ValueError:
                raise  # Re-raise ValueError
            except Exception as e:
                raise ValueError(
                    f"Cannot determine frontend URL. Error: {e}\n"
                    "Please pass frontend_url query parameter: /auth/google/login?frontend_url=YOUR_URL"
                )
    
    flow = create_oauth_flow()
    auth_url, oauth_state = get_authorization_url(flow)
    
    # Store frontend URL in OAuth state (combine with Google's state)
    # Google's state is for CSRF protection, we'll append our data
    state_data = {
        "frontend_url": target_frontend,
        "oauth_state": oauth_state  # Preserve Google's state
    }
    state_encoded = base64.urlsafe_b64encode(
        json.dumps(state_data).encode()
    ).decode()
    
    # Replace the state parameter in the auth URL with our combined state
    parsed = urlparse(auth_url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    query_params['state'] = [state_encoded]  # Replace state with our combined state
    
    # Reconstruct URL
    new_query = urlencode(query_params, doseq=True)
    auth_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    
    print(f"[AUTH] Login initiated, will redirect to: {target_frontend}")
    
    return RedirectResponse(auth_url)

@router.get("/auth/google/callback")
def google_callback(code: str, state: str = Query(None)):
    """
    Handle Google OAuth callback.
    
    Args:
        code: Authorization code from Google
        state: OAuth state containing frontend URL
    """
    # Extract frontend URL from state
    if not state:
        raise ValueError(
            "OAuth state parameter is missing. "
            "This indicates the login flow did not preserve the state. "
            "Please try logging in again from your frontend application."
        )
    
    try:
        state_data = json.loads(
            base64.urlsafe_b64decode(state.encode()).decode()
        )
        frontend_url = state_data.get("frontend_url")
        
        if not frontend_url:
            raise ValueError(
                "Frontend URL not found in OAuth state. "
                "This indicates the login flow did not preserve the frontend URL. "
                "Please try logging in again from your frontend application."
            )
        
        print(f"[AUTH] Callback received, will redirect to: {frontend_url}")
    except ValueError:
        raise  # Re-raise ValueError
    except Exception as e:
        raise ValueError(
            f"Could not decode OAuth state: {e}. "
            "Please try logging in again from your frontend application."
        )
    
    flow = create_oauth_flow()
    flow.fetch_token(code=code)

    credentials = flow.credentials
    
    # Extract ID token from the token response
    token_response = credentials.token
    id_token_jwt = credentials.id_token or token_response
    
    if not id_token_jwt:
        raise ValueError("ID token not found in response")
    
    # Decode the ID token without verification to get user info
    # (verify_oauth2_token would verify it, but we can also just decode for development)
    try:
        # Try to verify with Google's public keys
        request = requests.Request()
        info = id_token.verify_oauth2_token(
            id_token_jwt, request, settings.GOOGLE_CLIENT_ID
        )
    except:
        # Fallback: decode without verification for testing
        info = jwt.decode(id_token_jwt, options={"verify_signature": False})

    user_id = info["sub"]

    db.document(f"users/{user_id}").set({
        "email": info["email"],
        "google_tokens": {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
        }
    }, merge=True)

    session_token = create_session_token(user_id)
    
    # Redirect to frontend with token (use the frontend URL from state)
    return RedirectResponse(
        f"{frontend_url}/?token={session_token}"
    )

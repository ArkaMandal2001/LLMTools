"""
WebSocket endpoint for OpenAI Realtime API integration
"""
import json
import asyncio
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from openai import OpenAI
from app.config import settings
from app.auth.middleware import get_user_id_from_token
from app.llm.realtime_handler import RealtimeHandler

router = APIRouter()

@router.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for Realtime API communication.
    Handles audio streaming and tool calls.
    """
    try:
        print(f"[REALTIME] New connection attempt from {websocket.client}")
        await websocket.accept()
        print(f"[REALTIME] WebSocket accepted")
        
        # Get user_id from query params or headers
        user_id = None
        token = websocket.query_params.get("token")
        timezone_offset = websocket.query_params.get("timezone", "+00:00")  # Default to UTC if not provided
        
        if not token:
            # Try to get from headers
            auth_header = websocket.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "")
        
        print(f"[REALTIME] Token received: {bool(token)}, timezone: {timezone_offset}")
        
        if token:
            try:
                user_id = get_user_id_from_token(token)
                print(f"[REALTIME] User authenticated: {user_id}")
            except Exception as e:
                print(f"[REALTIME] Auth error: {e}")
                import traceback
                traceback.print_exc()
                await websocket.close(code=1008, reason="Authentication failed")
                return
        
        if not user_id:
            print(f"[REALTIME] No user_id found")
            await websocket.close(code=1008, reason="User ID required")
            return
        
        print(f"[REALTIME] Connection established for user {user_id} with timezone {timezone_offset}")
        
        # Initialize OpenAI client
        if not settings.OPENAI_API_KEY:
            print(f"[REALTIME] ERROR: OPENAI_API_KEY not set")
            await websocket.close(code=1011, reason="Server configuration error")
            return
            
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        
        # Initialize handler with timezone
        handler = RealtimeHandler(user_id=user_id, websocket=websocket, client=client, user_timezone=timezone_offset)
        
        # Start handling messages
        await handler.handle_connection()
        
    except WebSocketDisconnect:
        print(f"[REALTIME] Client disconnected")
    except Exception as e:
        print(f"[REALTIME] Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.close(code=1011, reason=f"Server error: {str(e)}")
        except:
            pass
    finally:
        try:
            if 'handler' in locals():
                await handler.cleanup()
        except:
            pass

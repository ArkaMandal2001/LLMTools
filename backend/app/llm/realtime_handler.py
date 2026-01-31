"""
Handler for OpenAI Realtime API integration with tool support
"""
import json
import asyncio
import base64
from typing import Dict, Any
from openai import OpenAI
from fastapi import WebSocket, WebSocketDisconnect
from app.llm.tools import (
    check_availability,
    find_available_slots,
    create_event,
    get_upcoming_events,
    get_current_time,
)
from app.llm.prompts import get_system_prompt
from app.llm.tools import get_current_datetime_info


class RealtimeHandler:
    """Handles Realtime API communication and tool calls"""
    
    def __init__(self, user_id: str, websocket: WebSocket, client: OpenAI, user_timezone: str = "+00:00"):
        self.user_id = user_id
        self.websocket = websocket
        self.client = client
        self.user_timezone = user_timezone  # Store user's timezone offset (e.g., "+05:30", "-05:00")
        self.session = None
        self._stop_flag = False  # Flag to signal cancellation
        self._recv_lock = asyncio.Lock()  # Lock to ensure only one recv() call at a time
        self.tool_map = {
            "get_current_time": get_current_time,
            "check_availability": check_availability,
            "find_available_slots": find_available_slots,
            "create_event": create_event,
            "get_upcoming_events": get_upcoming_events,
        }
        # Store config for later use
        time_info = get_current_datetime_info()
        self.system_prompt = get_system_prompt(self.user_id, time_info)
        self.tools = self._define_tools()
        print(f"[REALTIME] Initialized handler with timezone: {self.user_timezone}")
    
    def _define_tools(self):
        """Define tools for Realtime API"""
        return [
            {
                "type": "function",
                "name": "get_current_time",
                "description": "Get the current date and time",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "type": "function",
                "name": "check_availability",
                "description": "Check user's calendar availability during a specified time period",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {
                            "type": "string",
                            "description": "Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS)"
                        },
                        "end": {
                            "type": "string",
                            "description": "End datetime in ISO format (YYYY-MM-DDTHH:MM:SS)"
                        }
                    },
                    "required": ["start", "end"]
                }
            },
            {
                "type": "function",
                "name": "find_available_slots",
                "description": "Find available time slots for meetings within a date range",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {
                            "type": "string",
                            "description": "Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                        },
                        "end": {
                            "type": "string",
                            "description": "End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Desired meeting duration in minutes (default: 30)"
                        }
                    },
                    "required": ["start", "end"]
                }
            },
            {
                "type": "function",
                "name": "create_event",
                "description": "Create a new event on the user's Google Calendar",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Event title/summary"
                        },
                        "start": {
                            "type": "string",
                            "description": "Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS)"
                        },
                        "end": {
                            "type": "string",
                            "description": "End datetime in ISO format (YYYY-MM-DDTHH:MM:SS)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description (optional)"
                        }
                    },
                    "required": ["title", "start", "end"]
                }
            },
            {
                "type": "function",
                "name": "get_upcoming_events",
                "description": "Get upcoming events for the user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "Number of hours to look ahead (default: 24)"
                        }
                    },
                    "required": []
                }
            }
        ]
    
    async def handle_connection(self):
        """Handle the WebSocket connection and Realtime API events"""
        # Send connection confirmation immediately
        try:
            await self.websocket.send_json({
                "type": "connection.update",
                "status": "connected"
            })
            print(f"[REALTIME] Sent connection confirmation to frontend")
        except Exception as e:
            print(f"[REALTIME] Error sending connection confirmation: {e}")
        
        # Create Realtime API session - it's a context manager (has 'enter' method)
        session_manager = self.client.beta.realtime.connect(
            model="gpt-4o-realtime-preview-2024-12-17",
        )
        
        # Use the session as a context manager
        try:
            with session_manager as session:
                self.session = session
                print(f"[REALTIME] Realtime session established")
                
                # Send initial configuration via session.update event
                # The session has a send() method
                try:
                    session.send({
                        "type": "session.update",
                        "session": {
                            "voice": "alloy",
                            "instructions": self.system_prompt,
                            "tools": self.tools,
                            "tool_choice": "auto",
                            "temperature": 0.7,
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "prefix_padding_ms": 300,
                                "silence_duration_ms": 500,
                            },
                            "modalities": ["audio", "text"],  # API requires both, but frontend only uses audio
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm16",
                            "input_audio_transcription": {
                                "model": "whisper-1"
                            },
                        }
                    })
                    print(f"[REALTIME] Sent session configuration with turn detection")
                except Exception as e:
                    print(f"[REALTIME] Error sending session update: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Start background task to forward Realtime API events to WebSocket
                print(f"[REALTIME] Starting background task to forward Realtime events")
                forward_task = asyncio.create_task(self._forward_realtime_events())
                
                try:
                    # Handle WebSocket messages from frontend
                    print(f"[REALTIME] Starting WebSocket message receive loop")
                    message_count = 0
                    while True:
                        try:
                            data = await self.websocket.receive()
                            message_count += 1
                            
                            # Log every message for debugging
                            if message_count <= 5 or message_count % 100 == 0:
                                print(f"[REALTIME] Received message #${message_count}, keys: {list(data.keys())}")
                            
                            # Check if it's a disconnect message
                            if data.get("type") == "websocket.disconnect":
                                print(f"[REALTIME] Received disconnect message")
                                break
                            
                            # Handle binary audio data (frontend only sends binary audio)
                            if "bytes" in data:
                                # Handle binary audio data
                                audio_data = data["bytes"]
                                audio_size = len(audio_data)
                                if message_count <= 5 or message_count % 100 == 0:
                                    print(f"[REALTIME] Received binary audio data: {audio_size} bytes")
                                await self._handle_audio_data(audio_data)
                            else:
                                print(f"[REALTIME] Received unknown data type (message #{message_count}): {list(data.keys())}, full data: {data}")
                        except WebSocketDisconnect:
                            print(f"[REALTIME] WebSocket disconnected")
                            break
                        except RuntimeError as e:
                            # Handle "Cannot call receive once a disconnect message has been received"
                            if "disconnect" in str(e).lower():
                                print(f"[REALTIME] WebSocket already disconnected")
                                break
                            raise
                        except json.JSONDecodeError:
                            print(f"[REALTIME] Invalid JSON received")
                            # Continue loop for JSON errors
                        except Exception as e:
                            print(f"[REALTIME] Error handling message: {e}")
                            import traceback
                            traceback.print_exc()
                            # Check if it's a disconnect-related error
                            if "disconnect" in str(e).lower():
                                break
                finally:
                    print(f"[REALTIME] Cleaning up - setting stop flag and cancelling tasks")
                    self._stop_flag = True
                    forward_task.cancel()
                    try:
                        await asyncio.wait_for(forward_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        print(f"[REALTIME] Forward task didn't cancel in time, forcing close")
                    except asyncio.CancelledError:
                        print(f"[REALTIME] Forward task cancelled successfully")
                    except Exception as e:
                        print(f"[REALTIME] Error cancelling forward task: {e}")
        except Exception as e:
            print(f"[REALTIME] Error with Realtime session: {e}")
            import traceback
            traceback.print_exc()
    
    async def _handle_audio_data(self, audio_data: bytes):
        """Handle binary audio data from frontend - stream directly to Realtime API"""
        if self.session:
            # Send audio data to Realtime API via input_audio_buffer.append event
            # The buffer.append() method doesn't take arguments - we send events instead
            try:
                # Encode audio as base64 and send as an event
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                self.session.send({
                    "type": "input_audio_buffer.append",
                    "audio": audio_base64
                })
                print(f"[REALTIME] Sent {len(audio_data)} bytes to input buffer")
            except Exception as e:
                print(f"[REALTIME] Error sending audio: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[REALTIME] WARNING: Received audio but session is None")
    
    async def _forward_realtime_events(self):
        """Forward Realtime API events to WebSocket client"""
        print(f"[REALTIME] _forward_realtime_events task started")
        try:
            # The session has recv() method to receive events
            # recv() is blocking and cannot be called concurrently
            # We must ensure only one recv() call is active at a time
            while not self._stop_flag:
                try:
                    # Check stop flag before attempting recv
                    if self._stop_flag:
                        print(f"[REALTIME] Stop flag set, exiting event loop")
                        break
                    
                    # Use lock to ensure only one recv() call at a time
                    # The lock prevents concurrent calls
                    async with self._recv_lock:
                        # Run recv() in thread pool - it will block until an event is received
                        # We don't use timeout because recv() cannot be cancelled mid-call
                        # Instead, we rely on the stop flag and session.close() for cleanup
                        try:
                            event = await asyncio.to_thread(self.session.recv)
                        except Exception as e:
                            # If recv() fails (e.g., connection closed), check stop flag
                            if self._stop_flag:
                                print(f"[REALTIME] Stop flag set, exiting after recv error")
                                break
                            # Re-raise to handle in outer exception handler
                            raise
                    
                    # Convert event object to dictionary
                    event_dict = self._event_to_dict(event)
                    
                    event_type = event_dict.get('type', 'unknown')
                    
                    # Log important events for debugging
                    if event_type in ["response.created", "response.output_item.done", "response.done", "response.audio.delta", 
                                     "response.audio_transcript.delta", "response.text.delta", "response.output_item.added"]:
                        print(f"[REALTIME] Received event: {event_type}")
                        if event_type == "response.created":
                            print(f"[REALTIME] New response created: {event_dict.get('response', {}).get('id', 'N/A')}")
                        elif event_type == "response.output_item.done":
                            print(f"[REALTIME] Output item done: {event_dict.get('item', {}).get('type', 'N/A')}")
                        elif event_type == "response.audio.delta":
                            delta_len = len(event_dict.get('delta', ''))
                            print(f"[REALTIME] Audio delta received: {delta_len} chars (base64), ~{delta_len * 3 // 4} bytes decoded")
                        elif event_type == "response.text.delta":
                            print(f"[REALTIME] Text delta received: {event_dict.get('delta', '')[:50]}")
                    elif not event_type.startswith("rate_limits") and not event_type.startswith("conversation.item.input_audio"):
                        # Log other events except rate limits and input audio transcription
                        print(f"[REALTIME] Received event: {event_type}")
                    
                    # Handle error events
                    if event_type == "error":
                        error_message = event_dict.get('error', {}).get('message', 'Unknown error') if isinstance(event_dict.get('error'), dict) else str(event_dict.get('error', 'Unknown error'))
                        error_code = event_dict.get('error', {}).get('code', 'unknown') if isinstance(event_dict.get('error'), dict) else 'unknown'
                        print(f"[REALTIME] ERROR: {error_message} (code: {error_code})")
                        print(f"[REALTIME] Full error event: {event_dict}")
                        # Forward error to frontend
                        await self.websocket.send_json(event_dict)
                        continue
                    
                    # Handle tool calls
                    if event_type == "response.function_call_arguments.done":
                        await self._handle_tool_call(event_dict)
                    
                    # Forward all events as JSON to frontend
                    # Audio events contain base64-encoded audio in the delta field
                    # Frontend will handle decoding and playback
                    await self.websocket.send_json(event_dict)
                    
                except asyncio.CancelledError:
                    print(f"[REALTIME] _forward_realtime_events task cancelled")
                    raise
                except Exception as e:
                    # Check if it's a connection closed error
                    error_str = str(e).lower()
                    if "closed" in error_str or "disconnect" in error_str or "connection" in error_str:
                        print(f"[REALTIME] Realtime connection closed: {e}")
                        break
                    if self._stop_flag:
                        print(f"[REALTIME] Stop flag set, exiting event loop")
                        break
                    print(f"[REALTIME] Error in _forward_realtime_events: {e}")
                    import traceback
                    traceback.print_exc()
                    # Continue loop to try receiving again
                    await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            print(f"[REALTIME] _forward_realtime_events task cancelled")
            raise
        except Exception as e:
            print(f"[REALTIME] Error forwarding events: {e}")
            import traceback
            traceback.print_exc()
    
    def _event_to_dict(self, event) -> Dict[str, Any]:
        """Convert Realtime API event to dictionary"""
        if hasattr(event, 'model_dump'):
            return event.model_dump()
        elif hasattr(event, 'dict'):
            return event.dict()
        elif isinstance(event, dict):
            return event
        else:
            return {"type": str(type(event).__name__), "data": str(event)}
    
    async def _handle_tool_call(self, event: Dict[str, Any]):
        """Handle tool calls from Realtime API"""
        try:
            call_id = event.get("call_id")
            function_name = event.get("name")
            arguments_str = event.get("arguments", "{}")
            
            # Parse arguments
            if isinstance(arguments_str, str):
                arguments = json.loads(arguments_str)
            else:
                arguments = arguments_str
            
            print(f"[REALTIME] Tool call: {function_name} with args: {arguments}")
            
            # Get the tool function
            tool_func = self.tool_map.get(function_name)
            if not tool_func:
                result = f"Error: Tool {function_name} not found"
            else:
                # Add user_id to arguments
                arguments["user_id"] = self.user_id
                
                # Add timezone if needed (use the user's timezone from connection)
                if function_name in ["create_event", "get_upcoming_events", "check_availability"]:
                    arguments.setdefault("user_timezone", self.user_timezone)
                    print(f"[REALTIME] Using timezone {self.user_timezone} for tool {function_name}")
                
                # Call the tool
                try:
                    result = tool_func.invoke(arguments)
                except Exception as e:
                    result = f"Error: {str(e)}"
                    import traceback
                    traceback.print_exc()
            
            # Provide tool result to Realtime API
            # The Realtime API doesn't support sending function_call_output as an event
            # However, we can inject the tool result into the conversation so the API can use it
            # This allows the API to generate a response based on the tool result
            print(f"[REALTIME] Tool execution completed for call_id {call_id}")
            print(f"[REALTIME] Tool result: {result[:200]}...")
            
            # Inject the tool result into the conversation so the API can use it
            # The Realtime API doesn't have a direct way to provide tool results,
            # so we inject it as a conversation item and then request a response
            try:
                # Format the tool result as a natural language message
                if isinstance(result, dict):
                    # Format dict results nicely
                    result_str = json.dumps(result, indent=2)
                else:
                    result_str = str(result)
                
                # Format as if the assistant is reporting the tool result
                # This allows the API to continue the conversation naturally
                tool_result_message = f"I found the following information: {result_str}"
                
                # Inject as assistant message with the tool result
                # The API will see this and can generate a natural language response
                self.session.send({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": tool_result_message
                            }
                        ]
                    }
                })
                print(f"[REALTIME] Injected tool result into conversation")
                
                # With turn_detection enabled, the API should automatically generate a response
                # after seeing the tool result. However, since we're injecting it as an assistant
                # message, we may need to explicitly request a response.
                # Small delay to ensure the conversation item is processed
                await asyncio.sleep(0.2)
                
                # Request a new response from the API
                # The API should use the session's modalities configuration (audio + text)
                # Just send response.create without parameters - it should use session defaults
                self.session.send({"type": "response.create"})
                print(f"[REALTIME] Requested new response after tool result (should use session audio config)")
            except Exception as e:
                print(f"[REALTIME] Error injecting tool result: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            print(f"[REALTIME] Error handling tool call: {e}")
            import traceback
            traceback.print_exc()
    
    async def cleanup(self):
        """Cleanup resources"""
        print(f"[REALTIME] Cleanup called - setting stop flag")
        self._stop_flag = True
        if self.session:
            try:
                self.session.close()
                print(f"[REALTIME] Realtime session closed")
            except Exception as e:
                print(f"[REALTIME] Error closing Realtime session: {e}")
        # Session is cleaned up automatically when exiting the async with block
        self.session = None

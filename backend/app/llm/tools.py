from datetime import datetime, timedelta, timezone
from langchain_core.tools import tool
from google.auth.exceptions import RefreshError
from app.db.firestore import get_user_google_tokens
from app.llm.google_calendar import get_calendar_service


def parse_timezone_offset(offset_str: str) -> timezone:
    """
    Parse a timezone offset string (e.g., "+05:30", "-05:00") into a timezone object.
    
    Args:
        offset_str: Timezone offset in format "+HH:MM" or "-HH:MM" (e.g., "+05:30", "-05:00")
    
    Returns:
        timezone object representing the offset
    """
    if not offset_str or offset_str == "UTC":
        return timezone.utc
    
    # Parse offset string (e.g., "+05:30" or "-05:00")
    try:
        sign = offset_str[0]
        parts = offset_str[1:].split(":")
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        
        # Create timedelta (negative for ahead of UTC, positive for behind)
        # But Python timezone uses positive for ahead, negative for behind
        if sign == "+":
            delta = timedelta(hours=hours, minutes=minutes)
        else:  # sign == "-"
            delta = timedelta(hours=-hours, minutes=-minutes)
        
        return timezone(delta)
    except (ValueError, IndexError) as e:
        print(f"[TOOL] Invalid timezone offset '{offset_str}', falling back to UTC: {e}")
        return timezone.utc


def format_datetime_for_api(dt: datetime) -> str:
    """
    Format a datetime for Google Calendar API (RFC3339 format with Z for UTC).
    
    Args:
        dt: Datetime object (naive or timezone-aware)
    
    Returns:
        ISO format string with Z notation for UTC (e.g., "2026-01-29T13:24:48.754095Z")
    """
    # Make timezone-aware (UTC) if naive
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Format for Google Calendar API (replace +00:00 with Z)
    return dt.isoformat().replace('+00:00', 'Z')


def get_current_datetime_info():
    """
    Get current date and time information.
    Returns a dict with formatted date/time strings.
    Can be used both in tools and system prompts.
    """
    now = datetime.now(timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S UTC"),
        "datetime_full": now.strftime("%A, %B %d, %Y at %I:%M %p UTC"),
        "iso": now.isoformat(),
        "year": str(now.year),
    }


@tool
def get_current_time() -> str:
    """
    Get the current date and time.
    Returns:
        A string with the current date and time in ISO format and human-readable format
    """
    try:
        time_info = get_current_datetime_info()
        print(f"\n[TOOL] get_current_time called: {time_info['iso']}")
        result = f"Current date and time: {time_info['datetime_full']}\nISO format: {time_info['iso']}"
        print(f"[TOOL] get_current_time result: {result}")
        return result
    except Exception as e:
        error = f"Error getting current time: {str(e)}"
        print(f"[TOOL] get_current_time error: {error}")
        return error


@tool
def check_availability(user_id: str, start: str, end: str) -> str:
    """
    Check user's calendar availability during a specified time period. 
    ONLY use this tool when the user explicitly asks:
    - If they are free/available at a specific time
    - If they have conflicts during a time period
    - To check availability for scheduling
    
    Do NOT use this tool for casual conversation or greetings.
    
    Args:
        user_id: The user's unique identifier
        start: Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS)
        end: End datetime in ISO format (YYYY-MM-DDTHH:MM:SS)
    Returns:
        A string describing the user's availability and any conflicting events
    """
    try:
        print(f"\n[TOOL] check_availability called: user_id={user_id}, start={start}, end={end}")
        tokens = get_user_google_tokens(user_id)
        print(f"[TOOL] Got tokens: access_token={tokens.get('access_token')[:20] if tokens else None}...")
        service = get_calendar_service(tokens)
        print(f"[TOOL] Got calendar service")

        # Parse datetime strings (assumed to be naive/UTC)
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        
        # Format for Google Calendar API
        time_min = format_datetime_for_api(start_dt)
        time_max = format_datetime_for_api(end_dt)

        events = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        items = events.get("items", [])
        print(f"[TOOL] Found {len(items)} events during check_availability")

        if not items:
            return f"✓ You are free from {start} to {end}."

        busy_events = []
        print(f"[TOOL] Processing {len(items)} events:")
        for e in items:
            summary = e.get('summary', 'Unnamed event')
            start_time = e['start'].get('dateTime', e['start'].get('date', 'Unknown'))
            end_time = e['end'].get('dateTime', e['end'].get('date', 'Unknown'))
            print(f"[TOOL]   Event: {summary} ({start_time} → {end_time})")
            busy_events.append(f"  • {summary} ({start_time} → {end_time})")

        result = f"You have {len(busy_events)} conflicting event(s) during this time:\n" + "\n".join(busy_events)
        print(f"[TOOL] check_availability result: {result}")
        return result
    except RefreshError as e:
        error = "Your Google account access has expired. Please log out and log back in to refresh your calendar permissions."
        print(f"[TOOL] check_availability RefreshError: {error}")
        return error
    except Exception as e:
        error = f"Error checking availability: {str(e)}"
        print(f"[TOOL] check_availability error: {error}")
        import traceback
        traceback.print_exc()
        return error


@tool
def find_available_slots(user_id: str, start: str, end: str, duration_minutes: int = 30) -> str:
    """
    Find available time slots for meetings within a date range.
    Args:
        user_id: The user's unique identifier
        start: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        end: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        duration_minutes: Desired meeting duration in minutes (default: 30)
    Returns:
        A string listing available time slots
    """
    try:
        tokens = get_user_google_tokens(user_id)
        service = get_calendar_service(tokens)

        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        # If only date provided, use full day
        if start_dt.time() == datetime.min.time():
            start_dt = start_dt.replace(hour=9, minute=0)  # Start at 9 AM
        if end_dt.time() == datetime.min.time():
            end_dt = end_dt.replace(hour=17, minute=0)  # End at 5 PM

        # Format for Google Calendar API
        time_min = format_datetime_for_api(start_dt)
        time_max = format_datetime_for_api(end_dt)
        
        events = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        items = events.get("items", [])
        
        # Find gaps between events
        available_slots = []
        current_time = start_dt

        for event in items:
            event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
            event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))

            # Check if there's a gap before this event
            gap = event_start - current_time
            if gap.total_seconds() >= duration_minutes * 60:
                slot_end = current_time + timedelta(minutes=duration_minutes)
                available_slots.append(f"  • {current_time.isoformat()} → {slot_end.isoformat()}")

            current_time = max(current_time, event_end)

        # Check gap after last event
        if current_time < end_dt:
            gap = end_dt - current_time
            if gap.total_seconds() >= duration_minutes * 60:
                slot_end = current_time + timedelta(minutes=duration_minutes)
                available_slots.append(f"  • {current_time.isoformat()} → {slot_end.isoformat()}")

        if available_slots:
            return f"Available {duration_minutes}-minute slots:\n" + "\n".join(available_slots)
        else:
            return f"No available {duration_minutes}-minute slots found between {start} and {end}."
    except RefreshError as e:
        return "Your Google account access has expired. Please log out and log back in to refresh your calendar permissions."
    except Exception as e:
        return f"Error finding available slots: {str(e)}"


@tool
def create_event(user_id: str, title: str, start: str, end: str, description: str = "", user_timezone: str = None) -> str:
    """
    Create a new event on the user's Google Calendar.
    ONLY use this tool when the user explicitly asks to:
    - Schedule, create, or add an event/meeting/appointment
    - Book a time slot
    - Add something to their calendar
    
    Do NOT use this tool unless the user clearly wants to create an event.
    
    CRITICAL: DO NOT CALL THIS TOOL IF INFORMATION IS MISSING!
    - This tool requires ALL of the following: title, start date, start time, and end time
    - If the user says "schedule a meeting tomorrow" without a time → ASK for the time first
    - If the user says "schedule a 1 hour meeting" without a date/time → ASK for date and time first
    - If the user says "book something for 2pm" without a date/title → ASK for date and title first
    - NEVER assume default times, dates, or durations - always ask the user for missing information
    
    REQUIRED PARAMETERS (all must be provided):
    - title: Event name/title (e.g., "Dentist Appointment", "Team Meeting")
    - start: Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS) - must include both date AND time
    - end: End datetime in ISO format (YYYY-MM-DDTHH:MM:SS) - must include both date AND time
    
    CRITICAL TIMEZONE HANDLING:
    - The user is in their local timezone (provided in request or defaults to UTC)
    - When the user says "12pm" or "2:30pm", they mean their LOCAL time
    - Convert the time to ISO format (YYYY-MM-DDTHH:MM:SS) assuming it's in the user's local timezone
    - Example: If user says "12pm on January 30", use "2026-01-30T12:00:00" (the tool will treat this as local time)
    
    Args:
        user_id: The user's unique identifier
        title: Event title/summary (REQUIRED - do not assume if missing)
        start: Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS) - interpret as LOCAL time (REQUIRED - must include date AND time)
        end: End datetime in ISO format (YYYY-MM-DDTHH:MM:SS) - interpret as LOCAL time (REQUIRED - must include date AND time)
        description: Event description (optional)
    Returns:
        A string confirming the event creation with the calendar link
    """
    try:
        print(f"\n[TOOL] create_event called: user_id={user_id}, title={title}, start={start}, end={end}, timezone={user_timezone}")
        tokens = get_user_google_tokens(user_id)
        service = get_calendar_service(tokens)

        # Parse datetime as naive (assumed to be in user's local timezone)
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        print(f"[TOOL] Parsed datetimes: start={start_dt}, end={end_dt}")
        
        # Get user timezone offset (from parameter or fallback to UTC)
        if user_timezone is None:
            user_timezone = "+00:00"
        
        # Parse timezone offset (e.g., "+05:30" or "-05:00")
        user_tz = parse_timezone_offset(user_timezone)
        print(f"[TOOL] Parsed timezone offset '{user_timezone}' to timezone object")
        
        # Localize to user's timezone (treat naive datetime as local time)
        start_dt_local = start_dt.replace(tzinfo=user_tz)
        end_dt_local = end_dt.replace(tzinfo=user_tz)
        print(f"[TOOL] Localized datetimes: start={start_dt_local}, end={end_dt_local}, offset={user_timezone}")
        
        # Validate that the event is not in the past
        now_local = datetime.now(user_tz)
        if start_dt_local < now_local:
            warning = f"WARNING: Event start time {start_dt_local} is in the past (current time: {now_local}). Event may not appear in calendar views."
            print(f"[TOOL] {warning}")
            # Don't fail, but log the warning - the event will still be created
        
        # Convert to UTC for Google Calendar API (API requires timezone name, so we use UTC)
        start_dt_utc = start_dt_local.astimezone(timezone.utc)
        end_dt_utc = end_dt_local.astimezone(timezone.utc)

        event = {
            "summary": title,
            "start": {"dateTime": start_dt_utc.isoformat().replace('+00:00', 'Z'), "timeZone": "UTC"},
            "end": {"dateTime": end_dt_utc.isoformat().replace('+00:00', 'Z'), "timeZone": "UTC"},
        }

        if description:
            event["description"] = description

        print(f"[TOOL] Creating event with body: {event}")
        print(f"[TOOL] Using calendarId='primary' (user's main calendar)")
        try:
            created = service.events().insert(
                calendarId="primary",
                body=event
            ).execute()
            
            event_id = created.get('id')
            event_link = created.get('htmlLink')
            event_start = created.get('start', {}).get('dateTime', 'N/A')
            event_end = created.get('end', {}).get('dateTime', 'N/A')
            event_calendar_id = created.get('organizer', {}).get('email', 'N/A')
            event_status = created.get('status', 'N/A')
            event_visibility = created.get('visibility', 'N/A')
            event_attendees = created.get('attendees', [])
            
            print(f"[TOOL] Event created successfully!")
            print(f"[TOOL] Event ID: {event_id}")
            print(f"[TOOL] Event Link: {event_link}")
            print(f"[TOOL] Event Start: {event_start}")
            print(f"[TOOL] Event End: {event_end}")
            print(f"[TOOL] Event Calendar (organizer): {event_calendar_id}")
            print(f"[TOOL] Event Status: {event_status}")
            print(f"[TOOL] Event Visibility: {event_visibility}")
            print(f"[TOOL] Event Attendees: {len(event_attendees)}")
            
            # Verify the event is in the primary calendar
            if event_status != 'confirmed':
                print(f"[TOOL] WARNING: Event status is '{event_status}', not 'confirmed'!")
            
            if not event_id:
                print(f"[TOOL] WARNING: Event created but no ID returned!")
                return f"Error: Event creation may have failed - no event ID returned. Please check your Google Calendar."
        except Exception as api_error:
            error_msg = f"Google Calendar API error: {str(api_error)}"
            print(f"[TOOL] API error during event creation: {error_msg}")
            import traceback
            traceback.print_exc()
            return f"Error creating event: {error_msg}"

        # Format time for user-friendly response (TTS-friendly)
        start_time_str = start_dt.strftime("%I:%M %p").lstrip('0')
        end_time_str = end_dt.strftime("%I:%M %p").lstrip('0')
        date_str = start_dt.strftime("%B %d, %Y")
        
        return f"I've scheduled {title} for {date_str} from {start_time_str} to {end_time_str}."
    except RefreshError as e:
        error_msg = "Your Google account access has expired. Please log out and log back in to refresh your calendar permissions."
        print(f"[TOOL] create_event RefreshError: {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Error creating event: {str(e)}"
        print(f"[TOOL] create_event error: {error_msg}")
        import traceback
        traceback.print_exc()
        return error_msg


@tool
def get_upcoming_events(user_id: str, hours: int = 24, user_timezone: str = None) -> str:
    """
    Get upcoming events for the user. ONLY use this tool when the user explicitly asks about:
    - Their calendar, schedule, or appointments
    - Upcoming events or meetings
    - What they have planned
    - Events on a specific day or time period
    
    Do NOT use this tool for:
    - Simple greetings or casual conversation
    - General questions unrelated to calendar
    
    Args:
        user_id: The user's unique identifier
        hours: Number of hours to look ahead (default: 24)
    Returns:
        A string listing upcoming events
    """
    try:
        print(f"\n[TOOL] get_upcoming_events called: user_id={user_id}, hours={hours}")
        tokens = get_user_google_tokens(user_id)
        service = get_calendar_service(tokens)

        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=hours)
        
        # Format for Google Calendar API
        time_min = format_datetime_for_api(now)
        time_max = format_datetime_for_api(future)
        print(f"[TOOL] Query range: {time_min} to {time_max}")

        events = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        items = events.get("items", [])
        print(f"[TOOL] get_upcoming_events found {len(items)} events")

        if not items:
            result = f"No upcoming events in the next {hours} hours."
            print(f"[TOOL] get_upcoming_events result: {result}")
            return result

        # Get user timezone offset (from parameter or fallback to UTC)
        if user_timezone is None:
            user_timezone = "+00:00"
        
        # Parse timezone offset (e.g., "+05:30" or "-05:00")
        user_tz = parse_timezone_offset(user_timezone)
        utc_tz = timezone.utc
        upcoming = []
        
        for e in items:
            summary = e.get('summary', 'Unnamed event')
            start_time_str = e['start'].get('dateTime', e['start'].get('date', 'Unknown'))
            
            # Parse and convert to user's local timezone for display
            if 'T' in start_time_str:
                # Has time component - parse ISO format
                try:
                    # Handle Z suffix (UTC)
                    if start_time_str.endswith('Z'):
                        dt_str = start_time_str.replace('Z', '+00:00')
                        dt = datetime.fromisoformat(dt_str)
                    else:
                        dt = datetime.fromisoformat(start_time_str)
                    
                    # Ensure timezone-aware
                    if dt.tzinfo is None:
                        dt_utc = dt.replace(tzinfo=utc_tz)
                    else:
                        dt_utc = dt
                    
                    # Convert to user's local timezone
                    dt_local = dt_utc.astimezone(user_tz)
                    formatted_time = dt_local.strftime("%B %d at %I:%M %p").lstrip('0').replace(' 0', ' ')
                    upcoming.append(f"{summary} on {formatted_time}")
                except Exception as parse_error:
                    # Fallback: just use the raw string
                    print(f"[TOOL] Error parsing datetime {start_time_str}: {parse_error}")
                    upcoming.append(f"{summary} on {start_time_str}")
            else:
                # Date only
                try:
                    dt = datetime.fromisoformat(start_time_str)
                    formatted_date = dt.strftime("%B %d, %Y")
                    upcoming.append(f"{summary} on {formatted_date}")
                except:
                    upcoming.append(f"{summary} on {start_time_str}")
            
            print(f"[TOOL]   Event: {summary} - {start_time_str}")

        if upcoming:
            result = "Upcoming events:\n" + "\n".join(upcoming)
        else:
            result = f"No upcoming events in the next {hours} hours."
        print(f"[TOOL] get_upcoming_events result:\n{result}")
        return result
    except RefreshError as e:
        error = "Your Google account access has expired. Please log out and log back in to refresh your calendar permissions."
        print(f"[TOOL] get_upcoming_events RefreshError: {error}")
        return error
    except Exception as e:
        error = f"Error fetching upcoming events: {str(e)}"
        print(f"[TOOL] get_upcoming_events error: {error}")
        import traceback
        traceback.print_exc()
        return error

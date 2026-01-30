from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from app.llm.tools import (
    check_availability,
    find_available_slots,
    create_event,
    get_upcoming_events,
    get_current_time,
    get_current_datetime_info,
)
from app.llm.prompts import get_system_prompt
from app.config import settings
from app.db.firestore import (
    get_conversation_history,
    save_conversation_message
)


class State(TypedDict):
    """Graph state for calendar assistant"""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    user_timezone: str


# Define tools for the LLM agent
tools = [
    get_current_time,
    check_availability,
    find_available_slots,
    create_event,
    get_upcoming_events,
]

# Initialize OpenAI LLM
llm = ChatOpenAI(
    model="gpt-4.1-mini",
    temperature=0,
    api_key=settings.OPENAI_API_KEY,
)

# Bind tools to the LLM
llm_with_tools = llm.bind_tools(tools)


def should_continue(state: State) -> str:
    """Determine if we should continue or end"""
    messages = state["messages"]
    last_message = messages[-1]
    
    # If the last message is from the assistant and has no tool calls, we're done
    if isinstance(last_message, AIMessage):
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return END
    
    return "continue"


def call_llm(state: State) -> State:
    """Call the LLM with tools"""
    messages = state["messages"]
    
    # Get current date/time for context using the same function as the tool
    time_info = get_current_datetime_info()
    
    # Get system prompt from separate file
    system_prompt = get_system_prompt(state['user_id'], time_info)
    
    response = llm_with_tools.invoke(
        [{"role": "system", "content": system_prompt}] + messages
    )
    
    messages.append(response)
    return State(messages=messages, user_id=state["user_id"], user_timezone=state.get("user_timezone", "+00:00"))


def process_tool_calls(state: State) -> State:
    """Process tool calls from the LLM"""
    messages = state["messages"]
    last_message = messages[-1]
    
    # If there are no tool calls, just return
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return state
    
    # Process each tool call
    tool_results = []
    tool_map = {tool.name: tool for tool in tools}
    
    # Get user timezone from state
    user_timezone = state.get("user_timezone", "+00:00")
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_input = tool_call["args"].copy()  # Make a copy to avoid modifying original
        
        # Add user_timezone to tool inputs for tools that need it
        if tool_name in ["create_event", "get_upcoming_events", "check_availability"]:
            tool_input["user_timezone"] = user_timezone
        
        if tool_name in tool_map:
            try:
                result = tool_map[tool_name].invoke(tool_input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": result
                })
            except Exception as e:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": f"Error: {str(e)}"
                })
    
    # Add tool results to messages as ToolMessage
    for result in tool_results:
        messages.append(ToolMessage(
            content=result["content"],
            tool_call_id=result["tool_use_id"]
        ))
    
    return State(messages=messages, user_id=state["user_id"], user_timezone=state.get("user_timezone", "+00:00"))


# Create the graph
workflow = StateGraph(State)
workflow.add_node("llm", call_llm)
workflow.add_node("tools", process_tool_calls)

workflow.set_entry_point("llm")
workflow.add_conditional_edges("llm", should_continue, {"continue": "tools", END: END})
workflow.add_edge("tools", "llm")

graph = workflow.compile()


def run_graph(user_id: str, message: str, user_timezone: str = None) -> str:
    """Run the calendar assistant graph with conversation history"""
    try:
        print(f"\n[GRAPH] run_graph called with user_id={user_id}, message={message}")
        # Load conversation history for this user
        history = get_conversation_history(user_id, limit=10)
        print(f"[GRAPH] Loaded {len(history)} messages from history")
        messages = []
        
        # Convert stored history to LangChain messages
        # Only load simple user/assistant messages (no tool calls/responses)
        for msg in history:
            content = msg.get("content", "")
            if not content or len(content.strip()) == 0:
                continue
                
            if msg["role"] == "user":
                messages.append(HumanMessage(content=content))
            elif msg["role"] == "assistant":
                # Only save final assistant responses (not tool calls)
                # Skip error messages that might indicate incomplete tool calls
                if not content.startswith("Error processing"):
                    messages.append(AIMessage(content=content))
        
        # Add the current user message
        messages.append(HumanMessage(content=message))
        
        # Save user message to history
        save_conversation_message(user_id, "user", message)
        
        # Use provided timezone or default to UTC
        if user_timezone is None:
            user_timezone = "+00:00"
        
        print(f"[GRAPH] Creating initial state with {len(messages)} messages, timezone: {user_timezone}")
        initial_state = State(
            messages=messages,
            user_id=user_id,
            user_timezone=user_timezone,
        )
        
        print(f"[GRAPH] Invoking graph...")
        result = graph.invoke(initial_state)
        print(f"[GRAPH] Graph invocation complete. Result messages: {len(result['messages'])}")
        
        # Debug: print all messages
        for i, msg in enumerate(result["messages"]):
            msg_type = type(msg).__name__
            has_tool_calls = hasattr(msg, "tool_calls") and msg.tool_calls is not None
            content_preview = str(msg.content)[:80] if hasattr(msg, "content") else "NO CONTENT"
            print(f"[GRAPH]   Message {i}: {msg_type} | tool_calls={has_tool_calls} | content={content_preview}...")
        
        # Extract the final response
        final_response = ""
        if result["messages"]:
            # Find the last non-tool message from the assistant
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage) and not hasattr(msg, "tool_calls"):
                    final_response = msg.content
                    print(f"[GRAPH] Found final response: {final_response[:100]}...")
                    break
            
            # Fallback to last message
            if not final_response:
                last_msg = result["messages"][-1]
                print(f"[GRAPH] Using fallback, last message type: {type(last_msg)}")
                print(f"[GRAPH] Last message content: {last_msg.content if hasattr(last_msg, 'content') else 'NO CONTENT ATTR'}")
                print(f"[GRAPH] Last message has tool_calls: {hasattr(last_msg, 'tool_calls')}")
                if isinstance(last_msg, AIMessage):
                    final_response = last_msg.content
                    print(f"[GRAPH] Extracted content from AIMessage: {final_response[:100] if final_response else 'EMPTY'}...")
                else:
                    final_response = str(last_msg)
                    print(f"[GRAPH] Converted to string: {final_response[:100]}...")
        
        # Save assistant response to history
        if final_response:
            save_conversation_message(user_id, "assistant", final_response)
        
        return final_response or "No response generated"
    except Exception as e:
        error = f"Error processing calendar request: {str(e)}"
        print(f"[GRAPH] Exception: {error}")
        import traceback
        traceback.print_exc()
        
        # If it's a tool call format error, clear conversation history to start fresh
        if "tool_call" in str(e).lower() or "tool_call_id" in str(e).lower():
            print(f"[GRAPH] Detected tool call format error, clearing conversation history")
            from app.db.firestore import clear_conversation_history
            clear_conversation_history(user_id)
            return "I encountered an error with the previous conversation. Please try your request again."
        
        return error

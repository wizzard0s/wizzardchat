"""Node Type Registry API – built-in + custom node types."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CustomNodeType, User
from app.schemas import (
    CustomNodeTypeCreate, CustomNodeTypeUpdate, NodeTypeOut,
)
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/node-types",
    tags=["node-types"],
    dependencies=[Depends(get_current_user)],
)

# ──────────── Built-in node types (read-only) ────────────

BUILTIN_NODE_TYPES: List[NodeTypeOut] = [
    # ── Flow Control ──
    NodeTypeOut(key="start", label="Start", icon="bi-play-circle", category="Flow Control",
                color="#198754", has_input=False, has_output=True,
                description="Entry point of the flow.",
                config_schema=[
                    {"key": "trigger", "label": "Trigger", "type": "select",
                     "options": ["inbound_call", "inbound_chat", "api", "scheduled", "manual"],
                     "default": "inbound_call", "description": "What starts this flow"},
                    {"key": "connector_id", "label": "Chat Connector", "type": "connector_select",
                     "description": "Link this flow to a chat connector (inbound_chat only). "
                                    "The connector's metadata field mappings will be pre-loaded as flow variables.",
                     "expression_enabled": False},
                ]),
    NodeTypeOut(key="end", label="End", icon="bi-stop-circle", category="Flow Control",
                color="#dc3545", has_input=True, has_output=False,
                description="Terminates the flow.",
                config_schema=[
                    {"key": "status", "label": "End Status", "type": "select",
                     "options": ["completed", "failed", "abandoned"], "default": "completed"},
                    {"key": "message", "label": "End Message", "type": "string",
                     "placeholder": "Optional completion message"},
                ]),
    NodeTypeOut(key="condition", label="Condition", icon="bi-signpost-split", category="Flow Control",
                color="#ffc107", has_input=True, has_output=True,
                description="Branch flow based on a condition. Has 'true' and 'false' output ports.",
                config_schema=[
                    {"key": "variable", "label": "Variable", "type": "string", "required": True,
                     "placeholder": "e.g. contact.age or flow.status"},
                    {"key": "operator", "label": "Operator", "type": "select",
                     "options": ["equals", "not_equals", "contains", "not_contains",
                                 "greater_than", "less_than", "starts_with", "ends_with",
                                 "regex", "is_empty", "is_not_empty"]},
                    {"key": "value", "label": "Value", "type": "string",
                     "placeholder": "Value to compare against"},
                ]),
    NodeTypeOut(key="goto", label="GoTo", icon="bi-arrow-return-right", category="Flow Control",
                color="#6c757d", has_input=True, has_output=False,
                description="Jump to another node in the flow.",
                config_schema=[
                    {"key": "target_node", "label": "Target Node", "type": "string",
                     "placeholder": "Node label or ID"},
                ]),
    NodeTypeOut(key="sub_flow", label="Sub-Flow", icon="bi-box-arrow-in-right", category="Flow Control",
                color="#087990", has_input=True, has_output=True,
                description="Execute another flow as a sub-routine.",
                config_schema=[
                    {"key": "flow_id", "label": "Sub-Flow", "type": "flow_select", "required": True,
                     "placeholder": "Select a flow"},
                    {"key": "input_mapping", "label": "Input Variables", "type": "json",
                     "placeholder": '{"var": "value"}', "description": "Variables to pass into the sub-flow"},
                    {"key": "output_variable", "label": "Output Variable", "type": "string",
                     "placeholder": "result", "description": "Variable to store sub-flow result"},
                ]),

    # ── Interaction ──
    NodeTypeOut(key="message", label="Message", icon="bi-chat-left-text", category="Interaction",
                color="#0d6efd", has_input=True, has_output=True,
                description="Send a message to the contact.",
                config_schema=[
                    {"key": "text", "label": "Message Text", "type": "textarea", "required": True,
                     "placeholder": "Enter message to send..."},
                    {"key": "delay_ms", "label": "Typing Delay (ms)", "type": "number",
                     "default": 0, "description": "Simulate typing delay before sending"},
                ]),
    NodeTypeOut(key="input", label="Input", icon="bi-input-cursor-text", category="Interaction",
                color="#6f42c1", has_input=True, has_output=True,
                description="Prompt the contact for input and store in a variable.",
                config_schema=[
                    {"key": "prompt", "label": "Prompt", "type": "string", "required": True,
                     "placeholder": "Ask the user..."},
                    {"key": "variable", "label": "Variable Name", "type": "string", "required": True,
                     "placeholder": "user_input"},
                    {"key": "validation", "label": "Validation", "type": "select",
                     "options": ["any", "number", "email", "phone", "date", "regex"], "default": "any"},
                    {"key": "validation_regex", "label": "Regex Pattern", "type": "string",
                     "placeholder": "^[0-9]+$", "description": "Used when validation is 'regex'"},
                    {"key": "error_message", "label": "Error Message", "type": "string",
                     "placeholder": "Invalid input, please try again"},
                    {"key": "max_retries", "label": "Max Retries", "type": "number", "default": 3},
                ]),
    NodeTypeOut(key="menu", label="Menu", icon="bi-list-ol", category="Interaction",
                color="#0dcaf0", has_input=True, has_output=True,
                description="Present numbered options to the contact.",
                config_schema=[
                    {"key": "prompt", "label": "Prompt", "type": "string", "required": True,
                     "placeholder": "Please choose:", "default": "Please choose:"},
                    {"key": "options", "label": "Menu Options", "type": "options_list",
                     "description": "Static key-label pairs. Click the \u26a1 toggle to build items dynamically with a JSONata expression that returns [{\"key\":\"1\",\"text\":\"Label\"}, ...]"},
                ]),
    NodeTypeOut(key="wait", label="Wait", icon="bi-hourglass", category="Interaction",
                color="#adb5bd", has_input=True, has_output=True,
                description="Pause the flow for a specified duration.",
                config_schema=[
                    {"key": "duration", "label": "Duration (seconds)", "type": "number",
                     "required": True, "default": 5},
                ]),

    # ── Telephony ──
    NodeTypeOut(key="play_audio", label="Play Audio", icon="bi-volume-up", category="Telephony",
                color="#6610f2", has_input=True, has_output=True,
                description="Play an audio file to the caller.",
                config_schema=[
                    {"key": "audio_url", "label": "Audio URL / File", "type": "string", "required": True,
                     "placeholder": "https://... or file path"},
                    {"key": "loop", "label": "Loop", "type": "boolean", "default": False},
                ]),
    NodeTypeOut(key="record", label="Record", icon="bi-mic", category="Telephony",
                color="#d63384", has_input=True, has_output=True,
                description="Record audio from the caller.",
                config_schema=[
                    {"key": "variable", "label": "Save to Variable", "type": "string",
                     "placeholder": "recording_url"},
                    {"key": "max_duration", "label": "Max Duration (sec)", "type": "number", "default": 60},
                    {"key": "beep", "label": "Play Beep", "type": "boolean", "default": True},
                    {"key": "silence_timeout", "label": "Silence Timeout (sec)", "type": "number", "default": 5},
                ]),
    NodeTypeOut(key="dtmf", label="DTMF", icon="bi-grid-3x3", category="Telephony",
                color="#495057", has_input=True, has_output=True,
                description="Collect touch-tone keypad input.",
                config_schema=[
                    {"key": "variable", "label": "Save to Variable", "type": "string",
                     "placeholder": "dtmf_input"},
                    {"key": "max_digits", "label": "Max Digits", "type": "number", "default": 1},
                    {"key": "timeout", "label": "Timeout (seconds)", "type": "number", "default": 10},
                    {"key": "finish_on_key", "label": "Finish on Key", "type": "string",
                     "default": "#", "placeholder": "# or *"},
                ]),

    # ── Routing ──
    NodeTypeOut(key="queue", label="Queue", icon="bi-people", category="Routing",
                color="#fd7e14", has_input=True, has_output=False,
                description="Place the contact into an agent queue.",
                config_schema=[
                    {"key": "queue_id", "label": "Queue", "type": "queue_select", "required": True,
                     "description": "Select the queue to route this contact to. "
                                    "The queue must belong to a campaign so agents can be dispatched automatically."},
                    {"key": "queue_message", "label": "Hold Message", "type": "string",
                     "default": "Connecting you with an agent, please wait…",
                     "placeholder": "Please wait while we connect you..."},
                    {"key": "priority", "label": "Priority", "type": "number", "default": 0},
                    {"key": "timeout", "label": "Timeout (seconds)", "type": "number",
                     "default": 300, "description": "Max wait time before overflow"},
                ]),
    NodeTypeOut(key="transfer", label="Transfer", icon="bi-telephone-forward", category="Routing",
                color="#e85d04", has_input=True, has_output=False,
                description="Transfer the conversation to another destination.",
                config_schema=[
                    {"key": "target", "label": "Transfer To", "type": "string", "required": True,
                     "placeholder": "Extension, queue, or number"},
                    {"key": "transfer_type", "label": "Transfer Type", "type": "select",
                     "options": ["blind", "warm"], "default": "blind"},
                ]),

    # ── Integration ──
    NodeTypeOut(key="http_request", label="HTTP Request", icon="bi-globe", category="Integration",
                color="#20c997", has_input=True, has_output=True,
                description="Make an HTTP API call.",
                config_schema=[
                    {"key": "url", "label": "URL", "type": "string", "required": True,
                     "placeholder": "https://api.example.com/endpoint"},
                    {"key": "method", "label": "Method", "type": "select",
                     "options": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
                    {"key": "headers", "label": "Headers", "type": "json",
                     "placeholder": '{"Content-Type": "application/json"}',
                     "description": "Request headers as JSON object"},
                    {"key": "body", "label": "Request Body", "type": "json",
                     "placeholder": '{"key": "value"}',
                     "description": "Request body (for POST/PUT/PATCH)"},
                    {"key": "response_var", "label": "Response Variable", "type": "string",
                     "placeholder": "api_response"},
                    {"key": "timeout_ms", "label": "Timeout (ms)", "type": "number", "default": 30000},
                ]),
    NodeTypeOut(key="webhook", label="Webhook", icon="bi-broadcast", category="Integration",
                color="#d63384", has_input=True, has_output=True,
                description="Send a webhook notification.",
                config_schema=[
                    {"key": "url", "label": "Webhook URL", "type": "string", "required": True,
                     "placeholder": "https://..."},
                    {"key": "method", "label": "Method", "type": "select",
                     "options": ["POST", "GET"], "default": "POST"},
                    {"key": "headers", "label": "Headers", "type": "json", "placeholder": '{}'},
                    {"key": "payload", "label": "Payload", "type": "json", "placeholder": '{}',
                     "description": "Data to send with the webhook"},
                ]),
    NodeTypeOut(key="set_variable", label="Set Variable", icon="bi-braces", category="Integration",
                color="#6c757d", has_input=True, has_output=True,
                description="Set one or more variables using literal values or JSONata expressions."),
    NodeTypeOut(key="ai_bot", label="AI Bot", icon="bi-robot", category="Integration",
                color="#7c3aed", has_input=True, has_output=True,
                description="Hand off to an AI conversational agent.",
                config_schema=[
                    {"key": "system_prompt", "label": "System Prompt", "type": "textarea", "required": True,
                     "placeholder": "You are a helpful assistant..."},
                    {"key": "model", "label": "Model", "type": "select",
                     "options": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo",
                                 "claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
                     "default": "gpt-4o"},
                    {"key": "max_turns", "label": "Max Turns", "type": "number", "default": 10,
                     "description": "Maximum conversation turns before exiting"},
                    {"key": "temperature", "label": "Temperature", "type": "number", "default": 0.7,
                     "description": "0 = deterministic, 1 = creative"},
                    {"key": "exit_keywords", "label": "Exit Keywords", "type": "string",
                     "placeholder": "done, exit, bye",
                     "description": "Comma-separated keywords that end the bot conversation"},
                    {"key": "output_variable", "label": "Output Variable", "type": "string",
                     "placeholder": "ai_result", "description": "Variable to store final AI response"},
                ]),
]

BUILTIN_KEYS = {t.key for t in BUILTIN_NODE_TYPES}


# ──────────── Endpoints ────────────

@router.get("", response_model=List[NodeTypeOut])
async def list_node_types(db: AsyncSession = Depends(get_db)):
    """Return all node types: built-in + custom."""
    result = await db.execute(select(CustomNodeType).order_by(CustomNodeType.category, CustomNodeType.label))
    custom = result.scalars().all()
    custom_out = [
        NodeTypeOut(
            key=c.key, label=c.label, icon=c.icon, category=c.category, color=c.color,
            has_input=c.has_input, has_output=c.has_output, is_builtin=False,
            config_schema=c.config_schema or [], description=c.description, id=c.id,
        )
        for c in custom
    ]
    return BUILTIN_NODE_TYPES + custom_out


@router.post("", response_model=NodeTypeOut, status_code=201)
async def create_custom_node_type(
    body: CustomNodeTypeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new custom node type."""
    if body.key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail=f"Key '{body.key}' conflicts with a built-in type")
    # Check unique
    exists = await db.execute(select(CustomNodeType).where(CustomNodeType.key == body.key))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Key '{body.key}' already exists")
    obj = CustomNodeType(
        key=body.key, label=body.label, icon=body.icon, category=body.category,
        color=body.color, has_input=body.has_input, has_output=body.has_output,
        config_schema=body.config_schema, description=body.description, created_by=user.id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await db.commit()
    return NodeTypeOut(
        key=obj.key, label=obj.label, icon=obj.icon, category=obj.category, color=obj.color,
        has_input=obj.has_input, has_output=obj.has_output, is_builtin=False,
        config_schema=obj.config_schema or [], description=obj.description, id=obj.id,
    )


@router.put("/{key}", response_model=NodeTypeOut)
async def update_custom_node_type(
    key: str,
    body: CustomNodeTypeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a custom node type (built-in types cannot be modified)."""
    if key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail="Cannot modify built-in node types")
    result = await db.execute(select(CustomNodeType).where(CustomNodeType.key == key))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Custom node type not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, val)
    await db.flush()
    await db.refresh(obj)
    await db.commit()
    return NodeTypeOut(
        key=obj.key, label=obj.label, icon=obj.icon, category=obj.category, color=obj.color,
        has_input=obj.has_input, has_output=obj.has_output, is_builtin=False,
        config_schema=obj.config_schema or [], description=obj.description, id=obj.id,
    )


@router.delete("/{key}", status_code=204)
async def delete_custom_node_type(key: str, db: AsyncSession = Depends(get_db)):
    """Delete a custom node type."""
    if key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail="Cannot delete built-in node types")
    result = await db.execute(select(CustomNodeType).where(CustomNodeType.key == key))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Custom node type not found")
    await db.delete(obj)
    await db.commit()

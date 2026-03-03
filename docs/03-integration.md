# Integration & Expansion Guide

This guide explains how to extend WizzardChat: adding new API routers, new flow node types, and integrating with external systems.

---

## Project Structure Quick Reference

```
wizzardchat/
├── main.py                    # App entry point — register new routers here
├── app/
│   ├── models.py              # SQLAlchemy ORM models — add new tables here
│   ├── schemas.py             # Pydantic request/response schemas
│   ├── database.py            # Engine + session factory (do not edit normally)
│   ├── auth.py                # JWT + password helpers
│   └── routers/
│       ├── chat_ws.py         # Flow execution engine — add new node handlers here
│       ├── node_types.py      # Node type registry — add built-in node definitions here
│       └── <your_module>.py   # ← Add new routers here
├── templates/                 # Jinja2 HTML templates
└── static/
    ├── css/
    └── js/                    # Frontend JS — flow-designer.js handles the canvas
```

---

## 1. Adding a New API Router (Module)

Each feature in WizzardChat is a self-contained FastAPI router. Follow this pattern to add a new one.

### Step 1 — Create the router file

Create `app/routers/my_feature.py`:

```python
"""My Feature — example module."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User          # add your own model as needed
from app.schemas import SomeSchema   # add your own schema as needed
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/my-feature",
    tags=["my-feature"],
    dependencies=[Depends(get_current_user)],   # all routes require auth
)

@router.get("", response_model=List[SomeSchema])
async def list_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MyModel).order_by(MyModel.created_at))
    return result.scalars().all()

@router.post("", response_model=SomeSchema, status_code=201)
async def create_item(body: SomeCreateSchema, db: AsyncSession = Depends(get_db)):
    obj = MyModel(**body.model_dump())
    db.add(obj)
    await db.flush()
    await db.commit()
    await db.refresh(obj)
    return obj
```

### Step 2 — Add the ORM model

In `app/models.py`, add your SQLAlchemy model:

```python
class MyModel(Base):
    __tablename__ = "my_features"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name       = Column(String(200), nullable=False)
    config     = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

WizzardChat calls `Base.metadata.create_all` on every startup, so the table is created automatically.

### Step 3 — Add Pydantic schemas

In `app/schemas.py`:

```python
class MyFeatureBase(BaseModel):
    name: str
    config: dict = {}

class MyFeatureCreate(MyFeatureBase):
    pass

class MyFeatureOut(MyFeatureBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

### Step 4 — Register the router

In `main.py`, import and register:

```python
from app.routers import my_feature as my_feature_router

# ... after the other app.include_router() calls:
app.include_router(my_feature_router.router)
```

### Step 5 — Add a UI page (optional)

Create `templates/my_feature.html` (copy an existing template as a base) and add a route in `main.py`:

```python
@app.get("/my-feature")
async def my_feature_page(request: Request):
    return templates.TemplateResponse("my_feature.html", {"request": request})
```

Add the page to the sidebar nav in any template that includes it.

---

## 2. Adding a New Flow Node Type

Flow node types are defined in `app/routers/node_types.py` as entries in `BUILTIN_NODE_TYPES`, and executed in `app/routers/chat_ws.py` inside the `run_flow` function.

### Step 1 — Define the node type

Add to `BUILTIN_NODE_TYPES` in `app/routers/node_types.py`:

```python
NodeTypeOut(
    key="send_sms",
    label="Send SMS",
    icon="bi-phone",           # Bootstrap icon class
    category="Integration",    # Groups nodes in the designer sidebar
    color="#20c997",
    has_input=True,
    has_output=True,
    description="Send an SMS message via Twilio.",
    config_schema=[
        {"key": "to",      "label": "To Number",  "type": "string",   "required": True,
         "placeholder": "+27821234567"},
        {"key": "message", "label": "Message",    "type": "textarea", "required": True,
         "placeholder": "Your OTP is {{otp}}"},
    ],
),
```

#### Config field types

| `type` value | UI control | Notes |
|-------------|------------|-------|
| `string` | Single-line text input | |
| `textarea` | Multi-line text input | Use for long text / message bodies |
| `number` | Numeric input | |
| `select` | Dropdown | Requires `options: [...]` array |
| `json` | JSON editor | Validates JSON structure |
| `queue_select` | Queue dropdown | Auto-populated from `/api/v1/queues` |
| `connector_select` | Connector dropdown | Auto-populated from `/api/v1/connectors` |
| `flow_select` | Flow dropdown | Auto-populated from `/api/v1/flows` |

### Step 2 — Implement the handler

In `app/routers/chat_ws.py`, inside `run_flow`, add a handler before the `else` catch-all:

```python
# ── Send SMS ──────────────────────────────────────────────────────────────
elif node.node_type == "send_sms":
    to      = _resolve_template(config.get("to", ""), ctx)
    message = _resolve_template(config.get("message", ""), ctx)
    try:
        await _send_sms(to, message)          # your integration function
        ctx["sms_sent"] = "true"
    except Exception as e:
        _log.warning("send_sms error: %s", e)
        ctx["sms_sent"] = "false"
    current_id = _next_node_id(edges, current_id)
```

#### Available helpers inside `run_flow`

| Helper | Description |
|--------|-------------|
| `_resolve_template(text, ctx)` | Replaces `{{variable}}` tokens with values from `ctx` |
| `_log_msg(session, from_, text, subtype, filename)` | Persists a message to the interaction log |
| `_next_node_id(edges, current_id, handle)` | Gets the next node ID following the given edge handle |
| `await send({...})` | Pushes a message to the visitor's SSE stream |
| `await manager.broadcast_to_agents({...})` | Broadcasts a message to all connected agent WebSockets |
| `await db.flush()` | Saves pending DB changes without comitting |

#### Node execution rules

- If your node is **instant** (no waiting for user input): advance `current_id` and `continue`
- If your node must **wait for a response**: set `session.waiting_node_id = current_id`, flush, and `return`
- The flow resumes via `handle_visitor_message()` which calls `run_flow` again

### Step 3 — Register the resume handler (only for waiting nodes)

If your node waits for input (like `input` or `menu`), add a resume case in the `resume from waiting node` section of `run_flow`:

```python
elif waiting_node.node_type == "send_sms":
    # This node type doesn't wait — it shouldn't be here
    pass
```

And in `handle_visitor_message` if you need to process the user's reply:

```python
elif session_waiting_node.node_type == "my_custom_waiting_node":
    ctx["my_variable"] = text
    await run_flow(session, connector, db)
```

---

## 3. Custom Node Types via API (Database-Driven)

You can register custom node types without touching source code — via the API. These are stored in the `custom_node_types` table.

```bash
curl -X POST http://localhost:8092/api/v1/node-types \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "crm_lookup",
    "label": "CRM Lookup",
    "icon": "bi-search",
    "category": "Integration",
    "color": "#fd7e14",
    "has_input": true,
    "has_output": true,
    "description": "Look up a contact record from the CRM.",
    "config_schema": [
      {"key": "search_field", "label": "Search Field", "type": "select",
       "options": ["email", "phone", "id"], "required": true}
    ]
  }'
```

> **Note:** Custom node types stored in the database define the UI appearance and form fields only. The execution logic must still be added to `chat_ws.py` — unless you are using a **Webhook** node to delegate execution to an external service.

---

## 4. Integrating with External APIs

### Using the Webhook Node (no code required)

The built-in **Webhook** node sends an HTTP request to any external URL:

- Configure the URL, method (GET/POST), headers, and payload
- Payload supports `{{variable}}` template syntax
- On success, sets `webhook_status_code` and `webhook_response` in `flow_context`
- The flow then continues to the next node

**Example webhook payload:**
```json
{
  "session_id": "{{session.id}}",
  "visitor_name": "{{contact.name}}",
  "intent": "{{flow.intent}}"
}
```

### Calling the WizzardChat API from External Systems

Use the REST API to programmatically trigger flows, create contacts, or manage sessions. See [04-api.md](04-api.md) for full reference.

**Example: Create a contact and start a session via API**

```python
import httpx

# 1. Get a token
resp = httpx.post("http://localhost:8092/api/v1/auth/login",
                  data={"username": "admin", "password": "M@M@5t3r"})
token = resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Create a contact
contact = httpx.post("http://localhost:8092/api/v1/contacts",
                     headers=headers,
                     json={"name": "Jane Doe", "email": "jane@example.com"}).json()
```

---

## 5. Adding a Database Column Migration

WizzardChat handles schema evolution through inline migrations in `main.py`. To add a column to an existing table:

In `main.py`, find the `migrations` list inside the `lifespan` function and add your migration:

```python
migrations = [
    # ... existing entries ...
    ("my_table.new_column",
     "ALTER TABLE my_table ADD COLUMN IF NOT EXISTS new_column VARCHAR(100)"),
]
```

The `IF NOT EXISTS` guard makes the migration safe to re-run on every startup.

---

## 6. Environment-Specific Configuration

All runtime configuration is driven by `.env`. To add a new config variable:

**Step 1** — Add to `app/config.py`:

```python
class Settings(BaseSettings):
    # ... existing ...
    my_api_key: str = ""             # Optional, empty default
    my_feature_enabled: bool = True  # Flag with sensible default
```

**Step 2** — Add to `.env.example`:

```env
MY_API_KEY=
MY_FEATURE_ENABLED=true
```

**Step 3** — Use in your code:

```python
from app.config import get_settings
settings = get_settings()

if settings.my_feature_enabled:
    api_key = settings.my_api_key
```

---

## 7. WebSocket & SSE Protocol Reference

The flow engine communicates with the visitor browser over a **WebSocket** (`/ws/chat/...`) with SSE fallback (`/sse/chat/...`).

### Messages the server sends to the visitor

| `type` | Fields | Description |
|--------|--------|-------------|
| `message` | `from`, `text`, `timestamp` | Standard text message from bot or agent |
| `menu` | `text`, `options[]`, `timestamp` | Multi-choice menu; `options` has `{key, text}` items |
| `queue` | `message`, `timestamp` | Waiting-for-agent notification |
| `end` | `status`, `message`, `timestamp` | Flow ended |
| `agent_joined` | `agent_name`, `timestamp` | Agent has taken the session |
| `error` | `message`, `timestamp` | Error condition |

### Messages the visitor sends to the server

| Format | Description |
|--------|-------------|
| `{"type": "message", "text": "Hello"}` | Plain text message |
| `{"type": "menu_choice", "key": "1"}` | Menu option selection |

### Agent WebSocket (`/ws/agent/{token}`)

Agents connect with their JWT token. Messages follow the same `type` convention but include a `session_key` field to target the right interaction.

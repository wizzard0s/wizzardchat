# API Reference

WizzardChat exposes a fully documented REST API v1 plus WebSocket and SSE endpoints.

- **Interactive docs (Swagger UI):** `http://localhost:8092/docs`
- **ReDoc:** `http://localhost:8092/redoc`
- **Base URL:** `http://localhost:8092`

---

## Authentication

WizzardChat uses **JWT Bearer tokens**. All `/api/v1/*` endpoints (except `/api/v1/auth/login`) require:

```
Authorization: Bearer <token>
```

### Obtain a token

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=M%40M%40S3cr3t
```

**Response:**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer"
}
```

The default admin credentials are set via `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars (seeded on first startup).

---

## Authentication (`/api/v1/auth`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Obtain a JWT access token (form-encoded) |
| `POST` | `/api/v1/auth/register` | Register a new user account |
| `GET` | `/api/v1/auth/me` | Get the currently authenticated user |

---

## Users (`/api/v1/users`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/users` | List all users |
| `GET` | `/api/v1/users/{user_id}` | Get a single user |
| `PATCH` | `/api/v1/users/{user_id}` | Update a user (name, email, password, role, status) |
| `DELETE` | `/api/v1/users/{user_id}` | Delete a user |
| `GET` | `/api/v1/users/{user_id}/campaigns` | List campaigns this user is assigned to |
| `PUT` | `/api/v1/users/{user_id}/campaigns` | Set the campaigns assigned to a user |

---

## Flows (`/api/v1/flows`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/flows` | List all flows |
| `POST` | `/api/v1/flows` | Create a new flow |
| `GET` | `/api/v1/flows/{flow_id}` | Get a flow including its nodes and edges |
| `PATCH` | `/api/v1/flows/{flow_id}` | Update flow metadata (name, description) |
| `DELETE` | `/api/v1/flows/{flow_id}` | Delete a flow |
| `PUT` | `/api/v1/flows/{flow_id}/designer` | Save the entire flow canvas (nodes + edges) in one call |
| `POST` | `/api/v1/flows/{flow_id}/publish` | Publish (activate) a flow |
| `POST` | `/api/v1/flows/{flow_id}/nodes` | Add a node to a flow |
| `PATCH` | `/api/v1/flows/{flow_id}/nodes/{node_id}` | Update a node (position, config) |
| `DELETE` | `/api/v1/flows/{flow_id}/nodes/{node_id}` | Remove a node |
| `POST` | `/api/v1/flows/{flow_id}/edges` | Add an edge between two nodes |
| `DELETE` | `/api/v1/flows/{flow_id}/edges/{edge_id}` | Remove an edge |
| `POST` | `/api/v1/flows/{flow_id}/simulate` | Simulate a flow execution (dry run) |

### Flow Designer Save payload

`PUT /api/v1/flows/{flow_id}/designer` accepts:

```json
{
  "nodes": [
    {
      "id": "node-1",
      "node_type": "message",
      "label": "Welcome",
      "position_x": 100,
      "position_y": 200,
      "config": { "text": "Hello {{name}}!" }
    }
  ],
  "edges": [
    {
      "id": "edge-1",
      "source_node_id": "node-1",
      "target_node_id": "node-2",
      "source_handle": "output"
    }
  ]
}
```

---

## Node Types (`/api/v1/node-types`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/node-types` | List all node types (built-in + custom) |
| `POST` | `/api/v1/node-types` | Create a custom node type |
| `PUT` | `/api/v1/node-types/{key}` | Update an existing custom node type |
| `DELETE` | `/api/v1/node-types/{key}` | Delete a custom node type (`built-in` nodes are protected) |

---

## Connectors (`/api/v1/connectors`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/connectors` | List all connectors |
| `POST` | `/api/v1/connectors` | Create a connector and assign a flow to it |
| `GET` | `/api/v1/connectors/{connector_id}` | Get a connector |
| `PUT` | `/api/v1/connectors/{connector_id}` | Update a connector |
| `POST` | `/api/v1/connectors/{connector_id}/regenerate-key` | Rotate the connector's API key |
| `DELETE` | `/api/v1/connectors/{connector_id}` | Delete a connector |
| `GET` | `/api/v1/connectors/{connector_id}/snippet` | Get the embeddable JS snippet for this connector |

---

## Queues (`/api/v1/queues`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/queues` | List all queues |
| `POST` | `/api/v1/queues` | Create a queue |
| `GET` | `/api/v1/queues/{queue_id}` | Get a queue |
| `PUT` | `/api/v1/queues/{queue_id}` | Update a queue |
| `DELETE` | `/api/v1/queues/{queue_id}` | Delete a queue |
| `POST` | `/api/v1/queues/{queue_id}/agents/{user_id}` | Assign an agent to a queue |
| `DELETE` | `/api/v1/queues/{queue_id}/agents/{user_id}` | Remove an agent from a queue |

---

## Contacts (`/api/v1/contacts`)

### Contacts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/contacts` | List contacts (supports pagination + search) |
| `POST` | `/api/v1/contacts` | Create a contact |
| `GET` | `/api/v1/contacts/{contact_id}` | Get a contact |
| `PUT` | `/api/v1/contacts/{contact_id}` | Update a contact |
| `DELETE` | `/api/v1/contacts/{contact_id}` | Delete a contact |
| `GET` | `/api/v1/contacts/count` | Count contacts (with optional filter) |
| `POST` | `/api/v1/contacts/bulk/delete` | Bulk delete contacts by ID list |
| `POST` | `/api/v1/contacts/bulk/add-to-list` | Bulk add contacts to a list |
| `POST` | `/api/v1/contacts/upload/preview` | Preview a CSV upload (parse headers, first rows) |
| `POST` | `/api/v1/contacts/upload/import` | Import contacts from CSV |

### Contact Lists

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/contacts/lists` | List all contact lists (paginated) |
| `GET` | `/api/v1/contacts/lists/all` | List all contact lists (no pagination) |
| `POST` | `/api/v1/contacts/lists` | Create a contact list |
| `GET` | `/api/v1/contacts/lists/{list_id}` | Get a contact list |
| `PUT` | `/api/v1/contacts/lists/{list_id}` | Update a contact list |
| `DELETE` | `/api/v1/contacts/lists/{list_id}` | Delete a contact list |
| `GET` | `/api/v1/contacts/lists/{list_id}/members` | List members of a contact list |
| `POST` | `/api/v1/contacts/lists/{list_id}/members/{contact_id}` | Add a contact to a list |
| `DELETE` | `/api/v1/contacts/lists/{list_id}/members/{contact_id}` | Remove a contact from a list |

---

## Campaigns (`/api/v1/campaigns`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/campaigns` | List campaigns |
| `POST` | `/api/v1/campaigns` | Create a campaign |
| `GET` | `/api/v1/campaigns/{campaign_id}` | Get a campaign |
| `PUT` | `/api/v1/campaigns/{campaign_id}` | Update a campaign |
| `POST` | `/api/v1/campaigns/{campaign_id}/start` | Start a campaign |
| `POST` | `/api/v1/campaigns/{campaign_id}/pause` | Pause a running campaign |
| `POST` | `/api/v1/campaigns/{campaign_id}/cancel` | Cancel a campaign |
| `DELETE` | `/api/v1/campaigns/{campaign_id}` | Delete a campaign |

---

## Teams (`/api/v1/teams`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/teams` | List all teams |
| `POST` | `/api/v1/teams` | Create a team |
| `GET` | `/api/v1/teams/{team_id}` | Get a team |
| `PUT` | `/api/v1/teams/{team_id}` | Update a team |
| `DELETE` | `/api/v1/teams/{team_id}` | Delete a team |
| `POST` | `/api/v1/teams/{team_id}/members/{user_id}` | Add a user to a team |
| `DELETE` | `/api/v1/teams/{team_id}/members/{user_id}` | Remove a user from a team |

---

## Roles & Permissions (`/api/v1/roles`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/roles` | List all roles |
| `GET` | `/api/v1/roles/permissions` | List all available permission strings |
| `POST` | `/api/v1/roles` | Create a role with specific permissions |
| `GET` | `/api/v1/roles/{role_id}` | Get a role |
| `PUT` | `/api/v1/roles/{role_id}` | Update a role |
| `DELETE` | `/api/v1/roles/{role_id}` | Delete a role |

---

## Office Hours (`/api/v1/office-hours`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/office-hours` | List all office hours groups |
| `POST` | `/api/v1/office-hours` | Create an office hours group |
| `GET` | `/api/v1/office-hours/{group_id}` | Get a group (includes weekly schedule) |
| `PUT` | `/api/v1/office-hours/{group_id}` | Update a group's name/timezone |
| `DELETE` | `/api/v1/office-hours/{group_id}` | Delete a group |
| `PUT` | `/api/v1/office-hours/{group_id}/schedule` | Replace the full weekly schedule |
| `GET` | `/api/v1/office-hours/{group_id}/exclusions` | List date exclusions (holidays) |
| `POST` | `/api/v1/office-hours/{group_id}/exclusions` | Add a date exclusion |
| `PUT` | `/api/v1/office-hours/{group_id}/exclusions/{excl_id}` | Update an exclusion |
| `DELETE` | `/api/v1/office-hours/{group_id}/exclusions/{excl_id}` | Delete an exclusion |

---

## Outcomes (`/api/v1/outcomes`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/outcomes` | List all outcomes |
| `POST` | `/api/v1/outcomes` | Create an outcome |
| `GET` | `/api/v1/outcomes/{outcome_id}` | Get an outcome |
| `PUT` | `/api/v1/outcomes/{outcome_id}` | Update an outcome |
| `DELETE` | `/api/v1/outcomes/{outcome_id}` | Delete an outcome |

---

## Tags (`/api/v1/tags`)

### Tag management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/tags` | List all tags |
| `POST` | `/api/v1/tags` | Create a tag |
| `GET` | `/api/v1/tags/{tag_id}` | Get a tag |
| `PUT` | `/api/v1/tags/{tag_id}` | Update a tag |
| `DELETE` | `/api/v1/tags/{tag_id}` | Delete a tag |

### Tag associations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/tags/interactions/{interaction_id}` | Get tags on an interaction |
| `POST` | `/api/v1/tags/interactions/{interaction_id}/{tag_id}` | Add tag to interaction |
| `DELETE` | `/api/v1/tags/interactions/{interaction_id}/{tag_id}` | Remove tag from interaction |
| `GET` | `/api/v1/tags/contacts/{contact_id}` | Get tags on a contact |
| `POST` | `/api/v1/tags/contacts/{contact_id}/{tag_id}` | Add tag to contact |
| `DELETE` | `/api/v1/tags/contacts/{contact_id}/{tag_id}` | Remove tag from contact |
| `GET` | `/api/v1/tags/users/{user_id}` | Get tags on a user |
| `POST` | `/api/v1/tags/users/{user_id}/{tag_id}` | Add tag to user |
| `DELETE` | `/api/v1/tags/users/{user_id}/{tag_id}` | Remove tag from user |

---

## Settings (`/api/v1/settings`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/settings/schema` | Get the settings schema (allowed keys + types) |
| `GET` | `/api/v1/settings` | List all current global settings |
| `GET` | `/api/v1/settings/{key}` | Get a single setting value |
| `PUT` | `/api/v1/settings/{key}` | Update a setting value |

---

## Sessions (`/api/v1/sessions`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/sessions/{session_id}/attach-contact` | Associate a contact record with an active session |

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Returns `{"status": "ok"}` — used by WebDash |

---

## Chat (Visitor-facing — no auth required)

These endpoints are called by the embedded chat widget in the visitor's browser. The `api_key` is the connector's public key (found in the embed snippet). The `session_id` is a UUID generated client-side.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat/{api_key}/{session_id}/init` | Start or resume a chat session — triggers the flow |
| `POST` | `/chat/{api_key}/{session_id}/send` | Send a visitor message into the flow |
| `POST` | `/chat/{api_key}/{session_id}/typing` | Send a typing indicator |
| `POST` | `/chat/{api_key}/{session_id}/close` | Close / end the session |
| `POST` | `/chat/{api_key}/{session_id}/upload` | Upload a file attachment |

### SSE stream

```http
GET /sse/chat/{api_key}/{session_id}
Accept: text/event-stream
```

Returns a persistent Server-Sent Events stream. Each event is a JSON object with a `type` field. The chat widget subscribes to this stream to receive bot replies, agent messages, menus, and end signals.

---

## WebSocket — Agent Console

```
WS ws://localhost:8092/ws/agent
```

Connect with the JWT token as a query parameter:
```
ws://localhost:8092/ws/agent?token=eyJhbGci...
```

After connecting, agents receive real-time session events and can send messages back:

```json
// Incoming (from server)
{"type": "visitor_message", "session_key": "abc-123", "text": "Hello", "timestamp": "..."}
{"type": "new_session", "session_key": "abc-123", "connector_name": "Website", "timestamp": "..."}

// Outgoing (from agent)
{"type": "agent_message", "session_key": "abc-123", "text": "Hi, how can I help?"}
{"type": "close_session", "session_key": "abc-123"}
{"type": "transfer", "session_key": "abc-123", "agent_id": "uuid-..."}
```

---

## Error Responses

All API errors follow the standard FastAPI JSON error format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request — invalid input |
| `401` | Unauthorized — missing or invalid token |
| `403` | Forbidden — insufficient permissions |
| `404` | Not found |
| `409` | Conflict — duplicate key or constraint violation |
| `422` | Unprocessable entity — Pydantic validation error |
| `500` | Internal server error — check `wizzardchat.log` |

---

## Code Examples

### Python — Fetch all flows

```python
import httpx

BASE = "http://localhost:8092"

# Authenticate
token = httpx.post(f"{BASE}/api/v1/auth/login",
                   data={"username": "admin", "password": "your-password"}).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# List flows
flows = httpx.get(f"{BASE}/api/v1/flows", headers=headers).json()
for f in flows:
    print(f["name"], "—", f["id"])
```

### JavaScript — Send a visitor message

```js
const sessionId = crypto.randomUUID();
const apiKey    = "your-connector-api-key";
const base      = "http://localhost:8092";

// Open SSE stream
const sse = new EventSource(`${base}/sse/chat/${apiKey}/${sessionId}`);
sse.onmessage = event => {
  const msg = JSON.parse(event.data);
  console.log("Bot:", msg);
};

// Start session
await fetch(`${base}/chat/${apiKey}/${sessionId}/init`, { method: "POST" });

// Send a message
await fetch(`${base}/chat/${apiKey}/${sessionId}/send`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ text: "Hello!" })
});
```

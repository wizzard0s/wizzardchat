# WizzardChat

An omnichannel customer engagement platform built with **FastAPI**, **async SQLAlchemy**, and **PostgreSQL**. Provides a real-time chat interface, visual flow designer, agent management, and multi-channel support — all served as a server-rendered Jinja2 web application.

---

## Features

- **Real-time Chat** — WebSocket-based visitor ↔ agent messaging with SSE-powered session feeds
- **Visual Flow Designer** — drag-and-drop node editor to build automated chat flows (messages, inputs, menus, conditions, queues, sub-flows, variables, DTMF, GoTo)
- **Sub-Flow Support** — reusable flow modules with a full call-stack engine (nested sub-flows supported)
- **Agent Panel** — live session management, message history, file/emoji support, queue visibility
- **Queue Management** — skill-based routing, auto-assignment, manual take, SLA tracking
- **Campaign Manager** — outbound messaging campaigns with contact list targeting
- **Contact Management** — full CRM with lists, tags, merge fields
- **Connectors** — embeddable chat widget with per-connector flow, allowed origins, and styling config
- **Office Hours** — per-connector schedule with timezone support (default `Africa/Johannesburg`)
- **Outcomes & Tags** — configurable disposition codes and tagging for interactions
- **Teams & Roles** — RBAC with custom roles, team membership, JWT-based auth
- **Crash-Safe Logging** — all uvicorn + app logs → `wizzardchat.log`, `sys.excepthook` for unhandled exceptions

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI |
| Server | Uvicorn |
| ORM | SQLAlchemy 2 (async) |
| Database | PostgreSQL (asyncpg driver) |
| Templates | Jinja2 |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Config | pydantic-settings + `.env` |
| Locale defaults | `en-ZA`, `+27`, `Africa/Johannesburg`, `ZAR` |

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (database `wizzardfrw` by default, auto-created tables on startup)

---

## Quick Start

```powershell
# 1. Clone
git clone https://github.com/wizzard0s/wizzardchat.git
cd wizzardchat

# 2. Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
Copy-Item .env.example .env
# Edit .env — set DATABASE_URL and SECRET_KEY at minimum

# 5. Run
python main.py
```

The app starts on **http://0.0.0.0:8092** by default (configurable via `APP_PORT`).

A default admin user is seeded on first startup:
- **Username:** `admin`
- **Password:** `admin`

> Change the admin password immediately after first login.

---

## Environment Variables

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/wizzardfrw` | Async DB URL (asyncpg) |
| `DATABASE_URL_SYNC` | `postgresql+psycopg2://...` | Sync DB URL (used for migrations) |
| `SECRET_KEY` | `wizzardchat-dev-secret-key-change-in-production` | JWT signing key — **change in production** |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | JWT expiry (8 hours) |
| `APP_NAME` | `WizzardChat` | Display name |
| `APP_PORT` | `8092` | Port to listen on |

---

## Project Structure

```
wizzardchat/
├── main.py                  # App entry point, lifespan, logging, startup migrations
├── requirements.txt
├── .env.example
├── app/
│   ├── config.py            # pydantic-settings config
│   ├── database.py          # Async SQLAlchemy engine + session factory
│   ├── models.py            # All ORM models (UUID PKs, JSONB columns)
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── auth.py              # JWT helpers, password hashing
│   └── routers/
│       ├── chat_ws.py       # WebSocket/SSE chat engine + flow runner
│       ├── flows.py         # Flow CRUD (nodes, edges)
│       ├── node_types.py    # Node type registry (fields, icons, categories)
│       ├── queues.py        # Queue management
│       ├── connectors.py    # Connector config + widget embed code
│       ├── contacts.py      # CRM contacts + lists
│       ├── campaigns.py     # Outbound campaigns
│       ├── teams.py         # Team management
│       ├── roles.py         # Custom RBAC roles
│       ├── office_hours.py  # Schedule management
│       ├── outcomes.py      # Disposition codes
│       ├── tags.py          # Tag management
│       ├── settings.py      # Global app settings
│       ├── auth.py          # Login/logout routes
│       └── users.py         # User CRUD
├── templates/               # Jinja2 HTML templates (server-rendered)
│   ├── index.html           # Dashboard / active sessions
│   ├── agent.html           # Agent chat panel
│   ├── flow_designer.html   # Visual flow editor
│   └── ...
└── static/
    ├── css/
    └── js/
        ├── agent.js         # Agent panel WebSocket client
        ├── flow-designer.js # Flow designer canvas + node editor
        └── ...
```

---

## Flow Designer — Node Types

| Node | Description |
|------|-------------|
| `start` | Entry point of every flow |
| `end` | Closes the interaction (with optional status + message) |
| `message` | Sends a bot message (supports `{{variable}}` templates) |
| `input` | Waits for free-text visitor input, stores to variable |
| `dtmf` | Single-key numeric input |
| `menu` | Multi-choice menu (buttons) |
| `condition` | Branches on expression (`true` / `false` edges) |
| `set_variable` | Sets a context variable |
| `queue` | Hands off to a human agent queue |
| `sub_flow` | Inline-executes another flow, returns on completion |
| `goto` | Jumps to a labelled node |

---

## API Highlights

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Obtain JWT token |
| `GET` | `/api/v1/flows` | List all flows |
| `POST` | `/api/v1/flows` | Create flow |
| `GET/PUT/DELETE` | `/api/v1/flows/{id}` | Manage individual flow |
| `GET` | `/api/v1/flows/{id}/nodes` | Get flow nodes + edges |
| `GET` | `/api/v1/queues` | List queues |
| `GET` | `/api/v1/connectors` | List connectors |
| `GET` | `/api/v1/contacts` | List contacts |
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/sse/chat/{connector_key}/{visitor_id}` | Visitor SSE stream |
| `WS` | `/ws/chat/{connector_key}/{visitor_id}` | Visitor WebSocket |
| `WS` | `/ws/agent/{token}` | Agent WebSocket |

---

## Logging

All application and uvicorn logs are written to `wizzardchat.log` in the project root. Unhandled exceptions are captured via `sys.excepthook` and written as `CRITICAL` entries.

```powershell
# Tail the log
Get-Content wizzardchat.log -Tail 50 -Wait
```

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push and open a Pull Request

---

## License

MIT

"""WizzardChat – Main FastAPI application."""

import os
import sys
import logging
import traceback
import uvicorn
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.config import get_settings
from app.database import engine, Base
from app.routers import auth, users, flows, queues, contacts, campaigns, teams, roles
from app.routers import settings as settings_router
from app.routers import node_types as node_types_router
from app.routers import connectors as connectors_router
from app.routers import chat_ws as chat_ws_router
from app.routers import outcomes as outcomes_router
from app.routers import tags as tags_router
from app.routers import office_hours as office_hours_router

# Ensure working directory is project root
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# ── Logging setup: always write to wizzardchat.log ──────────────────────────
LOG_FILE = BASE_DIR / "wizzardchat.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
_log = logging.getLogger("main")
_log.info("WizzardChat starting — log: %s", LOG_FILE)

def _crash_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _log.critical("UNHANDLED EXCEPTION:\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

sys.excepthook = _crash_handler
# ─────────────────────────────────────────────────────────────────────────────

# Ensure upload directory exists
(BASE_DIR / "static" / "uploads" / "chat").mkdir(parents=True, exist_ok=True)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text

    # ── STEP 1: Rename legacy tables BEFORE create_all so SQLAlchemy sees  ──
    # the new names when it checks what already exists in the DB.            ──
    async with engine.begin() as conn:
        renames = [
            (
                "rename chat_connectors -> connectors",
                "DO $$ BEGIN "
                "IF (to_regclass('public.chat_connectors') IS NOT NULL "
                "AND to_regclass('public.connectors') IS NULL) "
                "THEN ALTER TABLE chat_connectors RENAME TO connectors; "
                "END IF; END $$",
            ),
            (
                "rename chat_sessions -> interactions",
                "DO $$ BEGIN "
                "IF (to_regclass('public.chat_sessions') IS NOT NULL "
                "AND to_regclass('public.interactions') IS NULL) "
                "THEN ALTER TABLE chat_sessions RENAME TO interactions; "
                "END IF; END $$",
            ),
        ]
        for label, sql in renames:
            try:
                await conn.exec_driver_sql(sql)
                print(f"[WizzardChat] {label} OK")
            except Exception as e:
                print(f"[WizzardChat] {label} skip: {e}")

    # ── STEP 2: Create any missing tables (new installs or new models) ──────
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"[WizzardChat] Database tables ready")

    # Migrate node_type column from enum to varchar if needed
    async with engine.begin() as conn:
        try:
            r = await conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='flow_nodes' AND column_name='node_type'"
            ))
            row = r.fetchone()
            if row and row[0] == 'USER-DEFINED':
                await conn.execute(text(
                    "ALTER TABLE flow_nodes ALTER COLUMN node_type TYPE VARCHAR(50) USING node_type::text"
                ))
                await conn.execute(text("DROP TYPE IF EXISTS flownodetype CASCADE"))
                print("[WizzardChat] Migrated flow_nodes.node_type from enum to varchar")
        except Exception as e:
            print(f"[WizzardChat] node_type migration check: {e}")

    # ── STEP 3: Column-level migrations (all using new table names) ──────────
    async with engine.begin() as conn:
        migrations = [
            # queues
            ("queues.color",       "ALTER TABLE queues ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#fd7e14'"),
            ("queues.outcomes",    "ALTER TABLE queues ADD COLUMN IF NOT EXISTS outcomes JSONB DEFAULT '[]'"),
            ("queues.campaign_id", "ALTER TABLE queues ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL"),
            # campaigns
            ("campaigns.color",         "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#0d6efd'"),
            ("campaigns.is_active",     "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"),
            ("campaigns.campaign_time", "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS campaign_time JSONB DEFAULT '{\"start\":\"08:00\",\"end\":\"17:00\"}'"),
            ("campaigns.options",       "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS options JSONB DEFAULT '{\"allow_transfer\":true,\"allow_callback\":false}'"),
            ("campaigns.outcomes",      "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS outcomes JSONB DEFAULT '[]'"),
            ("campaigns.queues",        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS queues JSONB DEFAULT '[]'"),
            ("campaigns.agents",        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS agents JSONB DEFAULT '[]'"),
            # connectors (was chat_connectors)
            ("connectors.meta_fields",      "ALTER TABLE connectors ADD COLUMN IF NOT EXISTS meta_fields JSONB DEFAULT '[]'"),
            ("connectors.allowed_origins",  "ALTER TABLE connectors ADD COLUMN IF NOT EXISTS allowed_origins JSONB DEFAULT '[\"*\"]'"),
            ("connectors.style",            "ALTER TABLE connectors ADD COLUMN IF NOT EXISTS style JSONB DEFAULT '{}'"),
            # interactions (was chat_sessions)
            ("interactions.waiting_node_id",  "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS waiting_node_id VARCHAR(128)"),
            ("interactions.flow_context",     "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS flow_context JSONB DEFAULT '{}'"),
            ("interactions.visitor_metadata", "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS visitor_metadata JSONB DEFAULT '{}'"),
            ("interactions.queue_id",         "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS queue_id UUID REFERENCES queues(id) ON DELETE SET NULL"),
            ("interactions.agent_id",         "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES users(id) ON DELETE SET NULL"),
            ("interactions.last_activity_at", "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP"),
            ("interactions.message_log",      "ALTER TABLE interactions ADD COLUMN IF NOT EXISTS message_log JSONB DEFAULT '[]'"),
            # team_members: one team per user
            ("team_members.uq_user", "CREATE UNIQUE INDEX IF NOT EXISTS uq_team_members_user ON team_members(user_id)"),
            # custom_roles table
            ("custom_roles.table", "CREATE TABLE IF NOT EXISTS custom_roles (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(100) UNIQUE NOT NULL, description TEXT, is_system BOOLEAN NOT NULL DEFAULT FALSE, permissions JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())"),
            # contacts – extended fields
            ("contacts.title",         "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS title VARCHAR(50)"),
            ("contacts.job_title",     "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS job_title VARCHAR(150)"),
            ("contacts.address_line1", "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255)"),
            ("contacts.city",          "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS city VARCHAR(100)"),
            ("contacts.state",         "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS state VARCHAR(100)"),
            ("contacts.postal_code",   "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20)"),
            ("contacts.country",       "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS country VARCHAR(100)"),
            ("contacts.date_of_birth", "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS date_of_birth VARCHAR(20)"),
            ("contacts.gender",        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS gender VARCHAR(20)"),
            ("contacts.language",      "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS language VARCHAR(20) DEFAULT 'en'"),
            ("contacts.source",        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS source VARCHAR(100)"),
            ("contacts.notes",         "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS notes TEXT"),
            # contact_lists – color
            ("contact_lists.color",    "ALTER TABLE contact_lists ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#0d6efd'"),
        ]
        for label, sql in migrations:
            try:
                await conn.exec_driver_sql(sql)
                print(f"[WizzardChat] Migration OK: {label}")
            except Exception as e:
                print(f"[WizzardChat] Migration skip ({label}): {e}")

    # Seed default system admin if not exists
    from sqlalchemy import select
    from app.database import async_session
    from app.models import User, UserRole
    from app.auth import hash_password
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username == "admin", User.is_system_account == True)
        )
        existing = result.scalar_one_or_none()
        if not existing:
            admin = User(
                email="admin@wizzardchat.local",
                username="admin",
                hashed_password=hash_password("M@M@5t3r"),
                full_name="System Admin",
                role=UserRole.SUPER_ADMIN,
                is_system_account=True,
            )
            session.add(admin)
            await session.commit()
            print("[WizzardChat] System admin seeded")
        else:
            # Ensure password stays in sync on every boot
            existing.hashed_password = hash_password("M@M@5t3r")
            await session.commit()

    # Seed system roles
    from app.routers.roles import seed_system_roles
    async with async_session() as session:
        await seed_system_roles(session)

    # Seed default global settings if not present
    from app.routers.settings import seed_settings
    async with async_session() as session:
        await seed_settings(session)
        print("[WizzardChat] Global settings ready")

    yield

    await engine.dispose()


app = FastAPI(
    title="WizzardChat",
    description="Omnichannel Communication Platform – Voice, Chat, WhatsApp, App",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(flows.router)
app.include_router(queues.router)
app.include_router(contacts.router)
app.include_router(campaigns.router)
app.include_router(teams.router)
app.include_router(roles.router)
app.include_router(settings_router.router)
app.include_router(node_types_router.router)
app.include_router(connectors_router.router)
app.include_router(chat_ws_router.router)
app.include_router(outcomes_router.router)
app.include_router(tags_router.router)
app.include_router(office_hours_router.router)

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/flow-designer")
@app.get("/flow-designer/{flow_id}")
async def flow_designer_page(request: Request, flow_id: str = None):
    return templates.TemplateResponse("flow_designer.html", {"request": request, "flow_id": flow_id})


@app.get("/connectors")
async def connectors_page(request: Request):
    return templates.TemplateResponse("connectors.html", {"request": request})


@app.get("/queues")
async def queues_page(request: Request):
    return templates.TemplateResponse("queues.html", {"request": request})


@app.get("/campaigns")
async def campaigns_page(request: Request):
    return templates.TemplateResponse("campaigns.html", {"request": request})


@app.get("/contacts")
async def contacts_page(request: Request):
    return templates.TemplateResponse("contacts.html", {"request": request})


@app.get("/teams")
async def teams_page(request: Request):
    return templates.TemplateResponse("teams.html", {"request": request})


@app.get("/roles")
async def roles_page(request: Request):
    return templates.TemplateResponse("roles.html", {"request": request})


@app.get("/users")
async def users_page(request: Request):
    return templates.TemplateResponse("users.html", {"request": request})


@app.get("/outcomes")
async def outcomes_page(request: Request):
    return templates.TemplateResponse("outcomes.html", {"request": request})


@app.get("/tags")
async def tags_page(request: Request):
    return templates.TemplateResponse("tags.html", {"request": request})


@app.get("/office-hours")
async def office_hours_page(request: Request):
    return templates.TemplateResponse("office_hours.html", {"request": request})


@app.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/agent")
async def agent_page(request: Request):
    return templates.TemplateResponse("agent.html", {"request": request})


@app.get("/chat-preview")
async def chat_preview_page(request: Request, key: str = ""):
    """Simple test page that embeds the chat widget for a given API key."""
    base = str(request.base_url).rstrip("/")
    html = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Chat Widget Preview</title></head><body style='font-family:sans-serif;padding:40px'>"
        f"<h2>Chat Widget Preview</h2><p>API Key: <code>{key}</code></p>"
        "<p>The chat widget should appear in the bottom-right corner.</p>"
        f"<script>window.WizzardChat={{apiKey:'{key}',serverUrl:'{base}'}};</script>"
        f"<script src='{base}/static/js/chat-widget.js?v=4'></script>"
        "</body></html>"
    )
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "app": "WizzardChat", "version": "v1"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=False,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s"},
            },
            "handlers": {
                "file": {
                    "class": "logging.FileHandler",
                    "filename": str(LOG_FILE),
                    "encoding": "utf-8",
                    "formatter": "default",
                },
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                },
            },
            "root": {"handlers": ["file", "console"], "level": "INFO"},
            "loggers": {
                "uvicorn": {"handlers": ["file", "console"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["file", "console"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["file", "console"], "level": "INFO", "propagate": False},
            },
        },
    )

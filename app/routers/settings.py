"""Global settings endpoints – admin-only."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import GlobalSettings, User, UserRole
from app.schemas import GlobalSettingOut, GlobalSettingUpdate
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)

# ── Full settings schema: category → list of field definitions ──────────────
# Each field: key, label, description, type (text|select|color|number|toggle|password),
#             default, options (for select), min/max (for number), placeholder
SETTINGS_SCHEMA = [
    {
        "category": "Regional",
        "icon": "bi-globe2",
        "color": "primary",
        "fields": [
            {
                "key": "locale",
                "label": "System Locale",
                "description": "Phone-number region code used for formatting and validation.",
                "type": "select",
                "default": "en-ZA",
                "options": ["en-ZA", "en-US", "en-GB", "en-AU", "fr-FR", "de-DE", "pt-BR"],
            },
            {
                "key": "timezone",
                "label": "Timezone",
                "description": "Default timezone for timestamps and scheduling.",
                "type": "select",
                "default": "Africa/Johannesburg",
                "options": [
                    "Africa/Johannesburg", "Africa/Lagos", "Africa/Nairobi",
                    "America/New_York", "America/Chicago", "America/Los_Angeles",
                    "America/Sao_Paulo", "Europe/London", "Europe/Berlin",
                    "Europe/Paris", "Asia/Dubai", "Asia/Singapore",
                    "Asia/Tokyo", "Australia/Sydney", "UTC",
                ],
            },
            {
                "key": "date_format",
                "label": "Date Format",
                "description": "How dates are displayed across the platform.",
                "type": "select",
                "default": "YYYY-MM-DD",
                "options": ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "DD-MMM-YYYY"],
            },
            {
                "key": "phone_country_code",
                "label": "Default Country Code",
                "description": "International dialling prefix applied when no code is given.",
                "type": "text",
                "default": "+27",
                "placeholder": "+27",
            },
            {
                "key": "phone_format",
                "label": "Phone Display Format",
                "description": "How phone numbers are rendered in the UI.",
                "type": "select",
                "default": "international",
                "options": ["international", "national", "e164"],
            },
            {
                "key": "currency",
                "label": "Currency",
                "description": "Default currency used for billing and reports.",
                "type": "select",
                "default": "ZAR",
                "options": ["ZAR", "USD", "EUR", "GBP", "AUD", "CAD", "NGN", "KES"],
            },
        ],
    },
    {
        "category": "Branding",
        "icon": "bi-palette",
        "color": "warning",
        "fields": [
            {
                "key": "app_name",
                "label": "Application Name",
                "description": "Displayed in the browser tab, sidebar, and notifications.",
                "type": "text",
                "default": "WizzardChat",
                "placeholder": "WizzardChat",
            },
            {
                "key": "app_tagline",
                "label": "Tagline",
                "description": "Short description shown on the login page.",
                "type": "text",
                "default": "Omnichannel Communication Platform",
                "placeholder": "Your tagline here",
            },
            {
                "key": "primary_color",
                "label": "Primary Colour",
                "description": "Main accent colour used for buttons and highlights.",
                "type": "color",
                "default": "#0d6efd",
            },
            {
                "key": "logo_url",
                "label": "Logo URL",
                "description": "URL to your company logo (PNG/SVG, transparent background recommended).",
                "type": "text",
                "default": "",
                "placeholder": "https://example.com/logo.png",
            },
            {
                "key": "support_email",
                "label": "Support Email",
                "description": "Contact address shown to users in help text.",
                "type": "text",
                "default": "",
                "placeholder": "support@example.com",
            },
        ],
    },
    {
        "category": "Agent Panel",
        "icon": "bi-headset",
        "color": "success",
        "fields": [
            {
                "key": "agent_max_conversations",
                "label": "Max Concurrent Conversations",
                "description": "Maximum number of simultaneous chats an agent can handle.",
                "type": "number",
                "default": "5",
                "min": 1,
                "max": 50,
            },
            {
                "key": "session_timeout_minutes",
                "label": "Idle Session Timeout (min)",
                "description": "Minutes of inactivity before a chat session is auto-closed.",
                "type": "number",
                "default": "30",
                "min": 1,
                "max": 1440,
            },
            {
                "key": "typing_indicator",
                "label": "Typing Indicator",
                "description": "Show the typing … bubble to visitors while an agent is composing.",
                "type": "toggle",
                "default": "true",
            },
            {
                "key": "auto_assign",
                "label": "Auto-Assign Conversations",
                "description": "Automatically assign new conversations to available agents in the queue.",
                "type": "toggle",
                "default": "true",
            },
            {
                "key": "agent_status_on_login",
                "label": "Default Status on Login",
                "description": "Status set for agents when they first log in.",
                "type": "select",
                "default": "online",
                "options": ["online", "away", "busy", "offline"],
            },
        ],
    },
    {
        "category": "Queues",
        "icon": "bi-people",
        "color": "info",
        "fields": [
            {
                "key": "queue_max_wait_minutes",
                "label": "Max Queue Wait (min)",
                "description": "How long a visitor waits before being offered a callback or escalation.",
                "type": "number",
                "default": "15",
                "min": 1,
                "max": 120,
            },
            {
                "key": "queue_overflow_action",
                "label": "Queue Overflow Action",
                "description": "What happens when all agents are busy and the queue is full.",
                "type": "select",
                "default": "message",
                "options": ["message", "voicemail", "callback", "abandon"],
            },
            {
                "key": "business_hours_enabled",
                "label": "Enforce Business Hours",
                "description": "Only route conversations during configured working hours.",
                "type": "toggle",
                "default": "false",
            },
            {
                "key": "business_hours_start",
                "label": "Business Hours Start",
                "description": "Opening time (24h format, e.g. 08:00).",
                "type": "text",
                "default": "08:00",
                "placeholder": "08:00",
            },
            {
                "key": "business_hours_end",
                "label": "Business Hours End",
                "description": "Closing time (24h format, e.g. 17:00).",
                "type": "text",
                "default": "17:00",
                "placeholder": "17:00",
            },
        ],
    },
    {
        "category": "Security",
        "icon": "bi-shield-lock",
        "color": "danger",
        "fields": [
            {
                "key": "session_lifetime_minutes",
                "label": "Session Lifetime (min)",
                "description": "How long a login token remains valid before forced logout.",
                "type": "number",
                "default": "480",
                "min": 15,
                "max": 10080,
            },
            {
                "key": "password_min_length",
                "label": "Minimum Password Length",
                "description": "Passwords shorter than this are rejected at registration.",
                "type": "number",
                "default": "8",
                "min": 6,
                "max": 64,
            },
            {
                "key": "allow_registration",
                "label": "Allow Self-Registration",
                "description": "Let users create accounts without an admin invite.",
                "type": "toggle",
                "default": "false",
            },
            {
                "key": "require_2fa",
                "label": "Require Two-Factor Auth",
                "description": "Force all users to enrol in 2FA (future feature).",
                "type": "toggle",
                "default": "false",
            },
            {
                "key": "audit_log_enabled",
                "label": "Audit Logging",
                "description": "Record all admin actions to the audit log table.",
                "type": "toggle",
                "default": "true",
            },
        ],
    },
    {
        "category": "Notifications",
        "icon": "bi-bell",
        "color": "secondary",
        "fields": [
            {
                "key": "email_notifications",
                "label": "Email Notifications",
                "description": "Send system event emails (new contact, queue overflow, etc.).",
                "type": "toggle",
                "default": "false",
            },
            {
                "key": "smtp_host",
                "label": "SMTP Host",
                "description": "Outgoing mail server hostname.",
                "type": "text",
                "default": "",
                "placeholder": "smtp.example.com",
            },
            {
                "key": "smtp_port",
                "label": "SMTP Port",
                "description": "SMTP server port (25, 465, 587).",
                "type": "number",
                "default": "587",
                "min": 1,
                "max": 65535,
            },
            {
                "key": "smtp_from_address",
                "label": "From Address",
                "description": "The email address sent in the From header.",
                "type": "text",
                "default": "",
                "placeholder": "noreply@example.com",
            },
            {
                "key": "desktop_notifications",
                "label": "Browser Desktop Notifications",
                "description": "Request browser permission for desktop push when agents receive messages.",
                "type": "toggle",
                "default": "true",
            },
        ],
    },
]

# Flat lookup: key → field metadata
_SCHEMA_MAP = {f["key"]: f for cat in SETTINGS_SCHEMA for f in cat["fields"]}
# All valid keys
ALLOWED_KEYS = set(_SCHEMA_MAP.keys())

# All default values for seeding
SETTINGS_DEFAULTS = {f["key"]: f["default"] for cat in SETTINGS_SCHEMA for f in cat["fields"]}


async def seed_settings(db: AsyncSession) -> None:
    """Idempotent: insert any missing settings with their default values."""
    for key, value in SETTINGS_DEFAULTS.items():
        exists = await db.execute(select(GlobalSettings).where(GlobalSettings.key == key))
        if not exists.scalar_one_or_none():
            desc = _SCHEMA_MAP[key]["description"]
            db.add(GlobalSettings(key=key, value=value, description=desc))
    await db.commit()


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Only admin / super_admin may manage global settings."""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


@router.get("/schema")
async def get_schema():
    """Return the full settings schema (categories + field metadata) for the UI."""
    return {"schema": SETTINGS_SCHEMA}


@router.get("", response_model=List[GlobalSettingOut])
async def list_settings(db: AsyncSession = Depends(get_db)):
    """Return all global settings (readable by any authenticated user)."""
    result = await db.execute(select(GlobalSettings).order_by(GlobalSettings.key))
    return [GlobalSettingOut.model_validate(s) for s in result.scalars().all()]


@router.get("/{key}", response_model=GlobalSettingOut)
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GlobalSettings).where(GlobalSettings.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return GlobalSettingOut.model_validate(setting)


@router.put("/{key}", response_model=GlobalSettingOut)
async def update_setting(
    key: str,
    body: GlobalSettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    """Create or update a global setting. Admin only."""
    if key not in ALLOWED_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown setting key '{key}'. Valid keys: {', '.join(sorted(ALLOWED_KEYS))}",
        )
    meta = _SCHEMA_MAP[key]
    result = await db.execute(select(GlobalSettings).where(GlobalSettings.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = body.value
        setting.updated_by = current_user.id
    else:
        setting = GlobalSettings(
            key=key,
            value=body.value,
            description=meta["description"],
            updated_by=current_user.id,
        )
        db.add(setting)
    await db.flush()
    await db.refresh(setting)
    return GlobalSettingOut.model_validate(setting)

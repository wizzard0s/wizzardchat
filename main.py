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
from app.routers import agent_groups as agent_groups_router
from app.routers import dialler as dialler_router
from app.routers import settings as settings_router
from app.routers import node_types as node_types_router
from app.routers import connectors as connectors_router
from app.routers import chat_ws as chat_ws_router
from app.routers import outcomes as outcomes_router
from app.routers import tags as tags_router
from app.routers import office_hours as office_hours_router
from app.routers import dashboard as dashboard_router
from app.routers import wallboard as wallboard_router
from app.routers import ai as ai_router
from app.routers import copilot as copilot_router
from app.routers import csat as csat_router
from app.routers import interactions as interactions_router
from app.routers import inbound_router as inbound_router_module
from app.routers import email_connector as email_connector_router
from app.routers import whatsapp_connector as whatsapp_connector_router
from app.routers import voice_connector as voice_connector_router
from app.routers import sms_connector as sms_connector_router
from app.routers import voice_twiml as voice_twiml_router
from app.routers import audit as audit_router
from app.routers import agents as agents_router
from app.routers import message_templates as message_templates_router

# Project root — used for absolute paths; avoids mutating process cwd
BASE_DIR = Path(__file__).resolve().parent

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

# Warn early if running with insecure dev defaults
settings = get_settings()
settings.warn_insecure_defaults()

def _crash_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _log.critical("UNHANDLED EXCEPTION:\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

sys.excepthook = _crash_handler
# ─────────────────────────────────────────────────────────────────────────────

# Ensure upload directory exists
(BASE_DIR / "static" / "uploads" / "chat").mkdir(parents=True, exist_ok=True)


async def _seed_survey_template(
    name: str,
    description: str,
    nodes_spec: list,
    edges_spec: list,  # each item: (src, tgt) or (src, tgt, handle)
    label: str,
) -> None:
    """Seed a survey sub-flow — always refreshes nodes/edges so template fixes apply immediately."""
    from sqlalchemy import select, delete
    from app.database import async_session
    from app.models import Flow, FlowNode, FlowEdge, FlowType, FlowStatus

    async with async_session() as db:
        existing = (await db.execute(select(Flow).where(Flow.name == name))).scalar_one_or_none()
        if existing:
            # Refresh: drop existing nodes/edges then recreate (preserves Flow UUID so
            # any call_flow references remain valid)
            await db.execute(delete(FlowEdge).where(FlowEdge.flow_id == existing.id))
            await db.execute(delete(FlowNode).where(FlowNode.flow_id == existing.id))
            fid = existing.id
        else:
            flow = Flow(
                name=name,
                description=description,
                flow_type=FlowType.SUB_FLOW,
                status=FlowStatus.ACTIVE,
                is_active=True,
                is_published=True,
                published_version="1.0",
                version="1.0",
            )
            db.add(flow)
            await db.flush()
            fid = flow.id

        for spec in nodes_spec:
            db.add(FlowNode(flow_id=fid, **spec))
        for edge in edges_spec:
            src, tgt = edge[0], edge[1]
            handle = edge[2] if len(edge) > 2 else "default"
            db.add(FlowEdge(flow_id=fid, source_node_id=src, target_node_id=tgt, source_handle=handle))

        await db.commit()
        print(f"[WizzardChat] {label} seeded/refreshed")


async def _seed_csat_template() -> None:
    """Create the built-in CSAT survey sub-flow.

    Collected variables (auto-saved to the interaction by the flow engine):
      csat_score   int 1-5
      csat_comment str (optional; visitor types 'skip' to skip)
    """
    from uuid import uuid4
    n_start          = str(uuid4())
    n_msg            = str(uuid4())
    n_score          = str(uuid4())
    n_comment        = str(uuid4())
    n_save_survey    = str(uuid4())
    n_thanks         = str(uuid4())
    n_end            = str(uuid4())
    n_score_bail_msg = str(uuid4())
    n_score_bail_end = str(uuid4())

    await _seed_survey_template(
        name="__template__csat_survey",
        description=(
            "Built-in CSAT survey sub-flow. "
            "Attach to a positive Outcome (action_type=flow_redirect). "
            "Sets csat_score (1-5) and csat_comment in flow context — "
            "the flow engine saves them to the interaction automatically."
        ),
        nodes_spec=[
            dict(id=n_start,          node_type="start",   label="Start",              position_x= 100, position_y=300, position=0, config={}),
            dict(id=n_msg,            node_type="message",  label="Ask rating",         position_x= 320, position_y=300, position=1, config={
                "message": (
                    "Thank you for chatting with us! 😊\n\n"
                    "How would you rate your experience today?\n\n"
                    "Reply with a number:\n"
                    "  1 = Poor\n  2 = Fair\n  3 = Good\n  4 = Very good\n  5 = Excellent"
                ),
            }),
            dict(id=n_score,          node_type="input",    label="Capture score",      position_x= 560, position_y=300, position=2, config={
                "variable": "csat_score",
                "prompt": "",
                "validation": "^[1-5]$",
                "error_message": "Please reply with a number between 1 and 5.",
                "max_retries": 3,
            }),
            dict(id=n_comment,        node_type="input",       label="Capture comment",    position_x= 800, position_y=300, position=3, config={
                "variable": "csat_comment",
                "prompt": "Any other comments? (type 'skip' to skip)",
            }),
            dict(id=n_save_survey,    node_type="save_survey",  label="Save CSAT",           position_x=1040, position_y=300, position=4, config={
                "survey_name": "csat",
                "fields": {"score": "csat_score", "comment": "csat_comment"},
            }),
            dict(id=n_thanks,         node_type="message",      label="Thank you",           position_x=1280, position_y=300, position=5, config={
                "message": "Thank you for your feedback — it helps us serve you better. 🙏",
            }),
            dict(id=n_end,            node_type="end",          label="End",                 position_x=1520, position_y=300, position=6, config={}),
            # Timeout path — reached when visitor fails to provide a valid 1-5 rating
            dict(id=n_score_bail_msg, node_type="message",      label="Skip rating",         position_x= 560, position_y=560, position=7, config={
                "message": "No problem — we'll skip the rating for now. Thank you for chatting with us! 😊",
            }),
            dict(id=n_score_bail_end, node_type="end",          label="End (no score)",      position_x= 800, position_y=560, position=8, config={}),
        ],
        edges_spec=[
            (n_start, n_msg),
            (n_msg, n_score),
            (n_score, n_comment),                            # default: valid score captured
            (n_score, n_score_bail_msg, "timeout"),         # timeout: max retries exhausted
            (n_comment, n_save_survey),                      # default: comment captured → save
            (n_comment, n_save_survey, "timeout"),          # timeout: no comment → still save score
            (n_save_survey, n_thanks),
            (n_thanks, n_end),
            (n_score_bail_msg, n_score_bail_end),
        ],
        label="CSAT sub-flow template",
    )


async def _seed_nps_template() -> None:
    """Create the built-in NPS sub-flow.

    Collected variables (auto-saved to the interaction by the flow engine):
      nps_score   int 0-10
      nps_reason  str (optional; visitor types 'skip' to skip)

    NPS buckets:
      0-6  = Detractors
      7-8  = Passives
      9-10 = Promoters
    NPS = % Promoters - % Detractors
    """
    from uuid import uuid4
    n_start          = str(uuid4())
    n_msg            = str(uuid4())
    n_score          = str(uuid4())
    n_reason         = str(uuid4())
    n_save_survey    = str(uuid4())
    n_thanks         = str(uuid4())
    n_end            = str(uuid4())
    n_score_bail_msg = str(uuid4())
    n_score_bail_end = str(uuid4())

    await _seed_survey_template(
        name="__template__nps_survey",
        description=(
            "Built-in NPS sub-flow. "
            "Attach to an Outcome to trigger after an interaction. "
            "Sets nps_score (0-10) and nps_reason in flow context — "
            "the flow engine saves them to the interaction automatically. "
            "Input nodes use max_retries=3; the timeout handle leads to a graceful skip path."
        ),
        nodes_spec=[
            dict(id=n_start,          node_type="start",   label="Start",              position_x= 100, position_y=300, position=0, config={}),
            dict(id=n_msg,            node_type="message",  label="Ask NPS",            position_x= 320, position_y=300, position=1, config={
                "message": (
                    "One last question — on a scale of 0 to 10, how likely are you to "
                    "recommend us to a friend or colleague?\n\n"
                    "0 = Not at all likely     10 = Extremely likely"
                ),
            }),
            dict(id=n_score,          node_type="input",    label="Capture score",      position_x= 560, position_y=300, position=2, config={
                "variable": "nps_score",
                "prompt": "",
                "validation": r"^(10|[0-9])$",
                "error_message": "Please reply with a number between 0 and 10.",
                "max_retries": 3,
            }),
            dict(id=n_reason,         node_type="input",       label="Capture reason",     position_x= 800, position_y=300, position=3, config={
                "variable": "nps_reason",
                "prompt": "What's the main reason for your score? (type 'skip' to skip)",
            }),
            dict(id=n_save_survey,    node_type="save_survey",  label="Save NPS",            position_x=1040, position_y=300, position=4, config={
                "survey_name": "nps",
                "fields": {"score": "nps_score", "reason": "nps_reason"},
            }),
            dict(id=n_thanks,         node_type="message",      label="Thank you",           position_x=1280, position_y=300, position=5, config={
                "message": "Thank you for the feedback — we really appreciate it! 🙏",
            }),
            dict(id=n_end,            node_type="end",          label="End",                 position_x=1520, position_y=300, position=6, config={}),
            # Timeout path — reached when visitor fails to enter a valid 0-10 score
            dict(id=n_score_bail_msg, node_type="message",      label="Skip NPS",            position_x= 560, position_y=560, position=7, config={
                "message": "No problem — we'll skip the NPS rating for now. Thank you for chatting with us! 🙏",
            }),
            dict(id=n_score_bail_end, node_type="end",          label="End (no score)",      position_x= 800, position_y=560, position=8, config={}),
        ],
        edges_spec=[
            (n_start, n_msg),
            (n_msg, n_score),
            (n_score, n_reason),                             # default: valid score captured
            (n_score, n_score_bail_msg, "timeout"),         # timeout: max retries exhausted
            (n_reason, n_save_survey),                       # default: reason captured → save
            (n_reason, n_save_survey, "timeout"),           # timeout: no reason → still save score
            (n_save_survey, n_thanks),
            (n_thanks, n_end),
            (n_score_bail_msg, n_score_bail_end),
        ],
        label="NPS sub-flow template",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text

    # ── STEP 1: Rename legacy tables (no prefix) to chat_ prefix  ────────
    # Runs safely on old installs; skips if the new name already exists.   ──
    async with engine.begin() as conn:
        renames = [
            (
                "rename users -> chat_users",
                "DO $$ BEGIN "
                "IF (to_regclass('public.users') IS NOT NULL "
                "AND to_regclass('public.chat_users') IS NULL) "
                "THEN ALTER TABLE users RENAME TO chat_users; "
                "END IF; END $$",
            ),
            (
                "rename teams -> chat_teams",
                "DO $$ BEGIN "
                "IF (to_regclass('public.teams') IS NOT NULL "
                "AND to_regclass('public.chat_teams') IS NULL) "
                "THEN ALTER TABLE teams RENAME TO chat_teams; "
                "END IF; END $$",
            ),
            (
                "rename custom_roles -> chat_custom_roles",
                "DO $$ BEGIN "
                "IF (to_regclass('public.custom_roles') IS NOT NULL "
                "AND to_regclass('public.chat_custom_roles') IS NULL) "
                "THEN ALTER TABLE custom_roles RENAME TO chat_custom_roles; "
                "END IF; END $$",
            ),
            (
                "rename skills -> chat_skills",
                "DO $$ BEGIN "
                "IF (to_regclass('public.skills') IS NOT NULL "
                "AND to_regclass('public.chat_skills') IS NULL) "
                "THEN ALTER TABLE skills RENAME TO chat_skills; "
                "END IF; END $$",
            ),
            (
                "rename queues -> chat_queues",
                "DO $$ BEGIN "
                "IF (to_regclass('public.queues') IS NOT NULL "
                "AND to_regclass('public.chat_queues') IS NULL) "
                "THEN ALTER TABLE queues RENAME TO chat_queues; "
                "END IF; END $$",
            ),
            (
                "rename contacts -> chat_contacts",
                "DO $$ BEGIN "
                "IF (to_regclass('public.contacts') IS NOT NULL "
                "AND to_regclass('public.chat_contacts') IS NULL) "
                "THEN ALTER TABLE contacts RENAME TO chat_contacts; "
                "END IF; END $$",
            ),
            (
                "rename contact_lists -> chat_contact_lists",
                "DO $$ BEGIN "
                "IF (to_regclass('public.contact_lists') IS NOT NULL "
                "AND to_regclass('public.chat_contact_lists') IS NULL) "
                "THEN ALTER TABLE contact_lists RENAME TO chat_contact_lists; "
                "END IF; END $$",
            ),
            (
                "rename contact_list_members -> chat_contact_list_members",
                "DO $$ BEGIN "
                "IF (to_regclass('public.contact_list_members') IS NOT NULL "
                "AND to_regclass('public.chat_contact_list_members') IS NULL) "
                "THEN ALTER TABLE contact_list_members RENAME TO chat_contact_list_members; "
                "END IF; END $$",
            ),
            (
                "rename flows -> chat_flows",
                "DO $$ BEGIN "
                "IF (to_regclass('public.flows') IS NOT NULL "
                "AND to_regclass('public.chat_flows') IS NULL) "
                "THEN ALTER TABLE flows RENAME TO chat_flows; "
                "END IF; END $$",
            ),
            (
                "rename flow_nodes -> chat_flow_nodes",
                "DO $$ BEGIN "
                "IF (to_regclass('public.flow_nodes') IS NOT NULL "
                "AND to_regclass('public.chat_flow_nodes') IS NULL) "
                "THEN ALTER TABLE flow_nodes RENAME TO chat_flow_nodes; "
                "END IF; END $$",
            ),
            (
                "rename flow_edges -> chat_flow_edges",
                "DO $$ BEGIN "
                "IF (to_regclass('public.flow_edges') IS NOT NULL "
                "AND to_regclass('public.chat_flow_edges') IS NULL) "
                "THEN ALTER TABLE flow_edges RENAME TO chat_flow_edges; "
                "END IF; END $$",
            ),
            (
                "rename flow_versions -> chat_flow_versions",
                "DO $$ BEGIN "
                "IF (to_regclass('public.flow_versions') IS NOT NULL "
                "AND to_regclass('public.chat_flow_versions') IS NULL) "
                "THEN ALTER TABLE flow_versions RENAME TO chat_flow_versions; "
                "END IF; END $$",
            ),
            (
                "rename flow_node_stats -> chat_flow_node_stats",
                "DO $$ BEGIN "
                "IF (to_regclass('public.flow_node_stats') IS NOT NULL "
                "AND to_regclass('public.chat_flow_node_stats') IS NULL) "
                "THEN ALTER TABLE flow_node_stats RENAME TO chat_flow_node_stats; "
                "END IF; END $$",
            ),
            (
                "rename flow_node_visit_log -> chat_flow_node_visit_log",
                "DO $$ BEGIN "
                "IF (to_regclass('public.flow_node_visit_log') IS NOT NULL "
                "AND to_regclass('public.chat_flow_node_visit_log') IS NULL) "
                "THEN ALTER TABLE flow_node_visit_log RENAME TO chat_flow_node_visit_log; "
                "END IF; END $$",
            ),
            (
                "rename conversations -> chat_conversations",
                "DO $$ BEGIN "
                "IF (to_regclass('public.conversations') IS NOT NULL "
                "AND to_regclass('public.chat_conversations') IS NULL) "
                "THEN ALTER TABLE conversations RENAME TO chat_conversations; "
                "END IF; END $$",
            ),
            (
                "rename messages -> chat_messages",
                "DO $$ BEGIN "
                "IF (to_regclass('public.messages') IS NOT NULL "
                "AND to_regclass('public.chat_messages') IS NULL) "
                "THEN ALTER TABLE messages RENAME TO chat_messages; "
                "END IF; END $$",
            ),
            (
                "rename campaigns -> chat_campaigns",
                "DO $$ BEGIN "
                "IF (to_regclass('public.campaigns') IS NOT NULL "
                "AND to_regclass('public.chat_campaigns') IS NULL) "
                "THEN ALTER TABLE campaigns RENAME TO chat_campaigns; "
                "END IF; END $$",
            ),
            (
                "rename campaign_attempts -> chat_campaign_attempts",
                "DO $$ BEGIN "
                "IF (to_regclass('public.campaign_attempts') IS NOT NULL "
                "AND to_regclass('public.chat_campaign_attempts') IS NULL) "
                "THEN ALTER TABLE campaign_attempts RENAME TO chat_campaign_attempts; "
                "END IF; END $$",
            ),
            (
                "rename outcomes -> chat_outcomes",
                "DO $$ BEGIN "
                "IF (to_regclass('public.outcomes') IS NOT NULL "
                "AND to_regclass('public.chat_outcomes') IS NULL) "
                "THEN ALTER TABLE outcomes RENAME TO chat_outcomes; "
                "END IF; END $$",
            ),
            (
                "rename audit_logs -> chat_audit_logs",
                "DO $$ BEGIN "
                "IF (to_regclass('public.audit_logs') IS NOT NULL "
                "AND to_regclass('public.chat_audit_logs') IS NULL) "
                "THEN ALTER TABLE audit_logs RENAME TO chat_audit_logs; "
                "END IF; END $$",
            ),
            (
                "rename global_settings -> chat_global_settings",
                "DO $$ BEGIN "
                "IF (to_regclass('public.global_settings') IS NOT NULL "
                "AND to_regclass('public.chat_global_settings') IS NULL) "
                "THEN ALTER TABLE global_settings RENAME TO chat_global_settings; "
                "END IF; END $$",
            ),
            (
                "rename custom_node_types -> chat_custom_node_types",
                "DO $$ BEGIN "
                "IF (to_regclass('public.custom_node_types') IS NOT NULL "
                "AND to_regclass('public.chat_custom_node_types') IS NULL) "
                "THEN ALTER TABLE custom_node_types RENAME TO chat_custom_node_types; "
                "END IF; END $$",
            ),
            (
                "rename connectors -> chat_connectors",
                "DO $$ BEGIN "
                "IF (to_regclass('public.connectors') IS NOT NULL "
                "AND to_regclass('public.chat_connectors') IS NULL) "
                "THEN ALTER TABLE connectors RENAME TO chat_connectors; "
                "END IF; END $$",
            ),
            (
                "rename interactions -> chat_interactions",
                "DO $$ BEGIN "
                "IF (to_regclass('public.interactions') IS NOT NULL "
                "AND to_regclass('public.chat_interactions') IS NULL) "
                "THEN ALTER TABLE interactions RENAME TO chat_interactions; "
                "END IF; END $$",
            ),
            (
                "rename email_connectors -> chat_email_connectors",
                "DO $$ BEGIN "
                "IF (to_regclass('public.email_connectors') IS NOT NULL "
                "AND to_regclass('public.chat_email_connectors') IS NULL) "
                "THEN ALTER TABLE email_connectors RENAME TO chat_email_connectors; "
                "END IF; END $$",
            ),
            (
                "rename whatsapp_connectors -> chat_whatsapp_connectors",
                "DO $$ BEGIN "
                "IF (to_regclass('public.whatsapp_connectors') IS NOT NULL "
                "AND to_regclass('public.chat_whatsapp_connectors') IS NULL) "
                "THEN ALTER TABLE whatsapp_connectors RENAME TO chat_whatsapp_connectors; "
                "END IF; END $$",
            ),
            (
                "rename voice_connectors -> chat_voice_connectors",
                "DO $$ BEGIN "
                "IF (to_regclass('public.voice_connectors') IS NOT NULL "
                "AND to_regclass('public.chat_voice_connectors') IS NULL) "
                "THEN ALTER TABLE voice_connectors RENAME TO chat_voice_connectors; "
                "END IF; END $$",
            ),
            (
                "rename sms_connectors -> chat_sms_connectors",
                "DO $$ BEGIN "
                "IF (to_regclass('public.sms_connectors') IS NOT NULL "
                "AND to_regclass('public.chat_sms_connectors') IS NULL) "
                "THEN ALTER TABLE sms_connectors RENAME TO chat_sms_connectors; "
                "END IF; END $$",
            ),
            (
                "rename survey_submissions -> chat_survey_submissions",
                "DO $$ BEGIN "
                "IF (to_regclass('public.survey_submissions') IS NOT NULL "
                "AND to_regclass('public.chat_survey_submissions') IS NULL) "
                "THEN ALTER TABLE survey_submissions RENAME TO chat_survey_submissions; "
                "END IF; END $$",
            ),
            (
                "rename tags -> chat_tags",
                "DO $$ BEGIN "
                "IF (to_regclass('public.tags') IS NOT NULL "
                "AND to_regclass('public.chat_tags') IS NULL) "
                "THEN ALTER TABLE tags RENAME TO chat_tags; "
                "END IF; END $$",
            ),
            (
                "rename office_hours_groups -> chat_office_hours_groups",
                "DO $$ BEGIN "
                "IF (to_regclass('public.office_hours_groups') IS NOT NULL "
                "AND to_regclass('public.chat_office_hours_groups') IS NULL) "
                "THEN ALTER TABLE office_hours_groups RENAME TO chat_office_hours_groups; "
                "END IF; END $$",
            ),
            (
                "rename office_hours_schedule -> chat_office_hours_schedule",
                "DO $$ BEGIN "
                "IF (to_regclass('public.office_hours_schedule') IS NOT NULL "
                "AND to_regclass('public.chat_office_hours_schedule') IS NULL) "
                "THEN ALTER TABLE office_hours_schedule RENAME TO chat_office_hours_schedule; "
                "END IF; END $$",
            ),
            (
                "rename office_hours_exclusions -> chat_office_hours_exclusions",
                "DO $$ BEGIN "
                "IF (to_regclass('public.office_hours_exclusions') IS NOT NULL "
                "AND to_regclass('public.chat_office_hours_exclusions') IS NULL) "
                "THEN ALTER TABLE office_hours_exclusions RENAME TO chat_office_hours_exclusions; "
                "END IF; END $$",
            ),
            (
                "rename team_members -> chat_team_members",
                "DO $$ BEGIN "
                "IF (to_regclass('public.team_members') IS NOT NULL "
                "AND to_regclass('public.chat_team_members') IS NULL) "
                "THEN ALTER TABLE team_members RENAME TO chat_team_members; "
                "END IF; END $$",
            ),
            (
                "rename queue_agents -> chat_queue_agents",
                "DO $$ BEGIN "
                "IF (to_regclass('public.queue_agents') IS NOT NULL "
                "AND to_regclass('public.chat_queue_agents') IS NULL) "
                "THEN ALTER TABLE queue_agents RENAME TO chat_queue_agents; "
                "END IF; END $$",
            ),
            (
                "rename user_skills -> chat_user_skills",
                "DO $$ BEGIN "
                "IF (to_regclass('public.user_skills') IS NOT NULL "
                "AND to_regclass('public.chat_user_skills') IS NULL) "
                "THEN ALTER TABLE user_skills RENAME TO chat_user_skills; "
                "END IF; END $$",
            ),
            (
                "rename campaign_contact_lists -> chat_campaign_contact_lists",
                "DO $$ BEGIN "
                "IF (to_regclass('public.campaign_contact_lists') IS NOT NULL "
                "AND to_regclass('public.chat_campaign_contact_lists') IS NULL) "
                "THEN ALTER TABLE campaign_contact_lists RENAME TO chat_campaign_contact_lists; "
                "END IF; END $$",
            ),
            (
                "rename interaction_tags -> chat_interaction_tags",
                "DO $$ BEGIN "
                "IF (to_regclass('public.interaction_tags') IS NOT NULL "
                "AND to_regclass('public.chat_interaction_tags') IS NULL) "
                "THEN ALTER TABLE interaction_tags RENAME TO chat_interaction_tags; "
                "END IF; END $$",
            ),
            (
                "rename contact_tags -> chat_contact_tags",
                "DO $$ BEGIN "
                "IF (to_regclass('public.contact_tags') IS NOT NULL "
                "AND to_regclass('public.chat_contact_tags') IS NULL) "
                "THEN ALTER TABLE contact_tags RENAME TO chat_contact_tags; "
                "END IF; END $$",
            ),
            (
                "rename user_tags -> chat_user_tags",
                "DO $$ BEGIN "
                "IF (to_regclass('public.user_tags') IS NOT NULL "
                "AND to_regclass('public.chat_user_tags') IS NULL) "
                "THEN ALTER TABLE user_tags RENAME TO chat_user_tags; "
                "END IF; END $$",
            ),
            (
                "rename chat_sessions -> chat_interactions",
                "DO $$ BEGIN "
                "IF (to_regclass('public.chat_sessions') IS NOT NULL "
                "AND to_regclass('public.chat_interactions') IS NULL) "
                "THEN ALTER TABLE chat_sessions RENAME TO chat_interactions; "
                "END IF; END $$",
            ),
        ]
        for label, sql in renames:
            try:
                await conn.exec_driver_sql(sql)
                print(f"[WizzardChat] {label} OK")
            except Exception as e:
                print(f"[WizzardChat] {label} skip: {e}")

    # ── STEP 2: Ensure schema exists, then create any missing tables ─────
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"[WizzardChat] Database tables ready (schema: {settings.db_schema})")

    # Migrate node_type column from enum to varchar if needed
    async with engine.begin() as conn:
        try:
            r = await conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='chat_flow_nodes' AND column_name='node_type'"
            ))
            row = r.fetchone()
            if row and row[0] == 'USER-DEFINED':
                await conn.execute(text(
                    "ALTER TABLE chat_flow_nodes ALTER COLUMN node_type TYPE VARCHAR(50) USING node_type::text"
                ))
                await conn.execute(text("DROP TYPE IF EXISTS flownodetype CASCADE"))
                print("[WizzardChat] Migrated flow_nodes.node_type from enum to varchar")
        except Exception as e:
            print(f"[WizzardChat] node_type migration check: {e}")

    # ── STEP 3: Column-level migrations (all using new table names) ──────────
    # Each migration runs in its own transaction so a failed/skipped statement
    # (e.g. RENAME on a column that already has the new name) never aborts the
    # connection and blocks all subsequent migrations.
    _migrations = [
            # queues
            ("queues.color",       "ALTER TABLE chat_queues ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#fd7e14'"),
            ("queues.outcomes",    "ALTER TABLE chat_queues ADD COLUMN IF NOT EXISTS outcomes JSONB DEFAULT '[]'"),
            ("queues.campaign_id", "ALTER TABLE chat_queues ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES chat_campaigns(id) ON DELETE SET NULL"),
            # campaigns
            ("campaigns.color",         "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#0d6efd'"),
            ("campaigns.is_active",     "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"),
            ("campaigns.campaign_time", "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS campaign_time JSONB DEFAULT '{\"start\":\"08:00\",\"end\":\"17:00\"}'"),
            ("campaigns.options",       "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS options JSONB DEFAULT '{\"allow_transfer\":true,\"allow_callback\":false}'"),
            ("campaigns.outcomes",      "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS outcomes JSONB DEFAULT '[]'"),
            ("campaigns.queues",        "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS queues JSONB DEFAULT '[]'"),
            ("campaigns.agents",        "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS agents JSONB DEFAULT '[]'"),
            # connectors (was chat_connectors)
            ("connectors.meta_fields",      "ALTER TABLE chat_connectors ADD COLUMN IF NOT EXISTS meta_fields JSONB DEFAULT '[]'"),
            ("connectors.allowed_origins",  "ALTER TABLE chat_connectors ADD COLUMN IF NOT EXISTS allowed_origins JSONB DEFAULT '[\"*\"]'"),
            ("connectors.style",            "ALTER TABLE chat_connectors ADD COLUMN IF NOT EXISTS style JSONB DEFAULT '{}'"),
            # interactions (was chat_sessions)
            ("interactions.waiting_node_id",  "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS waiting_node_id VARCHAR(128)"),
            ("interactions.flow_context",     "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS flow_context JSONB DEFAULT '{}'"),
            ("interactions.visitor_metadata", "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS visitor_metadata JSONB DEFAULT '{}'"),
            ("interactions.queue_id",         "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS queue_id UUID REFERENCES chat_queues(id) ON DELETE SET NULL"),
            ("interactions.agent_id",         "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES chat_users(id) ON DELETE SET NULL"),
            ("interactions.last_activity_at", "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP"),
            ("interactions.message_log",      "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS message_log JSONB DEFAULT '[]'"),
            # team_members: one team per user
            ("team_members.uq_user", "CREATE UNIQUE INDEX IF NOT EXISTS uq_team_members_user ON chat_team_members(user_id)"),
            # custom_roles table
            ("custom_roles.table", "CREATE TABLE IF NOT EXISTS chat_custom_roles (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(100) UNIQUE NOT NULL, description TEXT, is_system BOOLEAN NOT NULL DEFAULT FALSE, permissions JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())"),
            # contacts – extended fields
            ("contacts.title",         "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS title VARCHAR(50)"),
            ("contacts.job_title",     "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS job_title VARCHAR(150)"),
            ("contacts.address_line1", "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255)"),
            ("contacts.city",          "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS city VARCHAR(100)"),
            ("contacts.state",         "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS state VARCHAR(100)"),
            ("contacts.postal_code",   "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20)"),
            ("contacts.country",       "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS country VARCHAR(100)"),
            ("contacts.date_of_birth", "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS date_of_birth VARCHAR(20)"),
            ("contacts.gender",        "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS gender VARCHAR(20)"),
            ("contacts.language",      "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS language VARCHAR(20) DEFAULT 'en'"),
            ("contacts.source",        "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS source VARCHAR(100)"),
            ("contacts.notes",         "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS notes TEXT"),
            # contact_lists – color
            ("contact_lists.color",    "ALTER TABLE chat_contact_lists ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#0d6efd'"),
            # visitor disconnect detection
            ("interactions.visitor_last_seen",     "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS visitor_last_seen TIMESTAMP"),
            ("interactions.disconnect_outcome",    "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS disconnect_outcome VARCHAR(200)"),
            ("queues.disconnect_timeout_minutes",  "ALTER TABLE chat_queues ADD COLUMN IF NOT EXISTS disconnect_timeout_minutes INT"),
            ("flows.disconnect_timeout_minutes",   "ALTER TABLE chat_flows ADD COLUMN IF NOT EXISTS disconnect_timeout_minutes INT"),
            # rename minutes → seconds
            ("queues.disconnect_timeout_seconds",  "ALTER TABLE chat_queues RENAME COLUMN disconnect_timeout_minutes TO disconnect_timeout_seconds"),
            ("flows.disconnect_timeout_seconds",   "ALTER TABLE chat_flows RENAME COLUMN disconnect_timeout_minutes TO disconnect_timeout_seconds"),
            # outcomes: action_type + redirect_flow_id (action-level config on the outcome itself)
            ("outcomes.action_type",         "ALTER TABLE chat_outcomes ADD COLUMN IF NOT EXISTS action_type VARCHAR(30) DEFAULT 'end_interaction'"),
            ("outcomes.redirect_flow_id",    "ALTER TABLE chat_outcomes ADD COLUMN IF NOT EXISTS redirect_flow_id UUID"),
            # queue / flow: single FK to the outcome to apply on disconnect
            ("queues.disconnect_outcome_id", "ALTER TABLE chat_queues ADD COLUMN IF NOT EXISTS disconnect_outcome_id UUID"),
            ("flows.disconnect_outcome_id",  "ALTER TABLE chat_flows ADD COLUMN IF NOT EXISTS disconnect_outcome_id UUID"),
            # per-edge analytics: track which node triggered each visit log entry
            ("flow_node_visit_log.from_node_id", "ALTER TABLE chat_flow_node_visit_log ADD COLUMN IF NOT EXISTS from_node_id UUID"),
            # error / abandon event tracking
            ("flow_node_visit_log.event_type", "ALTER TABLE chat_flow_node_visit_log ADD COLUMN IF NOT EXISTS event_type VARCHAR(20) NOT NULL DEFAULT 'visit'"),
            # ── Flow versioning: integer → semver string (major.minor) ──────────
            # Convert flows.version from INT to VARCHAR and normalise existing values to "N.0"
            ("flows.version_to_varchar", """
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='chat_flows' AND column_name='version' AND data_type='integer'
                  ) THEN
                    ALTER TABLE flows ALTER COLUMN version TYPE VARCHAR(50) USING version::text;
                    UPDATE flows SET version = version || '.0' WHERE version NOT LIKE '%.%';
                  END IF;
                END $$
            """),
            # Convert flow_versions.version_number from INT to VARCHAR similarly
            ("flow_versions.version_number_to_varchar", """
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='chat_flow_versions' AND column_name='version_number' AND data_type='integer'
                  ) THEN
                    ALTER TABLE flow_versions ALTER COLUMN version_number TYPE VARCHAR(50) USING version_number::text;
                    UPDATE flow_versions SET version_number = version_number || '.0' WHERE version_number NOT LIKE '%.%';
                  END IF;
                END $$
            """),
            # New Flow columns
            ("flows.published_version",       "ALTER TABLE chat_flows ADD COLUMN IF NOT EXISTS published_version VARCHAR(50)"),
            ("flows.is_restored",             "ALTER TABLE chat_flows ADD COLUMN IF NOT EXISTS is_restored BOOLEAN DEFAULT FALSE"),
            ("flows.restored_from_version",   "ALTER TABLE chat_flows ADD COLUMN IF NOT EXISTS restored_from_version VARCHAR(50)"),
            # New FlowVersion column
            ("flow_versions.is_published_snapshot", "ALTER TABLE chat_flow_versions ADD COLUMN IF NOT EXISTS is_published_snapshot BOOLEAN DEFAULT FALSE"),
            # CSAT: score, comment and submission timestamp on interactions
            ("interactions.csat_score",        "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS csat_score INT"),
            ("interactions.csat_comment",      "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS csat_comment TEXT"),
            ("interactions.csat_submitted_at", "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS csat_submitted_at TIMESTAMP"),
            # NPS: score (0-10), reason and submission timestamp
            ("interactions.nps_score",         "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS nps_score INT"),
            ("interactions.nps_reason",        "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS nps_reason TEXT"),
            ("interactions.nps_submitted_at",  "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS nps_submitted_at TIMESTAMP"),
            # AI-generated session summary
            ("interactions.notes",             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS notes TEXT"),
            # Generic survey submissions table — replaces magic variable names
            ("survey_submissions.table", """
                CREATE TABLE IF NOT EXISTS chat_survey_submissions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    interaction_id UUID NOT NULL REFERENCES chat_interactions(id) ON DELETE CASCADE,
                    survey_name VARCHAR(120) NOT NULL,
                    responses JSONB NOT NULL DEFAULT '{}',
                    submitted_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """),
            ("survey_submissions.ix_interaction",
             "CREATE INDEX IF NOT EXISTS ix_survey_submissions_interaction ON chat_survey_submissions(interaction_id)"),
            ("survey_submissions.ix_name",
             "CREATE INDEX IF NOT EXISTS ix_survey_submissions_name ON chat_survey_submissions(survey_name)"),
            # Wrap-up timing columns on interactions
            ("interactions.wrap_started_at",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS wrap_started_at TIMESTAMP"),
            ("interactions.wrap_time",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS wrap_time INTEGER"),
            # Segment-level lifecycle tracking
            ("interactions.segments",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS segments JSONB DEFAULT '[]'::jsonb"),
            # Interaction classification dimensions (QA + reporting)
            ("interactions.contact_id",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS contact_id UUID REFERENCES chat_contacts(id) ON DELETE SET NULL"),
            ("interactions.direction",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS direction VARCHAR(10)"),
            ("interactions.channel",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS channel VARCHAR(30)"),
            ("interactions.handling_type",
             "ALTER TABLE chat_interactions ADD COLUMN IF NOT EXISTS handling_type VARCHAR(20)"),
            ("interactions.ix_contact",
             "CREATE INDEX IF NOT EXISTS ix_interactions_contact ON chat_interactions(contact_id)"),
            ("interactions.ix_channel",
             "CREATE INDEX IF NOT EXISTS ix_interactions_channel ON chat_interactions(channel)"),
            # Agent language skill capability
            ("users.languages",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS languages JSONB DEFAULT '[]'::jsonb"),
            # Proactive trigger configuration per connector
            ("connectors.proactive_triggers",
             "ALTER TABLE chat_connectors ADD COLUMN IF NOT EXISTS proactive_triggers JSONB DEFAULT '{}'::jsonb"),
            # ── WhatsApp BSUID (March 2026) ─────────────────────────────────────
            ("contacts.wa_user_id",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS wa_user_id VARCHAR(128)"),
            ("contacts.ix_wa_user_id",
             "CREATE INDEX IF NOT EXISTS ix_contacts_wa_user_id ON chat_contacts(wa_user_id)"),
            # ── CPA/ECTA opt-out and consent fields ─────────────────────────────
            ("contacts.do_not_call",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS do_not_call BOOLEAN NOT NULL DEFAULT FALSE"),
            ("contacts.do_not_whatsapp",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS do_not_whatsapp BOOLEAN NOT NULL DEFAULT FALSE"),
            ("contacts.do_not_sms",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS do_not_sms BOOLEAN NOT NULL DEFAULT FALSE"),
            ("contacts.do_not_email",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS do_not_email BOOLEAN NOT NULL DEFAULT FALSE"),
            ("contacts.opt_out_at",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS opt_out_at TIMESTAMP"),
            ("contacts.opt_in_channel",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS opt_in_channel VARCHAR(50)"),
            ("contacts.opt_in_at",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS opt_in_at TIMESTAMP"),
            ("contacts.opt_in_reference",
             "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS opt_in_reference VARCHAR(255)"),
            # ── Voice connector: TwiML App SID for browser WebRTC ──────────────────
            ("voice_connectors.twiml_app_sid",
             "ALTER TABLE chat_voice_connectors ADD COLUMN IF NOT EXISTS twiml_app_sid VARCHAR(100)"),
            # ── Voice connector: on-premise PBX outbound caller ID override ────────
            ("voice_connectors.caller_id_override",
             "ALTER TABLE chat_voice_connectors ADD COLUMN IF NOT EXISTS caller_id_override VARCHAR(50)"),
            # ── Campaign agent-group assignment ─────────────────────────────────────
            ("campaigns.agent_groups",
             "ALTER TABLE chat_campaigns ADD COLUMN IF NOT EXISTS agent_groups JSONB DEFAULT '[]'"),
            # ── Agent omnichannel capacity limits (Phase 1) ──────────────────────────
            ("users.omni_max",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS omni_max INTEGER"),
            ("users.channel_max_voice",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS channel_max_voice INTEGER"),
            ("users.channel_max_chat",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS channel_max_chat INTEGER"),
            ("users.channel_max_whatsapp",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS channel_max_whatsapp INTEGER"),
            ("users.channel_max_email",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS channel_max_email INTEGER"),
            ("users.channel_max_sms",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS channel_max_sms INTEGER"),
            ("users.capacity_override_active",
             "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS capacity_override_active BOOLEAN NOT NULL DEFAULT FALSE"),
        ]
    for label, sql in _migrations:
        try:
            async with engine.begin() as _mig_conn:
                await _mig_conn.exec_driver_sql(sql)
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
            init_pwd = settings.admin_initial_password
            if not init_pwd:
                print("[WizzardChat] No ADMIN_INITIAL_PASSWORD set — system admin not seeded.")
                print("[WizzardChat] Set ADMIN_INITIAL_PASSWORD in .env to create the admin on first boot.")
            else:
                admin = User(
                    email="admin@wizzardchat.local",
                    username="admin",
                    hashed_password=hash_password(init_pwd),
                    full_name="System Admin",
                    role=UserRole.SUPER_ADMIN,
                    is_system_account=True,
                )
                session.add(admin)
                await session.commit()
                print("[WizzardChat] System admin seeded")
        else:
            # Admin already exists — never overwrite the password on boot.
            print("[WizzardChat] System admin already present — skipping seed.")

    # Seed system roles
    from app.routers.roles import seed_system_roles
    async with async_session() as session:
        await seed_system_roles(session)

    # Seed default global settings if not present
    from app.routers.settings import seed_settings
    async with async_session() as session:
        await seed_settings(session)
        print("[WizzardChat] Global settings ready")

    # Back-fill capacity columns for agents created before the capacity feature.
    # Any user with NULL capacity columns gets the current global defaults written
    # to their row so every agent has an explicit, visible configuration.
    from sqlalchemy import or_ as _or
    from app.models import GlobalSettings as _GS
    _CAP_KEYS = [
        ("omni_max",             "default_omni_max",             8),
        ("channel_max_voice",    "default_channel_max_voice",    1),
        ("channel_max_chat",     "default_channel_max_chat",     5),
        ("channel_max_whatsapp", "default_channel_max_whatsapp", 3),
        ("channel_max_email",    "default_channel_max_email",    5),
        ("channel_max_sms",      "default_channel_max_sms",      5),
    ]
    async with async_session() as session:
        # Load live global defaults from DB (may differ from code defaults if admin changed them)
        settings_rows = (await session.execute(
            select(_GS).where(_GS.key.in_([k for _, k, _ in _CAP_KEYS]))
        )).scalars().all()
        _live_defaults = {r.key: int(r.value) for r in settings_rows}
        _effective_defaults = {
            col: _live_defaults.get(sk, fb) for col, sk, fb in _CAP_KEYS
        }
        # Find all users with any NULL capacity column
        null_filter = _or(*[getattr(User, col).is_(None) for col, _, _ in _CAP_KEYS])
        users_to_fix = (await session.execute(select(User).where(null_filter))).scalars().all()
        for _u in users_to_fix:
            for col, _, _ in _CAP_KEYS:
                if getattr(_u, col) is None:
                    setattr(_u, col, _effective_defaults[col])
        if users_to_fix:
            await session.commit()
            print(f"[WizzardChat] Capacity defaults applied to {len(users_to_fix)} agent(s)")
        else:
            print("[WizzardChat] All agents already have capacity config")

    # Seed default interaction tags for A/B split testing (and general use)
    from app.models import Tag, TagType
    import re as _re
    def _slugify(name): return _re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    _default_tags = [
        {"name": "Variant A",        "slug": "variant-a",       "color": "#6f42c1"},
        {"name": "Variant B",        "slug": "variant-b",       "color": "#6f42c1"},
        {"name": "Campaign Control", "slug": "campaign-control", "color": "#0d6efd"},
        {"name": "Campaign Test",    "slug": "campaign-test",   "color": "#0d6efd"},
    ]
    async with async_session() as session:
        for _t in _default_tags:
            _exists = (await session.execute(
                select(Tag).where(Tag.slug == _t["slug"], Tag.tag_type == TagType.INTERACTION)
            )).scalar_one_or_none()
            if not _exists:
                session.add(Tag(
                    name=_t["name"], slug=_t["slug"],
                    tag_type=TagType.INTERACTION, color=_t["color"],
                    description="Seeded default A/B split tag",
                ))
        await session.commit()
        print("[WizzardChat] Interaction tags ready")

    # Reset all agent online flags — any stale True values from the previous
    # server process are meaningless now; agents re-connect and set is_online
    # again when they open the agent panel.
    from sqlalchemy import update as sa_update
    from app.models import User as UserModel
    async with async_session() as session:
        await session.execute(sa_update(UserModel).values(is_online=False))
        await session.commit()
    print("[WizzardChat] Agent online flags reset")

    # ── Seed survey sub-flow templates ─────────────────────────────────────────
    await _seed_csat_template()
    await _seed_nps_template()

    # ── Background: auto-close interactions when visitor has been disconnected
    # longer than the configured timeout (queue setting, or flow setting).
    import asyncio as _asyncio
    from datetime import datetime as _dt
    from sqlalchemy import select as _select
    from app.database import async_session as _sweep_session
    from app.models import Interaction as _Interaction, Connector as _Connector, Flow as _SweepFlow, Outcome as _SweepOutcome

    async def _disconnect_sweep():
        while True:
            await _asyncio.sleep(60)
            try:
                async with _sweep_session() as db:
                    res = await db.execute(
                        _select(_Interaction)
                        .where(_Interaction.status != "closed")
                        .where(_Interaction.visitor_last_seen.isnot(None))
                    )
                    now = _dt.utcnow()
                    _sweep_closed_keys: list = []
                    for interaction in res.scalars().all():
                        # Priority: queue timeout → connector's flow timeout → system default
                        # System default: 600 s — applies when neither queue nor flow sets a timeout
                        _SYSTEM_DEFAULT_DISCONNECT_S = 600
                        timeout_seconds = None
                        disconnect_outcome_id = None
                        if interaction.queue_id:
                            from app.models import Queue as _Queue
                            qr = await db.execute(_select(_Queue).where(_Queue.id == interaction.queue_id))
                            q_obj = qr.scalar_one_or_none()
                            if q_obj and q_obj.disconnect_timeout_seconds:
                                timeout_seconds = q_obj.disconnect_timeout_seconds
                                disconnect_outcome_id = q_obj.disconnect_outcome_id
                        if timeout_seconds is None and interaction.connector_id:
                            cr = await db.execute(_select(_Connector).where(_Connector.id == interaction.connector_id))
                            c_obj = cr.scalar_one_or_none()
                            if c_obj and c_obj.flow_id:
                                fr = await db.execute(_select(_SweepFlow).where(_SweepFlow.id == c_obj.flow_id))
                                f_obj = fr.scalar_one_or_none()
                                if f_obj and f_obj.disconnect_timeout_seconds:
                                    timeout_seconds = f_obj.disconnect_timeout_seconds
                                    disconnect_outcome_id = f_obj.disconnect_outcome_id
                        # Fall back to system default when no explicit timeout is configured
                        if timeout_seconds is None:
                            timeout_seconds = _SYSTEM_DEFAULT_DISCONNECT_S
                        elapsed = (now - interaction.visitor_last_seen).total_seconds()
                        if elapsed >= timeout_seconds:
                            # Log abandon event against the node where the visitor was waiting
                            if interaction.waiting_node_id:
                                try:
                                    from app.routers.chat_ws import _record_event_by_node_id as _rec_abandon
                                    _fc = interaction.flow_context or {}
                                    _aflow = _fc.get('_current_flow_id')
                                    if not _aflow and interaction.connector_id:
                                        _acr = await db.execute(_select(_Connector).where(_Connector.id == interaction.connector_id))
                                        _ac = _acr.scalar_one_or_none()
                                        if _ac:
                                            _aflow = str(_ac.flow_id)
                                    if _aflow:
                                        await _rec_abandon(_aflow, str(interaction.waiting_node_id), db, 'abandon')
                                except Exception:
                                    pass
                            # Resolve the outcome and its action
                            outcome_obj = None
                            if disconnect_outcome_id:
                                or_ = await db.execute(_select(_SweepOutcome).where(_SweepOutcome.id == disconnect_outcome_id))
                                outcome_obj = or_.scalar_one_or_none()
                            action_type = (outcome_obj.action_type if outcome_obj else None) or "end_interaction"
                            redirect_flow_id = outcome_obj.redirect_flow_id if outcome_obj else None
                            outcome_label = outcome_obj.label if outcome_obj else (interaction.disconnect_outcome or "abandoned")
                            log = list(interaction.message_log or [])
                            saved_agent_id = interaction.agent_id
                            if action_type == "flow_redirect" and redirect_flow_id:
                                # Record in history; redirect to recovery flow on visitor reconnect
                                log.append({
                                    "from": "system",
                                    "text": f"Visitor disconnected >{timeout_seconds}s — routing to recovery flow on reconnect.",
                                    "ts": now.isoformat(),
                                    "subtype": "system",
                                })
                                interaction.message_log = log
                                interaction.flow_context = {"_current_flow_id": str(redirect_flow_id)}
                                interaction.waiting_node_id = None
                                interaction.status = "active"
                                interaction.visitor_last_seen = None
                                interaction.queue_id = None
                                interaction.agent_id = None
                                _log.info(
                                    "Sweep: routed interaction %s to recovery flow %s (disconnected %.0fs)",
                                    interaction.session_key, redirect_flow_id, elapsed,
                                )
                                if saved_agent_id:
                                    from app.routers.chat_ws import manager as _ws_manager
                                    await _ws_manager.send_agent(str(saved_agent_id), {
                                        "type": "session_transferred",
                                        "session_id": interaction.session_key,
                                        "reason": "visitor_timeout_flow_redirect",
                                    })
                            else:
                                # end_interaction: close immediately
                                interaction.status = "closed"
                                _sweep_closed_keys.append(interaction.session_key)
                                log.append({
                                    "from": "system",
                                    "text": f"Auto-closed: visitor disconnected >{timeout_seconds}s. Outcome: {outcome_label}",
                                    "ts": now.isoformat(),
                                    "subtype": "system",
                                })
                                interaction.message_log = log
                                _log.info(
                                    "Sweep: auto-closed interaction %s (disconnected %.0fs ago)",
                                    interaction.session_key, elapsed,
                                )
                                if saved_agent_id:
                                    from app.routers.chat_ws import manager as _ws_manager
                                    await _ws_manager.send_agent(str(saved_agent_id), {
                                        "type": "session_closed",
                                        "session_id": interaction.session_key,
                                        "reason": "visitor_timeout",
                                        "outcome": outcome_label,
                                    })
                    await db.commit()
                    for _sk in _sweep_closed_keys:
                        try:
                            from app.routers.chat_ws import _summarise_async as _do_summarise
                            _asyncio.ensure_future(_do_summarise(_sk))
                        except Exception:
                            pass
            except Exception as _sweep_err:
                _log.exception("Disconnect sweep error: %s", _sweep_err)

    _asyncio.ensure_future(_disconnect_sweep())
    print("[WizzardChat] Visitor disconnect sweep task started")

    # ── Background: resume Wait/Delay nodes after their timer expires
    from app.models import Interaction as _WaitInteraction, Connector as _WaitConnector

    async def _wait_resume_sweep():
        while True:
            await _asyncio.sleep(5)  # poll every 5 seconds
            try:
                # First pass: collect session keys where timer has elapsed
                to_resume = []
                async with _sweep_session() as _wdb:
                    _wr = await _wdb.execute(
                        _select(_WaitInteraction)
                        .where(_WaitInteraction.status == "active")
                        .where(_WaitInteraction.waiting_node_id.isnot(None))
                    )
                    _now = _dt.utcnow()
                    for _si in _wr.scalars().all():
                        _fc = _si.flow_context or {}
                        _rat = _fc.get("_wait_resume_at")
                        if not _rat:
                            continue
                        try:
                            _resume_dt = _dt.fromisoformat(_rat)
                        except (ValueError, TypeError):
                            continue
                        if _now >= _resume_dt:
                            to_resume.append(_si.session_key)
                # Second pass: resume each in its own DB session
                for _sk in to_resume:
                    try:
                        async with _sweep_session() as _rdb:
                            _sr2 = await _rdb.execute(
                                _select(_WaitInteraction).where(_WaitInteraction.session_key == _sk)
                            )
                            _sess = _sr2.scalar_one_or_none()
                            if not _sess or _sess.status != "active" or not _sess.waiting_node_id:
                                continue
                            # Clear the wait marker before resuming
                            _fc2 = dict(_sess.flow_context or {})
                            _fc2.pop("_wait_resume_at", None)
                            _sess.flow_context = _fc2
                            _cr2 = await _rdb.execute(
                                _select(_WaitConnector).where(_WaitConnector.id == _sess.connector_id)
                            )
                            _conn = _cr2.scalar_one_or_none()
                            from app.routers.chat_ws import run_flow as _run_flow
                            await _run_flow(_sess, _conn, _rdb)
                            await _rdb.commit()
                            _log.info("Wait resume sweep: resumed session %s", _sk)
                    except Exception as _re:
                        _log.exception("Wait resume error for %s: %s", _sk, _re)
            except Exception as _we:
                _log.exception("Wait resume sweep error: %s", _we)

    _asyncio.ensure_future(_wait_resume_sweep())
    print("[WizzardChat] Wait/delay resume sweep task started")

    # ── Start email connector IMAP poll tasks ─────────────────────────────────
    from app.routers.email_connector import start_all_poll_tasks as _start_email_polls
    await _start_email_polls()

    yield

    await engine.dispose()


_OPENAPI_TAGS = [
    {"name": "auth",         "description": "Authentication — obtain JWT tokens and register users"},
    {"name": "users",        "description": "User account management and campaign assignments"},
    {"name": "flows",        "description": "Flow CRUD, node/edge management, publish and simulate"},
    {"name": "node-types",   "description": "Built-in and custom flow node type registry"},
    {"name": "connectors",   "description": "Chat connectors — embed snippet generation and key rotation"},
    {"name": "chat",         "description": "Visitor-facing chat endpoints (SSE stream, send, upload) and agent WebSocket"},
    {"name": "queues",       "description": "Agent queues and queue membership"},
    {"name": "contacts",     "description": "Contact records, lists, bulk operations and CSV import"},
    {"name": "campaigns",    "description": "Outbound campaign lifecycle — create, start, pause, cancel"},
    {"name": "teams",        "description": "Team management and membership"},
    {"name": "roles",        "description": "Roles and permission management"},
    {"name": "office-hours", "description": "Office hours groups, weekly schedules and date exclusions"},
    {"name": "outcomes",     "description": "Interaction outcome definitions"},
    {"name": "tags",         "description": "Tags and tag associations for interactions, contacts and users"},
    {"name": "settings",     "description": "Global platform settings (key/value store)"},
]

app = FastAPI(
    title="WizzardChat",
    description=(
        "Omnichannel Communication Platform – Voice, Chat, WhatsApp, App.\n\n"
        "All `/api/v1/*` endpoints (except `/api/v1/auth/login` and `/api/v1/auth/register`) "
        "require a **Bearer** JWT token obtained from `POST /api/v1/auth/login`.\n\n"
        "See [docs/04-api.md](https://github.com/wizzard0s/wizzardchat/blob/main/docs/04-api.md) "
        "for the full API reference."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)

# CORS
# allow_origins=["*"] is invalid with allow_credentials=True (browser rejects it).
# Origins are read from CORS_ORIGINS in .env (comma-separated).
_cors_origins = settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates (absolute paths — safe regardless of process cwd)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(agents_router.router)
app.include_router(flows.router)
app.include_router(queues.router)
app.include_router(contacts.router)
app.include_router(campaigns.router)
app.include_router(teams.router)
app.include_router(roles.router)
app.include_router(agent_groups_router.router)
app.include_router(settings_router.router)
app.include_router(node_types_router.router)
app.include_router(connectors_router.router)
app.include_router(chat_ws_router.router)
app.include_router(outcomes_router.router)
app.include_router(tags_router.router)
app.include_router(office_hours_router.router)
app.include_router(dashboard_router.router)
app.include_router(wallboard_router.router)
app.include_router(ai_router.router)
app.include_router(copilot_router.router)
app.include_router(csat_router.router)
app.include_router(interactions_router.router)
app.include_router(dialler_router.router)
app.include_router(inbound_router_module.router)
app.include_router(email_connector_router.router)
app.include_router(whatsapp_connector_router.router)
app.include_router(voice_connector_router.router)
app.include_router(sms_connector_router.router)
app.include_router(voice_twiml_router.router)
app.include_router(audit_router.router)
app.include_router(message_templates_router.router)

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/flows")
async def flows_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/flow-designer")
@app.get("/flow-designer/{flow_id}")
async def flow_designer_page(request: Request, flow_id: str = None):
    return templates.TemplateResponse("flow_designer.html", {"request": request, "flow_id": flow_id})


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/connectors")
async def connectors_page(request: Request):
    return templates.TemplateResponse("connectors.html", {"request": request})


@app.get("/queues")
async def queues_page(request: Request):
    return templates.TemplateResponse("queues.html", {"request": request})


@app.get("/campaigns")
async def campaigns_page(request: Request):
    return templates.TemplateResponse("campaigns.html", {"request": request})


@app.get("/dialler/{campaign_id}")
async def dialler_page(request: Request, campaign_id: str):
    return templates.TemplateResponse("dialler.html", {"request": request, "campaign_id": campaign_id})


@app.get("/contacts")
async def contacts_page(request: Request):
    return templates.TemplateResponse("contacts.html", {"request": request})


@app.get("/teams")
async def teams_page(request: Request):
    return templates.TemplateResponse("teams.html", {"request": request})


@app.get("/agent-groups")
async def agent_groups_page_redirect(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/groups")

@app.get("/groups")
async def groups_page(request: Request):
    return templates.TemplateResponse("agent_groups.html", {"request": request})


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


@app.get("/interactions")
async def interactions_page(request: Request):
    return templates.TemplateResponse("interactions.html", {"request": request})


@app.get("/wallboard")
async def wallboard_page(request: Request):
    return templates.TemplateResponse("wallboard.html", {"request": request})


@app.get("/audit-log")
async def audit_log_page(request: Request):
    return templates.TemplateResponse("audit_log.html", {"request": request})


@app.get("/msg-templates")
async def msg_templates_page(request: Request):
    return templates.TemplateResponse("msg_templates.html", {"request": request})


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

"""WizzardChat database models – full omnichannel schema."""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Float, DateTime, Date, ForeignKey,
    Enum as SAEnum, JSON, UniqueConstraint, Index, Table
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base
import enum


def _enum(e):
    """SAEnum that stores MEMBER NAMES (e.g. 'SUPER_ADMIN') matching the legacy
    uppercase PostgreSQL enum labels created before values_callable was set."""
    return SAEnum(e, values_callable=lambda x: [v.name for v in x])


# ──────────────────────────── Enums ────────────────────────────

class ChannelType(str, enum.Enum):
    VOICE = "voice"
    CHAT = "chat"
    WHATSAPP = "whatsapp"
    APP = "app"
    EMAIL = "email"
    SMS = "sms"


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    AGENT = "agent"
    VIEWER = "viewer"


class QueueStrategy(str, enum.Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_BUSY = "least_busy"
    SKILLS_BASED = "skills_based"
    PRIORITY = "priority"
    RANDOM = "random"


class ConversationStatus(str, enum.Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    WRAP_UP = "wrap_up"
    CLOSED = "closed"
    ABANDONED = "abandoned"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CampaignType(str, enum.Enum):
    OUTBOUND_VOICE = "outbound_voice"
    OUTBOUND_SMS = "outbound_sms"
    OUTBOUND_WHATSAPP = "outbound_whatsapp"
    OUTBOUND_EMAIL = "outbound_email"
    BLAST = "blast"


class AttemptStatus(str, enum.Enum):
    PENDING   = "pending"
    DIALLING  = "dialling"
    CONNECTED = "connected"
    NO_ANSWER = "no_answer"
    BUSY      = "busy"
    FAILED    = "failed"
    COMPLETED = "completed"
    SKIPPED   = "skipped"


class RecordingLeg(str, enum.Enum):
    OUTBOUND  = "outbound"   # contact leg (IVR/flow, hold, ringing)
    AGENT     = "agent"      # agent leg after bridge
    MERGED    = "merged"     # final merged/complete recording
    IVR       = "ivr"        # IVR/flow-only segment
    HOLD      = "hold"       # on-hold segment
    BARGE     = "barge"      # supervisor barge-in leg
    TRANSFER  = "transfer"   # warm transfer leg
    UNKNOWN   = "unknown"


class RecordingStatus(str, enum.Enum):
    PENDING    = "pending"    # provider notified us, download queued
    DOWNLOADING = "downloading"
    AVAILABLE  = "available"  # file stored locally in wizzrecordings/
    FAILED     = "failed"     # download / processing failed
    PROVIDER   = "provider"   # stored at provider only (no local copy)


class FlowNodeType(str, enum.Enum):
    START = "start"
    END = "end"
    MESSAGE = "message"
    CONDITION = "condition"
    INPUT = "input"
    TRANSFER = "transfer"
    QUEUE = "queue"
    HTTP_REQUEST = "http_request"
    SET_VARIABLE = "set_variable"
    WAIT = "wait"
    MENU = "menu"
    PLAY_AUDIO = "play_audio"
    RECORD = "record"
    DTMF = "dtmf"
    AI_BOT = "ai_bot"
    WEBHOOK = "webhook"
    GOTO = "goto"
    SUB_FLOW = "sub_flow"


class FlowType(str, enum.Enum):
    MAIN_FLOW = "main_flow"
    SUB_FLOW = "sub_flow"
    ERROR_HANDLER = "error_handler"
    SCHEDULED = "scheduled"


class FlowStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class ContactStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    OPTED_OUT = "opted_out"


class AuthType(str, enum.Enum):
    LOCAL = "local"
    SSO = "sso"
    LDAP = "ldap"
    OAUTH2 = "oauth2"
    SAML = "saml"


class TagType(str, enum.Enum):
    INTERACTION = "interaction"
    CONTACT = "contact"
    USER = "user"


# ─────────────── Association Tables ───────────────

team_members = Table(
    "chat_team_members",
    Base.metadata,
    Column("team_id", UUID(as_uuid=True), ForeignKey("chat_teams.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True),
)

queue_agents = Table(
    "chat_queue_agents",
    Base.metadata,
    Column("queue_id", UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True),
)

user_skills = Table(
    "chat_user_skills",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", UUID(as_uuid=True), ForeignKey("chat_skills.id", ondelete="CASCADE"), primary_key=True),
    Column("proficiency", Integer, default=100),  # 0-100
)

campaign_contact_lists = Table(
    "chat_campaign_contact_lists",
    Base.metadata,
    Column("campaign_id", UUID(as_uuid=True), ForeignKey("chat_campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("contact_list_id", UUID(as_uuid=True), ForeignKey("chat_contact_lists.id", ondelete="CASCADE"), primary_key=True),
)

interaction_tags = Table(
    "chat_interaction_tags",
    Base.metadata,
    Column("interaction_id", UUID(as_uuid=True), ForeignKey("chat_interactions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("chat_tags.id", ondelete="CASCADE"), primary_key=True),
)

contact_tags = Table(
    "chat_contact_tags",
    Base.metadata,
    Column("contact_id", UUID(as_uuid=True), ForeignKey("chat_contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("chat_tags.id", ondelete="CASCADE"), primary_key=True),
)

user_tags = Table(
    "chat_user_tags",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("chat_tags.id", ondelete="CASCADE"), primary_key=True),
)

agent_group_members = Table(
    "chat_agent_group_members",
    Base.metadata,
    Column("group_id", UUID(as_uuid=True), ForeignKey("chat_agent_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True),
)


# ──────────────────────────── Models ────────────────────────────

class User(Base):
    __tablename__ = "chat_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(_enum(UserRole), nullable=False, default=UserRole.AGENT)
    is_active = Column(Boolean, default=True)
    is_online = Column(Boolean, default=False)
    is_system_account = Column(Boolean, default=False, nullable=False)
    auth_type = Column(_enum(AuthType), nullable=False, default=AuthType.LOCAL)
    max_concurrent_chats = Column(Integer, default=5)
    # ── Omnichannel capacity (null = inherit business global default) ──────────
    omni_max            = Column(Integer, nullable=True)   # total across all channels
    channel_max_voice   = Column(Integer, nullable=True)   # concurrent voice calls (typically 1)
    channel_max_chat    = Column(Integer, nullable=True)   # concurrent chat sessions
    channel_max_whatsapp = Column(Integer, nullable=True)  # concurrent WhatsApp sessions
    channel_max_email   = Column(Integer, nullable=True)   # concurrent email threads
    channel_max_sms     = Column(Integer, nullable=True)   # concurrent SMS threads
    capacity_override_active = Column(Boolean, default=False, nullable=False)  # pick-next +1 slot consumed
    languages = Column(JSONB, default=list, nullable=True)  # ISO 639-1 codes: ["en","af","zu",…]
    avatar_url = Column(String(500))
    phone_number = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    teams = relationship("Team", secondary=team_members, back_populates="members")
    queues = relationship("Queue", secondary=queue_agents, back_populates="agents")
    conversations = relationship("Conversation", back_populates="agent", foreign_keys="Conversation.agent_id")
    skills = relationship("Skill", secondary=user_skills, back_populates="users")
    tag_refs = relationship("Tag", secondary="chat_user_tags", back_populates="tagged_users")


class Team(Base):
    __tablename__ = "chat_teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    leader_id = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    leader = relationship("User", foreign_keys=[leader_id])
    members = relationship("User", secondary=team_members, back_populates="teams")


class AgentGroup(Base):
    """Logical grouping of agents for campaign assignment (not related to permissions)."""
    __tablename__ = "chat_agent_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    color = Column(String(20), default="#6c757d")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = relationship("User", secondary=agent_group_members, backref="agent_groups")


class CustomRole(Base):
    """User-manageable roles with granular permissions."""
    __tablename__ = "chat_custom_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)  # True = seeded, not deletable
    permissions = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Skill(Base):
    __tablename__ = "chat_skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", secondary=user_skills, back_populates="skills")


class Queue(Base):
    __tablename__ = "chat_queues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    channel = Column(_enum(ChannelType), nullable=False)
    strategy = Column(_enum(QueueStrategy), default=QueueStrategy.ROUND_ROBIN)
    priority = Column(Integer, default=0)
    max_wait_time = Column(Integer, default=300)  # seconds
    sla_threshold = Column(Integer, default=30)  # seconds
    disconnect_timeout_seconds = Column(Integer, nullable=True)  # None = no auto-close
    disconnect_outcome_id = Column(UUID(as_uuid=True), ForeignKey("chat_outcomes.id", ondelete="SET NULL"), nullable=True)
    color = Column(String(20), default="#fd7e14")
    outcomes = Column(JSONB, default=list)  # [{key, label, description}]
    webform_urls = Column(JSONB, default=dict)  # {slots:[{name, url}], override_campaign:bool}
    is_active = Column(Boolean, default=True)
    overflow_queue_id = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"))
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"))
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("chat_campaigns.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    agents = relationship("User", secondary=queue_agents, back_populates="queues")
    overflow_queue = relationship("Queue", remote_side="Queue.id")
    flow = relationship("Flow", foreign_keys=[flow_id])
    disconnect_outcome = relationship("Outcome", foreign_keys=[disconnect_outcome_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
    conversations = relationship("Conversation", back_populates="queue")


# ──────────────── Contacts & Lists ────────────────

class Contact(Base):
    __tablename__ = "chat_contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # ── Identity ──
    first_name = Column(String(100))
    last_name = Column(String(100))
    title = Column(String(50))                        # Mr / Mrs / Dr / etc.
    job_title = Column(String(150))
    company = Column(String(255))
    # ── Contact channels ──
    email = Column(String(255), index=True)
    phone = Column(String(50), index=True)
    whatsapp_id = Column(String(50), index=True)
    wa_user_id = Column(String(128), nullable=True, index=True)  # Meta BSUID — set when phone is absent
    # ── CPA / ECTA compliance ──
    do_not_call        = Column(Boolean, default=False, nullable=False)     # DMASA DNC or customer opt-out
    do_not_whatsapp    = Column(Boolean, default=False, nullable=False)     # WhatsApp opt-out
    do_not_sms         = Column(Boolean, default=False, nullable=False)     # SMS opt-out
    do_not_email       = Column(Boolean, default=False, nullable=False)     # Email opt-out
    opt_out_at         = Column(DateTime, nullable=True)                    # Timestamp of most recent opt-out
    opt_in_channel     = Column(String(50), nullable=True)                  # Source of consent: web/import/call/whatsapp
    opt_in_at          = Column(DateTime, nullable=True)                    # Timestamp of consent capture
    opt_in_reference   = Column(String(255), nullable=True)                 # Reference / evidence (URL, doc ID)
    # ── Address ──
    address_line1 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100))
    # ── Demographics ──
    date_of_birth = Column(String(20))               # ISO date string
    gender = Column(String(20))                      # male/female/other/prefer_not_to_say
    language = Column(String(20), default="en")      # ISO-639-1 code
    # ── Classification ──
    status = Column(_enum(ContactStatus), default=ContactStatus.ACTIVE)
    source = Column(String(100))                     # web/import/api/manual/campaign
    tags = Column(JSONB, default=list)
    custom_fields = Column(JSONB, default=dict)
    notes = Column(Text)
    # ── Timestamps ──
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    list_memberships = relationship("ContactListMember", back_populates="contact")
    conversations = relationship("Conversation", back_populates="contact")
    tag_refs = relationship("Tag", secondary="chat_contact_tags", back_populates="tagged_contacts")


class ContactList(Base):
    __tablename__ = "chat_contact_lists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    color = Column(String(20), default="#0d6efd")
    is_dynamic = Column(Boolean, default=False)
    filter_criteria = Column(JSONB)  # For dynamic lists
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    members = relationship("ContactListMember", back_populates="contact_list")
    campaigns = relationship("Campaign", secondary=campaign_contact_lists, back_populates="contact_lists")


class ContactListMember(Base):
    __tablename__ = "chat_contact_list_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_list_id = Column(UUID(as_uuid=True), ForeignKey("chat_contact_lists.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("chat_contacts.id", ondelete="CASCADE"), nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contact_list_id", "contact_id"),)

    contact_list = relationship("ContactList", back_populates="members")
    contact = relationship("Contact", back_populates="list_memberships")


# ──────────────── Flows (IVR / Bot / Routing) ────────────────

class Flow(Base):
    __tablename__ = "chat_flows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    channel = Column(_enum(ChannelType))
    flow_type = Column(_enum(FlowType), nullable=False, default=FlowType.MAIN_FLOW)
    status = Column(_enum(FlowStatus), nullable=False, default=FlowStatus.DRAFT)
    is_active = Column(Boolean, default=False)
    is_published = Column(Boolean, default=False)
    published_version = Column(String(50), nullable=True)      # version string at last publish
    disconnect_timeout_seconds = Column(Integer, nullable=True)  # None = no auto-close
    disconnect_outcome_id = Column(UUID(as_uuid=True), ForeignKey("chat_outcomes.id", ondelete="SET NULL"), nullable=True)
    version = Column(String(50), default="1.0")               # major.minor — major++ on publish, minor++ on save
    is_restored = Column(Boolean, default=False)              # True when canvas was last set by a restore
    restored_from_version = Column(String(50), nullable=True) # version string of the snapshot restored from
    created_by = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    updated_by = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    nodes = relationship("FlowNode", back_populates="flow", cascade="all, delete-orphan", order_by="FlowNode.position")
    edges = relationship("FlowEdge", back_populates="flow", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])


class FlowNode(Base):
    __tablename__ = "chat_flow_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="CASCADE"), nullable=False)
    node_type = Column(String(50), nullable=False)  # built-in key or custom key
    label = Column(String(255), default="")
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    position = Column(Integer, default=0)
    config = Column(JSONB, default=dict)  # Node-specific configuration
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_flow_nodes_flow_id", "flow_id"),)

    flow = relationship("Flow", back_populates="nodes")
    outgoing_edges = relationship("FlowEdge", back_populates="source_node", foreign_keys="FlowEdge.source_node_id",
                                  cascade="all, delete-orphan")
    incoming_edges = relationship("FlowEdge", back_populates="target_node", foreign_keys="FlowEdge.target_node_id",
                                  cascade="all, delete-orphan")


class FlowEdge(Base):
    __tablename__ = "chat_flow_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="CASCADE"), nullable=False)
    source_node_id = Column(UUID(as_uuid=True), ForeignKey("chat_flow_nodes.id", ondelete="CASCADE"), nullable=False)
    target_node_id = Column(UUID(as_uuid=True), ForeignKey("chat_flow_nodes.id", ondelete="CASCADE"), nullable=False)
    source_handle = Column(String(50), default="default")  # which output port
    label = Column(String(255), default="")
    condition = Column(JSONB)  # Condition to traverse this edge
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_flow_edges_flow_id", "flow_id"),)

    flow = relationship("Flow", back_populates="edges")
    source_node = relationship("FlowNode", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node = relationship("FlowNode", foreign_keys=[target_node_id], back_populates="incoming_edges")


class FlowVersion(Base):
    """Immutable snapshot of a flow's nodes and edges, saved on each designer PUT."""
    __tablename__ = "chat_flow_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(String(50), nullable=False)       # e.g. "1.3" — string label of that snapshot
    is_published_snapshot = Column(Boolean, default=False)   # True when this snapshot was created by a publish
    label = Column(String(255), default="")          # optional user label
    snapshot = Column(JSONB, nullable=False)          # {nodes: [...], edges: [...]}
    saved_at = Column(DateTime, default=datetime.utcnow)
    saved_by = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("ix_flow_versions_flow_id", "flow_id"),)

    flow = relationship("Flow")
    saver = relationship("User", foreign_keys=[saved_by])


class FlowNodeStats(Base):
    """Cumulative visit counters per node — reset when the flow is re-saved."""
    __tablename__ = "chat_flow_node_stats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(UUID(as_uuid=True), nullable=False)   # not a FK — survives re-save
    node_label = Column(String(255), default="")
    node_type = Column(String(50), default="")
    visit_count = Column(Integer, default=0)
    last_visited_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("flow_id", "node_id", name="uq_flow_node_stats"),
        Index("ix_flow_node_stats_flow_id", "flow_id"),
    )

class FlowNodeVisitLog(Base):
    """Append-only per-visit log — used for time-windowed analytics."""
    __tablename__ = "chat_flow_node_visit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(UUID(as_uuid=True), nullable=False)
    node_label = Column(String(255), default="")
    node_type = Column(String(50), default="")
    from_node_id = Column(UUID(as_uuid=True), nullable=True)   # which node transitioned to this one
    event_type = Column(String(20), nullable=False, server_default='visit')  # visit | error | abandon
    visited_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_flow_node_visit_log_flow_time", "flow_id", "visited_at"),
    )

# ──────────────── Conversations ────────────────

class Conversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(_enum(ChannelType), nullable=False)
    status = Column(_enum(ConversationStatus), default=ConversationStatus.WAITING)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("chat_contacts.id", ondelete="SET NULL"))
    agent_id = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    queue_id = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"))
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("chat_campaigns.id", ondelete="SET NULL"))
    external_id = Column(String(255))  # e.g. WhatsApp conversation ID
    direction = Column(String(10), default="inbound")  # inbound / outbound
    priority = Column(Integer, default=0)
    tags = Column(JSONB, default=list)
    metadata_ = Column("metadata", JSONB, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow)
    answered_at = Column(DateTime)
    ended_at = Column(DateTime)
    wait_time = Column(Integer)   # seconds
    handle_time = Column(Integer)  # seconds
    wrap_up_code = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_conversations_status", "status"),
        Index("ix_conversations_agent", "agent_id"),
        Index("ix_conversations_queue", "queue_id"),
    )

    contact = relationship("Contact", back_populates="conversations")
    agent = relationship("User", back_populates="conversations", foreign_keys=[agent_id])
    queue = relationship("Queue", back_populates="conversations")
    campaign = relationship("Campaign", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Message(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    sender_type = Column(String(20), nullable=False)  # agent / contact / system / bot
    sender_id = Column(UUID(as_uuid=True))
    content_type = Column(String(50), default="text")  # text / image / audio / video / file / template
    content = Column(Text)
    media_url = Column(String(500))
    metadata_ = Column("metadata", JSONB, default=dict)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_messages_conversation", "conversation_id"),)

    conversation = relationship("Conversation", back_populates="messages")


# ──────────────── Campaigns ────────────────

class Campaign(Base):
    __tablename__ = "chat_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    campaign_type = Column(_enum(CampaignType), nullable=False)
    status = Column(_enum(CampaignStatus), default=CampaignStatus.DRAFT)
    is_active = Column(Boolean, default=True)
    color = Column(String(20), default="#0d6efd")
    campaign_time = Column(JSONB, default=lambda: {"start": "08:00", "end": "17:00"})  # daily hours
    options = Column(JSONB, default=lambda: {"allow_transfer": True, "allow_callback": False})  # feature flags
    outcomes = Column(JSONB, default=list)  # [{key, label, description}]
    webform_urls = Column(JSONB, default=dict)  # {slots:[{name, url}]}
    queues = Column(JSONB, default=list)    # list of Queue UUIDs assigned to this campaign
    agents = Column(JSONB, default=list)         # individual User UUIDs overrides / additions
    agent_groups = Column(JSONB, default=list)   # list of AgentGroup UUIDs assigned to this campaign
    queue_id = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"))
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"))
    scheduled_start = Column(DateTime)
    scheduled_end = Column(DateTime)
    max_attempts = Column(Integer, default=3)
    retry_interval = Column(Integer, default=3600)  # seconds
    caller_id = Column(String(50))
    message_template = Column(Text)
    settings = Column(JSONB, default=dict)
    # Outbound dialler configuration (multi-channel)
    # Keys: primary_channel, fallback_channels, autodial, dialler_mode,
    #       wa_template_id, wa_variable_map, wa_connector_id,
    #       sms_template_id, sms_variable_map, sms_connector_id,
    #       email_template_id, email_variable_map, email_connector_id,
    #       voice_connector_id, calling_hours, max_attempts, retry_interval_hours
    outbound_config = Column(JSONB, default=dict)
    stats = Column(JSONB, default=dict)  # {total, attempted, connected, completed, failed}
    created_by = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    queue = relationship("Queue", foreign_keys=[queue_id])
    flow = relationship("Flow", foreign_keys=[flow_id])
    contact_lists = relationship("ContactList", secondary=campaign_contact_lists, back_populates="campaigns")
    conversations = relationship("Conversation", back_populates="campaign")
    creator = relationship("User", foreign_keys=[created_by])


# ──────────────── Campaign Attempts ────────────────

class CampaignAttempt(Base):
    """One dial / message attempt against a single contact in a campaign."""
    __tablename__ = "chat_campaign_attempts"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id     = Column(UUID(as_uuid=True), ForeignKey("chat_campaigns.id", ondelete="CASCADE"),  nullable=False)
    contact_id      = Column(UUID(as_uuid=True), ForeignKey("chat_contacts.id",  ondelete="CASCADE"),  nullable=False)
    agent_id        = Column(UUID(as_uuid=True), ForeignKey("chat_users.id",     ondelete="SET NULL"), nullable=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("chat_conversations.id", ondelete="SET NULL"), nullable=True)
    attempt_number  = Column(Integer, default=1)
    status          = Column(_enum(AttemptStatus), default=AttemptStatus.PENDING)
    outcome_code    = Column(String(100))
    notes           = Column(Text)
    # WhatsApp 24-hour free-messaging window flag.
    # True  = last inbound WA message from this contact was within 24 h — agent can send free text.
    # False = window expired — agent MUST use the campaign message_template (HSM).
    # None  = not a WhatsApp campaign.
    wa_window_open  = Column(Boolean, nullable=True)
    dialled_at      = Column(DateTime)
    connected_at    = Column(DateTime)
    ended_at        = Column(DateTime)
    ring_duration   = Column(Integer)   # seconds: dialled_at → answer/no_answer
    handle_duration = Column(Integer)   # seconds: connected_at → ended_at
    # Primary recording URL — points at the merged/full recording (local path or provider URL)
    recording_url   = Column(String(500), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_campaign_attempts_campaign", "campaign_id"),
        Index("ix_campaign_attempts_contact",  "contact_id"),
    )

    campaign     = relationship("Campaign",     foreign_keys=[campaign_id])
    contact      = relationship("Contact",      foreign_keys=[contact_id])
    agent        = relationship("User",         foreign_keys=[agent_id])
    conversation = relationship("Conversation", foreign_keys=[conversation_id])
    recordings   = relationship("CallRecording", back_populates="attempt",
                                cascade="all, delete-orphan",
                                order_by="CallRecording.started_at")


# ──────────────── Call Recordings ────────────────

class CallRecording(Base):
    """One recording segment / leg for a campaign attempt.

    A single call may produce multiple rows — one per leg (outbound contact,
    agent, held segment, IVR, barge, transfer).  The merged/full file is the
    row with leg=MERGED and is also referenced from
    ``CampaignAttempt.recording_url`` for quick access.
    """
    __tablename__ = "chat_call_recordings"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id          = Column(UUID(as_uuid=True),
                                 ForeignKey("chat_campaign_attempts.id", ondelete="CASCADE"),
                                 nullable=False)
    # Context back-references (denormalised for fast supervisor queries)
    campaign_id         = Column(UUID(as_uuid=True), nullable=True)
    agent_id            = Column(UUID(as_uuid=True), nullable=True)
    contact_id          = Column(UUID(as_uuid=True), nullable=True)

    provider            = Column(String(50))          # twilio | vonage | telnyx | …
    leg                 = Column(String(50), default="unknown")  # RecordingLeg value
    status              = Column(String(50), default="pending")   # RecordingStatus value

    # Provider side
    provider_recording_id = Column(String(255))       # Twilio RecordingSid, Vonage uuid, …
    provider_url          = Column(String(500))       # raw CDN / API URL from provider webhook

    # Local storage
    # Relative to BASE_DIR/wizzrecordings/, e.g. "2026/03/15/{attempt_id}/{recording_id}.mp3"
    file_path           = Column(String(500))         # set once downloaded
    file_size_bytes     = Column(Integer)
    mime_type           = Column(String(50), default="audio/mpeg")

    # Timing
    duration_seconds    = Column(Integer)
    started_at          = Column(DateTime)
    ended_at            = Column(DateTime)

    error_message       = Column(Text)                # populated if status=FAILED
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_call_recordings_attempt",  "attempt_id"),
        Index("ix_call_recordings_campaign", "campaign_id"),
        Index("ix_call_recordings_agent",    "agent_id"),
        Index("ix_call_recordings_provider_id", "provider_recording_id"),
    )

    attempt = relationship("CampaignAttempt", back_populates="recordings")


# ──────────────── Global Outcomes ────────────────

class Outcome(Base):
    """System-wide outcome codes agents use to close sessions."""
    __tablename__ = "chat_outcomes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)   # machine key e.g. "resolved"
    label = Column(String(100), nullable=False)                          # display name e.g. "Resolved"
    outcome_type = Column(String(50), default="neutral")                 # positive / negative / neutral / escalation
    action_type = Column(String(30), default="end_interaction")          # end_interaction | flow_redirect
    redirect_flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──────────────── Audit Log ────────────────

class AuditLog(Base):
    __tablename__ = "chat_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100))
    entity_id = Column(UUID(as_uuid=True))
    details = Column(JSONB, default=dict)
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_audit_created", "created_at"),)


# ──────────────── Global Settings ────────────────

class GlobalSettings(Base):
    __tablename__ = "chat_global_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(Text)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──────────────── Custom Node Types ────────────────

class CustomNodeType(Base):
    """User-defined node types that extend the built-in palette."""
    __tablename__ = "chat_custom_node_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(50), unique=True, nullable=False, index=True)      # e.g. "crm_lookup"
    label = Column(String(100), nullable=False)                            # e.g. "CRM Lookup"
    icon = Column(String(100), default="bi-puzzle")                        # Bootstrap icon class
    category = Column(String(50), default="Custom")                        # Palette group header
    color = Column(String(20), default="#6c757d")                          # Node header colour
    has_input = Column(Boolean, default=True)                              # Has input port
    has_output = Column(Boolean, default=True)                             # Has output port (default)
    config_schema = Column(JSONB, default=list)                            # Array of field definitions
    description = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──────────────── Connectors ────────────────────────────────────────────────

class Connector(Base):
    """Connector – links an external channel (chat, voice, WhatsApp…) to a flow."""
    __tablename__ = "chat_connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"))
    allowed_origins = Column(JSONB, default=lambda: ["*"])
    style = Column(JSONB, default=dict)
    meta_fields = Column(JSONB, default=list)  # [{name, label, required, map_to_variable}]
    proactive_triggers = Column(JSONB, default=dict)  # {enabled, triggers:[{type, value, selector, repeat}], nudge:{enabled, message, auto_open, delay_seconds}}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow = relationship("Flow", foreign_keys=[flow_id])
    interactions = relationship("Interaction", back_populates="connector", cascade="all, delete-orphan")


class Interaction(Base):
    """In-progress interaction (chat, voice, WhatsApp…) from a visitor or call."""
    __tablename__ = "chat_interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector_id = Column(UUID(as_uuid=True), ForeignKey("chat_connectors.id", ondelete="CASCADE"), nullable=False)
    session_key = Column(String(128), unique=True, nullable=False, index=True)
    visitor_metadata = Column(JSONB, default=dict)
    flow_context = Column(JSONB, default=dict)
    waiting_node_id = Column(String(128))          # node ID flow is paused at (waiting for input)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="active")  # active | waiting_agent | with_agent | closed
    agent_id = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"))
    message_log = Column(JSONB, default=list)         # [{from, text, ts, subtype}] full transcript
    # Interaction classification — set on create / update when context is known
    contact_id     = Column(UUID(as_uuid=True), ForeignKey("chat_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    direction      = Column(String(10), nullable=True)   # inbound | outbound
    channel        = Column(String(30), nullable=True)   # voice | chat | whatsapp | email | sms
    handling_type  = Column(String(20), nullable=True)   # human | flow | blended | bot_only
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    visitor_last_seen = Column(DateTime, nullable=True)  # NULL = connected; set on SSE disconnect
    disconnect_outcome = Column(String(200), nullable=True)  # outcome to record when auto-closed
    csat_score = Column(Integer, nullable=True)           # 1–5 rating submitted via CSAT sub-flow
    csat_comment = Column(Text, nullable=True)            # optional free-text feedback
    csat_submitted_at = Column(DateTime, nullable=True)  # populated when visitor submits score
    nps_score = Column(Integer, nullable=True)            # 0–10 Net Promoter Score
    nps_reason = Column(Text, nullable=True)              # optional reason text
    nps_submitted_at = Column(DateTime, nullable=True)   # populated when visitor submits NPS
    notes = Column(Text, nullable=True)                  # AI-generated session summary (filled on close)
    wrap_started_at = Column(DateTime, nullable=True)    # when visitor left and wrap-up clock started
    wrap_time = Column(Integer, nullable=True)           # seconds agent spent in wrap-up before submitting outcome
    # Lifecycle segments — one entry per logical phase the session passed through:
    # [{type, started_at, ended_at, summary, agent_id?, queue_id?, flow_id?, waited_seconds?}]
    segments = Column(JSONB, default=list, nullable=True)

    __table_args__ = (
        Index("ix_interactions_status", "status"),
        Index("ix_interactions_contact", "contact_id"),
        Index("ix_interactions_channel", "channel"),
    )

    connector = relationship("Connector", back_populates="interactions")
    agent = relationship("User", foreign_keys=[agent_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
    queue = relationship("Queue", foreign_keys=[queue_id])
    tag_refs = relationship("Tag", secondary="chat_interaction_tags", back_populates="tagged_interactions")
    survey_submissions = relationship("SurveySubmission", back_populates="interaction", cascade="all, delete-orphan")


# ──────────── Email Connector ────────────────────────────────────────────────

class EmailConnector(Base):
    """IMAP/SMTP connector — polls inbound email and routes threads into flows/queues."""
    __tablename__ = "chat_email_connectors"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name             = Column(String(255), nullable=False)
    description      = Column(Text)
    # IMAP inbound
    imap_host        = Column(String(255))
    imap_port        = Column(Integer, default=993)
    imap_username    = Column(String(255))
    imap_password    = Column(String(255))          # store encrypted in production
    imap_use_ssl     = Column(Boolean, default=True)
    imap_folder      = Column(String(100), default="INBOX")
    poll_interval_seconds = Column(Integer, default=60)
    # SMTP outbound
    smtp_host        = Column(String(255))
    smtp_port        = Column(Integer, default=587)
    smtp_username    = Column(String(255))
    smtp_password    = Column(String(255))
    smtp_use_tls     = Column(Boolean, default=True)
    from_address     = Column(String(255))
    from_name        = Column(String(255))
    # Routing
    flow_id          = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"), nullable=True)
    queue_id         = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"), nullable=True)
    is_active        = Column(Boolean, default=True)
    last_poll_at     = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow  = relationship("Flow",  foreign_keys=[flow_id])
    queue = relationship("Queue", foreign_keys=[queue_id])


# ──────────── WhatsApp Connector ─────────────────────────────────────────────

class WhatsAppConnector(Base):
    """WhatsApp Business API connector — supports Meta Cloud API, Twilio, 360dialog and generic webhooks."""
    __tablename__ = "chat_whatsapp_connectors"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name                 = Column(String(255), nullable=False)
    description          = Column(Text)
    provider             = Column(String(50), default="meta_cloud")  # meta_cloud | twilio | 360dialog | vonage | generic
    business_phone_number = Column(String(50))                        # E.164 number customers message
    # Meta Cloud API
    phone_number_id      = Column(String(100))     # Meta: phone number ID
    waba_id              = Column(String(100))     # Meta: WhatsApp Business Account ID
    access_token         = Column(String(512))     # Meta: permanent access token
    verify_token         = Column(String(128))     # Meta: webhook verification token
    # Twilio / generic
    account_sid          = Column(String(100))     # Twilio account SID
    auth_token           = Column(String(100))     # Twilio auth token
    api_key              = Column(String(256))     # Generic API key
    # Routing
    flow_id              = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"), nullable=True)
    queue_id             = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"), nullable=True)
    is_active            = Column(Boolean, default=True)
    created_at           = Column(DateTime, default=datetime.utcnow)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow  = relationship("Flow",  foreign_keys=[flow_id])
    queue = relationship("Queue", foreign_keys=[queue_id])


# ──────────── Voice Connector ─────────────────────────────────────────────────

class VoiceConnector(Base):
    """Telephony / SIP connector — supports Twilio, Vonage, Asterisk ARI and generic SIP webhooks."""
    __tablename__ = "chat_voice_connectors"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name          = Column(String(255), nullable=False)
    description   = Column(Text)
    provider      = Column(String(50), default="generic")  # twilio | vonage | telnyx | africastalking | freeswitch | 3cx | asterisk | generic
    # Provider credentials
    account_sid   = Column(String(100))   # Twilio/Vonage/Telnyx account SID or profile ID; 3CX OAuth client_id; Asterisk/FS ESL username
    auth_token    = Column(String(100))   # Twilio/Telnyx auth token; 3CX OAuth client_secret; Asterisk/FS ESL password
    api_key       = Column(String(256))   # Vonage / Africa's Talking / generic key; Asterisk Stasis app; FreeSWITCH SIP gateway; 3CX agent extension
    api_secret    = Column(String(256))   # Vonage / Telnyx / generic secret; FreeSWITCH outbound caller_id (fallback)
    sip_domain    = Column(String(255))   # SIP domain, trunk address, or PBX host:port
    twiml_app_sid = Column(String(100))   # Twilio TwiML App SID (APxxx) for browser WebRTC agent leg
    caller_id_override = Column(String(50))  # Outbound caller ID override for on-premise PBX providers
    # DID management
    did_numbers   = Column(JSONB, default=list)  # List of E.164 DID numbers for this connector
    # Routing
    flow_id       = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"), nullable=True)
    queue_id      = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"), nullable=True)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow  = relationship("Flow",  foreign_keys=[flow_id])
    queue = relationship("Queue", foreign_keys=[queue_id])


class SmsConnector(Base):
    """SMS gateway connector — supports Twilio, Vonage, Africa's Talking and generic HTTP gateways."""
    __tablename__ = "chat_sms_connectors"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name          = Column(String(255), nullable=False)
    description   = Column(Text)
    provider      = Column(String(50), default="generic")  # twilio | vonage | africastalking | generic
    # Provider credentials
    account_sid   = Column(String(100))   # Twilio account SID
    auth_token    = Column(String(100))   # Twilio auth token / Africa's Talking API key
    api_key       = Column(String(256))   # Vonage / generic key
    api_secret    = Column(String(256))   # Vonage / generic secret
    from_number   = Column(String(50))    # Sender ID or number, e.g. +27821234567 or 'WizzardChat'
    # Routing
    flow_id       = Column(UUID(as_uuid=True), ForeignKey("chat_flows.id", ondelete="SET NULL"), nullable=True)
    queue_id      = Column(UUID(as_uuid=True), ForeignKey("chat_queues.id", ondelete="SET NULL"), nullable=True)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow  = relationship("Flow",  foreign_keys=[flow_id])
    queue = relationship("Queue", foreign_keys=[queue_id])


class SurveySubmission(Base):
    """One row per survey submitted during an interaction.

    `survey_name` is a free string set on the save_survey flow node (e.g. 'csat', 'nps',
    'post_call_feedback').  `responses` is a JSONB object whose keys are the field names
    configured on that node and whose values are the raw strings captured from the visitor.
    """
    __tablename__ = "chat_survey_submissions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interaction_id = Column(UUID(as_uuid=True), ForeignKey("chat_interactions.id", ondelete="CASCADE"), nullable=False, index=True)
    survey_name    = Column(String(120), nullable=False, index=True)   # e.g. 'csat', 'nps', 'onboarding'
    responses      = Column(JSONB, default=dict)                        # {"score": "4", "comment": "Great!"}
    submitted_at   = Column(DateTime, default=datetime.utcnow)

    interaction = relationship("Interaction", back_populates="survey_submissions")


# ──────────────── Tags ────────────────

class Tag(Base):
    """Managed tags that can be applied to interactions, contacts, or users."""
    __tablename__ = "chat_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, index=True)  # lowercase dash-separated for lookups
    tag_type = Column(_enum(TagType), nullable=False, index=True)
    color = Column(String(20), default="#6c757d")
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("slug", "tag_type", name="uq_tag_slug_type"),)

    tagged_interactions = relationship("Interaction", secondary="chat_interaction_tags", back_populates="tag_refs")
    tagged_contacts = relationship("Contact", secondary="chat_contact_tags", back_populates="tag_refs")
    tagged_users = relationship("User", secondary="chat_user_tags", back_populates="tag_refs")


# ──────────────── Office Hours ────────────────

class OfficeHoursGroup(Base):
    """A named set of operating hours (e.g. 'Main Office', 'After-Hours Support')."""
    __tablename__ = "chat_office_hours_groups"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String(120), nullable=False, unique=True)
    description = Column(Text)
    timezone    = Column(String(60), default="Africa/Johannesburg")
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    schedule   = relationship("OfficeHoursSchedule", back_populates="group",
                              cascade="all, delete-orphan", order_by="OfficeHoursSchedule.day_of_week")
    exclusions = relationship("OfficeHoursExclusion", back_populates="group",
                              cascade="all, delete-orphan", order_by="OfficeHoursExclusion.date")


class OfficeHoursSchedule(Base):
    """Weekly schedule entry: one row per day-of-week per group.

    day_of_week: 0 = Monday … 6 = Sunday
    open_time / close_time stored as 'HH:MM' strings (local time per group timezone).
    """
    __tablename__ = "chat_office_hours_schedule"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id     = Column(UUID(as_uuid=True), ForeignKey("chat_office_hours_groups.id", ondelete="CASCADE"), nullable=False)
    day_of_week  = Column(Integer, nullable=False)   # 0=Mon, 6=Sun
    is_open      = Column(Boolean, default=True)
    open_time    = Column(String(5), default="08:00")  # HH:MM
    close_time   = Column(String(5), default="17:00")  # HH:MM

    __table_args__ = (UniqueConstraint("group_id", "day_of_week", name="uq_oh_schedule_group_day"),)

    group = relationship("OfficeHoursGroup", back_populates="schedule")


class OfficeHoursExclusion(Base):
    """Date-specific override that replaces the weekly schedule for that day.

    Examples: public holidays, shutdown days, extended hours for events.
    If is_open=False the business is closed all day regardless of schedule.
    If is_open=True the override_open / override_close times are used instead.
    """
    __tablename__ = "chat_office_hours_exclusions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id       = Column(UUID(as_uuid=True), ForeignKey("chat_office_hours_groups.id", ondelete="CASCADE"), nullable=False)
    date           = Column(Date, nullable=False)          # e.g. 2026-01-01
    label          = Column(String(120))                   # e.g. "New Year's Day"
    is_open        = Column(Boolean, default=False)        # False = closed all day
    override_open  = Column(String(5))                     # HH:MM if is_open=True
    override_close = Column(String(5))                     # HH:MM if is_open=True
    created_at     = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("group_id", "date", name="uq_oh_exclusion_group_date"),)

    group = relationship("OfficeHoursGroup", back_populates="exclusions")


# ──────────────── Message Templates ────────────────

class MessageTemplate(Base):
    """Reusable outbound-message templates for WhatsApp (HSM), SMS, and Email.

    Variables are referenced as ``{{1}}``, ``{{2}}`` etc. in the body text
    (matching WhatsApp HSM convention).  The ``variables`` JSONB column maps
    each positional variable to a label and, optionally, a Contact field name
    so the dialler can auto-fill them from the contact record.

    Example variables list::

        [{"pos": 1, "label": "First name", "contact_field": "first_name"},
         {"pos": 2, "label": "Renewal date", "contact_field": null}]
    """
    __tablename__ = "chat_message_templates"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name            = Column(String(255), nullable=False)
    channel         = Column(String(20),  nullable=False)   # whatsapp | sms | email
    # Approval / lifecycle
    status          = Column(String(20), default="active")  # active | draft | archived
    # WhatsApp-specific
    wa_template_name    = Column(String(255))   # approved name on Meta / WhatsApp Business
    wa_language         = Column(String(10), default="en")
    wa_approval_status  = Column(String(20), default="pending")  # approved | pending | rejected
    wa_category         = Column(String(50))    # MARKETING | UTILITY | AUTHENTICATION
    # Content
    subject         = Column(String(500))   # email subject line only
    body            = Column(Text, nullable=False)
    # Variable mapping — list of {pos, label, contact_field, default}
    variables       = Column(JSONB, default=list)
    # Email extras
    from_name       = Column(String(100))
    reply_to        = Column(String(255))
    # Metadata
    created_by      = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])


# ──────────────── Routines / Outbound Webhook ────────────────────────────────

class WebhookSubscription(Base):
    """Register an external URL to receive events from WizzardChat (Routines).

    ``event_topics``  — list of topic strings e.g. ``["conversation.closed"]``
    ``filter_expr``   — optional JSON condition tree (see event_dispatcher docs)
    ``payload_template`` — optional dict with ``${path}`` tokens; None = send full event
    ``secret``        — HMAC-SHA256 signing secret; None = unsigned
    """
    __tablename__ = "chat_webhook_subscriptions"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name             = Column(String(255), nullable=False)
    description      = Column(Text)

    # Target
    url              = Column(String(2000), nullable=False)
    http_method      = Column(String(8),  default="POST")    # POST | GET
    custom_headers   = Column(JSONB,      default=dict)

    # Trigger
    event_topics     = Column(JSONB,      nullable=False)    # ["conversation.closed", ...]
    filter_expr      = Column(JSONB,      default=None)      # Condition tree or None

    # Payload
    payload_template = Column(JSONB,      default=None)      # None = full event dict

    # Security
    secret           = Column(String(255), nullable=True)

    # Reliability
    enabled          = Column(Boolean,    default=True)
    retry_max        = Column(Integer,    default=3)
    timeout_seconds  = Column(Integer,    default=10)

    # Audit
    created_by       = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deliveries = relationship("WebhookDelivery", back_populates="subscription",
                              cascade="all, delete-orphan", passive_deletes=True)
    creator    = relationship("User", foreign_keys=[created_by])


class WebhookDelivery(Base):
    """Records every dispatch attempt for a WebhookSubscription event."""
    __tablename__ = "chat_webhook_deliveries"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id = Column(UUID(as_uuid=True),
                             ForeignKey("chat_webhook_subscriptions.id", ondelete="CASCADE"),
                             nullable=False)
    event_id        = Column(String(100))   # unique ID per event occurrence
    event_topic     = Column(String(100))
    payload         = Column(JSONB)         # resolved payload sent

    # State: queued | dispatching | delivered | failed | abandoned
    status          = Column(String(30), default="queued")
    attempts        = Column(Integer,    default=0)
    max_attempts    = Column(Integer,    default=3)
    next_retry_at   = Column(DateTime,   nullable=True)

    # Last attempt result
    response_code   = Column(Integer,  nullable=True)
    response_body   = Column(Text,     nullable=True)
    duration_ms     = Column(Integer,  nullable=True)

    queued_at        = Column(DateTime, default=datetime.utcnow)
    last_attempt_at  = Column(DateTime, nullable=True)
    delivered_at     = Column(DateTime, nullable=True)

    subscription = relationship("WebhookSubscription", back_populates="deliveries")

    __table_args__ = (
        Index("ix_wh_delivery_sub",        "subscription_id"),
        Index("ix_wh_delivery_status",     "status"),
        Index("ix_wh_delivery_next_retry", "next_retry_at"),
    )


class RoutineSchedule(Base):
    """Time-based event emitter.  Fires ``routine.tick`` at the configured cron interval.

    ``cron_expression`` — standard 5-field cron (minute, hour, dom, month, dow)
    ``timezone``        — IANA tz string (default Africa/Johannesburg)
    ``custom_data``     — arbitrary dict included in the ``routine.tick`` payload
    """
    __tablename__ = "chat_routine_schedules"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name            = Column(String(255), nullable=False)
    description     = Column(Text)
    cron_expression = Column(String(100), nullable=False)
    timezone        = Column(String(50),  default="Africa/Johannesburg")
    custom_data     = Column(JSONB,       default=dict)
    enabled         = Column(Boolean,     default=True)
    last_run_at     = Column(DateTime,    nullable=True)
    next_run_at     = Column(DateTime,    nullable=True)

    created_by      = Column(UUID(as_uuid=True), ForeignKey("chat_users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])


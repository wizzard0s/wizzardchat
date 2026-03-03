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
    "team_members",
    Base.metadata,
    Column("team_id", UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

queue_agents = Table(
    "queue_agents",
    Base.metadata,
    Column("queue_id", UUID(as_uuid=True), ForeignKey("queues.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

user_skills = Table(
    "user_skills",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
    Column("proficiency", Integer, default=100),  # 0-100
)

campaign_contact_lists = Table(
    "campaign_contact_lists",
    Base.metadata,
    Column("campaign_id", UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("contact_list_id", UUID(as_uuid=True), ForeignKey("contact_lists.id", ondelete="CASCADE"), primary_key=True),
)

interaction_tags = Table(
    "interaction_tags",
    Base.metadata,
    Column("interaction_id", UUID(as_uuid=True), ForeignKey("interactions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

contact_tags = Table(
    "contact_tags",
    Base.metadata,
    Column("contact_id", UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

user_tags = Table(
    "user_tags",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


# ──────────────────────────── Models ────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.AGENT)
    is_active = Column(Boolean, default=True)
    is_online = Column(Boolean, default=False)
    is_system_account = Column(Boolean, default=False, nullable=False)
    auth_type = Column(SAEnum(AuthType), nullable=False, default=AuthType.LOCAL)
    max_concurrent_chats = Column(Integer, default=5)
    avatar_url = Column(String(500))
    phone_number = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    teams = relationship("Team", secondary=team_members, back_populates="members")
    queues = relationship("Queue", secondary=queue_agents, back_populates="agents")
    conversations = relationship("Conversation", back_populates="agent", foreign_keys="Conversation.agent_id")
    skills = relationship("Skill", secondary=user_skills, back_populates="users")
    tag_refs = relationship("Tag", secondary="user_tags", back_populates="tagged_users")


class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    leader_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    leader = relationship("User", foreign_keys=[leader_id])
    members = relationship("User", secondary=team_members, back_populates="teams")


class CustomRole(Base):
    """User-manageable roles with granular permissions."""
    __tablename__ = "custom_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)  # True = seeded, not deletable
    permissions = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Skill(Base):
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", secondary=user_skills, back_populates="skills")


class Queue(Base):
    __tablename__ = "queues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    channel = Column(SAEnum(ChannelType), nullable=False)
    strategy = Column(SAEnum(QueueStrategy), default=QueueStrategy.ROUND_ROBIN)
    priority = Column(Integer, default=0)
    max_wait_time = Column(Integer, default=300)  # seconds
    sla_threshold = Column(Integer, default=30)  # seconds
    color = Column(String(20), default="#fd7e14")
    outcomes = Column(JSONB, default=list)  # [{key, label, description}]
    is_active = Column(Boolean, default=True)
    overflow_queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"))
    flow_id = Column(UUID(as_uuid=True), ForeignKey("flows.id", ondelete="SET NULL"))
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    agents = relationship("User", secondary=queue_agents, back_populates="queues")
    overflow_queue = relationship("Queue", remote_side="Queue.id")
    flow = relationship("Flow", foreign_keys=[flow_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
    conversations = relationship("Conversation", back_populates="queue")


# ──────────────── Contacts & Lists ────────────────

class Contact(Base):
    __tablename__ = "contacts"

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
    status = Column(SAEnum(ContactStatus), default=ContactStatus.ACTIVE)
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
    tag_refs = relationship("Tag", secondary="contact_tags", back_populates="tagged_contacts")


class ContactList(Base):
    __tablename__ = "contact_lists"

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
    __tablename__ = "contact_list_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_list_id = Column(UUID(as_uuid=True), ForeignKey("contact_lists.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contact_list_id", "contact_id"),)

    contact_list = relationship("ContactList", back_populates="members")
    contact = relationship("Contact", back_populates="list_memberships")


# ──────────────── Flows (IVR / Bot / Routing) ────────────────

class Flow(Base):
    __tablename__ = "flows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    channel = Column(SAEnum(ChannelType))
    flow_type = Column(SAEnum(FlowType), nullable=False, default=FlowType.MAIN_FLOW)
    status = Column(SAEnum(FlowStatus), nullable=False, default=FlowStatus.DRAFT)
    is_active = Column(Boolean, default=False)
    is_published = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    nodes = relationship("FlowNode", back_populates="flow", cascade="all, delete-orphan", order_by="FlowNode.position")
    edges = relationship("FlowEdge", back_populates="flow", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])


class FlowNode(Base):
    __tablename__ = "flow_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
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
    __tablename__ = "flow_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    source_node_id = Column(UUID(as_uuid=True), ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False)
    target_node_id = Column(UUID(as_uuid=True), ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False)
    source_handle = Column(String(50), default="default")  # which output port
    label = Column(String(255), default="")
    condition = Column(JSONB)  # Condition to traverse this edge
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_flow_edges_flow_id", "flow_id"),)

    flow = relationship("Flow", back_populates="edges")
    source_node = relationship("FlowNode", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node = relationship("FlowNode", foreign_keys=[target_node_id], back_populates="incoming_edges")


# ──────────────── Conversations ────────────────

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(SAEnum(ChannelType), nullable=False)
    status = Column(SAEnum(ConversationStatus), default=ConversationStatus.WAITING)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"))
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"))
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"))
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
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
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
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    campaign_type = Column(SAEnum(CampaignType), nullable=False)
    status = Column(SAEnum(CampaignStatus), default=CampaignStatus.DRAFT)
    is_active = Column(Boolean, default=True)
    color = Column(String(20), default="#0d6efd")
    campaign_time = Column(JSONB, default=lambda: {"start": "08:00", "end": "17:00"})  # daily hours
    options = Column(JSONB, default=lambda: {"allow_transfer": True, "allow_callback": False})  # feature flags
    outcomes = Column(JSONB, default=list)  # [{key, label, description}]
    queues = Column(JSONB, default=list)    # list of Queue UUIDs assigned to this campaign
    agents = Column(JSONB, default=list)    # list of User UUIDs assigned to work this campaign
    queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"))
    flow_id = Column(UUID(as_uuid=True), ForeignKey("flows.id", ondelete="SET NULL"))
    scheduled_start = Column(DateTime)
    scheduled_end = Column(DateTime)
    max_attempts = Column(Integer, default=3)
    retry_interval = Column(Integer, default=3600)  # seconds
    caller_id = Column(String(50))
    message_template = Column(Text)
    settings = Column(JSONB, default=dict)
    stats = Column(JSONB, default=dict)  # {total, attempted, connected, completed, failed}
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    queue = relationship("Queue", foreign_keys=[queue_id])
    flow = relationship("Flow", foreign_keys=[flow_id])
    contact_lists = relationship("ContactList", secondary=campaign_contact_lists, back_populates="campaigns")
    conversations = relationship("Conversation", back_populates="campaign")
    creator = relationship("User", foreign_keys=[created_by])


# ──────────────── Global Outcomes ────────────────

class Outcome(Base):
    """System-wide outcome codes agents use to close sessions."""
    __tablename__ = "outcomes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)   # machine key e.g. "resolved"
    label = Column(String(100), nullable=False)                          # display name e.g. "Resolved"
    outcome_type = Column(String(50), default="neutral")                 # positive / negative / neutral / escalation
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──────────────── Audit Log ────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100))
    entity_id = Column(UUID(as_uuid=True))
    details = Column(JSONB, default=dict)
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_audit_created", "created_at"),)


# ──────────────── Global Settings ────────────────

class GlobalSettings(Base):
    __tablename__ = "global_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(Text)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──────────────── Custom Node Types ────────────────

class CustomNodeType(Base):
    """User-defined node types that extend the built-in palette."""
    __tablename__ = "custom_node_types"

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
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──────────────── Connectors ────────────────────────────────────────────────

class Connector(Base):
    """Connector – links an external channel (chat, voice, WhatsApp…) to a flow."""
    __tablename__ = "connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("flows.id", ondelete="SET NULL"))
    allowed_origins = Column(JSONB, default=lambda: ["*"])
    style = Column(JSONB, default=dict)
    meta_fields = Column(JSONB, default=list)  # [{name, label, required, map_to_variable}]
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow = relationship("Flow", foreign_keys=[flow_id])
    interactions = relationship("Interaction", back_populates="connector", cascade="all, delete-orphan")


class Interaction(Base):
    """In-progress interaction (chat, voice, WhatsApp…) from a visitor or call."""
    __tablename__ = "interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector_id = Column(UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    session_key = Column(String(128), unique=True, nullable=False, index=True)
    visitor_metadata = Column(JSONB, default=dict)
    flow_context = Column(JSONB, default=dict)
    waiting_node_id = Column(String(128))          # node ID flow is paused at (waiting for input)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="active")  # active | waiting_agent | with_agent | closed
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    message_log = Column(JSONB, default=list)         # [{from, text, ts, subtype}] full transcript
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_interactions_status", "status"),)

    connector = relationship("Connector", back_populates="interactions")
    agent = relationship("User", foreign_keys=[agent_id])
    queue = relationship("Queue", foreign_keys=[queue_id])
    tag_refs = relationship("Tag", secondary="interaction_tags", back_populates="tagged_interactions")


# ──────────────── Tags ────────────────

class Tag(Base):
    """Managed tags that can be applied to interactions, contacts, or users."""
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, index=True)  # lowercase dash-separated for lookups
    tag_type = Column(SAEnum(TagType), nullable=False, index=True)
    color = Column(String(20), default="#6c757d")
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("slug", "tag_type", name="uq_tag_slug_type"),)

    tagged_interactions = relationship("Interaction", secondary="interaction_tags", back_populates="tag_refs")
    tagged_contacts = relationship("Contact", secondary="contact_tags", back_populates="tag_refs")
    tagged_users = relationship("User", secondary="user_tags", back_populates="tag_refs")


# ──────────────── Office Hours ────────────────

class OfficeHoursGroup(Base):
    """A named set of operating hours (e.g. 'Main Office', 'After-Hours Support')."""
    __tablename__ = "office_hours_groups"

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
    __tablename__ = "office_hours_schedule"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id     = Column(UUID(as_uuid=True), ForeignKey("office_hours_groups.id", ondelete="CASCADE"), nullable=False)
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
    __tablename__ = "office_hours_exclusions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id       = Column(UUID(as_uuid=True), ForeignKey("office_hours_groups.id", ondelete="CASCADE"), nullable=False)
    date           = Column(Date, nullable=False)          # e.g. 2026-01-01
    label          = Column(String(120))                   # e.g. "New Year's Day"
    is_open        = Column(Boolean, default=False)        # False = closed all day
    override_open  = Column(String(5))                     # HH:MM if is_open=True
    override_close = Column(String(5))                     # HH:MM if is_open=True
    created_at     = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("group_id", "date", name="uq_oh_exclusion_group_date"),)

    group = relationship("OfficeHoursGroup", back_populates="exclusions")

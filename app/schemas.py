"""Pydantic schemas for request/response validation."""

from datetime import datetime, date
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from app.models import (
    ChannelType, UserRole, QueueStrategy, ConversationStatus,
    CampaignStatus, CampaignType, ContactStatus, AuthType,
    FlowType, FlowStatus, TagType, AttemptStatus,
    RecordingStatus, RecordingLeg,
)


# ──────────────── Auth ────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


# ──────────────── User ────────────────

class UserCreate(BaseModel):
    email: str
    username: str
    password: str
    full_name: str
    role: UserRole = UserRole.AGENT
    max_concurrent_chats: int = 5
    omni_max: Optional[int] = None
    channel_max_voice: Optional[int] = None
    channel_max_chat: Optional[int] = None
    channel_max_whatsapp: Optional[int] = None
    channel_max_email: Optional[int] = None
    channel_max_sms: Optional[int] = None
    phone_number: Optional[str] = None
    auth_type: AuthType = AuthType.LOCAL
    languages: List[str] = []


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    max_concurrent_chats: Optional[int] = None
    omni_max: Optional[int] = None
    channel_max_voice: Optional[int] = None
    channel_max_chat: Optional[int] = None
    channel_max_whatsapp: Optional[int] = None
    channel_max_email: Optional[int] = None
    channel_max_sms: Optional[int] = None
    phone_number: Optional[str] = None
    auth_type: Optional[AuthType] = None
    password: Optional[str] = None
    languages: Optional[List[str]] = None


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    is_online: bool
    max_concurrent_chats: int
    omni_max: Optional[int] = None
    channel_max_voice: Optional[int] = None
    channel_max_chat: Optional[int] = None
    channel_max_whatsapp: Optional[int] = None
    channel_max_email: Optional[int] = None
    channel_max_sms: Optional[int] = None
    capacity_override_active: bool = False
    phone_number: Optional[str]
    auth_type: AuthType
    languages: List[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Team ────────────────

class UserMini(BaseModel):
    id: UUID
    full_name: str
    username: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}


class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None
    leader_id: Optional[UUID] = None
    is_active: bool = True


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    leader_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class TeamOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    leader_id: Optional[UUID]
    is_active: bool
    created_at: datetime
    members: List[UserMini] = []

    model_config = {"from_attributes": True}


# ──────────────── AgentGroup ────────────────

class AgentGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = "#6c757d"
    is_active: bool = True


class AgentGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class AgentGroupOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    color: str
    is_active: bool
    created_at: datetime
    members: List[UserMini] = []

    model_config = {"from_attributes": True}


# ──────────────── CustomRole ────────────────

# All permission keys understood by the system
ALL_PERMISSIONS: List[str] = [
    # Dashboard
    "dashboard.view",
    # Flows
    "flows.view", "flows.create", "flows.edit", "flows.delete",
    # Queues
    "queues.view", "queues.create", "queues.edit", "queues.delete",
    # Campaigns
    "campaigns.view", "campaigns.create", "campaigns.edit", "campaigns.delete",
    # Contacts
    "contacts.view", "contacts.create", "contacts.edit", "contacts.delete",
    # Contact Lists (managed separately — agents can add to lists but not create/import them)
    "contact_lists.view", "contact_lists.create", "contact_lists.edit", "contact_lists.delete", "contact_lists.import",
    # Tags
    "tags.view", "tags.create", "tags.edit", "tags.delete",
    # Office Hours
    "office_hours.view", "office_hours.create", "office_hours.edit", "office_hours.delete",
    # Connectors
    "connectors.view", "connectors.create", "connectors.edit", "connectors.delete",
    # Teams
    "teams.view", "teams.create", "teams.edit", "teams.delete",
    # Users
    "users.view", "users.create", "users.edit", "users.delete",
    # Outcomes
    "outcomes.view", "outcomes.create", "outcomes.edit", "outcomes.delete",
    # Roles
    "roles.view", "roles.create", "roles.edit", "roles.delete",
    # Reports
    "reports.view",
    # Agent panel
    "agent_panel.access",
    # System
    "system.settings",
]


# ──────────────── Tags ────────────────

class TagCreate(BaseModel):
    name: str
    tag_type: TagType
    color: str = "#6c757d"
    description: Optional[str] = None
    is_active: bool = True


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TagOut(BaseModel):
    id: UUID
    name: str
    slug: str
    tag_type: TagType
    color: str
    description: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: Dict[str, bool] = {}


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[Dict[str, bool]] = None


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    is_system: bool
    permissions: Dict[str, bool]
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Queue ────────────────

class QueueCreate(BaseModel):
    name: str
    description: Optional[str] = None
    channel: ChannelType
    strategy: QueueStrategy = QueueStrategy.ROUND_ROBIN
    priority: int = 0
    max_wait_time: int = 300
    sla_threshold: int = 30
    disconnect_timeout_seconds: Optional[int] = None
    disconnect_outcome_id: Optional[UUID] = None
    color: str = "#fd7e14"
    outcomes: List[str] = []  # list of global Outcome IDs
    is_active: bool = True
    overflow_queue_id: Optional[UUID] = None
    flow_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None


class QueueOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    channel: ChannelType
    strategy: QueueStrategy
    priority: int
    max_wait_time: int
    sla_threshold: int
    disconnect_timeout_seconds: Optional[int] = None
    disconnect_outcome_id: Optional[UUID] = None
    color: str = "#fd7e14"
    outcomes: List[Any] = []  # list of global Outcome IDs
    is_active: bool
    overflow_queue_id: Optional[UUID]
    flow_id: Optional[UUID]
    campaign_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Contact ────────────────

class ContactCreate(BaseModel):
    # Identity
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    # Channels
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_id: Optional[str] = None
    # Address
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    # Demographics
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    language: Optional[str] = "en"
    # Classification
    source: Optional[str] = None
    tags: List[str] = []
    custom_fields: Dict[str, Any] = {}
    notes: Optional[str] = None


class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_id: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    language: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class ContactListRef(BaseModel):
    id: UUID
    name: str
    model_config = {"from_attributes": True}


class ContactOut(BaseModel):
    id: UUID
    first_name: Optional[str]
    last_name: Optional[str]
    title: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    whatsapp_id: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    language: Optional[str] = None
    source: Optional[str] = None
    status: Optional[ContactStatus] = ContactStatus.ACTIVE
    tags: Any
    custom_fields: Any
    notes: Optional[str] = None
    created_at: datetime
    lists: List[ContactListRef] = []

    model_config = {"from_attributes": True}


# ──────────────── Contact List ────────────────

class ContactListCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = "#0d6efd"
    is_dynamic: bool = False
    filter_criteria: Optional[Dict[str, Any]] = None


class ContactListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


class ContactListOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    color: Optional[str] = "#0d6efd"
    is_dynamic: bool
    filter_criteria: Optional[Any]
    member_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Flow ────────────────

class FlowNodeCreate(BaseModel):
    node_type: str  # built-in key (e.g. "start") or custom key
    label: str = ""
    position_x: float = 0
    position_y: float = 0
    position: int = 0
    config: Dict[str, Any] = {}


class FlowNodeUpdate(BaseModel):
    label: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    position: Optional[int] = None
    config: Optional[Dict[str, Any]] = None


class FlowNodeOut(BaseModel):
    id: UUID
    flow_id: UUID
    node_type: str
    label: str
    position_x: float
    position_y: float
    position: int
    config: Any
    created_at: datetime

    model_config = {"from_attributes": True}


class FlowEdgeCreate(BaseModel):
    source_node_id: UUID
    target_node_id: UUID
    source_handle: str = "default"
    label: str = ""
    condition: Optional[Dict[str, Any]] = None
    priority: int = 0


class FlowEdgeOut(BaseModel):
    id: UUID
    flow_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    source_handle: str
    label: str
    condition: Optional[Any]
    priority: int
    created_at: datetime

    model_config = {"from_attributes": True}


class FlowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    channel: Optional[ChannelType] = None
    flow_type: FlowType = FlowType.MAIN_FLOW


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[ChannelType] = None
    flow_type: Optional[FlowType] = None
    status: Optional[FlowStatus] = None
    is_active: Optional[bool] = None
    disconnect_timeout_seconds: Optional[int] = None
    disconnect_outcome_id: Optional[UUID] = None


class FlowOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    channel: Optional[ChannelType]
    flow_type: FlowType
    status: FlowStatus
    is_active: bool
    is_published: bool
    published_version: Optional[str] = None
    disconnect_timeout_seconds: Optional[int] = None
    disconnect_outcome_id: Optional[UUID] = None
    version: str
    is_restored: bool = False
    restored_from_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FlowDetail(FlowOut):
    nodes: List[FlowNodeOut] = []
    edges: List[FlowEdgeOut] = []


# Edge reference used by the designer (accepts temp ids like "temp_1")
class DesignerEdgeRef(BaseModel):
    source_node_id: str
    target_node_id: str
    source_handle: str = "default"
    label: str = ""
    condition: Optional[Dict[str, Any]] = None
    priority: int = 0


# Full flow save (from designer)
class FlowDesignerSave(BaseModel):
    """Complete flow state pushed from the visual designer."""
    name: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[ChannelType] = None
    nodes: List[FlowNodeCreate] = []
    edges: List[DesignerEdgeRef] = []


# ──────────────── Campaign ────────────────

class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    campaign_type: CampaignType = CampaignType.OUTBOUND_VOICE
    color: str = "#0d6efd"
    campaign_time: Dict[str, Any] = {"start": "08:00", "end": "17:00"}
    options: Dict[str, Any] = {"allow_transfer": True, "allow_callback": False}
    outcomes: List[str] = []  # list of global Outcome IDs
    queues: List[str] = []    # list of Queue IDs
    agents: List[str] = []         # individual User IDs (overrides / additions)
    agent_groups: List[str] = []    # list of AgentGroup IDs assigned to this campaign
    is_active: bool = True
    queue_id: Optional[UUID] = None
    flow_id: Optional[UUID] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    max_attempts: int = 3
    retry_interval: int = 3600
    caller_id: Optional[str] = None
    message_template: Optional[str] = None
    # Voice-specific
    voice_connector_id: Optional[UUID] = None     # stored in settings["voice_connector_id"]
    dialler_mode: Optional[str] = "preview"       # preview | progressive  (stored in settings)
    # SA CPA/ECTA calling-hours window (SAST)
    # Defaults enforce the legal minimum: Mon-Fri 08:00-20:00, Sat 08:00-13:00, no Sun/PH
    calling_hours: Optional[Dict[str, Any]] = None  # stored in settings["calling_hours"]
    settings: Dict[str, Any] = {}


class CampaignOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    campaign_type: CampaignType
    status: CampaignStatus
    is_active: bool = True
    color: str = "#0d6efd"
    campaign_time: Dict[str, Any] = {}
    options: Dict[str, Any] = {}
    outcomes: List[Any] = []  # list of global Outcome IDs
    queues: List[Any] = []    # list of Queue IDs
    agents: List[Any] = []         # individual User IDs (overrides / additions)
    agent_groups: List[Any] = []    # list of AgentGroup IDs assigned to this campaign
    queue_id: Optional[UUID]
    flow_id: Optional[UUID]
    scheduled_start: Optional[datetime]
    scheduled_end: Optional[datetime]
    max_attempts: int = 3
    retry_interval: int = 3600
    message_template: Optional[str] = None
    settings: Dict[str, Any] = {}
    outbound_config: Dict[str, Any] = {}
    stats: Any
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Campaign Attempt / Dialler ────────────────

class CampaignAttemptCreate(BaseModel):
    contact_id: UUID
    agent_id: Optional[UUID] = None


class CampaignAttemptUpdate(BaseModel):
    status:          Optional[AttemptStatus] = None
    outcome_code:    Optional[str] = None
    notes:           Optional[str] = None
    connected_at:    Optional[datetime] = None
    ended_at:        Optional[datetime] = None
    ring_duration:   Optional[int] = None
    handle_duration: Optional[int] = None


class CallRecordingOut(BaseModel):
    id:                     UUID
    attempt_id:             UUID
    campaign_id:            Optional[UUID]
    agent_id:               Optional[UUID]
    contact_id:             Optional[UUID]
    provider:               Optional[str]
    leg:                    str = "unknown"
    status:                 str = "pending"
    provider_recording_id:  Optional[str]
    provider_url:           Optional[str]
    file_path:              Optional[str]
    file_size_bytes:        Optional[int]
    mime_type:              Optional[str]
    duration_seconds:       Optional[int]
    started_at:             Optional[datetime]
    ended_at:               Optional[datetime]
    # Derived — full playback URL served by the recordings router
    playback_url:           Optional[str] = None
    created_at:             datetime

    model_config = {"from_attributes": True}


class CampaignAttemptOut(BaseModel):
    id:              UUID
    campaign_id:     UUID
    contact_id:      UUID
    agent_id:        Optional[UUID]
    conversation_id: Optional[UUID]
    attempt_number:  int
    status:          AttemptStatus
    outcome_code:    Optional[str]
    notes:           Optional[str]
    wa_window_open:  Optional[bool]  # None = not WA campaign
    dialled_at:      Optional[datetime]
    connected_at:    Optional[datetime]
    ended_at:        Optional[datetime]
    ring_duration:   Optional[int]
    handle_duration: Optional[int]
    recording_url:   Optional[str]
    recordings:      List["CallRecordingOut"] = []
    created_at:      datetime

    model_config = {"from_attributes": True}


class ContactDiallerOut(BaseModel):
    """Contact data used by the dialler view — includes all outbound channel endpoints
    and opt-out flags so the UI can show the multi-channel action buttons correctly."""
    id:           UUID
    first_name:   Optional[str]
    last_name:    Optional[str]
    company:      Optional[str]
    phone:        Optional[str]
    whatsapp_id:  Optional[str]
    email:        Optional[str]
    language:     Optional[str]
    notes:        Optional[str]
    custom_fields: Any = {}
    # Opt-out / DNC flags
    do_not_call:     bool = False
    do_not_whatsapp: bool = False
    do_not_sms:      bool = False
    do_not_email:    bool = False
    # Tags for display
    tags: Any = []

    model_config = {"from_attributes": True}


class ContactHistoryItem(BaseModel):
    """One interaction record from the cross-campaign 30-day history panel."""
    id:              UUID
    campaign_id:     UUID
    campaign_name:   str
    channel:         str         # voice | whatsapp | sms | email
    direction:       Optional[str]  # inbound | outbound
    status:          str         # AttemptStatus value
    outcome_code:    Optional[str]
    notes:           Optional[str]
    dialled_at:      Optional[datetime]
    ended_at:        Optional[datetime]
    handle_duration: Optional[int]
    created_at:      datetime

    model_config = {"from_attributes": True}


class DiallerNextOut(BaseModel):
    contact:            Optional[ContactDiallerOut]
    attempt:            Optional[CampaignAttemptOut]
    template_required:  bool = False
    message_template:   Optional[str] = None
    # Resolved template info for the active channel
    active_channel:     Optional[str] = None   # voice|whatsapp|sms|email
    template_id:        Optional[str] = None   # MessageTemplate.id if applicable
    template_variables: List[Any] = []         # [{pos, label, contact_field, resolved_value}]
    # Campaign fallback config
    outbound_config:    Dict[str, Any] = {}
    total_contacts:     int = 0
    attempted_contacts: int = 0
    completed_contacts: int = 0
    remaining_contacts: int = 0
    campaign_exhausted: bool = False

    model_config = {"from_attributes": True}


# Fix forward ref
TokenResponse.model_rebuild()


# ──────────────── Message Templates ────────────────

class TemplateVariableMap(BaseModel):
    """Maps one positional variable slot to a label and optional Contact field."""
    pos:           int
    label:         str                 # human-readable description, e.g. "First name"
    contact_field: Optional[str] = None  # Contact column name, e.g. "first_name"
    default:       Optional[str] = None  # fallback if no contact data


class MessageTemplateCreate(BaseModel):
    name:               str
    channel:            str  # whatsapp | sms | email
    body:               str
    status:             str = "active"
    subject:            Optional[str] = None   # email only
    variables:          List[TemplateVariableMap] = []
    wa_template_name:   Optional[str] = None
    wa_language:        Optional[str] = "en"
    wa_approval_status: Optional[str] = "pending"
    wa_category:        Optional[str] = None
    from_name:          Optional[str] = None   # email only
    reply_to:           Optional[str] = None   # email only


class MessageTemplateOut(BaseModel):
    id:                 UUID
    name:               str
    channel:            str
    status:             str
    body:               str
    subject:            Optional[str]
    variables:          List[Any] = []
    wa_template_name:   Optional[str]
    wa_language:        Optional[str]
    wa_approval_status: Optional[str]
    wa_category:        Optional[str]
    from_name:          Optional[str]
    reply_to:           Optional[str]
    created_at:         datetime
    updated_at:         datetime

    model_config = {"from_attributes": True}


# ──────────────── Global Settings ────────────────

class GlobalSettingOut(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GlobalSettingUpdate(BaseModel):
    value: str


# ──────────────── Custom Node Type ────────────────

class CustomNodeTypeCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    label: str = Field(..., min_length=1, max_length=100)
    icon: str = "bi-puzzle"
    category: str = "Custom"
    color: str = "#6c757d"
    has_input: bool = True
    has_output: bool = True
    config_schema: List[Dict[str, Any]] = []
    description: Optional[str] = None


class CustomNodeTypeUpdate(BaseModel):
    label: Optional[str] = None
    icon: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    has_input: Optional[bool] = None
    has_output: Optional[bool] = None
    config_schema: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None


class NodeTypeOut(BaseModel):
    """Unified output for both built-in and custom node types."""
    key: str
    label: str
    icon: str
    category: str
    color: str
    has_input: bool
    has_output: bool
    is_builtin: bool = True
    config_schema: List[Dict[str, Any]] = []
    description: Optional[str] = None
    id: Optional[UUID] = None  # Only present for custom types


# ──────────────── Flow Simulation ────────────────

class FlowSimulateRequest(BaseModel):
    """Inputs for running a dry-run simulation of a flow."""
    context: Dict[str, Any] = {}        # Initial variable state
    inputs: Dict[str, Any] = {}         # {node_id: value} – pre-supplied answers for input/menu/dtmf nodes
    entry_node_id: Optional[str] = None # ID of the entry node to start from (required when flow has multiple entry points)


class SimulateStep(BaseModel):
    step: int
    node_id: str
    node_type: str
    label: str
    context_before: Dict[str, Any]
    context_after: Dict[str, Any]
    output: Optional[str] = None        # Message text emitted, audio played, etc.
    edge_taken: Optional[str] = None    # 'default', 'true', 'false', or port name
    status: str                         # "executed" | "end" | "external" | "needs_input" | "error"
    note: Optional[str] = None          # Human-readable explanation of what happened


class FlowSimulateResponse(BaseModel):
    trace: List[SimulateStep]
    final_context: Dict[str, Any]
    status: str                         # "completed" | "blocked" | "max_steps" | "error"
    message: Optional[str] = None


class FlowVersionOut(BaseModel):
    """A single historical snapshot of a flow (read-only)."""
    id: UUID
    flow_id: UUID
    version_number: str
    is_published_snapshot: bool = False
    label: str
    snapshot: Any                       # {nodes: [...], edges: [...]}
    saved_at: datetime
    saved_by: Optional[UUID] = None

    model_config = {"from_attributes": True}


# ──────────────── Connectors ────────────────

class MetaFieldMapping(BaseModel):
    name: str                   # key sent by the visitor page
    label: str = ""
    required: bool = False
    map_to_variable: str = ""   # flow context variable to set


class ConnectorCreate(BaseModel):
    name: str
    description: Optional[str] = None
    flow_id: Optional[UUID] = None
    allowed_origins: List[str] = ["*"]
    style: Dict[str, Any] = {}
    meta_fields: List[Dict[str, Any]] = []
    proactive_triggers: Dict[str, Any] = {}
    is_active: bool = True


class ConnectorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    flow_id: Optional[UUID] = None
    allowed_origins: Optional[List[str]] = None
    style: Optional[Dict[str, Any]] = None
    meta_fields: Optional[List[Dict[str, Any]]] = None
    proactive_triggers: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class ConnectorOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    api_key: str
    flow_id: Optional[UUID]
    allowed_origins: List[str]
    style: Dict[str, Any]
    meta_fields: List[Dict[str, Any]]
    proactive_triggers: Dict[str, Any] = {}
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class InteractionOut(BaseModel):
    id: UUID
    connector_id: UUID
    session_key: str
    visitor_metadata: Dict[str, Any]
    flow_context: Dict[str, Any]
    waiting_node_id: Optional[str]
    queue_id: Optional[UUID] = None
    status: str
    agent_id: Optional[UUID]
    created_at: datetime
    last_activity_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SurveySubmissionOut(BaseModel):
    id: UUID
    survey_name: str
    responses: Dict[str, Any]
    submitted_at: datetime

    model_config = {"from_attributes": True}


class InteractionDetailOut(BaseModel):
    """Full detail view — includes transcript, segments, CSAT/NPS, outcome, notes."""
    id: UUID
    connector_id: UUID
    connector_name: Optional[str] = None
    session_key: str
    status: str
    visitor_metadata: Dict[str, Any] = {}
    flow_context: Dict[str, Any] = {}
    waiting_node_id: Optional[str] = None
    queue_id: Optional[UUID] = None
    queue_name: Optional[str] = None
    agent_id: Optional[UUID] = None
    agent_name: Optional[str] = None
    message_log: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    disconnect_outcome: Optional[str] = None
    notes: Optional[str] = None
    csat_score: Optional[int] = None
    csat_comment: Optional[str] = None
    csat_submitted_at: Optional[datetime] = None
    nps_score: Optional[int] = None
    nps_reason: Optional[str] = None
    nps_submitted_at: Optional[datetime] = None
    wrap_time: Optional[int] = None
    created_at: datetime
    last_activity_at: Optional[datetime] = None
    tags: List[str] = []
    survey_submissions: List[SurveySubmissionOut] = []

    model_config = {"from_attributes": True}

# ──────────────── Outcome ────────────────

class OutcomeCreate(BaseModel):
    code: str
    label: str
    outcome_type: str = "neutral"       # positive / negative / neutral / escalation
    action_type: str = "end_interaction" # end_interaction | flow_redirect
    redirect_flow_id: Optional[UUID] = None
    description: Optional[str] = None
    is_active: bool = True


class OutcomeOut(BaseModel):
    id: UUID
    code: str
    label: str
    outcome_type: str
    action_type: str = "end_interaction"
    redirect_flow_id: Optional[UUID] = None
    description: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Office Hours ────────────────

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class OfficeHoursScheduleIn(BaseModel):
    """One day-of-week entry when setting/updating a group's weekly schedule."""
    day_of_week: int  # 0=Monday, 6=Sunday
    is_open:     bool    = True
    open_time:   str     = "08:00"   # HH:MM
    close_time:  str     = "17:00"   # HH:MM


class OfficeHoursScheduleOut(BaseModel):
    id:          UUID
    day_of_week: int
    day_name:    str
    is_open:     bool
    open_time:   str
    close_time:  str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_name(cls, obj):
        d = {"id": obj.id, "day_of_week": obj.day_of_week,
             "day_name": DAY_NAMES[obj.day_of_week],
             "is_open": obj.is_open, "open_time": obj.open_time, "close_time": obj.close_time}
        return cls(**d)


class OfficeHoursExclusionCreate(BaseModel):
    date:           date
    label:          Optional[str] = None
    is_open:        bool          = False  # False = closed all day
    override_open:  Optional[str] = None  # HH:MM; required when is_open=True
    override_close: Optional[str] = None  # HH:MM; required when is_open=True


class OfficeHoursExclusionUpdate(BaseModel):
    label:          Optional[str]  = None
    is_open:        Optional[bool] = None
    override_open:  Optional[str]  = None
    override_close: Optional[str]  = None


class OfficeHoursExclusionOut(BaseModel):
    id:             UUID
    date:           date
    label:          Optional[str]
    is_open:        bool
    override_open:  Optional[str]
    override_close: Optional[str]
    created_at:     datetime

    model_config = {"from_attributes": True}


class OfficeHoursGroupCreate(BaseModel):
    name:        str
    description: Optional[str] = None
    timezone:    str           = "Africa/Johannesburg"
    is_active:   bool          = True


class OfficeHoursGroupUpdate(BaseModel):
    name:        Optional[str]  = None
    description: Optional[str]  = None
    timezone:    Optional[str]  = None
    is_active:   Optional[bool] = None


class OfficeHoursGroupOut(BaseModel):
    id:          UUID
    name:        str
    description: Optional[str]
    timezone:    str
    is_active:   bool
    created_at:  datetime
    schedule:    List[OfficeHoursScheduleOut] = []
    exclusions:  List[OfficeHoursExclusionOut] = []

    model_config = {"from_attributes": True}


# ──────────────── Email Connector ────────────────

class EmailConnectorCreate(BaseModel):
    name: str
    description: Optional[str] = None
    # IMAP
    imap_host: Optional[str] = None
    imap_port: int = 993
    imap_username: Optional[str] = None
    imap_password: Optional[str] = None
    imap_use_ssl: bool = True
    imap_folder: str = "INBOX"
    poll_interval_seconds: int = 60
    # SMTP
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    from_address: Optional[str] = None
    from_name: Optional[str] = None
    # Routing
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: bool = True


class EmailConnectorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_username: Optional[str] = None
    imap_password: Optional[str] = None
    imap_use_ssl: Optional[bool] = None
    imap_folder: Optional[str] = None
    poll_interval_seconds: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    from_address: Optional[str] = None
    from_name: Optional[str] = None
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class EmailConnectorOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    imap_host: Optional[str]
    imap_port: int
    imap_username: Optional[str]
    imap_use_ssl: bool
    imap_folder: str
    poll_interval_seconds: int
    smtp_host: Optional[str]
    smtp_port: int
    smtp_username: Optional[str]
    smtp_use_tls: bool
    from_address: Optional[str]
    from_name: Optional[str]
    flow_id: Optional[UUID]
    queue_id: Optional[UUID]
    is_active: bool
    last_poll_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ──────────────── WhatsApp Connector ────────────────

class WhatsAppConnectorCreate(BaseModel):
    name: str
    description: Optional[str] = None
    provider: str = "meta_cloud"      # meta_cloud | twilio | 360dialog | vonage | generic
    business_phone_number: Optional[str] = None
    # Meta Cloud
    phone_number_id: Optional[str] = None
    waba_id: Optional[str] = None
    access_token: Optional[str] = None
    verify_token: Optional[str] = None
    # Twilio / generic
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    # Routing
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: bool = True


class WhatsAppConnectorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    business_phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None
    waba_id: Optional[str] = None
    access_token: Optional[str] = None
    verify_token: Optional[str] = None
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class WhatsAppConnectorOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    provider: str
    business_phone_number: Optional[str]
    phone_number_id: Optional[str]
    waba_id: Optional[str]
    verify_token: Optional[str]
    account_sid: Optional[str]
    flow_id: Optional[UUID]
    queue_id: Optional[UUID]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ──────────────── Voice Connector ────────────────

class VoiceConnectorCreate(BaseModel):
    name: str
    description: Optional[str] = None
    provider: str = "generic"   # twilio | vonage | telnyx | africastalking | freeswitch | 3cx | asterisk | generic
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    sip_domain: Optional[str] = None
    twiml_app_sid: Optional[str] = None
    caller_id_override: Optional[str] = None
    did_numbers: List[str] = []
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: bool = True


class VoiceConnectorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    sip_domain: Optional[str] = None
    twiml_app_sid: Optional[str] = None
    caller_id_override: Optional[str] = None
    did_numbers: Optional[List[str]] = None
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class VoiceConnectorOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    provider: str
    account_sid: Optional[str]
    api_key: Optional[str]
    sip_domain: Optional[str]
    twiml_app_sid: Optional[str] = None
    caller_id_override: Optional[str] = None
    did_numbers: List[str] = []
    flow_id: Optional[UUID]
    queue_id: Optional[UUID]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── SMS Connector ─────────────────────────────────────────────────────────────

class SmsConnectorCreate(BaseModel):
    name: str
    description: Optional[str] = None
    provider: str = "generic"  # twilio | vonage | africastalking | generic
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    from_number: Optional[str] = None
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: bool = True


class SmsConnectorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    from_number: Optional[str] = None
    flow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class SmsConnectorOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    provider: str
    account_sid: Optional[str]
    api_key: Optional[str]
    from_number: Optional[str]
    flow_id: Optional[UUID]
    queue_id: Optional[UUID]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
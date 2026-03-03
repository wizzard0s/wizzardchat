"""Pydantic schemas for request/response validation."""

from datetime import datetime, date
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from app.models import (
    ChannelType, UserRole, QueueStrategy, ConversationStatus,
    CampaignStatus, CampaignType, ContactStatus, AuthType,
    FlowType, FlowStatus, TagType,
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
    phone_number: Optional[str] = None
    auth_type: AuthType = AuthType.LOCAL


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    max_concurrent_chats: Optional[int] = None
    phone_number: Optional[str] = None
    auth_type: Optional[AuthType] = None
    password: Optional[str] = None


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    is_online: bool
    max_concurrent_chats: int
    phone_number: Optional[str]
    auth_type: AuthType
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


class FlowOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    channel: Optional[ChannelType]
    flow_type: FlowType
    status: FlowStatus
    is_active: bool
    is_published: bool
    version: int
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
    agents: List[str] = []    # list of User IDs assigned to work this campaign
    is_active: bool = True
    queue_id: Optional[UUID] = None
    flow_id: Optional[UUID] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    max_attempts: int = 3
    retry_interval: int = 3600
    caller_id: Optional[str] = None
    message_template: Optional[str] = None
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
    agents: List[Any] = []    # list of User IDs assigned to work this campaign
    queue_id: Optional[UUID]
    flow_id: Optional[UUID]
    scheduled_start: Optional[datetime]
    scheduled_end: Optional[datetime]
    stats: Any
    created_at: datetime

    model_config = {"from_attributes": True}


# Fix forward ref
TokenResponse.model_rebuild()


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
    is_active: bool = True


class ConnectorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    flow_id: Optional[UUID] = None
    allowed_origins: Optional[List[str]] = None
    style: Optional[Dict[str, Any]] = None
    meta_fields: Optional[List[Dict[str, Any]]] = None
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

# ──────────────── Outcome ────────────────

class OutcomeCreate(BaseModel):
    code: str
    label: str
    outcome_type: str = "neutral"  # positive / negative / neutral / escalation
    description: Optional[str] = None
    is_active: bool = True


class OutcomeOut(BaseModel):
    id: UUID
    code: str
    label: str
    outcome_type: str
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
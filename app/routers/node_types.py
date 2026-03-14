"""Node Type Registry API – built-in + custom node types."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CustomNodeType, User
from app.schemas import (
    CustomNodeTypeCreate, CustomNodeTypeUpdate, NodeTypeOut,
)
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/node-types",
    tags=["node-types"],
    dependencies=[Depends(get_current_user)],
)

# ──────────── Built-in node types (read-only) ────────────

# Keys that count as flow entry points (no input port; the simulator finds any of these)
ENTRY_NODE_KEYS = {
    "start", "start_chat", "start_whatsapp", "start_api", "start_voice", "start_email", "start_sms",
    "start_chat_ended", "start_call_ended", "start_internal_call",
    "start_sla_breached", "start_contact_imported", "start_contact_status_changed",
    # Blocked (requires third-party account) — registered so flow designer can display them
    "start_messenger", "start_instagram_dm", "start_instagram_post",
    "start_facebook_wall", "start_x_dm", "start_x_post",
    "start_apple_business", "start_hubspot",
}

BUILTIN_NODE_TYPES: List[NodeTypeOut] = [
    # ── Entry Points ─────────────────────────────────────────────────────────
    NodeTypeOut(key="start_chat", label="Chat Entry", icon="bi-chat-dots-fill",
                category="Entry Points", color="#0891b2", has_input=False, has_output=True,
                description="Flow entry point triggered by an inbound web chat session.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. Support Chat, Sales Enquiry",
                     "description": "Descriptive name — shown in the node body and routing logs."},
                    {"key": "connector_id", "label": "Chat Connector", "type": "connector_select",
                     "description": "Bind to a specific chat connector. Leave blank to accept from any chat connector."},
                    {"key": "initial_variables", "label": "Variables from Session",
                     "type": "key_value",
                     "description": "Map session metadata fields (key) to flow variable names (value). "
                                     "e.g.  visitor_name → contact_name"},
                ]),
    NodeTypeOut(key="start_whatsapp", label="WhatsApp Entry", icon="bi-whatsapp",
                category="Entry Points", color="#128C7E", has_input=False, has_output=True,
                description="Flow entry point triggered by an inbound WhatsApp message.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. WhatsApp Support, WhatsApp Sales"},
                    {"key": "connector_id", "label": "WhatsApp Connector", "type": "whatsapp_connector_select",
                     "description": "Bind to a specific WhatsApp connector."},
                    {"key": "from_filter", "label": "Sender Filter (optional)", "type": "string",
                     "placeholder": "+27 numbers, comma-separated. Empty = accept all.",
                     "description": "Only trigger for messages from these WhatsApp numbers."},
                    {"key": "keyword_filter", "label": "Keyword Filter (optional)", "type": "string",
                     "placeholder": "e.g. HELLO, HI",
                     "description": "Only trigger if the message starts with one of these keywords "
                                     "(comma-separated, case-insensitive). Empty = accept all."},
                    {"key": "initial_variables", "label": "Variables from Message",
                     "type": "key_value",
                     "description": "Map WhatsApp message fields (key) to flow variable names (value). "
                                     "Available fields: from_number, display_name, message_body, media_url"},
                ]),
    NodeTypeOut(key="start_api", label="API Entry", icon="bi-braces-asterisk",
                category="Entry Points", color="#7c3aed", has_input=False, has_output=True,
                description="Flow entry point triggered by a REST API call. "
                            "The trigger key is exposed at POST /api/v1/flows/{flow_id}/trigger/{key}.",
                config_schema=[
                    {"key": "trigger_key", "label": "Trigger Key", "type": "string", "required": True,
                     "placeholder": "e.g. new_ticket, lead_enquiry",
                     "description": "URL-safe key that callers pass to trigger this entry point. "
                                     "Must be unique within the flow."},
                    {"key": "require_auth", "label": "Require API Token", "type": "boolean",
                     "default": True,
                     "description": "Require a valid API bearer token in the Authorization header."},
                    {"key": "input_mapping", "label": "Payload → Flow Variables",
                     "type": "key_value",
                     "description": "Map API request body fields (key) to flow variable names (value). "
                                     "e.g.  customer_id → contact_id"},
                ]),
    NodeTypeOut(key="start_voice", label="Voice Entry", icon="bi-telephone-inbound-fill",
                category="Entry Points", color="#c2410c", has_input=False, has_output=True,
                description="Flow entry point triggered by an inbound voice call.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. Main Inbound, Support IVR"},
                    {"key": "connector_id", "label": "Voice Connector", "type": "voice_connector_select",
                     "description": "Bind to a specific voice connector for reporting and routing."},
                    {"key": "did_number", "label": "DID / Inbound Number (optional)", "type": "string",
                     "placeholder": "+27 10 123 4567",
                     "description": "Only match when the call arrives on this DID. "
                                     "Leave blank to accept all inbound calls."},
                    {"key": "queue_id", "label": "Inbound Queue (optional)", "type": "queue_select",
                     "description": "Associate this entry with an inbound queue for routing and reporting."},
                    {"key": "caller_id_variable", "label": "Store Caller ID As", "type": "string",
                     "placeholder": "caller_id", "default": "caller_id",
                     "description": "Flow variable that holds the caller's phone number."},
                    {"key": "dialled_variable", "label": "Store Dialled Number As", "type": "string",
                     "placeholder": "dialled_number",
                     "description": "Flow variable that holds the DID/number the caller dialled."},
                ]),
    NodeTypeOut(key="start_email", label="Email Entry", icon="bi-envelope-fill",
                category="Entry Points", color="#0369a1", has_input=False, has_output=True,
                description="Flow entry point triggered by an inbound email.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. Support Email, Sales Enquiry"},
                    {"key": "connector_id", "label": "Email Connector", "type": "email_connector_select",
                     "description": "Bind to a specific email connector (IMAP/SMTP config)."},
                    {"key": "from_filter", "label": "Sender Filter (optional)", "type": "string",
                     "placeholder": "e.g. @company.co.za — empty = accept all",
                     "description": "Only trigger for emails from addresses matching this substring."},
                    {"key": "subject_filter", "label": "Subject Filter (optional)", "type": "string",
                     "placeholder": "e.g. SUPPORT: — empty = accept all",
                     "description": "Only trigger when the subject starts with this prefix (case-insensitive)."},
                    {"key": "initial_variables", "label": "Variables from Email",
                     "type": "key_value",
                     "description": "Map email fields (key) to flow variable names (value). "
                                     "Available fields: from_address, from_name, subject, body_text, body_html, "
                                     "reply_to, message_id"},
                ]),
    NodeTypeOut(key="start_sms", label="SMS Entry", icon="bi-chat-square-text-fill",
                category="Entry Points", color="#059669", has_input=False, has_output=True,
                description="Flow entry point triggered by an inbound SMS (text message).",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. SMS Support, SMS Opt-in"},
                    {"key": "connector_id", "label": "SMS Connector", "type": "sms_connector_select",
                     "description": "Bind to a specific SMS connector (Twilio, Vonage, Africa's Talking, etc.)."},
                    {"key": "from_filter", "label": "Sender Filter (optional)", "type": "string",
                     "placeholder": "+27 numbers, comma-separated. Empty = accept all.",
                     "description": "Only trigger for messages from these numbers."},
                    {"key": "keyword_filter", "label": "Keyword Filter (optional)", "type": "string",
                     "placeholder": "e.g. HELP, STOP, JOIN",
                     "description": "Only trigger if the message starts with one of these keywords "
                                     "(comma-separated, case-insensitive). Empty = accept all."},
                    {"key": "initial_variables", "label": "Variables from SMS",
                     "type": "key_value",
                     "description": "Map SMS fields (key) to flow variable names (value). "
                                     "Available fields: from_number, to_number, message_body, message_id"},
                ]),
    # ── Event / Lifecycle Entry Points ────────────────────────────────────────
    NodeTypeOut(key="start_chat_ended", label="Chat Ended", icon="bi-chat-x-fill",
                category="Entry Points", color="#64748b", has_input=False, has_output=True,
                description="Flow entry point fired when a live-chat session closes (visitor disconnect, agent close, or timeout).",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. Post-Chat Survey, Wrap-Up"},
                    {"key": "connector_id", "label": "Chat Connector (optional)", "type": "connector_select",
                     "description": "Only fire when the closed session belongs to this connector. Leave blank for any."},
                    {"key": "trigger_on", "label": "Trigger On", "type": "select",
                     "options": ["any", "visitor_closed", "agent_closed", "timeout", "wrap_up_completed"],
                     "default": "any",
                     "description": "Which closure reason fires this node."},
                    {"key": "initial_variables", "label": "Variables from Session",
                     "type": "key_value",
                     "description": "Map closed-session fields (key) to flow variable names. "
                                     "Available fields: session_key, connector_id, closed_by, channel, contact_id, queue_id"},
                ]),
    NodeTypeOut(key="start_call_ended", label="Call Ended", icon="bi-telephone-x-fill",
                category="Entry Points", color="#92400e", has_input=False, has_output=True,
                description="Flow entry point fired when a voice call completes.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. Post-Call Survey, Call Reconciliation"},
                    {"key": "connector_id", "label": "Voice Connector (optional)", "type": "voice_connector_select",
                     "description": "Only fire when the call used this connector. Leave blank for any."},
                    {"key": "trigger_on", "label": "Trigger On", "type": "select",
                     "options": ["any", "completed", "no_answer", "busy", "failed"],
                     "default": "any",
                     "description": "Which call disposition fires this node."},
                    {"key": "initial_variables", "label": "Variables from Call",
                     "type": "key_value",
                     "description": "Map call fields (key) to flow variable names. "
                                     "Available fields: caller_id, dialled_number, call_id, duration_seconds, disposition, recording_url"},
                ]),
    NodeTypeOut(key="start_internal_call", label="Internal Transfer", icon="bi-telephone-forward-fill",
                category="Entry Points", color="#1d4ed8", has_input=False, has_output=True,
                description="Flow entry point triggered when a call or interaction is transferred internally "
                            "from another flow using the Transfer node.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. Billing Transfer, Technical Support"},
                    {"key": "transfer_key", "label": "Transfer Key", "type": "string", "required": True,
                     "placeholder": "e.g. billing_team, tech_support",
                     "description": "Unique key that the Transfer node references to route here."},
                    {"key": "initial_variables", "label": "Context from Transferring Flow",
                     "type": "key_value",
                     "description": "Map context fields (key) passed from the originating flow to flow variable names (value)."},
                ]),
    NodeTypeOut(key="start_sla_breached", label="SLA Breached", icon="bi-alarm-fill",
                category="Entry Points", color="#dc2626", has_input=False, has_output=True,
                description="Flow entry point fired by the SLA monitor when a queued interaction "
                            "exceeds its configured SLA threshold.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. SLA Breach Alert"},
                    {"key": "queue_id", "label": "Queue (optional)", "type": "queue_select",
                     "description": "Only fire for SLA breaches in this queue. Leave blank to trigger on any queue."},
                    {"key": "sla_threshold_seconds", "label": "SLA Threshold (seconds)", "type": "number",
                     "default": 300,
                     "description": "Waiting time in seconds that constitutes a breach."},
                    {"key": "initial_variables", "label": "Variables from Breach Event",
                     "type": "key_value",
                     "description": "Map breach fields (key) to flow variable names. "
                                     "Available fields: interaction_id, session_key, queue_id, waited_seconds, breach_at"},
                ]),
    NodeTypeOut(key="start_contact_imported", label="Contact Imported", icon="bi-person-plus-fill",
                category="Entry Points", color="#0891b2", has_input=False, has_output=True,
                description="Flow entry point fired after a contact is created or imported via the API.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. New Contact Onboarding"},
                    {"key": "initial_variables", "label": "Variables from Contact",
                     "type": "key_value",
                     "description": "Map contact fields (key) to flow variable names. "
                                     "Available fields: contact_id, name, email, phone, company, source, tags"},
                ]),
    NodeTypeOut(key="start_contact_status_changed", label="Contact Status Changed", icon="bi-person-fill-gear",
                category="Entry Points", color="#7c3aed", has_input=False, has_output=True,
                description="Flow entry point fired when a contact's status field changes.",
                config_schema=[
                    {"key": "entry_label", "label": "Entry Label", "type": "string",
                     "placeholder": "e.g. VIP Upgrade, Churn Risk"},
                    {"key": "from_status", "label": "From Status (optional)", "type": "string",
                     "placeholder": "Leave blank to match any previous status"},
                    {"key": "to_status", "label": "To Status (optional)", "type": "string",
                     "placeholder": "Leave blank to match any new status"},
                    {"key": "initial_variables", "label": "Variables from Contact",
                     "type": "key_value",
                     "description": "Map status change fields (key) to flow variable names. "
                                     "Available fields: contact_id, name, email, phone, old_status, new_status"},
                ]),
    # ── Third-Party Channels (placeholder — requires provider account) ───────────────
    NodeTypeOut(key="start_messenger", label="Messenger Entry", icon="bi-messenger",
                category="Entry Points", color="#0866ff", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by a Facebook Messenger message. Requires a Meta Business account and app approval.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "Facebook Messenger integration requires a Meta Business Account, App Review approval and a linked Facebook Page. See Meta documentation."},
                ]),
    NodeTypeOut(key="start_instagram_dm", label="Instagram DM Entry", icon="bi-instagram",
                category="Entry Points", color="#c13584", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by an Instagram Direct Message. Requires Meta Business account and Instagram Graph API access.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "Instagram DM integration requires a Meta Business Account and Instagram Graph API permissions. See Meta documentation."},
                ]),
    NodeTypeOut(key="start_instagram_post", label="Instagram Post Entry", icon="bi-instagram",
                category="Entry Points", color="#833ab4", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by an Instagram post comment or mention. Requires Meta Business account.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "Instagram Post integration requires a Meta Business Account and Instagram Graph API permissions."},
                ]),
    NodeTypeOut(key="start_facebook_wall", label="Facebook Wall Post Entry", icon="bi-facebook",
                category="Entry Points", color="#1877f2", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by a Facebook Page wall post or comment. Requires Meta Business account.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "Facebook Wall Post integration requires a Meta Business Account and Facebook Page API permissions."},
                ]),
    NodeTypeOut(key="start_x_dm", label="X (Twitter) DM Entry", icon="bi-twitter-x",
                category="Entry Points", color="#000000", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by an X (Twitter) Direct Message. Requires an X Developer account (paid).",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "X DM integration requires an X Developer account with Direct Messages API access (paid tier)."},
                ]),
    NodeTypeOut(key="start_x_post", label="X (Twitter) Post Entry", icon="bi-twitter-x",
                category="Entry Points", color="#1da1f2", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by an X (Twitter) post mention or reply. Requires an X Developer account.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "X Post integration requires an X Developer account with v2 API access."},
                ]),
    NodeTypeOut(key="start_apple_business", label="Apple Business Chat Entry", icon="bi-apple",
                category="Entry Points", color="#555555", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by an Apple Business Chat message. Requires Apple Business Register and a Messages for Business account.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "Apple Business Chat requires Apple Business Register approval and a licensed Messages for Business provider."},
                ]),
    NodeTypeOut(key="start_hubspot", label="HubSpot Object Entry", icon="bi-circle-fill",
                category="Entry Points", color="#ff7a59", has_input=False, has_output=True,
                description="[Coming soon] Flow entry point triggered by a HubSpot CRM object event. Requires HubSpot OAuth credentials and a Private App.",
                config_schema=[
                    {"key": "_coming_soon", "label": "Status", "type": "info",
                     "description": "HubSpot integration requires a HubSpot account, a Private App (OAuth) and CRM object webhook configuration."},
                ]),

    # ── Flow Control ──
    NodeTypeOut(key="start", label="Start", icon="bi-play-circle", category="Flow Control",
                color="#198754", has_input=False, has_output=True,
                description="Entry point of the flow.",
                config_schema=[
                    {"key": "trigger", "label": "Trigger", "type": "select",
                     "options": ["inbound_call", "inbound_chat", "api", "scheduled", "manual"],
                     "default": "inbound_call", "description": "What starts this flow"},
                    {"key": "connector_id", "label": "Chat Connector", "type": "connector_select",
                     "description": "Link this flow to a chat connector (inbound_chat only). "
                                    "The connector's metadata field mappings will be pre-loaded as flow variables.",
                     "expression_enabled": False},
                ]),
    NodeTypeOut(key="end", label="End", icon="bi-stop-circle", category="Flow Control",
                color="#dc3545", has_input=True, has_output=False,
                description="Terminates the flow.",
                config_schema=[
                    {"key": "status", "label": "End Status", "type": "select",
                     "options": ["completed", "failed", "abandoned"], "default": "completed"},
                    {"key": "message", "label": "End Message", "type": "string",
                     "placeholder": "Optional completion message"},
                ]),
    NodeTypeOut(key="condition", label="Condition", icon="bi-signpost-split", category="Flow Control",
                color="#ffc107", has_input=True, has_output=True,
                description="Branch flow based on a condition. Has 'true' and 'false' output ports.",
                config_schema=[
                    {"key": "variable", "label": "Variable", "type": "string", "required": True,
                     "placeholder": "e.g. contact.age or flow.status"},
                    {"key": "operator", "label": "Operator", "type": "select",
                     "options": ["equals", "not_equals", "contains", "not_contains",
                                 "greater_than", "less_than", "starts_with", "ends_with",
                                 "regex", "is_empty", "is_not_empty",
                                 "is_array", "is_not_array", "is_object", "is_not_object",
                                 "is_true", "is_false"]},

                    {"key": "value", "label": "Value", "type": "string",
                     "placeholder": "Value to compare against"},
                ]),
    NodeTypeOut(key="switch", label="Switch", icon="bi-diagram-3", category="Flow Control",
                color="#fd7e14", has_input=True, has_output=True,
                description="Multi-branch routing: each case specifies one or more conditions (all must match — AND logic). First matching case wins; falls through to Default if none match.",
                config_schema=[]),
    NodeTypeOut(key="ab_split", label="A/B Split", icon="bi-intersect", category="Flow Control",
                color="#6f42c1", has_input=True, has_output=True,
                description="Route interactions randomly to Branch A or Branch B at a configured percentage. Tags the flow context with the chosen variant for reporting.",
                config_schema=[
                    {"key": "split_percent", "label": "Branch A percentage", "type": "number", "required": True,
                     "default": 50, "placeholder": "e.g. 50 (means 50 % A, 50 % B)"},
                    {"key": "tag_a", "label": "Variant tag for Branch A", "type": "tag_select", "required": False,
                     "placeholder": "Select a tag"},
                    {"key": "tag_b", "label": "Variant tag for Branch B", "type": "tag_select", "required": False,
                     "placeholder": "Select a tag"},
                ]),
    NodeTypeOut(key="loop", label="Loop", icon="bi-arrow-repeat", category="Flow Control",
                color="#20c997", has_input=True, has_output=True,
                description="Iterate over every item in a JSON array, executing the loop body once per item. Routes via 'Loop' on each iteration and 'Done' when all items are processed (or the safety limit is reached).",
                config_schema=[
                    {"key": "array_variable", "label": "Array Variable", "type": "string", "required": True,
                     "placeholder": "e.g. api_response.items or contact.orders"},
                    {"key": "item_variable", "label": "Item Variable Name", "type": "string",
                     "default": "item", "placeholder": "item",
                     "description": "Context variable set to the current item on each pass"},
                    {"key": "index_variable", "label": "Index Variable Name", "type": "string",
                     "default": "loop_index", "placeholder": "loop_index",
                     "description": "Context variable set to the current 0-based index"},
                    {"key": "max_iterations", "label": "Max Iterations (safety)", "type": "number",
                     "default": 50, "description": "Hard limit to prevent infinite loops"},
                ]),
    NodeTypeOut(key="time_gate", label="Time Gate", icon="bi-clock", category="Flow Control",
                color="#0dcaf0", has_input=True, has_output=True,
                description="Route interactions based on the current time of day and day of week. 'Open' fires within the schedule; 'Closed' fires outside it.",
                config_schema=[
                    {"key": "days", "label": "Active Days", "type": "weekdays",
                     "default": "Mon,Tue,Wed,Thu,Fri"},
                    {"key": "start_time", "label": "Start Time (HH:MM)", "type": "string",
                     "default": "08:00", "placeholder": "08:00"},
                    {"key": "end_time", "label": "End Time (HH:MM)", "type": "string",
                     "default": "17:00", "placeholder": "17:00"},
                    {"key": "timezone", "label": "Timezone", "type": "string",
                     "default": "Africa/Johannesburg", "placeholder": "Africa/Johannesburg"},
                ]),
    NodeTypeOut(key="goto", label="GoTo", icon="bi-arrow-return-right", category="Flow Control",
                color="#6c757d", has_input=True, has_output=False,
                description="Jump to another node in the flow.",
                config_schema=[
                    {"key": "target_node", "label": "Target Node", "type": "string",
                     "placeholder": "Node label or ID"},
                ]),
    NodeTypeOut(key="sub_flow", label="Sub-Flow", icon="bi-box-arrow-in-right", category="Flow Control",
                color="#087990", has_input=True, has_output=True,
                description="Execute another flow as a sub-routine. Only mapped variables are available inside the sub-flow.",
                config_schema=[
                    {"key": "flow_id", "label": "Sub-Flow", "type": "flow_select", "required": True,
                     "placeholder": "Select a flow"},
                    {"key": "input_mapping", "label": "Pass Variables In",
                     "type": "key_value",
                     "description": "Map sub-flow variable names (key) to values from this flow (value). Supports {{variable}} templates."},
                    {"key": "result_variable", "label": "Sub-flow Result Variable", "type": "string",
                     "placeholder": "result",
                     "description": "Name of the variable set inside the sub-flow whose value is exported back to this flow"},
                    {"key": "output_variable", "label": "Store Result As", "type": "string",
                     "placeholder": "sub_result",
                     "description": "Parent-flow variable name to store the sub-flow result in"},
                ]),

    # ── Interaction ──
    NodeTypeOut(key="message", label="Message", icon="bi-chat-left-text", category="Interaction",
                color="#0d6efd", has_input=True, has_output=True,
                description="Send a message to the contact.",
                config_schema=[
                    {"key": "text", "label": "Message Text", "type": "textarea", "required": True,
                     "placeholder": "Enter message to send..."},
                    {"key": "delay_ms", "label": "Typing Delay (ms)", "type": "number",
                     "default": 0, "description": "Simulate typing delay before sending"},
                ]),
    NodeTypeOut(key="input", label="Input", icon="bi-input-cursor-text", category="Interaction",
                color="#6f42c1", has_input=True, has_output=True,
                description="Prompt the contact for input and store in a variable.",
                config_schema=[
                    {"key": "prompt", "label": "Prompt", "type": "string", "required": True,
                     "placeholder": "Ask the user..."},
                    {"key": "variable", "label": "Variable Name", "type": "string", "required": True,
                     "placeholder": "user_input"},
                    {"key": "validation", "label": "Validation", "type": "select",
                     "options": ["any", "number", "email", "phone", "date", "regex"], "default": "any"},
                    {"key": "validation_regex", "label": "Regex Pattern", "type": "string",
                     "placeholder": "^[0-9]+$", "description": "Used when validation is 'regex'"},
                    {"key": "error_message", "label": "Error Message", "type": "string",
                     "placeholder": "Invalid input, please try again"},
                    {"key": "max_retries", "label": "Max Retries", "type": "number", "default": 3},
                ]),
    NodeTypeOut(key="menu", label="Menu", icon="bi-list-ol", category="Interaction",
                color="#0dcaf0", has_input=True, has_output=True,
                description="Present numbered options to the contact.",
                config_schema=[
                    {"key": "prompt", "label": "Prompt", "type": "string", "required": True,
                     "placeholder": "Please choose:", "default": "Please choose:"},
                    {"key": "options", "label": "Menu Options", "type": "options_list",
                     "description": "Static key-label pairs. Click the \u26a1 toggle to build items dynamically with a JSONata expression that returns [{\"key\":\"1\",\"text\":\"Label\"}, ...]"},
                ]),
    NodeTypeOut(key="wait", label="Wait", icon="bi-hourglass", category="Interaction",
                color="#adb5bd", has_input=True, has_output=True,
                description="Pause the flow for a specified duration.",
                config_schema=[
                    {"key": "duration", "label": "Duration (seconds)", "type": "number",
                     "required": True, "default": 5},
                ]),
    NodeTypeOut(key="save_survey", label="Save Survey", icon="bi-clipboard2-check", category="Interaction",
                color="#20c997", has_input=True, has_output=True,
                description="Persist survey responses to a dedicated survey_submissions record linked to this interaction. Configure as many field mappings as your survey has questions — each key is the stored field name, each value is the flow context variable that holds the answer.",
                config_schema=[
                    {"key": "survey_name", "label": "Survey Name", "type": "string", "required": True,
                     "placeholder": "e.g. csat, nps, post_call_feedback",
                     "description": "Identifies this survey type. Use 'csat' or 'nps' to also mirror well-known scores to the interaction's built-in columns."},
                    {"key": "fields", "label": "Field Mappings", "type": "key_value",
                     "description": "Map stored field names (key) to flow context variables (value). Add as many rows as your survey has questions. E.g. score → csat_score, comment → csat_comment, recommend → nps_recommend"},
                ]),

    # ── Telephony ──
    NodeTypeOut(key="play_audio", label="Play Audio", icon="bi-volume-up", category="Telephony",
                color="#6610f2", has_input=True, has_output=True,
                description="Play an audio file to the caller.",
                config_schema=[
                    {"key": "audio_url", "label": "Audio URL / File", "type": "string", "required": True,
                     "placeholder": "https://... or file path"},
                    {"key": "loop", "label": "Loop", "type": "boolean", "default": False},
                ]),
    NodeTypeOut(key="record", label="Record", icon="bi-mic", category="Telephony",
                color="#d63384", has_input=True, has_output=True,
                description="Record audio from the caller.",
                config_schema=[
                    {"key": "variable", "label": "Save to Variable", "type": "string",
                     "placeholder": "recording_url"},
                    {"key": "max_duration", "label": "Max Duration (sec)", "type": "number", "default": 60},
                    {"key": "beep", "label": "Play Beep", "type": "boolean", "default": True},
                    {"key": "silence_timeout", "label": "Silence Timeout (sec)", "type": "number", "default": 5},
                ]),
    NodeTypeOut(key="dtmf", label="DTMF", icon="bi-grid-3x3", category="Telephony",
                color="#495057", has_input=True, has_output=True,
                description="Collect touch-tone keypad input.",
                config_schema=[
                    {"key": "variable", "label": "Save to Variable", "type": "string",
                     "placeholder": "dtmf_input"},
                    {"key": "max_digits", "label": "Max Digits", "type": "number", "default": 1},
                    {"key": "timeout", "label": "Timeout (seconds)", "type": "number", "default": 10},
                    {"key": "finish_on_key", "label": "Finish on Key", "type": "string",
                     "default": "#", "placeholder": "# or *"},
                ]),

    # ── Routing ──
    NodeTypeOut(key="queue", label="Queue", icon="bi-people", category="Routing",
                color="#fd7e14", has_input=True, has_output=False,
                description="Place the contact into an agent queue.",
                config_schema=[
                    {"key": "queue_id", "label": "Queue", "type": "queue_select", "required": True,
                     "description": "Select the queue to route this contact to. "
                                    "The queue must belong to a campaign so agents can be dispatched automatically."},
                    {"key": "queue_message", "label": "Hold Message", "type": "string",
                     "default": "Connecting you with an agent, please wait…",
                     "placeholder": "Please wait while we connect you..."},
                    {"key": "priority", "label": "Priority", "type": "number", "default": 0},
                    {"key": "timeout", "label": "Timeout (seconds)", "type": "number",
                     "default": 300, "description": "Max wait time before overflow"},
                ]),
    NodeTypeOut(key="transfer", label="Transfer", icon="bi-telephone-forward", category="Routing",
                color="#e85d04", has_input=True, has_output=False,
                description="Transfer the conversation to another destination.",
                config_schema=[
                    {"key": "target", "label": "Transfer To", "type": "string", "required": True,
                     "placeholder": "Extension, queue, or number"},
                    {"key": "transfer_type", "label": "Transfer Type", "type": "select",
                     "options": ["blind", "warm"], "default": "blind"},
                ]),

    # ── Integration ──
    NodeTypeOut(key="http_request", label="HTTP Request", icon="bi-globe", category="Integration",
                color="#20c997", has_input=True, has_output=True,
                description="Make an HTTP API call. Outputs: 'success' (2xx) / 'error' (non-2xx, timeout, or network failure).",
                config_schema=[
                    {"key": "url", "label": "URL", "type": "string", "required": True,
                     "placeholder": "https://api.example.com/endpoint"},
                    {"key": "method", "label": "Method", "type": "select",
                     "options": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
                    {"key": "headers", "label": "Headers", "type": "json",
                     "placeholder": '{"Content-Type": "application/json"}',
                     "description": "Request headers as JSON object"},
                    {"key": "body", "label": "Request Body", "type": "json",
                     "placeholder": '{"key": "value"}',
                     "description": "Request body (for POST/PUT/PATCH)"},
                    {"key": "response_var", "label": "Response Variable", "type": "string",
                     "placeholder": "api_response"},
                    {"key": "error_variable", "label": "Error Variable", "type": "string",
                     "placeholder": "api_error",
                     "description": "Variable to store error details on non-2xx response or network failure"},
                    {"key": "timeout_ms", "label": "Timeout (ms)", "type": "number", "default": 30000},
                ]),
    NodeTypeOut(key="webhook", label="Webhook", icon="bi-broadcast", category="Integration",
                color="#d63384", has_input=True, has_output=True,
                description="Send a webhook notification.",
                config_schema=[
                    {"key": "url", "label": "Webhook URL", "type": "string", "required": True,
                     "placeholder": "https://..."},
                    {"key": "method", "label": "Method", "type": "select",
                     "options": ["POST", "GET"], "default": "POST"},
                    {"key": "headers", "label": "Headers", "type": "json", "placeholder": '{}'},
                    {"key": "payload", "label": "Payload", "type": "json", "placeholder": '{}',
                     "description": "Data to send with the webhook"},
                ]),
    NodeTypeOut(key="set_variable", label="Set Variable", icon="bi-braces", category="Integration",
                color="#6c757d", has_input=True, has_output=True,
                description="Set one or more variables using literal values or JSONata expressions."),
    NodeTypeOut(key="ai_bot", label="AI Bot", icon="bi-robot", category="Integration",
                color="#7c3aed", has_input=True, has_output=True,
                description=(
                    "Conversational AI node powered by WizzardAI. "
                    "Set output_variable for single-shot Q&A mode, or leave blank for "
                    "multi-turn conversation (exits via the 'exit' handle when an exit "
                    "keyword is matched, or via the default handle when max turns is reached)."
                ),
                config_schema=[
                    {"key": "system_prompt", "label": "System Prompt", "type": "textarea", "required": True,
                     "placeholder": "You are a helpful assistant..."},
                    {"key": "model", "label": "Model", "type": "select",
                     "options": [
                         "── Local (Ollama) ──",
                         "wizzardai://ollama/qwen3:8b",
                         "wizzardai://ollama/qwen2.5:7b",
                         "wizzardai://ollama/llama3.2:1b",
                         "── OpenAI ──",
                         "wizzardai://openai/gpt-4o",
                         "wizzardai://openai/gpt-4o-mini",
                         "── Anthropic ──",
                         "wizzardai://anthropic/claude-3-5-sonnet-20241022",
                         "wizzardai://anthropic/claude-3-haiku-20240307",
                         "── Legacy (resolved by WizzardAI) ──",
                         "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo",
                         "claude-3-opus", "claude-3-sonnet", "claude-3-haiku",
                     ],
                     "default": "wizzardai://ollama/qwen3:8b"},
                    {"key": "max_turns", "label": "Max Turns", "type": "number", "default": 10,
                     "description": "Maximum conversation turns before exiting via the default handle"},
                    {"key": "temperature", "label": "Temperature", "type": "number", "default": 0.7,
                     "description": "0 = deterministic, 1 = creative"},
                    {"key": "exit_keywords", "label": "Exit Keywords", "type": "string",
                     "placeholder": "done, exit, bye",
                     "description": "Comma-separated keywords that trigger the 'exit' output handle"},
                    {"key": "output_variable", "label": "Output Variable", "type": "string",
                     "placeholder": "ai_result",
                     "description": "If set, stores the AI response here and advances immediately (single-shot mode)"},
                ]),
    NodeTypeOut(key="kb_search", label="KB Search", icon="bi-book-half", category="Integration",
                color="#0dcaf0", has_input=True, has_output=True,
                description="Search the knowledge base and store the best matching article in a variable.",
                config_schema=[
                    {"key": "query_variable", "label": "Query Variable", "type": "string",
                     "placeholder": "user_input",
                     "description": "Variable containing the search query text"},
                    {"key": "result_variable", "label": "Result Variable", "type": "string",
                     "placeholder": "kb_result",
                     "description": "Variable to store the matched article (title, url, excerpt)"},
                    {"key": "found_variable", "label": "Found Variable", "type": "string",
                     "placeholder": "kb_found",
                     "description": "Boolean variable — true if a match was found"},
                    {"key": "limit", "label": "Max Results", "type": "number", "default": 1},
                    {"key": "min_score", "label": "Min Relevance", "type": "number",
                     "default": 0.005,
                     "description": "0.0–1.0. Results below this threshold are ignored."},
                    {"key": "source_id", "label": "Source Filter", "type": "string",
                     "placeholder": "Leave blank for all sources"},
                ]),
    NodeTypeOut(key="translate", label="Translate", icon="bi-translate", category="Integration",
                color="#0d6efd", has_input=True, has_output=True,
                description=(
                    "Translate text using LibreTranslate (free, self-hostable). "
                    "Auto-detects source language; sets contact.language. "
                    "SA languages: Afrikaans (af), Zulu/Xhosa require a custom LibreTranslate model pack."
                ),
                config_schema=[
                    {"key": "mode", "label": "Mode", "type": "select",
                     "options": ["translate", "detect_only"],
                     "default": "translate",
                     "description": "'translate' translates then sets contact.language. 'detect_only' identifies language only."},
                    {"key": "input_variable", "label": "Input Variable", "type": "string",
                     "default": "message", "placeholder": "message",
                     "description": "Flow context variable containing the text to translate."},
                    {"key": "target_language", "label": "Target Language", "type": "string",
                     "placeholder": "en",
                     "description": "ISO 639-1 code — e.g. en, af, zu, fr. Supports {{variable}} templates."},
                    {"key": "source_language", "label": "Source Language", "type": "string",
                     "default": "auto", "placeholder": "auto",
                     "description": "auto = detect automatically. Otherwise provide an ISO 639-1 code."},
                    {"key": "result_variable", "label": "Result Variable", "type": "string",
                     "default": "translated_text", "placeholder": "translated_text",
                     "description": "Variable to store the translated text."},
                    {"key": "language_variable", "label": "Language Variable", "type": "string",
                     "default": "contact.language", "placeholder": "contact.language",
                     "description": "Variable to store the detected/source language code."},
                    {"key": "libretranslate_url", "label": "LibreTranslate URL (optional override)",
                     "type": "string", "placeholder": "http://localhost:5000",
                     "description": "Leave blank to use the value from server settings (LIBRETRANSLATE_URL)."},
                    {"key": "api_key", "label": "API Key (optional)", "type": "string",
                     "placeholder": "Leave blank for unauthenticated instances"},
                ]),
]

BUILTIN_KEYS = {t.key for t in BUILTIN_NODE_TYPES}


# ──────────── Endpoints ────────────

@router.get("", response_model=List[NodeTypeOut])
async def list_node_types(db: AsyncSession = Depends(get_db)):
    """Return all node types: built-in + custom."""
    result = await db.execute(select(CustomNodeType).order_by(CustomNodeType.category, CustomNodeType.label))
    custom = result.scalars().all()
    custom_out = [
        NodeTypeOut(
            key=c.key, label=c.label, icon=c.icon, category=c.category, color=c.color,
            has_input=c.has_input, has_output=c.has_output, is_builtin=False,
            config_schema=c.config_schema or [], description=c.description, id=c.id,
        )
        for c in custom
    ]
    return BUILTIN_NODE_TYPES + custom_out


@router.post("", response_model=NodeTypeOut, status_code=201)
async def create_custom_node_type(
    body: CustomNodeTypeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new custom node type."""
    if body.key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail=f"Key '{body.key}' conflicts with a built-in type")
    # Check unique
    exists = await db.execute(select(CustomNodeType).where(CustomNodeType.key == body.key))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Key '{body.key}' already exists")
    obj = CustomNodeType(
        key=body.key, label=body.label, icon=body.icon, category=body.category,
        color=body.color, has_input=body.has_input, has_output=body.has_output,
        config_schema=body.config_schema, description=body.description, created_by=user.id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await db.commit()
    return NodeTypeOut(
        key=obj.key, label=obj.label, icon=obj.icon, category=obj.category, color=obj.color,
        has_input=obj.has_input, has_output=obj.has_output, is_builtin=False,
        config_schema=obj.config_schema or [], description=obj.description, id=obj.id,
    )


@router.put("/{key}", response_model=NodeTypeOut)
async def update_custom_node_type(
    key: str,
    body: CustomNodeTypeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a custom node type (built-in types cannot be modified)."""
    if key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail="Cannot modify built-in node types")
    result = await db.execute(select(CustomNodeType).where(CustomNodeType.key == key))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Custom node type not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, val)
    await db.flush()
    await db.refresh(obj)
    await db.commit()
    return NodeTypeOut(
        key=obj.key, label=obj.label, icon=obj.icon, category=obj.category, color=obj.color,
        has_input=obj.has_input, has_output=obj.has_output, is_builtin=False,
        config_schema=obj.config_schema or [], description=obj.description, id=obj.id,
    )


@router.delete("/{key}", status_code=204)
async def delete_custom_node_type(key: str, db: AsyncSession = Depends(get_db)):
    """Delete a custom node type."""
    if key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail="Cannot delete built-in node types")
    result = await db.execute(select(CustomNodeType).where(CustomNodeType.key == key))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Custom node type not found")
    await db.delete(obj)
    await db.commit()

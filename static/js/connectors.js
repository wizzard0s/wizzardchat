/**
 * WizzardChat – Connectors admin page logic
 */
'use strict';

// ─── Auth helpers ────────────────────────────────────────────────────────────
const _token = () => localStorage.getItem('wizzardchat_token') || '';
const apiFetch = (url, opts = {}) => {
    opts.headers = Object.assign({ Authorization: 'Bearer ' + _token(), 'Content-Type': 'application/json' }, opts.headers || {});
    return fetch(url, opts);
};

// ─── State ───────────────────────────────────────────────────────────────────
let connectors = [];
let waConnectors = [];    // WhatsApp connectors
let voiceConnectors = []; // Voice connectors
let smsConnectors = [];   // SMS connectors
let emailConnectors = []; // Email connectors
let flows = [];
let selectedConnectorId = null;  // ID of connector open in edit modal
let selectedConnectorType = 'chat'; // type of connector open in modal
let deleteTargetId = null;
let deleteTargetType = 'chat';

// Live chat state
let agentWs = null;
let sessions = {};  // session_key → session data
let activeSessionKey = null;  // currently open in chat window

// ─── Bootstrap modals ────────────────────────────────────────────────────────
let connectorModal, snippetModal, deleteModal;

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    // Ensure auth
    if (!_token()) { window.location.href = '/login'; return; }

    connectorModal = new bootstrap.Modal(document.getElementById('connectorModal'));
    snippetModal   = new bootstrap.Modal(document.getElementById('snippetModal'));
    deleteModal    = new bootstrap.Modal(document.getElementById('deleteConnectorModal'));

    // Verify auth
    try {
        const r = await apiFetch('/api/v1/auth/me');
        if (!r.ok) { window.location.href = '/login'; return; }
    } catch { window.location.href = '/login'; return; }

    bindTabSwitcher();
    bindConnectorModal();
    bindSnippetModal();
    bindDeleteModal();

    await loadFlows();
    await loadConnectors();
    await loadWaConnectors();
    await loadVoiceConnectors();
    await loadSmsConnectors();
    await loadEmailConnectors();

    document.getElementById('btnLogout')?.addEventListener('click', () => {
        localStorage.removeItem('wizzardchat_token'); window.location.href = '/login';
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tab switcher
// ─────────────────────────────────────────────────────────────────────────────
function bindTabSwitcher() {
    document.querySelectorAll('[data-tab]').forEach(link => {
        link.addEventListener('click', e => {
            e.preventDefault();
            document.querySelectorAll('[data-tab]').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            const tab = link.dataset.tab;
            document.getElementById('tabConnectors').classList.toggle('d-none', tab !== 'connectors');
            document.getElementById('tabInbox').classList.toggle('d-none', tab !== 'inbox');
            if (tab === 'inbox' && !agentWs) initAgentWs();
        });
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Load helpers
// ─────────────────────────────────────────────────────────────────────────────
async function loadConnectors() {
    const r = await apiFetch('/api/v1/connectors');
    if (!r.ok) return;
    connectors = await r.json();
    renderConnectorList();
}

async function loadWaConnectors() {
    const r = await apiFetch('/api/v1/whatsapp-connectors');
    if (r.ok) { waConnectors = await r.json(); renderConnectorList(); }
}

async function loadVoiceConnectors() {
    const r = await apiFetch('/api/v1/voice-connectors');
    if (r.ok) { voiceConnectors = await r.json(); renderConnectorList(); }
}

async function loadSmsConnectors() {
    const r = await apiFetch('/api/v1/sms-connectors');
    if (r.ok) { smsConnectors = await r.json(); renderConnectorList(); }
}

async function loadEmailConnectors() {
    const r = await apiFetch('/api/v1/email-connectors');
    if (r.ok) { emailConnectors = await r.json(); renderConnectorList(); }
}

async function loadFlows() {
    const r = await apiFetch('/api/v1/flows');
    if (!r.ok) return;
    const data = await r.json();
    flows = Array.isArray(data) ? data : (data.items || []);
}

// ─────────────────────────────────────────────────────────────────────────────
// Render connector cards
// ─────────────────────────────────────────────────────────────────────────────
// ─── Connector card builders ─────────────────────────────────────────────────
const CONNECTOR_TYPE_META = {
    chat:      { wz: 'wz-channel-chat',     icon: 'bi-chat',                    label: 'Chat'     },
    whatsapp:  { wz: 'wz-channel-whatsapp', icon: 'bi-whatsapp',                label: 'WhatsApp' },
    voice:     { wz: 'wz-channel-voice',    icon: 'bi-telephone-inbound-fill',  label: 'Voice'    },
    sms:       { wz: 'wz-channel-sms',      icon: 'bi-chat-square-text-fill',   label: 'SMS'      },
    email:     { wz: 'wz-channel-email',    icon: 'bi-envelope-fill',           label: 'Email'    },
};

function makeConnectorCard(c, type) {
    const meta   = CONNECTOR_TYPE_META[type] || CONNECTOR_TYPE_META.chat;
    const linkedFlow = flows.find(f => f.id === c.flow_id);
    const statusDot  = c.is_active
        ? '<span class="connector-status bg-success me-1"></span>Active'
        : '<span class="connector-status bg-secondary me-1"></span>Inactive';
    const badgeHtml  = `<span class="wz-badge ${meta.wz}"><i class="bi ${meta.icon} me-1"></i>${meta.label}</span>`;

    // Extra line for typed connectors
    let providerLine = '';
    if (c.provider)  providerLine = `<div class="small text-muted mb-1"><i class="bi bi-server me-1"></i>${escHtml(c.provider)}</div>`;
    if (c.business_phone_number) providerLine += `<div class="small text-muted mb-1"><i class="bi bi-telephone me-1"></i>${escHtml(c.business_phone_number)}</div>`;
    if (c.did_numbers?.length)   providerLine += `<div class="small text-muted mb-1"><i class="bi bi-telephone me-1"></i>${c.did_numbers.slice(0,3).map(escHtml).join(', ')}</div>`;
    if (c.from_number)           providerLine += `<div class="small text-muted mb-1"><i class="bi bi-telephone me-1"></i>${escHtml(c.from_number)}</div>`;

    const keyHint = c.api_key
        ? `<div class="small text-muted font-monospace text-truncate" title="${escHtml(c.api_key)}"><i class="bi bi-key me-1"></i>${c.api_key.slice(0, 18)}…</div>`
        : '';

    const snippetBtn = type === 'chat'
        ? `<button class="btn btn-sm btn-outline-info btn-snippet" data-id="${c.id}" data-type="${type}"><i class="bi bi-code-slash"></i></button>`
        : `<button class="btn btn-sm btn-outline-info btn-webhook-info" data-id="${c.id}" data-type="${type}" title="Webhook info"><i class="bi bi-link-45deg"></i></button>`;

    const col = document.createElement('div');
    col.className = 'col-md-6 col-lg-4 col';
    col.innerHTML = `
        <div class="card connector-card h-100">
            <div class="card-body">
                <div class="d-flex align-items-start justify-content-between mb-2">
                    <div>
                        <h6 class="mb-0">${escHtml(c.name)}</h6>
                        <div class="small text-muted mt-1">${statusDot}</div>
                    </div>
                    ${badgeHtml}
                </div>
                ${c.description ? `<p class="small text-muted mb-2">${escHtml(c.description)}</p>` : ''}
                <div class="small text-muted mb-1">
                    <i class="bi bi-diagram-3 me-1"></i>
                    ${linkedFlow ? escHtml(linkedFlow.name) : '<em>No destination flow set</em>'}
                </div>
                ${providerLine}
                ${keyHint}
            </div>
            <div class="card-footer d-flex gap-2 py-2">
                <button class="btn btn-sm btn-outline-secondary flex-fill btn-edit-connector" data-id="${c.id}" data-type="${type}">
                    <i class="bi bi-pencil me-1"></i>Edit
                </button>
                ${snippetBtn}
                <button class="btn btn-sm btn-outline-danger btn-del-connector" data-id="${c.id}" data-name="${escHtml(c.name)}" data-type="${type}">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>`;
    col.querySelector('.btn-edit-connector')?.addEventListener('click', () => openEditConnector(c.id, type));
    col.querySelector('.btn-snippet')?.addEventListener('click', () => openSnippet(c.id));
    col.querySelector('.btn-webhook-info')?.addEventListener('click', () => openWebhookInfo(c.id, type));
    col.querySelector('.btn-del-connector')?.addEventListener('click', () => openDeleteConfirm(c.id, c.name, type));
    return col;
}

function renderConnectorList() {
    const el = document.getElementById('connectorsList');
    const empty = document.getElementById('connectorsEmpty');

    const all = [
        ...connectors.map(c => ({ c, type: 'chat' })),
        ...waConnectors.map(c => ({ c, type: 'whatsapp' })),
        ...voiceConnectors.map(c => ({ c, type: 'voice' })),
        ...smsConnectors.map(c => ({ c, type: 'sms' })),
        ...emailConnectors.map(c => ({ c, type: 'email' })),
    ];

    el.querySelectorAll('.col').forEach(c => c.remove());

    if (!all.length) {
        empty.classList.remove('d-none');
        return;
    }
    empty.classList.add('d-none');
    all.forEach(({ c, type }) => el.appendChild(makeConnectorCard(c, type)));
}

function escHtml(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─────────────────────────────────────────────────────────────────────────────
// Create / Edit modal
// ─────────────────────────────────────────────────────────────────────────────

/** Switch visible type-specific panel and update the type hidden input */
function switchConnectorType(type) {
    selectedConnectorType = type;
    document.getElementById('connectorType').value = type;
    document.querySelectorAll('.connector-type-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.type === type);
    });
    document.getElementById('chatConnectorFields').classList.toggle('d-none', type !== 'chat');
    document.getElementById('waConnectorFields').classList.toggle('d-none', type !== 'whatsapp');
    document.getElementById('voiceConnectorFields').classList.toggle('d-none', type !== 'voice');
    document.getElementById('smsConnectorFields').classList.toggle('d-none', type !== 'sms');
    document.getElementById('emailConnectorFields').classList.toggle('d-none', type !== 'email');
    // Widget preview only makes sense for chat
    document.getElementById('widgetPreviewWrap')?.classList.toggle('d-none', type !== 'chat');
}

function bindConnectorModal() {
    document.getElementById('btnNewConnector').addEventListener('click', () => openNewConnector());
    document.getElementById('btnSaveConnector').addEventListener('click', saveConnector);
    document.getElementById('btnAddMetaField').addEventListener('click', addMetaFieldRow);
    document.getElementById('btnAddTrigger')?.addEventListener('click', () => addTriggerRule(null));
    document.getElementById('btnRegenKey')?.addEventListener('click', regenerateKey);

    // Type picker buttons
    document.querySelectorAll('.connector-type-btn').forEach(btn => {
        btn.addEventListener('click', () => switchConnectorType(btn.dataset.type));
    });

    // Live style preview
    ['sTitle','sSubtitle','sPrimaryColor','sPrimaryColorHex'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updatePreview);
    });

    // Sync color picker ↔ hex text ↔ round swatch
    const _updateSwatch = (color) => {
        const sw = document.getElementById('colorSwatch');
        if (sw) sw.style.background = color;
    };
    document.getElementById('sPrimaryColor')?.addEventListener('input', e => {
        document.getElementById('sPrimaryColorHex').value = e.target.value;
        _updateSwatch(e.target.value);
        updatePreview();
    });
    document.getElementById('sPrimaryColorHex')?.addEventListener('input', e => {
        if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
            document.getElementById('sPrimaryColor').value = e.target.value;
            _updateSwatch(e.target.value);
        }
        updatePreview();
    });
}

function populateFlowDropdown() {
    const sel = document.getElementById('cFlowId');
    sel.innerHTML = '<option value="">— No flow —</option>';
    flows.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.id;
        opt.textContent = f.name;
        sel.appendChild(opt);
    });
}

function openNewConnector() {
    selectedConnectorId = null;
    document.getElementById('connectorModalTitle').innerHTML = '<i class="bi bi-plus-lg me-2"></i>New Connector';
    document.getElementById('connectorId').value = '';
    document.getElementById('cName').value = '';
    document.getElementById('cDescription').value = '';
    document.getElementById('cAllowedOrigins').value = '*';
    document.getElementById('cIsActive').checked = true;
    document.getElementById('sTitle').value = 'Chat with us';
    document.getElementById('sSubtitle').value = 'We typically reply within minutes';
    document.getElementById('sPrimaryColor').value = '#0d6efd';
    document.getElementById('sPrimaryColorHex').value = '#0d6efd';
    const sw0 = document.getElementById('colorSwatch');
    if (sw0) sw0.style.background = '#0d6efd';
    document.getElementById('sPosition').value = 'bottom-right';
    document.getElementById('sTheme').value = 'light';
    document.getElementById('sLogoUrl').value = '';
    document.getElementById('sWidth').value = '370px';
    document.getElementById('sHeight').value = '520px';
    document.getElementById('metaFieldsBody').innerHTML = '';
    document.getElementById('existingKeyPanel').classList.add('d-none');
    fillProactive({});
    populateFlowDropdown();
    updateMetaFieldsEmpty();
    updatePreview();
    // Reset WA / Voice / SMS / Email fields
    clearWaFields(); clearVoiceFields(); clearSmsFields(); clearEmailFields();
    updateWaCredentialHints(); updateSmsCredentialHints();
    // Show type picker for new connector
    document.getElementById('connectorTypePicker').classList.remove('d-none');
    switchConnectorType('chat');
    connectorModal.show();
}

function openEditConnector(id, type) {
    type = type || 'chat';
    selectedConnectorId = id;
    selectedConnectorType = type;
    // Hide type picker when editing (type is fixed)
    document.getElementById('connectorTypePicker').classList.add('d-none');
    switchConnectorType(type);

    let c;
    if (type === 'chat')      c = connectors.find(x => x.id === id);
    else if (type === 'whatsapp') c = waConnectors.find(x => x.id === id);
    else if (type === 'voice')    c = voiceConnectors.find(x => x.id === id);
    else if (type === 'sms')      c = smsConnectors.find(x => x.id === id);
    else if (type === 'email')    c = emailConnectors.find(x => x.id === id);
    if (!c) return;

    document.getElementById('connectorModalTitle').innerHTML = '<i class="bi bi-pencil me-2"></i>Edit Connector';
    document.getElementById('connectorId').value = c.id;
    document.getElementById('cName').value = c.name || '';
    document.getElementById('cDescription').value = c.description || '';
    document.getElementById('cIsActive').checked = c.is_active;
    populateFlowDropdown();
    document.getElementById('cFlowId').value = c.flow_id || '';

    if (type === 'chat') {
        document.getElementById('cAllowedOrigins').value = (c.allowed_origins || ['*']).join(', ');
        const s = c.style || {};
        document.getElementById('sTitle').value = s.title || 'Chat with us';
        document.getElementById('sSubtitle').value = s.subtitle || '';
        document.getElementById('sPrimaryColor').value = s.primary_color || '#0d6efd';
        document.getElementById('sPrimaryColorHex').value = s.primary_color || '#0d6efd';
        const swEdit = document.getElementById('colorSwatch');
        if (swEdit) swEdit.style.background = s.primary_color || '#0d6efd';
        document.getElementById('sPosition').value = s.position || 'bottom-right';
        document.getElementById('sTheme').value = s.theme || 'light';
        document.getElementById('sLogoUrl').value = s.logo_url || '';
        document.getElementById('sWidth').value = s.width || '370px';
        document.getElementById('sHeight').value = s.height || '520px';
        const tbody = document.getElementById('metaFieldsBody');
        tbody.innerHTML = '';
        (c.meta_fields || []).forEach(mf => addMetaFieldRow(null, mf));
        fillProactive(c.proactive_triggers || {});
        document.getElementById('existingKeyPanel').classList.remove('d-none');
        document.getElementById('displayApiKey').value = c.api_key;
        updateMetaFieldsEmpty();
        updatePreview();
    } else if (type === 'whatsapp') {
        fillWaFields(c);
        updateWaCredentialHints();
    } else if (type === 'voice') {
        fillVoiceFields(c);
    } else if (type === 'sms') {
        fillSmsFields(c);
        updateSmsCredentialHints();
    } else if (type === 'email') {
        fillEmailFields(c);
    }
    connectorModal.show();
}

// ── Field helpers for typed connectors ──────────────────────────────────────
function clearWaFields() {
    ['waProvider','waBusinessPhone','waPhoneNumberId','waWabaId','waAccessToken',
     'waVerifyToken','waAccountSid','waAuthToken','waApiKey'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = el.tagName === 'SELECT' ? el.options[0]?.value || '' : '';
    });
    const wi = document.getElementById('waWebhookInfo');
    if (wi) wi.style.display = 'none';
}
function fillWaFields(c) {
    document.getElementById('waProvider').value       = c.provider || 'meta_cloud';
    document.getElementById('waBusinessPhone').value  = c.business_phone_number || '';
    document.getElementById('waPhoneNumberId').value  = c.phone_number_id || '';
    document.getElementById('waWabaId').value         = c.waba_id || '';
    document.getElementById('waAccessToken').value    = '';  // never pre-fill secret
    document.getElementById('waVerifyToken').value    = c.verify_token || '';
    document.getElementById('waAccountSid').value     = c.account_sid || '';
    document.getElementById('waAuthToken').value      = '';
    document.getElementById('waApiKey').value         = '';
}
function clearVoiceFields() {
    ['voiceProvider','voiceAccountSid','voiceAuthToken','voiceApiKey',
     'voiceApiSecret','voiceSipDomain','voiceDidNumbers','voiceTwilioAppSid',
     'voiceCallerIdOverride'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = el.tagName === 'SELECT' ? el.options[0]?.value || '' : '';
    });
}
function fillVoiceFields(c) {
    document.getElementById('voiceProvider').value          = c.provider || 'twilio';
    document.getElementById('voiceAccountSid').value        = c.account_sid || '';
    document.getElementById('voiceAuthToken').value         = '';
    document.getElementById('voiceApiKey').value            = c.api_key || '';
    document.getElementById('voiceApiSecret').value         = '';
    document.getElementById('voiceSipDomain').value         = c.sip_domain || '';
    document.getElementById('voiceDidNumbers').value        = (c.did_numbers || []).join('\n');
    document.getElementById('voiceTwilioAppSid').value      = c.twiml_app_sid || '';
    document.getElementById('voiceCallerIdOverride').value  = c.caller_id_override || '';
    updateVoiceCredentialHints();
}

// Updates field labels, placeholders, visibility and the credential guide based on the selected voice provider.
// ─── Hints are split into two sections ────────────────────────────────────────
// "In WizzardChat"     — what to fill in the fields below.
// "On provider portal" — external configuration you must do on the provider's dashboard / server.
function updateVoiceCredentialHints() {
    const provider = document.getElementById('voiceProvider')?.value || 'twilio';

    // ── Per-provider config ────────────────────────────────────────────────────
    // fields: which of the six credential fields to show (true = visible)
    //   sid | token | key | secret | sip | callerId
    const config = {
        twilio: {
            sid:    'Account SID',    sidPh: 'ACxxxxxxxxxxxxxxxx',
            token:  'Auth Token',     tokenPh: 'Auth token (Twilio console)',
            key:    'API Key SID',    keyPh: 'SKxxxxxxxxxxxxxxxx — only needed for agent softphone',
            secret: 'API Key Secret', secPh: 'API Key Secret — only needed for agent softphone',
            sip:    null,
            fields: { sid: true, token: true, key: true, secret: true, sip: false, callerId: false },
            hint:
                '<b>In WizzardChat:</b> Account SID + Auth Token are required for all calls. '
                + 'API Key SID, API Key Secret and TwiML App SID are only needed for the agent browser softphone.<br>'
                + '<b>On the Twilio console:</b> WizzardChat supplies the status callback URL automatically — no extra setup needed.',
        },
        vonage: {
            sid:    'API Key',        sidPh: 'Vonage API key',
            token:  'API Secret',     tokenPh: 'Vonage API secret',
            key:    'Application ID', keyPh: 'Vonage Voice Application ID',
            secret: 'Private Key',    secPh: 'Leave blank — set via Vonage dashboard',
            sip:    'SIP Domain',     sipPh: 'sip.vonage.com',
            fields: { sid: true, token: true, key: true, secret: true, sip: true, callerId: false },
            hint:
                '<b>In WizzardChat:</b> Account SID = Vonage API Key. Auth Token = Vonage API Secret. API Key = Voice Application ID.<br>'
                + '<b>On the Vonage dashboard:</b> Voice Application → '
                + 'Answer URL = <code>GET https://your-host/api/v1/voice/ncco/{attempt_id}</code> '
                + '· Event URL = <code>POST https://your-host/api/v1/voice/vonage/event/{attempt_id}</code>.',
        },
        telnyx: {
            sid:    'Profile ID',      sidPh: 'Telnyx Connection Profile ID',
            token:  'API Key',         tokenPh: 'TELNYXxxxxxxxxxxxxxxxx (v2 key)',
            key:    null,
            secret: null,
            sip:    'TeXML App ID',    sipPh: 'TeXML App ID or Connection Profile ID (from Telnyx portal)',
            fields: { sid: true, token: true, key: false, secret: false, sip: true, callerId: false },
            hint:
                '<b>In WizzardChat:</b> Auth Token = Telnyx API v2 key. '
                + 'SIP Domain = TeXML App ID or Connection Profile ID — both found in your Telnyx portal.<br>'
                + '<b>On the Telnyx portal:</b> TeXML App → Webhook URL = '
                + '<code>POST https://your-host/api/v1/voice/telnyx/event/{attempt_id}</code>.',
        },
        africastalking: {
            sid:    'Username', sidPh: "Africa's Talking username",
            token:  'API Key',  tokenPh: "Africa's Talking API key",
            key:    null,
            secret: null,
            sip:    null,
            fields: { sid: true, token: true, key: false, secret: false, sip: false, callerId: false },
            hint:
                "<b>In WizzardChat:</b> Account SID = AT username. Auth Token = AT API key.<br>"
                + "<b>On the AT dashboard:</b> Voice → Callback URL = "
                + "<code>POST https://your-host/api/v1/voice/at/event/{attempt_id}</code>.",
        },
        asterisk: {
            sid:    'ARI Username', sidPh: 'Username from ari.conf',
            token:  'ARI Password', tokenPh: 'Password from ari.conf',
            key:    'Stasis App',   keyPh: 'Stasis application name — e.g. wizzardchat',
            secret: 'SIP Trunk',    secPh: 'Trunk name from channels.conf — e.g. voip_ms',
            sip:    'Host:Port',    sipPh: '192.168.1.100:8088',
            fields: { sid: true, token: true, key: true, secret: true, sip: true, callerId: true },
            hint:
                '<b>In WizzardChat:</b> SIP Domain = Asterisk host:8088. Account SID + Auth Token = ARI credentials from <code>ari.conf</code>. '
                + 'API Key = Stasis app name. API Secret = SIP trunk name. Caller ID Override = outbound number shown to contacts.<br>'
                + '<b>On Asterisk:</b> Add the Stasis app to <code>ari.conf</code>. '
                + 'Route inbound DIDs in your dialplan to <code>Stasis(wizzardchat)</code>.',
        },
        freeswitch: {
            sid:    'ESL Username', sidPh: 'Usually ClueCon (event_socket.conf)',
            token:  'ESL Password', tokenPh: 'ESL password from event_socket.conf',
            key:    'SIP Gateway',  keyPh: 'Gateway name from sofia.conf — e.g. voip_ms',
            secret: 'Outbound Caller ID', secPh: '+27210000001',
            sip:    'Host:Port',    sipPh: '192.168.1.50:8021',
            fields: { sid: true, token: true, key: true, secret: true, sip: true, callerId: true },
            hint:
                '<b>In WizzardChat:</b> SIP Domain = FreeSWITCH host:8021 (ESL port). '
                + 'Account SID = ESL username. Auth Token = ESL password. '
                + 'API Key = outbound SIP gateway name. API Secret = outbound caller ID.<br>'
                + '<b>On FreeSWITCH:</b> Route inbound DIDs to mod_httapi: '
                + '<code>POST https://your-host/api/v1/inbound/freeswitch</code>.',
        },
        '3cx': {
            sid:    'OAuth2 Client ID',     sidPh: 'client_id from 3CX portal',
            token:  'OAuth2 Client Secret', tokenPh: 'client_secret from 3CX portal',
            key:    'Agent Extension',      keyPh: '101',
            secret: null,
            sip:    'Host:Port',            sipPh: 'your-pbx.3cx.eu:5001',
            fields: { sid: true, token: true, key: true, secret: false, sip: true, callerId: true },
            hint:
                '<b>In WizzardChat:</b> SIP Domain = 3CX REST API host:port. '
                + 'Account SID = OAuth2 client_id. Auth Token = OAuth2 client_secret. '
                + 'API Key = default agent extension number.<br>'
                + '<b>On the 3CX management console:</b> Settings → CRM Integration → Webhook URL = '
                + '<code>POST https://your-host/api/v1/inbound/3cx</code>.',
        },
        generic: {
            sid:    'Account SID',   sidPh: 'Provider account identifier',
            token:  'Auth Token',    tokenPh: 'Provider auth token',
            key:    'API Key',       keyPh: 'API key',
            secret: 'API Secret',    secPh: 'API secret',
            sip:    'SIP Domain',    sipPh: 'sip.example.com',
            fields: { sid: true, token: true, key: true, secret: true, sip: true, callerId: false },
            hint: null,
        },
    };

    const h = config[provider] || config.generic;

    // ── Apply labels and placeholders ─────────────────────────────────────────
    const _set = (id, val) => { const el = document.getElementById(id); if (el && val) el.textContent = val; };
    const _ph  = (id, val) => { const el = document.getElementById(id); if (el && val) el.placeholder = val; };
    if (h.sid)    { _set('lblVoiceAccountSid', h.sid);    _ph('voiceAccountSid', h.sidPh); }
    if (h.token)  { _set('lblVoiceAuthToken',  h.token);  _ph('voiceAuthToken',  h.tokenPh); }
    if (h.key)    { _set('lblVoiceApiKey',     h.key);    _ph('voiceApiKey',     h.keyPh); }
    if (h.secret) { _set('lblVoiceApiSecret',  h.secret); _ph('voiceApiSecret',  h.secPh); }
    if (h.sip)    { _set('lblVoiceSipDomain',  h.sip);    _ph('voiceSipDomain',  h.sipPh); }

    // ── Show / hide credential fields ─────────────────────────────────────────
    const _vis = (id, show) => { const el = document.getElementById(id); if (el) el.style.display = show ? '' : 'none'; };
    const f = h.fields || {};
    _vis('voiceAccountSidWrap',  f.sid     !== false);
    _vis('voiceAuthTokenWrap',   f.token   !== false);
    _vis('voiceApiKeyWrap',      f.key     !== false);
    _vis('voiceApiSecretWrap',   f.secret  !== false);
    _vis('voiceSipDomainWrap',   f.sip     !== false);
    _vis('voiceCallerIdWrap',    f.callerId === true);
    // TwiML App SID — only for Twilio
    _vis('voiceTwimlAppWrap',    provider === 'twilio');

    // ── Hint banner — uses innerHTML so bold/code tags render ─────────────────
    const hintEl = document.getElementById('voiceCredHint');
    if (hintEl) { hintEl.style.display = h.hint ? '' : 'none'; hintEl.innerHTML = h.hint || ''; }
}

// ── Per-provider field visibility for WhatsApp connectors ────────────────────
function updateWaCredentialHints() {
    const p = document.getElementById('waProvider')?.value || 'meta_cloud';

    // true = show, false = hide
    const fields = {
        meta_cloud:  { phoneNumberId: true,  wabaId: true,  accessToken: true,  verifyToken: true,  accountSid: false, authToken: false, apiKey: false },
        twilio:      { phoneNumberId: false, wabaId: false, accessToken: false, verifyToken: false, accountSid: true,  authToken: true,  apiKey: false },
        '360dialog': { phoneNumberId: false, wabaId: false, accessToken: false, verifyToken: false, accountSid: false, authToken: false, apiKey: true  },
        vonage:      { phoneNumberId: false, wabaId: false, accessToken: false, verifyToken: false, accountSid: false, authToken: false, apiKey: true  },
        generic:     { phoneNumberId: false, wabaId: false, accessToken: false, verifyToken: true,  accountSid: false, authToken: false, apiKey: true  },
    };
    const hints = {
        meta_cloud:  '<b>In WizzardChat:</b> Phone Number ID, WABA ID and Access Token come from Meta Business Suite → WhatsApp → API Setup.',
        twilio:      '<b>In WizzardChat:</b> Account SID and Auth Token are from your Twilio Console. Set the inbound webhook URL below on your Twilio phone number.',
        '360dialog': '<b>In WizzardChat:</b> API Key is generated in your 360dialog Hub account under Channels.',
        vonage:      '<b>In WizzardChat:</b> API Key is from Vonage Dashboard → API Settings → WhatsApp.',
        generic:     '<b>In WizzardChat:</b> Verify Token is used to validate webhook challenge requests. API Key is your provider credential.',
    };

    const f = fields[p] || fields.meta_cloud;
    const _vis = (id, show) => { const el = document.getElementById(id); if (el) el.style.display = show ? '' : 'none'; };
    _vis('waPhoneNumberIdWrap', f.phoneNumberId);
    _vis('waWabaIdWrap',        f.wabaId);
    _vis('waAccessTokenWrap',   f.accessToken);
    _vis('waVerifyTokenWrap',   f.verifyToken);
    _vis('waAccountSidWrap',    f.accountSid);
    _vis('waAuthTokenWrap',     f.authToken);
    _vis('waApiKeyWrap',        f.apiKey);

    const hintEl = document.getElementById('waCredHint');
    if (hintEl) { hintEl.style.display = hints[p] ? '' : 'none'; hintEl.innerHTML = hints[p] || ''; }
}

// ── Per-provider field visibility for SMS connectors ─────────────────────────
function updateSmsCredentialHints() {
    const p = document.getElementById('smsProvider')?.value || 'twilio';

    const fields = {
        twilio:         { accountSid: true,  authToken: true,  apiKey: false, apiSecret: false },
        vonage:         { accountSid: false, authToken: false, apiKey: true,  apiSecret: true  },
        africastalking: { accountSid: true,  authToken: true,  apiKey: false, apiSecret: false },
        generic:        { accountSid: false, authToken: false, apiKey: true,  apiSecret: true  },
    };
    const labels = {
        twilio:         { accountSid: 'Account SID',    authToken: 'Auth Token'  },
        africastalking: { accountSid: 'AT Username',    authToken: 'AT API Key'  },
        vonage:         { accountSid: 'Account SID',    authToken: 'Auth Token'  },
        generic:        { accountSid: 'Account SID',    authToken: 'Auth Token'  },
    };
    const hints = {
        twilio:         '<b>In WizzardChat:</b> Account SID and Auth Token are from the Twilio Console home page.',
        vonage:         "<b>In WizzardChat:</b> API Key and API Secret are from Vonage Dashboard → API Settings.",
        africastalking: "<b>In WizzardChat:</b> AT Username = your Africa's Talking account username. AT API Key = from the AT dashboard → Settings → API Key.",
        generic:        null,
    };

    const f = fields[p] || fields.twilio;
    const l = labels[p] || labels.twilio;
    const _vis = (id, show) => { const el = document.getElementById(id); if (el) el.style.display = show ? '' : 'none'; };
    _vis('smsAccountSidWrap', f.accountSid);
    _vis('smsAuthTokenWrap',  f.authToken);
    _vis('smsApiKeyWrap',     f.apiKey);
    _vis('smsApiSecretWrap',  f.apiSecret);

    // Update labels for providers with non-standard field names
    const lblSid = document.getElementById('lblSmsAccountSid');
    const lblTok = document.getElementById('lblSmsAuthToken');
    if (lblSid) lblSid.textContent = l.accountSid;
    if (lblTok) lblTok.textContent = l.authToken;

    const hintEl = document.getElementById('smsCredHint');
    if (hintEl) { hintEl.style.display = hints[p] ? '' : 'none'; hintEl.innerHTML = hints[p] || ''; }
}

function clearSmsFields() {
    ['smsProvider','smsAccountSid','smsAuthToken','smsApiKey',
     'smsApiSecret','smsFromNumber'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = el.tagName === 'SELECT' ? el.options[0]?.value || '' : '';
    });
}
function fillSmsFields(c) {
    document.getElementById('smsProvider').value      = c.provider || 'twilio';
    document.getElementById('smsAccountSid').value    = c.account_sid || '';
    document.getElementById('smsAuthToken').value     = '';
    document.getElementById('smsApiKey').value        = c.api_key || '';
    document.getElementById('smsApiSecret').value     = '';
    document.getElementById('smsFromNumber').value    = c.from_number || '';
}
function clearEmailFields() {
    ['emailImapHost','emailImapUsername','emailImapPassword','emailImapFolder',
     'emailSmtpHost','emailSmtpUsername','emailSmtpPassword',
     'emailFromAddress','emailFromName'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    document.getElementById('emailImapPort').value     = '993';
    document.getElementById('emailSmtpPort').value     = '587';
    document.getElementById('emailImapFolder').value   = 'INBOX';
    document.getElementById('emailPollInterval').value = '60';
    const ssl = document.getElementById('emailImapUseSsl');
    if (ssl) ssl.checked = true;
    const tls = document.getElementById('emailSmtpUseTls');
    if (tls) tls.checked = true;
}
function fillEmailFields(c) {
    document.getElementById('emailImapHost').value     = c.imap_host || '';
    document.getElementById('emailImapPort').value     = c.imap_port || 993;
    document.getElementById('emailImapUsername').value = c.imap_username || '';
    document.getElementById('emailImapPassword').value = '';           // never pre-fill
    document.getElementById('emailImapUseSsl').checked = c.imap_use_ssl !== false;
    document.getElementById('emailImapFolder').value   = c.imap_folder || 'INBOX';
    document.getElementById('emailPollInterval').value = c.poll_interval_seconds || 60;
    document.getElementById('emailSmtpHost').value     = c.smtp_host || '';
    document.getElementById('emailSmtpPort').value     = c.smtp_port || 587;
    document.getElementById('emailSmtpUsername').value = c.smtp_username || '';
    document.getElementById('emailSmtpPassword').value = '';           // never pre-fill
    document.getElementById('emailSmtpUseTls').checked = c.smtp_use_tls !== false;
    document.getElementById('emailFromAddress').value  = c.from_address || '';
    document.getElementById('emailFromName').value     = c.from_name || '';
}

async function saveConnector() {
    const name = document.getElementById('cName').value.trim();
    if (!name) { alert('Name is required'); return; }
    const type = document.getElementById('connectorType').value || 'chat';

    let endpoint, body;
    const commonFields = {
        name,
        description: document.getElementById('cDescription').value.trim() || null,
        flow_id: document.getElementById('cFlowId').value || null,
        is_active: document.getElementById('cIsActive').checked,
    };

    if (type === 'chat') {
        const originsRaw = document.getElementById('cAllowedOrigins').value.trim();
        const origins = originsRaw.split(',').map(s => s.trim()).filter(Boolean);
        body = {
            ...commonFields,
            allowed_origins: origins.length ? origins : ['*'],
            style: {
                title: document.getElementById('sTitle').value,
                subtitle: document.getElementById('sSubtitle').value,
                primary_color: document.getElementById('sPrimaryColorHex').value,
                position: document.getElementById('sPosition').value,
                theme: document.getElementById('sTheme').value,
                logo_url: document.getElementById('sLogoUrl').value,
                width: document.getElementById('sWidth').value,
                height: document.getElementById('sHeight').value,
            },
            meta_fields: collectMetaFields(),
            proactive_triggers: collectProactive(),
        };
        endpoint = '/api/v1/connectors';
    } else if (type === 'whatsapp') {
        body = {
            ...commonFields,
            provider: document.getElementById('waProvider').value,
            business_phone_number: document.getElementById('waBusinessPhone').value.trim() || null,
            phone_number_id: document.getElementById('waPhoneNumberId').value.trim() || null,
            waba_id: document.getElementById('waWabaId').value.trim() || null,
            verify_token: document.getElementById('waVerifyToken').value.trim() || null,
            account_sid: document.getElementById('waAccountSid').value.trim() || null,
        };
        const at = document.getElementById('waAccessToken').value.trim();
        const au = document.getElementById('waAuthToken').value.trim();
        const ak = document.getElementById('waApiKey').value.trim();
        if (at) body.access_token = at;
        if (au) body.auth_token = au;
        if (ak) body.api_key = ak;
        endpoint = '/api/v1/whatsapp-connectors';
    } else if (type === 'voice') {
        body = {
            ...commonFields,
            provider: document.getElementById('voiceProvider').value,
            account_sid: document.getElementById('voiceAccountSid').value.trim() || null,
            api_key: document.getElementById('voiceApiKey').value.trim() || null,
            sip_domain: document.getElementById('voiceSipDomain').value.trim() || null,
            twiml_app_sid: document.getElementById('voiceTwilioAppSid').value.trim() || null,
            caller_id_override: document.getElementById('voiceCallerIdOverride').value.trim() || null,
            did_numbers: document.getElementById('voiceDidNumbers').value.trim()
                .split('\n').map(s => s.trim()).filter(Boolean),
        };
        const at = document.getElementById('voiceAuthToken').value.trim();
        const as_ = document.getElementById('voiceApiSecret').value.trim();
        if (at) body.auth_token = at;
        if (as_) body.api_secret = as_;
        endpoint = '/api/v1/voice-connectors';
    } else if (type === 'sms') {
        body = {
            ...commonFields,
            provider: document.getElementById('smsProvider').value,
            account_sid: document.getElementById('smsAccountSid').value.trim() || null,
            api_key: document.getElementById('smsApiKey').value.trim() || null,
            from_number: document.getElementById('smsFromNumber').value.trim() || null,
        };
        const at = document.getElementById('smsAuthToken').value.trim();
        const as_ = document.getElementById('smsApiSecret').value.trim();
        if (at) body.auth_token = at;
        if (as_) body.api_secret = as_;
        endpoint = '/api/v1/sms-connectors';
    } else if (type === 'email') {
        body = {
            ...commonFields,
            imap_host:    document.getElementById('emailImapHost').value.trim() || null,
            imap_port:    parseInt(document.getElementById('emailImapPort').value, 10) || 993,
            imap_username: document.getElementById('emailImapUsername').value.trim() || null,
            imap_use_ssl: document.getElementById('emailImapUseSsl').checked,
            imap_folder:  document.getElementById('emailImapFolder').value.trim() || 'INBOX',
            poll_interval_seconds: parseInt(document.getElementById('emailPollInterval').value, 10) || 60,
            smtp_host:     document.getElementById('emailSmtpHost').value.trim() || null,
            smtp_port:     parseInt(document.getElementById('emailSmtpPort').value, 10) || 587,
            smtp_username: document.getElementById('emailSmtpUsername').value.trim() || null,
            smtp_use_tls:  document.getElementById('emailSmtpUseTls').checked,
            from_address:  document.getElementById('emailFromAddress').value.trim() || null,
            from_name:     document.getElementById('emailFromName').value.trim() || null,
        };
        const ip = document.getElementById('emailImapPassword').value.trim();
        const sp = document.getElementById('emailSmtpPassword').value.trim();
        if (ip) body.imap_password = ip;
        if (sp) body.smtp_password = sp;
        endpoint = '/api/v1/email-connectors';
    }

    let r;
    if (selectedConnectorId) {
        r = await apiFetch(endpoint + '/' + selectedConnectorId, { method: 'PUT', body: JSON.stringify(body) });
    } else {
        r = await apiFetch(endpoint, { method: 'POST', body: JSON.stringify(body) });
    }

    if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert('Error: ' + (err.detail || r.statusText));
        return;
    }
    connectorModal.hide();
    // Reload all connector types
    await Promise.all([loadConnectors(), loadWaConnectors(), loadVoiceConnectors(), loadSmsConnectors(), loadEmailConnectors()]);
}

async function regenerateKey() {
    if (!selectedConnectorId) return;
    if (!confirm('This will invalidate the current API key. Continue?')) return;
    const r = await apiFetch('/api/v1/connectors/' + selectedConnectorId + '/regenerate-key', { method: 'POST' });
    if (r.ok) {
        const updated = await r.json();
        document.getElementById('displayApiKey').value = updated.api_key;
        await loadConnectors();
    }
}

// ─── Meta field rows ──────────────────────────────────────────────────────────
function addMetaFieldRow(e, data = {}) {
    const tbody = document.getElementById('metaFieldsBody');
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td><input type="text" class="form-control form-control-sm mf-name" value="${escHtml(data.name || '')}" placeholder="e.g. customer_id"></td>
        <td><input type="text" class="form-control form-control-sm mf-label" value="${escHtml(data.label || '')}" placeholder="Customer ID"></td>
        <td class="text-center">
            <div class="form-check form-switch d-flex justify-content-center">
                <input class="form-check-input mf-required" type="checkbox" ${data.required ? 'checked' : ''}>
            </div>
        </td>
        <td><input type="text" class="form-control form-control-sm mf-var" value="${escHtml(data.map_to_variable || '')}" placeholder="flow variable name"></td>
        <td>
            <button class="btn btn-sm btn-outline-danger mf-remove" type="button"><i class="bi bi-x"></i></button>
        </td>`;
    tr.querySelector('.mf-remove').addEventListener('click', () => { tr.remove(); updateMetaFieldsEmpty(); });
    tbody.appendChild(tr);
    updateMetaFieldsEmpty();
}

function collectMetaFields() {
    const rows = document.querySelectorAll('#metaFieldsBody tr');
    return Array.from(rows).map(tr => ({
        name: tr.querySelector('.mf-name')?.value.trim() || '',
        label: tr.querySelector('.mf-label')?.value.trim() || '',
        required: tr.querySelector('.mf-required')?.checked || false,
        map_to_variable: tr.querySelector('.mf-var')?.value.trim() || '',
    })).filter(mf => mf.name);
}

function updateMetaFieldsEmpty() {
    const has = document.querySelectorAll('#metaFieldsBody tr').length > 0;
    document.getElementById('metaFieldsEmpty')?.classList.toggle('d-none', has);
}

// ─── Proactive triggers ─────────────────────────────────────────────────────────────────────
const TRIGGER_TYPES = [
    { value: 'time_on_page',   label: 'Time on page (seconds)' },
    { value: 'scroll_depth',   label: 'Scroll depth (%)'       },
    { value: 'exit_intent',    label: 'Exit intent (mouse-out)' },
    { value: 'element_in_view', label: 'Element in view (CSS selector)' },
];

function fillProactive(pt) {
    document.getElementById('ptEnabled').checked = !!(pt.enabled);
    document.getElementById('ptNudgeEnabled').checked = (pt.nudge?.enabled !== false);
    document.getElementById('ptAutoOpen').checked = !!(pt.nudge?.auto_open);
    document.getElementById('ptNudgeMessage').value = pt.nudge?.message || '👋 Need help?';
    document.getElementById('ptNudgeDelay').value = pt.nudge?.delay_seconds || 0;
    const container = document.getElementById('ptRulesContainer');
    container.innerHTML = '';
    (pt.triggers || []).forEach(r => addTriggerRule(r));
    updateTriggerRulesEmpty();
}

function collectProactive() {
    const triggers = Array.from(document.querySelectorAll('.pt-rule-row')).map(row => ({
        type:     row.querySelector('.pt-type').value,
        value:    row.querySelector('.pt-value').value !== '' ? (isNaN(row.querySelector('.pt-value').value) ? row.querySelector('.pt-value').value : Number(row.querySelector('.pt-value').value)) : null,
        selector: row.querySelector('.pt-selector').value.trim() || null,
        repeat:   row.querySelector('.pt-repeat').checked,
    }));
    return {
        enabled:  document.getElementById('ptEnabled').checked,
        triggers,
        nudge: {
            enabled:        document.getElementById('ptNudgeEnabled').checked,
            auto_open:      document.getElementById('ptAutoOpen').checked,
            message:        document.getElementById('ptNudgeMessage').value.trim() || '👋 Need help?',
            delay_seconds:  parseInt(document.getElementById('ptNudgeDelay').value, 10) || 0,
        },
    };
}

function addTriggerRule(data) {
    data = data || { type: 'time_on_page', value: 30, repeat: false };
    const container = document.getElementById('ptRulesContainer');
    const div = document.createElement('div');
    div.className = 'pt-rule-row d-flex gap-2 align-items-end mb-2';
    const typeOpts = TRIGGER_TYPES.map(t =>
        `<option value="${t.value}"${data.type === t.value ? ' selected' : ''}>${escHtml(t.label)}</option>`
    ).join('');
    const needsSel = data.type === 'element_in_view';
    div.innerHTML = `
        <div style="min-width:190px">
            <label class="form-label small mb-1">Trigger type</label>
            <select class="form-select form-select-sm pt-type">${typeOpts}</select>
        </div>
        <div class="pt-value-wrap" style="min-width:100px;${needsSel ? 'display:none' : ''}">
            <label class="form-label small mb-1">Value</label>
            <input type="number" class="form-control form-control-sm pt-value" value="${data.value ?? 30}" min="1">
        </div>
        <div class="pt-selector-wrap" style="flex:1;${needsSel ? '' : 'display:none'}">
            <label class="form-label small mb-1">CSS selector</label>
            <input type="text" class="form-control form-control-sm pt-selector" value="${escHtml(data.selector || '')}" placeholder="#pricing">
        </div>
        <div class="text-center" style="padding-bottom:4px">
            <div class="form-check form-switch mb-0">
                <input class="form-check-input pt-repeat" type="checkbox" title="Repeat on next page load"${data.repeat ? ' checked' : ''}>
                <label class="form-check-label small">Repeat</label>
            </div>
        </div>
        <div style="padding-bottom:2px">
            <button class="btn btn-sm btn-outline-danger pt-remove" type="button"><i class="bi bi-x"></i></button>
        </div>`;
    // Show/hide value vs selector on type change
    const typeEl  = div.querySelector('.pt-type');
    const valWrap = div.querySelector('.pt-value-wrap');
    const selWrap = div.querySelector('.pt-selector-wrap');
    typeEl.addEventListener('change', function () {
        const isSel = this.value === 'element_in_view';
        const isExit = this.value === 'exit_intent';
        valWrap.style.display  = (isSel || isExit) ? 'none' : '';
        selWrap.style.display  = isSel ? '' : 'none';
    });
    div.querySelector('.pt-remove').addEventListener('click', () => { div.remove(); updateTriggerRulesEmpty(); });
    container.appendChild(div);
    updateTriggerRulesEmpty();
}

function updateTriggerRulesEmpty() {
    const has = document.querySelectorAll('.pt-rule-row').length > 0;
    document.getElementById('ptRulesEmpty')?.classList.toggle('d-none', has);
}

// ─── Preview ──────────────────────────────────────────────────────────────────
function updatePreview() {
    const color = document.getElementById('sPrimaryColorHex')?.value || '#0d6efd';
    const title = document.getElementById('sTitle')?.value || 'Chat with us';
    const subtitle = document.getElementById('sSubtitle')?.value || '';

    const header = document.getElementById('previewHeader');
    if (header) header.style.background = color;
    document.getElementById('previewTitle').textContent = title;
    document.getElementById('previewSubtitle').textContent = subtitle;
    const userBubble = document.getElementById('previewUserBubble');
    if (userBubble) userBubble.style.background = color;
}

// ─────────────────────────────────────────────────────────────────────────────
// Snippet modal
// ─────────────────────────────────────────────────────────────────────────────
function bindSnippetModal() {
    document.getElementById('btnCopySnippet')?.addEventListener('click', () => {
        const code = document.getElementById('snippetCode')?.textContent || '';
        navigator.clipboard.writeText(code).then(() => {
            const btn = document.getElementById('btnCopySnippet');
            btn.innerHTML = '<i class="bi bi-check me-1"></i>Copied!';
            setTimeout(() => { btn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copy'; }, 2000);
        });
    });
}

async function openSnippet(id) {
    const r = await apiFetch('/api/v1/connectors/' + id + '/snippet');
    if (!r.ok) return;
    const data = await r.json();
    const connector = connectors.find(c => c.id === id);
    const metaFields = connector?.meta_fields || [];

    document.getElementById('snippetCode').textContent = data.snippet;

    // Build metadata example
    let metaExStr = '<!-- Optionally set metadata before including the script -->\n<script>\n';
    metaExStr += 'window.WizzardChat = {\n  apiKey: \'' + data.api_key + '\',\n  serverUrl: \'' + data.server_url + '\'';
    if (metaFields.length) {
        metaExStr += ',\n  // Pre-supply metadata fields (must match configured field names)\n  metadata: {\n';
        metaFields.forEach((mf, i) => {
            metaExStr += '    ' + mf.name + ': "..."' + (i < metaFields.length - 1 ? ',' : '') + '  // → ' + (mf.map_to_variable || mf.name) + '\n';
        });
        metaExStr += '  }';
    }
    metaExStr += '\n};\n<\/script>';
    document.getElementById('snippetMetaExample').textContent = metaExStr;

    // Test link
    const testUrl = data.server_url + '/chat-preview?key=' + data.api_key;
    document.getElementById('snippetTestLink').href = testUrl;

    snippetModal.show();
}

// ─────────────────────────────────────────────────────────────────────────────
// Delete modal
// ─────────────────────────────────────────────────────────────────────────────
function bindDeleteModal() {
    document.getElementById('btnConfirmDelete')?.addEventListener('click', async () => {
        if (!deleteTargetId) return;
        const typeEndpoints = {
            chat:      '/api/v1/connectors/',
            whatsapp:  '/api/v1/whatsapp-connectors/',
            voice:     '/api/v1/voice-connectors/',
            sms:       '/api/v1/sms-connectors/',
            email:     '/api/v1/email-connectors/',
        };
        const endpoint = (typeEndpoints[deleteTargetType] || typeEndpoints.chat) + deleteTargetId;
        const r = await apiFetch(endpoint, { method: 'DELETE' });
        if (r.ok || r.status === 204) {
            deleteModal.hide();
            await Promise.all([loadConnectors(), loadWaConnectors(), loadVoiceConnectors(), loadSmsConnectors(), loadEmailConnectors()]);
        } else {
            alert('Delete failed');
        }
    });
}

function openDeleteConfirm(id, name, type) {
    deleteTargetId = id;
    deleteTargetType = type || 'chat';
    document.getElementById('deleteConnectorName').textContent = name;
    deleteModal.show();
}

// ─── Webhook info modal (for typed connectors) ────────────────────────────
async function openWebhookInfo(id, type) {
    let endpoint;
    if (type === 'whatsapp') endpoint = '/api/v1/whatsapp-connectors/' + id + '/webhook-info';
    else if (type === 'voice') endpoint = '/api/v1/voice-connectors/' + id + '/webhook-info';
    else if (type === 'sms')   endpoint = '/api/v1/sms-connectors/' + id + '/webhook-info';
    else return;
    const r = await apiFetch(endpoint);
    if (!r.ok) { alert('Could not retrieve webhook info'); return; }
    const data = await r.json();
    // Build a simple info display in a small modal or alert
    let msg = 'Inbound Webhook URL:\n' + (data.inbound_url || data.webhook_url || '—') + '\n\n';
    if (data.verify_token) msg += 'Verify Token: ' + data.verify_token + '\n';
    if (data.instructions) msg += '\nSetup:\n' + data.instructions;
    alert(msg);
}

// ─────────────────────────────────────────────────────────────────────────────
// Live Chat Inbox – Agent WebSocket
// ─────────────────────────────────────────────────────────────────────────────
function initAgentWs() {
    const token = _token();
    const wsBase = (window.location.origin.replace(/^http/, 'ws'));
    const wsUrl = wsBase + '/ws/agent?token=' + encodeURIComponent(token);
    agentWs = new WebSocket(wsUrl);

    agentWs.onopen = () => {
        setInboxStatus('Connected');
    };

    agentWs.onmessage = e => {
        let msg;
        try { msg = JSON.parse(e.data); } catch { return; }
        handleAgentMessage(msg);
    };

    agentWs.onclose = () => {
        setInboxStatus('Disconnected – reconnecting…');
        agentWs = null;
        setTimeout(initAgentWs, 3000);
    };

    agentWs.onerror = () => agentWs?.close();
}

function handleAgentMessage(msg) {
    switch (msg.type) {
        case 'sessions':
            sessions = {};
            (msg.data || []).forEach(s => { sessions[s.session_key] = s; });
            renderSessionList();
            break;

        case 'new_session':
            sessions[msg.session.session_key] = msg.session;
            renderSessionList();
            showInboxBadge();
            break;

        case 'message':
            if (msg.session_id === activeSessionKey) {
                appendChatMessage(msg.from || 'visitor', msg.text, msg.timestamp);
            }
            break;

        case 'session_update':
            if (sessions[msg.session?.session_key]) {
                sessions[msg.session.session_key] = { ...sessions[msg.session.session_key], ...msg.session };
                renderSessionList();
                if (msg.session.session_key === activeSessionKey) updateChatHeader();
            }
            break;

        case 'session_closed':
            delete sessions[msg.session_id];
            renderSessionList();
            if (activeSessionKey === msg.session_id) {
                document.getElementById('chatMsgs').innerHTML = '';
                activeSessionKey = null;
                updateChatHeader();
            }
            break;

        case 'typing':
            if (msg.session_id === activeSessionKey) {
                const el = document.getElementById('agentTypingStatus');
                if (el) {
                    el.textContent = 'Visitor is typing…';
                    clearTimeout(el._t);
                    el._t = setTimeout(() => { el.textContent = ''; }, 3000);
                }
            }
            break;
    }
}

function renderSessionList() {
    const list = document.getElementById('sessionList');
    const noSess = document.getElementById('noSessions');
    const count = document.getElementById('sessionCount');
    const keys = Object.keys(sessions);

    count.textContent = keys.length;
    if (!keys.length) {
        noSess?.classList.remove('d-none');
        list.querySelectorAll('.inbox-session').forEach(el => el.remove());
        return;
    }
    noSess?.classList.add('d-none');
    list.querySelectorAll('.inbox-session').forEach(el => el.remove());

    keys.forEach(key => {
        const s = sessions[key];
        const statusBadge = {
            active:        '<span class="wz-badge wz-status-in-flow">active</span>',
            waiting_agent: '<span class="wz-badge wz-status-waiting">waiting</span>',
            with_agent:    '<span class="wz-badge wz-status-with-agent">with agent</span>',
            closed:        '<span class="wz-badge wz-status-closed">closed</span>',
        }[s.status] || '';

        const el = document.createElement('a');
        el.href = '#';
        el.className = 'list-group-item list-group-item-action inbox-session p-2' + (key === activeSessionKey ? ' active' : '');
        el.innerHTML = `
            <div class="d-flex justify-content-between align-items-start">
                <span class="fw-semibold">${escHtml(s.visitor_name || 'Visitor')}</span>
                ${statusBadge}
            </div>
            <div class="small text-muted text-truncate">${escHtml(s.connector_name || '')}</div>
            <div class="d-flex justify-content-between">
                <span class="small text-muted text-truncate">${escHtml(s.page_url || '')}</span>
            </div>`;
        el.addEventListener('click', e => { e.preventDefault(); openChatSession(key); });
        list.appendChild(el);
    });
}

function openChatSession(sessionKey) {
    activeSessionKey = sessionKey;
    renderSessionList();  // re-render to update active class
    document.getElementById('chatMsgs').innerHTML = '';
    updateChatHeader();

    const sess = sessions[sessionKey];
    if (sess?.metadata) {
        const metaEl = document.getElementById('chatMeta');
        const metaContent = document.getElementById('chatMetaContent');
        if (metaEl && metaContent) {
            const pairs = Object.entries(sess.metadata || {}).slice(0, 8)
                .map(([k, v]) => `<span class="me-2"><strong>${escHtml(k)}:</strong> ${escHtml(String(v))}</span>`)
                .join('');
            metaContent.innerHTML = pairs;
            metaEl.classList.toggle('d-none', !pairs);
        }
    }
}

function updateChatHeader() {
    const sess = sessions[activeSessionKey];
    const nameEl = document.getElementById('chatVisitorName');
    const statusEl = document.getElementById('chatStatus');
    const msgInput = document.getElementById('agentMsgInput');
    const sendBtn = document.getElementById('btnAgentSend');
    const takeBtn = document.getElementById('btnTakeSession');
    const releaseBtn = document.getElementById('btnReleaseSession');
    const closeBtn = document.getElementById('btnCloseSession');

    if (!sess) {
        if (nameEl) nameEl.textContent = 'Select a session';
        if (statusEl) statusEl.className = 'badge ms-2 d-none';
        [msgInput, sendBtn].forEach(el => el && (el.disabled = true));
        [takeBtn, releaseBtn, closeBtn].forEach(el => el?.classList.add('d-none'));
        return;
    }

    if (nameEl) nameEl.textContent = sess.visitor_name || 'Visitor';

    const statusClasses = { active: 'wz-status-in-flow', waiting_agent: 'wz-status-waiting', with_agent: 'wz-status-with-agent', closed: 'wz-status-closed' };
    if (statusEl) {
        statusEl.className = 'wz-badge ms-2 ' + (statusClasses[sess.status] || 'wz-status-inactive');
        statusEl.textContent = sess.status?.replace('_', ' ');
    }

    const withAgent = sess.status === 'with_agent';
    if (msgInput) msgInput.disabled = !withAgent;
    if (sendBtn) sendBtn.disabled = !withAgent;
    takeBtn?.classList.toggle('d-none', sess.status !== 'waiting_agent');
    releaseBtn?.classList.toggle('d-none', !withAgent);
    closeBtn?.classList.toggle('d-none', !activeSessionKey);

    // Bind action buttons (re-bind each time)
    if (takeBtn && !takeBtn._bound) {
        takeBtn._bound = true;
        takeBtn.addEventListener('click', () => {
            agentWs?.send(JSON.stringify({ type: 'take', session_id: activeSessionKey }));
        });
    }
    if (releaseBtn && !releaseBtn._bound) {
        releaseBtn._bound = true;
        releaseBtn.addEventListener('click', () => {
            agentWs?.send(JSON.stringify({ type: 'release', session_id: activeSessionKey }));
        });
    }
    if (closeBtn && !closeBtn._bound) {
        closeBtn._bound = true;
        closeBtn.addEventListener('click', () => {
            if (confirm('Close this session?')) {
                agentWs?.send(JSON.stringify({ type: 'close', session_id: activeSessionKey }));
            }
        });
    }

    // Send message binding
    const agentSend = document.getElementById('btnAgentSend');
    if (agentSend && !agentSend._bound) {
        agentSend._bound = true;
        agentSend.addEventListener('click', doAgentSend);
    }
    const inp = document.getElementById('agentMsgInput');
    if (inp && !inp._bound) {
        inp._bound = true;
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doAgentSend(); }
        });
    }
}

function doAgentSend() {
    if (!activeSessionKey) return;
    const inp = document.getElementById('agentMsgInput');
    const text = inp?.value.trim();
    if (!text) return;
    agentWs?.send(JSON.stringify({ type: 'message', session_id: activeSessionKey, text }));
    appendChatMessage('agent', text);
    inp.value = '';
}

function appendChatMessage(role, text, timestamp) {
    const msgs = document.getElementById('chatMsgs');
    if (!msgs) return;
    const div = document.createElement('div');
    const cls = { visitor: 'from-visitor', bot: 'from-bot', agent: 'from-agent', system: 'system' }[role] || 'from-visitor';
    div.className = 'chat-bubble ' + cls;
    div.textContent = text;
    if (timestamp) {
        const ts = document.createElement('div');
        ts.className = 'text-muted small';
        ts.style.fontSize = '10px';
        ts.textContent = new Date(timestamp).toLocaleTimeString();
        div.appendChild(ts);
    }
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function setInboxStatus(msg) {
    // Could show in a small status bar; skip for now
    console.log('[Inbox]', msg);
}

function showInboxBadge() {
    const b = document.getElementById('inboxBadge');
    if (b) { b.classList.remove('d-none'); b.textContent = Object.keys(sessions).length; }
}

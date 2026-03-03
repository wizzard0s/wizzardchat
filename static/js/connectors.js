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
let flows = [];
let selectedConnectorId = null;  // ID of connector open in edit modal
let deleteTargetId = null;

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
    if (!_token()) { window.location.href = '/'; return; }

    connectorModal = new bootstrap.Modal(document.getElementById('connectorModal'));
    snippetModal   = new bootstrap.Modal(document.getElementById('snippetModal'));
    deleteModal    = new bootstrap.Modal(document.getElementById('deleteConnectorModal'));

    // Show current user
    try {
        const r = await apiFetch('/api/v1/auth/me');
        if (!r.ok) { window.location.href = '/'; return; }
        const user = await r.json();
        document.getElementById('currentUser').textContent = user.full_name || user.username;
    } catch { window.location.href = '/'; return; }

    bindTabSwitcher();
    bindConnectorModal();
    bindSnippetModal();
    bindDeleteModal();

    await loadFlows();
    await loadConnectors();

    document.getElementById('btnLogout')?.addEventListener('click', () => {
        localStorage.removeItem('wizzardchat_token'); window.location.href = '/';
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

async function loadFlows() {
    const r = await apiFetch('/api/v1/flows');
    if (!r.ok) return;
    const data = await r.json();
    flows = Array.isArray(data) ? data : (data.items || []);
}

// ─────────────────────────────────────────────────────────────────────────────
// Render connector cards
// ─────────────────────────────────────────────────────────────────────────────
function renderConnectorList() {
    const el = document.getElementById('connectorsList');
    const empty = document.getElementById('connectorsEmpty');

    if (!connectors.length) {
        empty.classList.remove('d-none');
        el.querySelectorAll('.col').forEach(c => c.remove());
        return;
    }
    empty.classList.add('d-none');

    // Remove old cards
    el.querySelectorAll('.col').forEach(c => c.remove());

    connectors.forEach(c => {
        const linkedFlow = flows.find(f => f.id === c.flow_id);
        const statusDot = c.is_active
            ? '<span class="connector-status bg-success me-1"></span>Active'
            : '<span class="connector-status bg-secondary me-1"></span>Inactive';

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
                        <span class="badge bg-info text-dark"><i class="bi bi-chat me-1"></i>Chat</span>
                    </div>
                    ${c.description ? `<p class="small text-muted mb-2">${escHtml(c.description)}</p>` : ''}
                    <div class="small text-muted mb-1">
                        <i class="bi bi-diagram-3 me-1"></i>
                        ${linkedFlow ? escHtml(linkedFlow.name) : '<em>No flow linked</em>'}
                    </div>
                    <div class="small text-muted font-monospace text-truncate" title="${escHtml(c.api_key)}">
                        <i class="bi bi-key me-1"></i>${c.api_key.slice(0, 18)}…
                    </div>
                </div>
                <div class="card-footer d-flex gap-2 py-2">
                    <button class="btn btn-sm btn-outline-secondary flex-fill btn-edit-connector" data-id="${c.id}">
                        <i class="bi bi-pencil me-1"></i>Edit
                    </button>
                    <button class="btn btn-sm btn-outline-info btn-snippet" data-id="${c.id}">
                        <i class="bi bi-code-slash"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger btn-del-connector" data-id="${c.id}" data-name="${escHtml(c.name)}">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>`;
        el.appendChild(col);

        col.querySelector('.btn-edit-connector')?.addEventListener('click', () => openEditConnector(c.id));
        col.querySelector('.btn-snippet')?.addEventListener('click', () => openSnippet(c.id));
        col.querySelector('.btn-del-connector')?.addEventListener('click', () => openDeleteConfirm(c.id, c.name));
    });
}

function escHtml(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─────────────────────────────────────────────────────────────────────────────
// Create / Edit modal
// ─────────────────────────────────────────────────────────────────────────────
function bindConnectorModal() {
    document.getElementById('btnNewConnector').addEventListener('click', () => openNewConnector());
    document.getElementById('btnSaveConnector').addEventListener('click', saveConnector);
    document.getElementById('btnAddMetaField').addEventListener('click', addMetaFieldRow);
    document.getElementById('btnRegenKey')?.addEventListener('click', regenerateKey);

    // Live style preview
    ['sTitle','sSubtitle','sPrimaryColor','sPrimaryColorHex'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updatePreview);
    });

    // Sync color picker ↔ hex text
    document.getElementById('sPrimaryColor')?.addEventListener('input', e => {
        document.getElementById('sPrimaryColorHex').value = e.target.value;
        updatePreview();
    });
    document.getElementById('sPrimaryColorHex')?.addEventListener('input', e => {
        if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
            document.getElementById('sPrimaryColor').value = e.target.value;
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
    document.getElementById('sPosition').value = 'bottom-right';
    document.getElementById('sTheme').value = 'light';
    document.getElementById('sLogoUrl').value = '';
    document.getElementById('sWidth').value = '370px';
    document.getElementById('sHeight').value = '520px';
    document.getElementById('metaFieldsBody').innerHTML = '';
    document.getElementById('existingKeyPanel').classList.add('d-none');
    populateFlowDropdown();
    updateMetaFieldsEmpty();
    updatePreview();
    connectorModal.show();
}

function openEditConnector(id) {
    const c = connectors.find(x => x.id === id);
    if (!c) return;
    selectedConnectorId = id;
    document.getElementById('connectorModalTitle').innerHTML = '<i class="bi bi-pencil me-2"></i>Edit Connector';
    document.getElementById('connectorId').value = c.id;
    document.getElementById('cName').value = c.name || '';
    document.getElementById('cDescription').value = c.description || '';
    document.getElementById('cAllowedOrigins').value = (c.allowed_origins || ['*']).join(', ');
    document.getElementById('cIsActive').checked = c.is_active;

    const s = c.style || {};
    document.getElementById('sTitle').value = s.title || 'Chat with us';
    document.getElementById('sSubtitle').value = s.subtitle || '';
    document.getElementById('sPrimaryColor').value = s.primary_color || '#0d6efd';
    document.getElementById('sPrimaryColorHex').value = s.primary_color || '#0d6efd';
    document.getElementById('sPosition').value = s.position || 'bottom-right';
    document.getElementById('sTheme').value = s.theme || 'light';
    document.getElementById('sLogoUrl').value = s.logo_url || '';
    document.getElementById('sWidth').value = s.width || '370px';
    document.getElementById('sHeight').value = s.height || '520px';

    // Meta fields
    const tbody = document.getElementById('metaFieldsBody');
    tbody.innerHTML = '';
    (c.meta_fields || []).forEach(mf => addMetaFieldRow(null, mf));

    // Show API key
    document.getElementById('existingKeyPanel').classList.remove('d-none');
    document.getElementById('displayApiKey').value = c.api_key;

    populateFlowDropdown();
    document.getElementById('cFlowId').value = c.flow_id || '';
    updateMetaFieldsEmpty();
    updatePreview();
    connectorModal.show();
}

async function saveConnector() {
    const name = document.getElementById('cName').value.trim();
    if (!name) { alert('Name is required'); return; }

    const originsRaw = document.getElementById('cAllowedOrigins').value.trim();
    const origins = originsRaw.split(',').map(s => s.trim()).filter(Boolean);

    const body = {
        name,
        description: document.getElementById('cDescription').value.trim() || null,
        flow_id: document.getElementById('cFlowId').value || null,
        allowed_origins: origins.length ? origins : ['*'],
        is_active: document.getElementById('cIsActive').checked,
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
    };

    let r;
    if (selectedConnectorId) {
        r = await apiFetch('/api/v1/connectors/' + selectedConnectorId, { method: 'PUT', body: JSON.stringify(body) });
    } else {
        r = await apiFetch('/api/v1/connectors', { method: 'POST', body: JSON.stringify(body) });
    }

    if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert('Error: ' + (err.detail || r.statusText));
        return;
    }
    connectorModal.hide();
    await loadConnectors();
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
        const r = await apiFetch('/api/v1/connectors/' + deleteTargetId, { method: 'DELETE' });
        if (r.ok || r.status === 204) {
            deleteModal.hide();
            await loadConnectors();
        } else {
            alert('Delete failed');
        }
    });
}

function openDeleteConfirm(id, name) {
    deleteTargetId = id;
    document.getElementById('deleteConnectorName').textContent = name;
    deleteModal.show();
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
            active: '<span class="badge bg-primary">active</span>',
            waiting_agent: '<span class="badge bg-warning text-dark">waiting</span>',
            with_agent: '<span class="badge bg-success">with agent</span>',
            closed: '<span class="badge bg-secondary">closed</span>',
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

    const statusColors = { active: 'bg-primary', waiting_agent: 'bg-warning text-dark', with_agent: 'bg-success', closed: 'bg-secondary' };
    if (statusEl) {
        statusEl.className = 'badge ms-2 ' + (statusColors[sess.status] || 'bg-secondary');
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

/**
 * WizzardChat – Agent Panel JS
 * Connects to /ws/agent, manages session list, chat window, and campaign dispatch.
 */
'use strict';

// ─── Auth helpers ────────────────────────────────────────────────────────────
const _token = () => localStorage.getItem('wizzardchat_token') || '';

async function apiFetch(url, opts = {}) {
    opts.headers = Object.assign(
        { Authorization: 'Bearer ' + _token(), 'Content-Type': 'application/json' },
        opts.headers || {}
    );
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/'; }
    return res;
}

// ─── State ───────────────────────────────────────────────────────────────────
let ws = null;
let sessions = {};           // session_key → session data
let activeKey = null;        // currently open session key
let chatHistory = {};        // session_key → [{from, text, ts}]
let currentUserId = null;
let activeCampaignId = null;

let typingTimer = null;

// ─── DOM refs ────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const el = {
    wsStatusDot:      $('wsStatusDot'),
    agentName:        $('agentName'),
    availabilitySel:  $('availabilitySelect'),
    campaignSel:      $('campaignSelect'),
    campaignStatus:   $('campaignStatus'),
    listWaiting:   $('listWaiting'),
    listMine:      $('listMine'),
    listFlow:      $('listFlow'),
    countWaiting:  $('countWaiting'),
    countMine:     $('countMine'),
    countFlow:     $('countFlow'),
    // chat
    noSession:     $('noSession'),
    chatView:      $('chatView'),
    chatName:      $('chatVisitorName'),
    chatMeta:      $('chatVisitorMeta'),
    chatBadge:     $('chatStatusBadge'),
    btnTake:       $('btnTake'),
    btnRelease:    $('btnRelease'),
    btnClose:      $('btnClose'),
    msgList:       $('msgList'),
    typingInd:     $('typingIndicator'),
    msgInput:      $('msgInput'),
    btnSend:       $('btnSend'),
    // emoji & attachment
    emojiBtn:    $('agentEmojiBtn'),
    attachBtn:   $('agentAttachBtn'),
    fileInput:   $('agentFileInput'),
    emojiPicker: $('agentEmojiPicker'),
};

// ─── Init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    if (!_token()) { window.location.href = '/'; return; }

    try {
        const r = await apiFetch('/api/v1/auth/me');
        if (!r.ok) { window.location.href = '/'; return; }
        const user = await r.json();
        currentUserId = String(user.id);
        el.agentName.textContent = user.full_name || user.username;
    } catch { window.location.href = '/'; return; }

    await loadCampaigns();
    connectWs();
    bindUI();
});

// ─── Availability ─────────────────────────────────────────────────────────────
const AVAILABILITY_COLORS = {
    available: '#198754', admin: '#0d6efd', lunch: '#ffc107',
    break: '#fd7e14', training: '#6f42c1', meeting: '#20c997', offline: '#6c757d'
};

function setAvailabilityUI(status) {
    if (!el.availabilitySel) return;
    el.availabilitySel.value = status;
    el.availabilitySel.className = 'form-select form-select-sm av-' + status;
    if (el.wsStatusDot && el.wsStatusDot.classList.contains('online')) {
        el.wsStatusDot.style.background = AVAILABILITY_COLORS[status] || '#198754';
    }
}

// ─── Campaigns ───────────────────────────────────────────────────────────────
async function loadCampaigns() {
    try {
        const r = await apiFetch('/api/v1/campaigns');
        if (!r.ok) return;
        const camps = await r.json();
        el.campaignSel.innerHTML = '<option value="">— All campaigns —</option>';
        camps.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name;
            el.campaignSel.appendChild(opt);
        });
        // If only one campaign, auto-select it locally too (server will also send campaign_set)
        if (camps.length === 1) {
            el.campaignSel.value = camps[0].id;
        }
    } catch { /* ignore */ }
}

// ─── WebSocket ───────────────────────────────────────────────────────────────
function connectWs() {
    const wsBase = window.location.origin.replace(/^http/, 'ws');
    const url = wsBase + '/ws/agent?token=' + encodeURIComponent(_token());
    ws = new WebSocket(url);

    ws.onopen = () => {
        el.wsStatusDot.className = 'status-dot online';
        el.campaignStatus.textContent = activeCampaignId ? 'Connected – campaign active' : 'Connected – receiving all sessions';
        // Re-apply campaign filter after reconnect
        if (activeCampaignId) {
            wsSend({ type: 'set_campaign', campaign_id: activeCampaignId });
        }
        // Do NOT re-send availability here — the server sends availability_set on every
        // connect with the persisted state. Re-sending from the dropdown would overwrite
        // the server's stored value with the HTML default ("offline") on every page load.
    };

    ws.onclose = () => {
        el.wsStatusDot.className = 'status-dot offline';
        el.campaignStatus.textContent = 'Disconnected – reconnecting…';
        setTimeout(connectWs, 3000);
    };

    ws.onerror = () => {
        el.wsStatusDot.className = 'status-dot offline';
    };

    ws.onmessage = e => {
        try { handleWsMsg(JSON.parse(e.data)); } catch { /* ignore */ }
    };
}

function wsSend(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

// ─── Emoji picker ────────────────────────────────────────────────────────────────────────
const AGENT_EMOJIS = [
  '\u{1F600}','\u{1F603}','\u{1F604}','\u{1F601}','\u{1F606}','\u{1F605}','\u{1F923}','\u{1F602}','\u{1F642}','\u{1F609}','\u{1F60A}','\u{1F607}',
  '\u{1F970}','\u{1F60D}','\u{1F618}','\u{1F61B}','\u{1F61C}','\u{1F61D}','\u{1F911}','\u{1F917}','\u{1F914}','\u{1F610}','\u{1F611}','\u{1F636}',
  '\u{1F60F}','\u{1F612}','\u{1F644}','\u{1F62C}','\u{1F60C}','\u{1F614}','\u{1F62A}','\u{1F634}','\u{1F637}','\u{1F922}','\u{1F927}','\u{1F635}',
  '\u{1F60E}','\u{1F615}','\u{1F61F}','\u{1F641}','\u2639\uFE0F','\u{1F62E}','\u{1F632}','\u{1F633}','\u{1F97A}','\u{1F626}','\u{1F627}','\u{1F628}',
  '\u{1F630}','\u{1F625}','\u{1F622}','\u{1F62D}','\u{1F631}','\u{1F616}','\u{1F623}','\u{1F61E}','\u{1F629}','\u{1F62B}','\u{1F624}','\u{1F621}',
  '\u{1F620}','\u{1F92C}','\u{1F608}','\u{1F47F}','\u{1F480}','\u{1F4A9}','\u{1F921}','\u{1F47B}','\u{1F47D}',
  '\u{1F44D}','\u{1F44E}','\u{1F44F}','\u{1F64C}','\u{1F91D}','\u{1F64F}','\u{1F4AA}','\u{1F44B}','\u270C\uFE0F','\u{1F91E}','\u{1F919}',
  '\u{1F448}','\u{1F449}','\u{1F446}','\u{1F447}','\u261D\uFE0F','\u270A','\u{1F44A}',
  '\u2764\uFE0F','\u{1F9E1}','\u{1F49B}','\u{1F49A}','\u{1F499}','\u{1F49C}','\u{1F596}','\u{1F494}','\u{1F495}','\u{1F49E}','\u{1F493}','\u{1F497}','\u{1F496}','\u{1F498}',
  '\u{1F525}','\u2B50','\u{1F31F}','\u2728','\u26A1','\u{1F389}','\u{1F38A}','\u{1F388}','\u{1F381}','\u{1F3C6}','\u{1F451}','\u{1F48E}',
  '\u2705','\u274C','\u26A0\uFE0F','\u{1F4A1}','\u{1F514}','\u{1F3B5}','\u{1F3B6}','\u{1F4F1}','\u{1F4BB}','\u{1F511}','\u{1F4DD}','\u{1F4CC}','\u{1F4CE}','\u{1F50D}','\u{1F4AC}',
  '\u{1F34E}','\u{1F34A}','\u{1F34B}','\u{1F347}','\u{1F353}','\u{1F352}','\u{1F351}','\u{1F354}','\u{1F35F}','\u{1F355}','\u{1F32E}','\u2615','\u{1F37A}','\u{1F377}','\u{1F973}',
  '\u{1F436}','\u{1F431}','\u{1F42D}','\u{1F430}','\u{1F98A}','\u{1F43B}','\u{1F43C}','\u{1F981}','\u{1F438}','\u{1F435}','\u{1F648}','\u{1F649}','\u{1F64A}','\u{1F414}',
  '\u{1F33A}','\u{1F338}','\u{1F33C}','\u{1F33B}','\u{1F339}','\u{1F340}','\u{1F33F}','\u{1F331}','\u{1F30D}','\u{1F319}','\u{1F31E}','\u26C5','\u{1F308}','\u2744\uFE0F',
  '\u{1F697}','\u2708\uFE0F','\u{1F680}','\u{1F3E0}','\u26BD','\u{1F3C0}','\u{1F3AE}','\u{1F3AF}','\u{1F3B2}','\u265F'
];
let agentEmojiOpen = false;

function buildAgentEmojiPicker() {
    if (!el.emojiPicker || el.emojiPicker.childNodes.length) return;
    AGENT_EMOJIS.forEach(em => {
        const btn = document.createElement('button');
        btn.textContent = em; btn.type = 'button'; btn.title = em;
        btn.addEventListener('click', e => {
            e.stopPropagation();
            if (el.msgInput && !el.msgInput.disabled) {
                const pos = el.msgInput.selectionStart || el.msgInput.value.length;
                el.msgInput.value = el.msgInput.value.slice(0, pos) + em + el.msgInput.value.slice(pos);
                el.msgInput.focus();
            }
            closeAgentEmojiPicker();
        });
        el.emojiPicker.appendChild(btn);
    });
}

function toggleAgentEmojiPicker(e) {
    if (e) e.stopPropagation();
    agentEmojiOpen = !agentEmojiOpen;
    el.emojiPicker?.classList.toggle('ep-open', agentEmojiOpen);
}

function closeAgentEmojiPicker() {
    agentEmojiOpen = false;
    el.emojiPicker?.classList.remove('ep-open');
}

// ─── File upload (agent) ───────────────────────────────────────────────────────────────────
function agentUpload(file) {
    if (!file || !activeKey) return;
    const fd = new FormData();
    fd.append('file', file);
    fetch(`/api/v1/sessions/${activeKey}/attachment`, {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + _token() },
        body: fd,
    }).then(r => r.ok ? r.json() : null).then(data => {
        if (!data) return;
        const ts = new Date().toISOString();
        const entry = { from: 'agent', text: data.url, ts, subtype: 'attachment', filename: data.filename };
        if (!chatHistory[activeKey]) chatHistory[activeKey] = [];
        chatHistory[activeKey].push(entry);
        if (sessions[activeKey]) (sessions[activeKey].message_log = sessions[activeKey].message_log || []).push(entry);
        appendBubble('agent', data.url, ts, true, 'attachment', data.filename);
    }).catch(err => console.error('agent upload error:', err));
    if (el.fileInput) el.fileInput.value = '';
}

// ─── WS message handler ───────────────────────────────────────────────────────
function handleWsMsg(msg) {
    switch (msg.type) {

        case 'sessions':
            sessions = {};
            (msg.data || []).forEach(s => { sessions[s.session_key] = s; });
            renderSessionLists();
            break;

        case 'new_session':
        case 'session_assigned': {
            const s = msg.session;
            sessions[s.session_key] = s;
            renderSessionLists();
            // Auto-open if it was assigned to me and nothing is open
            if (msg.type === 'session_assigned' && s.agent_id === currentUserId && !activeKey) {
                openSession(s.session_key);
            }
            break;
        }

        case 'session_update': {
            const s = msg.session;
            sessions[s.session_key] = { ...sessions[s.session_key], ...s };
            renderSessionLists();
            if (s.session_key === activeKey) updateChatHeader();
            break;
        }

        case 'session_closed': {
            const key = msg.session_id;
            if (sessions[key]) sessions[key].status = 'closed';
            renderSessionLists();
            if (key === activeKey) updateChatHeader();
            break;
        }

        case 'message': {
            // Agent received a visitor message forwarded to them
            const key = msg.session_id;
            if (!chatHistory[key]) chatHistory[key] = [];
            const entry = { from: msg.from, text: msg.text, ts: msg.timestamp, subtype: msg.subtype || 'message', filename: msg.filename || '' };
            chatHistory[key].push(entry);
            if (sessions[key]) (sessions[key].message_log = sessions[key].message_log || []).push(entry);
            if (key === activeKey) appendBubble(msg.from, msg.text, msg.timestamp, true, msg.subtype || 'message', msg.filename || '');
            // Flash session card if not active
            if (key !== activeKey) flashSessionCard(key);
            break;
        }

        case 'campaign_set':
            activeCampaignId = msg.campaign_id;
            el.campaignSel.value = msg.campaign_id || '';
            el.campaignStatus.textContent = msg.campaign_id
                ? (msg.auto_selected ? 'Campaign auto-selected – dispatch on' : 'Campaign active – auto-dispatch on')
                : 'Serving all campaigns';
            break;

        case 'availability_set':
            setAvailabilityUI(msg.status || 'available');
            break;

        case 'typing':
            if (msg.session_id === activeKey) {
                el.typingInd.textContent = 'Visitor is typing…';
                clearTimeout(typingTimer);
                typingTimer = setTimeout(() => { el.typingInd.textContent = ''; }, 3000);
            }
            break;
    }
}

// ─── Session list rendering ───────────────────────────────────────────────────
function renderSessionLists() {
    const waiting = [], mine = [], flow = [];

    Object.values(sessions).forEach(s => {
        if (s.status === 'closed') return;
        if (s.status === 'waiting_agent') waiting.push(s);
        else if (s.status === 'with_agent' && s.agent_id === currentUserId) mine.push(s);
        else if (s.status === 'active') flow.push(s);
    });

    el.countWaiting.textContent = waiting.length;
    el.countMine.textContent = mine.length;
    el.countFlow.textContent = flow.length;

    el.listWaiting.innerHTML = waiting.map(s => sessionCardHTML(s, 'waiting')).join('') || emptyRow();
    el.listMine.innerHTML    = mine.map(s => sessionCardHTML(s, 'mine')).join('') || emptyRow();
    el.listFlow.innerHTML    = flow.map(s => sessionCardHTML(s, '')).join('') || emptyRow();

    // Bind clicks
    document.querySelectorAll('.session-card').forEach(card => {
        card.addEventListener('click', () => openSession(card.dataset.key));
    });

    // Highlight active
    if (activeKey) {
        document.querySelectorAll(`.session-card[data-key="${activeKey}"]`).forEach(c => c.classList.add('active'));
    }
}

function emptyRow() {
    return '<p class="text-muted small px-3 py-1 mb-0">None</p>';
}

function sessionCardHTML(s, cssClass) {
    const meta = s.metadata || {};
    const name = s.visitor_name || meta.name || 'Visitor';
    const page = meta.page_url ? new URL(meta.page_url).pathname : '';
    const isActive = s.session_key === activeKey ? ' active' : '';
    const age = s.created_at ? timeAgo(s.created_at) : '';
    return `
    <div class="session-card ${cssClass}${isActive} px-3 py-2" data-key="${esc(s.session_key)}">
        <div class="d-flex justify-content-between align-items-start">
            <span class="fw-semibold small">${esc(name)}</span>
            <span class="text-muted" style="font-size:.7rem;">${age}</span>
        </div>
        ${page ? `<div class="text-muted" style="font-size:.72rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${esc(page)}</div>` : ''}
    </div>`;
}

// ─── Open session ─────────────────────────────────────────────────────────────
function openSession(key) {
    activeKey = key;

    el.noSession.style.display = 'none';
    el.chatView.style.display = 'flex';

    renderSessionLists();   // re-highlight

    const s = sessions[key];
    if (!chatHistory[key]) chatHistory[key] = [];

    // Seed chatHistory from persisted message_log if not already populated
    if (!chatHistory[key] || chatHistory[key].length === 0) {
        chatHistory[key] = (s.message_log || []).map(e => ({
            from: e.from, text: e.text, ts: e.ts, subtype: e.subtype || 'message', filename: e.filename || ''
        }));
    }

    // Also update local sessions object so navigating away and back re-seeds correctly
    if (s.message_log) sessions[key].message_log = s.message_log;

    // Render chat header
    updateChatHeader();

    // Render message history
    el.msgList.innerHTML = '';
    const history = chatHistory[key];

    if (!history.length) {
        appendBubble('system', 'No messages yet.', null, false);
    } else {
        // Find index of first agent message to insert separator
        const firstAgentIdx = history.findIndex(m => m.from === 'agent');
        history.forEach((m, i) => {
            if (i === firstAgentIdx) {
                // Insert a visual divider before the first agent message
                const div = document.createElement('div');
                div.className = 'chat-divider';
                div.textContent = '\u2014 Agent joined \u2014';
                el.msgList.appendChild(div);
            }
            appendBubble(m.from, m.text, m.ts, false, m.subtype, m.filename || '');
        });
    }
    scrollToBottom();
    el.typingInd.textContent = '';

    // Enable input if I'm the agent
    const canType = s && s.status === 'with_agent' && s.agent_id === currentUserId;
    el.msgInput.disabled = !canType;
    el.btnSend.disabled  = !canType;
    if (el.emojiBtn) el.emojiBtn.disabled = !canType;
    if (el.attachBtn) el.attachBtn.disabled = !canType;
    el.msgInput.focus();
}

function updateChatHeader() {
    const s = sessions[activeKey];
    if (!s) return;

    const meta = s.metadata || {};
    el.chatName.textContent = s.visitor_name || meta.name || 'Visitor';
    el.chatMeta.textContent = [meta.email, meta.page_url ? '🔗 ' + meta.page_url : ''].filter(Boolean).join(' · ');

    const badgeMap = {
        active:        ['bg-info',    'In Flow'],
        waiting_agent: ['bg-warning', 'Waiting'],
        with_agent:    ['bg-success', 'Live Chat'],
        closed:        ['bg-secondary','Closed'],
    };
    const [cls, label] = badgeMap[s.status] || ['bg-secondary', s.status];
    el.chatBadge.className = 'badge ' + cls;
    el.chatBadge.textContent = label;

    // Buttons
    const isMine = s.agent_id === currentUserId;
    el.btnTake.style.display    = s.status === 'waiting_agent' ? '' : 'none';
    el.btnRelease.style.display = (s.status === 'with_agent' && isMine) ? '' : 'none';
    el.btnClose.style.display   = s.status !== 'closed' ? '' : 'none';

    const canType = s.status === 'with_agent' && isMine;
    el.msgInput.disabled = !canType;
    el.btnSend.disabled  = !canType;
    if (el.emojiBtn) el.emojiBtn.disabled = !canType;
    if (el.attachBtn) el.attachBtn.disabled = !canType;
}

// ─── Chat bubbles ─────────────────────────────────────────────────────────────
function appendBubble(from, text, ts, doScroll = true, subtype = 'message', filename = '') {
    const div = document.createElement('div');
    div.className = 'bubble ' + (from || 'system');
    const time = ts ? new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    let inner;
    if (subtype === 'attachment') {
        const url = text;
        const fname = filename || url.split('/').pop() || 'File';
        const isImage = /\.(jpe?g|png|gif|webp|bmp|svg)(\?|$)/i.test(url) || url.startsWith('blob:');
        if (isImage) {
            inner = `<a href="${esc(url)}" target="_blank"><img src="${esc(url)}" class="attach-img" alt="${esc(fname)}"></a>`;
        } else {
            inner = `<a href="${esc(url)}" target="_blank" class="attach-file">&#x1F4CE; ${esc(fname)}</a>`;
        }
    } else if (subtype === 'menu' && text && text.includes('\n')) {
        const nl = text.indexOf('\n');
        const question = text.slice(0, nl);
        const optsRaw = text.slice(nl + 1);
        const opts = optsRaw.split('  |  ').map(o => `<div class="menu-opt-item">&bull; ${esc(o.trim())}</div>`).join('');
        inner = `${esc(question)}<div class="menu-opts-list">${opts}</div>`;
    } else {
        inner = esc(text || '');
    }
    div.innerHTML = `${inner}<div class="meta">${esc(from || 'system')} ${time}</div>`;
    el.msgList.appendChild(div);
    if (doScroll) scrollToBottom();
}

function scrollToBottom() {
    el.msgList.scrollTop = el.msgList.scrollHeight;
}

function flashSessionCard(key) {
    const card = document.querySelector(`.session-card[data-key="${key}"]`);
    if (!card) return;
    card.style.transition = 'background .1s';
    card.style.background = '#4a3000';
    setTimeout(() => { card.style.background = ''; }, 800);
}

// ─── Action buttons ───────────────────────────────────────────────────────────
function bindUI() {
    // Campaign apply
    el.btnSetCampaign?.addEventListener('click', () => {
        const cid = el.campaignSel.value || null;
        activeCampaignId = cid;
        wsSend({ type: 'set_campaign', campaign_id: cid });
    });

    // Availability change
    el.availabilitySel?.addEventListener('change', () => {
        const status = el.availabilitySel.value;
        wsSend({ type: 'set_availability', status });
        setAvailabilityUI(status);
    });

    // Take session
    el.btnTake?.addEventListener('click', () => {
        if (!activeKey) return;
        wsSend({ type: 'take', session_id: activeKey });
        // Optimistically update
        if (sessions[activeKey]) {
            sessions[activeKey].status = 'with_agent';
            sessions[activeKey].agent_id = currentUserId;
        }
        updateChatHeader();
        renderSessionLists();
    });

    // Release session
    el.btnRelease?.addEventListener('click', () => {
        if (!activeKey) return;
        wsSend({ type: 'release', session_id: activeKey });
        if (sessions[activeKey]) {
            sessions[activeKey].status = 'waiting_agent';
            sessions[activeKey].agent_id = null;
        }
        updateChatHeader();
        renderSessionLists();
        el.msgInput.disabled = true;
        el.btnSend.disabled = true;
        if (el.emojiBtn) el.emojiBtn.disabled = true;
        if (el.attachBtn) el.attachBtn.disabled = true;
        closeAgentEmojiPicker();
    });

    // Close session
    el.btnClose?.addEventListener('click', () => {
        if (!activeKey) return;
        if (!confirm('Close this session?')) return;
        wsSend({ type: 'close', session_id: activeKey });
        if (sessions[activeKey]) sessions[activeKey].status = 'closed';
        updateChatHeader();
        renderSessionLists();
        el.msgInput.disabled = true;
        el.btnSend.disabled = true;
        if (el.emojiBtn) el.emojiBtn.disabled = true;
        if (el.attachBtn) el.attachBtn.disabled = true;
        closeAgentEmojiPicker();
    });

    // Send message
    // Also track agent's own sent messages in history so they appear on re-open
    function sendMsg() {
        const text = el.msgInput.value.trim();
        if (!text || !activeKey) return;
        wsSend({ type: 'message', session_id: activeKey, text });
        el.msgInput.value = '';
        // Add to local history + render
        if (!chatHistory[activeKey]) chatHistory[activeKey] = [];
        const ts = new Date().toISOString();
        const entry = { from: 'agent', text, ts, subtype: 'message' };
        chatHistory[activeKey].push(entry);
        if (sessions[activeKey]) (sessions[activeKey].message_log = sessions[activeKey].message_log || []).push(entry);
        appendBubble('agent', text, ts);
    }

    el.btnSend?.addEventListener('click', sendMsg);
    el.msgInput?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
        // Send typing indicator
        wsSend({ type: 'typing', session_id: activeKey });
    });

    // Emoji picker
    buildAgentEmojiPicker();
    el.emojiBtn?.addEventListener('click', e => toggleAgentEmojiPicker(e));
    document.addEventListener('click', e => {
        if (agentEmojiOpen && el.emojiPicker && !el.emojiPicker.contains(e.target) && e.target !== el.emojiBtn) {
            closeAgentEmojiPicker();
        }
    });

    // File attachment
    el.attachBtn?.addEventListener('click', () => { if (el.fileInput) el.fileInput.click(); });
    el.fileInput?.addEventListener('change', function() {
        if (this.files && this.files[0]) agentUpload(this.files[0]);
    });

    // Logout
    $('btnLogout')?.addEventListener('click', () => {
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/';
    });
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function esc(v) {
    return String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function timeAgo(iso) {
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60)  return diff + 's';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    return Math.floor(diff / 3600) + 'h';
}

/**
 * WizzardChat \u2013 Agent Panel JS
 * Connects to /ws/agent, manages session list, chat window, and campaign dispatch.
 * navToggle, accordion init, availability init, and agentName are in sidebar.js
 */
'use strict';


// \u2500\u2500\u2500 Auth helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
const _token = () => localStorage.getItem('wizzardchat_token') || '';

async function apiFetch(url, opts = {}) {
    opts.headers = Object.assign(
        { Authorization: 'Bearer ' + _token(), 'Content-Type': 'application/json' },
        opts.headers || {}
    );
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/login'; }
    return res;
}

// \u2500\u2500\u2500 State \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
let ws = null;
let sessions = {};           // session_key \u2192 session data
let activeKey = null;        // currently open session key
let chatHistory = {};        // session_key \u2192 [{from, text, ts}]
let currentUserId = null;
let activeCampaignId = null;

// Dialler state
let diallerContact = null;   // ContactDiallerOut for next contact
let diallerAttempt = null;   // CampaignAttemptOut after POST /dialler/attempt
let diallerCampaign = null;  // Full campaign object
let diallerProgress = null;  // GET /dialler/progress response
let diallerPollTimer = null; // setInterval handle for progress polling
let diallerOutcomeCode = null; // selected outcome code

// Voice device (dialler softphone)
let _vzDevice        = null;   // WzVoiceDevice instance
let _vzTimerInterval = null;   // setInterval handle for call timer
let _vzMuted         = false;  // current mute state
let _vzConnectedAt   = null;   // Date when call connected

let typingTimer = null;
let sessionOutcomes = {};   // session_key \u2192 [{id, code, label, action_type, ...}]
let wrapTimers = {};         // session_key \u2192 { intervalId, secondsLeft }
let myCapacity = null;       // CapacityOut from /api/v1/agents/me/capacity
let myLoad = { total: 0, voice: 0, chat: 0, whatsapp: 0, email: 0, sms: 0 };
let voiceCall = null;        // { attemptId, contactName, contactPhone, connectedAt, muted, held }
let voiceTimerInterval = null;

// \u2500\u2500\u2500 DOM refs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
    btnClose:           $('btnClose'),
    btnOutcome:         $('btnOutcome'),
    outcomeModal:       $('outcomeModal'),
    outcomeModalMeta:   $('outcomeModalMeta'),
    outcomeModalBody:   $('outcomeModalBody'),
    msgList:       $('msgList'),
    typingInd:     $('typingIndicator'),
    summaryBanner: $('summaryBanner'),
    summaryText:   $('summaryText'),
    // wrap-up panel
    wrapPanel:      $('wrapPanel'),
    wrapCountdown:  $('wrapCountdown'),
    wrapNotes:      $('wrapNotes'),
    wrapOutcomeRow: $('wrapOutcomeRow'),
    msgInput:      $('msgInput'),
    btnSend:       $('btnSend'),
    // emoji & attachment
    emojiBtn:    $('agentEmojiBtn'),
    attachBtn:   $('agentAttachBtn'),
    fileInput:   $('agentFileInput'),
    emojiPicker: $('agentEmojiPicker'),
    // capacity strip
    capOmniBar:    $('capOmniBar'),
    capOmniCount:  $('capOmniCount'),
    btnPickNext:   $('btnPickNext'),

    // voice card
    voiceCard:       $('voiceCard'),
    vcCallerName:    $('vcCallerName'),
    vcCallerPhone:   $('vcCallerPhone'),
    vcTimer:         $('vcTimer'),
    vcState:         $('vcState'),
    vcBtnMute:       $('vcBtnMute'),
    vcBtnHold:       $('vcBtnHold'),
    vcBtnHangup:     $('vcBtnHangup'),
    vcBtnTransfer:   $('vcBtnTransfer'),
    vcTransferModal: $('vcTransferModal'),
    vcBtnDoTransfer: $('vcBtnDoTransfer'),
    // dialler view
    diallerView:         $('diallerView'),
    dpBtnOpenPanel:      $('dpBtnOpenPanel'),
    dpCampaignName:      $('dpCampaignName'),
    dpTypeBadge:         $('dpTypeBadge'),
    dpStatusBadge:       $('dpStatusBadge'),
    dpDiallerMode:       $('dpDiallerMode'),
    dpProgressText:      $('dpProgressText'),
    dpProgressPct:       $('dpProgressPct'),
    dpProgressBar:       $('dpProgressBar'),
    dpByStatus:          $('dpByStatus'),
    dpLoading:           $('dpLoading'),
    dpExhausted:         $('dpExhausted'),
    dpNoContact:         $('dpNoContact'),
    dpContactCard:       $('dpContactCard'),
    dpContactName:       $('dpContactName'),
    dpContactCompany:    $('dpContactCompany'),
    dpAttemptBadge:      $('dpAttemptBadge'),
    dpTemplateBadge:     $('dpTemplateBadge'),
    dpContactPhone:      $('dpContactPhone'),
    dpContactWa:         $('dpContactWa'),
    dpContactEmail:      $('dpContactEmail'),
    dpContactLang:       $('dpContactLang'),
    dpContactNotes:      $('dpContactNotes'),
    dpActionRow:         $('dpActionRow'),
    dpBtnDial:           $('dpBtnDial'),
    dpBtnNext:           $('dpBtnNext'),
    dpBtnSkip:           $('dpBtnSkip'),
    dpBtnRefresh:        $('dpBtnRefresh'),
    dpOutcomeSection:    $('dpOutcomeSection'),
    dpOutcomePills:      $('dpOutcomePills'),
    dpOutcomeNotes:      $('dpOutcomeNotes'),
    dpBtnSubmitOutcome:  $('dpBtnSubmitOutcome'),
    dpBtnCancelOutcome:  $('dpBtnCancelOutcome'),
    // toolbar
    tbarCampaignBadge:   $('tbarCampaignBadge'),
    tbarCampaignName:    $('tbarCampaignName'),
    // chat header enhancements
    chatHeaderBar:       $('chatHeaderBar'),
    chatChannelBadge:    $('chatChannelBadge'),
    // context bar
    chatContextBar:      $('chatContextBar'),
    ctxContactRef:       $('ctxContactRef'),
    ctxChannelInfo:      $('ctxChannelInfo'),
    ctxTags:             $('ctxTags'),
    // voice input row (in chat area)
    voiceInputRow:       $('voiceInputRow'),
    viTimer:             $('viTimer'),
    viBtnMute:           $('viBtnMute'),
    viBtnHold:           $('viBtnHold'),
    viBtnHangup:         $('viBtnHangup'),
    chatInputRow:        $('chatInputRow'),
    // dialler softphone strip
    dpSoftphone:         $('dpSoftphone'),
    dpSoftphoneStatus:   $('dpSoftphoneStatus'),
    dpSoftphoneTimer:    $('dpSoftphoneTimer'),
    dpBtnSoftMute:       $('dpBtnSoftMute'),
    dpBtnSoftHangup:     $('dpBtnSoftHangup'),
    dpSoftphoneFallback: $('dpSoftphoneFallback'),
    dpFallbackMsg:       $('dpFallbackMsg'),
};

// \u2500\u2500\u2500 Init \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
document.addEventListener('DOMContentLoaded', async () => {
    if (!_token()) { window.location.href = '/login'; return; }

    try {
        const r = await apiFetch('/api/v1/auth/me');
        if (!r.ok) { window.location.href = '/login'; return; }
        const user = await r.json();
        currentUserId = String(user.id);
        el.agentName.textContent = user.full_name || user.username;
    } catch { window.location.href = '/login'; return; }

    await loadCampaigns();
    await loadCapacity();
    connectWs();
    bindUI();
});

// \u2500\u2500\u2500 Availability \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

// \u2500\u2500\u2500 Campaigns \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
async function loadCampaigns() {
    try {
        const r = await apiFetch('/api/v1/campaigns');
        if (!r.ok) { console.error('loadCampaigns: API returned', r.status); return; }
        const camps = await r.json();
        el.campaignSel.innerHTML = '<option value="">\u2014 All campaigns \u2014</option>';
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
    } catch (err) { console.error('loadCampaigns error:', err); }
}

// \u2500\u2500\u2500 WebSocket \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function connectWs() {
    const wsBase = window.location.origin.replace(/^http/, 'ws');
    const url = wsBase + '/ws/agent?token=' + encodeURIComponent(_token());
    ws = new WebSocket(url);

    ws.onopen = () => {
        el.wsStatusDot.className = 'status-dot online';
        el.campaignStatus.textContent = activeCampaignId ? 'Connected \u2013 campaign active' : 'Connected \u2013 receiving all sessions';
        // Re-apply campaign filter after reconnect
        if (activeCampaignId) {
            wsSend({ type: 'set_campaign', campaign_id: activeCampaignId });
        }
        // Do NOT re-send availability here \u2014 the server sends availability_set on every
        // connect with the persisted state. Re-sending from the dropdown would overwrite
        // the server's stored value with the HTML default ("offline") on every page load.
    };

    ws.onclose = () => {
        el.wsStatusDot.className = 'status-dot offline';
        el.campaignStatus.textContent = 'Disconnected \u2013 reconnecting\u2026';
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

// \u2500\u2500\u2500 Emoji picker \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

// \u2500\u2500\u2500 File upload (agent) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

// \u2500\u2500\u2500 WS message handler \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

        case 'session_summary': {
            const sk = msg.session_id;
            if (sessions[sk]) sessions[sk].notes = msg.notes;
            if (sk === activeKey) _showSummary(msg.notes);
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
                ? (msg.auto_selected ? 'Campaign auto-selected \u2013 dispatch on' : 'Campaign active \u2013 auto-dispatch on')
                : 'Serving all campaigns';
            if (msg.campaign_id) {
                if (el.dpBtnOpenPanel) el.dpBtnOpenPanel.style.display = '';
                if (!activeKey) diallerOpen();
            } else {
                if (el.dpBtnOpenPanel) el.dpBtnOpenPanel.style.display = 'none';
                diallerClose();
                if (!activeKey) {
                    if (el.noSession) el.noSession.style.display = '';
                }
            }
            break;

        case 'availability_set':
            setAvailabilityUI(msg.status || 'available');
            break;

        case 'capacity_update':
            myLoad = Object.assign({}, myLoad, msg.load || {});
            updateCapacityBar();
            break;

        case 'call_ringing':
            voiceCall = { attemptId: msg.attempt_id, contactName: null, contactPhone: null, connectedAt: null, muted: false, held: false };
            _showVoiceCard('ringing', 'Ringing\u2026');
            break;

        case 'call_connected':
            voiceCall = {
                attemptId:    msg.attempt_id,
                contactName:  msg.contact_name  || 'Unknown Caller',
                contactPhone: msg.contact_phone || '',
                connectedAt:  msg.connected_at ? new Date(msg.connected_at) : new Date(),
                muted: false,
                held:  false,
            };
            _showVoiceCard('connected', '');
            _startVoiceTimer();
            break;

        case 'call_ended':
            _hideVoiceCard();
            break;

        case 'call_hold_ack':
            if (voiceCall && msg.attempt_id === voiceCall.attemptId) {
                voiceCall.held = !!msg.held;
                _syncVoiceCardState();
            }
            break;

        case 'call_mute_ack':
            if (voiceCall && msg.attempt_id === voiceCall.attemptId) {
                voiceCall.muted = !!msg.muted;
                _syncVoiceCardState();
            }
            break;

        case 'typing':
            if (msg.session_id === activeKey) {
                el.typingInd.textContent = 'Visitor is typing\u2026';
                clearTimeout(typingTimer);
                typingTimer = setTimeout(() => { el.typingInd.textContent = ''; }, 3000);
            }
            break;

        case 'session_flow_redirected': {
            // Agent\u2019s outcome sent the visitor into a new flow \u2014 update local state
            const key = msg.session_id;
            if (sessions[key]) {
                sessions[key].status = 'active';
                sessions[key].agent_id = null;
            }
            renderSessionLists();
            if (key === activeKey) updateChatHeader();
            break;
        }

        case 'session_visitor_left': {
            // Visitor disconnected while agent was assigned \u2014 enter wrap-up
            const key = msg.session_id;
            const secs = msg.wrap_seconds || 120;
            if (sessions[key]) sessions[key].status = 'wrap_up';
            renderSessionLists();
            if (key === activeKey) {
                updateChatHeader();
                startWrapUp(key, secs);
            } else {
                // Pre-load outcomes so the panel is instant when agent switches
                loadSessionOutcomes(key);
                wrapTimers[key] = { intervalId: null, secondsLeft: secs };
            }
            break;
        }
    }   // end switch
}       // end handleWsMsg

// \u2500\u2500 Wrap-up helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

function _fmtCountdown(s) {
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, '0')}`;
}

async function startWrapUp(sessionKey, seconds) {
    stopWrapUp(sessionKey);   // clear any existing timer first

    // Pre-fill notes textarea with AI summary if available
    const s = sessions[sessionKey];
    if (el.wrapNotes) el.wrapNotes.value = (s && s.notes) ? s.notes : '';

    // Load outcomes and render buttons
    await loadSessionOutcomes(sessionKey);
    _renderWrapOutcomes(sessionKey);

    // Show the panel
    if (el.wrapPanel)    el.wrapPanel.classList.add('active');
    if (el.wrapCountdown) el.wrapCountdown.textContent = _fmtCountdown(seconds);

    const state = { intervalId: null, secondsLeft: seconds };
    wrapTimers[sessionKey] = state;

    state.intervalId = setInterval(() => {
        state.secondsLeft -= 1;
        if (el.wrapCountdown) {
            el.wrapCountdown.textContent = _fmtCountdown(state.secondsLeft);
            el.wrapCountdown.classList.toggle('urgent', state.secondsLeft <= 30);
        }
        if (state.secondsLeft <= 0) {
            stopWrapUp(sessionKey);
            // Auto-submit with resolve outcome
            const resolve = (sessionOutcomes[sessionKey] || []).find(o => o.action_type === 'end_interaction') ||
                { id: null, code: 'resolve', label: 'Resolve', action_type: 'end_interaction', outcome_type: 'positive' };
            selectOutcome(resolve);
        }
    }, 1000);
}

function stopWrapUp(sessionKey) {
    const state = wrapTimers[sessionKey];
    if (state && state.intervalId) {
        clearInterval(state.intervalId);
    }
    delete wrapTimers[sessionKey];
    if (sessionKey === activeKey) {
        if (el.wrapPanel) el.wrapPanel.classList.remove('active');
        if (el.wrapCountdown) el.wrapCountdown.classList.remove('urgent');
    }
}

function _renderWrapOutcomes(sessionKey) {
    if (!el.wrapOutcomeRow) return;
    const outcomes = sessionOutcomes[sessionKey] || [];
    // Show first 5 outcomes as quick buttons + a "More..." button
    const quick = outcomes.slice(0, 5);
    let html = quick.map(o => {
        const acls = o.action_type === 'flow_redirect' ? 'flow_redirect' : (o.outcome_type || 'neutral');
        return `<button class="wrap-outcome-btn ${acls}" data-code="${esc(o.code)}">${esc(o.label)}</button>`;
    }).join('');
    if (outcomes.length > 5) {
        html += `<button class="wrap-outcome-btn neutral" id="wrapMoreBtn">More\u2026</button>`;
    }
    el.wrapOutcomeRow.innerHTML = html;
    el.wrapOutcomeRow.querySelectorAll('.wrap-outcome-btn').forEach(btn => {
        if (btn.id === 'wrapMoreBtn') {
            btn.addEventListener('click', () => openOutcomeModal(sessionKey));
            return;
        }
        const o = outcomes.find(x => x.code === btn.dataset.code);
        if (o) btn.addEventListener('click', () => selectOutcome(o));
    });
}
// \u2500\u2500\u2500 Outcome helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

async function loadSessionOutcomes(sessionKey) {
    try {
        const r = await apiFetch(`/api/v1/sessions/${encodeURIComponent(sessionKey)}/outcomes`);
        if (r.ok) {
            sessionOutcomes[sessionKey] = await r.json();
        }
    } catch { /* network error \u2014 fallback below */ }
    // Guarantee at least Resolve if the fetch failed or returned empty
    if (!sessionOutcomes[sessionKey]?.length) {
        sessionOutcomes[sessionKey] = [{
            id: null, code: 'resolve', label: 'Resolve',
            action_type: 'end_interaction', outcome_type: 'positive',
        }];
    }
}

const SENTIMENT_ORDER  = ['negative', 'escalation', 'neutral', 'positive'];
const SENTIMENT_CONFIG = {
    negative:   { label: 'Negative',   icon: 'bi-exclamation-circle-fill', colour: '#dc3545' },
    escalation: { label: 'Escalation', icon: 'bi-arrow-up-circle-fill',    colour: '#fd7e14' },
    neutral:    { label: 'Neutral',    icon: 'bi-dash-circle-fill',         colour: '#6c757d' },
    positive:   { label: 'Positive',   icon: 'bi-check-circle-fill',        colour: '#198754' },
};

function renderOutcomeModal(sessionKey) {
    if (!el.outcomeModalBody) return;
    const outcomes = sessionOutcomes[sessionKey] || [];

    // Group by outcome_type; unknown types fall into neutral
    const groups = {};
    SENTIMENT_ORDER.forEach(t => { groups[t] = []; });
    outcomes.forEach(o => {
        const t = SENTIMENT_ORDER.includes(o.outcome_type) ? o.outcome_type : 'neutral';
        groups[t].push(o);
    });

    // Only render groups that have at least one outcome
    const nonEmpty = SENTIMENT_ORDER.filter(t => groups[t].length);

    // Up to 4 columns \u2014 one per sentiment group present
    // 4 groups \u2192 col-3 (25% each); fewer groups \u2192 col-4 (33%)
    const colClass = nonEmpty.length >= 4 ? 'col-12 col-sm-6 col-lg-3' : 'col-12 col-sm-6 col-lg-4';

    let html = '<div class="row g-3">';
    nonEmpty.forEach(type => {
        const items = groups[type];
        const cfg = SENTIMENT_CONFIG[type];
        html += `<div class="${colClass}">
          <div class="d-flex align-items-center gap-2 mb-2 pb-2" style="border-bottom:1px solid #2e3140;">
            <i class="bi ${cfg.icon}" style="color:${cfg.colour};font-size:.9rem;"></i>
            <span class="fw-semibold small text-uppercase" style="color:${cfg.colour};letter-spacing:.06em;">${cfg.label}</span>
          </div>
          <div class="d-flex flex-column gap-2">`;
        items.forEach(o => {
            const isFlow = o.action_type === 'flow_redirect';
            const badge = isFlow
                ? `<span class="wz-badge wz-flowtype-main mt-1"><i class="bi bi-diagram-2-fill me-1"></i>Redirects to flow</span>`
                : `<span class="badge bg-dark border mt-1" style="border-color:#2e3140!important;"><i class="bi bi-x-circle me-1"></i>Ends session</span>`;
            html += `<button class="outcome-card-btn text-start p-3 rounded"
                      style="background:#252836;border:1px solid #2e3140;border-left:3px solid ${cfg.colour};cursor:pointer;display:block;width:100%;"
                      data-outcome-code="${esc(o.code)}"
                      onmouseover="this.style.background='#2e3240'" onmouseout="this.style.background='#252836'">
              <div class="fw-semibold" style="color:#f8f9fa;">${esc(o.label)}</div>
              ${badge}
            </button>`;
        });
        html += '</div></div>';
    });
    html += '</div>';

    el.outcomeModalBody.innerHTML = html || '<p class="text-muted">No outcomes available.</p>';

    // Bind card clicks
    el.outcomeModalBody.querySelectorAll('.outcome-card-btn').forEach(btn => {
        const code = btn.dataset.outcomeCode;
        const outcome = outcomes.find(o => o.code === code);
        if (outcome) btn.addEventListener('click', () => selectOutcome(outcome));
    });
}

function openOutcomeModal(sessionKey) {
    if (!el.outcomeModal) return;
    const s = sessions[sessionKey];
    const name = s ? (s.visitor_name || (s.metadata || {}).name || 'Visitor') : 'Visitor';
    if (el.outcomeModalMeta) el.outcomeModalMeta.textContent = `Session with ${name}`;
    if (el.outcomeModalBody) el.outcomeModalBody.innerHTML =
        '<div class="text-center py-4 text-muted"><i class="bi bi-hourglass-split me-2"></i>Loading outcomes\u2026</div>';

    bootstrap.Modal.getOrCreateInstance(el.outcomeModal).show();
    loadSessionOutcomes(sessionKey).then(() => renderOutcomeModal(sessionKey));
}

function selectOutcome(outcome) {
    if (!activeKey) return;
    if (el.outcomeModal) bootstrap.Modal.getInstance(el.outcomeModal)?.hide();

    // If in wrap-up, capture any notes the agent typed before closing
    const wrapNote = (el.wrapNotes && el.wrapPanel && el.wrapPanel.classList.contains('active'))
        ? el.wrapNotes.value.trim() : null;

    // Stop the wrap timer for this session
    stopWrapUp(activeKey);

    wsSend({
        type:         'close_with_outcome',
        session_id:   activeKey,
        outcome_id:   outcome.id || null,
        outcome_code: outcome.code || 'resolve',
        notes:        wrapNote || undefined,
    });
    // Optimistic update \u2014 backend confirms via session_flow_redirected or session_closed.
    // Use the outcome's action_type so the card moves to the right list immediately.
    if (sessions[activeKey]) {
        if (outcome.action_type === 'flow_redirect') {
            sessions[activeKey].status   = 'active';
            sessions[activeKey].agent_id = null;
        } else {
            sessions[activeKey].status = 'closed';
        }
    }
    delete sessionOutcomes[activeKey];   // clear cache so next chat loads fresh
    updateChatHeader();
    renderSessionLists();
    el.msgInput.disabled = true;
    el.btnSend.disabled  = true;
    if (el.emojiBtn)  el.emojiBtn.disabled  = true;
    if (el.attachBtn) el.attachBtn.disabled = true;
    closeAgentEmojiPicker();
}

// \u2500\u2500\u2500 Session list rendering \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function renderSessionLists() {
    const waiting = [], mine = [], flow = [], wrap = [];

    Object.values(sessions).forEach(s => {
        if (s.status === 'closed') return;
        if (s.status === 'waiting_agent') waiting.push(s);
        else if (s.status === 'wrap_up' && s.agent_id === currentUserId) wrap.push(s);
        else if (s.status === 'with_agent' && s.agent_id === currentUserId) mine.push(s);
        else if (s.status === 'active') flow.push(s);
    });

    el.countWaiting.textContent = waiting.length;
    el.countMine.textContent = mine.length + wrap.length;
    el.countFlow.textContent = flow.length;

    el.listWaiting.innerHTML = waiting.map(s => sessionCardHTML(s, 'waiting')).join('') || emptyRow();
    // Mine = actively handling + in wrap-up
    el.listMine.innerHTML    = [...mine.map(s => sessionCardHTML(s, 'mine')), ...wrap.map(s => sessionCardHTML(s, 'mine wrap'))].join('') || emptyRow();
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

// \u2500\u2500\u2500 Open session \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function openSession(key) {
    activeKey = key;

    el.noSession.style.display = 'none';
    if (el.diallerView) el.diallerView.style.display = 'none';
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
    _showSummary(s && s.notes ? s.notes : null);

    // Enable input if I'm the agent (not during wrap-up \u2014 visitor already left)
    const canType = s && s.status === 'with_agent' && s.agent_id === currentUserId;
    el.msgInput.disabled = !canType;
    el.btnSend.disabled  = !canType;
    if (el.emojiBtn) el.emojiBtn.disabled = !canType;
    if (el.attachBtn) el.attachBtn.disabled = !canType;
    el.msgInput.focus();

    // If this session is in wrap-up, immediately show the wrap panel
    const isWrap = s && s.status === 'wrap_up' && s.agent_id === currentUserId;
    if (isWrap) {
        const state = wrapTimers[key];
        if (state) {
            // Timer was already ticking in the background \u2014 resume display
            startWrapUp(key, state.secondsLeft);
        } else {
            // No timer running (e.g. page reload) \u2014 start fresh with remaining time
            startWrapUp(key, 120);
        }
    } else {
        if (el.wrapPanel) el.wrapPanel.classList.remove('active');
    }
}

function updateChatHeader() {
    const s = sessions[activeKey];
    if (!s) return;

    const meta = s.metadata || {};
    el.chatName.textContent = s.visitor_name || meta.name || 'Visitor';
    el.chatMeta.textContent = [meta.email, meta.page_url ? '\uD83D\uDD17 ' + meta.page_url : ''].filter(Boolean).join(' \u00B7 ');

    const badgeMap = {
        active:        ['wz-status-in-flow',  'In Flow'],
        waiting_agent: ['wz-status-waiting',  'Waiting'],
        with_agent:    ['wz-status-with-agent','Live Chat'],
        wrap_up:       ['wz-status-wrap-up',  'Wrap-Up'],
        closed:        ['wz-status-closed',   'Closed'],
    };
    const [cls, label] = badgeMap[s.status] || ['wz-status-closed', s.status];
    el.chatBadge.className = 'wz-badge ' + cls;
    el.chatBadge.textContent = label;

    // \u2500\u2500 Channel badge + header border \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const channel = s.channel || (meta.channel) || 'chat';
    const chLabels = { voice: '\uD83D\uDCDE Voice', chat: '\uD83D\uDCAC Chat', whatsapp: '\uD83D\uDFE2 WhatsApp', email: '\u2709 Email', sms: '\uD83D\uDCF1 SMS' };
    const chBadgeCls = { voice: 'ch-badge-voice', chat: 'ch-badge-chat', whatsapp: 'ch-badge-whatsapp', email: 'ch-badge-email', sms: 'ch-badge-sms' };
    const chHeaderCls = { voice: 'ch-voice', chat: 'ch-chat', whatsapp: 'ch-whatsapp', email: 'ch-email', sms: 'ch-sms' };
    if (el.chatChannelBadge) {
        el.chatChannelBadge.textContent = chLabels[channel] || channel;
        el.chatChannelBadge.className = 'chatChannelBadge active ' + (chBadgeCls[channel] || '');
    }
    if (el.chatHeaderBar) {
        el.chatHeaderBar.className = el.chatHeaderBar.className.replace(/\bch-\w+\b/g, '').trim();
        if (chHeaderCls[channel]) el.chatHeaderBar.classList.add(chHeaderCls[channel]);
    }

    // \u2500\u2500 Context bar \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if (el.chatContextBar) {
        const ref = s.session_key ? s.session_key.slice(-8).toUpperCase() : '';
        if (el.ctxContactRef) el.ctxContactRef.textContent = ref ? '#' + ref : '';
        if (el.ctxChannelInfo) el.ctxChannelInfo.textContent = (chLabels[channel] || channel);
        if (el.ctxTags) {
            el.ctxTags.innerHTML = '';
            const tags = s.tags || meta.tags || [];
            tags.forEach(t => {
                const span = document.createElement('span');
                span.className = 'ctx-tag';
                span.textContent = t;
                el.ctxTags.appendChild(span);
            });
        }
        el.chatContextBar.classList.toggle('active', s.status !== 'closed');
    }

    // \u2500\u2500 Voice input row visibility \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const isVoice = channel === 'voice';
    if (el.voiceInputRow) el.voiceInputRow.classList.toggle('active', isVoice && s.status === 'with_agent');
    if (el.chatInputRow)  el.chatInputRow.style.display = (isVoice && s.status === 'with_agent') ? 'none' : '';

    const isMine   = s.agent_id === currentUserId;
    const isWithMe = s.status === 'with_agent' && isMine;
    const isWrap   = s.status === 'wrap_up' && isMine;

    el.btnTake.style.display    = s.status === 'waiting_agent' ? '' : 'none';
    el.btnRelease.style.display = isWithMe ? '' : 'none';
    // Outcome button: available during live chat AND during wrap-up
    if (el.btnOutcome) el.btnOutcome.style.display = (isWithMe || isWrap) ? '' : 'none';
    // Direct close: waiting / in-flow only (not while live or in wrap-up)
    el.btnClose.style.display   = (!isWithMe && !isWrap && s.status !== 'closed') ? '' : 'none';

    // Typing disabled during wrap-up (visitor already left)
    const canType = isWithMe && !isVoice;
    el.msgInput.disabled = !canType;
    el.btnSend.disabled  = !canType;
    if (el.emojiBtn) el.emojiBtn.disabled = !canType;
    if (el.attachBtn) el.attachBtn.disabled = !canType;

    // Show or hide the wrap panel to match current status
    if (isWrap && wrapTimers[activeKey]) {
        startWrapUp(activeKey, wrapTimers[activeKey].secondsLeft);
    } else if (!isWrap) {
        if (el.wrapPanel) el.wrapPanel.classList.remove('active');
    }
}

// \u2500\u2500\u2500 Chat bubbles \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

// \u2500\u2500\u2500 Capacity bar \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
// Hard-coded fallback shown when the API is unreachable (e.g. server restarting).
const _CAP_DEFAULTS = {
    omni_max: 8, channel_max_voice: 1, channel_max_chat: 5,
    channel_max_whatsapp: 3, channel_max_email: 5, channel_max_sms: 5,
    capacity_override_active: false,
    omni_max_is_custom: false, channel_max_voice_is_custom: false,
    channel_max_chat_is_custom: false, channel_max_whatsapp_is_custom: false,
    channel_max_email_is_custom: false, channel_max_sms_is_custom: false,
};

async function loadCapacity() {
    try {
        const r = await apiFetch('/api/v1/agents/me/capacity');
        if (r.ok) {
            myCapacity = await r.json();
        } else {
            // API unavailable \u2014 show defaults so the toolbar is never blank
            myCapacity = { ...myCapacity, ..._CAP_DEFAULTS };
        }
    } catch {
        myCapacity = { ...myCapacity, ..._CAP_DEFAULTS };
    }
    updateCapacityBar();
}

const _CH_ICONS = {
    voice: 'bi-telephone-fill', chat: 'bi-chat-fill',
    whatsapp: 'bi-whatsapp', email: 'bi-envelope-fill', sms: 'bi-phone-fill',
};

function updateCapacityBar() {
    if (!myCapacity) return;
    const total = myLoad.total;
    const omni  = myCapacity.omni_max ?? 8;
    const pct   = Math.min(100, Math.round(total / omni * 100));
    if (el.capOmniBar) {
        el.capOmniBar.style.width = pct + '%';
        el.capOmniBar.className = 'cap-bar-fill' + (pct >= 100 ? ' full' : pct >= 80 ? ' near' : '');
    }
    if (el.capOmniCount) el.capOmniCount.textContent = `${total}/${omni}`;
    ['voice', 'chat', 'whatsapp', 'email', 'sms'].forEach(ch => {
        const pill = $('capPill-' + ch);
        if (!pill) return;
        const load  = myLoad[ch] ?? 0;
        const cap   = myCapacity['channel_max_' + ch] ?? 1;
        const ratio = cap > 0 ? load / cap : 0;
        pill.className = 'cap-pill' +
            (ratio >= 1 ? ' full' : ratio >= 0.8 ? ' near' : load > 0 ? ' active' : '');
        pill.innerHTML = `<i class="bi ${_CH_ICONS[ch]} me-1"></i>${load}/${cap}`;
    });
    if (el.btnPickNext) {
        el.btnPickNext.classList.toggle('armed', !!myCapacity.capacity_override_active);
    }
}

// \u2500\u2500\u2500 Voice card helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function _showVoiceCard(state, stateText) {
    if (!el.voiceCard) return;
    if (el.vcCallerName) el.vcCallerName.textContent = voiceCall?.contactName  || 'Unknown Caller';
    if (el.vcCallerPhone) el.vcCallerPhone.textContent = voiceCall?.contactPhone || '';
    if (el.vcState) el.vcState.textContent = stateText || '';
    if (el.vcTimer) el.vcTimer.textContent = state === 'ringing' ? '\u2013:\u2013\u2013' : '0:00';
    el.voiceCard.className = state === 'ringing' ? 'vc-ringing vc-active' : 'vc-active';
    // Mirror to voice input row in chat area
    if (el.voiceInputRow) el.voiceInputRow.classList.add('active');
    if (el.chatInputRow)  el.chatInputRow.style.display = 'none';
    _syncVoiceCardState();
}

function _hideVoiceCard() {
    clearInterval(voiceTimerInterval);
    voiceTimerInterval = null;
    voiceCall = null;
    if (el.voiceCard) el.voiceCard.className = '';
    if (el.vcTimer) el.vcTimer.textContent = '\u2013:\u2013\u2013';
    if (el.vcState) el.vcState.textContent = '';
    // Restore text input row
    if (el.voiceInputRow) el.voiceInputRow.classList.remove('active');
    if (el.chatInputRow)  el.chatInputRow.style.display = '';
}

function _syncVoiceCardState() {
    if (!voiceCall) return;
    if (el.vcBtnMute) el.vcBtnMute.classList.toggle('vc-on', voiceCall.muted);
    if (el.vcBtnHold) el.vcBtnHold.classList.toggle('vc-on', voiceCall.held);
    if (el.voiceCard) el.voiceCard.classList.toggle('vc-held', voiceCall.held);
}

function _startVoiceTimer() {
    clearInterval(voiceTimerInterval);
    voiceTimerInterval = setInterval(() => {
        if (!voiceCall?.connectedAt) return;
        const secs = Math.floor((Date.now() - voiceCall.connectedAt.getTime()) / 1000);
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        const timeStr = `${m}:${String(s).padStart(2, '0')}`;
        if (el.vcTimer) el.vcTimer.textContent = timeStr;
        if (el.viTimer) el.viTimer.textContent = timeStr;
    }, 1000);
}

// \u2500\u2500\u2500 Dialler (Campaign panel) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

function diallerShowView() {
    if (!activeCampaignId || activeKey) return;
    if (el.noSession) el.noSession.style.display = 'none';
    if (el.chatView)  el.chatView.style.display  = 'none';
    if (el.diallerView) el.diallerView.style.display = 'flex';
}

function diallerHideView() {
    if (el.diallerView) el.diallerView.style.display = 'none';
}

async function diallerOpen() {
    if (!activeCampaignId) return;
    diallerStopPoll();
    await diallerFetchCampaign();
    await Promise.all([diallerFetchProgress(), diallerFetchNext()]);
    diallerShowView();
    diallerStartPoll();
}

// ── Voice-device helpers (dialler softphone) ────────────────────────────────

async function diallerVoiceInit(connectorId) {
    // Destroy any previous device before creating a new one
    if (_vzDevice) { try { _vzDevice.hangup(); } catch (_) {} }
    _vzDevice = new WzVoiceDevice(apiFetch);
    _vzDevice.on('state', _onVzState);
    await _vzDevice.init(connectorId);
}

function _onVzState(state, detail) {
    const strip    = el.dpSoftphone;
    const statusEl = el.dpSoftphoneStatus;
    if (!strip) return;

    if (state === 'connected') {
        _vzConnectedAt = Date.now();
        diallerVoiceStartTimer();
        if (statusEl) statusEl.textContent = 'Connected';
        strip.classList.add('active');
    } else if (state === 'ringing') {
        if (statusEl) statusEl.textContent = 'Ringing…';
    } else if (state === 'ready') {
        // call ended cleanly
        if (_vzConnectedAt) {
            // Leave strip visible until outcome submitted
            if (statusEl) statusEl.textContent = 'Call ended';
            strip.classList.remove('active');
        }
    } else if (state === 'error') {
        if (statusEl) statusEl.textContent = 'Error: ' + (detail || 'unknown');
        strip.classList.remove('active');
    } else if (state === 'unsupported') {
        strip.style.display = 'none';
        if (el.dpSoftphoneFallback) el.dpSoftphoneFallback.style.display = 'flex';
    }
}

function diallerVoiceStartTimer() {
    clearInterval(_vzTimerInterval);
    _vzTimerInterval = setInterval(() => {
        if (!_vzConnectedAt || !el.dpSoftphoneTimer) return;
        const secs = Math.floor((Date.now() - _vzConnectedAt) / 1000);
        const m = Math.floor(secs / 60);
        const s = String(secs % 60).padStart(2, '0');
        el.dpSoftphoneTimer.textContent = m + ':' + s;
    }, 1000);
}

function diallerVoiceStop() {
    clearInterval(_vzTimerInterval);
    _vzTimerInterval = null;
    _vzConnectedAt   = null;
    _vzMuted         = false;
    if (_vzDevice) { try { _vzDevice.hangup(); } catch (_) {} }
    if (el.dpSoftphone) {
        el.dpSoftphone.style.display = 'none';
        el.dpSoftphone.classList.remove('active');
    }
    if (el.dpSoftphoneFallback) el.dpSoftphoneFallback.style.display = 'none';
    if (el.dpSoftphoneTimer) el.dpSoftphoneTimer.textContent = '0:00';
}

function diallerClose() {
    diallerStopPoll();
    diallerVoiceStop();
    diallerContact = null;
    diallerAttempt = null;
    diallerCampaign = null;
    diallerProgress = null;
    diallerOutcomeCode = null;
    diallerHideView();
}

async function diallerFetchCampaign() {
    if (!activeCampaignId) return;
    try {
        const r = await apiFetch('/api/v1/campaigns/' + activeCampaignId);
        if (r.ok) {
            diallerCampaign = await r.json();
            diallerRenderHeader();
            // Initialise WebRTC device for voice campaigns
            const connectorId = diallerCampaign.settings?.voice_connector_id;
            if (diallerCampaign.campaign_type === 'outbound_voice' && connectorId) {
                diallerVoiceInit(connectorId).catch(e =>
                    console.error('diallerVoiceInit failed:', e)
                );
            }
        }
    } catch { /* ignore */ }
}

async function diallerFetchProgress() {
    if (!activeCampaignId) return;
    try {
        const r = await apiFetch('/api/v1/campaigns/' + activeCampaignId + '/dialler/progress');
        if (r.ok) {
            diallerProgress = await r.json();
            diallerRenderProgress();
            // Refresh header dialler_mode once progress is fetched
            if (diallerCampaign) diallerRenderHeader();
        }
    } catch { /* ignore */ }
}

async function diallerFetchNext() {
    if (!activeCampaignId) return;
    _dpShowState('loading');
    diallerContact = null;
    diallerOutcomeCode = null;
    if (el.dpOutcomeSection) el.dpOutcomeSection.style.display = 'none';
    if (el.dpActionRow)      el.dpActionRow.style.display      = '';
    if (el.dpContactCard)    el.dpContactCard.classList.remove('has-outcome');
    try {
        const r = await apiFetch('/api/v1/campaigns/' + activeCampaignId + '/dialler/next');
        if (!r.ok) { _dpShowState('nocontact'); return; }
        const data = await r.json();
        if (data.campaign_exhausted) { _dpShowState('exhausted'); return; }
        if (!data.contact)           { _dpShowState('nocontact'); return; }
        diallerContact = data.contact;
        diallerAttempt = data.attempt || null;
        diallerRenderContact(data);
        _dpShowState('contact');
    } catch { _dpShowState('nocontact'); }
}

function _dpShowState(state) {
    if (el.dpLoading)    el.dpLoading.style.display    = state === 'loading'   ? ''     : 'none';
    if (el.dpExhausted)  el.dpExhausted.style.display  = state === 'exhausted' ? 'flex' : 'none';
    if (el.dpNoContact)  el.dpNoContact.style.display  = state === 'nocontact' ? ''     : 'none';
    if (el.dpContactCard)el.dpContactCard.style.display = state === 'contact'  ? ''     : 'none';
}

function diallerRenderHeader() {
    if (!diallerCampaign) return;
    if (el.dpCampaignName) el.dpCampaignName.textContent = diallerCampaign.name || '';

    const typeMap = {
        outbound_voice:    ['dp-type-voice',    'Voice'],
        outbound_sms:      ['dp-type-sms',      'SMS'],
        outbound_whatsapp: ['dp-type-whatsapp', 'WhatsApp'],
        outbound_email:    ['dp-type-email',    'Email'],
        blast:             ['dp-type-blast',    'Blast'],
    };
    const [cls, label] = typeMap[diallerCampaign.campaign_type] || ['', diallerCampaign.campaign_type || ''];
    if (el.dpTypeBadge) {
        el.dpTypeBadge.className = 'dp-type-badge ' + cls;
        el.dpTypeBadge.textContent = label;
    }

    const statusColors = {
        running: 'wz-status-running', paused: 'wz-status-paused',
        draft: 'wz-status-draft', completed: 'wz-status-completed', archived: 'wz-status-inactive',
    };
    if (el.dpStatusBadge) {
        el.dpStatusBadge.className = 'wz-badge ' + (statusColors[diallerCampaign.status] || 'wz-status-inactive');
        el.dpStatusBadge.textContent = (diallerCampaign.status || '').toUpperCase();
    }

    const mode = (diallerProgress?.dialler_mode) || diallerCampaign.settings?.dialler_mode || '';
    if (el.dpDiallerMode) el.dpDiallerMode.textContent = mode ? mode.charAt(0).toUpperCase() + mode.slice(1) + ' mode' : '';

    // \u2500\u2500 Toolbar campaign badge \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if (el.tbarCampaignBadge) {
        el.tbarCampaignBadge.classList.add('active');
        if (el.tbarCampaignName) el.tbarCampaignName.textContent = diallerCampaign.name || '';
        const tbarTypeBadge = document.getElementById('tbarCampaignTypeBadge');
        if (tbarTypeBadge) { tbarTypeBadge.className = 'dp-type-badge ' + cls; tbarTypeBadge.textContent = label; }
    }
}

function diallerRenderProgress() {
    if (!diallerProgress) return;
    const { total = 0, attempted = 0, pct_complete = 0, by_status = {} } = diallerProgress;

    if (el.dpProgressText) el.dpProgressText.textContent = `${attempted} / ${total} attempted`;
    if (el.dpProgressPct)  el.dpProgressPct.textContent  = pct_complete.toFixed(1) + '%';
    if (el.dpProgressBar)  el.dpProgressBar.style.width  = Math.min(pct_complete, 100) + '%';

    if (el.dpByStatus) {
        const pills = [
            { key: 'completed', label: '\u2713 Done',       cls: 'wz-status-completed' },
            { key: 'no_answer', label: '\u21A9 No Answer',  cls: 'wz-status-no-answer' },
            { key: 'busy',      label: '\u260E Busy',       cls: 'wz-status-busy'      },
            { key: 'failed',    label: '\u2717 Failed',     cls: 'wz-status-failed'    },
            { key: 'skipped',   label: '\u27EB Skipped',    cls: 'wz-status-inactive'  },
        ].filter(p => (by_status[p.key] || 0) > 0);
        el.dpByStatus.innerHTML = pills.map(p =>
            `<span class="wz-badge ${p.cls} dp-stat-pill">${p.label}: ${by_status[p.key]}</span>`
        ).join('');
    }
}

function diallerRenderContact(data) {
    const c = data.contact;
    if (!c) return;

    if (el.dpContactName) el.dpContactName.textContent =
        (`${c.first_name || ''} ${c.last_name || ''}`).trim() || 'Unknown Contact';

    if (el.dpContactCompany) {
        el.dpContactCompany.textContent  = c.company || '';
        el.dpContactCompany.style.display = c.company ? '' : 'none';
    }

    if (el.dpContactPhone) {
        el.dpContactPhone.innerHTML      = c.phone ? `<i class="bi bi-telephone me-1"></i>${esc(c.phone)}` : '';
        el.dpContactPhone.style.display  = c.phone ? '' : 'none';
    }
    if (el.dpContactWa) {
        el.dpContactWa.innerHTML         = c.whatsapp_id ? `<i class="bi bi-whatsapp me-1"></i>${esc(c.whatsapp_id)}` : '';
        el.dpContactWa.style.display     = c.whatsapp_id ? '' : 'none';
    }
    if (el.dpContactEmail) {
        el.dpContactEmail.innerHTML      = c.email ? `<i class="bi bi-envelope me-1"></i>${esc(c.email)}` : '';
        el.dpContactEmail.style.display  = c.email ? '' : 'none';
    }
    if (el.dpContactLang) {
        el.dpContactLang.innerHTML = c.language
            ? `<i class="bi bi-translate me-1"></i>${esc(c.language.toUpperCase())}`
            : '';
    }
    if (el.dpContactNotes) {
        el.dpContactNotes.textContent  = c.notes || '';
        el.dpContactNotes.style.display = c.notes ? '' : 'none';
    }

    const attemptNum  = data.attempt?.attempt_number ?? 1;
    const maxAttempts = diallerCampaign?.max_attempts ?? '?';
    if (el.dpAttemptBadge) el.dpAttemptBadge.textContent = `Attempt ${attemptNum} of ${maxAttempts}`;
    if (el.dpTemplateBadge) el.dpTemplateBadge.style.display = data.template_required ? '' : 'none';

    // Label the Dial button based on campaign type
    if (el.dpBtnDial) {
        const type = diallerCampaign?.campaign_type || '';
        const btnLabels = {
            outbound_voice:    '<i class="bi bi-telephone-fill me-1"></i>Dial',
            outbound_whatsapp: '<i class="bi bi-whatsapp me-1"></i>Send',
            outbound_sms:      '<i class="bi bi-chat-text-fill me-1"></i>Send SMS',
            outbound_email:    '<i class="bi bi-envelope-fill me-1"></i>Send Email',
        };
        el.dpBtnDial.innerHTML = btnLabels[type] || '<i class="bi bi-send-fill me-1"></i>Contact';
        el.dpBtnDial.disabled  = false;
    }
    if (el.dpBtnNext) el.dpBtnNext.disabled = false;
    if (el.dpBtnSkip) el.dpBtnSkip.disabled = false;
}

async function diallerDial() {
    if (!activeCampaignId || !diallerContact) return;
    if (el.dpBtnDial) el.dpBtnDial.disabled = true;
    if (el.dpBtnNext) el.dpBtnNext.disabled = true;
    if (el.dpBtnSkip) el.dpBtnSkip.disabled = true;
    try {
        const r = await apiFetch('/api/v1/campaigns/' + activeCampaignId + '/dialler/attempt', {
            method: 'POST', body: JSON.stringify({ contact_id: diallerContact.id }),
        });
        if (!r.ok) {
            console.error('Dialler attempt failed:', await r.text());
            if (el.dpBtnDial) el.dpBtnDial.disabled = false;
            if (el.dpBtnNext) el.dpBtnNext.disabled = false;
            if (el.dpBtnSkip) el.dpBtnSkip.disabled = false;
            return;
        }
        diallerAttempt = await r.json();
        diallerRenderOutcomePills();
        if (el.dpContactCard)    el.dpContactCard.classList.add('has-outcome');
        if (el.dpOutcomeSection) el.dpOutcomeSection.style.display = 'flex';
        if (el.dpActionRow)      el.dpActionRow.style.display      = 'none';
        if (el.dpOutcomeNotes)   el.dpOutcomeNotes.value           = '';

        // Start WebRTC call for voice campaigns
        if (diallerCampaign?.campaign_type === 'outbound_voice') {
            const room = `outbound-${diallerAttempt.id}`;
            if (_vzDevice && _vzDevice.supported) {
                if (el.dpSoftphone) el.dpSoftphone.style.display = 'flex';
                if (el.dpSoftphoneStatus) el.dpSoftphoneStatus.textContent = 'Connecting…';
                await _vzDevice.dial(room);
            } else {
                // Non-WebRTC provider: server will initiate the call via API
                const fallbackMsg = _vzDevice?.supported === false
                    ? 'Call initiated — answer on your desk phone.'
                    : 'WebRTC not ready. Dial manually.';
                if (el.dpSoftphoneFallback)  el.dpSoftphoneFallback.style.display = 'flex';
                if (el.dpFallbackMsg)        el.dpFallbackMsg.textContent = fallbackMsg;
            }
        }
    } catch {
        if (el.dpBtnDial) el.dpBtnDial.disabled = false;
        if (el.dpBtnNext) el.dpBtnNext.disabled = false;
        if (el.dpBtnSkip) el.dpBtnSkip.disabled = false;
    }
}

async function diallerSkip() {
    if (!activeCampaignId || !diallerContact) return;
    try {
        // Create the attempt record, then immediately mark it skipped
        const r1 = await apiFetch('/api/v1/campaigns/' + activeCampaignId + '/dialler/attempt', {
            method: 'POST', body: JSON.stringify({ contact_id: diallerContact.id }),
        });
        if (r1.ok) {
            const attempt = await r1.json();
            await apiFetch(`/api/v1/campaigns/${activeCampaignId}/dialler/attempt/${attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'skipped', ended_at: new Date().toISOString() }),
            });
        }
    } catch { /* ignore */ }
    await diallerFetchProgress();
    await diallerFetchNext();
}

function diallerRenderOutcomePills() {
    if (!el.dpOutcomePills) return;
    diallerOutcomeCode = null;

    const outcomes = (diallerCampaign?.outcomes?.length)
        ? diallerCampaign.outcomes
        : [
            { code: 'completed',  label: 'Completed',  action_type: 'positive' },
            { code: 'no_answer',  label: 'No Answer',  action_type: 'neutral'  },
            { code: 'busy',       label: 'Busy',       action_type: 'neutral'  },
            { code: 'voicemail',  label: 'Voicemail',  action_type: 'neutral'  },
            { code: 'callback',   label: 'Callback',   action_type: 'neutral'  },
            { code: 'failed',     label: 'Failed',     action_type: 'negative' },
        ];

    el.dpOutcomePills.innerHTML = outcomes.map(o =>
        `<button class="dp-outcome-pill ${esc(o.action_type || 'neutral')}" data-code="${esc(o.code)}">${esc(o.label)}</button>`
    ).join('');

    el.dpOutcomePills.querySelectorAll('.dp-outcome-pill').forEach(btn => {
        btn.addEventListener('click', () => {
            el.dpOutcomePills.querySelectorAll('.dp-outcome-pill').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            diallerOutcomeCode = btn.dataset.code;
        });
    });
}

async function diallerSubmitOutcome() {
    if (!activeCampaignId || !diallerAttempt) return;
    const statusMap = {
        completed: 'completed', no_answer: 'no_answer', busy: 'busy',
        voicemail: 'no_answer', callback: 'no_answer',  failed: 'failed',
    };
    const status = statusMap[diallerOutcomeCode] || 'completed';
    const notes  = el.dpOutcomeNotes?.value?.trim() || null;
    try {
        const r = await apiFetch(
            `/api/v1/campaigns/${activeCampaignId}/dialler/attempt/${diallerAttempt.id}`,
            { method: 'PATCH', body: JSON.stringify({ status, outcome_code: diallerOutcomeCode, notes, ended_at: new Date().toISOString() }) }
        );
        if (!r.ok) { console.error('Submit outcome failed:', await r.text()); return; }
    } catch { /* ignore */ }

    if (el.dpOutcomeSection) el.dpOutcomeSection.style.display = 'none';
    if (el.dpContactCard)    el.dpContactCard.classList.remove('has-outcome');
    if (el.dpActionRow)      el.dpActionRow.style.display      = '';
    diallerAttempt     = null;
    diallerOutcomeCode = null;
    await diallerFetchProgress();
    await diallerFetchNext();
}

function diallerStartPoll() {
    diallerStopPoll();
    diallerPollTimer = setInterval(() => diallerFetchProgress(), 30_000);
}

function diallerStopPoll() {
    if (diallerPollTimer) { clearInterval(diallerPollTimer); diallerPollTimer = null; }
}

// \u2500\u2500\u2500 Action buttons \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    // Direct close (waiting / in-flow \u2014 no outcome required)
    el.btnClose?.addEventListener('click', () => {
        if (!activeKey) return;
        if (!confirm('Close this session?')) return;
        wsSend({ type: 'close', session_id: activeKey });
        if (sessions[activeKey]) sessions[activeKey].status = 'closed';
        updateChatHeader();
        renderSessionLists();
        el.msgInput.disabled = true;
        el.btnSend.disabled  = true;
        if (el.emojiBtn) el.emojiBtn.disabled = true;
        if (el.attachBtn) el.attachBtn.disabled = true;
        closeAgentEmojiPicker();
    });

    // Outcome button \u2014 opens sentiment-grouped modal
    el.btnOutcome?.addEventListener('click', () => {
        if (!activeKey) return;
        openOutcomeModal(activeKey);
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

    // Pick Next \u2014 arm a one-shot +1 capacity override
    el.btnPickNext?.addEventListener('click', async () => {
        const r = await apiFetch('/api/v1/agents/me/pick-next', { method: 'POST' });
        if (r.ok || r.status === 204) {
            if (myCapacity) myCapacity.capacity_override_active = true;
            updateCapacityBar();
        }
    });

    // \u2500\u2500 Voice card controls (session panel) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    el.vcBtnMute?.addEventListener('click', () => {
        if (!voiceCall) return;
        wsSend({ type: voiceCall.muted ? 'call_unmute' : 'call_mute', attempt_id: voiceCall.attemptId });
    });

    el.vcBtnHold?.addEventListener('click', () => {
        if (!voiceCall) return;
        wsSend({ type: voiceCall.held ? 'call_unhold' : 'call_hold', attempt_id: voiceCall.attemptId });
    });

    el.vcBtnHangup?.addEventListener('click', () => {
        if (!voiceCall) return;
        if (!confirm('Hang up this call?')) return;
        wsSend({ type: 'call_hangup', attempt_id: voiceCall.attemptId });
    });

    // \u2500\u2500 Voice input row controls (chat area) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    el.viBtnMute?.addEventListener('click', () => {
        if (!voiceCall) return;
        wsSend({ type: voiceCall.muted ? 'call_unmute' : 'call_mute', attempt_id: voiceCall.attemptId });
    });

    el.viBtnHold?.addEventListener('click', () => {
        if (!voiceCall) return;
        wsSend({ type: voiceCall.held ? 'call_unhold' : 'call_hold', attempt_id: voiceCall.attemptId });
    });

    el.viBtnHangup?.addEventListener('click', () => {
        if (!voiceCall) return;
        if (!confirm('Hang up this call?')) return;
        wsSend({ type: 'call_hangup', attempt_id: voiceCall.attemptId });
    });

    el.vcBtnDoTransfer?.addEventListener('click', () => {
        if (!voiceCall) return;
        const phone = $('vcTransferPhone')?.value?.trim();
        if (!phone) return;
        wsSend({ type: 'call_transfer_number', attempt_id: voiceCall.attemptId, to_number: phone });
        bootstrap.Modal.getInstance(el.vcTransferModal)?.hide();
    });

    // Logout
    $('btnLogout')?.addEventListener('click', () => {
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/login';
    });

    // \u2500\u2500 Dialler panel controls \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    el.dpBtnOpenPanel?.addEventListener('click', () => {
        if (!activeCampaignId) return;
        if (el.chatView) el.chatView.style.display = 'none';
        diallerShowView();
        diallerFetchProgress();
    });
    el.dpBtnRefresh?.addEventListener('click', async () => {
        await diallerFetchProgress();
        await diallerFetchNext();
    });
    el.dpBtnDial?.addEventListener('click', diallerDial);
    el.dpBtnNext?.addEventListener('click', () => diallerFetchNext());
    el.dpBtnSkip?.addEventListener('click', diallerSkip);
    el.dpBtnSoftMute?.addEventListener('click', () => {
        if (!_vzDevice) return;
        _vzMuted = !_vzMuted;
        _vzDevice.mute(_vzMuted);
        const icon = el.dpBtnSoftMute?.querySelector('i');
        if (icon) icon.className = _vzMuted ? 'bi bi-mic-mute-fill' : 'bi bi-mic-fill';
        el.dpBtnSoftMute?.classList.toggle('active', _vzMuted);
    });
    el.dpBtnSoftHangup?.addEventListener('click', () => {
        if (_vzDevice) _vzDevice.hangup();
        diallerVoiceStop();
    });
    el.dpBtnSubmitOutcome?.addEventListener('click', diallerSubmitOutcome);
    el.dpBtnCancelOutcome?.addEventListener('click', () => {
        if (el.dpOutcomeSection) el.dpOutcomeSection.style.display = 'none';
        if (el.dpContactCard)    el.dpContactCard.classList.remove('has-outcome');
        if (el.dpActionRow)      el.dpActionRow.style.display      = '';
        if (el.dpBtnDial) el.dpBtnDial.disabled = false;
        if (el.dpBtnNext) el.dpBtnNext.disabled = false;
        if (el.dpBtnSkip) el.dpBtnSkip.disabled = false;
        diallerAttempt     = null;
        diallerOutcomeCode = null;
    });
}

// \u2500\u2500\u2500 Helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function esc(v) {
    return String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function timeAgo(iso) {
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60)  return diff + 's';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    return Math.floor(diff / 3600) + 'h';
}

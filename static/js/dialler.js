/**
 * WizzardChat – Outbound Dialler (preview + progressive)
 *
 * State machine:
 *   idle → dialling → connected → wrap_up → idle (or exhausted)
 *
 * WhatsApp rule:
 *   OUTBOUND_WHATSAPP campaigns check the 24-hour free-messaging window on
 *   every contact load.  When template_required is true the HSM template card
 *   is displayed and the agent is warned they must use the approved template.
 */
(function () {
    'use strict';

    // ── Config ────────────────────────────────────────────────────────────────
    const CAMPAIGN_ID   = window.DIALLER_CAMPAIGN_ID || '';
    const API           = '';
    const _token        = () => localStorage.getItem('wizzardchat_token');
    const _headers      = () => ({ Authorization: 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    // ── State ─────────────────────────────────────────────────────────────────
    let _campaign       = null;   // full campaign object
    let _diallerMode    = 'preview';   // 'preview' | 'progressive'
    let _ringTimeout    = 45;          // seconds before auto no-answer (progressive)
    let _contact        = null;        // current ContactDiallerOut
    let _next           = null;        // full DiallerNextOut from /dialler/next
    let _attempt        = null;        // current CampaignAttemptOut (after POST)
    let _selectedOutcome = null;       // outcome key string
    let _outboundConfig = {};          // campaign.outbound_config
    let _activeChannel  = 'voice';     // resolved active channel
    let _templateVars   = [];          // [{pos, label, contact_field, resolved_value}]

    // Timers
    let _connStart      = null;
    let _connTimerInt   = null;
    let _ringTimerInt   = null;
    let _autoAdvInt     = null;

    // ── DOM shortcuts ─────────────────────────────────────────────────────────
    const $  = id => document.getElementById(id);
    const body = () => document.querySelector('.d-body') || document.body;

    // ── Helpers ───────────────────────────────────────────────────────────────
    function esc(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _fmtSeconds(secs) {
        const m = Math.floor(secs / 60);
        const s = String(Math.floor(secs % 60)).padStart(2, '0');
        return `${m}:${s}`;
    }

    function _channelIcon(type) {
        const map = {
            outbound_voice:    'bi-telephone-fill',
            outbound_sms:      'bi-chat-fill',
            outbound_whatsapp: 'bi-whatsapp',
            outbound_email:    'bi-envelope-fill',
            blast:             'bi-megaphone-fill',
        };
        return map[type] || 'bi-megaphone';
    }

    function _channelLabel(type) {
        const map = {
            outbound_voice:    'Voice',
            outbound_sms:      'SMS',
            outbound_whatsapp: 'WhatsApp',
            outbound_email:    'Email',
            blast:             'Blast',
        };
        return map[type] || type;
    }

    function _statusColor(s) {
        const map = {
            completed: '#22c55e', no_answer: '#f59e0b', busy: '#64748b',
            failed: '#ef4444', skipped: '#7d8590', dialling: '#38bdf8',
            connected: '#22c55e',
        };
        return map[s] || '#7d8590';
    }

    function _statusLabel(s) {
        const map = {
            pending: 'Pending', dialling: 'Dialling', connected: 'Connected',
            no_answer: 'No Answer', busy: 'Busy', failed: 'Failed',
            completed: 'Completed', skipped: 'Skipped',
        };
        return map[s] || s;
    }

    function _setState(state) {
        // state: idle | dialling | connected | wrap_up | exhausted
        document.body.className = `state-${state}`;
    }

    // ── API ───────────────────────────────────────────────────────────────────
    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/login'; }
        return r;
    }

    // ── Initialise ────────────────────────────────────────────────────────────
    async function init() {
        const token = _token();
        if (!token) { window.location.href = '/login'; return; }
        if (!CAMPAIGN_ID) { alert('No campaign ID — returning to campaigns list.'); window.location.href = '/campaigns'; return; }

        await loadCampaign();
        _setState('idle');
        await loadNext();
    }

    // ── Load campaign metadata ────────────────────────────────────────────────
    async function loadCampaign() {
        const r = await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}`);
        if (!r.ok) { alert('Could not load campaign.'); window.location.href = '/campaigns'; return; }
        _campaign = await r.json();

        // Dialler settings (stored in campaign.settings.dialler_mode etc.)
        const s = _campaign.settings || {};
        _diallerMode = s.dialler_mode || 'preview';
        _ringTimeout  = s.ring_timeout  || 45;

        // Top bar
        $('tbCampaignName').textContent = _campaign.name;
        const ch = $('tbChannelBadge');
        ch.textContent = _channelLabel(_campaign.campaign_type);
        ch.className = `badge bg-secondary`;
        $('tbModeBadge').textContent = _diallerMode === 'progressive' ? 'Progressive' : 'Preview';
        $('tbModeBadge').className = `badge ${_diallerMode === 'progressive' ? 'bg-warning text-dark' : 'bg-info text-dark'}`;

        const sb = $('tbStatusBadge');
        sb.textContent = _campaign.status;
        sb.className = `badge ${_campaign.status === 'running' ? 'bg-success' : 'bg-secondary'}`;

        // Outcomes
        const grid = $('outcomeGrid');
        grid.innerHTML = '';
        const outcomes = Array.isArray(_campaign.outcomes) ? _campaign.outcomes : [];
        if (outcomes.length === 0) {
            // If no per-campaign outcomes, try fetching global outcomes
            await _loadGlobalOutcomes();
        } else {
            outcomes.forEach(o => {
                const key   = typeof o === 'string' ? o : (o.key || o.code || o);
                const label = typeof o === 'object'  ? (o.label || key) : key;
                grid.insertAdjacentHTML('beforeend', `
                    <button class="outcome-btn" data-key="${esc(key)}" onclick="selectOutcome(this,'${esc(key)}')">
                        ${esc(label)}
                    </button>`);
            });
        }
        if (grid.children.length === 0) {
            $('outcomeEmpty').style.display = '';
        }
    }

    async function _loadGlobalOutcomes() {
        const r = await apiFetch('/api/v1/outcomes');
        if (!r.ok) return;
        const outcomes = await r.json();
        const active   = outcomes.filter(o => o.is_active);
        const grid = $('outcomeGrid');
        active.forEach(o => {
            grid.insertAdjacentHTML('beforeend', `
                <button class="outcome-btn" data-key="${esc(o.code)}" onclick="selectOutcome(this,'${esc(o.code)}')">
                    ${esc(o.label)}
                </button>`);
        });
    }

    // ── Load next contact ─────────────────────────────────────────────────────
    async function loadNext() {
        _attempt        = null;
        _selectedOutcome = null;
        _contact        = null;

        // Reset outcome selection
        document.querySelectorAll('.outcome-btn').forEach(b => b.classList.remove('selected'));
        $('wrapNotes').value = '';

        const r = await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/next`);
        if (!r.ok) {
            _setState('idle');
            renderNoContact('Failed to load next contact. Check campaign status.');
            return;
        }
        _next = await r.json();
        _updateProgress(_next);

        if (_next.campaign_exhausted || !_next.contact) {
            _setState('exhausted');
            const exhaustedStats = $('exhaustedStats');
            if (exhaustedStats) {
                exhaustedStats.textContent = `All ${_next.total_contacts} contacts processed. ` +
                    `${_next.completed_contacts} completed.`;
            }
            renderNoContact('');
            return;
        }

        _contact = _next.contact;
        _outboundConfig = _next.outbound_config || {};
        _activeChannel  = _next.active_channel  || 'voice';
        _templateVars   = _next.template_variables || [];

        _setState('idle');
        renderContact(_contact);
        renderWaBanner(_next);
        renderChannelButtons(_next);
        renderTemplateCard(_next);
        await loadHistory(_contact.id);
    }

    function _updateProgress(data) {
        const pct = data.total_contacts > 0
            ? Math.round(data.completed_contacts / data.total_contacts * 100)
            : 0;
        $('hdrProgress').style.width = pct + '%';
        $('hdrProgressLabel').textContent =
            `${data.completed_contacts} / ${data.total_contacts} completed · ${data.remaining_contacts} remaining`;
    }

    // ── Render contact ────────────────────────────────────────────────────────
    function renderNoContact(msg) {
        $('noContactMsg').style.display = '';
        $('contactDetail').style.display = 'none';
        if (msg) $('noContactMsg').innerHTML = `<i class="bi bi-person-x fs-2 d-block mb-2"></i>${esc(msg)}`;
    }

    function renderContact(c) {
        $('noContactMsg').style.display = 'none';
        $('contactDetail').style.display = '';

        const initials = [c.first_name, c.last_name]
            .filter(Boolean).map(s => s[0].toUpperCase()).join('') || '?';
        $('contactAvatar').textContent = initials;

        const fullName = [c.first_name, c.last_name].filter(Boolean).join(' ') || 'Unknown';
        $('contactName').textContent = fullName;
        $('contactCompany').textContent = c.company || '';

        // Channel chips
        const chips = $('contactChannels');
        chips.innerHTML = '';
        if (c.phone)        chips.insertAdjacentHTML('beforeend', `<span class="ch-pill"><i class="bi bi-telephone"></i>${esc(c.phone)}</span>`);
        if (c.whatsapp_id)  chips.insertAdjacentHTML('beforeend', `<span class="ch-pill"><i class="bi bi-whatsapp"></i>${esc(c.whatsapp_id)}</span>`);
        if (c.email)        chips.insertAdjacentHTML('beforeend', `<span class="ch-pill"><i class="bi bi-envelope"></i>${esc(c.email)}</span>`);

        // Notes
        if (c.notes) {
            $('contactNotes').textContent = c.notes;
            $('contactNotesWrap').style.display = '';
        } else {
            $('contactNotesWrap').style.display = 'none';
        }

        // Idle panel
        $('idleContactName').textContent = fullName;
        // Show the contact endpoint for the active channel
        const endpointMap = { voice: c.phone, whatsapp: c.whatsapp_id, sms: c.phone, email: c.email };
        $('idleContactPhone').textContent = endpointMap[_activeChannel] || c.phone || c.whatsapp_id || c.email || '';

        // Dialling panel
        $('diallingName').textContent = fullName;
        $('diallingPhone').textContent = c.phone || c.whatsapp_id || c.email || '';

        // Connected panel
        $('connectedName').textContent = fullName;
    }

    // ── WA window banner ──────────────────────────────────────────────────────
    function renderWaBanner(next) {
        const isWa = (_campaign.campaign_type === 'outbound_whatsapp') || (next.active_channel === 'whatsapp');
        if (!isWa) {
            $('waBannerWrap').style.display = 'none';
            return;  // templateCardWrap handled by renderTemplateCard
        }

        $('waBannerWrap').style.display = '';
        const banner = $('waBanner');
        const title  = $('waBannerTitle');
        const text   = $('waBannerText');

        if (next.template_required) {
            banner.className = 'wa-banner closed';
            title.textContent = '24-hour window expired';
            text.textContent  = 'The last inbound message from this contact is older than 24 hours. ' +
                'You must send the approved outbound template (HSM) to reopen the conversation.';
        } else {
            banner.className = 'wa-banner open';
            title.textContent = '24-hour window open';
            text.textContent  = 'This contact messaged within the last 24 hours. Free-form messaging is allowed.';
        }
    }

    // ── Channel action buttons ────────────────────────────────────────────────
    const CHANNEL_DEFS = {
        voice:    { icon: 'bi-telephone-fill', label: 'Dial',        btnCls: 'btn-success' },
        whatsapp: { icon: 'bi-whatsapp',       label: 'WhatsApp',    btnCls: 'btn-success' },
        sms:      { icon: 'bi-chat-fill',      label: 'Send SMS',    btnCls: 'btn-info text-dark' },
        email:    { icon: 'bi-envelope-fill',  label: 'Send Email',  btnCls: 'btn-warning text-dark' },
    };
    const OPT_OUT_FLAG = { voice: 'do_not_call', whatsapp: 'do_not_whatsapp', sms: 'do_not_sms', email: 'do_not_email' };

    function renderChannelButtons(next) {
        const primary   = next.active_channel || 'voice';
        const fallbacks = (next.outbound_config || {}).fallback_channels || [];
        const c         = next.contact || _contact || {};
        const pd        = CHANNEL_DEFS[primary] || CHANNEL_DEFS.voice;
        const optedOut  = !!c[OPT_OUT_FLAG[primary]];

        // Primary button
        const primaryGroup = $('channelActionGroup');
        if (primaryGroup) {
            primaryGroup.innerHTML = optedOut
                ? `<button class="btn btn-secondary ch-action-primary" disabled title="Contact opted out of ${primary}"><i class="bi ${pd.icon} me-2"></i>${pd.label} (Opted out)</button>`
                : `<button class="btn ${pd.btnCls} ch-action-primary" onclick="beginDial('${primary}')"><i class="bi ${pd.icon} me-2"></i>${pd.label}</button>`;
        }

        // Idle panel channel icon
        const iconMap = { voice: 'bi-telephone-outbound', whatsapp: 'bi-whatsapp', sms: 'bi-chat', email: 'bi-envelope' };
        const iconEl = $('idleChannelIcon');
        if (iconEl) iconEl.className = `bi ${iconMap[primary] || 'bi-telephone-outbound'} fs-1 text-muted`;

        // Fallback buttons
        const fbGroup = $('fallbackActionsGroup');
        if (fbGroup) {
            fbGroup.innerHTML = '';
            const activeFb = fallbacks.filter(ch => ch !== primary);
            if (activeFb.length) {
                fbGroup.style.removeProperty('display');
                activeFb.forEach(ch => {
                    const d      = CHANNEL_DEFS[ch] || CHANNEL_DEFS.voice;
                    const opted2 = !!c[OPT_OUT_FLAG[ch]];
                    fbGroup.insertAdjacentHTML('beforeend', opted2
                        ? `<button class="btn btn-outline-secondary ch-action-fallback" disabled><i class="bi ${d.icon} me-1"></i>${d.label}</button>`
                        : `<button class="btn btn-outline-secondary ch-action-fallback" onclick="beginDial('${ch}')"><i class="bi ${d.icon} me-1"></i>${d.label}</button>`
                    );
                });
            } else {
                fbGroup.style.display = 'none';
            }
        }
    }

    // ── Template card ─────────────────────────────────────────────────────────
    function renderTemplateCard(next) {
        const channel    = next.active_channel || 'voice';
        const vars       = next.template_variables || [];
        const hasTemplate = !!(next.template_id || next.message_template);

        if (!hasTemplate) {
            $('templateCardWrap').style.display = 'none';
            return;
        }
        $('templateCardWrap').style.display = '';

        const channelMeta = {
            whatsapp: { icon: 'bi-whatsapp',      label: 'WhatsApp HSM', badgeCls: 'bg-success' },
            sms:      { icon: 'bi-phone',          label: 'SMS',          badgeCls: 'bg-info text-dark' },
            email:    { icon: 'bi-envelope-fill',  label: 'Email',        badgeCls: 'bg-warning text-dark' },
        };
        const meta = channelMeta[channel] || { icon: 'bi-card-text', label: 'Template', badgeCls: 'bg-secondary' };

        const iconEl = $('templateCardIcon');
        if (iconEl) iconEl.className = `bi ${meta.icon} text-warning`;

        const titleEl = $('templateCardTitle');
        if (titleEl) titleEl.textContent = meta.label + ' Template';

        const badgeEl = $('templateChannelBadge');
        if (badgeEl) { badgeEl.className = `badge ${meta.badgeCls} ms-auto`; badgeEl.textContent = channel.toUpperCase(); }

        $('templateText').textContent = next.message_template || '(No body — configure template in campaign settings)';

        // Subject row (email)
        const subjectWrap = $('templateSubjectWrap');
        const subjectEl   = $('templateSubject');
        if (subjectWrap && subjectEl) {
            if (channel === 'email' && next.template_subject) {
                subjectWrap.style.display = '';
                subjectEl.textContent = next.template_subject;
            } else {
                subjectWrap.style.display = 'none';
            }
        }

        // Variable rows
        const varsWrap = $('templateVarsWrap');
        const varsList = $('templateVarsList');
        if (varsWrap && varsList) {
            if (vars.length) {
                varsWrap.style.display = '';
                varsList.innerHTML = '';
                vars.forEach(v => {
                    varsList.insertAdjacentHTML('beforeend', `
                        <div class="var-resolved-row">
                            <code>{{${v.pos}}}</code>
                            <span class="text-muted">${esc(v.label || '')}</span>
                            <span class="fw-semibold">${esc(v.resolved_value || v.default || '\u2013')}</span>
                        </div>`);
                });
            } else {
                varsWrap.style.display = 'none';
            }
        }

        const helpEl = $('templateCardHelp');
        if (helpEl) {
            helpEl.textContent = channel === 'whatsapp'
                ? 'Send this approved template to initiate the conversation.'
                : `Use this ${channel} template when contacting this customer.`;
        }
    }

    // ── History ───────────────────────────────────────────────────────────────
    async function loadHistory(contactId) {
        const list  = $('historyList');
        const empty = $('histEmpty');
        const r = await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/history/${contactId}`);
        if (!r.ok) return;
        const history = await r.json();

        list.innerHTML = '';
        if (!history.length) {
            list.innerHTML = '<div class="no-contact" id="histEmpty">No prior attempts</div>';
            return;
        }

        history.forEach(a => {
            const col   = _statusColor(a.status);
            const label = _statusLabel(a.status);
            const when  = a.dialled_at ? new Date(a.dialled_at).toLocaleString('en-ZA') : '–';
            list.insertAdjacentHTML('beforeend', `
                <div class="hist-item mb-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="hist-status" style="color:${col}">${esc(label)}</span>
                        <span class="text-muted" style="font-size:11px">Attempt #${a.attempt_number}</span>
                    </div>
                    <div class="text-muted mt-1" style="font-size:11px">${esc(when)}</div>
                    ${a.outcome_code ? `<div class="mt-1" style="font-size:12px">Outcome: <strong>${esc(a.outcome_code)}</strong></div>` : ''}
                    ${a.notes ? `<div class="text-muted mt-1" style="font-size:12px;font-style:italic">${esc(a.notes)}</div>` : ''}
                </div>`);
        });
    }

    // ── State transitions ─────────────────────────────────────────────────────

    window.beginDial = async function (channel) {
        if (!_contact) return;

        const ch = channel || _activeChannel || 'voice';
        const r = await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt`, {
            method: 'POST',
            body: JSON.stringify({ contact_id: _contact.id, channel: ch }),
        });
        if (!r.ok) { alert('Could not start attempt. Please try again.'); return; }
        _attempt = await r.json();

        _setState('dialling');

        // Progressive: start ring timeout countdown
        if (_diallerMode === 'progressive') {
            _startRingTimeout();
        } else {
            $('ringTimeoutWrap').style.display = 'none';
        }
    };

    window.skipContact = async function () {
        // If an attempt was already created, mark it skipped; otherwise just load next
        if (_attempt) {
            await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt/${_attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'skipped' }),
            });
        }
        _stopRingTimeout();
        await loadNext();
    };

    window.markConnected = async function () {
        _stopRingTimeout();
        if (_attempt) {
            await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt/${_attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'connected', connected_at: new Date().toISOString() }),
            });
        }
        _connStart = Date.now();
        _startConnTimer();
        _setState('connected');
    };

    window.enterWrapUp = function () {
        _stopConnTimer();
        _setState('wrap_up');
    };

    window.logNoAnswer = async function () {
        _stopRingTimeout();
        if (_attempt) {
            await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt/${_attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'no_answer' }),
            });
        }
        await _afterResult();
    };

    window.logBusy = async function () {
        _stopRingTimeout();
        if (_attempt) {
            await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt/${_attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'busy' }),
            });
        }
        await _afterResult();
    };

    window.logFailed = async function () {
        _stopRingTimeout();
        if (_attempt) {
            await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt/${_attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'failed' }),
            });
        }
        await _afterResult();
    };

    window.selectOutcome = function (btn, key) {
        document.querySelectorAll('.outcome-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        _selectedOutcome = key;
    };

    window.logAndNext = async function (pauseAfter = false) {
        if (!_selectedOutcome && document.querySelectorAll('.outcome-btn').length > 0) {
            // Only require outcome if outcomes are configured
            alert('Please select an outcome before proceeding.');
            return;
        }

        const notes = $('wrapNotes').value.trim();
        if (_attempt) {
            await apiFetch(`/api/v1/campaigns/${CAMPAIGN_ID}/dialler/attempt/${_attempt.id}`, {
                method: 'PATCH',
                body: JSON.stringify({
                    status: 'completed',
                    outcome_code: _selectedOutcome || null,
                    notes: notes || null,
                    ended_at: new Date().toISOString(),
                }),
            });
        }

        if (pauseAfter) {
            // Stay on current contact — just refresh history
            await loadHistory(_contact?.id);
            _setState('idle');
            return;
        }

        await _afterResult();
    };

    /**
     * Called after any terminal status (no_answer, busy, failed, completed).
     * In progressive mode: shows the auto-advance strip and counts down.
     * In preview mode: immediately loads the next contact.
     */
    async function _afterResult() {
        if (_diallerMode === 'progressive') {
            _showAutoAdvance();
        } else {
            await loadNext();
        }
    }

    // ── Connection timer ──────────────────────────────────────────────────────
    function _startConnTimer() {
        _stopConnTimer();
        $('connTimer').textContent = '0:00';
        _connTimerInt = setInterval(() => {
            const elapsed = (Date.now() - _connStart) / 1000;
            $('connTimer').textContent = _fmtSeconds(elapsed);
        }, 1000);
    }

    function _stopConnTimer() {
        if (_connTimerInt) { clearInterval(_connTimerInt); _connTimerInt = null; }
    }

    // ── Ring timeout (progressive) ────────────────────────────────────────────
    function _startRingTimeout() {
        $('ringTimeoutWrap').style.display = '';
        const fill  = $('ringTimeoutFill');
        const label = $('ringTimeoutLabel');
        fill.style.width = '100%';
        fill.style.transition = 'none';

        let remaining = _ringTimeout;
        label.textContent = `Auto no-answer in ${remaining}s`;

        _ringTimerInt = setInterval(async () => {
            remaining -= 1;
            const pct = Math.max(0, (remaining / _ringTimeout) * 100);
            fill.style.transition = 'width .9s linear';
            fill.style.width = pct + '%';
            label.textContent = remaining > 0
                ? `Auto no-answer in ${remaining}s`
                : 'Logging no answer…';

            if (remaining <= 0) {
                _stopRingTimeout();
                await logNoAnswer();
            }
        }, 1000);
    }

    function _stopRingTimeout() {
        if (_ringTimerInt) { clearInterval(_ringTimerInt); _ringTimerInt = null; }
        $('ringTimeoutWrap').style.display = 'none';
    }

    // ── Auto-advance strip (progressive) ─────────────────────────────────────
    function _showAutoAdvance() {
        const strip = $('autoAdvanceStrip');
        strip.classList.remove('hidden');
        let count = 5;
        $('autoCountdown').textContent = count;

        _autoAdvInt = setInterval(async () => {
            count -= 1;
            $('autoCountdown').textContent = count;
            if (count <= 0) {
                _hideAutoAdvance();
                await loadNext();
            }
        }, 1000);
    }

    function _hideAutoAdvance() {
        if (_autoAdvInt) { clearInterval(_autoAdvInt); _autoAdvInt = null; }
        $('autoAdvanceStrip').classList.add('hidden');
    }

    window.cancelAutoAdvance = function () {
        _hideAutoAdvance();
        // Stay in current state (wrap_up, typically already logged)
        _setState('idle');
        // Re-render the current contact so the agent can review
        if (_contact) renderContact(_contact);
    };

    // ── Cross-campaign history ─────────────────────────────────────────────────
    window.loadCrossHistory = async function () {
        if (!_contact) return;
        const btn = $('btnXHistory');
        if (btn) btn.textContent = 'Loading\u2026';

        const r = await apiFetch(`/api/v1/campaigns/contact/${_contact.id}/history?days=30`);
        if (!r.ok) { if (btn) { btn.textContent = 'Error'; btn.disabled = false; } return; }
        const items = await r.json();

        const list  = $('xHistoryList');
        const empty = $('xHistEmpty');
        if (!list) return;
        list.innerHTML = '';

        if (!items.length) {
            if (empty) empty.style.display = '';
            if (btn) btn.textContent = 'No history';
            return;
        }
        if (empty) empty.style.display = 'none';
        if (btn) btn.style.display = 'none';

        const CC = { voice: '#60a5fa', whatsapp: '#22c55e', sms: '#0dcaf0', email: '#f59e0b' };
        items.forEach(item => {
            const col  = _statusColor(item.status);
            const cc   = CC[item.channel] || '#7d8590';
            const when = item.dialled_at ? new Date(item.dialled_at).toLocaleDateString('en-ZA') : '\u2013';
            list.insertAdjacentHTML('beforeend', `
                <div class="x-hist-item mb-1">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="x-hist-channel" style="color:${cc}">${esc(item.channel)}</span>
                        <span class="hist-status" style="color:${col};font-size:10px">${esc(item.status)}</span>
                    </div>
                    <div class="fw-semibold" style="font-size:11px">${esc(item.campaign_name)}</div>
                    <div class="text-muted" style="font-size:10px">${esc(when)}${item.outcome_code ? ' &middot; ' + esc(item.outcome_code) : ''}</div>
                </div>`);
        });
    };

    // ── Exit ──────────────────────────────────────────────────────────────────
    window.exitDialler = function () {
        _stopConnTimer();
        _stopRingTimeout();
        _hideAutoAdvance();
        window.location.href = '/campaigns';
    };

    // ── Boot ──────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

})();

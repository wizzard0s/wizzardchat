/* interactions.js — Interaction History page logic */
'use strict';

const Interactions = (() => {
    const API   = '/api/v1';
    let _page   = 1;
    let _total  = 0;
    let _pageSize = 40;

    // ── Auth header ─────────────────────────────────────────────────────────
    function _h() {
        return { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('wizzardchat_token')}` };
    }

    // ── Init ────────────────────────────────────────────────────────────────
    async function init() {
        await _loadFilters();
        await load(1);
    }

    async function _loadFilters() {
        const res = await fetch(`${API}/interactions/filters`, { headers: _h() });
        if (!res.ok) return;
        const data = await res.json();
        const cc   = document.getElementById('filterConnector');
        const ca   = document.getElementById('filterAgent');
        data.connectors.forEach(c => cc.insertAdjacentHTML('beforeend', `<option value="${c.id}">${_esc(c.name)}</option>`));
        data.agents.forEach(a     => ca.insertAdjacentHTML('beforeend', `<option value="${a.id}">${_esc(a.name)}</option>`));
    }

    // ── Load list ────────────────────────────────────────────────────────────
    async function load(page) {
        _page = page || 1;
        const params = new URLSearchParams({ page: _page, page_size: _pageSize });
        const status    = document.getElementById('filterStatus').value;
        const connector = document.getElementById('filterConnector').value;
        const agent     = document.getElementById('filterAgent').value;
        const search    = document.getElementById('filterSearch').value.trim();
        const from      = document.getElementById('filterFrom').value;
        const to        = document.getElementById('filterTo').value;
        if (status)    params.set('status', status);
        if (connector) params.set('connector_id', connector);
        if (agent)     params.set('agent_id', agent);
        if (search)    params.set('search', search);
        if (from)      params.set('date_from', from);
        if (to)        params.set('date_to', to + 'T23:59:59');

        const res = await fetch(`${API}/interactions?${params}`, { headers: _h() });
        if (!res.ok) { _showError(); return; }
        const data = await res.json();
        _total = data.total;
        _renderTable(data.items);
        _renderPagination(data.total, data.page, data.page_size);
    }

    function reset() {
        ['filterStatus','filterConnector','filterAgent','filterSearch','filterFrom','filterTo']
            .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        load(1);
    }

    // ── Table ────────────────────────────────────────────────────────────────
    function _renderTable(items) {
        const tbody = document.getElementById('ixTableBody');
        document.getElementById('totalLabel').textContent = `${_total.toLocaleString()} interactions`;
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center text-secondary py-4">No interactions match the current filters.</td></tr>';
            return;
        }
        tbody.innerHTML = items.map(ix => {
            const started = ix.created_at ? _fmtDate(ix.created_at) : '—';
            const statusBadge = `<span class="badge badge-status-${ix.status}">${_statusLabel(ix.status)}</span>`;
            const outcome  = ix.disconnect_outcome ? `<span class="badge badge-outcome">${_esc(ix.disconnect_outcome)}</span>` : '<span class="text-muted">—</span>';
            const csat     = ix.csat_score   ? _renderStarsMini(ix.csat_score, 5)   : '<span class="text-muted">—</span>';
            const nps      = ix.nps_score !== null && ix.nps_score !== undefined ? `<span class="badge bg-secondary">${ix.nps_score}</span>` : '<span class="text-muted">—</span>';
            const agentTxt = _esc(ix.agent_name || '—');
            const connTxt  = _esc(ix.connector_name || '—');
            const session  = _esc(ix.session_key.slice(0, 18) + (ix.session_key.length > 18 ? '…' : ''));
            const tagChips = (ix.tags || []).map(t => `<span class="tag-chip ms-1">${_esc(t)}</span>`).join('');
            return `<tr class="ix-row" onclick="Interactions.openDetail('${ix.id}')">
                <td class="text-secondary">${started}</td>
                <td><code class="text-info" style="font-size:.78rem;">${session}</code>${tagChips}</td>
                <td>${connTxt}</td>
                <td>${agentTxt}</td>
                <td>${statusBadge}</td>
                <td class="text-secondary">${ix.message_count || 0}</td>
                <td>${outcome}</td>
                <td>${csat}</td>
                <td>${nps}</td>
            </tr>`;
        }).join('');
    }

    function _showError() {
        document.getElementById('ixTableBody').innerHTML =
            '<tr><td colspan="9" class="text-center text-danger py-4"><i class="bi bi-exclamation-triangle me-1"></i>Failed to load interactions.</td></tr>';
    }

    // ── Pagination ────────────────────────────────────────────────────────────
    function _renderPagination(total, page, pageSize) {
        const totalPages = Math.ceil(total / pageSize);
        document.getElementById('pageInfo').textContent =
            `Page ${page} of ${totalPages} — ${total.toLocaleString()} records`;
        const bar = document.getElementById('paginationBar');
        bar.innerHTML = '';
        if (totalPages <= 1) return;
        const add = (label, p, disabled) => {
            bar.insertAdjacentHTML('beforeend',
                `<button class="btn btn-sm ${p === page ? 'btn-info' : 'btn-outline-secondary'}" ${disabled ? 'disabled' : ''} onclick="Interactions.load(${p})">${label}</button>`
            );
        };
        add('‹', page - 1, page === 1);
        const start = Math.max(1, page - 2);
        const end   = Math.min(totalPages, page + 2);
        if (start > 1) { add('1', 1, false); if (start > 2) bar.insertAdjacentHTML('beforeend', '<span class="text-muted px-1">…</span>'); }
        for (let p = start; p <= end; p++) add(p, p, false);
        if (end < totalPages) { if (end < totalPages - 1) bar.insertAdjacentHTML('beforeend', '<span class="text-muted px-1">…</span>'); add(totalPages, totalPages, false); }
        add('›', page + 1, page === totalPages);
    }

    // ── Detail panel ─────────────────────────────────────────────────────────
    async function openDetail(id) {
        const panel = document.getElementById('detailPanel');
        const body  = document.getElementById('detailPanelBody');
        body.innerHTML = '<div class="text-center py-5 text-secondary"><i class="bi bi-hourglass-split me-1"></i>Loading…</div>';
        document.getElementById('overlay').classList.add('show');
        panel.classList.add('open');

        const res = await fetch(`${API}/interactions/${id}`, { headers: _h() });
        if (!res.ok) {
            body.innerHTML = '<div class="text-danger p-3">Failed to load interaction detail.</div>';
            return;
        }
        const ix = await res.json();
        body.innerHTML = _buildDetail(ix);
    }

    function closeDetail() {
        document.getElementById('detailPanel').classList.remove('open');
        document.getElementById('overlay').classList.remove('show');
    }

    // ── Build detail HTML ─────────────────────────────────────────────────────
    function _buildDetail(ix) {
        const created = ix.created_at ? _fmtDate(ix.created_at) : '—';
        const statusBadge = `<span class="badge badge-status-${ix.status} fs-6">${_statusLabel(ix.status)}</span>`;
        const session = _esc(ix.session_key);

        let html = `
        <h6 class="text-info mb-0 pe-5"><i class="bi bi-chat-square-text me-2"></i>Interaction Detail</h6>
        <div class="d-flex gap-2 align-items-center mt-1 mb-3">
            ${statusBadge}
            <code class="text-secondary" style="font-size:.75rem;">${session}</code>
            <span class="text-muted" style="font-size:.78rem;">${created}</span>
        </div>`;

        // ── Meta row ──
        html += `<div class="row g-2 mb-3" style="font-size:.83rem;">
            <div class="col-6 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;">Connector</div>
                <div>${_esc(ix.connector_name || '—')}</div>
            </div>
            <div class="col-6 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;">Agent</div>
                <div>${_esc(ix.agent_name || '—')}</div>
            </div>
            <div class="col-6 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;">Queue</div>
                <div>${_esc(ix.queue_name || '—')}</div>
            </div>
            <div class="col-6 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;">Wrap-up time</div>
                <div>${ix.wrap_time != null ? ix.wrap_time + 's' : '—'}</div>
            </div>
        </div>`;

        // ── Visitor metadata ──
        const vm = ix.visitor_metadata || {};
        if (vm.page_url || vm.page_title || vm.trigger_type) {
            html += `<div class="metric-card mb-3" style="font-size:.82rem;">
                <div class="text-secondary mb-1 fw-semibold" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-globe me-1"></i>Visitor info</div>
                ${vm.page_title ? `<div class="mb-1"><span class="text-secondary">Page:</span> ${_esc(vm.page_title)}</div>` : ''}
                ${vm.page_url   ? `<div class="mb-1 text-truncate"><span class="text-secondary">URL:</span> <a href="${_esc(vm.page_url)}" target="_blank" class="text-info" style="font-size:.78rem;">${_esc(vm.page_url)}</a></div>` : ''}
                ${vm.trigger_type ? `<div><span class="text-secondary">Trigger:</span> <span class="badge badge-outline-info">${_esc(vm.trigger_type)}</span> <span class="text-muted">${_esc(vm.trigger_value || '')}</span></div>` : ''}
            </div>`;
        }

        // ── Segment lifecycle bar ──
        if (ix.segments && ix.segments.length) {
            html += _buildSegmentBar(ix.segments);
        }

        // ── Outcome + CSAT + NPS ──
        html += `<div class="row g-2 mb-3">`;
        if (ix.disconnect_outcome) {
            html += `<div class="col-12 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-flag me-1"></i>Outcome</div>
                <span class="badge badge-outcome fs-6">${_esc(ix.disconnect_outcome)}</span>
            </div>`;
        }
        if (ix.csat_score != null) {
            html += `<div class="col-12 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-star me-1"></i>CSAT</div>
                <div class="csat-stars fs-5 mb-1">${_renderStars(ix.csat_score, 5)}</div>
                <div class="text-secondary" style="font-size:.78rem;">${ix.csat_comment ? _esc(ix.csat_comment) : 'No comment.'}</div>
                ${ix.csat_submitted_at ? `<div class="text-muted mt-1" style="font-size:.7rem;">Submitted ${_fmtDate(ix.csat_submitted_at)}</div>` : ''}
            </div>`;
        }
        if (ix.nps_score != null) {
            html += `<div class="col-12 metric-card">
                <div class="text-secondary mb-1" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-graph-up me-1"></i>NPS</div>
                ${_renderNPS(ix.nps_score)}
                ${ix.nps_reason ? `<div class="text-secondary mt-1" style="font-size:.78rem;">${_esc(ix.nps_reason)}</div>` : ''}
            </div>`;
        }
        html += `</div>`;

        // ── Notes (AI summary) ──
        if (ix.notes) {
            html += `<div class="metric-card mb-3">
                <div class="text-secondary mb-1 fw-semibold" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-robot me-1"></i>AI Summary</div>
                <p class="mb-0" style="font-size:.83rem;line-height:1.5;">${_esc(ix.notes)}</p>
            </div>`;
        }

        // ── Tags ──
        if (ix.tags && ix.tags.length) {
            html += `<div class="mb-3 d-flex flex-wrap gap-1">
                ${ix.tags.map(t => `<span class="tag-chip"><i class="bi bi-tag me-1"></i>${_esc(t)}</span>`).join('')}
            </div>`;
        }

        // ── Survey submissions ──
        if (ix.survey_submissions && ix.survey_submissions.length) {
            html += `<div class="metric-card mb-3">
                <div class="text-secondary mb-2 fw-semibold" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-clipboard-check me-1"></i>Survey Submissions</div>
                ${ix.survey_submissions.map(s => `
                <div class="mb-2 pb-2 border-bottom border-secondary">
                    <div class="text-info fw-semibold mb-1" style="font-size:.8rem;">${_esc(s.survey_name)}</div>
                    ${Object.entries(s.responses || {}).map(([k,v]) => `
                    <div style="font-size:.78rem;"><span class="text-secondary">${_esc(k)}:</span> ${_esc(String(v))}</div>`).join('')}
                    <div class="text-muted mt-1" style="font-size:.7rem;">${s.submitted_at ? _fmtDate(s.submitted_at) : ''}</div>
                </div>`).join('')}
            </div>`;
        }

        // ── Chat timeline ──
        html += `<div class="mb-2">
            <div class="text-secondary mb-2 fw-semibold" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-chat-left-dots me-1"></i>Transcript (${(ix.message_log||[]).length} messages)</div>
            ${_buildTimeline(ix.message_log || [])}
        </div>`;

        return html;
    }

    // ── Segment lifecycle bar ─────────────────────────────────────────────────
    function _buildSegmentBar(segments) {
        // Calculate total duration in seconds for proportional sizing
        let totalMs = 0;
        const withDuration = segments.map(s => {
            const start = s.started_at ? new Date(s.started_at) : null;
            const end   = s.ended_at   ? new Date(s.ended_at)   : new Date();
            const ms    = (start && end) ? Math.max(0, end - start) : 0;
            totalMs += ms;
            return { ...s, ms };
        });

        const SEG_ICONS = { flow:'diagram-3', queue:'hourglass-split', agent:'headset', wrap_up:'clock-history' };
        const SEG_LABELS = { flow:'Flow', queue:'Queue wait', agent:'Agent', wrap_up:'Wrap-up' };

        const chunks = withDuration.map(s => {
            const pct   = totalMs > 0 ? Math.max(3, (s.ms / totalMs) * 100) : (100 / withDuration.length);
            const label = SEG_LABELS[s.type] || s.type;
            const icon  = SEG_ICONS[s.type]  || 'circle';
            const dur   = s.ms > 0 ? _fmtDur(s.ms / 1000) : '';
            return `<div class="seg-chunk seg-${s.type || 'unknown'}" style="flex:${pct.toFixed(1)};"
                         title="${label}${dur ? ' · ' + dur : ''}">
                <i class="bi bi-${icon} me-1"></i>${label}${dur ? ` · ${dur}` : ''}
            </div>`;
        }).join('');

        // Detailed segment list
        const details = withDuration.map(s => {
            const start = s.started_at ? _fmtDate(s.started_at) : '—';
            const end   = s.ended_at   ? _fmtDate(s.ended_at)   : 'ongoing';
            const dur   = s.ms > 0 ? ' · ' + _fmtDur(s.ms / 1000) : '';
            const label = SEG_LABELS[s.type] || s.type;
            return `<div class="d-flex justify-content-between" style="font-size:.75rem;border-bottom:1px solid #2a2a3e;padding:.25rem 0;">
                <span class="seg-${s.type || 'unknown'} px-2 rounded">${label}</span>
                <span class="text-muted">${start} → ${end}${dur}</span>
            </div>`;
        }).join('');

        return `<div class="metric-card mb-3">
            <div class="text-secondary mb-2 fw-semibold" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"><i class="bi bi-bar-chart-steps me-1"></i>Lifecycle</div>
            <div class="seg-bar mb-2">${chunks}</div>
            ${details}
        </div>`;
    }

    // ── Chat timeline bubbles ─────────────────────────────────────────────────
    function _buildTimeline(messages) {
        if (!messages.length) return '<div class="text-muted" style="font-size:.82rem;">No messages recorded.</div>';

        const FROM_CONFIG = {
            bot:     { cls:'bot',     avatar:'robot',        label:'Bot'    },
            agent:   { cls:'agent',   avatar:'headset',      label:'Agent'  },
            visitor: { cls:'visitor', avatar:'person-circle', label:'Visitor' },
            system:  { cls:'system',  avatar:'',             label:'System' },
        };

        const bubbles = messages.map(m => {
            const cfg  = FROM_CONFIG[m.from] || FROM_CONFIG.system;
            const ts   = m.ts ? _fmtTime(m.ts) : '';
            const text = m.subtype === 'attachment'
                ? `<i class="bi bi-paperclip me-1"></i><em>${_esc(m.filename || m.text)}</em>`
                : _esc(m.text || '');

            if (m.from === 'system') {
                return `<div class="msg-row system">
                    <div class="msg-bubble">${text} <span class="ms-1 text-muted" style="font-size:.68rem;">${ts}</span></div>
                </div>`;
            }

            const avatar = cfg.avatar
                ? `<div class="msg-avatar avatar-${cfg.cls}"><i class="bi bi-${cfg.avatar}"></i></div>`
                : '';

            if (m.from === 'visitor') {
                return `<div class="msg-row visitor">
                    <div>
                        <div class="msg-meta text-end">${ts}</div>
                        <div class="msg-bubble">${text}</div>
                    </div>
                    ${avatar}
                </div>`;
            }
            return `<div class="msg-row ${cfg.cls}">
                ${avatar}
                <div>
                    <div class="msg-meta">${cfg.label} · ${ts}</div>
                    <div class="msg-bubble">${text}</div>
                </div>
            </div>`;
        }).join('');

        return `<div class="chat-timeline">${bubbles}</div>`;
    }

    // ── Helpers ───────────────────────────────────────────────────────────────
    function _renderStars(score, max) {
        let out = '';
        for (let i = 1; i <= max; i++) {
            out += `<i class="bi bi-star${i <= score ? '-fill star-filled' : ' star-empty'}"></i>`;
        }
        return out;
    }

    function _renderStarsMini(score, max) {
        let out = `<span class="csat-stars text-nowrap" style="font-size:.78rem;">`;
        for (let i = 1; i <= max; i++) {
            out += `<i class="bi bi-star${i <= score ? '-fill star-filled' : ' star-empty'}"></i>`;
        }
        return out + '</span>';
    }

    function _renderNPS(score) {
        const color  = score >= 9 ? '#22c55e' : score >= 7 ? '#f59e0b' : '#ef4444';
        const label  = score >= 9 ? 'Promoter' : score >= 7 ? 'Passive' : 'Detractor';
        return `<div class="d-flex align-items-center gap-2">
            <span style="font-size:1.6rem;font-weight:700;color:${color};">${score}</span>
            <span style="font-size:.78rem;color:${color};">${label}</span>
            <div style="flex:1;height:8px;border-radius:4px;background:#2a2a3e;overflow:hidden;">
                <div style="width:${(score/10)*100}%;height:100%;background:${color};border-radius:4px;"></div>
            </div>
        </div>`;
    }

    function _statusLabel(s) {
        return { active:'Active', closed:'Closed', with_agent:'With Agent', waiting_agent:'Waiting' }[s] || s;
    }

    function _fmtDate(iso) {
        if (!iso) return '—';
        const d = new Date(iso);
        return d.toLocaleDateString('en-ZA', { year:'numeric', month:'short', day:'numeric' })
             + ' ' + d.toLocaleTimeString('en-ZA', { hour:'2-digit', minute:'2-digit' });
    }

    function _fmtTime(iso) {
        if (!iso) return '';
        return new Date(iso).toLocaleTimeString('en-ZA', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
    }

    function _fmtDur(seconds) {
        if (seconds < 60)   return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds/60)}m ${Math.round(seconds%60)}s`;
        return `${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m`;
    }

    function _esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    return { init, load, reset, openDetail, closeDetail };
})();

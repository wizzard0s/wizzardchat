/**
 * WizzardChat – Campaigns management page
 */
(function () {
    'use strict';

    const API = '';
    const _token = () => localStorage.getItem('wizzardchat_token');
    const _headers = () => ({ 'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    let _campaigns = [];
    let _editId = null;
    let _deleteId = null;
    let _allOutcomes = [];
    let _allQueues = [];
    let _allUsers = [];

    const modal    = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('campaignModal'));
    const delModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteCModal'));

    function _guard() {
        if (!_token()) { window.location.href = '/'; }
    }

    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/'; }
        return r;
    }

    function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    function _statusBadge(status) {
        const map = {
            running:   ['Running',   'bg-success'],
            draft:     ['Draft',     'bg-secondary'],
            paused:    ['Paused',    'bg-warning text-dark'],
            completed: ['Completed', 'bg-primary'],
            cancelled: ['Cancelled', 'bg-danger'],
        };
        const [label, cls] = map[status] ?? [status, 'bg-secondary'];
        return `<span class="badge ${cls}">${label}</span>`;
    }

    function _typeLabel(t) {
        return { inbound: 'Inbound', outbound: 'Outbound', blended: 'Blended' }[t] ?? t;
    }

    // ─── Load / Render ─────────────────────────────────────────────────────────
    async function loadCampaigns() {
        const r = await apiFetch('/api/v1/campaigns');
        _campaigns = r.ok ? await r.json() : [];
        renderCampaigns();
    }

    function renderCampaigns() {
        const grid  = document.getElementById('campaignGrid');
        const empty = document.getElementById('campaignEmpty');
        grid.querySelectorAll('.camp-col').forEach(el => el.remove());

        if (!_campaigns.length) {
            empty.style.display = 'flex';
            return;
        }
        empty.style.display = 'none';

        _campaigns.forEach(c => {
            const col = document.createElement('div');
            col.className = 'col-md-4 col-lg-3 camp-col';
            const outcomeCount = (c.outcomes || []).length;
            const queueCount   = (c.queues || []).length;
            const agentCount   = (c.agents || []).length;
            const ct = c.campaign_time || {};
            const timeStr = (ct.start && ct.end) ? `${ct.start}–${ct.end}` : '—';
            const activeBadge = c.is_active
                ? '<span class="badge bg-success ms-1">Active</span>'
                : '<span class="badge bg-secondary ms-1">Inactive</span>';
            col.innerHTML = `
<div class="card campaign-card h-100" onclick="openCampaignModal('${c.id}')">
    <div class="card-body">
        <div class="d-flex align-items-center gap-2 mb-2">
            <span class="camp-color-dot" style="background:${esc(c.color || '#0d6efd')}"></span>
            <span class="fw-semibold text-truncate">${esc(c.name)}</span>
            ${_statusBadge(c.status)}${activeBadge}
        </div>
        <p class="text-muted small mb-2">${esc(c.description || '—')}</p>
        <div class="small">
            <span class="badge bg-secondary me-1">${_typeLabel(c.campaign_type)}</span>
            <span class="text-muted"><i class="bi bi-clock me-1"></i>${timeStr}</span>
        </div>
    </div>
    <div class="card-footer d-flex justify-content-between align-items-center py-1 px-2">
        <span class="d-flex gap-2">
            <small class="text-muted"><i class="bi bi-people me-1"></i>${queueCount} queue${queueCount !== 1 ? 's' : ''}</small>
            <small class="text-muted"><i class="bi bi-person-badge me-1"></i>${agentCount} agent${agentCount !== 1 ? 's' : ''}</small>
            <small class="text-muted"><i class="bi bi-flag me-1"></i>${outcomeCount} outcome${outcomeCount !== 1 ? 's' : ''}</small>
        </span>
        <button class="btn btn-sm btn-link text-danger p-0" onclick="event.stopPropagation();deleteCampaign('${c.id}','${esc(c.name)}')">
            <i class="bi bi-trash"></i>
        </button>
    </div>
</div>`;
            grid.appendChild(col);
        });
    }

    // ─── Modal open ────────────────────────────────────────────────────────────
    window.openCampaignModal = function (id) {
        _editId = id || null;
        const title = document.getElementById('campaignModalTitle');

        if (_editId) {
            const c = _campaigns.find(x => x.id === _editId);
            if (!c) return;
            title.innerHTML = `<i class="bi bi-megaphone me-2"></i>Edit Campaign`;
            _fillForm(c);
        } else {
            title.innerHTML = `<i class="bi bi-megaphone me-2"></i>New Campaign`;
            _resetForm();
        }

        const firstTab = document.querySelector('#campaignTabs .nav-link');
        bootstrap.Tab.getOrCreateInstance(firstTab).show();
        modal().show();
    };

    function _resetForm() {
        document.getElementById('cName').value = '';
        document.getElementById('cDescription').value = '';
        document.getElementById('cColor').value = '#0d6efd';
        document.getElementById('cTimeStart').value = '08:00';
        document.getElementById('cTimeEnd').value = '17:00';
        document.getElementById('cIsActive').checked = true;
        document.getElementById('cAllowTransfer').checked = true;
        document.getElementById('cAllowCallback').checked = false;
        _renderOutcomeCheckboxes('cOutcomeList', 'cOutcomeEmpty', []);
        _renderQueueCheckboxes([]);
        _renderUserCheckboxes([]);
    }

    function _fillForm(c) {
        document.getElementById('cName').value = c.name || '';
        document.getElementById('cDescription').value = c.description || '';
        document.getElementById('cColor').value = c.color || '#0d6efd';
        const ct = c.campaign_time || {};
        document.getElementById('cTimeStart').value = ct.start || '08:00';
        document.getElementById('cTimeEnd').value   = ct.end   || '17:00';
        document.getElementById('cIsActive').checked = !!c.is_active;

        const opts = c.options || {};
        document.getElementById('cAllowTransfer').checked = opts.allow_transfer !== false;
        document.getElementById('cAllowCallback').checked = !!opts.allow_callback;

        // Outcomes
        _renderOutcomeCheckboxes('cOutcomeList', 'cOutcomeEmpty', c.outcomes || []);
        // Queues
        _renderQueueCheckboxes(c.queues || []);
        // Agents
        _renderUserCheckboxes(c.agents || []);
    }

    // ─── Global outcomes ────────────────────────────────────────────────────────
    async function loadAllOutcomes() {
        const r = await apiFetch('/api/v1/outcomes?active_only=true');
        _allOutcomes = r.ok ? await r.json() : [];
    }

    function _renderOutcomeCheckboxes(listId, emptyId, selectedIds) {
        const list  = document.getElementById(listId);
        const empty = document.getElementById(emptyId);
        list.innerHTML = '';
        if (!_allOutcomes.length) {
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';
        const typeBadge = { positive: 'success', negative: 'danger', neutral: 'secondary', escalation: 'warning' };
        _allOutcomes.forEach(o => {
            const checked = selectedIds.includes(o.id) ? 'checked' : '';
            const badge   = typeBadge[o.outcome_type] ?? 'secondary';
            const col     = document.createElement('div');
            col.className = 'col-md-6';
            col.innerHTML = `
<div class="form-check border border-secondary rounded p-2 ms-0">
    <input class="form-check-input" type="checkbox" value="${o.id}" id="co_${o.id}" ${checked}>
    <label class="form-check-label d-flex align-items-center gap-2" for="co_${o.id}">
        <span class="fw-semibold">${esc(o.label)}</span>
        <span class="badge bg-${badge} text-uppercase" style="font-size:.65rem">${esc(o.outcome_type)}</span>
        <code class="text-muted" style="font-size:.75rem">${esc(o.code)}</code>
    </label>
</div>`;
            list.appendChild(col);
        });
    }

    // ─── Outcomes (checkbox selection) ─────────────────────────────────────────
    function _readOutcomes() {
        return Array.from(document.querySelectorAll('#cOutcomeList input[type=checkbox]:checked')).map(el => el.value);
    }
    // ─── Queues (checkbox selection) ──────────────────────────────────────────
    async function loadAllQueues() {
        const r = await apiFetch('/api/v1/queues');
        _allQueues = r.ok ? await r.json() : [];
    }

    function _renderQueueCheckboxes(selectedIds) {
        const list  = document.getElementById('cQueueList');
        const empty = document.getElementById('cQueueEmpty');
        list.innerHTML = '';
        if (!_allQueues.length) {
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';
        const channelIcon = { chat: 'bi-chat', voice: 'bi-telephone', whatsapp: 'bi-whatsapp', email: 'bi-envelope', sms: 'bi-phone' };
        _allQueues.forEach(q => {
            const checked = selectedIds.includes(q.id) ? 'checked' : '';
            const icon    = channelIcon[q.channel] ?? 'bi-people';
            const col     = document.createElement('div');
            col.className = 'col-md-6';
            col.innerHTML = `
<div class="form-check border border-secondary rounded p-2 ms-0">
    <input class="form-check-input" type="checkbox" value="${q.id}" id="cq_${q.id}" ${checked}>
    <label class="form-check-label d-flex align-items-center gap-2" for="cq_${q.id}">
        <span class="queue-color-dot" style="background:${esc(q.color || '#fd7e14')};width:10px;height:10px;border-radius:50%;display:inline-block;flex-shrink:0"></span>
        <span class="fw-semibold">${esc(q.name)}</span>
        <span class="badge bg-dark border"><i class="bi ${icon} me-1"></i>${esc(q.channel)}</span>
        ${q.is_active ? '' : '<span class="badge bg-secondary">Inactive</span>'}
    </label>
</div>`;
            list.appendChild(col);
        });
    }

    function _readQueues() {
        return Array.from(document.querySelectorAll('#cQueueList input[type=checkbox]:checked')).map(el => el.value);
    }
    // ─── Users / Agents (checkbox selection) ──────────────────────────────────
    async function loadAllUsers() {
        const r = await apiFetch('/api/v1/users');
        _allUsers = r.ok ? (await r.json()).filter(u => u.is_active !== false) : [];
    }

    function _renderUserCheckboxes(selectedIds) {
        const list  = document.getElementById('cAgentList');
        const empty = document.getElementById('cAgentEmpty');
        list.innerHTML = '';
        if (!_allUsers.length) {
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';
        const roleColor = { super_admin: 'danger', admin: 'warning', supervisor: 'info', agent: 'primary', viewer: 'secondary' };
        _allUsers.forEach(u => {
            const checked   = selectedIds.includes(u.id) ? 'checked' : '';
            const roleBadge = roleColor[u.role] ?? 'secondary';
            const online    = u.is_online
                ? '<span class="badge bg-success" style="font-size:.6rem">Online</span>'
                : '<span class="badge bg-secondary" style="font-size:.6rem">Offline</span>';
            const col = document.createElement('div');
            col.className = 'col-md-6';
            col.innerHTML = `
<div class="form-check border border-secondary rounded p-2 ms-0">
    <input class="form-check-input" type="checkbox" value="${u.id}" id="ca_${u.id}" ${checked}>
    <label class="form-check-label d-flex align-items-center gap-2" for="ca_${u.id}">
        <span class="fw-semibold">${esc(u.full_name || u.username)}</span>
        <span class="badge bg-${roleBadge}" style="font-size:.65rem">${esc(u.role)}</span>
        ${online}
    </label>
</div>`;
            list.appendChild(col);
        });
    }

    function _readAgents() {
        return Array.from(document.querySelectorAll('#cAgentList input[type=checkbox]:checked')).map(el => el.value);
    }
    // ─── Save ──────────────────────────────────────────────────────────────────
    window.saveCampaign = async function () {
        const name = document.getElementById('cName').value.trim();
        if (!name) { alert('Campaign name is required.'); return; }

        const body = {
            name,
            description:   document.getElementById('cDescription').value.trim() || null,
            color:         document.getElementById('cColor').value,
            campaign_time: {
                start: document.getElementById('cTimeStart').value,
                end:   document.getElementById('cTimeEnd').value,
            },
            is_active: document.getElementById('cIsActive').checked,
            options: {
                allow_transfer: document.getElementById('cAllowTransfer').checked,
                allow_callback: document.getElementById('cAllowCallback').checked,
            },
            outcomes: _readOutcomes(),
            queues:   _readQueues(),
            agents:   _readAgents(),
        };

        const url    = _editId ? `/api/v1/campaigns/${_editId}` : '/api/v1/campaigns';
        const method = _editId ? 'PUT' : 'POST';

        const r = await apiFetch(url, { method, body: JSON.stringify(body) });
        if (!r.ok) {
            const e = await r.json().catch(() => ({}));
            const msg = Array.isArray(e.detail)
                ? e.detail.map(d => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('\n')
                : (e.detail || 'Save failed');
            alert(msg);
            return;
        }

        modal().hide();
        await loadCampaigns();
    };

    // ─── Delete ────────────────────────────────────────────────────────────────
    window.deleteCampaign = function (id, name) {
        _deleteId = id;
        document.getElementById('deleteCName').textContent = name;
        delModal().show();
    };

    window.confirmDeleteCampaign = async function () {
        if (!_deleteId) return;
        await apiFetch(`/api/v1/campaigns/${_deleteId}`, { method: 'DELETE' });
        delModal().hide();
        _deleteId = null;
        await loadCampaigns();
    };

    // ─── Logout ────────────────────────────────────────────────────────────────
    document.getElementById('btnLogout').addEventListener('click', e => {
        e.preventDefault();
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/';
    });

    // ─── Boot ──────────────────────────────────────────────────────────────────
    _guard();    loadAllOutcomes();    loadAllQueues();    loadAllUsers();    loadCampaigns();

    (async () => {
        const r = await apiFetch('/api/v1/users/me').catch(() => null);
        if (r && r.ok) {
            const u = await r.json();
            const el = document.getElementById('currentUser');
            if (el) el.textContent = u.full_name || u.username || 'Agent';
        }
    })();
})();

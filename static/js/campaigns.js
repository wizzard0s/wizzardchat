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
    let _allGroups = [];
    let _allConnectors = [];
    let _allTemplates  = [];
    let _waMetaTemplates = [];

    // ─── Shuttle Widget ────────────────────────────────────────────────────────
    const _sh = {};

    function shuttleCreate(id, items, selectedIds) {
        _sh[id] = {
            items:    new Map(items.map(i => [i.id, i])),
            selected: new Set((selectedIds || []).map(String)),
        };
        _shuttleRender(id);
    }

    function _shuttleRender(id) {
        const state = _sh[id];
        if (!state) return;
        const avail = [...state.items.values()].filter(i => !state.selected.has(i.id));
        const sel   = [...state.items.values()].filter(i =>  state.selected.has(i.id));
        const af = (document.getElementById(id + '_avail_search') || {}).value || '';
        const sf = (document.getElementById(id + '_sel_search')   || {}).value || '';
        _fillShuttleList(id + '_avail_list', avail, af);
        _fillShuttleList(id + '_sel_list',   sel,   sf);
        const ah = document.getElementById(id + '_avail_hdr');
        const sh = document.getElementById(id + '_sel_hdr');
        if (ah) ah.textContent = `Available (${avail.length})`;
        if (sh) sh.textContent = `Selected (${sel.length})`;
    }

    function _fillShuttleList(listId, items, filter) {
        const ul = document.getElementById(listId);
        if (!ul) return;
        const q = filter.toLowerCase();
        ul.innerHTML = '';
        items.filter(i => !q || i.searchText.toLowerCase().includes(q)).forEach(i => {
            const btn  = document.createElement('button');
            btn.type   = 'button';
            btn.className = 'list-group-item list-group-item-action py-1 px-2 border-0 shuttle-item';
            btn.dataset.id = i.id;
            btn.innerHTML  = i.html;
            btn.addEventListener('click', () => btn.classList.toggle('active'));
            ul.appendChild(btn);
        });
    }

    window.shuttleMove = function(id, direction) {
        const state = _sh[id];
        if (!state) return;
        if (direction === 'all_right') {
            state.items.forEach(i => state.selected.add(i.id));
        } else if (direction === 'all_left') {
            state.selected.clear();
        } else if (direction === 'sel_right') {
            document.querySelectorAll(`#${id}_avail_list .active`).forEach(el => state.selected.add(el.dataset.id));
        } else if (direction === 'sel_left') {
            document.querySelectorAll(`#${id}_sel_list .active`).forEach(el => state.selected.delete(el.dataset.id));
        }
        _shuttleRender(id);
    };

    function shuttleGetSelected(id) {
        return _sh[id] ? [..._sh[id].selected] : [];
    }

    function _buildShuttleHtml(id) {
        return `
<div class="d-flex flex-column flex-fill" style="min-width:0">
  <div class="small fw-semibold text-muted mb-1" id="${id}_avail_hdr">Available</div>
  <input type="search" class="form-control form-control-sm mb-1" id="${id}_avail_search"
         placeholder="Filter\u2026" oninput="_shuttleRender('${id}')">
  <div class="list-group list-group-flush overflow-auto shuttle-list" id="${id}_avail_list"></div>
</div>
<div class="d-flex flex-column align-items-center justify-content-center gap-1 px-2 flex-shrink-0">
  <button type="button" class="btn btn-sm btn-outline-primary px-2" title="Add all" onclick="shuttleMove('${id}','all_right')">»</button>
  <button type="button" class="btn btn-sm btn-outline-primary px-2" title="Add selected" onclick="shuttleMove('${id}','sel_right')">›</button>
  <button type="button" class="btn btn-sm btn-outline-secondary px-2" title="Remove selected" onclick="shuttleMove('${id}','sel_left')">‹</button>
  <button type="button" class="btn btn-sm btn-outline-secondary px-2" title="Remove all" onclick="shuttleMove('${id}','all_left')">«</button>
</div>
<div class="d-flex flex-column flex-fill" style="min-width:0">
  <div class="small fw-semibold text-muted mb-1" id="${id}_sel_hdr">Selected</div>
  <input type="search" class="form-control form-control-sm mb-1" id="${id}_sel_search"
         placeholder="Filter\u2026" oninput="_shuttleRender('${id}')">
  <div class="list-group list-group-flush overflow-auto shuttle-list" id="${id}_sel_list"></div>
</div>`;
    }

    function _initGroupShuttle(selectedIds) {
        document.getElementById('groupShuttleWrap').innerHTML = _buildShuttleHtml('campGroups');
        shuttleCreate('campGroups', _allGroups.map(g => ({
            id:         g.id,
            searchText: g.name,
            html: `<span class="fw-semibold">${esc(g.name)}</span>`
                  + ` <span class="badge bg-secondary ms-1" style="font-size:.6rem">${g.members?.length ?? 0} members</span>`,
        })), selectedIds || []);
    }

    function _initAgentShuttle(selectedIds) {
        document.getElementById('agentShuttleWrap').innerHTML = _buildShuttleHtml('campAgents');
        const roleClass = { super_admin: 'wz-role-super-admin', admin: 'wz-role-admin', supervisor: 'wz-role-supervisor', agent: 'wz-role-agent', viewer: 'wz-role-viewer' };
        shuttleCreate('campAgents', _allUsers.map(u => ({
            id:         u.id,
            searchText: (u.full_name || u.username) + ' ' + u.role,
            html: `<span class="fw-semibold">${esc(u.full_name || u.username)}</span>`
                  + ` <span class="wz-badge ${roleClass[u.role] ?? 'wz-role-viewer'} ms-1" style="font-size:.6rem">${esc(u.role)}</span>`,
        })), selectedIds || []);
    }

    const modal    = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('campaignModal'));
    const delModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteCModal'));

    function _guard() {
        if (!_token()) { window.location.href = '/login'; }
    }

    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/login'; }
        return r;
    }

    function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    function _statusBadge(status) {
        const map = {
            running:   ['Running',   'wz-status-running'],
            draft:     ['Draft',     'wz-status-draft'],
            paused:    ['Paused',    'wz-status-paused'],
            completed: ['Completed', 'wz-status-completed'],
            cancelled: ['Cancelled', 'wz-status-cancelled'],
        };
        const [label, cls] = map[status] ?? [status, 'wz-status-inactive'];
        return `<span class="wz-badge ${cls}">${label}</span>`;
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
                ? '<span class="wz-badge wz-status-active ms-1">Active</span>'
                : '<span class="wz-badge wz-status-inactive ms-1">Inactive</span>';
            const diallerBtn = (c.status === 'running')
                ? `<button class="btn btn-sm btn-success w-100 mt-2" style="font-size:12px"
                      onclick="event.stopPropagation();window.location.href='/dialler/${c.id}'">
                      <i class="bi bi-telephone-outbound me-1"></i>Open Dialler
                   </button>`
                : '';
            const modeLabel = (() => {
                const m = (c.settings || {}).dialler_mode;
                if (m === 'progressive') return '<span class="wz-badge wz-mode-progressive ms-1">Progressive</span>';
                if (m === 'preview') return '<span class="wz-badge wz-mode-preview ms-1">Preview</span>';
                return '';
            })();
            col.innerHTML = `
<div class="card campaign-card h-100" onclick="openCampaignModal('${c.id}')">
    <div class="card-body">
        <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
            <span class="camp-color-dot" style="background:${esc(c.color || '#0d6efd')}"></span>
            <span class="fw-semibold text-truncate">${esc(c.name)}</span>
            ${_statusBadge(c.status)}${activeBadge}${modeLabel}
        </div>
        <p class="text-muted small mb-2">${esc(c.description || '—')}</p>
        <div class="small">
            <span class="badge bg-secondary me-1">${_typeLabel(c.campaign_type)}</span>
            <span class="text-muted"><i class="bi bi-clock me-1"></i>${timeStr}</span>
        </div>
        ${diallerBtn}
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
        document.getElementById('cDiallerMode').value = 'preview';
        document.getElementById('cRingTimeout').value = '45';
        document.getElementById('cMaxAttempts').value = '3';
        document.getElementById('cRetryInterval').value = '3600';
        _renderOutcomeCheckboxes('cOutcomeList', 'cOutcomeEmpty', []);
        _renderQueueCheckboxes([]);
        _initGroupShuttle([]);
        _initAgentShuttle([]);
        _fillOutboundTab({});
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

        // Dialler settings
        const ds = c.settings || {};
        document.getElementById('cDiallerMode').value   = ds.dialler_mode  || 'preview';
        document.getElementById('cRingTimeout').value   = ds.ring_timeout  || 45;
        document.getElementById('cMaxAttempts').value   = c.max_attempts   || 3;
        document.getElementById('cRetryInterval').value = c.retry_interval || 3600;

        // Outcomes
        _renderOutcomeCheckboxes('cOutcomeList', 'cOutcomeEmpty', c.outcomes || []);
        // Queues
        _renderQueueCheckboxes(c.queues || []);
        // Groups + individual agents
        _initGroupShuttle(c.agent_groups || []);
        _initAgentShuttle(c.agents || []);
        // Outbound config
        _fillOutboundTab(c.outbound_config || {});
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
        const typeBadge = { positive: 'wz-badge-ok', negative: 'wz-badge-fail', neutral: 'wz-badge-muted', escalation: 'wz-badge-warn' };
        _allOutcomes.forEach(o => {
            const checked = selectedIds.includes(o.id) ? 'checked' : '';
            const badge   = typeBadge[o.outcome_type] ?? 'wz-badge-muted';
            const col     = document.createElement('div');
            col.className = 'col-md-6';
            col.innerHTML = `
<div class="form-check border border-secondary rounded p-2 ms-0">
    <input class="form-check-input" type="checkbox" value="${o.id}" id="co_${o.id}" ${checked}>
    <label class="form-check-label d-flex align-items-center gap-2" for="co_${o.id}">
        <span class="fw-semibold">${esc(o.label)}</span>
        <span class="wz-badge ${badge}">${esc(o.outcome_type)}</span>
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
        <span class="wz-badge wz-badge-info"><i class="bi ${icon} me-1"></i>${esc(q.channel)}</span>
        ${q.is_active ? '' : '<span class="wz-badge wz-badge-muted">Inactive</span>'}
    </label>
</div>`;
            list.appendChild(col);
        });
    }

    function _readQueues() {
        return Array.from(document.querySelectorAll('#cQueueList input[type=checkbox]:checked')).map(el => el.value);
    }
    // ─── Users / Agents ────────────────────────────────────────────────────────
    async function loadAllUsers() {
        const r = await apiFetch('/api/v1/users');
        _allUsers = r.ok ? (await r.json()).filter(u => u.is_active !== false) : [];
    }

    async function loadAllGroups() {
        const r = await apiFetch('/api/v1/agent-groups');
        _allGroups = r.ok ? await r.json() : [];
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
            max_attempts:   parseInt(document.getElementById('cMaxAttempts').value, 10) || 3,
            retry_interval: parseInt(document.getElementById('cRetryInterval').value, 10) || 3600,
            settings: {
                dialler_mode: document.getElementById('cDiallerMode').value,
                ring_timeout: parseInt(document.getElementById('cRingTimeout').value, 10) || 45,
            },
            outcomes:     _readOutcomes(),
            queues:        _readQueues(),
            agents:        shuttleGetSelected('campAgents'),
            agent_groups:  shuttleGetSelected('campGroups'),
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

        // Save outbound config to the dedicated endpoint
        const savedCampaign = await r.json().catch(() => null);
        const savedId = savedCampaign?.id || _editId;
        if (savedId) {
            const outboundCfg = _readOutboundTab();
            await apiFetch(`/api/v1/campaigns/${savedId}/outbound-config`, {
                method: 'PUT',
                body: JSON.stringify(outboundCfg),
            });
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
        window.location.href = '/login';
    });

    // ─── Outbound Config ───────────────────────────────────────────────────────

    async function loadAllConnectors() {
        const r = await apiFetch('/api/v1/connectors');
        _allConnectors = r.ok ? await r.json() : [];
    }

    async function loadAllTemplates() {
        const r = await apiFetch('/api/v1/templates');
        _allTemplates = r.ok ? await r.json() : [];
    }

    function _fillConnectorSelect(selectId, providerTypes) {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">— none —</option>';
        _allConnectors
            .filter(c => !providerTypes.length || providerTypes.some(t => (c.connector_type || c.type || '').toLowerCase().includes(t)))
            .forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.name || c.id;
                if (c.id === current) opt.selected = true;
                sel.appendChild(opt);
            });
    }

    function _fillTemplateSelect(selectId, channel) {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">— none —</option>';
        _allTemplates
            .filter(t => t.channel === channel && t.status === 'active')
            .forEach(t => {
                const opt = document.createElement('option');
                opt.value = t.id;
                opt.textContent = t.name;
                if (t.id === current) opt.selected = true;
                sel.appendChild(opt);
            });
        sel.addEventListener('change', () => _onTemplateSelectChange(selectId, channel, sel.value));
    }

    // ─── WhatsApp Meta templates ───────────────────────────────────────────────
    async function _loadWaMetaTemplates(connectorId) {
        const sel = document.getElementById('ocWaTemplate');
        if (!sel) return;
        const wrap = document.getElementById('ocWaVarWrap');
        if (!connectorId) {
            sel.innerHTML = '<option value="">— select connector first —</option>';
            _waMetaTemplates = [];
            if (wrap) wrap.style.display = 'none';
            return;
        }
        sel.innerHTML = '<option value="">— loading… —</option>';
        const r = await apiFetch(`/api/v1/whatsapp-connectors/${connectorId}/meta-templates`);
        if (!r.ok) {
            sel.innerHTML = '<option value="">— error loading templates —</option>';
            _waMetaTemplates = [];
            return;
        }
        _waMetaTemplates = await r.json();
        sel.innerHTML = '<option value="">— none —</option>';
        _waMetaTemplates
            .filter(t => t.status === 'APPROVED')
            .forEach(t => {
                const opt = document.createElement('option');
                opt.value           = t.name;
                opt.textContent     = `${t.name} (${t.language})`;
                opt.dataset.body    = t.body    || '';
                opt.dataset.lang    = t.language || 'en';
                opt.dataset.metaId  = t.id       || '';
                opt.dataset.varsCount = t.variables_count || 0;
                sel.appendChild(opt);
            });
        sel.onchange = () => _onWaMetaTemplateChange(sel.value);
    }
    window.loadWaMetaTemplates = _loadWaMetaTemplates;

    function _onWaMetaTemplateChange(templateName) {
        const wrap = document.getElementById('ocWaVarWrap');
        const rows = document.getElementById('ocWaVarRows');
        if (!templateName) { if (wrap) wrap.style.display = 'none'; return; }
        const tmpl = _waMetaTemplates.find(t => t.name === templateName);
        if (!tmpl || !(tmpl.variables_count > 0)) { if (wrap) wrap.style.display = 'none'; return; }
        if (wrap) wrap.style.display = '';
        rows.innerHTML = '';
        const varRe = /\{\{(\d+)\}\}/g;
        const positions = []; let m;
        while ((m = varRe.exec(tmpl.body || '')) !== null) {
            const n = parseInt(m[1], 10);
            if (!positions.includes(n)) positions.push(n);
        }
        positions.sort((a, b) => a - b);
        positions.forEach(pos => {
            const div = document.createElement('div');
            div.className = 'd-flex align-items-center gap-2 mb-1';
            div.dataset.pos = pos;
            div.innerHTML = `
<span class="fw-bold text-warning" style="width:32px;text-align:center">{{${pos}}}</span>
<span class="text-muted small flex-fill">Variable ${pos}</span>
<input type="text" class="form-control form-control-sm oc-var-override" style="max-width:180px"
    placeholder="Override value…" data-pos="${pos}">`;
            rows.appendChild(div);
        });
    }

    function _onTemplateSelectChange(selectId, channel, templateId) {
        const chanMap = { wa: 'whatsapp', sms: 'sms', email: 'email' };
        // Determine which var section to update based on selectId
        let prefix = '';
        if (selectId === 'ocWaTemplate')    prefix = 'ocWa';
        if (selectId === 'ocSmsTemplate')   prefix = 'ocSms';
        if (selectId === 'ocEmailTemplate') prefix = 'ocEmail';
        if (!prefix) return;

        const wrap = document.getElementById(`${prefix}VarWrap`);
        const rows = document.getElementById(`${prefix}VarRows`);
        if (!templateId) {
            if (wrap) wrap.style.display = 'none';
            return;
        }
        const tmpl = _allTemplates.find(t => t.id === templateId);
        if (!tmpl || !(tmpl.variables || []).length) {
            if (wrap) wrap.style.display = 'none';
            return;
        }
        if (wrap) wrap.style.display = '';
        rows.innerHTML = '';
        (tmpl.variables || []).forEach(v => {
            const div = document.createElement('div');
            div.className = 'd-flex align-items-center gap-2 mb-1';
            div.dataset.pos = v.pos;
            div.innerHTML = `
<span class="fw-bold text-warning" style="width:32px;text-align:center">{{${v.pos}}}</span>
<span class="text-muted small flex-fill">${esc(v.label || `Variable ${v.pos}`)} · <em>${esc(v.contact_field || 'no binding')}</em></span>
<input type="text" class="form-control form-control-sm oc-var-override" style="max-width:180px"
    placeholder="Override value…" data-pos="${v.pos}">`;
            rows.appendChild(div);
        });
    }

    function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : ''; }

    function _readVarOverrides(rowsId) {
        const out = {};
        document.querySelectorAll(`#${rowsId} .oc-var-override`).forEach(inp => {
            if (inp.value.trim()) out[inp.dataset.pos] = inp.value.trim();
        });
        return out;
    }

    function _fillOutboundTab(outbound_config) {
        const cfg = outbound_config || {};

        // Primary channel
        const primary = cfg.primary_channel || 'voice';
        const radio = document.querySelector(`input[name="primaryChannel"][value="${primary}"]`);
        if (radio) radio.checked = true;

        // Fallback channels
        ['voice','whatsapp','sms','email'].forEach(ch => {
            const cb = document.getElementById(`fb${ch.charAt(0).toUpperCase() + ch.slice(1) === 'Whatsapp' ? 'Wa' : ch.charAt(0).toUpperCase() + ch.slice(1)}`);
        });
        // cleaner approach
        const fbMap = { voice: 'fbVoice', whatsapp: 'fbWa', sms: 'fbSms', email: 'fbEmail' };
        Object.entries(fbMap).forEach(([ch, id]) => {
            const cb = document.getElementById(id);
            if (cb) cb.checked = (cfg.fallback_channels || []).includes(ch);
        });

        // Autodial
        const adEl = document.getElementById('cAutodial');
        if (adEl) adEl.checked = !!cfg.autodial;

        // Connector selectors
        _fillConnectorSelect('ocVoiceConnector', ['voice', 'twilio', 'vici']);
        _fillConnectorSelect('ocWaConnector',    ['whatsapp']);
        _fillConnectorSelect('ocSmsConnector',   ['sms', 'bulksms', 'twilio_sms']);
        _fillConnectorSelect('ocEmailConnector', ['email', 'smtp', 'sendgrid']);

        // Template selectors (WA loaded from Meta via connector; SMS & Email from local DB)
        _fillTemplateSelect('ocSmsTemplate',   'sms');
        _fillTemplateSelect('ocEmailTemplate', 'email');

        // Set saved connector values
        if (cfg.voice_connector_id)  { const el = document.getElementById('ocVoiceConnector');  if (el) el.value = cfg.voice_connector_id;  }
        if (cfg.sms_connector_id)    { const el = document.getElementById('ocSmsConnector');     if (el) el.value = cfg.sms_connector_id;    }
        if (cfg.email_connector_id)  { const el = document.getElementById('ocEmailConnector');   if (el) el.value = cfg.email_connector_id;  }

        // WA: load Meta templates from connector then restore saved selection
        (async () => {
            const waConnEl = document.getElementById('ocWaConnector');
            if (waConnEl && cfg.wa_connector_id) {
                waConnEl.value = cfg.wa_connector_id;
                await _loadWaMetaTemplates(cfg.wa_connector_id);
                const waTemplateSel = document.getElementById('ocWaTemplate');
                if (waTemplateSel && cfg.wa_meta_template_name) {
                    waTemplateSel.value = cfg.wa_meta_template_name;
                    _onWaMetaTemplateChange(cfg.wa_meta_template_name);
                }
            } else {
                const waTemplateSel = document.getElementById('ocWaTemplate');
                if (waTemplateSel) waTemplateSel.innerHTML = '<option value="">— select connector first —</option>';
            }
        })();

        // SMS/Email: set saved template + trigger variable mapper
        if (cfg.sms_template_id)   { const el = document.getElementById('ocSmsTemplate');   if (el) { el.value = cfg.sms_template_id;   _onTemplateSelectChange('ocSmsTemplate',   'sms',   cfg.sms_template_id); } }
        if (cfg.email_template_id) { const el = document.getElementById('ocEmailTemplate'); if (el) { el.value = cfg.email_template_id; _onTemplateSelectChange('ocEmailTemplate', 'email', cfg.email_template_id); } }
    }

    function _readOutboundTab() {
        const primary = (document.querySelector('input[name="primaryChannel"]:checked') || {}).value || 'voice';
        const fbMap = { voice: 'fbVoice', whatsapp: 'fbWa', sms: 'fbSms', email: 'fbEmail' };
        const fallbacks = Object.entries(fbMap)
            .filter(([, id]) => { const el = document.getElementById(id); return el && el.checked; })
            .map(([ch]) => ch);

        return {
            primary_channel:   primary,
            fallback_channels: fallbacks,
            autodial:          document.getElementById('cAutodial')?.checked || false,
            voice_connector_id:  document.getElementById('ocVoiceConnector')?.value  || null,
            wa_connector_id:          document.getElementById('ocWaConnector')?.value || null,
            wa_meta_template_name:    (() => { const s = document.getElementById('ocWaTemplate'); return s?.value || null; })(),
            wa_meta_template_lang:    (() => { const s = document.getElementById('ocWaTemplate'); return s?.selectedOptions[0]?.dataset.lang || 'en'; })(),
            wa_meta_template_body:    (() => { const s = document.getElementById('ocWaTemplate'); return s?.selectedOptions[0]?.dataset.body || null; })(),
            wa_meta_template_id:      (() => { const s = document.getElementById('ocWaTemplate'); return s?.selectedOptions[0]?.dataset.metaId || null; })(),
            wa_variable_map:          _readVarOverrides('ocWaVarRows'),
            sms_connector_id:    document.getElementById('ocSmsConnector')?.value     || null,
            sms_template_id:     document.getElementById('ocSmsTemplate')?.value      || null,
            sms_variable_map:    _readVarOverrides('ocSmsVarRows'),
            email_connector_id:  document.getElementById('ocEmailConnector')?.value   || null,
            email_template_id:   document.getElementById('ocEmailTemplate')?.value    || null,
            email_variable_map:  _readVarOverrides('ocEmailVarRows'),
        };
    }

    // ─── Boot ──────────────────────────────────────────────────────────────────
    _guard();    loadAllOutcomes();    loadAllQueues();    loadAllUsers();    loadAllGroups();    loadCampaigns();
    loadAllConnectors();    loadAllTemplates();

    (async () => {
        const r = await apiFetch('/api/v1/users/me').catch(() => null);
        if (r && r.ok) {
            const u = await r.json();
            const el = document.getElementById('currentUser');
            if (el) el.textContent = u.full_name || u.username || 'Agent';
        }
    })();
})();

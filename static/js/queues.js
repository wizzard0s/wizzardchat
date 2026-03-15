/**
 * WizzardChat \u2013 Queues management page
 */
(function () {
    'use strict';

    const API = '';
    const _token = () => localStorage.getItem('wizzardchat_token');
    const _headers = () => ({ 'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    let _queues = [];
    let _editId = null;
    let _deleteId = null;
    let _allOutcomes = [];

    const modal   = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('queueModal'));
    const delModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteQModal'));

    // \u2500\u2500\u2500 Auth guard \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    function _guard() {
        if (!_token()) { window.location.href = '/login'; }
    }

    // \u2500\u2500\u2500 Helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/login'; }
        return r;
    }

    function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    function _strategyLabel(s) {
        return { round_robin: 'Round Robin', least_busy: 'Least Busy', skills_based: 'Skills Based',
                 priority: 'Priority', random: 'Random' }[s] ?? s;
    }

    // \u2500\u2500\u2500 Global outcomes \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    async function loadAllOutcomes() {
        const r = await apiFetch('/api/v1/outcomes?active_only=true');
        _allOutcomes = r.ok ? await r.json() : [];
    }

    function _fillDisconnectOutcomeSelect(selectedId) {
        const sel = document.getElementById('qDisconnectOutcome');
        if (!sel) return;
        sel.innerHTML = '<option value="">&#8212; None / just close &#8212;</option>';
        const actionLabel = { end_interaction: 'End', flow_redirect: 'Redirect' };
        _allOutcomes.forEach(o => {
            const opt = document.createElement('option');
            opt.value = o.id;
            const tag = actionLabel[o.action_type] || o.action_type || 'End';
            opt.textContent = `${o.label} [${tag}]`;
            if (String(o.id) === String(selectedId)) opt.selected = true;
            sel.appendChild(opt);
        });
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
    <input class="form-check-input" type="checkbox" value="${o.id}" id="oc_${o.id}" ${checked}>
    <label class="form-check-label d-flex align-items-center gap-2" for="oc_${o.id}">
        <span class="fw-semibold">${esc(o.label)}</span>
        <span class="badge bg-${badge} text-uppercase" style="font-size:.65rem">${esc(o.outcome_type)}</span>
        <code class="text-muted" style="font-size:.75rem">${esc(o.code)}</code>
    </label>
</div>`;
            list.appendChild(col);
        });
    }

    // \u2500\u2500\u2500 Load / Render \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    async function loadQueues() {
        const r = await apiFetch('/api/v1/queues');
        _queues = r.ok ? await r.json() : [];
        renderQueues();
    }

    function renderQueues() {
        const grid  = document.getElementById('queueGrid');
        const empty = document.getElementById('queueEmpty');
        grid.querySelectorAll('.queue-col').forEach(el => el.remove());

        if (!_queues.length) {
            empty.style.display = 'flex';
            return;
        }
        empty.style.display = 'none';

        _queues.forEach(q => {
            const col = document.createElement('div');
            col.className = 'col-md-4 col-lg-3 queue-col';
            const statusBadge = q.is_active
                ? '<span class="badge bg-success">Active</span>'
                : '<span class="badge bg-secondary">Inactive</span>';
            const outcomeCount = (q.outcomes || []).length;
            col.innerHTML = `
<div class="card queue-card h-100" onclick="openQueueModal('${q.id}')">
    <div class="card-body">
        <div class="d-flex align-items-center gap-2 mb-2">
            <span class="queue-color-dot" style="background:${esc(q.color || '#fd7e14')}"></span>
            <span class="fw-semibold text-truncate">${esc(q.name)}</span>
            ${statusBadge}
        </div>
        <p class="text-muted small mb-2">${esc(q.description || '\u2014')}</p>
        <div class="small">
            <span class="badge bg-secondary me-1">${esc(q.channel)}</span>
            <span class="badge bg-dark border me-1">${_strategyLabel(q.strategy)}</span>
            <span class="text-muted">Pri: ${q.priority}</span>
        </div>
    </div>
    <div class="card-footer d-flex justify-content-between align-items-center py-1 px-2">
        <small class="text-muted"><i class="bi bi-flag me-1"></i>${outcomeCount} outcome${outcomeCount !== 1 ? 's' : ''}</small>
        <button class="btn btn-sm btn-link text-danger p-0" onclick="event.stopPropagation();deleteQueue('${q.id}','${esc(q.name)}')">
            <i class="bi bi-trash"></i>
        </button>
    </div>
</div>`;
            grid.appendChild(col);
        });
    }

    // \u2500\u2500\u2500 Modal open \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    window.openQueueModal = function (id) {
        _editId = id || null;
        const title = document.getElementById('queueModalTitle');

        if (_editId) {
            const q = _queues.find(x => x.id === _editId);
            if (!q) return;
            title.innerHTML = `<i class="bi bi-people me-2"></i>Edit Queue`;
            _fillForm(q);
        } else {
            title.innerHTML = `<i class="bi bi-people me-2"></i>New Queue`;
            _resetForm();
        }

        // Activate first tab
        const firstTab = document.querySelector('#queueTabs .nav-link');
        if (firstTab) bootstrap.Tab.getOrCreateInstance(firstTab).show();

        modal().show();
    };

    function _resetForm() {
        document.getElementById('qName').value = '';
        document.getElementById('qChannel').value = 'chat';
        document.getElementById('qDescription').value = '';
        document.getElementById('qColor').value = '#fd7e14';
        document.getElementById('qIsActive').checked = true;
        document.getElementById('qStrategy').value = 'round_robin';
        document.getElementById('qPriority').value = 0;
        document.getElementById('qMaxWait').value = 300;
        document.getElementById('qSla').value = 30;
        document.getElementById('qDisconnectTimeout').value = '';
        _fillDisconnectOutcomeSelect(null);
        _renderOutcomeCheckboxes('qOutcomeList', 'qOutcomeEmpty', []);
        _fillWebformSlots('q', []);
        const ovr = document.getElementById('qOverrideCampaign');
        if (ovr) ovr.checked = false;
    }

    function _fillForm(q) {
        document.getElementById('qName').value = q.name || '';
        document.getElementById('qChannel').value = q.channel || 'chat';
        document.getElementById('qDescription').value = q.description || '';
        document.getElementById('qColor').value = q.color || '#fd7e14';
        document.getElementById('qIsActive').checked = !!q.is_active;
        document.getElementById('qStrategy').value = q.strategy || 'round_robin';
        document.getElementById('qPriority').value = q.priority ?? 0;
        document.getElementById('qMaxWait').value = q.max_wait_time ?? 300;
        document.getElementById('qSla').value = q.sla_threshold ?? 30;
        document.getElementById('qDisconnectTimeout').value = q.disconnect_timeout_seconds ?? '';
        _fillDisconnectOutcomeSelect(q.disconnect_outcome_id);

        // Outcomes
        _renderOutcomeCheckboxes('qOutcomeList', 'qOutcomeEmpty', q.outcomes || []);
        // Webform URLs
        const intCfg = q.webform_urls || {};
        _fillWebformSlots('q', intCfg.slots || []);
        const ovr = document.getElementById('qOverrideCampaign');
        if (ovr) ovr.checked = !!intCfg.override_campaign;
    }

    // \u2500\u2500\u2500 Outcomes (checkbox selection) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    //  Webform URL slots 
    function _readWebformSlots(prefix) {
        const slots = [];
        for (let i = 1; i <= 5; i++) {
            const name = (document.getElementById(prefix + 'SlotName_' + i)?.value || '').trim();
            const url  = (document.getElementById(prefix + 'SlotUrl_'  + i)?.value || '').trim();
            slots.push({ name, url });
        }
        return slots;
    }

    function _fillWebformSlots(prefix, slots) {
        for (let i = 1; i <= 5; i++) {
            const slot = slots[i - 1] || {};
            const nameEl = document.getElementById(prefix + 'SlotName_' + i);
            const urlEl  = document.getElementById(prefix + 'SlotUrl_'  + i);
            if (nameEl) nameEl.value = slot.name || '';
            if (urlEl)  urlEl.value  = slot.url  || '';
        }
    }

    function _readOutcomes() {
        return Array.from(document.querySelectorAll('#qOutcomeList input[type=checkbox]:checked')).map(el => el.value);
    }

    // \u2500\u2500\u2500 Save \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    window.saveQueue = async function () {
        const name = document.getElementById('qName').value.trim();
        if (!name) { alert('Queue name is required.'); return; }

        const body = {
            name,
            channel:        document.getElementById('qChannel').value,
            description:    document.getElementById('qDescription').value.trim() || null,
            color:          document.getElementById('qColor').value,
            is_active:      document.getElementById('qIsActive').checked,
            strategy:       document.getElementById('qStrategy').value,
            priority:       parseInt(document.getElementById('qPriority').value) || 0,
            max_wait_time:  parseInt(document.getElementById('qMaxWait').value) || 300,
            sla_threshold:  parseInt(document.getElementById('qSla').value) || 30,
            disconnect_timeout_seconds: parseInt(document.getElementById('qDisconnectTimeout').value) || null,
            disconnect_outcome_id: document.getElementById('qDisconnectOutcome').value || null,
            outcomes:       _readOutcomes(),
            webform_urls: {
                slots:             _readWebformSlots('q'),
                override_campaign: !!(document.getElementById('qOverrideCampaign')?.checked),
            },
        };

        const url    = _editId ? `/api/v1/queues/${_editId}` : '/api/v1/queues';
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
        await loadQueues();
    };

    // \u2500\u2500\u2500 Delete \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    window.deleteQueue = function (id, name) {
        _deleteId = id;
        document.getElementById('deleteQName').textContent = name;
        delModal().show();
    };

    window.confirmDeleteQueue = async function () {
        if (!_deleteId) return;
        await apiFetch(`/api/v1/queues/${_deleteId}`, { method: 'DELETE' });
        delModal().hide();
        _deleteId = null;
        await loadQueues();
    };

    // \u2500\u2500\u2500 Logout \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    document.getElementById('btnLogout').addEventListener('click', e => {
        e.preventDefault();
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/login';
    });

    // \u2500\u2500\u2500 Boot \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    _guard();
    loadAllOutcomes().then(() => { _fillDisconnectOutcomeSelect(null); });
    loadQueues();

    // Show username
    (async () => {
        const r = await apiFetch('/api/v1/users/me').catch(() => null);
        if (r && r.ok) {
            const u = await r.json();
            const el = document.getElementById('currentUser');
            if (el) el.textContent = u.full_name || u.username || 'Agent';
        }
    })();
})();

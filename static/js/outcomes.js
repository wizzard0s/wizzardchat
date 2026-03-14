/**
 * WizzardChat – Outcomes management page
 */
(function () {
    'use strict';

    const API = '';
    const _token = () => localStorage.getItem('wizzardchat_token');
    const _headers = () => ({ 'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    let _outcomes = [];
    let _allFlows  = [];
    let _editId = null;
    let _deleteId = null;

    const modal    = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('outcomeModal'));
    const delModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteOModal'));

    function _guard() { if (!_token()) { window.location.href = '/login'; } }

    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/login'; }
        return r;
    }

    function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    const TYPE_LABELS  = { positive: 'Positive', negative: 'Negative', neutral: 'Neutral', escalation: 'Escalation' };
    const TYPE_CLASS   = { positive: 'wz-badge-ok', negative: 'wz-badge-fail', neutral: 'wz-badge-muted', escalation: 'wz-badge-warn' };
    const ACTION_LABELS = { end_interaction: 'End interaction', flow_redirect: 'Redirect to flow' };
    const ACTION_CLASS  = { end_interaction: 'action-badge-end', flow_redirect: 'action-badge-redirect' };

    // ─── Load / Render ──────────────────────────────────────────────────────────
    async function loadFlows() {
        const r = await apiFetch('/api/v1/flows?include_sub_flows=true');
        if (r.ok) {
            const all = await r.json();
            // Include active flows AND published sub-flows (for templates like CSAT)
            _allFlows = (Array.isArray(all) ? all : (all.items || [])).filter(
                f => f.status === 'active' || f.is_published
            );
        }
    }

    function _fillFlowSelect(selectedId) {
        const sel = document.getElementById('oRedirectFlow');
        sel.innerHTML = '<option value="">&#8212; Select a flow &#8212;</option>';
        _allFlows.forEach(f => {
            const o = document.createElement('option');
            o.value = f.id; o.textContent = f.name;
            if (String(f.id) === String(selectedId)) o.selected = true;
            sel.appendChild(o);
        });
    }

    function _updateFlowRowVisibility() {
        const v = document.getElementById('oActionType').value;
        document.getElementById('oRedirectFlowRow').style.display = v === 'flow_redirect' ? '' : 'none';
    }

    // ─── CSAT hint ──────────────────────────────────────────────────────────────
    function _getCSATTemplateFlow() {
        return _allFlows.find(f => f.name === '__template__csat_survey');
    }

    function _updateCsatHint() {
        let banner = document.getElementById('csatHintBanner');
        const isPositive = document.getElementById('oType').value === 'positive';
        const tpl = _getCSATTemplateFlow();

        if (!banner) return;
        if (isPositive && tpl) {
            banner.style.display = '';
        } else {
            banner.style.display = 'none';
        }
    }

    window._applyCsatTemplate = function () {
        const tpl = _getCSATTemplateFlow();
        if (!tpl) return;
        document.getElementById('oActionType').value = 'flow_redirect';
        _updateFlowRowVisibility();
        _fillFlowSelect(tpl.id);
        _updateCsatHint();
    };

    async function loadOutcomes() {
        const r = await apiFetch('/api/v1/outcomes');
        _outcomes = r.ok ? await r.json() : [];
        renderOutcomes();
    }

    function renderOutcomes() {
        const tbody = document.getElementById('outcomeTableBody');
        const empty = document.getElementById('outcomeEmpty');

        // Remove old data rows
        tbody.querySelectorAll('.outcome-data-row').forEach(el => el.remove());

        if (!_outcomes.length) {
            empty.style.display = '';
            return;
        }
        empty.style.display = 'none';

        _outcomes.forEach(o => {
            const tr = document.createElement('tr');
            tr.className = 'outcome-data-row';
            const typeCls = TYPE_CLASS[o.outcome_type] || 'wz-badge-muted';
            const typeLabel = TYPE_LABELS[o.outcome_type] || o.outcome_type;
            tr.innerHTML = `
<td><code class="text-info">${esc(o.code)}</code></td>
<td class="fw-semibold">${esc(o.label)}</td>
<td><span class="wz-badge ${typeCls}">${esc(typeLabel)}</span></td>
<td class="text-muted small">${esc(o.description || '—')}</td>
<td class="text-center">
    ${o.is_active
        ? '<span class="wz-badge wz-badge-ok">Active</span>'
        : '<span class="wz-badge wz-badge-muted">Inactive</span>'}
</td>
<td class="text-center">
    <button class="btn btn-sm btn-outline-secondary me-1" onclick="openOutcomeModal('${o.id}')" title="Edit"><i class="bi bi-pencil"></i></button>
    <button class="btn btn-sm btn-outline-danger" onclick="deleteOutcome('${o.id}','${esc(o.label)}')" title="Delete"><i class="bi bi-trash"></i></button>
</td>`;
            tbody.appendChild(tr);
        });
    }

    // ─── Modal open ─────────────────────────────────────────────────────────────
    window.openOutcomeModal = function (id) {
        _editId = id || null;
        const title = document.getElementById('outcomeModalTitle');

        if (_editId) {
            const o = _outcomes.find(x => x.id === _editId);
            if (!o) return;
            title.innerHTML = `<i class="bi bi-flag me-2"></i>Edit Outcome`;
            document.getElementById('oCode').value        = o.code || '';
            document.getElementById('oLabel').value       = o.label || '';
            document.getElementById('oType').value        = o.outcome_type || 'neutral';
            document.getElementById('oActionType').value  = o.action_type || 'end_interaction';
            document.getElementById('oIsActive').checked  = !!o.is_active;
            document.getElementById('oDescription').value = o.description || '';
            _fillFlowSelect(o.redirect_flow_id);
        } else {
            title.innerHTML = `<i class="bi bi-flag me-2"></i>New Outcome`;
            document.getElementById('oCode').value        = '';
            document.getElementById('oLabel').value       = '';
            document.getElementById('oType').value        = 'neutral';
            document.getElementById('oActionType').value  = 'end_interaction';
            document.getElementById('oIsActive').checked  = true;
            document.getElementById('oDescription').value = '';
            _fillFlowSelect(null);
        }
        _updateFlowRowVisibility();
        _updateCsatHint();
        modal().show();
    };

    // auto-generate code from label
    document.getElementById('oLabel').addEventListener('input', function () {
        if (_editId) return; // don't overwrite when editing
        document.getElementById('oCode').value = this.value
            .toLowerCase().trim()
            .replace(/\s+/g, '_')
            .replace(/[^a-z0-9_]/g, '')
            .substring(0, 50);
    });

    // ─── Save ───────────────────────────────────────────────────────────────────
    window.saveOutcome = async function () {
        const code  = document.getElementById('oCode').value.trim().toLowerCase().replace(/\s+/g, '_');
        const label = document.getElementById('oLabel').value.trim();
        if (!code)  { alert('Code is required.'); return; }
        if (!label) { alert('Label is required.'); return; }

        const body = {
            code,
            label,
            outcome_type:      document.getElementById('oType').value,
            action_type:       document.getElementById('oActionType').value,
            redirect_flow_id:  document.getElementById('oRedirectFlow').value || null,
            is_active:         document.getElementById('oIsActive').checked,
            description:       document.getElementById('oDescription').value.trim() || null,
        };

        const url    = _editId ? `/api/v1/outcomes/${_editId}` : '/api/v1/outcomes';
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
        await loadOutcomes();
    };

    // ─── Delete ─────────────────────────────────────────────────────────────────
    window.deleteOutcome = function (id, label) {
        _deleteId = id;
        document.getElementById('deleteOName').textContent = label;
        delModal().show();
    };

    window.confirmDeleteOutcome = async function () {
        if (!_deleteId) return;
        await apiFetch(`/api/v1/outcomes/${_deleteId}`, { method: 'DELETE' });
        delModal().hide();
        _deleteId = null;
        await loadOutcomes();
    };

    // ─── Logout ─────────────────────────────────────────────────────────────────
    document.getElementById('btnLogout').addEventListener('click', e => {
        e.preventDefault();
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/login';
    });

    // ─── Boot ───────────────────────────────────────────────────────────────────
    _guard();
    document.getElementById('oActionType').addEventListener('change', _updateFlowRowVisibility);
    document.getElementById('oType').addEventListener('change', _updateCsatHint);
    loadFlows().then(_updateCsatHint);
    loadOutcomes();

    (async () => {
        const r = await apiFetch('/api/v1/users/me').catch(() => null);
        if (r && r.ok) {
            const u = await r.json();
            const el = document.getElementById('currentUser');
            if (el) el.textContent = u.full_name || u.username || 'Agent';
        }
    })();
})();

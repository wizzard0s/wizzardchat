/**
 * WizzardChat – Outcomes management page
 */
(function () {
    'use strict';

    const API = '';
    const _token = () => localStorage.getItem('wizzardchat_token');
    const _headers = () => ({ 'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    let _outcomes = [];
    let _editId = null;
    let _deleteId = null;

    const modal    = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('outcomeModal'));
    const delModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteOModal'));

    function _guard() { if (!_token()) { window.location.href = '/'; } }

    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/'; }
        return r;
    }

    function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    const TYPE_LABELS = { positive: 'Positive', negative: 'Negative', neutral: 'Neutral', escalation: 'Escalation' };
    const TYPE_CLASS  = { positive: 'type-badge-positive', negative: 'type-badge-negative', neutral: 'type-badge-neutral', escalation: 'type-badge-escalation' };

    // ─── Load / Render ──────────────────────────────────────────────────────────
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
            const typeCls = TYPE_CLASS[o.outcome_type] || 'type-badge-neutral';
            const typeLabel = TYPE_LABELS[o.outcome_type] || o.outcome_type;
            tr.innerHTML = `
<td><code class="text-info">${esc(o.code)}</code></td>
<td class="fw-semibold">${esc(o.label)}</td>
<td><span class="badge ${typeCls}">${esc(typeLabel)}</span></td>
<td class="text-muted small">${esc(o.description || '—')}</td>
<td class="text-center">
    ${o.is_active
        ? '<span class="badge bg-success">Active</span>'
        : '<span class="badge bg-secondary">Inactive</span>'}
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
            document.getElementById('oIsActive').checked  = !!o.is_active;
            document.getElementById('oDescription').value = o.description || '';
        } else {
            title.innerHTML = `<i class="bi bi-flag me-2"></i>New Outcome`;
            document.getElementById('oCode').value        = '';
            document.getElementById('oLabel').value       = '';
            document.getElementById('oType').value        = 'neutral';
            document.getElementById('oIsActive').checked  = true;
            document.getElementById('oDescription').value = '';
        }
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
            outcome_type: document.getElementById('oType').value,
            is_active:    document.getElementById('oIsActive').checked,
            description:  document.getElementById('oDescription').value.trim() || null,
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
        window.location.href = '/';
    });

    // ─── Boot ───────────────────────────────────────────────────────────────────
    _guard();
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

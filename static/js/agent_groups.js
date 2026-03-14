/* agent_groups.js — Groups management page */
'use strict';

// ─── Auth ─────────────────────────────────────────────────────────────────────
const _token = () => localStorage.getItem('wizzardchat_token');
async function apiFetch(url, opts = {}) {
    opts.headers = { ...(opts.headers || {}), Authorization: `Bearer ${_token()}`, 'Content-Type': 'application/json' };
    const res = await fetch(url, opts);
    if (res.status === 401) {
        localStorage.removeItem('wizzardchat_token');
        location.href = '/login';
        throw new Error('Unauthorized');
    }
    return res;
}

// ─── State ────────────────────────────────────────────────────────────────────
let _groups   = [];
let _allUsers = [];
let _editId   = null;
let _deleteId = null;

// ─── Shuttle Widget ───────────────────────────────────────────────────────────
// A dual-list pick widget. Shared between groups member management.
const _sh = {};

function shuttleCreate(id, items, selectedIds) {
    _sh[id] = {
        items:    new Map(items.map(i => [i.id, i])),
        selected: new Set((selectedIds || []).map(String)),
    };
    _shuttleRender(id);
}

function shuttleRefresh(id, items, selectedIds) {
    if (!_sh[id]) return;
    _sh[id].items    = new Map(items.map(i => [i.id, i]));
    _sh[id].selected = new Set((selectedIds || []).map(String));
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
    if (sh) sh.textContent = `Members (${sel.length})`;
}

function _fillShuttleList(listId, items, filter) {
    const ul = document.getElementById(listId);
    if (!ul) return;
    const q = filter.toLowerCase();
    ul.innerHTML = '';
    const visible = items.filter(i => !q || i.searchText.toLowerCase().includes(q));
    visible.forEach(i => {
        const btn  = document.createElement('button');
        btn.type   = 'button';
        btn.className = 'list-group-item list-group-item-action py-1 px-2 border-0 shuttle-item';
        btn.dataset.id = i.id;
        btn.innerHTML  = i.html;
        btn.addEventListener('click', () => btn.classList.toggle('active'));
        ul.appendChild(btn);
    });
}

function shuttleMove(id, direction) {
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
}

function shuttleGetSelected(id) {
    return _sh[id] ? [..._sh[id].selected] : [];
}

function _buildShuttleHtml(id) {
    return `
<div class="d-flex flex-column flex-fill" style="min-width:0">
  <div class="small fw-semibold text-muted mb-1" id="${id}_avail_hdr">Available</div>
  <input type="search" class="form-control form-control-sm mb-1" id="${id}_avail_search"
         placeholder="Filter…" oninput="_shuttleRender('${id}')">
  <div class="list-group list-group-flush overflow-auto shuttle-list" id="${id}_avail_list"></div>
</div>
<div class="d-flex flex-column align-items-center justify-content-center gap-1 px-2 flex-shrink-0">
  <button type="button" class="btn btn-sm btn-outline-primary px-2" title="Add all" onclick="shuttleMove('${id}','all_right')">»</button>
  <button type="button" class="btn btn-sm btn-outline-primary px-2" title="Add selected" onclick="shuttleMove('${id}','sel_right')">›</button>
  <button type="button" class="btn btn-sm btn-outline-secondary px-2" title="Remove selected" onclick="shuttleMove('${id}','sel_left')">‹</button>
  <button type="button" class="btn btn-sm btn-outline-secondary px-2" title="Remove all" onclick="shuttleMove('${id}','all_left')">«</button>
</div>
<div class="d-flex flex-column flex-fill" style="min-width:0">
  <div class="small fw-semibold text-muted mb-1" id="${id}_sel_hdr">Members</div>
  <input type="search" class="form-control form-control-sm mb-1" id="${id}_sel_search"
         placeholder="Filter…" oninput="_shuttleRender('${id}')">
  <div class="list-group list-group-flush overflow-auto shuttle-list" id="${id}_sel_list"></div>
</div>`;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function groupModal()  { return bootstrap.Modal.getOrCreateInstance(document.getElementById('groupModal')); }
function deleteModal() { return bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteGroupModal')); }

const roleClass = { super_admin: 'wz-role-super-admin', admin: 'wz-role-admin', supervisor: 'wz-role-supervisor', agent: 'wz-role-agent', viewer: 'wz-role-viewer' };

// ─── Load ─────────────────────────────────────────────────────────────────────
async function loadAll() {
    const [gr, ur] = await Promise.all([
        apiFetch('/api/v1/agent-groups'),
        apiFetch('/api/v1/users'),
    ]);
    _groups   = gr.ok ? await gr.json() : [];
    _allUsers = ur.ok ? (await ur.json()).filter(u => u.is_active !== false) : [];
    renderGroupsTable();
}

// ─── Table Render ─────────────────────────────────────────────────────────────
function renderGroupsTable() {
    const tbody = document.getElementById('groupsBody');
    tbody.innerHTML = '';

    if (!_groups.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-5">No groups yet. <a href="#" onclick="openGroupModal()">Create one</a>.</td></tr>';
    } else {
        _groups.forEach(g => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
<td><span class="color-dot" style="background:${esc(g.color)}"></span></td>
<td class="fw-semibold">${esc(g.name)}</td>
<td class="text-muted small">${esc(g.description || '–')}</td>
<td class="text-center">
  <span class="wz-badge wz-badge-muted">${g.members?.length ?? 0}</span>
</td>
<td class="text-center">
  ${g.is_active
    ? '<span class="wz-badge wz-status-active">Active</span>'
    : '<span class="wz-badge wz-status-inactive">Inactive</span>'}
</td>
<td class="text-end">
  <button class="btn btn-sm btn-outline-info me-1" onclick="openGroupModal('${g.id}')">
    <i class="bi bi-pencil"></i>
  </button>
  <button class="btn btn-sm btn-outline-danger" onclick="deleteGroup('${g.id}','${esc(g.name)}')">
    <i class="bi bi-trash"></i>
  </button>
</td>`;
            tbody.appendChild(tr);
        });
    }

    // Stats
    document.getElementById('statTotal').textContent   = _groups.length;
    document.getElementById('statActive').textContent  = _groups.filter(g => g.is_active).length;
    document.getElementById('statMembers').textContent = _groups.reduce((s, g) => s + (g.members?.length ?? 0), 0);
}

// ─── Open Modal ───────────────────────────────────────────────────────────────
window.openGroupModal = function(id) {
    _editId = id || null;
    document.getElementById('gId').value = id || '';
    document.getElementById('gName').value = '';
    document.getElementById('gDescription').value = '';
    document.getElementById('gColor').value = '#6c757d';
    document.getElementById('gIsActive').checked = true;
    document.getElementById('groupModalTitle').innerHTML =
        `<i class="bi bi-collection me-2"></i>${id ? 'Edit Group' : 'New Group'}`;

    // Build member shuttle in the Members tab
    const wrap = document.getElementById('memberShuttleWrap');
    wrap.innerHTML = _buildShuttleHtml('groupMembers');

    const selectedIds = id
        ? (_groups.find(g => g.id === id)?.members || []).map(m => m.id)
        : [];

    shuttleCreate('groupMembers', _allUsers.map(u => ({
        id:         u.id,
        searchText: (u.full_name || u.username) + ' ' + u.role,
        html: `<span class="fw-semibold">${esc(u.full_name || u.username)}</span>
               <span class="wz-badge ${roleClass[u.role] ?? 'wz-role-viewer'} ms-1" style="font-size:.6rem">${esc(u.role)}</span>`,
    })), selectedIds);

    if (id) {
        const g = _groups.find(g => g.id === id);
        if (g) {
            document.getElementById('gName').value        = g.name;
            document.getElementById('gDescription').value = g.description || '';
            document.getElementById('gColor').value       = g.color || '#6c757d';
            document.getElementById('gIsActive').checked  = g.is_active;
        }
    }

    groupModal().show();
};

// ─── Save ─────────────────────────────────────────────────────────────────────
window.saveGroup = async function() {
    const name = document.getElementById('gName').value.trim();
    if (!name) { alert('Group name is required.'); return; }

    const body = {
        name,
        description: document.getElementById('gDescription').value.trim() || null,
        color:       document.getElementById('gColor').value,
        is_active:   document.getElementById('gIsActive').checked,
    };

    const url    = _editId ? `/api/v1/agent-groups/${_editId}` : '/api/v1/agent-groups';
    const method = _editId ? 'PUT' : 'POST';
    const r      = await apiFetch(url, { method, body: JSON.stringify(body) });
    if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        alert(e.detail || 'Save failed');
        return;
    }
    const saved = await r.json();

    // Update members via set_members endpoint
    const memberIds = shuttleGetSelected('groupMembers');
    await apiFetch(`/api/v1/agent-groups/${saved.id}/members`, {
        method: 'PUT',
        body:   JSON.stringify(memberIds),
    });

    groupModal().hide();
    await loadAll();
};

// ─── Delete ───────────────────────────────────────────────────────────────────
window.deleteGroup = function(id, name) {
    _deleteId = id;
    document.getElementById('deleteGName').textContent = name;
    deleteModal().show();
};

window.confirmDeleteGroup = async function() {
    if (!_deleteId) return;
    await apiFetch(`/api/v1/agent-groups/${_deleteId}`, { method: 'DELETE' });
    deleteModal().hide();
    _deleteId = null;
    await loadAll();
};

// ─── Auth / User ──────────────────────────────────────────────────────────────
(async () => {
    if (!_token()) { location.href = '/login'; return; }
    document.getElementById('btnLogout').addEventListener('click', e => {
        e.preventDefault();
        localStorage.removeItem('wizzardchat_token');
        location.href = '/login';
    });
    await loadAll();
})();

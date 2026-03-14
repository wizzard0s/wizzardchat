/**
 * WizzardChat \u2013 Users management page
 */
(function () {
    'use strict';

    const API = '';
    const _token  = () => localStorage.getItem('wizzardchat_token');
    const _headers = () => ({ 'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    let _users            = [];
    let _editId           = null;
    let _deleteId         = null;
    let _allCampaigns     = [];
    let _globalCapDefs    = {};   // default_omni_max, default_channel_max_*, etc.

    const modal    = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('userModal'));
    const delModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteUModal'));

    function _guard() { if (!_token()) window.location.href = '/login'; }

    async function apiFetch(path, opts = {}) {
        const r = await fetch(API + path, { headers: _headers(), ...opts });
        if (r.status === 401) { localStorage.removeItem('wizzardchat_token'); window.location.href = '/login'; }
        return r;
    }

    function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

    const ROLE_COLOR = { super_admin: 'danger', admin: 'warning', supervisor: 'info', agent: 'primary', viewer: 'secondary' };
    const ROLE_LABEL = { super_admin: 'Super Admin', admin: 'Admin', supervisor: 'Supervisor', agent: 'Agent', viewer: 'viewer' };

    function _roleBadge(role) {
        const cls = ROLE_COLOR[role] ?? 'secondary';
        const lbl = ROLE_LABEL[role] ?? role;
        return `<span class="badge bg-${cls}">${lbl}</span>`;
    }

    function _initials(u) {
        const name = u.full_name || u.username || '?';
        return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
    }

    const AVATAR_COLORS = ['#0d6efd','#6610f2','#6f42c1','#d63384','#dc3545','#fd7e14','#ffc107','#198754','#20c997','#0dcaf0'];
    function _avatarColor(id) {
        let n = 0;
        for (const c of String(id)) n += c.charCodeAt(0);
        return AVATAR_COLORS[n % AVATAR_COLORS.length];
    }

    // \u2500\u2500\u2500 Global capacity defaults \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    async function loadGlobalCapacityDefaults() {
        const r = await apiFetch('/api/v1/settings');
        if (!r.ok) return;
        const settings = await r.json();   // [{key, value}, \u2026]
        const CAP_KEYS = [
            'default_omni_max',
            'default_channel_max_voice',
            'default_channel_max_chat',
            'default_channel_max_whatsapp',
            'default_channel_max_email',
            'default_channel_max_sms',
        ];
        for (const s of settings) {
            if (CAP_KEYS.includes(s.key)) _globalCapDefs[s.key] = s.value;
        }
        _applyCapacityPlaceholders();
    }

    function _applyCapacityPlaceholders() {
        const MAP = [
            ['uLimOmni',  'default_omni_max'],
            ['uLimVoice', 'default_channel_max_voice'],
            ['uLimChat',  'default_channel_max_chat'],
            ['uLimWa',    'default_channel_max_whatsapp'],
            ['uLimEmail', 'default_channel_max_email'],
            ['uLimSms',   'default_channel_max_sms'],
        ];
        for (const [id, key] of MAP) {
            const el = document.getElementById(id);
            if (el) el.placeholder = _globalCapDefs[key] ?? '\u2013';
        }
    }

    // \u2500\u2500\u2500 Load / Render \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    async function loadUsers() {
        const r = await apiFetch('/api/v1/users');
        _users = r.ok ? await r.json() : [];
        renderUsers();
    }

    function renderUsers() {
        const grid  = document.getElementById('userGrid');
        const empty = document.getElementById('userEmpty');
        grid.querySelectorAll('.user-col').forEach(el => el.remove());

        if (!_users.length) { empty.style.display = 'block'; return; }
        empty.style.display = 'none';

        _users.forEach(u => {
            const col = document.createElement('div');
            col.className = 'col-md-4 col-lg-3 user-col';
            const online = u.is_online
                ? '<span class="online-dot bg-success ms-1" title="Online"></span>'
                : '<span class="online-dot bg-secondary ms-1" title="Offline"></span>';
            const activeBadge = u.is_active
                ? '' : '<span class="badge bg-secondary ms-1">Inactive</span>';
            col.innerHTML = `
<div class="card user-card h-100" onclick="openUserModal('${u.id}')">
    <div class="card-body">
        <div class="d-flex align-items-center gap-3 mb-2">
            <div class="user-avatar text-white" style="background:${_avatarColor(u.id)}">${esc(_initials(u))}</div>
            <div class="overflow-hidden">
                <div class="fw-semibold text-truncate d-flex align-items-center gap-1">
                    ${esc(u.full_name || u.username)}${online}${activeBadge}
                </div>
                <div class="text-muted small text-truncate">@${esc(u.username)}</div>
            </div>
        </div>
        <div class="small text-muted text-truncate mb-1"><i class="bi bi-envelope me-1"></i>${esc(u.email)}</div>
        ${u.phone_number ? `<div class="small text-muted text-truncate"><i class="bi bi-telephone me-1"></i>${esc(u.phone_number)}</div>` : ''}
    </div>
    <div class="card-footer d-flex justify-content-between align-items-center py-1 px-2">
        ${_roleBadge(u.role)}
        <button class="btn btn-sm btn-link text-danger p-0" onclick="event.stopPropagation();deleteUser('${u.id}','${esc(u.full_name || u.username)}')">
            <i class="bi bi-trash"></i>
        </button>
    </div>
</div>`;
            grid.appendChild(col);
        });
    }

    // \u2500\u2500\u2500 Load campaigns for checkboxes \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    async function loadAllCampaigns() {
        const r = await apiFetch('/api/v1/campaigns');
        _allCampaigns = r.ok ? await r.json() : [];
    }

    async function loadUserCampaignAssignments(userId) {
        const loading = document.getElementById('uCampaignLoading');
        const list    = document.getElementById('uCampaignList');
        const empty   = document.getElementById('uCampaignEmpty');

        loading.style.display = 'block';
        list.innerHTML = '';
        empty.style.display = 'none';

        let assignedIds = [];
        if (userId) {
            const r = await apiFetch(`/api/v1/users/${userId}/campaigns`);
            if (r.ok) {
                const campaigns = await r.json();
                assignedIds = campaigns.map(c => c.id);
            }
        }

        loading.style.display = 'none';
        _renderCampaignCheckboxes(assignedIds);
    }

    function _renderCampaignCheckboxes(selectedIds) {
        const list  = document.getElementById('uCampaignList');
        const empty = document.getElementById('uCampaignEmpty');
        list.innerHTML = '';

        const activeCampaigns = _allCampaigns.filter(c => c.is_active !== false);
        if (!activeCampaigns.length) {
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';

        const statusBadge = { running: 'success', draft: 'secondary', paused: 'warning', completed: 'primary', cancelled: 'danger' };
        activeCampaigns.forEach(c => {
            const checked = selectedIds.includes(c.id) ? 'checked' : '';
            const badge   = statusBadge[c.status] ?? 'secondary';
            const col     = document.createElement('div');
            col.className = 'col-md-6';
            col.innerHTML = `
<div class="form-check border border-secondary rounded p-2 ms-0">
    <input class="form-check-input" type="checkbox" value="${c.id}" id="uc_${c.id}" ${checked}>
    <label class="form-check-label d-flex align-items-center gap-2" for="uc_${c.id}">
        <span class="camp-color-dot rounded-circle d-inline-block" style="background:${esc(c.color||'#0d6efd')};width:10px;height:10px;flex-shrink:0"></span>
        <span class="fw-semibold text-truncate">${esc(c.name)}</span>
        <span class="badge bg-${badge}" style="font-size:.65rem">${esc(c.status)}</span>
    </label>
</div>`;
            list.appendChild(col);
        });
    }

    function _readCampaignSelections() {
        return Array.from(document.querySelectorAll('#uCampaignList input[type=checkbox]:checked')).map(el => el.value);
    }

    // \u2500\u2500\u2500 Modal open \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    window.openUserModal = function (id) {
        _editId = id || null;
        const title  = document.getElementById('userModalTitle');
        const pwNote = document.getElementById('uPasswordNote');

        if (_editId) {
            const u = _users.find(x => x.id === _editId);
            if (!u) return;
            title.innerHTML = `<i class="bi bi-person me-2"></i>Edit User`;
            pwNote.textContent = '(leave blank to keep current)';
            _fillForm(u);
            // Load campaign checkboxes for this user
            loadUserCampaignAssignments(_editId);
            // Load per-agent capacity (fills fields with custom values or leaves blank for global defaults)
            loadAgentCapacity(_editId);
        } else {
            title.innerHTML = `<i class="bi bi-person-plus me-2"></i>New User`;
            pwNote.textContent = '';
            _resetForm();
            // Show empty campaign checkboxes (no assignments yet)
            _renderCampaignCheckboxes([]);
            document.getElementById('uCampaignLoading').style.display = 'none';
            // New user: clear capacity fields (will use global defaults)
            _clearCapacityFields();
        }

        bootstrap.Tab.getOrCreateInstance(document.querySelector('#userTabs .nav-link')).show();
        modal().show();
    };

    function _resetForm() {
        document.getElementById('uFullName').value     = '';
        document.getElementById('uUsername').value     = '';
        document.getElementById('uEmail').value        = '';
        document.getElementById('uPhone').value        = '';
        document.getElementById('uRole').value         = 'agent';
        document.getElementById('uPassword').value     = '';
        document.getElementById('uIsActive').checked   = true;
        _setLanguages([]);
    }

    function _fillForm(u) {
        document.getElementById('uFullName').value     = u.full_name || '';
        document.getElementById('uUsername').value     = u.username || '';
        document.getElementById('uEmail').value        = u.email || '';
        document.getElementById('uPhone').value        = u.phone_number || '';
        document.getElementById('uRole').value         = u.role || 'agent';
        document.getElementById('uPassword').value     = '';
        document.getElementById('uIsActive').checked   = !!u.is_active;
        _setLanguages(u.languages || []);
    }

    async function loadAgentCapacity(userId) {
        const r = await apiFetch(`/api/v1/agents/${userId}/capacity`);
        if (!r.ok) { _clearCapacityFields(); return; }
        const cap = await r.json();
        // Only populate when a custom override is set; leave blank to show global default placeholder
        document.getElementById('uLimOmni').value  = cap.omni_max_is_custom             ? cap.omni_max             : '';
        document.getElementById('uLimVoice').value = cap.channel_max_voice_is_custom    ? cap.channel_max_voice    : '';
        document.getElementById('uLimChat').value  = cap.channel_max_chat_is_custom     ? cap.channel_max_chat     : '';
        document.getElementById('uLimWa').value    = cap.channel_max_whatsapp_is_custom ? cap.channel_max_whatsapp : '';
        document.getElementById('uLimEmail').value = cap.channel_max_email_is_custom    ? cap.channel_max_email    : '';
        document.getElementById('uLimSms').value   = cap.channel_max_sms_is_custom      ? cap.channel_max_sms      : '';
        _applyCapacityPlaceholders();
    }

    function _clearCapacityFields() {
        ['uLimOmni','uLimVoice','uLimChat','uLimWa','uLimEmail','uLimSms']
            .forEach(id => { document.getElementById(id).value = ''; });
        _applyCapacityPlaceholders();
    }

    window.resetCapacityToDefaults = function () { _clearCapacityFields(); };

    function _readCapacity() {
        function _parseOpt(id) {
            const v = document.getElementById(id).value.trim();
            return v === '' ? null : parseInt(v, 10);
        }
        return {
            omni_max:             _parseOpt('uLimOmni'),
            channel_max_voice:    _parseOpt('uLimVoice'),
            channel_max_chat:     _parseOpt('uLimChat'),
            channel_max_whatsapp: _parseOpt('uLimWa'),
            channel_max_email:    _parseOpt('uLimEmail'),
            channel_max_sms:      _parseOpt('uLimSms'),
        };
    }

    function _setLanguages(langs) {
        document.querySelectorAll('#uLanguageChips input[type=checkbox]').forEach(cb => {
            cb.checked = langs.includes(cb.value);
        });
    }

    function _readLanguages() {
        return Array.from(
            document.querySelectorAll('#uLanguageChips input[type=checkbox]:checked')
        ).map(cb => cb.value);
    }

    // \u2500\u2500\u2500 Save \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    window.saveUser = async function () {
        const fullName = document.getElementById('uFullName').value.trim();
        const username = document.getElementById('uUsername').value.trim();
        const email    = document.getElementById('uEmail').value.trim();
        const password = document.getElementById('uPassword').value;

        if (!fullName || !username || !email) {
            alert('Full name, username, and email are required.');
            return;
        }
        if (!_editId && !password) {
            alert('Password is required for new users.');
            return;
        }

        let savedUserId = _editId;

        if (_editId) {
            // PATCH existing user
            const patchBody = {
                full_name:            fullName,
                email,
                phone_number:         document.getElementById('uPhone').value.trim() || null,
                role:                 document.getElementById('uRole').value,
                is_active:            document.getElementById('uIsActive').checked,
                languages:            _readLanguages(),
            };
            if (password) patchBody.password = password;

            const r = await apiFetch(`/api/v1/users/${_editId}`, {
                method: 'PATCH',
                body: JSON.stringify(patchBody),
            });
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                alert(e.detail || 'Failed to update user.');
                return;
            }
        } else {
            // POST new user via auth/register
            const createBody = {
                full_name:            fullName,
                username,
                email,
                password,
                phone_number:         document.getElementById('uPhone').value.trim() || null,
                role:                 document.getElementById('uRole').value,
                auth_type:            'local',
                languages:            _readLanguages(),
            };
            const r = await apiFetch('/api/v1/auth/register', {
                method: 'POST',
                body: JSON.stringify(createBody),
            });
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                alert(e.detail || 'Failed to create user.');
                return;
            }
            const newUser = await r.json();
            savedUserId = newUser.id;
        }

        // Save campaign assignments
        const campaignIds = _readCampaignSelections();
        if (savedUserId) {
            const ra = await apiFetch(`/api/v1/users/${savedUserId}/campaigns`, {
                method: 'PUT',
                body: JSON.stringify({ campaign_ids: campaignIds }),
            });
            if (!ra.ok) {
                const e = await ra.json().catch(() => ({}));
                console.warn('Campaign assignment failed:', e.detail);
            }
        }

        // Save capacity overrides (null values reset to global default)
        if (savedUserId) {
            const rl = await apiFetch(`/api/v1/agents/${savedUserId}/limits`, {
                method: 'PATCH',
                body: JSON.stringify(_readCapacity()),
            });
            if (!rl.ok) {
                const e = await rl.json().catch(() => ({}));
                console.warn('Capacity save failed:', e.detail);
            }
        }

        modal().hide();
        await loadUsers();
    };

    // \u2500\u2500\u2500 Delete \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    window.deleteUser = function (id, name) {
        _deleteId = id;
        document.getElementById('deleteUName').textContent = name;
        delModal().show();
    };

    window.confirmDeleteUser = async function () {
        if (!_deleteId) return;
        await apiFetch(`/api/v1/users/${_deleteId}`, { method: 'DELETE' });
        delModal().hide();
        _deleteId = null;
        await loadUsers();
    };

    // \u2500\u2500\u2500 Logout \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    document.getElementById('btnLogout').addEventListener('click', e => {
        e.preventDefault();
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/login';
    });

    // \u2500\u2500\u2500 Boot \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    _guard();
    loadAllCampaigns();
    loadGlobalCapacityDefaults();
    loadUsers();

    (async () => {
        const r = await apiFetch('/api/v1/users/me').catch(() => null);
        if (r && r.ok) {
            const u = await r.json();
            const el = document.getElementById('currentUser');
            if (el) el.textContent = u.full_name || u.username || 'Agent';
        }
    })();
})();

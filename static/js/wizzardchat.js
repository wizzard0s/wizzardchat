/* WizzardChat – Main dashboard JS */
(function () {
    const API = '';
    let token = localStorage.getItem('wizzardchat_token');
    let currentUserData = null;

    // ──── Auth ────
    async function apiFetch(url, opts = {}) {
        opts.headers = opts.headers || {};
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;
        if (opts.body && typeof opts.body === 'object') {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(opts.body);
        }
        const res = await fetch(API + url, opts);
        if (res.status === 401) {
            token = null;
            localStorage.removeItem('wizzardchat_token');
            showLogin();
            throw new Error('Unauthorized');
        }
        return res;
    }

    function showLogin() {
        new bootstrap.Modal(document.getElementById('loginModal')).show();
    }

    function isAdmin() {
        return currentUserData && (currentUserData.role === 'super_admin' || currentUserData.role === 'admin');
    }

    document.getElementById('loginForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errEl = document.getElementById('loginError');
        errEl.style.display = 'none';
        const form = new URLSearchParams();
        form.append('username', document.getElementById('loginUser').value);
        form.append('password', document.getElementById('loginPass').value);
        try {
            const res = await fetch(API + '/api/v1/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: form
            });
            if (!res.ok) {
                errEl.textContent = 'Invalid credentials';
                errEl.style.display = 'block';
                return;
            }
            const data = await res.json();
            token = data.access_token;
            currentUserData = data.user;
            localStorage.setItem('wizzardchat_token', token);
            document.getElementById('currentUser').textContent = data.user.full_name;
            bootstrap.Modal.getInstance(document.getElementById('loginModal'))?.hide();
            updateSettingsVisibility();
            loadDashboard();
        } catch (err) {
            errEl.textContent = err.message;
            errEl.style.display = 'block';
        }
    });

    document.getElementById('btnLogout')?.addEventListener('click', () => {
        token = null;
        currentUserData = null;
        localStorage.removeItem('wizzardchat_token');
        showLogin();
    });

    function updateSettingsVisibility() {
        const settingsLink = document.querySelector('[data-section="settings"]');
        if (settingsLink) {
            settingsLink.parentElement.style.display = isAdmin() ? '' : 'none';
        }
    }

    // ──── Section navigation ────
    document.querySelectorAll('[data-section]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('#sidebar .nav-link').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            const section = link.dataset.section;
            if (section === 'users') loadUsersSection();
            else if (section === 'settings') loadSettingsSection();
            else if (section === 'flows') loadFlowsSection();
        });
    });

    // ──── Flows Section ────
    let flowFilters = { name: '', status: '', flow_type: '' };

    async function loadFlowsSection() {
        const main = document.getElementById('mainContent');
        main.innerHTML = '<h4 class="mb-4"><i class="bi bi-diagram-3 me-2"></i>Flows</h4><p class="text-muted">Loading...</p>';
        try {
            const params = new URLSearchParams();
            if (flowFilters.name) params.set('name', flowFilters.name);
            if (flowFilters.status) params.set('status', flowFilters.status);
            if (flowFilters.flow_type) params.set('flow_type', flowFilters.flow_type);
            const qs = params.toString() ? '?' + params.toString() : '';
            const res = await apiFetch('/api/v1/flows' + qs);
            if (!res.ok) throw new Error('Failed to load flows');
            const flows = await res.json();
            renderFlowsTable(flows);
        } catch (err) {
            main.innerHTML = '<h4 class="mb-4"><i class="bi bi-diagram-3 me-2"></i>Flows</h4><div class="alert alert-danger">' + err.message + '</div>';
        }
    }

    function renderFlowsTable(flows) {
        const main = document.getElementById('mainContent');
        const statusBadge = (s) => {
            const map = { draft: 'secondary', active: 'success', inactive: 'warning', archived: 'dark' };
            return `<span class="badge bg-${map[s] || 'secondary'}">${(s || 'draft').replace('_', ' ')}</span>`;
        };
        const typeBadge = (t) => {
            const map = { main_flow: 'primary', sub_flow: 'info', error_handler: 'danger', scheduled: 'warning' };
            return `<span class="badge bg-${map[t] || 'secondary'}">${(t || 'main_flow').replace(/_/g, ' ')}</span>`;
        };
        const channelBadge = (c) => {
            if (!c) return '<span class="text-muted">—</span>';
            const map = { voice: 'success', chat: 'primary', whatsapp: 'success', app: 'info', email: 'warning', sms: 'secondary' };
            return `<span class="badge bg-${map[c] || 'secondary'}">${c}</span>`;
        };
        const rows = flows.map(f => `
            <tr>
                <td><a href="/flow-designer/${f.id}" class="text-decoration-none fw-semibold">${f.name}</a></td>
                <td class="text-muted small">${f.description || '—'}</td>
                <td>${typeBadge(f.flow_type)}</td>
                <td>${statusBadge(f.status)}</td>
                <td>${channelBadge(f.channel)}</td>
                <td>v${f.version}</td>
                <td class="text-muted small">${new Date(f.updated_at).toLocaleString()}</td>
                <td class="text-nowrap">
                    <a href="/flow-designer/${f.id}" class="btn btn-sm btn-outline-primary me-1" title="Open Designer"><i class="bi bi-pencil-square"></i></a>
                    <button class="btn btn-sm btn-outline-danger" onclick="window._wc_deleteFlow('${f.id}','${f.name.replace(/'/g, "\\'")}')"><i class="bi bi-trash"></i></button>
                </td>
            </tr>
        `).join('');
        const emptyMsg = flows.length === 0
            ? '<tr><td colspan="8" class="text-center text-muted py-4">No flows found — click <strong>New Flow</strong> to create one.</td></tr>'
            : rows;
        main.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0"><i class="bi bi-diagram-3 me-2"></i>Flows</h4>
                <button class="btn btn-primary btn-sm" id="btnNewFlow"><i class="bi bi-plus-lg me-1"></i>New Flow</button>
            </div>

            <!-- Filters -->
            <div class="card mb-3">
                <div class="card-body py-2">
                    <div class="row g-2 align-items-end">
                        <div class="col-md-4">
                            <label class="form-label small mb-1">Search by name</label>
                            <input type="text" class="form-control form-control-sm" id="flowFilterName" placeholder="Flow name..." value="${flowFilters.name}">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label small mb-1">Status</label>
                            <select class="form-select form-select-sm" id="flowFilterStatus">
                                <option value="">All Statuses</option>
                                <option value="draft" ${flowFilters.status==='draft'?'selected':''}>Draft</option>
                                <option value="active" ${flowFilters.status==='active'?'selected':''}>Active</option>
                                <option value="inactive" ${flowFilters.status==='inactive'?'selected':''}>Inactive</option>
                                <option value="archived" ${flowFilters.status==='archived'?'selected':''}>Archived</option>
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label small mb-1">Type</label>
                            <select class="form-select form-select-sm" id="flowFilterType">
                                <option value="">All Types</option>
                                <option value="main_flow" ${flowFilters.flow_type==='main_flow'?'selected':''}>Main Flow</option>
                                <option value="sub_flow" ${flowFilters.flow_type==='sub_flow'?'selected':''}>Sub Flow</option>
                                <option value="error_handler" ${flowFilters.flow_type==='error_handler'?'selected':''}>Error Handler</option>
                                <option value="scheduled" ${flowFilters.flow_type==='scheduled'?'selected':''}>Scheduled</option>
                            </select>
                        </div>
                        <div class="col-md-2">
                            <button class="btn btn-sm btn-outline-secondary w-100" id="btnFlowFilter"><i class="bi bi-search me-1"></i>Filter</button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead><tr><th>Name</th><th>Description</th><th>Type</th><th>Status</th><th>Channel</th><th>Version</th><th>Updated</th><th></th></tr></thead>
                        <tbody>${emptyMsg}</tbody>
                    </table>
                </div>
            </div>
        `;

        // Filter events
        document.getElementById('btnFlowFilter')?.addEventListener('click', () => {
            flowFilters.name = document.getElementById('flowFilterName').value.trim();
            flowFilters.status = document.getElementById('flowFilterStatus').value;
            flowFilters.flow_type = document.getElementById('flowFilterType').value;
            loadFlowsSection();
        });
        document.getElementById('flowFilterName')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); document.getElementById('btnFlowFilter').click(); }
        });

        // New flow
        document.getElementById('btnNewFlow')?.addEventListener('click', () => showNewFlowModal());
    }

    // ── New Flow modal ──
    function showNewFlowModal() {
        let modal = document.getElementById('newFlowModal');
        if (!modal) {
            const div = document.createElement('div');
            div.innerHTML = `
            <div class="modal fade" id="newFlowModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header"><h5 class="modal-title"><i class="bi bi-plus-circle me-2"></i>New Flow</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                        <div class="modal-body">
                            <form id="newFlowForm">
                                <div class="mb-3"><label class="form-label">Name</label><input type="text" class="form-control" id="nfName" required></div>
                                <div class="mb-3"><label class="form-label">Description</label><textarea class="form-control" id="nfDesc" rows="2"></textarea></div>
                                <div class="mb-3"><label class="form-label">Type</label>
                                    <select class="form-select" id="nfType">
                                        <option value="main_flow" selected>Main Flow</option>
                                        <option value="sub_flow">Sub Flow</option>
                                        <option value="error_handler">Error Handler</option>
                                        <option value="scheduled">Scheduled</option>
                                    </select>
                                </div>
                                <div class="mb-3"><label class="form-label">Channel</label>
                                    <select class="form-select" id="nfChannel">
                                        <option value="">Any</option>
                                        <option value="voice">Voice</option>
                                        <option value="chat">Chat</option>
                                        <option value="whatsapp">WhatsApp</option>
                                        <option value="app">App</option>
                                        <option value="email">Email</option>
                                        <option value="sms">SMS</option>
                                    </select>
                                </div>
                                <div id="nfError" class="text-danger small mb-2" style="display:none;"></div>
                                <button type="submit" class="btn btn-primary w-100"><i class="bi bi-plus-lg me-1"></i>Create Flow</button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>`;
            document.body.appendChild(div.firstElementChild);
            modal = document.getElementById('newFlowModal');
            document.getElementById('newFlowForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const errEl = document.getElementById('nfError');
                errEl.style.display = 'none';
                const payload = {
                    name: document.getElementById('nfName').value.trim(),
                    description: document.getElementById('nfDesc').value.trim() || null,
                    flow_type: document.getElementById('nfType').value,
                    channel: document.getElementById('nfChannel').value || null,
                };
                try {
                    const res = await apiFetch('/api/v1/flows', { method: 'POST', body: payload });
                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || 'Failed to create flow');
                    }
                    const flow = await res.json();
                    bootstrap.Modal.getInstance(modal)?.hide();
                    // Navigate to designer with the new flow
                    window.location.href = '/flow-designer/' + flow.id;
                } catch (err) {
                    errEl.textContent = err.message;
                    errEl.style.display = 'block';
                }
            });
        }
        document.getElementById('newFlowForm')?.reset();
        document.getElementById('nfError').style.display = 'none';
        new bootstrap.Modal(modal).show();
    }

    // ── Delete flow ──
    window._wc_deleteFlow = async function (id, name) {
        if (!confirm('Delete flow "' + name + '"? This cannot be undone.')) return;
        try {
            const res = await apiFetch('/api/v1/flows/' + id, { method: 'DELETE' });
            if (!res.ok && res.status !== 204) {
                const data = await res.json().catch(() => ({}));
                alert(data.detail || 'Failed to delete');
                return;
            }
            loadFlowsSection();
        } catch (err) {
            alert(err.message);
        }
    };

    // ──── Users Section ────
    async function loadUsersSection() {
        const main = document.getElementById('mainContent');
        main.innerHTML = '<h4 class="mb-4"><i class="bi bi-shield-lock me-2"></i>Users</h4><p class="text-muted">Loading...</p>';
        try {
            const res = await apiFetch('/api/v1/users');
            if (!res.ok) throw new Error('Failed to load users');
            const users = await res.json();

            // Always render the table (even if empty – it shows "Add User" button)
            renderUsersTable(users);
        } catch (err) {
            main.innerHTML = '<h4 class="mb-4"><i class="bi bi-shield-lock me-2"></i>Users</h4><div class="alert alert-danger">' + err.message + '</div>';
        }
    }

    function renderUsersTable(users) {
        const main = document.getElementById('mainContent');
        const roleBadge = (r) => {
            const map = { super_admin: 'danger', admin: 'warning', supervisor: 'info', agent: 'primary', viewer: 'secondary' };
            return `<span class="badge bg-${map[r] || 'secondary'}">${r.replace('_', ' ')}</span>`;
        };
        const authBadge = (a) => {
            const map = { local: 'secondary', sso: 'info', ldap: 'primary', oauth2: 'success', saml: 'warning' };
            return `<span class="badge bg-${map[a] || 'secondary'}">${(a || 'local').toUpperCase()}</span>`;
        };
        const rows = users.map(u => `
            <tr>
                <td>${u.full_name}</td>
                <td>${u.username}</td>
                <td>${u.email}</td>
                <td>${u.phone_number || '<span class="text-muted">—</span>'}</td>
                <td>${roleBadge(u.role)}</td>
                <td>${authBadge(u.auth_type)}</td>
                <td><span class="badge bg-${u.is_active ? 'success' : 'secondary'}">${u.is_active ? 'Active' : 'Disabled'}</span></td>
                <td><span class="badge bg-${u.is_online ? 'success' : 'dark'}">${u.is_online ? 'Online' : 'Offline'}</span></td>
                <td class="text-nowrap">
                    <button class="btn btn-sm btn-outline-primary me-1" onclick="window._wc_editUser('${u.id}')"><i class="bi bi-pencil"></i></button>
                    <button class="btn btn-sm btn-outline-danger" onclick="window._wc_deleteUser('${u.id}','${u.username}')"><i class="bi bi-trash"></i></button>
                </td>
            </tr>
        `).join('');
        const emptyMsg = users.length === 0
            ? '<tr><td colspan="9" class="text-center text-muted py-4">No users yet — click <strong>Add User</strong> to get started.</td></tr>'
            : rows;
        main.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h4 class="mb-0"><i class="bi bi-shield-lock me-2"></i>Users</h4>
                <button class="btn btn-primary btn-sm" id="btnAddUser"><i class="bi bi-person-plus me-1"></i>Add User</button>
            </div>
            <div class="card">
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead><tr><th>Name</th><th>Username</th><th>Email</th><th>Phone</th><th>Role</th><th>Auth</th><th>Status</th><th>Online</th><th></th></tr></thead>
                        <tbody>${emptyMsg}</tbody>
                    </table>
                </div>
            </div>
        `;
        document.getElementById('btnAddUser')?.addEventListener('click', () => showAddUserModal());
    }

    // ── Delete user ──
    window._wc_deleteUser = async function (id, username) {
        if (!confirm('Delete user "' + username + '"?')) return;
        try {
            const res = await apiFetch('/api/v1/users/' + id, { method: 'DELETE' });
            if (!res.ok && res.status !== 204) {
                const data = await res.json().catch(() => ({}));
                alert(data.detail || 'Failed to delete');
                return;
            }
            loadUsersSection();
        } catch (err) {
            alert(err.message);
        }
    };

    // ── Edit user ──
    window._wc_editUser = async function (id) {
        try {
            const res = await apiFetch('/api/v1/users/' + id);
            if (!res.ok) throw new Error('Failed to load user');
            const user = await res.json();
            showEditUserModal(user);
        } catch (err) {
            alert(err.message);
        }
    };

    function showEditUserModal(user) {
        let modal = document.getElementById('editUserModal');
        if (modal) modal.remove();

        const div = document.createElement('div');
        div.innerHTML = `
        <div class="modal fade" id="editUserModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header"><h5 class="modal-title"><i class="bi bi-pencil-square me-2"></i>Edit User</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                    <div class="modal-body">
                        <form id="editUserForm">
                            <input type="hidden" id="euId" value="${user.id}">
                            <div class="mb-3"><label class="form-label">Full Name</label><input type="text" class="form-control" id="euFullName" value="${user.full_name}" required></div>
                            <div class="mb-3"><label class="form-label">Email</label><input type="email" class="form-control" id="euEmail" value="${user.email}" required></div>
                            <div class="mb-3"><label class="form-label">Username</label><input type="text" class="form-control" id="euUsername" value="${user.username}" disabled></div>
                            <div class="mb-3"><label class="form-label">New Password</label><input type="password" class="form-control" id="euPassword" placeholder="Leave blank to keep current"></div>
                            <div class="mb-3"><label class="form-label">Role</label>
                                <select class="form-select" id="euRole">
                                    <option value="super_admin" ${user.role==='super_admin'?'selected':''}>Super Admin</option>
                                    <option value="admin" ${user.role==='admin'?'selected':''}>Admin</option>
                                    <option value="supervisor" ${user.role==='supervisor'?'selected':''}>Supervisor</option>
                                    <option value="agent" ${user.role==='agent'?'selected':''}>Agent</option>
                                    <option value="viewer" ${user.role==='viewer'?'selected':''}>Viewer</option>
                                </select>
                            </div>
                            <div class="mb-3"><label class="form-label">Auth Type</label>
                                <select class="form-select" id="euAuthType">
                                    <option value="local" ${user.auth_type==='local'?'selected':''}>Local</option>
                                    <option value="sso" ${user.auth_type==='sso'?'selected':''}>SSO</option>
                                    <option value="ldap" ${user.auth_type==='ldap'?'selected':''}>LDAP</option>
                                    <option value="oauth2" ${user.auth_type==='oauth2'?'selected':''}>OAuth2</option>
                                    <option value="saml" ${user.auth_type==='saml'?'selected':''}>SAML</option>
                                </select>
                            </div>
                            <div class="mb-3"><label class="form-label">Phone Number</label><input type="tel" class="form-control" id="euPhone" value="${user.phone_number || ''}"></div>
                            <div class="mb-3"><label class="form-label">Max Concurrent Chats</label><input type="number" class="form-control" id="euMaxChats" value="${user.max_concurrent_chats}" min="1"></div>
                            <div class="mb-3 form-check">
                                <input type="checkbox" class="form-check-input" id="euActive" ${user.is_active ? 'checked' : ''}>
                                <label class="form-check-label" for="euActive">Active</label>
                            </div>
                            <div id="euError" class="text-danger small mb-2" style="display:none;"></div>
                            <button type="submit" class="btn btn-primary w-100"><i class="bi bi-check-lg me-1"></i>Save Changes</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>`;
        document.body.appendChild(div.firstElementChild);
        modal = document.getElementById('editUserModal');

        document.getElementById('editUserForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const errEl = document.getElementById('euError');
            errEl.style.display = 'none';
            const payload = {
                full_name: document.getElementById('euFullName').value.trim(),
                email: document.getElementById('euEmail').value.trim(),
                role: document.getElementById('euRole').value,
                auth_type: document.getElementById('euAuthType').value,
                phone_number: document.getElementById('euPhone').value.trim() || null,
                max_concurrent_chats: parseInt(document.getElementById('euMaxChats').value) || 5,
                is_active: document.getElementById('euActive').checked,
            };
            const pwd = document.getElementById('euPassword').value;
            if (pwd) payload.password = pwd;
            try {
                const res = await apiFetch('/api/v1/users/' + document.getElementById('euId').value, { method: 'PATCH', body: payload });
                if (!res.ok) {
                    const data = await res.json();
                    throw new Error(data.detail || 'Update failed');
                }
                bootstrap.Modal.getInstance(modal)?.hide();
                loadUsersSection();
            } catch (err) {
                errEl.textContent = err.message;
                errEl.style.display = 'block';
            }
        });

        new bootstrap.Modal(modal).show();
    }

    // ── Add user modal ──
    function showAddUserModal() {
        let modal = document.getElementById('addUserModal');
        if (!modal) {
            const div = document.createElement('div');
            div.innerHTML = `
            <div class="modal fade" id="addUserModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header"><h5 class="modal-title"><i class="bi bi-person-plus me-2"></i>Add User</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                        <div class="modal-body">
                            <form id="addUserForm">
                                <div class="mb-3"><label class="form-label">Full Name</label><input type="text" class="form-control" id="auFullName" required></div>
                                <div class="mb-3"><label class="form-label">Email</label><input type="email" class="form-control" id="auEmail" required></div>
                                <div class="mb-3"><label class="form-label">Username</label><input type="text" class="form-control" id="auUsername" required></div>
                                <div class="mb-3"><label class="form-label">Password</label><input type="password" class="form-control" id="auPassword" required minlength="6"></div>
                                <div class="mb-3"><label class="form-label">Role</label>
                                    <select class="form-select" id="auRole">
                                        <option value="super_admin">Super Admin</option>
                                        <option value="admin">Admin</option>
                                        <option value="supervisor">Supervisor</option>
                                        <option value="agent" selected>Agent</option>
                                        <option value="viewer">Viewer</option>
                                    </select>
                                </div>
                                <div class="mb-3"><label class="form-label">Auth Type</label>
                                    <select class="form-select" id="auAuthType">
                                        <option value="local" selected>Local</option>
                                        <option value="sso">SSO</option>
                                        <option value="ldap">LDAP</option>
                                        <option value="oauth2">OAuth2</option>
                                        <option value="saml">SAML</option>
                                    </select>
                                </div>
                                <div class="mb-3"><label class="form-label">Phone Number</label><input type="tel" class="form-control" id="auPhone" placeholder="Optional"></div>
                                <div id="auError" class="text-danger small mb-2" style="display:none;"></div>
                                <button type="submit" class="btn btn-primary w-100">Create User</button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>`;
            document.body.appendChild(div.firstElementChild);
            modal = document.getElementById('addUserModal');
            document.getElementById('addUserForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const errEl = document.getElementById('auError');
                errEl.style.display = 'none';
                const payload = {
                    full_name: document.getElementById('auFullName').value.trim(),
                    email: document.getElementById('auEmail').value.trim(),
                    username: document.getElementById('auUsername').value.trim(),
                    password: document.getElementById('auPassword').value,
                    role: document.getElementById('auRole').value,
                    auth_type: document.getElementById('auAuthType').value,
                    phone_number: document.getElementById('auPhone').value.trim() || null,
                };
                try {
                    const res = await apiFetch('/api/v1/auth/register', { method: 'POST', body: payload });
                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || 'Failed');
                    }
                    bootstrap.Modal.getInstance(modal)?.hide();
                    loadUsersSection();
                } catch (err) {
                    errEl.textContent = err.message;
                    errEl.style.display = 'block';
                }
            });
        }
        document.getElementById('addUserForm').reset();
        document.getElementById('auError').style.display = 'none';
        new bootstrap.Modal(modal).show();
    }

    // ──── Settings Section (admin only) ────
    async function loadSettingsSection() {
        const main = document.getElementById('mainContent');
        if (!isAdmin()) {
            main.innerHTML = '<h4 class="mb-4"><i class="bi bi-gear me-2"></i>Settings</h4><div class="alert alert-warning">Admin privileges required.</div>';
            return;
        }
        main.innerHTML = '<h4 class="mb-4"><i class="bi bi-gear me-2"></i>Global Settings</h4><p class="text-muted">Loading...</p>';
        try {
            const res = await apiFetch('/api/v1/settings');
            if (!res.ok) throw new Error('Failed to load settings');
            const settings = await res.json();
            renderSettings(settings);
        } catch (err) {
            main.innerHTML = '<h4 class="mb-4"><i class="bi bi-gear me-2"></i>Settings</h4><div class="alert alert-danger">' + err.message + '</div>';
        }
    }

    function renderSettings(settings) {
        const main = document.getElementById('mainContent');
        const keyIcons = {
            locale: 'bi-globe', phone_country_code: 'bi-telephone', phone_format: 'bi-phone',
            timezone: 'bi-clock', date_format: 'bi-calendar', currency: 'bi-currency-exchange'
        };
        const rows = settings.map(s => `
            <tr>
                <td><i class="bi ${keyIcons[s.key] || 'bi-gear'} me-2"></i><strong>${s.key}</strong></td>
                <td><input type="text" class="form-control form-control-sm" id="setting_${s.key}" value="${s.value}" style="max-width:300px;"></td>
                <td class="text-muted small">${s.description || ''}</td>
                <td><button class="btn btn-sm btn-outline-success" onclick="window._wc_saveSetting('${s.key}')"><i class="bi bi-check-lg"></i></button></td>
            </tr>
        `).join('');
        main.innerHTML = `
            <h4 class="mb-4"><i class="bi bi-gear me-2"></i>Global Settings</h4>
            <div class="card">
                <div class="card-header bg-dark">
                    <i class="bi bi-sliders me-2"></i>Locale & Regional Configuration
                    <span class="badge bg-warning text-dark ms-2">Admin Only</span>
                </div>
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead><tr><th>Setting</th><th>Value</th><th>Description</th><th></th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
            <div id="settingsAlert" class="mt-3" style="display:none;"></div>
        `;
    }

    window._wc_saveSetting = async function (key) {
        const input = document.getElementById('setting_' + key);
        const alertEl = document.getElementById('settingsAlert');
        if (!input) return;
        try {
            const res = await apiFetch('/api/v1/settings/' + key, {
                method: 'PUT',
                body: { value: input.value.trim() }
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to save');
            }
            alertEl.className = 'mt-3 alert alert-success';
            alertEl.textContent = `Setting "${key}" saved successfully.`;
            alertEl.style.display = '';
            setTimeout(() => { alertEl.style.display = 'none'; }, 3000);
        } catch (err) {
            alertEl.className = 'mt-3 alert alert-danger';
            alertEl.textContent = err.message;
            alertEl.style.display = '';
        }
    };

    // ──── Dashboard data ────
    async function loadDashboard() {
        try {
            const flowsRes = await apiFetch('/api/v1/flows');
            if (flowsRes.ok) {
                const flows = await flowsRes.json();
                document.getElementById('statFlows').textContent = flows.filter(f => f.is_active).length;
                const recentEl = document.getElementById('recentFlows');
                if (flows.length === 0) {
                    recentEl.innerHTML = '<p class="text-muted">No flows yet. <a href="/flow-designer">Create one</a></p>';
                } else {
                    recentEl.innerHTML = flows.slice(0, 5).map(f => `
                        <div class="d-flex justify-content-between align-items-center py-1 border-bottom border-dark">
                            <a href="/flow-designer/${f.id}" class="text-decoration-none">${f.name}</a>
                            <span class="badge ${f.is_active ? 'bg-success' : 'bg-secondary'}">${f.is_active ? 'Active' : 'Draft'}</span>
                        </div>
                    `).join('');
                }
            }

            const campRes = await apiFetch('/api/v1/campaigns');
            if (campRes.ok) {
                const camps = await campRes.json();
                const activeEl = document.getElementById('activeCampaigns');
                const active = camps.filter(c => c.status === 'running');
                if (active.length === 0) {
                    activeEl.innerHTML = '<p class="text-muted">No active campaigns</p>';
                } else {
                    activeEl.innerHTML = active.map(c => `
                        <div class="d-flex justify-content-between py-1 border-bottom border-dark">
                            <span>${c.name}</span>
                            <span class="badge bg-success">Running</span>
                        </div>
                    `).join('');
                }
            }
        } catch (err) {
            console.error('Dashboard load error:', err);
        }
    }

    // ──── Init ────
    async function init() {
        if (!token) {
            showLogin();
            return;
        }
        try {
            const res = await apiFetch('/api/v1/auth/me');
            if (res.ok) {
                const user = await res.json();
                currentUserData = user;
                document.getElementById('currentUser').textContent = user.full_name;
                updateSettingsVisibility();
                loadDashboard();
            } else {
                showLogin();
            }
        } catch {
            showLogin();
        }
    }

    init();
})();

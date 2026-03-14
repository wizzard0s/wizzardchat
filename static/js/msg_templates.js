/**
 * WizzardChat – Message Templates management page
 */
(function () {
    'use strict';

    const API = '';
    const _token = () => localStorage.getItem('wizzardchat_token');
    const _headers = () => ({ 'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json' });

    let _templates = [];
    let _editId = null;
    let _waConnectors = [];
    let _waMetaTemplates = [];

    // ── Contact fields available for variable binding ────────────────────────
    const CONTACT_FIELDS = [
        { value: '', label: '— no binding —' },
        { value: 'first_name', label: 'First name' },
        { value: 'last_name', label: 'Last name' },
        { value: 'company', label: 'Company' },
        { value: 'phone', label: 'Phone' },
        { value: 'whatsapp_id', label: 'WhatsApp ID' },
        { value: 'email', label: 'Email' },
        { value: 'language', label: 'Language' },
    ];

    const CHANNEL_META = {
        whatsapp: { label: 'WhatsApp', icon: 'bi-whatsapp', color: '#0d6efd', wz: 'wz-channel-whatsapp' },
        sms:      { label: 'SMS',       icon: 'bi-phone',    color: '#0dcaf0', wz: 'wz-channel-sms'      },
        email:    { label: 'Email',     icon: 'bi-envelope', color: '#f59e0b', wz: 'wz-channel-email'    },
    };

    const STATUS_BADGE = {
        active:   'wz-status-active',
        draft:    'wz-status-draft',
        inactive: 'wz-status-inactive',
    };

    // ── Modal helpers ────────────────────────────────────────────────────────
    function _modal() {
        return bootstrap.Modal.getOrCreateInstance(document.getElementById('templateModal'));
    }

    // ── Load + render ────────────────────────────────────────────────────────
    async function loadTemplates() {
        const r = await fetch(API + '/api/v1/templates', { headers: _headers() });
        if (!r.ok) { console.error('templates fetch failed', r.status); return; }
        _templates = await r.json();
        _render();
    }

    function _render() {
        const grids = { all: [], wa: [], sms: [], email: [] };

        _templates.forEach(t => {
            const card = _buildCard(t);
            grids.all.push(card);
            if (t.channel === 'whatsapp') grids.wa.push(card);
            else if (t.channel === 'sms')  grids.sms.push(card);
            else if (t.channel === 'email') grids.email.push(card);
        });

        const fill = (gridId, emptyId, cards) => {
            const g = document.getElementById(gridId);
            const e = document.getElementById(emptyId);
            g.innerHTML = '';
            if (!cards.length) {
                e.style.display = 'block';
            } else {
                e.style.display = 'none';
                cards.forEach(c => g.appendChild(c));
            }
        };

        fill('gridAll', 'emptyAll', grids.all);
        fill('gridSms', 'emptySms', grids.sms);
        fill('gridEmail', 'emptyEmail', grids.email);

        // Stats (WA count is updated by loadWaMetaTab when a connector is selected)
        document.getElementById('statSms').textContent   = _templates.filter(t => t.channel === 'sms').length;
        document.getElementById('statEmail').textContent = _templates.filter(t => t.channel === 'email').length;
    }

    function _buildCard(t) {
        const col = document.createElement('div');
        col.className = 'col-md-4 col-sm-6';
        const m = CHANNEL_META[t.channel] || { label: t.channel, icon: 'bi-file-text', wz: 'wz-badge-muted' };
        const sb = STATUS_BADGE[t.status] || 'wz-status-inactive';
        const varCount = (t.variables || []).length;
        const waExtra = t.channel === 'whatsapp' && t.wa_template_name
            ? `<div class="small text-muted mt-1"><i class="bi bi-check2-circle me-1"></i><code>${esc(t.wa_template_name)}</code> · ${esc(t.wa_approval_status || '–')}</div>`
            : '';
        col.innerHTML = `
<div class="template-card-item h-100" onclick="openTemplateModal('${t.id}')">
    <div class="d-flex align-items-start justify-content-between mb-2">
        <div class="d-flex align-items-center gap-2">
            <span class="wz-badge ${m.wz}"><i class="bi ${m.icon} me-1"></i>${m.label}</span>
            <span class="wz-badge ${sb}" style="font-size:.68rem">${esc(t.status)}</span>
        </div>
        ${varCount ? `<span class="badge bg-dark border" title="${varCount} variable(s)"><i class="bi bi-braces me-1"></i>${varCount}</span>` : ''}
    </div>
    <div class="fw-semibold mb-1" style="font-size:14px">${esc(t.name)}</div>
    <div class="template-body-preview">${esc(t.body || '–')}</div>
    ${waExtra}
</div>`;
        return col;
    }

    function esc(s) {
        if (!s) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    // ── Variable scanning ────────────────────────────────────────────────────
    const VAR_RE = /\{\{(\d+)\}\}/g;

    window.tmplScanVars = function () {
        const body = document.getElementById('tmplBody').value;
        const positions = [];
        let m;
        VAR_RE.lastIndex = 0;
        while ((m = VAR_RE.exec(body)) !== null) {
            const pos = parseInt(m[1], 10);
            if (!positions.includes(pos)) positions.push(pos);
        }
        positions.sort((a, b) => a - b);
        const countEl = document.getElementById('tmplVarCount');
        countEl.textContent = positions.length ? `${positions.length} variable(s) detected: ${positions.map(p => `{{${p}}}`).join(', ')}` : '';
        _renderVarMapper(positions);
    };

    function _readCurrentVarRows() {
        const rows = {};
        document.querySelectorAll('.var-row[data-pos]').forEach(row => {
            const pos   = parseInt(row.dataset.pos, 10);
            const label = row.querySelector('.var-label-input').value.trim();
            const field = row.querySelector('.var-field-select').value;
            const def   = row.querySelector('.var-default-input').value.trim();
            rows[pos] = { label, field, def };
        });
        return rows;
    }

    function _renderVarMapper(positions) {
        const existing = _readCurrentVarRows();
        const wrap = document.getElementById('varMapperRows');
        if (!positions.length) {
            wrap.innerHTML = '<div class="text-muted fst-italic small">No <code>{{N}}</code> placeholders detected in the body yet.</div>';
            return;
        }
        const fieldOpts = CONTACT_FIELDS.map(f => `<option value="${f.value}">${esc(f.label)}</option>`).join('');
        wrap.innerHTML = `
<div class="row fw-semibold text-muted small mb-1 px-1" style="font-size:11px;">
    <div class="col-1">Pos</div>
    <div class="col-3">Label</div>
    <div class="col-4">Contact field</div>
    <div class="col-4">Default value</div>
</div>`;
        positions.forEach(pos => {
            const prev = existing[pos] || {};
            const row = document.createElement('div');
            row.className = 'var-row row g-2 mb-1';
            row.dataset.pos = pos;
            const fieldSel = CONTACT_FIELDS.map(f =>
                `<option value="${f.value}" ${(prev.field || '') === f.value ? 'selected' : ''}>${esc(f.label)}</option>`
            ).join('');
            row.innerHTML = `
<div class="col-1 fw-bold text-warning d-flex align-items-center justify-content-center" style="font-size:14px;">{{${pos}}}</div>
<div class="col-3"><input type="text" class="form-control form-control-sm var-label-input" placeholder="Label…" value="${esc(prev.label || '')}"></div>
<div class="col-4"><select class="form-select form-select-sm var-field-select">${fieldSel}</select></div>
<div class="col-4"><input type="text" class="form-control form-control-sm var-default-input" placeholder="Default…" value="${esc(prev.def || '')}"></div>`;
            wrap.appendChild(row);
        });
    }

    function _readVarRows() {
        return Array.from(document.querySelectorAll('.var-row[data-pos]')).map(row => ({
            pos:           parseInt(row.dataset.pos, 10),
            label:         row.querySelector('.var-label-input').value.trim() || `Variable ${row.dataset.pos}`,
            contact_field: row.querySelector('.var-field-select').value || null,
            default:       row.querySelector('.var-default-input').value.trim() || null,
        }));
    }

    // ── Channel change handler ────────────────────────────────────────────────
    window.tmplChannelChange = function () {
        const ch = document.getElementById('tmplChannel').value;
        document.getElementById('tmplTabWaLi').style.display    = ch === 'whatsapp' ? '' : 'none';
        document.getElementById('tmplTabEmailLi').style.display = ch === 'email'    ? '' : 'none';
    };

    // ── Open modal ───────────────────────────────────────────────────────────
    window.openTemplateModal = function (id) {
        _editId = id || null;
        const deleteBtn = document.getElementById('btnDeleteTemplate');

        if (_editId) {
            const t = _templates.find(x => x.id === _editId);
            if (!t) return;
            document.getElementById('tmplModalTitle').innerHTML = '<i class="bi bi-card-text me-2"></i>Edit Template';
            deleteBtn.style.display = '';
            _fillForm(t);
        } else {
            document.getElementById('tmplModalTitle').innerHTML = '<i class="bi bi-card-text me-2"></i>New Template';
            deleteBtn.style.display = 'none';
            _resetForm();
        }

        const firstTab = document.querySelector('#tmplTabs .nav-link');
        bootstrap.Tab.getOrCreateInstance(firstTab).show();
        _modal().show();
    };

    function _resetForm() {
        document.getElementById('tmplName').value        = '';
        document.getElementById('tmplChannel').value     = 'sms';
        document.getElementById('tmplStatus').value      = 'active';
        document.getElementById('tmplBody').value        = '';
        document.getElementById('tmplWaName').value      = '';
        document.getElementById('tmplWaLang').value      = 'en';
        document.getElementById('tmplWaApproval').value  = 'pending';
        document.getElementById('tmplWaCategory').value  = '';
        document.getElementById('tmplEmailSubject').value = '';
        document.getElementById('tmplEmailFrom').value   = '';
        document.getElementById('tmplEmailReplyTo').value = '';
        document.getElementById('varMapperRows').innerHTML = '<div class="text-muted fst-italic small">No <code>{{N}}</code> placeholders detected in the body yet.</div>';
        document.getElementById('tmplVarCount').textContent = '';
        tmplChannelChange();
    }

    function _fillForm(t) {
        document.getElementById('tmplName').value        = t.name || '';
        document.getElementById('tmplChannel').value     = t.channel || 'whatsapp';
        document.getElementById('tmplStatus').value      = t.status || 'active';
        document.getElementById('tmplBody').value        = t.body || '';
        document.getElementById('tmplWaName').value      = t.wa_template_name || '';
        document.getElementById('tmplWaLang').value      = t.wa_language || 'en';
        document.getElementById('tmplWaApproval').value  = t.wa_approval_status || 'pending';
        document.getElementById('tmplWaCategory').value  = t.wa_category || '';
        document.getElementById('tmplEmailSubject').value = t.subject || '';
        document.getElementById('tmplEmailFrom').value   = t.from_name || '';
        document.getElementById('tmplEmailReplyTo').value = t.reply_to || '';
        tmplChannelChange();

        // Scan vars and pre-fill from saved variables
        const body = t.body || '';
        const positions = [];
        let m;
        VAR_RE.lastIndex = 0;
        while ((m = VAR_RE.exec(body)) !== null) {
            const pos = parseInt(m[1], 10);
            if (!positions.includes(pos)) positions.push(pos);
        }
        positions.sort((a, b) => a - b);
        _renderVarMapper(positions);

        // Apply saved variable metadata
        (t.variables || []).forEach(v => {
            const row = document.querySelector(`.var-row[data-pos="${v.pos}"]`);
            if (!row) return;
            if (v.label)         row.querySelector('.var-label-input').value    = v.label;
            if (v.contact_field) row.querySelector('.var-field-select').value   = v.contact_field;
            if (v.default)       row.querySelector('.var-default-input').value  = v.default;
        });

        const countEl = document.getElementById('tmplVarCount');
        countEl.textContent = positions.length ? `${positions.length} variable(s): ${positions.map(p => `{{${p}}}`).join(', ')}` : '';
    }

    // ── Save ─────────────────────────────────────────────────────────────────
    window.saveTemplate = async function () {
        const name = document.getElementById('tmplName').value.trim();
        if (!name) { alert('Template name is required.'); return; }
        const body = document.getElementById('tmplBody').value.trim();
        if (!body) { alert('Template body is required.'); return; }

        const payload = {
            name,
            channel:  document.getElementById('tmplChannel').value,
            status:   document.getElementById('tmplStatus').value,
            body,
            subject:            document.getElementById('tmplEmailSubject').value.trim() || null,
            from_name:          document.getElementById('tmplEmailFrom').value.trim() || null,
            reply_to:           document.getElementById('tmplEmailReplyTo').value.trim() || null,
            wa_template_name:   document.getElementById('tmplWaName').value.trim() || null,
            wa_language:        document.getElementById('tmplWaLang').value.trim() || 'en',
            wa_approval_status: document.getElementById('tmplWaApproval').value || 'pending',
            wa_category:        document.getElementById('tmplWaCategory').value || null,
            variables:          _readVarRows(),
        };

        const url    = _editId ? `/api/v1/templates/${_editId}` : '/api/v1/templates';
        const method = _editId ? 'PUT' : 'POST';

        const r = await fetch(API + url, { method, headers: _headers(), body: JSON.stringify(payload) });
        if (!r.ok) {
            const e = await r.json().catch(() => ({}));
            const msg = Array.isArray(e.detail)
                ? e.detail.map(d => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('\n')
                : (e.detail || 'Save failed');
            alert(msg);
            return;
        }

        _modal().hide();
        await loadTemplates();
    };

    // ── Delete ───────────────────────────────────────────────────────────────
    window.deleteTemplate = async function () {
        if (!_editId) return;
        if (!confirm('Delete this template? This action cannot be undone.')) return;
        const r = await fetch(API + `/api/v1/templates/${_editId}`, { method: 'DELETE', headers: _headers() });
        if (!r.ok) { alert('Delete failed.'); return; }
        _modal().hide();
        await loadTemplates();
    };

    // ── WhatsApp Meta browser ─────────────────────────────────────────────────
    async function _loadWaConnectors() {
        const r = await fetch(API + '/api/v1/connectors', { headers: _headers() });
        if (!r.ok) return;
        const all = await r.json();
        _waConnectors = all.filter(c => (c.connector_type || c.type || '').toLowerCase().includes('whatsapp'));
        const sel = document.getElementById('waConnectorSel');
        if (!sel) return;
        sel.innerHTML = '<option value="">\u2014 select connector \u2014</option>';
        _waConnectors.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name || c.id;
            sel.appendChild(opt);
        });
        if (_waConnectors.length === 1) {
            sel.value = _waConnectors[0].id;
            window.loadWaMetaTab(_waConnectors[0].id);
        }
    }

    window.loadWaMetaTab = async function (connectorId) {
        const grid  = document.getElementById('gridWaMeta');
        const empty = document.getElementById('emptyWaMeta');
        if (!grid) return;
        grid.innerHTML = '';
        if (!connectorId) {
            empty.style.display = 'block';
            empty.textContent = 'Select a WhatsApp connector to view approved templates.';
            document.getElementById('statWa').textContent = '\u2013';
            return;
        }
        empty.style.display = 'block';
        empty.textContent = 'Loading from Meta\u2026';
        const r = await fetch(API + `/api/v1/whatsapp-connectors/${connectorId}/meta-templates`, { headers: _headers() });
        if (!r.ok) {
            empty.textContent = 'Failed to load templates \u2014 check connector credentials.';
            return;
        }
        _waMetaTemplates = await r.json();
        const approved = _waMetaTemplates.filter(t => t.status === 'APPROVED');
        document.getElementById('statWa').textContent = approved.length;
        if (!_waMetaTemplates.length) {
            empty.textContent = 'No templates found in this Meta account.';
            return;
        }
        empty.style.display = 'none';
        _waMetaTemplates.forEach(t => {
            const col = document.createElement('div');
            col.className = 'col-md-4 col-sm-6';
            const statusCls = t.status === 'APPROVED' ? 'wz-status-active'
                            : t.status === 'REJECTED'  ? 'wz-status-cancelled'
                            : 'wz-status-draft';
            const varBadge = t.variables_count > 0
                ? `<span class="badge bg-dark border" title="${t.variables_count} variable(s)"><i class="bi bi-braces me-1"></i>${t.variables_count}</span>` : '';
            const catBadge = t.category
                ? `<span class="badge bg-secondary ms-1" style="font-size:.65rem">${esc(t.category)}</span>` : '';
            const hdrLine  = t.header ? `<div class="small text-muted mt-1"><i class="bi bi-card-heading me-1"></i>${esc(t.header)}</div>` : '';
            const ftrLine  = t.footer ? `<div class="small text-muted"><i class="bi bi-card-text me-1"></i>${esc(t.footer)}</div>` : '';
            col.innerHTML = `
<div class="template-card-item h-100">
    <div class="d-flex align-items-start justify-content-between mb-2">
        <div class="d-flex align-items-center gap-1 flex-wrap">
            <span class="wz-badge wz-channel-whatsapp"><i class="bi bi-whatsapp me-1"></i>WhatsApp</span>
            <span class="wz-badge ${statusCls}" style="font-size:.68rem">${esc(t.status)}</span>
            ${catBadge}
        </div>
        ${varBadge}
    </div>
    <div class="fw-semibold mb-1" style="font-size:14px">${esc(t.name)}</div>
    <div class="text-muted small mb-1"><i class="bi bi-translate me-1"></i>${esc(t.language)}</div>
    <div class="template-body-preview">${esc(t.body || '\u2013')}</div>
    ${hdrLine}${ftrLine}
</div>`;
            grid.appendChild(col);
        });
    };

    // ── Logout ───────────────────────────────────────────────────────────────
    document.getElementById('btnLogout').addEventListener('click', e => {
        e.preventDefault();
        localStorage.removeItem('wizzardchat_token');
        window.location.href = '/login';
    });

    // ── Boot ─────────────────────────────────────────────────────────────────
    if (typeof _guard === 'function') _guard();
    loadTemplates();
    _loadWaConnectors();

})();

/**
 * WizzardChat Flow Designer – Visual drag-and-drop flow editor
 * Canvas with pan/zoom, node drag, edge drawing, properties panel, API save/load.
 */
(function () {
    'use strict';

    const API = '';
    const token = () => localStorage.getItem('wizzardchat_token');
    const headers = () => ({
        'Authorization': 'Bearer ' + token(),
        'Content-Type': 'application/json',
    });

    // ───── Utilities ─────
    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ───── State ─────
    let flowId = null;
    let flowData = null;
    let nodes = [];       // { id, type, label, x, y, config, el }
    let edges = [];       // { id, sourceId, targetId, sourceHandle, label, condition, el }
    let selectedNode = null;
    let selectedEdge = null;
    let nextTempId = 1;

    // Canvas transform
    let panX = 0, panY = 0, zoom = 1;
    let isPanning = false, panStartX = 0, panStartY = 0;

    // Dragging nodes
    let dragNode = null, dragOffsetX = 0, dragOffsetY = 0;

    // Drawing edges
    let drawingEdge = false, edgeSourceNode = null, edgeSourceHandle = 'default';

    // DOM refs
    const canvas = document.getElementById('canvas');
    const container = document.getElementById('canvasContainer');
    const edgeSvg = document.getElementById('edgeSvg');
    const tempEdgeSvg = document.getElementById('tempEdgeSvg');
    const propsPanel = document.getElementById('propertiesPanel');
    const propBody = document.getElementById('propBody');
    const propTitle = document.getElementById('propTitle');

    // Node type metadata — populated from registry API at init, with fallback defaults
    const NODE_ICONS = {
        start: 'bi-play-circle', end: 'bi-stop-circle', message: 'bi-chat-left-text',
        condition: 'bi-signpost-split', input: 'bi-input-cursor-text', transfer: 'bi-telephone-forward',
        queue: 'bi-people', http_request: 'bi-globe', set_variable: 'bi-braces',
        wait: 'bi-hourglass', menu: 'bi-list-ol', play_audio: 'bi-volume-up',
        record: 'bi-mic', dtmf: 'bi-grid-3x3', ai_bot: 'bi-robot', webhook: 'bi-broadcast',
        goto: 'bi-arrow-return-right', sub_flow: 'bi-box-arrow-in-right',
    };

    // Full registry: key → { key, label, icon, category, color, has_input, has_output, config_schema, is_builtin }
    const NODE_REGISTRY = {};

    // ───── API helpers ─────

    async function apiFetch(url, opts = {}) {
        opts.headers = { ...headers(), ...(opts.headers || {}) };
        if (opts.body && typeof opts.body === 'object') {
            opts.body = JSON.stringify(opts.body);
        }
        const res = await fetch(API + url, opts);
        if (res.status === 401) {
            window.location.href = '/';
            return null;
        }
        return res;
    }

    // ───── Canvas Transform ─────

    function updateTransform() {
        canvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
        // SVGs use viewBox only (no CSS transform) – avoids double-transform misalignment
        const vb = `${-panX / zoom} ${-panY / zoom} ${container.clientWidth / zoom} ${container.clientHeight / zoom}`;
        edgeSvg.setAttribute('viewBox', vb);
        tempEdgeSvg.setAttribute('viewBox', vb);
    }

    // Keep SVG viewBox in sync whenever the container resizes
    // (e.g. properties panel show/hide changes flex width)
    new ResizeObserver(() => updateTransform()).observe(container);

    container.addEventListener('mousedown', (e) => {
        if (e.target === container || e.target === canvas) {
            isPanning = true;
            panStartX = e.clientX - panX;
            panStartY = e.clientY - panY;
            container.classList.add('panning');
            deselectAll();
        }
    });

    window.addEventListener('mousemove', (e) => {
        if (isPanning) {
            panX = e.clientX - panStartX;
            panY = e.clientY - panStartY;
            updateTransform();
        }
        if (dragNode) {
            const rect = container.getBoundingClientRect();
            dragNode.x = (e.clientX - rect.left - panX - dragOffsetX) / zoom;
            dragNode.y = (e.clientY - rect.top - panY - dragOffsetY) / zoom;
            positionNode(dragNode);
            renderEdges();
        }
        if (drawingEdge) {
            drawTempEdge(e);
        }
    });

    window.addEventListener('mouseup', (e) => {
        if (isPanning) {
            isPanning = false;
            container.classList.remove('panning');
        }
        if (dragNode) {
            dragNode = null;
        }
        if (drawingEdge) {
            finishEdgeDraw(e);
        }
    });

    // Zoom
    container.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.08 : 0.08;
        const newZoom = Math.max(0.2, Math.min(3, zoom + delta));
        // Zoom toward mouse
        const rect = container.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        panX = mx - (mx - panX) * (newZoom / zoom);
        panY = my - (my - panY) * (newZoom / zoom);
        zoom = newZoom;
        updateTransform();
    }, { passive: false });

    document.getElementById('btnZoomIn').addEventListener('click', () => { zoom = Math.min(3, zoom + 0.15); updateTransform(); });
    document.getElementById('btnZoomOut').addEventListener('click', () => { zoom = Math.max(0.2, zoom - 0.15); updateTransform(); });
    document.getElementById('btnFitView').addEventListener('click', fitView);

    function fitView() {
        if (nodes.length === 0) { panX = 100; panY = 100; zoom = 1; updateTransform(); return; }
        const xs = nodes.map(n => n.x);
        const ys = nodes.map(n => n.y);
        const minX = Math.min(...xs) - 50, maxX = Math.max(...xs) + 220;
        const minY = Math.min(...ys) - 50, maxY = Math.max(...ys) + 120;
        const w = maxX - minX, h = maxY - minY;
        const cw = container.clientWidth, ch = container.clientHeight;
        zoom = Math.min(cw / w, ch / h, 1.5);
        panX = (cw - w * zoom) / 2 - minX * zoom;
        panY = (ch - h * zoom) / 2 - minY * zoom;
        updateTransform();
    }

    // ───── Node Rendering ─────

    function createNodeElement(node) {
        const el = document.createElement('div');
        el.className = 'flow-node';
        el.dataset.type = node.type;
        el.dataset.id = node.id;

        const icon = NODE_ICONS[node.type] || 'bi-puzzle';
        const reg = NODE_REGISTRY[node.type];
        const hasInput = reg ? reg.has_input : (node.type !== 'start');
        const hasOutput = reg ? reg.has_output : (node.type !== 'end');
        const isCondition = node.type === 'condition';

        el.innerHTML = `
            <div class="node-header"><i class="bi ${icon}"></i>${node.type.replace(/_/g, ' ')}</div>
            <div class="node-body">${node.label || node.type}</div>
            ${hasInput ? '<div class="node-port port-in" data-port="in"></div>' : ''}
            ${isCondition
                ? '<div class="node-port port-out-true" data-port="true" title="True"></div><div class="node-port port-out-false" data-port="false" title="False"></div>'
                : (hasOutput ? '<div class="node-port port-out" data-port="default"></div>' : '')
            }
        `;

        // Node click select
        el.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('node-port')) return;
            e.stopPropagation();
            selectNode(node);
            dragNode = node;
            const rect = el.getBoundingClientRect();
            dragOffsetX = e.clientX - rect.left;
            dragOffsetY = e.clientY - rect.top;
        });

        // Port mousedown → start edge drawing
        el.querySelectorAll('.node-port[data-port]:not([data-port="in"])').forEach(port => {
            port.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                drawingEdge = true;
                edgeSourceNode = node;
                edgeSourceHandle = port.dataset.port;
            });
        });

        // Port mouseup → complete edge
        const inPort = el.querySelector('.node-port[data-port="in"]');
        if (inPort) {
            inPort.addEventListener('mouseup', (e) => {
                e.stopPropagation();
                if (drawingEdge && edgeSourceNode && edgeSourceNode.id !== node.id) {
                    addEdge(edgeSourceNode.id, node.id, edgeSourceHandle);
                }
                drawingEdge = false;
                edgeSourceNode = null;
                tempEdgeSvg.innerHTML = '';
            });
        }

        canvas.appendChild(el);
        node.el = el;
        positionNode(node);
        return el;
    }

    function positionNode(node) {
        if (node.el) {
            node.el.style.left = node.x + 'px';
            node.el.style.top = node.y + 'px';
        }
    }

    // ───── Edge Rendering ─────

    function getPortPosition(node, handle) {
        if (!node.el) return { x: node.x, y: node.y };
        const w = node.el.offsetWidth;
        const h = node.el.offsetHeight;
        if (handle === 'in') return { x: node.x + w / 2, y: node.y };
        if (handle === 'true') return { x: node.x + w * 0.3, y: node.y + h };
        if (handle === 'false') return { x: node.x + w * 0.7, y: node.y + h };
        return { x: node.x + w / 2, y: node.y + h }; // default out
    }

    function renderEdges() {
        edgeSvg.innerHTML = '';
        edges.forEach(edge => {
            const src = nodes.find(n => n.id === edge.sourceId);
            const tgt = nodes.find(n => n.id === edge.targetId);
            if (!src || !tgt) return;

            const from = getPortPosition(src, edge.sourceHandle || 'default');
            const to = getPortPosition(tgt, 'in');

            const midY = (from.y + to.y) / 2;
            const d = `M ${from.x} ${from.y} C ${from.x} ${midY}, ${to.x} ${midY}, ${to.x} ${to.y}`;

            const ns = 'http://www.w3.org/2000/svg';
            const path = document.createElementNS(ns, 'path');
            path.setAttribute('d', d);
            path.setAttribute('class', 'edge-path' + (selectedEdge === edge.id ? ' selected' : ''));
            path.style.pointerEvents = 'stroke';
            path.addEventListener('click', (e) => {
                e.stopPropagation();
                selectEdge(edge);
            });
            edgeSvg.appendChild(path);

            // Edge label
            if (edge.label || edge.sourceHandle === 'true' || edge.sourceHandle === 'false') {
                const text = document.createElementNS(ns, 'text');
                text.setAttribute('x', (from.x + to.x) / 2);
                text.setAttribute('y', midY - 6);
                text.setAttribute('fill', '#adb5bd');
                text.setAttribute('font-size', '11');
                text.setAttribute('text-anchor', 'middle');
                text.textContent = edge.label || edge.sourceHandle;
                edgeSvg.appendChild(text);
            }
        });
    }

    function drawTempEdge(e) {
        if (!edgeSourceNode) return;
        const rect = container.getBoundingClientRect();
        const mx = (e.clientX - rect.left - panX) / zoom;
        const my = (e.clientY - rect.top - panY) / zoom;
        const from = getPortPosition(edgeSourceNode, edgeSourceHandle);
        const midY = (from.y + my) / 2;
        const d = `M ${from.x} ${from.y} C ${from.x} ${midY}, ${mx} ${midY}, ${mx} ${my}`;
        tempEdgeSvg.innerHTML = '';
        const ns = 'http://www.w3.org/2000/svg';

        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', d);
        path.setAttribute('class', 'temp-edge');
        tempEdgeSvg.appendChild(path);
    }

    function finishEdgeDraw(e) {
        drawingEdge = false;
        edgeSourceNode = null;
        tempEdgeSvg.innerHTML = '';
    }

    // ───── Selection ─────

    function deselectAll() {
        nodes.forEach(n => n.el?.classList.remove('selected'));
        selectedNode = null;
        selectedEdge = null;
        propsPanel.style.display = 'none';
        edgeSvg.querySelectorAll('.edge-path').forEach(p => p.classList.remove('selected'));
    }

    function selectNode(node) {
        deselectAll();
        selectedNode = node;
        node.el.classList.add('selected');
        showNodeProperties(node);
    }

    function selectEdge(edge) {
        deselectAll();
        selectedEdge = edge.id;
        renderEdges();
        // Show minimal edge props
        propsPanel.style.display = 'block';
        propTitle.textContent = 'Edge';
        propBody.innerHTML = `
            <div class="mb-2">
                <label class="form-label">Label</label>
                <input type="text" class="form-control form-control-sm" value="${edge.label || ''}" id="edgeLabel">
            </div>
            <button class="btn btn-sm btn-outline-danger w-100" id="btnDeleteEdge"><i class="bi bi-trash me-1"></i>Delete Edge</button>
        `;
        document.getElementById('edgeLabel')?.addEventListener('change', (e) => {
            edge.label = e.target.value;
            renderEdges();
        });
        document.getElementById('btnDeleteEdge')?.addEventListener('click', () => {
            edges = edges.filter(ed => ed.id !== edge.id);
            renderEdges();
            deselectAll();
        });
    }

    // ───── Properties Panel ─────

    let _currentNodeId = null; // tracked so expression builder knows which node's vars to show

    function showNodeProperties(node) {
        _currentNodeId = node.id;
        propsPanel.style.display = 'block';
        propTitle.textContent = node.type.replace(/_/g, ' ');

        const esc = (v) => String(v ?? '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
        const reg = NODE_REGISTRY[node.type];
        const schema = reg?.config_schema || [];

        // Ensure expression mode tracking object exists
        if (!node.config._expressions) node.config._expressions = {};

        let html = `
            <div class="mb-2">
                <label class="form-label">Label</label>
                <input type="text" class="form-control form-control-sm" value="${esc(node.label)}" id="propLabel">
            </div>
        `;

        // Node type description
        if (reg?.description) {
            html += `<div class="form-text small text-muted mb-2"><i class="bi bi-info-circle me-1"></i>${reg.description}</div>`;
        }

        // Set Variable has its own rich multi-field editor
        if (node.type === 'set_variable') {
            html += renderSetFieldsPanel(node);
        } else if (schema.length > 0) {
            // Universal schema-driven form rendering with expression toggles
            html += renderFormFields(schema, node);
        }

        // Advanced JSON config (always at bottom)
        html += `
            <hr>
            <details class="mb-2">
                <summary class="small text-muted"><i class="bi bi-code-slash me-1"></i>Advanced (JSON config)</summary>
                <textarea class="form-control form-control-sm mt-1 font-monospace" rows="4" id="propConfigJson">${JSON.stringify(node.config, null, 2)}</textarea>
            </details>
        `;

        propBody.innerHTML = html;

        // ─── Bind events ───

        // Label
        document.getElementById('propLabel')?.addEventListener('change', (e) => {
            node.label = e.target.value;
            updateNodeDisplay(node);
        });

        // Universal form field bindings (schema-driven)
        if (node.type !== 'set_variable' && schema.length > 0) {
            bindFormFields(schema, node);
        }

        // Set variable multi-field editor bindings
        if (node.type === 'set_variable') {
            bindSetFieldsPanel(node);
        }

        // JSON config override
        document.getElementById('propConfigJson')?.addEventListener('change', (e) => {
            try {
                node.config = JSON.parse(e.target.value);
                updateNodeDisplay(node);
            } catch { /* ignore bad JSON */ }
        });

        // Delete node button
        document.getElementById('btnDeleteNode')?.addEventListener('click', () => {
            deleteNode(node);
        });

        // Attach {{ variable pickers to all text inputs in this panel
        _attachVariablePickers(node.id);
    }

    // ───── Universal Form Rendering (schema-driven with expression toggle) ─────

    /** Render all form fields from a config_schema array */
    function renderFormFields(schema, node) {
        let html = '';
        schema.forEach(field => {
            html += renderFormField(field, node);
        });
        return html;
    }

    /** Render a single form field with optional expression toggle */
    function renderFormField(field, node) {
        const esc = (v) => String(v ?? '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
        const isExpr = node.config._expressions?.[field.key] === true;
        const val = node.config[field.key] ?? field.default ?? '';
        const exprEnabled = field.expression_enabled !== false; // default: true

        let html = `<div class="mb-2 form-field-group" data-field-key="${field.key}">`;

        // Label row with expression toggle button
        const showVarLabelBtn = ['textarea','code','json'].includes(field.type) || isExpr;
        html += `<div class="d-flex align-items-center gap-1 mb-1">`;
        html += `<label class="form-label mb-0 flex-grow-1">${field.label || field.key}${field.required ? ' <span class="text-danger">*</span>' : ''}</label>`;
        if (showVarLabelBtn) {
            html += `<button class="btn btn-sm btn-outline-secondary btn-var-insert" data-key="${field.key}" title="Insert {{variable}}">
                        <i class="bi bi-braces"></i>
                    </button>`;
        }
        if (exprEnabled) {
            html += `<button class="btn btn-sm field-mode-toggle ${isExpr ? 'field-mode-expr' : 'field-mode-text'}" data-key="${field.key}"
                        title="${isExpr ? 'JSONata expression mode \u2013 click for literal' : 'Literal value \u2013 click for expression'}">
                        ${isExpr ? '<i class="bi bi-lightning-charge-fill"></i>' : '<i class="bi bi-fonts"></i>'}
                    </button>`;
            if (isExpr) {
                html += `<button class="btn btn-sm btn-outline-warning field-expr-builder" data-key="${field.key}" title="Open Expression Builder">
                            <i class="bi bi-tools"></i>
                        </button>`;
            }
        }
        html += `</div>`;

        // Description
        if (field.description) {
            html += `<div class="field-description">${field.description}</div>`;
        }

        // Input widget: expression mode or literal form widget
        if (isExpr) {
            if (field.type === 'options_list') {
                const exprStr = typeof val === 'string' ? val : JSON.stringify(val, null, 2);
                html += `<textarea class="form-control form-control-sm field-input field-expr-input font-monospace"
                            data-key="${field.key}" data-field-type="expression"
                            rows="5" placeholder='JSONata expression returning e.g. [{"key":"1","text":"Yes"},{"key":"2","text":"No"}]'>${esc(exprStr)}</textarea>`;
            } else {
                html += `<input type="text" class="form-control form-control-sm field-input field-expr-input"
                            data-key="${field.key}" data-field-type="expression" value="${esc(val)}"
                            placeholder="JSONata expr e.g. $var &amp; ' text'">`;
            }
        } else {
            html += renderFieldWidget(field, val, esc);
        }

        html += `</div>`;
        return html;
    }

    /** Render the literal-mode form widget for a given field type */
    function renderFieldWidget(field, val, esc) {
        const key = field.key;
        const ph = field.placeholder || '';
        switch (field.type) {
            case 'textarea':
                return `<textarea class="form-control form-control-sm field-input" data-key="${key}" data-field-type="textarea"
                            rows="3" placeholder="${esc(ph)}">${esc(val)}</textarea>`;
            case 'number':
                return `<input type="number" class="form-control form-control-sm field-input" data-key="${key}" data-field-type="number"
                            step="any" value="${esc(val)}" placeholder="${esc(ph)}">`;
            case 'boolean':
                return `<select class="form-select form-select-sm field-input" data-key="${key}" data-field-type="boolean">
                            <option value="true" ${val === true || val === 'true' ? 'selected' : ''}>true</option>
                            <option value="false" ${val === false || val === 'false' ? 'selected' : ''}>false</option>
                        </select>`;
            case 'select':
                return `<select class="form-select form-select-sm field-input" data-key="${key}" data-field-type="select">
                            ${(field.options || []).map(opt => `<option value="${esc(opt)}" ${String(val) === String(opt) ? 'selected' : ''}>${opt}</option>`).join('')}
                        </select>`;
            case 'url':
                return `<div class="input-group input-group-sm">
                    <input type="url" class="form-control field-input" data-key="${key}" data-field-type="url"
                        value="${esc(val)}" placeholder="${esc(ph || 'https://')}">
                    <button class="btn btn-outline-secondary btn-var-insert" type="button" data-key="${key}" title="Insert {{variable}}"><i class="bi bi-braces"></i></button>
                </div>`;
            case 'json': {
                const jsonVal = typeof val === 'object' && val !== null ? JSON.stringify(val, null, 2) : (val || '');
                return `<textarea class="form-control form-control-sm field-input font-monospace" data-key="${key}" data-field-type="json"
                            rows="3" placeholder="${esc(ph || '{}')}">${esc(jsonVal)}</textarea>`;
            }
            case 'code':
                return `<textarea class="form-control form-control-sm field-input font-monospace" data-key="${key}" data-field-type="code"
                            rows="4" placeholder="${esc(ph)}">${esc(val)}</textarea>`;
            case 'options_list':
                return renderOptionsListEditor(key, val || []);
            case 'key_value': {
                const kvVal = typeof val === 'object' && val !== null ? val : {};
                return renderKeyValueEditor(key, kvVal);
            }
            case 'connector_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="connector_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 None (unlinked) \u2014'}</option>
                    </select>
                    <a href="/connectors" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage connectors">
                        <i class="bi bi-box-arrow-up-right"></i>
                    </a>
                </div>`;
            case 'queue_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="queue_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 Select queue \u2014'}</option>
                    </select>
                    <a href="#" onclick="event.preventDefault()" class="btn btn-sm btn-outline-secondary" title="Queues are configured in the Queues section">
                        <i class="bi bi-people"></i>
                    </a>
                </div>`;
            case 'flow_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="flow_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 Select flow \u2014'}</option>
                    </select>
                    <a href="/flows" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage flows">
                        <i class="bi bi-diagram-3"></i>
                    </a>
                </div>`;
            default: // string
                return `<div class="input-group input-group-sm">
                    <input type="text" class="form-control field-input" data-key="${key}" data-field-type="string"
                        value="${esc(val)}" placeholder="${esc(ph)}">
                    <button class="btn btn-outline-secondary btn-var-insert" type="button" data-key="${key}" title="Insert {{variable}}"><i class="bi bi-braces"></i></button>
                </div>`;
        }
    }

    /** Render menu-style dynamic options list (key + text pairs) */
    function renderOptionsListEditor(key, options) {
        // Handle string value when switching back from JSONata expression mode
        if (typeof options === 'string') {
            try { options = JSON.parse(options); } catch { options = []; }
        }
        if (!Array.isArray(options) || options.length === 0) {
            options = [{ key: '1', text: 'Option 1' }];
        }
        const esc = (v) => String(v ?? '').replace(/"/g, '&quot;');
        let html = `<div class="options-list-editor" data-key="${key}">`;
        options.forEach((o, i) => {
            html += `<div class="input-group input-group-sm mb-1 opt-row" data-idx="${i}">
                <input type="text" class="form-control opt-key" value="${esc(o.key)}" placeholder="Key" style="max-width:60px">
                <input type="text" class="form-control opt-text" value="${esc(o.text)}" placeholder="Label text">
                <button class="btn btn-outline-danger opt-remove" type="button"><i class="bi bi-x"></i></button>
            </div>`;
        });
        html += `<button class="btn btn-sm btn-outline-secondary w-100 mt-1 opt-add" data-key="${key}">
                    <i class="bi bi-plus me-1"></i>Add Option
                 </button>`;
        html += `</div>`;
        return html;
    }

    /** Render a key-value editor for JSON objects */
    function renderKeyValueEditor(key, obj) {
        if (typeof obj !== 'object' || obj === null) obj = {};
        const entries = Object.entries(obj);
        const esc = (v) => String(v ?? '').replace(/"/g, '&quot;');
        let html = `<div class="kv-editor" data-key="${key}">`;
        entries.forEach(([k, v], i) => {
            html += `<div class="input-group input-group-sm mb-1 kv-row" data-idx="${i}">
                <input type="text" class="form-control kv-k" value="${esc(k)}" placeholder="Variable name">
                <input type="text" class="form-control kv-v" value="${esc(v)}" placeholder="Value / {{variable}}">
                <button class="btn btn-outline-secondary kv-var-insert" type="button" title="Insert {{variable}}"><i class="bi bi-braces"></i></button>
                <button class="btn btn-outline-danger kv-remove" type="button"><i class="bi bi-x"></i></button>
            </div>`;
        });
        html += `<button class="btn btn-sm btn-outline-secondary w-100 mt-1 kv-add" data-key="${key}">
                    <i class="bi bi-plus me-1"></i>Add
                 </button>`;
        html += `</div>`;
        return html;
    }

    /** Bind event handlers for all schema-driven form fields */
    function bindFormFields(schema, node) {
        // Value change handlers for standard field inputs
        document.querySelectorAll('#propBody .field-input').forEach(el => {
            el.addEventListener('change', () => {
                const key = el.dataset.key;
                const fieldType = el.dataset.fieldType;
                let val = el.value;

                // Type coercion based on field type
                if (fieldType === 'number') {
                    val = parseFloat(val);
                    if (isNaN(val)) val = 0;
                } else if (fieldType === 'boolean') {
                    val = val === 'true';
                } else if (fieldType === 'json') {
                    try { val = JSON.parse(val); } catch { /* keep as string */ }
                }

                node.config[key] = val;
                updateNodeDisplay(node);
            });
        });

        // Mode toggles (literal ↔ expression)
        document.querySelectorAll('#propBody .field-mode-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.key;
                const wasExpr = node.config._expressions[key] === true;
                node.config._expressions[key] = !wasExpr;
                // When switching to expression, convert non-string values
                if (!wasExpr && node.config[key] !== undefined && typeof node.config[key] !== 'string') {
                    node.config[key] = JSON.stringify(node.config[key]);
                }
                // When switching back to literal, parse JSON string back to array for options_list
                if (wasExpr) {
                    var _schema = NODE_REGISTRY[node.type]?.config_schema || [];
                    var _fld = _schema.find(function(f) { return f.key === key; });
                    if (_fld && _fld.type === 'options_list' && typeof node.config[key] === 'string') {
                        try { node.config[key] = JSON.parse(node.config[key]); } catch { /* keep string */ }
                    }
                }
                showNodeProperties(node);  // Re-render with new mode
            });
        });

        // Expression builder buttons
        document.querySelectorAll('#propBody .field-expr-builder').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.key;
                const reg = NODE_REGISTRY[node.type];
                const fieldDef = (reg?.config_schema || []).find(f => f.key === key);
                openExpressionBuilder(
                    node.config[key] || '',
                    fieldDef?.label || key,
                    (newVal) => {
                        node.config[key] = newVal;
                        updateNodeDisplay(node);
                        showNodeProperties(node);
                    }
                );
            });
        });

        // Variable insert buttons ({{}} braces)
        document.querySelectorAll('#propBody .btn-var-insert').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const key = btn.dataset.key;
                // Prefer sibling input inside input-group, else search the form-field-group
                const inputGrp = btn.closest('.input-group');
                const fieldGrp = btn.closest('.form-field-group');
                const input = inputGrp?.querySelector('.field-input')
                    || fieldGrp?.querySelector('.field-input, .field-expr-input');
                if (!input) return;
                const isExprMode = input.dataset.fieldType === 'expression';
                _showVarPickerForButton(btn, input, node.id, isExprMode);
            });
        });

        // Options list handlers (for menu-type fields)
        bindOptionsListEditors(node);

        // Key-value editor handlers
        bindKeyValueEditors(node);

        // Asynchronously populate connector_select / queue_select / flow_select dropdowns
        _populateConnectorSelects(node);
        _populateQueueSelects(node);
        _populateFlowSelects(node);
    }

    /** Bind options_list editors (add/remove/edit options) */
    function bindOptionsListEditors(node) {
        document.querySelectorAll('#propBody .options-list-editor').forEach(editor => {
            const key = editor.dataset.key;
            function readOptions() {
                const rows = editor.querySelectorAll('.opt-row');
                const opts = [];
                rows.forEach(row => {
                    opts.push({
                        key: row.querySelector('.opt-key').value,
                        text: row.querySelector('.opt-text').value,
                    });
                });
                node.config[key] = opts;
                updateNodeDisplay(node);
            }
            editor.querySelectorAll('.opt-key, .opt-text').forEach(el => {
                el.addEventListener('change', readOptions);
            });
            editor.querySelectorAll('.opt-remove').forEach(btn => {
                btn.addEventListener('click', () => {
                    btn.closest('.opt-row').remove();
                    readOptions();
                });
            });
            editor.querySelector('.opt-add')?.addEventListener('click', () => {
                const opts = node.config[key] || [];
                opts.push({ key: String(opts.length + 1), text: '' });
                node.config[key] = opts;
                showNodeProperties(node);  // Re-render
            });
        });
    }

    /** Bind key-value editors */
    function bindKeyValueEditors(node) {
        document.querySelectorAll('#propBody .kv-editor').forEach(editor => {
            const key = editor.dataset.key;
            function readKV() {
                const rows = editor.querySelectorAll('.kv-row');
                const obj = {};
                rows.forEach(row => {
                    const k = row.querySelector('.kv-k').value.trim();
                    const v = row.querySelector('.kv-v').value;
                    if (k) obj[k] = v;
                });
                node.config[key] = obj;
                updateNodeDisplay(node);
            }
            editor.querySelectorAll('.kv-k, .kv-v').forEach(el => {
                el.addEventListener('change', readKV);
            });
            editor.querySelectorAll('.kv-remove').forEach(btn => {
                btn.addEventListener('click', () => {
                    btn.closest('.kv-row').remove();
                    readKV();
                });
            });
            // {{}} insert buttons on each value field
            editor.querySelectorAll('.kv-var-insert').forEach(btn => {
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    const valInput = btn.closest('.kv-row')?.querySelector('.kv-v');
                    if (valInput) _showVarPickerForButton(btn, valInput, node.id, false);
                });
            });
            editor.querySelector('.kv-add')?.addEventListener('click', () => {
                const obj = node.config[key] || {};
                obj[''] = '';
                node.config[key] = obj;
                showNodeProperties(node);  // Re-render
            });
        });
    }

    // ───── Variable Picker ─────

    /**
     * Return all variables that are available *before* the given node in the flow,
     * by walking the edge graph backwards (BFS) and inspecting what each ancestor produces.
     * Returns [{name, source}] sorted alphabetically — only variables declared upstream.
     */
    function getAvailableVariables(forNodeId) {
        // Reverse adjacency: targetId → [sourceId]
        const incomingTo = {};
        edges.forEach(e => {
            if (!incomingTo[e.targetId]) incomingTo[e.targetId] = [];
            incomingTo[e.targetId].push(e.sourceId);
        });

        // BFS to collect all ancestor node IDs
        const visited = new Set();
        const toVisit = [forNodeId];
        while (toVisit.length) {
            const id = toVisit.shift();
            if (visited.has(id)) continue;
            visited.add(id);
            (incomingTo[id] || []).forEach(src => {
                if (!visited.has(src)) toVisit.push(src);
            });
        }
        visited.delete(forNodeId); // exclude the node itself

        const vars = [];
        const seen = new Set();
        const addVar = (name, source) => {
            if (name && !seen.has(name)) {
                seen.add(name);
                vars.push({ name, source });
            }
        };

        visited.forEach(id => {
            const n = nodes.find(nn => nn.id === id);
            if (!n) return;
            const lbl = n.label || n.type;
            switch (n.type) {
                case 'input':
                case 'dtmf':
                    addVar(n.config?.variable, lbl);
                    break;
                case 'menu':
                    addVar(n.config?.variable, lbl);
                    break;
                case 'set_variable':
                    if (Array.isArray(n.config?.fields)) {
                        n.config.fields.forEach(f => { if (f.name) addVar(f.name, lbl); });
                    }
                    break;
                case 'webhook':
                    addVar('webhook_status_code', lbl);
                    addVar('webhook_response', lbl);
                    break;
                case 'ai_bot':
                    addVar(n.config?.output_variable, lbl);
                    break;
                case 'sub_flow':
                    addVar(n.config?.output_variable, `Sub-flow: ${lbl}`);
                    break;
            }
        });

        return vars.sort((a, b) => a.name.localeCompare(b.name));
    }

    // Picker DOM + state
    let _pickerActive = false;
    let _pickerEl = null;
    let _pickerInput = null;

    function _getOrCreatePicker() {
        if (!_pickerEl) {
            _pickerEl = document.createElement('div');
            _pickerEl.id = 'varPicker';
            _pickerEl.className = 'var-picker';
            document.body.appendChild(_pickerEl);
            // Close when clicking outside
            document.addEventListener('mousedown', e => {
                if (_pickerActive && !_pickerEl.contains(e.target) && e.target !== _pickerInput) {
                    _hideVariablePicker();
                }
            }, true);
        }
        return _pickerEl;
    }

    function _showVariablePicker(inputEl, nodeId, filter, exprMode) {
        _pickerInput = inputEl;
        _pickerActive = true;

        const picker = _getOrCreatePicker();
        const allVars = getAvailableVariables(nodeId);
        const lcFilter = (filter || '').toLowerCase();
        const filtered = lcFilter
            ? allVars.filter(v => v.name.toLowerCase().includes(lcFilter))
            : allVars;

        if (filtered.length === 0) { _hideVariablePicker(); return; }

        picker.innerHTML = '<div class="var-picker-label">Insert variable</div><div class="var-picker-chips">' +
            filtered.map(v => `<button class="var-chip" data-varname="${v.name}" data-exprmode="${!!exprMode}" title="From: ${v.source}">${v.name}</button>`).join('') +
            '</div>';

        picker.querySelectorAll('.var-chip').forEach(btn => {
            btn.addEventListener('mousedown', e => {
                e.preventDefault();
                const useExpr = btn.dataset.exprmode === 'true';
                _insertVariable(inputEl, btn.dataset.varname, useExpr);
                _hideVariablePicker();
            });
        });

        picker.style.display = 'flex';
        _positionPicker(picker, inputEl);
    }

    /**
     * Show the variable picker anchored to a button element (button-click triggered).
     * Positions below/near the button. Shows ALL available vars without initial filter.
     */
    function _showVarPickerForButton(btnEl, inputEl, nodeId, exprMode) {
        _pickerInput = inputEl;
        _pickerActive = true;

        const picker = _getOrCreatePicker();
        const allVars = getAvailableVariables(nodeId);

        if (allVars.length === 0) {
            picker.innerHTML = '<span class="text-muted small px-2 py-1">No variables declared upstream yet</span>';
        } else {
            picker.innerHTML = '<div class="var-picker-label">Insert variable</div><div class="var-picker-chips">' +
                allVars.map(v => `<button class="var-chip" data-varname="${v.name}" data-exprmode="${!!exprMode}" title="From: ${v.source}">${v.name}</button>`).join('') +
                '</div>';
        }

        picker.querySelectorAll('.var-chip').forEach(chip => {
            chip.addEventListener('mousedown', e => {
                e.preventDefault();
                const useExpr = chip.dataset.exprmode === 'true';
                _insertVariable(inputEl, chip.dataset.varname, useExpr);
                _hideVariablePicker();
                inputEl.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });

        picker.style.display = 'flex';
        _positionPicker(picker, btnEl);
    }

    /**
     * Position the picker below (or above) anchorEl, clamped within the viewport.
     * Always left-aligns to the anchor's left edge, then right-clamps if needed.
     */
    function _positionPicker(picker, anchorEl) {
        picker.style.position = 'fixed';
        picker.style.left = '-9999px';   // off-screen so we can measure
        picker.style.top  = '-9999px';

        const rect    = anchorEl.getBoundingClientRect();
        const pw      = picker.offsetWidth  || 280;
        const ph      = picker.offsetHeight || 220;
        const vw      = window.innerWidth;
        const vh      = window.innerHeight;
        const gap     = 4;

        // Horizontal: left-align to anchor, clamp so we don't go off the right edge
        let left = rect.left;
        if (left + pw > vw - 8) {
            left = Math.max(8, vw - pw - 8);
        }

        // Vertical: prefer below, flip above if not enough room
        let top;
        if (rect.bottom + gap + ph <= vh) {
            top = rect.bottom + gap;
        } else if (rect.top - gap - ph >= 0) {
            top = rect.top - gap - ph;
        } else {
            // Not enough room either way — just clamp below inside viewport
            top = Math.max(8, vh - ph - 8);
        }

        picker.style.left = left + 'px';
        picker.style.top  = top  + 'px';
    }

    function _hideVariablePicker() {
        _pickerActive = false;
        if (_pickerEl) _pickerEl.style.display = 'none';
        _pickerInput = null;
    }

    /**
     * Insert {{varname}} (literal mode) or varname (expr mode) at the cursor.
     * Replaces any incomplete {{ prefix already typed.
     * @param {boolean} exprMode - If true, inserts bare name (for JSONata); otherwise wraps in {{}}
     */
    function _insertVariable(inputEl, varName, exprMode) {
        const val = inputEl.value;
        const pos = inputEl.selectionStart ?? val.length;
        const before = val.slice(0, pos);
        let newVal, newCursor;
        if (exprMode) {
            // In expression mode just insert the bare variable name at cursor
            newVal = before + varName + val.slice(pos);
            newCursor = before.length + varName.length;
        } else {
            const triggerIdx = before.lastIndexOf('{{');
            if (triggerIdx === -1) {
                newVal = val.slice(0, pos) + '{{' + varName + '}}' + val.slice(pos);
                newCursor = pos + varName.length + 4;
            } else {
                newVal = val.slice(0, triggerIdx) + '{{' + varName + '}}' + val.slice(pos);
                newCursor = triggerIdx + varName.length + 4;
            }
        }
        inputEl.value = newVal;
        inputEl.setSelectionRange(newCursor, newCursor);
        inputEl.dispatchEvent(new Event('change', { bubbles: true }));
    }

    /**
     * Detect '{{' typed in an input and show the variable picker.
     * Called from an 'input' event handler.
     */
    function _onVarInput(e, nodeId) {
        const el = e.target;
        const pos = el.selectionStart ?? el.value.length;
        const before = el.value.slice(0, pos);
        const triggerIdx = before.lastIndexOf('{{');
        // Hide if no open '{{' before cursor, or if it's already closed
        if (triggerIdx === -1 || before.indexOf('}}', triggerIdx) !== -1) {
            _hideVariablePicker();
            return;
        }
        const filter = before.slice(triggerIdx + 2);
        const isExprMode = el.dataset.fieldType === 'expression' || el.classList.contains('sf-expr-input');
        _showVariablePicker(el, nodeId, filter, isExprMode);
    }

    /**
     * Attach the {{ picker to all text/textarea inputs in #propBody for the given node.
     * Call this AFTER rendering the properties panel HTML.
     */
    function _attachVariablePickers(nodeId) {
        const propBody = document.getElementById('propBody');
        if (!propBody) return;
        const inputs = propBody.querySelectorAll(
            'input[data-field-type="string"], ' +
            'input[data-field-type="url"], ' +
            'input[data-field-type="expression"], ' +
            'textarea[data-field-type="textarea"], ' +
            'textarea.field-input, ' +
            '.kv-editor .kv-v, ' +
            '#sfFieldsList input.sf-val[type="text"], ' +
            '#sfFieldsList input.sf-expr-input'
        );
        inputs.forEach(el => {
            el.addEventListener('input', e => _onVarInput(e, nodeId));
            el.addEventListener('keydown', e => { if (e.key === 'Escape') _hideVariablePicker(); });
            el.addEventListener('blur', () => setTimeout(_hideVariablePicker, 160));
        });
    }

    // ───── JSONata Expression Builder ─────

    let _exprApplyCallback = null;

    /**
     * Open the JSONata Expression Builder modal.
     * @param {string} currentValue - Current expression value
     * @param {string} fieldLabel - Display label for the field
     * @param {Function} onApply - Callback(newValue) when user clicks Apply
     */
    function openExpressionBuilder(currentValue, fieldLabel, onApply) {
        _exprApplyCallback = onApply;
        document.getElementById('exprFieldName').textContent = fieldLabel;
        document.getElementById('exprInput').value = currentValue || '';
        document.getElementById('exprTestData').value = JSON.stringify(buildSampleContext(), null, 2);
        document.getElementById('exprResult').textContent = '';
        document.getElementById('exprResult').className = 'p-2 rounded border border-secondary expr-result-box';
        document.getElementById('exprStatus').textContent = '';

        // Populate flow variables panel in expression builder
        const varListEl = document.getElementById('exprVarList');
        if (varListEl) {
            const vars = _currentNodeId ? getAvailableVariables(_currentNodeId) : [];
            if (vars.length === 0) {
                varListEl.innerHTML = '<span class="text-muted" style="font-size:.75rem">No variables declared upstream</span>';
            } else {
                varListEl.innerHTML = vars.map(v =>
                    `<button class="var-chip" data-varname="${v.name}" title="From: ${v.source}">${v.name}</button>`
                ).join('');
                varListEl.querySelectorAll('.var-chip').forEach(chip => {
                    chip.addEventListener('click', () => {
                        const inp = document.getElementById('exprInput');
                        _insertVariable(inp, chip.dataset.varname, true);
                        inp.focus();
                    });
                });
            }
        }

        new bootstrap.Modal(document.getElementById('exprBuilderModal')).show();
    }

    /** Populate all queue_select dropdowns in the open properties panel */
    async function _populateQueueSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="queue_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/queues');
            const queues = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const key = sel.dataset.key;
                const currentVal = node.config[key] || '';
                sel.innerHTML = '<option value="">&mdash; Select queue &mdash;</option>';
                queues.forEach(q => {
                    const opt = document.createElement('option');
                    opt.value = q.id;
                    const campaignHint = q.campaign_id ? '' : ' \u26a0 no campaign';
                    opt.textContent = q.name + ' (' + q.channel + ')' + campaignHint;
                    if (q.id === currentVal) opt.selected = true;
                    sel.appendChild(opt);
                });
                // Show campaign hint beneath select
                if (currentVal) {
                    const q = queues.find(q => q.id === currentVal);
                    const parent = sel.closest('.form-field-group');
                    if (parent && !parent.querySelector('.queue-hint')) {
                        const hint = document.createElement('div');
                        hint.className = 'queue-hint mt-1 small';
                        if (q?.campaign_id) {
                            hint.innerHTML = '<span class="text-success"><i class="bi bi-check-circle me-1"></i>Auto-dispatch enabled via campaign</span>';
                        } else {
                            hint.innerHTML = '<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>No campaign linked – broadcast to all agents</span>';
                        }
                        parent.appendChild(hint);
                    }
                }
            });
        } catch (e) {
            // silently ignore
        }
    }

    /** Populate all flow_select dropdowns in the open properties panel */
    async function _populateFlowSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="flow_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/flows');
            const flows = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const key = sel.dataset.key;
                const currentVal = node.config[key] || '';
                sel.innerHTML = '<option value="">&mdash; Select flow &mdash;</option>';
                flows.forEach(f => {
                    const opt = document.createElement('option');
                    opt.value = f.id;
                    opt.textContent = f.name + (f.is_active ? '' : ' (draft)');
                    if (String(f.id) === String(currentVal)) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        } catch (e) {
            // silently ignore
        }
    }

    /** Populate all connector_select dropdowns in the open properties panel */
    async function _populateConnectorSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="connector_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/connectors');
            const connectors = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const key = sel.dataset.key;
                const currentVal = node.config[key] || '';
                sel.innerHTML = '<option value="">\u2014 None (unlinked) \u2014</option>';
                connectors.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name + (c.is_active ? '' : ' (inactive)');
                    if (c.id === currentVal) opt.selected = true;
                    sel.appendChild(opt);
                });
                // Show meta field info beneath select
                if (currentVal) {
                    const conn = connectors.find(c => c.id === currentVal);
                    if (conn?.meta_fields?.length) {
                        const parent = sel.closest('.form-field-group');
                        if (parent && !parent.querySelector('.connector-meta-hint')) {
                            const hint = document.createElement('div');
                            hint.className = 'connector-meta-hint mt-1 small text-info';
                            const varList = conn.meta_fields
                                .filter(mf => mf.map_to_variable)
                                .map(mf => '<code>' + mf.map_to_variable + '</code>')
                                .join(', ');
                            hint.innerHTML = '<i class="bi bi-info-circle me-1"></i>Variables injected: ' + (varList || 'none');
                            parent.appendChild(hint);
                        }
                    }
                }
            });
        } catch (e) {
            // silently ignore network errors in designer
        }
    }

    /** Build a sample context object from available flow variables for testing */
    function buildSampleContext() {
        const ctx = {
            flow: {},
            contact: { name: 'John Doe', phone: '+27821234567', email: 'john@example.com' },
            system: { timestamp: new Date().toISOString(), channel: 'chat' }
        };
        nodes.forEach(n => {
            if (n.type === 'set_variable' && Array.isArray(n.config?.fields)) {
                n.config.fields.forEach(f => {
                    if (f.name) ctx.flow[f.name] = f.value ?? '';
                });
            }
            if (n.type === 'input' && n.config?.variable) {
                ctx.flow[n.config.variable] = '<user_input>';
            }
            if (n.type === 'http_request' && n.config?.response_var) {
                ctx.flow[n.config.response_var] = { status: 200, body: {} };
            }
        });
        return ctx;
    }

    // Expression builder: Evaluate button
    document.getElementById('exprEvaluate')?.addEventListener('click', async () => {
        const expr = document.getElementById('exprInput').value.trim();
        const resultEl = document.getElementById('exprResult');
        const statusEl = document.getElementById('exprStatus');
        resultEl.textContent = '';
        statusEl.textContent = '';

        if (!expr) { resultEl.textContent = '(empty expression)'; return; }

        let testData;
        try {
            testData = JSON.parse(document.getElementById('exprTestData').value);
        } catch {
            resultEl.textContent = '\u274c Invalid test data JSON';
            resultEl.className = 'p-2 rounded border border-danger expr-result-box text-danger';
            return;
        }

        try {
            if (typeof jsonata === 'function') {
                const expression = jsonata(expr);
                const result = await expression.evaluate(testData);
                resultEl.textContent = result === undefined ? '(undefined)' :
                    (typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result));
                resultEl.className = 'p-2 rounded border border-success expr-result-box text-success';
                statusEl.textContent = '\u2705 Evaluated OK';
            } else {
                resultEl.textContent = '\u26a0\ufe0f JSONata library not loaded';
                resultEl.className = 'p-2 rounded border border-warning expr-result-box text-warning';
            }
        } catch (err) {
            resultEl.textContent = '\u274c ' + err.message;
            resultEl.className = 'p-2 rounded border border-danger expr-result-box text-danger';
            statusEl.textContent = 'Parse error';
        }
    });

    // Expression builder: Apply button
    document.getElementById('exprApply')?.addEventListener('click', () => {
        if (_exprApplyCallback) {
            _exprApplyCallback(document.getElementById('exprInput').value);
            _exprApplyCallback = null;
        }
        bootstrap.Modal.getInstance(document.getElementById('exprBuilderModal'))?.hide();
    });

    // ───── Set Fields (set_variable) – Rich typed-field system ─────

    const FIELD_TYPES = [
        { value: 'string',        label: 'String' },
        { value: 'number',        label: 'Number' },
        { value: 'boolean',       label: 'Boolean' },
        { value: 'date',          label: 'Date' },
        { value: 'relative_date', label: 'Relative Date' },
        { value: 'array',         label: 'Array' },
    ];

    /** Migrate legacy set_variable config (single variable/value) → fields[] */
    function ensureFieldsArray(node) {
        if (!Array.isArray(node.config.fields)) {
            const legacy = [];
            if (node.config.variable) {
                legacy.push({ name: node.config.variable, type: 'string', value: node.config.value || '', input_mode: 'text' });
            }
            node.config.fields = legacy.length ? legacy : [{ name: '', type: 'string', value: '', input_mode: 'text' }];
        }
        // Ensure every field has input_mode; migrate old json_parse → string+expression
        node.config.fields.forEach(f => {
            if (!f.input_mode) f.input_mode = 'text';
            if (f.type === 'json_parse') {
                f.type = 'string';
                f.input_mode = 'expression';
            }
        });
    }

    /** Try to parse a string as JSON; return parsed value or null on failure */
    function tryParseJson(str) {
        if (typeof str !== 'string') return null;
        const trimmed = str.trim();
        if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
            try { return JSON.parse(trimmed); } catch { return null; }
        }
        return null;
    }

    /** Produce a safe display string for a field value */
    function fieldValueDisplay(field) {
        const prefix = field.input_mode === 'expression' ? '⚡' : '';
        if (field.type === 'boolean') return prefix + (field.value ? 'true' : 'false');
        if (field.type === 'relative_date') {
            const v = field.value || {};
            return prefix + `${v.direction || '+'}${v.amount || 0} ${v.unit || 'days'}`;
        }
        if (field.type === 'array') {
            return prefix + (Array.isArray(field.value) ? JSON.stringify(field.value) : String(field.value || '[]'));
        }
        return prefix + String(field.value ?? '');
    }

    /** Render the value-input HTML for one field row depending on its type */
    function fieldValueInput(field, idx) {
        const esc = (v) => String(v ?? '').replace(/"/g, '&quot;');
        const mode = field.input_mode || 'text';
        const isExpr = mode === 'expression';

        // Mode toggle button
        const modeBtn = `<button class="btn btn-sm sf-mode-toggle ${isExpr ? 'sf-mode-expr' : 'sf-mode-text'}" data-idx="${idx}" title="${isExpr ? 'Expression (JSONata) – click for Text' : 'Text (literal) – click for Expression'}">
            ${isExpr ? '<i class="bi bi-lightning-charge-fill"></i>' : '<i class="bi bi-fonts"></i>'}
        </button>`;

        // If expression mode, always show a single text input for the JSONata expression
        if (isExpr) {
            return `<div class="d-flex gap-1 align-items-start">
                ${modeBtn}
                <input type="text" class="form-control form-control-sm sf-val sf-expr-input flex-fill" data-idx="${idx}" value="${esc(field.value)}" placeholder="JSONata expression">
                <button class="btn btn-sm btn-outline-secondary sf-var-insert" data-idx="${idx}" title="Insert variable reference">
                    <i class="bi bi-braces"></i>
                </button>
                <button class="btn btn-sm btn-outline-warning sf-expr-builder" data-idx="${idx}" title="Expression Builder">
                    <i class="bi bi-tools"></i>
                </button>
            </div>`;
        }

        // Text mode – type-specific widget
        let widget;
        switch (field.type) {
            case 'string':
                widget = `<div class="input-group input-group-sm">
                    <input type="text" class="form-control sf-val" data-idx="${idx}" value="${esc(field.value)}" placeholder="Value or {{variable}}">
                    <button class="btn btn-outline-secondary sf-var-insert" type="button" data-idx="${idx}" title="Insert {{variable}}"><i class="bi bi-braces"></i></button>
                </div>`;
                break;
            case 'number':
                widget = `<input type="number" class="form-control form-control-sm sf-val" data-idx="${idx}" step="any" value="${esc(field.value)}">`;
                break;
            case 'boolean':
                widget = `<select class="form-select form-select-sm sf-val" data-idx="${idx}">
                    <option value="true"  ${field.value === true  || field.value === 'true'  ? 'selected' : ''}>true</option>
                    <option value="false" ${field.value === false || field.value === 'false' ? 'selected' : ''}>false</option>
                </select>`;
                break;
            case 'date':
                widget = `<input type="date" class="form-control form-control-sm sf-val" data-idx="${idx}" value="${esc(field.value)}">`;
                break;
            case 'relative_date': {
                const v = (typeof field.value === 'object' && field.value) ? field.value : { direction: '+', amount: 0, unit: 'days' };
                widget = `<div class="d-flex gap-1 align-items-center sf-reldate" data-idx="${idx}">
                    <select class="form-select form-select-sm sf-rd-dir" style="width:60px">
                        <option value="+" ${v.direction === '+' ? 'selected' : ''}>+</option>
                        <option value="-" ${v.direction === '-' ? 'selected' : ''}>−</option>
                    </select>
                    <input type="number" class="form-control form-control-sm sf-rd-amt" style="width:70px" value="${v.amount || 0}" min="0">
                    <select class="form-select form-select-sm sf-rd-unit">
                        <option value="seconds" ${v.unit === 'seconds' ? 'selected' : ''}>sec</option>
                        <option value="minutes" ${v.unit === 'minutes' ? 'selected' : ''}>min</option>
                        <option value="hours"   ${v.unit === 'hours'   ? 'selected' : ''}>hrs</option>
                        <option value="days"    ${v.unit === 'days'    ? 'selected' : ''}>days</option>
                    </select>
                </div>`;
                break;
            }
            case 'array':
                widget = `<textarea class="form-control form-control-sm sf-val" data-idx="${idx}" rows="2" placeholder='["a","b"] or comma-separated'>${esc(Array.isArray(field.value) ? JSON.stringify(field.value) : field.value)}</textarea>`;
                break;
            default:
                widget = `<div class="input-group input-group-sm">
                    <input type="text" class="form-control sf-val" data-idx="${idx}" value="${esc(field.value)}" placeholder="Value or {{variable}}">
                    <button class="btn btn-outline-secondary sf-var-insert" type="button" data-idx="${idx}" title="Insert {{variable}}"><i class="bi bi-braces"></i></button>
                </div>`;
        }

        return `<div class="d-flex gap-1 align-items-start">
            ${modeBtn}
            <div class="flex-fill">${widget}</div>
        </div>`;
    }

    /** Render a single field row (collapsed or expanded) */
    function renderFieldRow(f, idx) {
        const esc = (v) => String(v ?? '').replace(/"/g, '&quot;');
        const isEditing = f._editing;

        if (isEditing) {
            // ─── Expanded edit form ───
            const typeOpts = FIELD_TYPES.map(t =>
                `<option value="${t.value}" ${f.type === t.value ? 'selected' : ''}>${t.label}</option>`
            ).join('');
            return `
                <div class="sf-row sf-row-edit border rounded p-2 mb-2" data-idx="${idx}">
                    <div class="d-flex gap-1 mb-2">
                        <input type="text" class="form-control form-control-sm sf-name flex-fill" data-idx="${idx}"
                               placeholder="Variable name" value="${esc(f.name)}">
                        <select class="form-select form-select-sm sf-type" data-idx="${idx}" style="width:110px">
                            ${typeOpts}
                        </select>
                    </div>
                    <div class="sf-value-wrap mb-2" data-idx="${idx}">
                        ${fieldValueInput(f, idx)}
                    </div>
                    <div class="d-flex gap-1 justify-content-end">
                        <button class="btn btn-sm btn-outline-success sf-done" data-idx="${idx}" title="Done">
                            <i class="bi bi-check-lg"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger sf-remove" data-idx="${idx}" title="Delete field">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </div>
            `;
        }

        // ─── Collapsed summary ───
        const typeBadge = `<span class="badge bg-secondary sf-type-badge">${f.type}</span>`;
        const modeIcon = f.input_mode === 'expression' ? '<i class="bi bi-lightning-charge-fill text-warning me-1" title="Expression"></i>' : '';
        const valDisplay = fieldValueDisplay(f).replace(/^⚡/, '');  // strip prefix; we show icon instead
        const valSummary = valDisplay.length > 28 ? valDisplay.substring(0, 28) + '…' : valDisplay;
        return `
            <div class="sf-row sf-row-summary border rounded px-2 py-1 mb-1 d-flex align-items-center gap-1" data-idx="${idx}">
                <span class="sf-summary-name text-truncate" title="${esc(f.name)}">${f.name || '<em class="text-muted">unnamed</em>'}</span>
                <span class="text-muted">=</span>
                ${modeIcon}
                <span class="sf-summary-val text-truncate text-muted" title="${esc(valDisplay)}">${valSummary || '<em>empty</em>'}</span>
                ${typeBadge}
                <span class="ms-auto d-flex gap-1 flex-shrink-0">
                    <button class="btn btn-sm btn-link text-info p-0 sf-edit" data-idx="${idx}" title="Edit"><i class="bi bi-pencil-square"></i></button>
                    <button class="btn btn-sm btn-link text-danger p-0 sf-remove" data-idx="${idx}" title="Delete"><i class="bi bi-trash"></i></button>
                </span>
            </div>
        `;
    }

    /** Render the full set-fields panel HTML */
    function renderSetFieldsPanel(node) {
        ensureFieldsArray(node);
        const fields = node.config.fields;
        let rows = '';
        fields.forEach((f, idx) => {
            rows += renderFieldRow(f, idx);
        });

        return `
            <label class="form-label fw-semibold">Fields</label>
            <div id="sfFieldsList">${rows}</div>
            <button class="btn btn-sm btn-outline-secondary w-100 mt-1" id="sfAddField">
                <i class="bi bi-plus me-1"></i>Add Field
            </button>
        `;
    }

    /** Bind events for the set-fields panel */
    function bindSetFieldsPanel(node) {
        ensureFieldsArray(node);

        function syncAndRedraw() {
            updateNodeDisplay(node);
            const container = document.getElementById('sfFieldsList');
            if (container) {
                let rows = '';
                node.config.fields.forEach((f, idx) => {
                    rows += renderFieldRow(f, idx);
                });
                container.innerHTML = rows;
                attachRowListeners();
            }
        }

        function readValue(idx) {
            const field = node.config.fields[idx];
            if (!field) return;

            // Expression mode – always store raw string (JSONata expression)
            if (field.input_mode === 'expression') {
                const el = document.querySelector(`.sf-val[data-idx="${idx}"]`);
                if (el) field.value = el.value;
                return;
            }

            // Relative date – composite widget
            if (field.type === 'relative_date') {
                const wrap = document.querySelector(`.sf-reldate[data-idx="${idx}"]`);
                if (wrap) {
                    field.value = {
                        direction: wrap.querySelector('.sf-rd-dir').value,
                        amount: parseInt(wrap.querySelector('.sf-rd-amt').value, 10) || 0,
                        unit: wrap.querySelector('.sf-rd-unit').value,
                    };
                }
                return;
            }

            const el = document.querySelector(`.sf-val[data-idx="${idx}"]`);
            if (!el) return;
            let raw = el.value;

            switch (field.type) {
                case 'boolean':
                    field.value = raw === 'true';
                    break;
                case 'number':
                    field.value = parseFloat(raw) || 0;
                    break;
                case 'array':
                    // try JSON array first, then split by comma
                    try {
                        const parsed = JSON.parse(raw);
                        field.value = Array.isArray(parsed) ? parsed : [parsed];
                    } catch {
                        field.value = raw.split(',').map(s => s.trim()).filter(Boolean);
                    }
                    break;
                default: // string, date
                    field.value = raw;
            }
        }

        function attachRowListeners() {
            // ─── Summary row: Edit buttons ───
            document.querySelectorAll('#sfFieldsList .sf-edit').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.idx, 10);
                    node.config.fields[idx]._editing = true;
                    syncAndRedraw();
                });
            });

            // ─── Edit row: Done buttons ───
            document.querySelectorAll('#sfFieldsList .sf-done').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.idx, 10);
                    readValue(idx);
                    delete node.config.fields[idx]._editing;
                    syncAndRedraw();
                });
            });

            // Name inputs (only in edit rows)
            document.querySelectorAll('#sfFieldsList .sf-name').forEach(el => {
                el.addEventListener('change', () => {
                    const idx = parseInt(el.dataset.idx, 10);
                    node.config.fields[idx].name = el.value;
                    updateNodeDisplay(node);
                });
            });

            // Type selectors — when type changes, reset value and redraw the value input
            document.querySelectorAll('#sfFieldsList .sf-type').forEach(el => {
                el.addEventListener('change', () => {
                    const idx = parseInt(el.dataset.idx, 10);
                    const newType = el.value;
                    const field = node.config.fields[idx];
                    field.type = newType;
                    // Reset value to sensible default
                    switch (newType) {
                        case 'boolean':       field.value = false; break;
                        case 'number':        field.value = 0; break;
                        case 'array':         field.value = []; break;
                        case 'relative_date': field.value = { direction: '+', amount: 0, unit: 'days' }; break;
                        case 'date':          field.value = new Date().toISOString().slice(0, 10); break;
                        default:              field.value = '';
                    }
                    syncAndRedraw();
                });
            });

            // Value inputs — save on both change and input events
            document.querySelectorAll('#sfFieldsList .sf-val').forEach(el => {
                el.addEventListener('change', () => readValue(parseInt(el.dataset.idx, 10)));
                el.addEventListener('input', () => readValue(parseInt(el.dataset.idx, 10)));
            });

            // Mode toggle buttons (text ↔ expression)
            document.querySelectorAll('#sfFieldsList .sf-mode-toggle').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.idx, 10);
                    const field = node.config.fields[idx];
                    // Capture current input value BEFORE switching mode
                    readValue(idx);
                    field.input_mode = field.input_mode === 'expression' ? 'text' : 'expression';
                    // When switching to expression, ensure value is a string
                    if (field.input_mode === 'expression' && typeof field.value !== 'string') {
                        field.value = JSON.stringify(field.value);
                    }
                    syncAndRedraw();
                });
            });

            // Relative date composite listeners
            document.querySelectorAll('#sfFieldsList .sf-reldate').forEach(wrap => {
                wrap.querySelectorAll('select, input').forEach(el => {
                    el.addEventListener('change', () => readValue(parseInt(wrap.dataset.idx, 10)));
                });
            });

            // Remove buttons (in both summary and edit rows)
            document.querySelectorAll('#sfFieldsList .sf-remove').forEach(el => {
                el.addEventListener('click', () => {
                    const idx = parseInt(el.dataset.idx, 10);
                    node.config.fields.splice(idx, 1);
                    if (node.config.fields.length === 0) {
                        node.config.fields.push({ name: '', type: 'string', value: '', input_mode: 'text', _editing: true });
                    }
                    syncAndRedraw();
                });
            });

            // Expression builder buttons (in set_variable expression mode)
            document.querySelectorAll('#sfFieldsList .sf-expr-builder').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.idx, 10);
                    const field = node.config.fields[idx];
                    openExpressionBuilder(
                        field.value || '',
                        field.name || 'Field ' + (idx + 1),
                        (newVal) => {
                            field.value = newVal;
                            syncAndRedraw();
                        }
                    );
                });
            });

            // Variable insert buttons ({{}} braces) — in set_variable rows
            document.querySelectorAll('#sfFieldsList .sf-var-insert').forEach(btn => {
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    const isExprRow = !!btn.closest('.d-flex')?.querySelector('.sf-expr-input');
                    const valInput = btn.closest('.input-group, .d-flex')?.querySelector('.sf-val, .sf-expr-input');
                    if (valInput) _showVarPickerForButton(btn, valInput, node.id, isExprRow);
                });
            });
        }

        // Add field button – new fields start in edit mode
        document.getElementById('sfAddField')?.addEventListener('click', () => {
            node.config.fields.push({ name: '', type: 'string', value: '', input_mode: 'text', _editing: true });
            syncAndRedraw();
        });

        // Initial attachment
        attachRowListeners();
    }

    function updateNodeDisplay(node) {
        if (!node.el) return;
        const body = node.el.querySelector('.node-body');
        if (body) {
            let displayText = node.label || node.type;
            if (node.type === 'message' && node.config.text) {
                displayText = node.config.text.substring(0, 40) + (node.config.text.length > 40 ? '...' : '');
            }
            if (node.type === 'set_variable' && Array.isArray(node.config.fields)) {
                const names = node.config.fields.map(f => f.name).filter(Boolean);
                if (names.length) displayText = names.join(', ');
            }
            body.textContent = displayText;
        }
    }

    // ───── CRUD helpers ─────

    function addNode(type, x, y, label = '', config = {}, dbId = null) {
        const id = dbId || ('temp_' + nextTempId++);
        const node = { id, type, label: label || type.replace(/_/g, ' '), x, y, config, el: null };
        nodes.push(node);
        createNodeElement(node);
        return node;
    }

    function deleteNode(node) {
        edges = edges.filter(e => e.sourceId !== node.id && e.targetId !== node.id);
        node.el?.remove();
        nodes = nodes.filter(n => n.id !== node.id);
        renderEdges();
        deselectAll();
    }

    function addEdge(sourceId, targetId, sourceHandle = 'default', label = '', condition = null, dbId = null) {
        // Prevent duplicates
        if (edges.find(e => e.sourceId === sourceId && e.targetId === targetId && e.sourceHandle === sourceHandle)) return;
        // Enforce one edge per output port – remove any existing edge from same source+handle
        const existing = edges.find(e => e.sourceId === sourceId && e.sourceHandle === sourceHandle);
        if (existing) {
            edges = edges.filter(e => e !== existing);
            showToast('Replaced previous connection from that port', 'info');
        }
        const id = dbId || ('edge_' + nextTempId++);
        edges.push({ id, sourceId, targetId, sourceHandle, label, condition });
        renderEdges();
    }

    // ───── Drag from palette ─────

    let paletteDropType = null;

    function bindPaletteNodes() {
        document.querySelectorAll('.palette-node').forEach(el => {
            el.addEventListener('dragstart', (e) => {
                paletteDropType = el.dataset.type;
                e.dataTransfer.effectAllowed = 'copy';
            });
        });
    }

    container.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    });

    container.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!paletteDropType) return;
        const rect = container.getBoundingClientRect();
        const x = (e.clientX - rect.left - panX) / zoom;
        const y = (e.clientY - rect.top - panY) / zoom;
        addNode(paletteDropType, x, y);
        paletteDropType = null;
    });

    // ───── Keyboard ─────

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Delete' || e.key === 'Backspace') {
            if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;
            if (selectedNode) {
                deleteNode(selectedNode);
            }
            if (selectedEdge) {
                edges = edges.filter(ed => ed.id !== selectedEdge);
                renderEdges();
                deselectAll();
            }
        }
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            saveFlow();
        }
    });

    // ───── Save / Load ─────

    async function saveFlow() {
        if (!flowId) return;
        const body = {
            nodes: nodes.map((n, idx) => {
                // Strip UI-only _editing flags from set_variable fields before saving
                const config = { ...n.config, _clientId: String(n.id), _dbId: String(n.id) };
                if (Array.isArray(config.fields)) {
                    config.fields = config.fields.map(f => {
                        const { _editing, ...rest } = f;
                        return rest;
                    });
                }
                return { node_type: n.type, label: n.label, position_x: n.x, position_y: n.y, position: idx, config };
            }),
            edges: edges.map(e => ({
                source_node_id: e.sourceId,
                target_node_id: e.targetId,
                source_handle: e.sourceHandle,
                label: e.label || '',
                condition: e.condition,
                priority: 0,
            })),
        };
        try {
            const res = await apiFetch(`/api/v1/flows/${flowId}/designer`, { method: 'PUT', body });
            if (res && res.ok) {
                const data = await res.json();
                showToast('Flow saved (v' + data.version + ')', 'success');
                document.getElementById('flowVersion').textContent = 'v' + data.version;
                // Reload to get real IDs
                await loadFlow(flowId);
            } else {
                showToast('Save failed', 'danger');
            }
        } catch (err) {
            showToast('Save error: ' + err.message, 'danger');
        }
    }

    async function loadFlow(id) {
        try {
            const res = await apiFetch(`/api/v1/flows/${id}`);
            if (!res || !res.ok) { showToast('Flow not found', 'danger'); return; }
            const data = await res.json();
            flowId = data.id;
            flowData = data;
            document.getElementById('flowName').textContent = data.name;
            document.getElementById('flowVersion').textContent = 'v' + data.version;

            // Clear canvas
            canvas.innerHTML = '';
            nodes = [];
            edges = [];

            // Load nodes
            (data.nodes || []).forEach(n => {
                addNode(n.node_type, n.position_x, n.position_y, n.label, n.config || {}, n.id);
            });

            // Load edges
            (data.edges || []).forEach(e => {
                addEdge(e.source_node_id, e.target_node_id, e.source_handle, e.label, e.condition, e.id);
            });

            fitView();
        } catch (err) {
            console.error('Load flow error:', err);
        }
    }

    // ───── Publish ─────

    document.getElementById('btnPublish').addEventListener('click', async () => {
        if (!flowId) return;
        await saveFlow();
        try {
            const res = await apiFetch(`/api/v1/flows/${flowId}/publish`, { method: 'POST' });
            if (res && res.ok) {
                showToast('Flow published!', 'success');
            } else {
                const err = await res.json();
                showToast(err.detail || 'Publish failed', 'warning');
            }
        } catch (err) {
            showToast('Publish error', 'danger');
        }
    });

    document.getElementById('btnSave').addEventListener('click', () => saveFlow());

    // ───── Flow list / New flow ─────

    document.getElementById('btnNewFlow')?.addEventListener('click', () => {
        bootstrap.Modal.getInstance(document.getElementById('flowListModal'))?.hide();
        new bootstrap.Modal(document.getElementById('newFlowModal')).show();
    });

    document.getElementById('btnCreateFlow')?.addEventListener('click', async () => {
        const name = document.getElementById('newFlowName').value.trim();
        if (!name) return;
        const channel = document.getElementById('newFlowChannel').value || null;
        const desc = document.getElementById('newFlowDesc').value.trim() || null;
        try {
            const res = await apiFetch('/api/v1/flows', { method: 'POST', body: { name, channel, description: desc } });
            if (res && res.ok) {
                const data = await res.json();
                bootstrap.Modal.getInstance(document.getElementById('newFlowModal'))?.hide();
                flowId = data.id;
                await loadFlow(data.id);
                showToast('Flow created', 'success');
            }
        } catch (err) {
            showToast('Create error', 'danger');
        }
    });

    async function showFlowList() {
        const listEl = document.getElementById('flowListItems');
        listEl.innerHTML = '<p class="text-muted">Loading...</p>';
        new bootstrap.Modal(document.getElementById('flowListModal')).show();
        try {
            const res = await apiFetch('/api/v1/flows');
            if (res && res.ok) {
                const flows = await res.json();
                if (flows.length === 0) {
                    listEl.innerHTML = '<p class="text-muted">No flows yet</p>';
                } else {
                    listEl.innerHTML = flows.map(f => `
                        <div class="d-flex justify-content-between align-items-center py-2 border-bottom border-dark">
                            <a href="#" class="text-decoration-none flow-list-item" data-id="${f.id}">${f.name}</a>
                            <span class="badge ${f.is_active ? 'bg-success' : 'bg-secondary'}">${f.is_active ? 'Active' : 'Draft'}</span>
                        </div>
                    `).join('');
                    listEl.querySelectorAll('.flow-list-item').forEach(a => {
                        a.addEventListener('click', (e) => {
                            e.preventDefault();
                            bootstrap.Modal.getInstance(document.getElementById('flowListModal'))?.hide();
                            loadFlow(a.dataset.id);
                        });
                    });
                }
            }
        } catch (err) {
            listEl.innerHTML = '<p class="text-danger">Error loading flows</p>';
        }
    }

    // ───── Toast ─────

    function showToast(msg, type = 'info') {
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-bg-${type} border-0`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `<div class="d-flex"><div class="toast-body">${msg}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
        container.appendChild(toast);
        new bootstrap.Toast(toast, { delay: 3000 }).show();
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    // ───── Node Type Registry ─────

    async function loadNodeTypeRegistry() {
        try {
            const res = await apiFetch('/api/v1/node-types?_=' + Date.now());
            if (!res || !res.ok) return;
            const types = await res.json();

            // Populate NODE_REGISTRY & NODE_ICONS
            types.forEach(t => {
                NODE_REGISTRY[t.key] = t;
                NODE_ICONS[t.key] = t.icon || 'bi-puzzle';
            });

            // Build palette grouped by category
            const groups = {};
            types.forEach(t => {
                if (!groups[t.category]) groups[t.category] = [];
                groups[t.category].push(t);
            });

            const paletteEl = document.getElementById('paletteGroups');
            paletteEl.innerHTML = '';
            for (const [cat, items] of Object.entries(groups)) {
                let groupHtml = `<div class="palette-group"><div class="palette-label">${cat}</div>`;
                items.forEach(t => {
                    groupHtml += `<div class="palette-node" draggable="true" data-type="${t.key}"><i class="bi ${t.icon}"></i> ${t.label}</div>`;
                });
                groupHtml += '</div>';
                paletteEl.innerHTML += groupHtml;
            }

            // Bind drag events on newly created palette nodes
            bindPaletteNodes();

            // Inject dynamic CSS for custom node type header colors
            let customCSS = '';
            types.forEach(t => {
                if (!t.is_builtin && t.color) {
                    customCSS += `.flow-node[data-type="${t.key}"] .node-header { background: ${t.color}; color: #fff; }\n`;
                }
            });
            if (customCSS) {
                const style = document.createElement('style');
                style.textContent = customCSS;
                document.head.appendChild(style);
            }
        } catch (err) {
            console.warn('Failed to load node type registry:', err);
            // Fall back — palette stays with whatever HTML was there
        }
    }

    // ───── Flow Simulator UI ─────

    function initTestPanel() {
        // Build context pre-fill from current variable set
        const sampleCtx = buildSampleContext();
        const ctxInput = document.getElementById('testContextInput');
        if (ctxInput) {
            // Only set placeholder-like guidance, not override user edits
            if (!ctxInput.value || ctxInput.value === '{}') {
                ctxInput.value = JSON.stringify(sampleCtx, null, 2);
            }
        }

        // Build per-node input fields for input / menu / dtmf nodes
        const container = document.getElementById('testNodeInputs');
        if (!container) return;
        container.innerHTML = '';

        const interactiveTypes = ['input', 'menu', 'dtmf'];
        const interactiveNodes = nodes.filter(n => interactiveTypes.includes(n.type));

        if (interactiveNodes.length === 0) {
            container.innerHTML = '<p class="text-muted small mb-0">No input nodes found in this flow.</p>';
            return;
        }

        interactiveNodes.forEach(n => {
            const label = n.config?.prompt || n.label || n.type;
            const varName = n.config?.variable || n.config?.result_var || 'response';

            const group = document.createElement('div');
            group.className = 'mb-3';
            group.innerHTML = `
                <label class="form-label small fw-semibold">${escapeHtml(label)} <span class="text-muted">(→ ${escapeHtml(varName)})</span></label>
                <input type="text" class="form-control form-control-sm test-node-input" data-node-id="${n.id}" data-var="${escapeHtml(varName)}" placeholder="Simulated user input…">
            `;
            container.appendChild(group);
        });
    }

    async function runSimulation() {
        // Parse context
        let context = {};
        const ctxRaw = document.getElementById('testContextInput')?.value?.trim();
        if (ctxRaw) {
            try { context = JSON.parse(ctxRaw); } catch (e) {
                alert('Context JSON is invalid: ' + e.message);
                return;
            }
        }

        // Collect node inputs
        const inputs = {};
        document.querySelectorAll('.test-node-input').forEach(el => {
            const nid = el.dataset.nodeId;
            if (nid && el.value.trim()) inputs[nid] = el.value.trim();
        });

        // UI: loading
        const btn = document.getElementById('btnRunSim');
        if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running…'; }

        try {
            const httpResp = await apiFetch(`/api/v1/flows/${flowId}/simulate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ context, inputs })
            });

            if (!httpResp || !httpResp.ok) {
                const errText = httpResp ? await httpResp.text() : 'No response';
                throw new Error(`Server error ${httpResp?.status}: ${errText}`);
            }

            const data = await httpResp.json();

            clearSimHighlights();
            renderTrace(data.trace || []);
            renderFinalContext(data.final_context || {});
            highlightSimNodes(data.trace || []);

            // Reset label to final
            const lbl = document.getElementById('testFinalVarsLabel');
            if (lbl) lbl.textContent = 'Final Variables (click a row above to inspect any step)';

            // Status banner
            const banner = document.getElementById('testStatusBanner');
            if (banner) {
                const colorMap = { completed: 'success', blocked: 'warning', max_steps: 'info', error: 'danger' };
                const color = colorMap[data.status] || 'secondary';
                banner.className = `alert alert-${color} py-2 mb-2 small`;
                banner.innerHTML = `<strong>${(data.status || 'unknown').toUpperCase()}</strong>${data.message ? ' — ' + escapeHtml(data.message) : ''}`;
                banner.classList.remove('d-none');
            }
        } catch (err) {
            alert('Simulation failed: ' + err.message);
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '▶ Run'; }
        }
    }

    function renderTrace(trace) {
        const tbody = document.getElementById('testTraceBody');
        const container = document.getElementById('testTraceContainer');
        const placeholder = document.getElementById('testPlaceholder');
        if (!tbody) return;

        const typeColors = {
            start: 'bg-success', end: 'bg-dark', message: 'bg-primary', condition: 'bg-warning text-dark',
            input: 'bg-info text-dark', menu: 'bg-info text-dark', dtmf: 'bg-info text-dark',
            set_variable: 'bg-secondary', http_request: 'bg-primary', ai_bot: 'bg-purple',
            transfer: 'bg-danger', queue: 'bg-danger', wait: 'bg-secondary',
            play_audio: 'bg-success', record: 'bg-warning text-dark', goto: 'bg-light text-dark',
            sub_flow: 'bg-light text-dark', webhook: 'bg-orange'
        };
        const statusColors = {
            executed: '', end: 'bg-success', external: 'bg-secondary',
            needs_input: 'bg-warning text-dark', error: 'bg-danger'
        };

        tbody.innerHTML = '';
        // Store trace on tbody so click handlers can access it
        tbody._trace = trace;
        trace.forEach((step, idx) => {
            const tColor = typeColors[step.node_type] || 'bg-secondary';
            const sColor = statusColors[step.status] || '';

            // Collect changed vars (deduplicated)
            const changedVars = [];
            if (step.context_before && step.context_after) {
                const allKeys = new Set([
                    ...Object.keys(step.context_before),
                    ...Object.keys(step.context_after)
                ]);
                allKeys.forEach(k => {
                    if (k === '_expressions') return;
                    const bv = JSON.stringify(step.context_before[k]);
                    const av = JSON.stringify(step.context_after[k]);
                    if (bv !== av) changedVars.push({ key: k, before: step.context_before[k], after: step.context_after[k], isNew: !(k in step.context_before) });
                });
            }

            const edgePill = step.edge_taken ? `<span class="badge bg-light text-dark border ms-1">${escapeHtml(step.edge_taken)}</span>` : '';
            const statusBadge = sColor ? `<span class="badge ${sColor} ms-1">${escapeHtml(step.status)}</span>` : '';
            const noteTxt = step.note ? `<div class="text-muted small mt-1">${escapeHtml(step.note)}</div>` : '';
            const outTxt = step.output ? `<div class="text-muted small">${escapeHtml(String(step.output).substring(0, 120))}</div>` : '';

            const tr = document.createElement('tr');
            tr.style.cursor = 'pointer';
            tr.dataset.step = idx;
            tr.className = changedVars.length > 0 ? 'sim-row-has-diff' : '';
            tr.innerHTML = `
                <td class="text-center align-top pt-2">${step.step}</td>
                <td class="align-top pt-2"><span class="badge ${tColor} sim-type-badge">${escapeHtml(step.node_type)}</span></td>
                <td class="align-top">${escapeHtml(step.label || step.node_id)}${statusBadge}${outTxt}${noteTxt}</td>
                <td class="align-top pt-2">${edgePill}</td>
            `;

            // Click row → show context at this step + highlight node on canvas
            tr.addEventListener('click', () => {
                // Deselect all rows
                tbody.querySelectorAll('tr.sim-row-selected').forEach(r => r.classList.remove('sim-row-selected'));
                tr.classList.add('sim-row-selected');

                // Show context_after for this step in the inspector panel
                const label = document.getElementById('testFinalVarsLabel');
                if (label) label.textContent = `Context after Step ${step.step} — ${step.label || step.node_type}`;
                renderFinalContext(step.context_after || {});

                // Focus canvas node
                const n = nodes.find(nd => nd.id === step.node_id);
                if (n && n.el) {
                    n.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    n.el.classList.add('sim-focus');
                    setTimeout(() => n.el.classList.remove('sim-focus'), 1200);
                }
            });
            tbody.appendChild(tr);

            // Inline diff row — always shown when there are changes
            if (changedVars.length > 0) {
                const diffTr = document.createElement('tr');
                diffTr.className = 'sim-diff-inline-row';
                const rows = changedVars.map(cv => {
                    const cls = cv.isNew ? 'sim-diff-added' : 'sim-diff-changed';
                    const beforeStr = cv.isNew ? '<em class="text-muted">(new)</em>' : escapeHtml(JSON.stringify(cv.before));
                    const afterStr = `<strong class="text-success">${escapeHtml(JSON.stringify(cv.after))}</strong>`;
                    return `<tr class="${cls}"><td class="var-diff-key ps-2">${escapeHtml(cv.key)}</td><td>${beforeStr}</td><td>→</td><td>${afterStr}</td></tr>`;
                }).join('');
                diffTr.innerHTML = `<td colspan="4" class="p-0 pb-1">
                    <table class="table table-sm table-borderless mb-0 ms-4 sim-inline-diff-table">
                        <tbody>${rows}</tbody>
                    </table></td>`;
                diffTr.style.cursor = 'pointer';
                diffTr.addEventListener('click', () => tr.click());
                tbody.appendChild(diffTr);
            }
        });

        if (container) container.classList.remove('d-none');
        if (placeholder) placeholder.classList.add('d-none');
    }

    function renderFinalContext(ctx) {
        const el = document.getElementById('testFinalVars');
        if (!el) return;
        const filtered = Object.fromEntries(Object.entries(ctx).filter(([k]) => k !== '_expressions'));
        // Syntax-highlighted JSON
        const json = JSON.stringify(filtered, null, 2);
        const highlighted = json
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/("[^"]+")\s*:/g, '<span style="color:#79c0ff">$1</span>:')
            .replace(/:\s*("[^"]*")/g, ': <span style="color:#a5d6ff">$1</span>')
            .replace(/:\s*(true|false)/g, ': <span style="color:#ff7b72">$1</span>')
            .replace(/:\s*(null)/g, ': <span style="color:#8b949e">$1</span>')
            .replace(/:\s*(-?\d+\.?\d*)/g, ': <span style="color:#f2cc60">$1</span>');
        el.innerHTML = `<pre class="mb-0 small">${highlighted}</pre>`;
    }

    function highlightSimNodes(trace) {
        clearSimHighlights();
        if (!trace || trace.length === 0) return;

        trace.forEach((step, idx) => {
            const n = nodes.find(nd => nd.id === step.node_id);
            if (!n || !n.el) return;
            if (idx < trace.length - 1) {
                n.el.classList.add('sim-visited');
            } else {
                // Last step — differentiate by status
                const cls = step.status === 'end' ? 'sim-end'
                    : step.status === 'error' ? 'sim-error'
                    : step.status === 'needs_input' ? 'sim-blocked'
                    : step.status === 'external' ? 'sim-external'
                    : 'sim-active';
                n.el.classList.add(cls);
            }
        });
    }

    function clearSimHighlights() {
        nodes.forEach(n => {
            if (!n.el) return;
            n.el.classList.remove('sim-visited', 'sim-active', 'sim-blocked', 'sim-end', 'sim-error', 'sim-external', 'sim-focus');
        });
    }

    function showVarDiff(step, stepNum) {
        const body = document.getElementById('testVarDiffBody');
        const stepEl = document.getElementById('testVarDiffStep');
        if (!body) return;

        const before = step.context_before || {};
        const after = step.context_after || {};
        const allKeys = new Set([
            ...Object.keys(before).filter(k => k !== '_expressions'),
            ...Object.keys(after).filter(k => k !== '_expressions')
        ]);

        const rows = [];
        allKeys.forEach(k => {
            const bVal = JSON.stringify(before[k]);
            const aVal = JSON.stringify(after[k]);
            if (bVal === aVal) return;  // unchanged

            const cls = !(k in before) ? 'var-diff-added' : 'var-diff-changed';
            rows.push(`
                <tr class="var-diff-row ${cls}">
                    <td class="var-diff-key">${escapeHtml(k)}</td>
                    <td class="var-diff-before">${escapeHtml(!(k in before) ? '(new)' : bVal ?? 'null')}</td>
                    <td class="var-diff-after">${escapeHtml(aVal ?? 'null')}</td>
                </tr>
            `);
        });

        body.innerHTML = rows.length > 0
            ? `<table class="table table-sm table-borderless mb-0"><thead><tr><th>Variable</th><th>Before</th><th>After</th></tr></thead><tbody>${rows.join('')}</tbody></table>`
            : '<p class="text-muted small mb-0">No variable changes in this step.</p>';

        if (stepEl) stepEl.textContent = stepNum;

        const modal = new bootstrap.Modal(document.getElementById('testVarDiffModal'));
        modal.show();
    }

    // Simulator button bindings (deferred until DOM ready)
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('btnTestFlow')?.addEventListener('click', () => {
            initTestPanel();
            new bootstrap.Modal(document.getElementById('testFlowModal')).show();
        });

        document.getElementById('btnRunSim')?.addEventListener('click', () => runSimulation());

        document.getElementById('btnResetSim')?.addEventListener('click', () => {
            clearSimHighlights();
            const tc = document.getElementById('testTraceContainer');
            const tp = document.getElementById('testPlaceholder');
            const sb = document.getElementById('testStatusBanner');
            const lbl = document.getElementById('testFinalVarsLabel');
            if (tc) tc.classList.add('d-none');
            if (tp) tp.classList.remove('d-none');
            if (sb) sb.classList.add('d-none');
            if (lbl) lbl.textContent = 'Final Variables';
            const tbody = document.getElementById('testTraceBody');
            if (tbody) tbody.innerHTML = '';
            const fv = document.getElementById('testFinalVars');
            if (fv) fv.innerHTML = '<span class="text-muted">—</span>';
        });

        document.getElementById('btnCloseTest')?.addEventListener('click', () => clearSimHighlights());

        // Var diff modal "back" button closes it
        document.getElementById('testVarDiffModal')?.addEventListener('hidden.bs.modal', () => {
            // nothing extra needed
        });
    });

    // ───── Init ─────

    async function init() {
        if (!token()) {
            window.location.href = '/';
            return;
        }

        // Load node type registry → builds palette dynamically
        await loadNodeTypeRegistry();

        // Check if flow_id is in the URL
        const pathParts = window.location.pathname.split('/');
        const urlFlowId = pathParts[pathParts.length - 1];

        if (urlFlowId && urlFlowId !== 'flow-designer') {
            await loadFlow(urlFlowId);
        } else {
            // Show flow picker
            showFlowList();
        }

        updateTransform();
    }

    init();
})();

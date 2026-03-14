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

    // AI Flow Builder state
    let _aiChatHistory = [];
    let _aiFoundFlowJson = null;

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

    // ── Analytics overlay state ──
    let _analyticsActive = false;      // toggle flag
    let _analyticsMap = new Map();     // nodeId → {visit_count, node_label}
    let _analyticsEdgeMap = new Map(); // "sourceId→targetId" → {count}
    let _analyticsMax = 1;             // max visit_count for normalisation
    let _analyticsWindow = 60;         // time window in minutes (0 = all-time)

    // Node type metadata — populated from registry API at init, with fallback defaults
    const NODE_ICONS = {
        // Entry Points — Inbound channels
        start_chat:      'bi-chat-dots-fill',
        start_whatsapp:  'bi-whatsapp',
        start_api:       'bi-braces-asterisk',
        start_voice:     'bi-telephone-inbound-fill',
        start_email:     'bi-envelope-fill',
        start_sms:       'bi-chat-square-text-fill',
        // Entry Points — Event / Lifecycle
        start_chat_ended:             'bi-chat-x-fill',
        start_call_ended:             'bi-telephone-x-fill',
        start_internal_call:          'bi-telephone-forward-fill',
        start_sla_breached:           'bi-alarm-fill',
        start_contact_imported:       'bi-person-plus-fill',
        start_contact_status_changed: 'bi-person-fill-gear',
        // Entry Points — Third-party placeholders
        start_messenger:       'bi-messenger',
        start_instagram_dm:    'bi-instagram',
        start_instagram_post:  'bi-instagram',
        start_facebook_wall:   'bi-facebook',
        start_x_dm:            'bi-twitter-x',
        start_x_post:          'bi-twitter-x',
        start_apple_business:  'bi-apple',
        start_hubspot:         'bi-circle-fill',
        // Flow Control
        start: 'bi-play-circle', end: 'bi-stop-circle', message: 'bi-chat-left-text',
        condition: 'bi-signpost-split', input: 'bi-input-cursor-text', transfer: 'bi-telephone-forward',
        queue: 'bi-people', http_request: 'bi-globe', set_variable: 'bi-braces',
        wait: 'bi-hourglass', menu: 'bi-list-ol', play_audio: 'bi-volume-up',
        record: 'bi-mic', dtmf: 'bi-grid-3x3', ai_bot: 'bi-robot', webhook: 'bi-broadcast',
        goto: 'bi-arrow-return-right', sub_flow: 'bi-box-arrow-in-right', switch: 'bi-diagram-3',
        ab_split: 'bi-intersect', loop: 'bi-arrow-repeat', time_gate: 'bi-clock',
    };

    // Entry node type keys — kept in sync with ENTRY_NODE_KEYS on the server
    const ENTRY_NODE_TYPES = new Set([
        'start', 'start_chat', 'start_whatsapp', 'start_api', 'start_voice', 'start_email', 'start_sms',
        'start_chat_ended', 'start_call_ended', 'start_internal_call',
        'start_sla_breached', 'start_contact_imported', 'start_contact_status_changed',
    ]);

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
            window.location.href = '/login';
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
        const hasInput = reg ? reg.has_input : !(node.type === 'start' || node.type.startsWith('start_'));
        const hasOutput = reg ? reg.has_output : (node.type !== 'end');
        const isCondition = node.type === 'condition';
        const isSwitchNode  = node.type === 'switch';
        const isAbSplit    = node.type === 'ab_split';
        const isLoopNode   = node.type === 'loop';
        const isTimeGate   = node.type === 'time_gate';
        const isHttpRequest = node.type === 'http_request';
        const isInputNode   = node.type === 'input';

        // Build output port markup — switch ports are dynamic (one per case + default)
        let outPortHtml = '';
        if (isCondition) {
            outPortHtml = '<div class="node-port port-out-true" data-port="true" title="True"></div>' +
                          '<div class="node-port port-out-false" data-port="false" title="False"></div>';
        } else if (isSwitchNode) {
            const switchCases = node.config?.cases || [];
            const swTotal = switchCases.length + 1; // cases + default
            // Scale node width so ports never crowd: 40px per slot, min 180px
            el.style.minWidth = Math.max(180, (swTotal + 1) * 40) + 'px';
            outPortHtml = switchCases.map((c, i) => {
                const pct = ((i + 1) / (swTotal + 1) * 100).toFixed(1);
                return `<div class="node-port port-out-switch" data-port="case_${i}" title="${(c.label || 'Case ' + (i + 1)).replace(/"/g, '&quot;')}" style="left:${pct}%"></div>`;
            }).join('') + (() => {
                const pct = (swTotal / (swTotal + 1) * 100).toFixed(1);
                return `<div class="node-port port-out-switch port-out-default" data-port="default" title="Default (fallthrough)" style="left:${pct}%"></div>`;
            })();
        } else if (isAbSplit) {
            const pct = node.config?.split_percent ?? 50;
            const tagA = node.config?.tag_a || 'Branch A';
            const tagB = node.config?.tag_b || 'Branch B';
            outPortHtml = `<div class="node-port port-out-a" data-port="branch_a" title="${pct}% → ${tagA}"></div>` +
                          `<div class="node-port port-out-b" data-port="branch_b" title="${100 - pct}% \u2192 ${tagB}"></div>`;
        } else if (isLoopNode) {
            outPortHtml = '<div class="node-port port-out-loop" data-port="loop" title="Loop (iterate body)"></div>' +
                          '<div class="node-port port-out-done" data-port="done" title="Done (all items processed)"></div>';
        } else if (isTimeGate) {
            outPortHtml = '<div class="node-port port-out-open" data-port="open" title="Open (within schedule)"></div>' +
                          '<div class="node-port port-out-closed" data-port="closed" title="Closed (outside schedule)"></div>';
        } else if (isHttpRequest) {
            outPortHtml = '<div class="node-port port-out-success" data-port="success" title="Success (2xx)"></div>' +
                          '<div class="node-port port-out-error"   data-port="error"   title="Error (non-2xx / timeout / network failure)"></div>';
        } else if (isInputNode) {
            outPortHtml = '<div class="node-port port-out-received" data-port="default" title="Response received"></div>' +
                          '<div class="node-port port-out-timeout"  data-port="timeout"  title="Max retries exceeded"></div>';
        } else if (hasOutput) {
            outPortHtml = '<div class="node-port port-out" data-port="default"></div>';
        }

        el.innerHTML = `
            <div class="node-header"><i class="bi ${icon}"></i>${node.type.replace(/_/g, ' ')}</div>
            <div class="node-body">${node.label || node.type}</div>
            ${hasInput ? '<div class="node-port port-in" data-port="in"></div>' : ''}
            ${outPortHtml}
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
        if (handle === 'true')     return { x: node.x + w * 0.3, y: node.y + h };
        if (handle === 'false')    return { x: node.x + w * 0.7, y: node.y + h };
        if (handle === 'branch_a') return { x: node.x + w * 0.3, y: node.y + h };
        if (handle === 'branch_b') return { x: node.x + w * 0.7, y: node.y + h };
        if (handle === 'open')    return { x: node.x + w * 0.3, y: node.y + h };
        if (handle === 'closed')  return { x: node.x + w * 0.7, y: node.y + h };
        if (handle === 'loop')    return { x: node.x + w * 0.3, y: node.y + h };
        if (handle === 'done')    return { x: node.x + w * 0.7, y: node.y + h };
        if (handle === 'success') return { x: node.x + w * 0.3, y: node.y + h };
        if (handle === 'error')   return { x: node.x + w * 0.7, y: node.y + h };
        if (handle === 'timeout') return { x: node.x + w * 0.7, y: node.y + h };
        if (node.type === 'input' && handle === 'default') return { x: node.x + w * 0.3, y: node.y + h };
        // Switch node: evenly space case_0..N and 'default' across the node bottom
        if (node.type === 'switch') {
            const swCases = node.config?.cases || [];
            const total = swCases.length + 1; // cases + default
            let idx;
            if (handle === 'default') {
                idx = swCases.length;
            } else if (handle.startsWith('case_')) {
                idx = parseInt(handle.split('_')[1], 10);
            } else {
                idx = 0;
            }
            const fraction = (idx + 1) / (total + 1);
            return { x: node.x + w * fraction, y: node.y + h };
        }
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

            // Edge label: show for condition true/false and all switch case handles
            const _srcNode = nodes.find(n => n.id === edge.sourceId);
            let _displayLabel = edge.label;
            if (_srcNode?.type === 'switch' && edge.sourceHandle) {
                if (edge.sourceHandle.startsWith('case_')) {
                    const _ci = parseInt(edge.sourceHandle.split('_')[1], 10);
                    _displayLabel = _srcNode.config?.cases?.[_ci]?.label || edge.sourceHandle;
                } else if (edge.sourceHandle === 'default') {
                    _displayLabel = 'Default';
                }
            }
            if (_srcNode?.type === 'ab_split' && edge.sourceHandle) {
                const _pct = _srcNode.config?.split_percent ?? 50;
                if (edge.sourceHandle === 'branch_a') {
                    _displayLabel = `A: ${_srcNode.config?.tag_a || 'branch_a'} (${_pct}%)`;
                } else if (edge.sourceHandle === 'branch_b') {
                    _displayLabel = `B: ${_srcNode.config?.tag_b || 'branch_b'} (${100 - _pct}%)`;
                }
            }
            const _showLabel = _displayLabel || ['true', 'false', 'open', 'closed', 'loop', 'done', 'success', 'error', 'timeout'].includes(edge.sourceHandle);
            if (_showLabel) {
                const text = document.createElementNS(ns, 'text');
                text.setAttribute('x', (from.x + to.x) / 2);
                text.setAttribute('y', midY - 6);
                text.setAttribute('fill', '#adb5bd');
                text.setAttribute('font-size', '11');
                text.setAttribute('text-anchor', 'middle');
                text.textContent = _displayLabel || edge.sourceHandle;
                edgeSvg.appendChild(text);
            }

            // Analytics overlay — colour edge by per-edge transition count + show count pill
            if (_analyticsActive && (_analyticsMap.size > 0 || _analyticsEdgeMap.size > 0)) {
                const edgeKey = `${edge.sourceId}\u2192${edge.targetId}`;
                const edgeStat = _analyticsEdgeMap.get(edgeKey);
                // When per-edge data is available (map non-empty), a missing entry means 0 traversals.
                // Only fall back to target-node count when the server returned no edge data at all
                // (window=0 / all-time mode which lacks from_node_id tracking).
                const edgeCount = _analyticsEdgeMap.size > 0
                    ? (edgeStat ? edgeStat.count : 0)
                    : (_analyticsMap.get(edge.targetId)?.visit_count || 0);
                const srcCount  = _analyticsMap.get(edge.sourceId)?.visit_count || 0;

                // Re-colour the edge path we already appended
                if (edgeCount > 0) {
                    const t = edgeCount / _analyticsMax;
                    path.setAttribute('stroke', _heatColor(t));
                    path.setAttribute('stroke-width', (1.5 + t * 3).toFixed(1));
                    path.setAttribute('stroke-opacity', '0.9');
                } else {
                    path.setAttribute('stroke', '#444');
                    path.setAttribute('stroke-opacity', '0.4');
                }

                // Traffic count pill at edge midpoint
                if (srcCount > 0 || edgeCount > 0) {
                    const labelX = (from.x + to.x) / 2;
                    const labelY = midY + (_showLabel ? 18 : 2);

                    const rect = document.createElementNS(ns, 'rect');
                    const pillW = 44, pillH = 15, pillR = 7;
                    rect.setAttribute('x', labelX - pillW / 2);
                    rect.setAttribute('y', labelY - pillH + 3);
                    rect.setAttribute('width',  pillW);
                    rect.setAttribute('height', pillH);
                    rect.setAttribute('rx', pillR);
                    rect.setAttribute('ry', pillR);
                    rect.setAttribute('fill', edgeCount > 0 ? _heatColor(edgeCount / _analyticsMax) : '#444');
                    rect.setAttribute('fill-opacity', '0.8');
                    edgeSvg.appendChild(rect);

                    const tText = document.createElementNS(ns, 'text');
                    tText.setAttribute('x', labelX);
                    tText.setAttribute('y', labelY - 2);
                    tText.setAttribute('fill', '#fff');
                    tText.setAttribute('font-size', '10');
                    tText.setAttribute('font-weight', 'bold');
                    tText.setAttribute('text-anchor', 'middle');
                    // Show edge count + traffic share % vs source node (clearer than drop-off on splits)
                    let tLabel = edgeCount > 999 ? `${(edgeCount/1000).toFixed(1)}k` : String(edgeCount);
                    if (srcCount > 0) {
                        const sharePct = Math.round((edgeCount / srcCount) * 100);
                        tLabel += ` \u00b7 ${sharePct}%`;
                    }
                    tText.textContent = tLabel;
                    edgeSvg.appendChild(tText);
                }
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
        } else if (node.type === 'switch') {
            html += '<label class="form-label fw-semibold">Cases <small class="text-muted fw-normal ms-1">(each row = one output port — all conditions in a row must match)</small></label>';
            html += renderSwitchCasesPanel(node);
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
        if (node.type !== 'set_variable' && node.type !== 'switch' && schema.length > 0) {
            bindFormFields(schema, node);
        }

        // Set variable multi-field editor bindings
        if (node.type === 'set_variable') {
            bindSetFieldsPanel(node);
        } else if (node.type === 'switch') {
            bindSwitchCasesPanel(node);
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
        const noVarTypes = ['number', 'boolean', 'date', 'select', 'connector_select', 'whatsapp_connector_select', 'voice_connector_select', 'sms_connector_select', 'email_connector_select', 'queue_select', 'flow_select', 'tag_select', 'options_list', 'key_value', 'weekdays'];
        const showVarBtn = isExpr || !noVarTypes.includes(field.type);

        let html = `<div class="mb-2 form-field-group" data-field-key="${field.key}">`;

        // Label only (no buttons here)
        html += `<label class="form-label mb-1">${field.label || field.key}${field.required ? ' <span class="text-danger">*</span>' : ''}</label>`;

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

        // Toolbar below the widget
        const hasToolbar = exprEnabled || showVarBtn;
        if (hasToolbar) {
            html += `<div class="sf-field-toolbar mt-1">`;
            if (exprEnabled) {
                html += `<button class="btn btn-sm field-mode-toggle ${isExpr ? 'field-mode-expr' : 'field-mode-text'}" data-key="${field.key}"
                    title="${isExpr ? 'JSONata expression mode \u2013 click for literal' : 'Literal value \u2013 click for expression'}">
                    ${isExpr ? '<i class="bi bi-lightning-charge-fill"></i>' : '<i class="bi bi-fonts"></i>'}
                </button>`;
            }
            if (showVarBtn) {
                html += `<button class="btn btn-sm btn-outline-secondary btn-var-insert" data-key="${field.key}" title="Insert variable"><i class="bi bi-braces"></i> Variables</button>`;
            }
            if (exprEnabled && isExpr) {
                html += `<button class="btn btn-sm btn-outline-warning field-expr-builder" data-key="${field.key}" title="Open Expression Builder"><i class="bi bi-tools"></i></button>`;
            }
            html += `</div>`;
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
                return `<input type="url" class="form-control form-control-sm field-input" data-key="${key}" data-field-type="url"
                    value="${esc(val)}" placeholder="${esc(ph || 'https://')}">`;
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
            case 'whatsapp_connector_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="whatsapp_connector_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 None (unlinked) \u2014'}</option>
                    </select>
                    <a href="/connectors" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage WhatsApp connectors">
                        <i class="bi bi-whatsapp"></i>
                    </a>
                </div>`;
            case 'voice_connector_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="voice_connector_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 None (unlinked) \u2014'}</option>
                    </select>
                    <a href="/connectors" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage Voice connectors">
                        <i class="bi bi-telephone-fill"></i>
                    </a>
                </div>`;
            case 'sms_connector_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="sms_connector_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 None (unlinked) \u2014'}</option>
                    </select>
                    <a href="/connectors" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage SMS connectors">
                        <i class="bi bi-chat-square-text-fill"></i>
                    </a>
                </div>`;
            case 'email_connector_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="email_connector_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 None (unlinked) \u2014'}</option>
                    </select>
                    <a href="/connectors" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage Email connectors">
                        <i class="bi bi-envelope-fill"></i>
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
            case 'tag_select':
                return `<div class="d-flex gap-1 align-items-center">
                    <select class="form-select form-select-sm field-input flex-fill"
                        data-key="${key}" data-field-type="tag_select">
                        <option value="">${String(val) ? 'Loading\u2026' : '\u2014 Select tag \u2014'}</option>
                    </select>
                    <a href="/tags" target="_blank" class="btn btn-sm btn-outline-secondary" title="Manage tags">
                        <i class="bi bi-tags"></i>
                    </a>
                </div>`;
            case 'weekdays': {
                const _days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
                const _active = String(val || 'Mon,Tue,Wed,Thu,Fri').split(',').map(d => d.trim());
                const _pills = _days.map(d =>
                    `<button type="button" class="btn btn-sm weekday-pill ${_active.includes(d) ? 'btn-primary' : 'btn-outline-secondary'}" data-day="${d}">${d}</button>`
                ).join('');
                return `<div class="weekdays-picker d-flex flex-wrap gap-1 mb-1">${_pills}</div>` +
                       `<input type="hidden" class="field-input" data-key="${key}" data-field-type="weekdays" value="${esc(String(val || 'Mon,Tue,Wed,Thu,Fri'))}">`;  
            }
            default: // string
                return `<input type="text" class="form-control form-control-sm field-input" data-key="${key}" data-field-type="string"
                    value="${esc(val)}" placeholder="${esc(ph)}">`;
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

        // Weekday picker pill binding
        document.querySelectorAll('#propBody .weekdays-picker').forEach(picker => {
            const hiddenInput = picker.nextElementSibling;
            if (!hiddenInput) return;
            picker.querySelectorAll('.weekday-pill').forEach(pill => {
                pill.addEventListener('click', () => {
                    pill.classList.toggle('btn-primary');
                    pill.classList.toggle('btn-outline-secondary');
                    const active = Array.from(picker.querySelectorAll('.weekday-pill.btn-primary'))
                        .map(p => p.dataset.day);
                    hiddenInput.value = active.join(',');
                    hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
                });
            });
        });

        // Asynchronously populate connector_select / queue_select / flow_select / tag_select dropdowns
        _populateConnectorSelects(node);
        _populateWhatsappConnectorSelects(node);
        _populateVoiceConnectorSelects(node);
        _populateSmsConnectorSelects(node);
        _populateQueueSelects(node);
        _populateFlowSelects(node);
        _populateTagSelects(node);
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

    // ───── Switch / Multi-branch Cases Editor ─────

    function renderSwitchCasesPanel(node) {
        const cases = node.config.cases || [];
        let html = '<div class="switch-cases-editor" id="switchCasesEditor">';
        html += '<div class="mb-2"><small class="text-muted">Evaluated top-to-bottom — first case where <strong>all</strong> conditions match wins.</small></div>';
        html += '<div id="switchCasesList">';
        cases.forEach((c, i) => { html += renderSwitchCaseRow(c, i); });
        html += '</div>';
        html += '<button class="btn btn-sm btn-outline-secondary mt-2 w-100" id="btnAddCase"><i class="bi bi-plus me-1"></i>Add Case</button>';
        html += '<div class="mt-3 p-2 rounded" style="background:#1a2035;border:1px solid #2e3a5b;">';
        html += '<div class="d-flex align-items-center gap-2"><span class="badge bg-secondary me-1">&#9670;</span><span class="small text-muted">Default (fallthrough) — always present as last port</span></div>';
        html += '</div></div>';
        return html;
    }

    function renderSwitchCaseRow(c, i) {
        const ops = ['equals','not_equals','contains','not_contains','greater_than','less_than',
                     'starts_with','ends_with','is_empty','is_not_empty',
                     'is_array','is_not_array','is_object','is_not_object',
                     'is_true','is_false','regex'];
        const esc = v => String(v ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;');
        // New format: c.conditions[] — legacy: single op/value with global variable
        const conditions = c.conditions || (c.operator ? [{ variable: '', operator: c.operator, value: c.value || '' }] : [{ variable: '', operator: 'equals', value: '' }]);
        let html = `<div class="switch-case-row border rounded p-2 mb-2" data-case-idx="${i}" style="background:#1a2035;border-color:#2e3a5b!important;">`;
        // Case header: number badge + label + remove
        html += `<div class="d-flex align-items-center gap-1 mb-2">
            <span class="badge bg-warning text-dark me-1" style="font-size:.65rem;">${i + 1}</span>
            <input type="text" class="form-control form-control-sm sc-label" value="${esc(c.label || '')}" placeholder="Case label (shown on edge)">
            <button class="btn btn-sm btn-outline-danger sc-remove ms-auto" title="Remove case"><i class="bi bi-x"></i></button>
        </div>`;
        // Per-condition rows
        html += '<div class="sc-conditions-list">';
        conditions.forEach((cond, ci) => {
            const noVal = ['is_empty','is_not_empty','is_array','is_not_array','is_object','is_not_object','is_true','is_false'].includes(cond.operator);
            html += `<div class="sc-cond-row d-flex gap-1 align-items-center mb-1 flex-wrap" data-cond-idx="${ci}">
                <span class="badge bg-secondary" style="font-size:.6rem;min-width:1.8rem;text-align:center;flex-shrink:0;">${ci === 0 ? 'IF' : 'AND'}</span>
                <div class="input-group input-group-sm" style="width:auto;flex:1 1 100px;min-width:80px;max-width:160px;">
                    <input type="text" class="form-control form-control-sm sc-var" value="${esc(cond.variable || '')}" placeholder="variable">
                    <button class="btn btn-outline-secondary sc-var-insert" type="button" title="Pick variable"><i class="bi bi-braces"></i></button>
                </div>
                <select class="form-select form-select-sm sc-op" style="width:auto;flex:0 0 auto;max-width:120px;">${ops.map(op => `<option value="${op}" ${cond.operator === op ? 'selected' : ''}>${op.replace(/_/g,' ')}</option>`).join('')}</select>
                <input type="text" class="form-control form-control-sm sc-val" value="${esc(cond.value || '')}" placeholder="value" ${noVal ? 'disabled' : ''} style="flex:1;min-width:50px;">
                <button class="btn btn-sm btn-outline-secondary sc-cond-remove" title="Remove condition" ${conditions.length === 1 ? 'disabled' : ''}><i class="bi bi-dash"></i></button>
            </div>`;
        });
        html += '</div>';
        html += '<button class="btn btn-sm btn-link text-secondary p-0 mt-1 sc-add-cond"><i class="bi bi-plus me-1"></i><small>Add condition</small></button>';
        html += '</div>';
        return html;
    }

    function bindSwitchCasesPanel(node) {
        const editor = document.getElementById('switchCasesEditor');
        if (!editor) return;

        function readCases() {
            const rows = editor.querySelectorAll('.switch-case-row');
            node.config.cases = Array.from(rows).map(row => ({
                label: row.querySelector('.sc-label').value,
                conditions: Array.from(row.querySelectorAll('.sc-cond-row')).map(cr => ({
                    variable: cr.querySelector('.sc-var').value,
                    operator: cr.querySelector('.sc-op').value,
                    value:    cr.querySelector('.sc-val').value,
                })),
            }));
            rebuildSwitchPorts(node);
            updateNodeDisplay(node);
        }

        // Label changes
        editor.querySelectorAll('.sc-label').forEach(el => el.addEventListener('change', readCases));

        // Condition variable / value changes
        editor.querySelectorAll('.sc-var, .sc-val').forEach(el => el.addEventListener('change', readCases));

        // Operator changes — disable value input for no-value operators
        editor.querySelectorAll('.sc-op').forEach(sel => sel.addEventListener('change', () => {
            const valInput = sel.closest('.sc-cond-row')?.querySelector('.sc-val');
            const noVal = ['is_empty','is_not_empty','is_array','is_not_array','is_object','is_not_object','is_true','is_false'].includes(sel.value);
            if (valInput) { valInput.disabled = noVal; if (noVal) valInput.value = ''; }
            readCases();
        }));

        // Variable picker buttons on condition rows
        editor.querySelectorAll('.sc-var-insert').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const varInput = btn.closest('.sc-cond-row')?.querySelector('.sc-var');
                if (varInput) _showVarPickerForButton(btn, varInput, node.id, false);
            });
        });

        // Remove entire case
        editor.querySelectorAll('.sc-remove').forEach(btn => btn.addEventListener('click', () => {
            btn.closest('.switch-case-row').remove();
            readCases();
            showNodeProperties(node);
        }));

        // Remove single condition row (not allowed when only one remains)
        editor.querySelectorAll('.sc-cond-remove').forEach(btn => btn.addEventListener('click', () => {
            if (btn.disabled) return;
            btn.closest('.sc-cond-row').remove();
            readCases();
            showNodeProperties(node);
        }));

        // Add condition row to existing case
        editor.querySelectorAll('.sc-add-cond').forEach(btn => btn.addEventListener('click', () => {
            const caseRow = btn.closest('.switch-case-row');
            const caseIdx = parseInt(caseRow.dataset.caseIdx, 10);
            readCases(); // persist current state first
            const cases = node.config.cases || [];
            if (cases[caseIdx]) {
                cases[caseIdx].conditions.push({ variable: '', operator: 'equals', value: '' });
                node.config.cases = cases;
            }
            showNodeProperties(node);
        }));

        // Add new case
        document.getElementById('btnAddCase')?.addEventListener('click', () => {
            const cases = node.config.cases || [];
            cases.push({ label: 'Case ' + (cases.length + 1), conditions: [{ variable: '', operator: 'equals', value: '' }] });
            node.config.cases = cases;
            showNodeProperties(node);
        });
    }

    function rebuildSwitchPorts(node) {
        if (!node.el) return;
        // Remove all existing output ports
        node.el.querySelectorAll('.node-port:not(.port-in)').forEach(p => p.remove());
        // Add N case ports + 1 default port, evenly spaced
        const cases = node.config?.cases || [];
        const total = cases.length + 1; // cases + default
        // Scale node width: 40px per slot, min 180px
        node.el.style.minWidth = Math.max(180, (total + 1) * 40) + 'px';
        const allHandles = cases.map((c, i) => ({
            handle: `case_${i}`,
            title: c.label || `Case ${i + 1}`,
            cls: 'port-out-switch',
            left: ((i + 1) / (total + 1) * 100).toFixed(1) + '%'
        }));
        allHandles.push({
            handle: 'default',
            title: 'Default (fallthrough)',
            cls: 'port-out-switch port-out-default',
            left: (total / (total + 1) * 100).toFixed(1) + '%'
        });
        allHandles.forEach(({ handle, title, cls, left }) => {
            const p = document.createElement('div');
            p.className = `node-port ${cls}`;
            p.dataset.port = handle;
            p.title = title;
            p.style.left = left;
            p.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                drawingEdge = true;
                edgeSourceNode = node;
                edgeSourceHandle = handle;
            });
            node.el.appendChild(p);
        });
        renderEdges();
    }

    // ───── Variable Picker ─────

    /**
     * Return all variables that are available *before* the given node in the flow,
     * by walking the edge graph backwards (BFS) and inspecting what each ancestor produces.
     * Returns [{name, source}] sorted alphabetically — only variables declared upstream.
     */
    function getAvailableVariables(forNodeId, sameNodeFieldIndex = -1) {
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

        // ── Same-node earlier fields — so field N can reference field N-1 set above it ──
        if (sameNodeFieldIndex > 0) {
            const ownNode = nodes.find(nn => nn.id === forNodeId);
            if (ownNode && Array.isArray(ownNode.config?.fields)) {
                const lbl = (ownNode.config?.label || ownNode.label || ownNode.type) + ' ↑';
                ownNode.config.fields.slice(0, sameNodeFieldIndex).forEach(f => {
                    if (f.name) addVar(f.name, lbl);
                });
            }
        }

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
            filtered.map(v => `<button class="var-chip" data-varname="${v.name}" data-exprmode="${!!exprMode}" >${v.name}<span class="var-chip-source">${v.source}</span></button>`).join('') +
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
    function _showVarPickerForButton(btnEl, inputEl, nodeId, exprMode, fieldIndex = -1) {
        _pickerInput = inputEl;
        _pickerActive = true;

        const picker = _getOrCreatePicker();
        const allVars = getAvailableVariables(nodeId, fieldIndex);

        if (allVars.length === 0) {
            picker.innerHTML = '<span class="text-muted small px-2 py-1">No variables declared upstream yet</span>';
        } else {
            picker.innerHTML = '<div class="var-picker-label">Insert variable</div><div class="var-picker-chips">' +
                allVars.map(v => `<button class="var-chip" data-varname="${v.name}" data-exprmode="${!!exprMode}" >${v.name}<span class="var-chip-source">${v.source}</span></button>`).join('') +
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
            // In expression mode insert $varName — matches Python _substitute_context_vars
            const exprInsert = '$' + varName;
            newVal = before + exprInsert + val.slice(pos);
            newCursor = before.length + exprInsert.length;
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
    /**
     * Open the JSONata Expression Builder modal.
     * @param {string}      currentValue  - Current expression value
     * @param {string}      fieldLabel    - Display label for the field
     * @param {Function}    onApply       - Callback(newValue) when user clicks Apply
     * @param {string|null} nodeId        - Node being edited (for same-node var visibility)
     * @param {number}      fieldIndex    - Field index: show same-node fields 0..fieldIndex-1
     */
    function openExpressionBuilder(currentValue, fieldLabel, onApply, nodeId = null, fieldIndex = -1) {
        _exprApplyCallback = onApply;
        document.getElementById('exprFieldName').textContent = fieldLabel;
        document.getElementById('exprInput').value = currentValue || '';
        document.getElementById('exprTestData').value = JSON.stringify(
            buildSampleContext(nodeId || _currentNodeId, fieldIndex), null, 2
        );
        document.getElementById('exprResult').textContent = '';
        document.getElementById('exprResult').className = 'p-2 rounded border border-secondary expr-result-box';
        document.getElementById('exprStatus').textContent = '';

        // Populate flow variables panel — includes same-node earlier fields
        const varListEl = document.getElementById('exprVarList');
        if (varListEl) {
            const effectiveId = nodeId || _currentNodeId;
            const vars = effectiveId ? getAvailableVariables(effectiveId, fieldIndex) : [];
            if (vars.length === 0) {
                varListEl.innerHTML = '<span class="text-muted" style="font-size:.75rem">No variables declared upstream</span>';
            } else {
                varListEl.innerHTML = vars.map(v =>
                    `<button class="var-chip" data-varname="${v.name}" title="From: ${v.source}">${v.name}</button>`
                ).join('');
                varListEl.querySelectorAll('.var-chip').forEach(chip => {
                    chip.addEventListener('click', () => {
                        const inp = document.getElementById('exprInput');
                        _insertVariable(inp, chip.dataset.varname, true); // inserts $varName
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

    /** Populate all flow_select dropdowns in the open properties panel.
     *  Only published flows are offered — you can only link to a published version. */
    async function _populateFlowSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="flow_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/flows?published_only=true');
            const flows = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const key = sel.dataset.key;
                const currentVal = node.config[key] || '';
                sel.innerHTML = '<option value="">&mdash; Select published flow &mdash;</option>';
                if (flows.length === 0) {
                    const opt = document.createElement('option');
                    opt.value = ''; opt.disabled = true;
                    opt.textContent = 'No published flows yet — publish a flow first';
                    sel.appendChild(opt);
                }
                flows.forEach(f => {
                    const opt = document.createElement('option');
                    opt.value = f.id;
                    opt.textContent = f.name + ' (v' + f.version + ')';
                    if (String(f.id) === String(currentVal)) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        } catch (e) {
            // silently ignore
        }
    }

    /** Populate all tag_select dropdowns (interaction tags) in the open properties panel */
    async function _populateTagSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="tag_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/tags?tag_type=interaction&active_only=true');
            const tags = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const key = sel.dataset.key;
                const currentVal = node.config[key] || '';
                sel.innerHTML = '<option value="">\u2014 Select tag \u2014</option>';
                tags.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.slug;
                    opt.textContent = t.name;
                    if (t.color) opt.style.borderLeft = `3px solid ${t.color}`;
                    if (t.slug === currentVal) opt.selected = true;
                    sel.appendChild(opt);
                });
                if (tags.length === 0) {
                    const opt = document.createElement('option');
                    opt.value = '';
                    opt.disabled = true;
                    opt.textContent = 'No interaction tags configured \u2014 add them in Tags';
                    sel.appendChild(opt);
                }
            });
        } catch (e) {
            // silently ignore network errors
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

    /** Populate all whatsapp_connector_select dropdowns */
    async function _populateWhatsappConnectorSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="whatsapp_connector_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/whatsapp-connectors');
            const items = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const currentVal = node.config[sel.dataset.key] || '';
                sel.innerHTML = '<option value="">\u2014 None (unlinked) \u2014</option>';
                items.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name + (c.is_active ? '' : ' (inactive)');
                    if (c.id === currentVal) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        } catch (e) { /* silently ignore */ }
    }

    /** Populate all voice_connector_select dropdowns */
    async function _populateVoiceConnectorSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="voice_connector_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/voice-connectors');
            const items = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const currentVal = node.config[sel.dataset.key] || '';
                sel.innerHTML = '<option value="">\u2014 None (unlinked) \u2014</option>';
                items.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name + (c.is_active ? '' : ' (inactive)');
                    if (c.id === currentVal) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        } catch (e) { /* silently ignore */ }
    }

    /** Populate all sms_connector_select dropdowns */
    async function _populateSmsConnectorSelects(node) {
        const selects = document.querySelectorAll('#propBody .field-input[data-field-type="sms_connector_select"]');
        if (!selects.length) return;
        try {
            const r = await apiFetch('/api/v1/sms-connectors');
            const items = r.ok ? await r.json() : [];
            selects.forEach(sel => {
                const currentVal = node.config[sel.dataset.key] || '';
                sel.innerHTML = '<option value="">\u2014 None (unlinked) \u2014</option>';
                items.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name + (c.is_active ? '' : ' (inactive)');
                    if (c.id === currentVal) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        } catch (e) { /* silently ignore */ }
    }

    /**
     * Build a sample context that mirrors the flat runtime context.
     * @param {string|null} nodeId - Current node (for same-node field visibility)
     * @param {number} fieldIndex - Field index: only include same-node fields 0..fieldIndex-1
     */
    function buildSampleContext(nodeId = null, fieldIndex = -1) {
        // FLAT context — matches what Python runtime passes to JSONata / _resolve_template
        const ctx = {};
        nodes.forEach(n => {
            if (n.type === 'set_variable' && Array.isArray(n.config?.fields)) {
                const maxIdx = (n.id === nodeId) ? fieldIndex : Infinity;
                n.config.fields.forEach((f, fi) => {
                    if (f.name && fi < maxIdx) ctx[f.name] = f.value ?? '';
                });
            }
            if (n.type === 'input' && n.config?.variable) {
                if (!ctx[n.config.variable]) ctx[n.config.variable] = '<user_input>';
            }
            if (n.type === 'webhook') {
                if (!ctx.webhook_status_code) ctx.webhook_status_code = 200;
                if (!ctx.webhook_response) ctx.webhook_response = { status: 200, body: {} };
            }
        });
        // Nested system objects (accessible as contact.name etc in templates)
        ctx.contact = { name: 'John Doe', phone: '+27821234567', email: 'john@example.com' };
        ctx.system  = { timestamp: new Date().toISOString(), channel: 'chat' };
        return ctx;
    }

    /**
     * Pre-substitute $varName references before passing to the JSONata JS library.
     * Mirrors Python _substitute_context_vars so the browser test matches runtime behaviour.
     */
    function _jsSubstContextVars(expr, ctx) {
        return expr.replace(/\$([a-zA-Z_][a-zA-Z0-9_]*)(?!\s*\()/g, (match, name) => {
            if (!(name in ctx)) return match;   // not in context — leave for JSONata
            const val = ctx[name];
            if (val === null || val === undefined) return 'null';
            if (typeof val === 'boolean') return val ? 'true' : 'false';
            if (typeof val === 'number')  return String(val);
            return JSON.stringify(String(val));  // string literal
        });
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
                // Pre-substitute $varName → literal value, matching Python runtime behaviour
                const substituted = _jsSubstContextVars(expr, testData);
                const expression = jsonata(substituted);
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
        const noVarTypes = ['number', 'boolean', 'date', 'relative_date', 'array'];
        const showVarBtn = isExpr || !noVarTypes.includes(field.type);

        // ── Value input widget ──
        let inputHtml;
        if (isExpr) {
            inputHtml = `<input type="text" class="form-control form-control-sm sf-val sf-expr-input" data-idx="${idx}" value="${esc(field.value)}" placeholder="JSONata expression">`;
        } else {
            switch (field.type) {
                case 'number':
                    inputHtml = `<input type="number" class="form-control form-control-sm sf-val" data-idx="${idx}" step="any" value="${esc(field.value)}">`;
                    break;
                case 'boolean':
                    inputHtml = `<select class="form-select form-select-sm sf-val" data-idx="${idx}">
                        <option value="true"  ${field.value === true  || field.value === 'true'  ? 'selected' : ''}>true</option>
                        <option value="false" ${field.value === false || field.value === 'false' ? 'selected' : ''}>false</option>
                    </select>`;
                    break;
                case 'date':
                    inputHtml = `<input type="date" class="form-control form-control-sm sf-val" data-idx="${idx}" value="${esc(field.value)}">`;
                    break;
                case 'relative_date': {
                    const v = (typeof field.value === 'object' && field.value) ? field.value : { direction: '+', amount: 0, unit: 'days' };
                    inputHtml = `<div class="d-flex gap-1 align-items-center sf-reldate" data-idx="${idx}">
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
                    inputHtml = `<textarea class="form-control form-control-sm sf-val" data-idx="${idx}" rows="2" placeholder='["a","b"] or comma-separated'>${esc(Array.isArray(field.value) ? JSON.stringify(field.value) : field.value)}</textarea>`;
                    break;
                default: // string
                    inputHtml = `<input type="text" class="form-control form-control-sm sf-val" data-idx="${idx}" value="${esc(field.value)}" placeholder="Value or {{variable}}">`;
            }
        }

        // ── Toolbar below the input ──
        const modeTitle = isExpr ? 'Expression (JSONata) \u2013 click for Text' : 'Text (literal) \u2013 click for Expression';
        const modeIcon  = isExpr ? '<i class="bi bi-lightning-charge-fill"></i>' : '<i class="bi bi-fonts"></i>';
        const varBtnHtml = showVarBtn
            ? `<button class="btn btn-sm btn-outline-secondary sf-var-insert" type="button" data-idx="${idx}" title="Insert variable"><i class="bi bi-braces"></i> Variables</button>`
            : '';
        const exprBuilderHtml = isExpr
            ? `<button class="btn btn-sm btn-outline-warning sf-expr-builder" type="button" data-idx="${idx}" title="Expression Builder"><i class="bi bi-tools"></i></button>`
            : '';

        return `<div class="sf-field-wrap">
            ${inputHtml}
            <div class="sf-field-toolbar">
                <button class="btn btn-sm sf-mode-toggle ${isExpr ? 'sf-mode-expr' : 'sf-mode-text'}" type="button" data-idx="${idx}" title="${modeTitle}">${modeIcon}</button>
                ${varBtnHtml}${exprBuilderHtml}
            </div>
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
                    // Pass nodeId + idx so same-node earlier fields appear in the builder
                    openExpressionBuilder(
                        field.value || '',
                        field.name || 'Field ' + (idx + 1),
                        (newVal) => {
                            field.value = newVal;
                            syncAndRedraw();
                        },
                        node.id,
                        idx
                    );
                });
            });

            // Variable insert buttons ({{}} braces) — in set_variable rows
            document.querySelectorAll('#sfFieldsList .sf-var-insert').forEach(btn => {
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    const isExprRow = !!btn.closest('.sf-field-wrap')?.querySelector('.sf-expr-input');
                    const valInput = btn.closest('.sf-field-wrap')?.querySelector('.sf-val, .sf-expr-input');
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
            // Keep the browser URL in sync so refresh always reloads the correct flow
            history.replaceState(null, '', `/flow-designer/${data.id}`);
            document.getElementById('flowName').textContent = data.name;
            document.getElementById('flowVersion').textContent = 'v' + data.version;

            // ── Restored indicator ────────────────────────────────────────────
            const restBadge = document.getElementById('flowRestoredBadge');
            if (restBadge) {
                if (data.is_restored) {
                    restBadge.textContent = `↺ Restored from v${data.restored_from_version || '?'}`;
                    restBadge.classList.remove('d-none');
                } else {
                    restBadge.classList.add('d-none');
                }
            }

            // ── Publish button colour ─────────────────────────────────────────
            const pubBtn = document.getElementById('btnPublish');
            if (pubBtn) {
                pubBtn.className = data.is_published
                    ? 'btn btn-sm btn-success'
                    : 'btn btn-sm btn-outline-success';
            }
            const timeoutEl = document.getElementById('flowDisconnectTimeout');
            if (timeoutEl) timeoutEl.value = data.disconnect_timeout_seconds ?? '';
            // store selected outcome id for when the settings modal opens
            const outcomeEl = document.getElementById('flowDisconnectOutcome');
            if (outcomeEl) outcomeEl.dataset.selected = data.disconnect_outcome_id ?? '';

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

            // Re-apply analytics overlay if it was active when flow reloaded
            if (_analyticsActive) loadAnalyticsOverlay();
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
                await loadFlow(flowId);  // refresh version badge + button state
            } else {
                const err = await res.json();
                showToast(err.detail || 'Publish failed', 'warning');
            }
        } catch (err) {
            showToast('Publish error', 'danger');
        }
    });

    document.getElementById('btnSave').addEventListener('click', () => saveFlow());

    // ───── Clone (top-bar button) ─────

    document.getElementById('btnCloneFlow')?.addEventListener('click', async () => {
        if (!flowId) { showToast('Open a flow first', 'warning'); return; }
        if (!confirm('Clone this flow? A copy will be created (it will not replace the current flow).')) return;
        try {
            const resp = await apiFetch(`/api/v1/flows/${flowId}/clone`, { method: 'POST' });
            if (!resp || !resp.ok) { const e = await resp.text(); throw new Error(e); }
            const data = await resp.json();
            showToast(
                `Cloned as "${escapeHtml(data.name)}" — <a href="/flow-designer/${data.id}" class="text-white fw-bold">Open copy</a>`,
                'success'
            );
        } catch (err) {
            showToast('Clone failed: ' + err.message, 'danger');
        }
    });

    // ───── Flow Settings ─────

    document.getElementById('btnFlowSettings')?.addEventListener('click', async () => {
        if (!flowId) { showToast('Save the flow first', 'warning'); return; }
        // Pre-fill description
        const descEl = document.getElementById('flowSettingsDesc');
        if (descEl) descEl.value = flowData?.description || '';
        // Populate disconnect outcome dropdown
        const sel = document.getElementById('flowDisconnectOutcome');
        if (sel) {
            const selectedId = sel.dataset.selected || '';
            try {
                const or = await apiFetch('/api/v1/outcomes?active_only=true');
                const outcomes = or && or.ok ? await or.json() : [];
                const actionLabel = { end_interaction: 'End', flow_redirect: 'Redirect' };
                sel.innerHTML = '<option value="">&#8212; None / just close &#8212;</option>';
                outcomes.forEach(o => {
                    const opt = document.createElement('option');
                    opt.value = o.id;
                    const tag = actionLabel[o.action_type] || o.action_type || 'End';
                    opt.textContent = `${o.label} [${tag}]`;
                    if (String(o.id) === String(selectedId)) opt.selected = true;
                    sel.appendChild(opt);
                });
            } catch (e) { /* ignore */ }
        }
        new bootstrap.Modal(document.getElementById('flowSettingsModal')).show();
    });

    document.getElementById('btnSaveFlowSettings')?.addEventListener('click', async () => {
        if (!flowId) return;
        const val = parseInt(document.getElementById('flowDisconnectTimeout').value) || null;
        const outcomeId = document.getElementById('flowDisconnectOutcome')?.value || null;
        const desc = document.getElementById('flowSettingsDesc')?.value.trim() || null;
        try {
            const res = await apiFetch(`/api/v1/flows/${flowId}`, {
                method: 'PATCH',
                body: JSON.stringify({
                    disconnect_timeout_seconds: val,
                    disconnect_outcome_id: outcomeId,
                    description: desc,
                }),
            });
            if (res && res.ok) {
                // Update cached data
                if (flowData) flowData.description = desc;
                const outcomeSel = document.getElementById('flowDisconnectOutcome');
                if (outcomeSel) outcomeSel.dataset.selected = outcomeId ?? '';
                showToast('Flow settings saved', 'success');
                bootstrap.Modal.getInstance(document.getElementById('flowSettingsModal'))?.hide();
            } else {
                showToast('Save failed', 'danger');
            }
        } catch (err) {
            showToast('Save error', 'danger');
        }
    });

    document.getElementById('btnNewFlow')?.addEventListener('click', () => {
        bootstrap.Modal.getInstance(document.getElementById('flowListModal'))?.hide();
        new bootstrap.Modal(document.getElementById('newFlowModal')).show();
    });

    document.getElementById('btnNewFlowAi')?.addEventListener('click', () => {
        showAiFlowBuilder();
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

    // Holds the full flow list so client-side filtering doesn't re-fetch
    let _allFlows = [];

    function _renderFlowList() {
        const listEl = document.getElementById('flowListItems');
        const q = (document.getElementById('flowListSearch')?.value || '').trim().toLowerCase();
        const statusSel = (document.getElementById('flowListStatusFilter')?.value || 'all');

        const visible = _allFlows.filter(f => {
            const matchText = !q ||
                f.name.toLowerCase().includes(q) ||
                (f.description || '').toLowerCase().includes(q);
            const matchStatus = statusSel === 'all' ||
                (statusSel === 'published' && f.is_published) ||
                (statusSel === 'draft' && !f.is_published);
            return matchText && matchStatus;
        });

        if (visible.length === 0) {
            listEl.innerHTML = `<p class="text-muted small">No flows match your filter.</p>`;
            return;
        }

        listEl.innerHTML = visible.map(f => {
            const pubBadge = f.is_published
                ? `<span class="wz-badge wz-status-published me-1">Published</span><span class="wz-badge wz-badge-muted me-2">v${f.version}</span>`
                : `<span class="wz-badge wz-status-draft me-1">Draft</span><span class="wz-badge wz-badge-muted me-2">v${f.version}</span>`;
            const desc = f.description ? `<div class="text-muted small mt-1">${escapeHtml(f.description)}</div>` : '';
            return `
            <div class="d-flex justify-content-between align-items-start py-2 border-bottom border-dark">
                <div class="flex-fill me-2">
                    <a href="#" class="text-decoration-none flow-list-item" data-id="${f.id}">${escapeHtml(f.name)}</a>
                    <div>${pubBadge}</div>
                    ${desc}
                </div>
                <div class="d-flex gap-1 flex-shrink-0">
                    <button class="btn btn-sm btn-outline-secondary" title="Clone flow"
                        onclick="window._cloneFlow('${f.id}')"><i class="bi bi-copy"></i></button>
                    <button class="btn btn-sm btn-outline-danger" title="Delete flow"
                        onclick="window._deleteFlow('${f.id}', ${JSON.stringify(escapeHtml(f.name))})"><i class="bi bi-trash"></i></button>
                </div>
            </div>`;
        }).join('');

        listEl.querySelectorAll('.flow-list-item').forEach(a => {
            a.addEventListener('click', (e) => {
                e.preventDefault();
                bootstrap.Modal.getInstance(document.getElementById('flowListModal'))?.hide();
                loadFlow(a.dataset.id);
            });
        });
    }

    async function showFlowList() {
        const listEl = document.getElementById('flowListItems');
        listEl.innerHTML = '<p class="text-muted">Loading...</p>';

        // Wire up filter controls once
        const searchEl = document.getElementById('flowListSearch');
        const filterEl = document.getElementById('flowListStatusFilter');
        if (searchEl && !searchEl.dataset.bound) {
            searchEl.dataset.bound = '1';
            searchEl.addEventListener('input', _renderFlowList);
            filterEl.addEventListener('change', _renderFlowList);
        }
        // Reset filters on each open so the user sees everything first
        if (searchEl) searchEl.value = '';
        if (filterEl) filterEl.value = 'all';

        new bootstrap.Modal(document.getElementById('flowListModal')).show();
        try {
            const res = await apiFetch('/api/v1/flows');
            if (res && res.ok) {
                _allFlows = await res.json();
                if (_allFlows.length === 0) {
                    listEl.innerHTML = '<p class="text-muted">No flows yet</p>';
                } else {
                    _renderFlowList();
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
                    const color = t.color || '#555';
                    groupHtml += `<div class="palette-node" draggable="true" data-type="${t.key}" title="${t.label}" style="border-left-color:${color}"><i class="bi ${t.icon}"></i><span class="palette-node-text">${t.label}</span></div>`;
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

    // ───── Version History ─────

    async function loadVersionHistory() {
        if (!flowId) return;
        const listEl = document.getElementById('historyList');
        if (!listEl) return;
        listEl.innerHTML = '<p class="text-muted small">Loading\u2026</p>';
        try {
            const resp = await apiFetch(`/api/v1/flows/${flowId}/versions`);
            if (!resp || !resp.ok) throw new Error('API error');
            const versions = await resp.json();
            if (!versions.length) {
                listEl.innerHTML = '<p class="text-muted small">No saved versions yet. Each save creates a snapshot here.</p>';
                return;
            }
            const rows = versions.map(v => {
                const dt = new Date(v.saved_at).toLocaleString('en-ZA', { dateStyle: 'short', timeStyle: 'short' });
                const nodeCount = (v.snapshot?.nodes || []).length;
                const edgeCount = (v.snapshot?.edges || []).length;
                return `<div class="d-flex align-items-center gap-2 border-bottom border-secondary py-2">
                    <div class="flex-fill">
                        <span class="badge bg-secondary me-2">v${v.version_number}</span>
                        <span class="fw-semibold small">${escapeHtml(v.label || 'Untitled')}</span>
                        <span class="text-muted ms-2 small">${dt}</span>
                        <span class="text-muted ms-2 small">${nodeCount} nodes \u00b7 ${edgeCount} edges</span>
                    </div>
                    <button class="btn btn-sm btn-outline-info flex-shrink-0"
                        onclick="window._openDiff('${v.id}', 'current')">
                        <i class="bi bi-subtract me-1"></i>Diff
                    </button>
                    <button class="btn btn-sm btn-outline-warning flex-shrink-0"
                        onclick="window._restoreVersion('${v.id}')">
                        <i class="bi bi-arrow-counterclockwise me-1"></i>Restore
                    </button>
                </div>`;
            }).join('');
            listEl.innerHTML = rows;
        } catch (err) {
            listEl.innerHTML = `<p class="text-danger small">Failed to load versions: ${escapeHtml(err.message)}</p>`;
        }
    }

    window._restoreVersion = async function(versionId) {
        if (!confirm('Restore this version? The current canvas will be saved first, then replaced.')) return;
        try {
            const resp = await apiFetch(`/api/v1/flows/${flowId}/versions/${versionId}/restore`, { method: 'POST' });
            if (!resp || !resp.ok) { const e = await resp.text(); throw new Error(e); }
            bootstrap.Modal.getInstance(document.getElementById('historyModal'))?.hide();
            await loadFlow(flowId);
            showToast('Flow restored', 'warning');
        } catch (err) {
            alert('Restore failed: ' + err.message);
        }
    };

    window._cloneFlow = async function(srcId) {
        if (!confirm('Clone this flow? A copy will be created (it will not be opened automatically).')) return;
        try {
            const resp = await apiFetch(`/api/v1/flows/${srcId}/clone`, { method: 'POST' });
            if (!resp || !resp.ok) { const e = await resp.text(); throw new Error(e); }
            const data = await resp.json();
            // Refresh the list so the copy appears, but do NOT navigate away from the current flow
            _allFlows = [];
            showToast(
                `Cloned as "${escapeHtml(data.name)}" — <a href="/flow-designer/${data.id}" class="text-white fw-bold">Open copy</a>`,
                'success'
            );
            // Re-fetch the list silently so the copy shows next time the modal opens
            try {
                const lr = await apiFetch('/api/v1/flows');
                if (lr && lr.ok) _allFlows = await lr.json();
                _renderFlowList();
            } catch (_) { /* ignore */ }
        } catch (err) {
            showToast('Clone failed: ' + err.message, 'danger');
        }
    };

    window._deleteFlow = async function(targetId, targetName) {
        // Fetch usage before confirming
        let usage = { connectors: [], sub_flow_parents: [], campaigns: [], outcomes: [] };
        try {
            const ur = await apiFetch(`/api/v1/flows/${targetId}/usage`);
            if (ur && ur.ok) usage = await ur.json();
        } catch (_) { /* ignore, proceed with plain confirm */ }

        const hasUsage = usage.connectors.length || usage.sub_flow_parents.length ||
                         usage.campaigns.length || usage.outcomes.length;

        // Build warning body
        const modalEl = document.getElementById('flowDeleteModal');
        document.getElementById('flowDeleteName').textContent = targetName;
        const warningEl = document.getElementById('flowDeleteWarning');

        if (hasUsage) {
            let html = '<p class="text-warning fw-semibold mb-2"><i class="bi bi-exclamation-triangle-fill me-1"></i>This flow is referenced by:</p><ul class="small mb-0">';
            usage.connectors.forEach(c => {
                const badge = c.is_active
                    ? '<span class="wz-badge wz-status-active ms-1">active</span>'
                    : '<span class="wz-badge wz-status-inactive ms-1">inactive</span>';
                html += `<li><strong>Connector:</strong> ${escapeHtml(c.name)}${badge}</li>`;
            });
            usage.sub_flow_parents.forEach(p => {
                html += `<li><strong>Sub-flow node</strong> "${escapeHtml(p.node_label)}" in flow <em>${escapeHtml(p.flow_name)}</em></li>`;
            });
            usage.campaigns.forEach(c => {
                html += `<li><strong>Campaign:</strong> ${escapeHtml(c.name)}</li>`;
            });
            usage.outcomes.forEach(o => {
                html += `<li><strong>Outcome redirect:</strong> ${escapeHtml(o.label)}</li>`;
            });
            html += '</ul><p class="mt-2 mb-0 text-danger small">These references will break. Connectors will stop routing. Active chat sessions on this flow will fail.</p>';
            warningEl.innerHTML = html;
            warningEl.classList.remove('d-none');
        } else {
            warningEl.innerHTML = '';
            warningEl.classList.add('d-none');
        }

        // Store id for the confirm button and close the list modal first
        document.getElementById('btnFlowDeleteConfirm').dataset.flowId = targetId;
        const listModal = bootstrap.Modal.getInstance(document.getElementById('flowListModal'));
        if (listModal) {
            // Wait for list modal to close, then open delete confirm
            document.getElementById('flowListModal').addEventListener('hidden.bs.modal', function _onHide() {
                document.getElementById('flowListModal').removeEventListener('hidden.bs.modal', _onHide);
                new bootstrap.Modal(modalEl).show();
            }, { once: true });
            listModal.hide();
        } else {
            new bootstrap.Modal(modalEl).show();
        }
    };

    document.getElementById('btnFlowDeleteConfirm')?.addEventListener('click', async function() {
        const targetId = this.dataset.flowId;
        if (!targetId) return;
        try {
            const resp = await apiFetch(`/api/v1/flows/${targetId}`, { method: 'DELETE' });
            if (!resp || !resp.ok) { const e = await resp.text(); throw new Error(e); }
            // Clear id BEFORE hiding so hidden.bs.modal knows delete succeeded (skip reopen)
            this.dataset.flowId = '';
            bootstrap.Modal.getInstance(document.getElementById('flowDeleteModal'))?.hide();
            // If we just deleted the open flow, clear the canvas
            if (String(targetId) === String(flowId)) {
                flowId = null; flowData = null;
                document.getElementById('flowName').textContent = 'No flow open';
                document.getElementById('flowVersion').textContent = '';
                document.getElementById('canvas').innerHTML = '';
                document.getElementById('edgeSvg').innerHTML = '';
            }
            showToast('Flow deleted', 'success');
            await showFlowList();
        } catch (err) {
            showToast('Delete failed: ' + err.message, 'danger');
        }
    });

    // Reopen flow list when delete modal is dismissed via Cancel / X (not after a successful delete)
    document.getElementById('flowDeleteModal')?.addEventListener('hidden.bs.modal', function() {
        const btn = document.getElementById('btnFlowDeleteConfirm');
        if (btn.dataset.flowId) {
            // Cancel path: id still set → user did not confirm → reopen list
            btn.dataset.flowId = '';
            showFlowList();
        }
    });

    // ───── Flow Diff engine ─────

    // Normalise a snapshot node to a comparable shape.
    // Uses node_type+label as the identity key — robust to ID churn.
    function _normNode(n) {
        return {
            type: n.node_type || n.type || '',
            label: (n.label || '').trim(),
            config: n.config || {},
        };
    }
    function _nodeKey(n) {
        // Primary key: type + label (lowercased, trimmed)
        return `${(n.node_type || n.type || '').toLowerCase()}::${(n.label || '').trim().toLowerCase()}`;
    }
    function _edgeKey(nodes, e) {
        // Key by (source node key → handle → target node key)
        const src = nodes.find(n => String(n.id || n.node_id) === String(e.source_node_id || e.sourceId));
        const tgt = nodes.find(n => String(n.id || n.node_id) === String(e.target_node_id || e.targetId));
        const sk = src ? _nodeKey(src) : String(e.source_node_id || e.sourceId || '');
        const tk = tgt ? _nodeKey(tgt) : String(e.target_node_id || e.targetId || '');
        const h = e.source_handle || e.sourceHandle || 'default';
        return `${sk}--[${h}]-->${tk}`;
    }

    // Deep compare two plain objects; return list of changed keys at top level.
    function _configDiff(a, b) {
        const allKeys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
        const changed = [];
        allKeys.forEach(k => {
            if (k.startsWith('_')) return; // skip internal keys
            const av = JSON.stringify((a || {})[k] ?? null);
            const bv = JSON.stringify((b || {})[k] ?? null);
            if (av !== bv) changed.push({ key: k, from: (a || {})[k], to: (b || {})[k] });
        });
        return changed;
    }

    // Core diff: takes two {nodes:[], edges:[]} snapshots and returns a structured result.
    function diffSnapshots(snapA, snapB, labelA = 'A', labelB = 'B') {
        const nodesA = (snapA.nodes || []);
        const nodesB = (snapB.nodes || []);

        const mapA = new Map(nodesA.map(n => [_nodeKey(n), n]));
        const mapB = new Map(nodesB.map(n => [_nodeKey(n), n]));

        const added = [];       // in B, not in A
        const removed = [];     // in A, not in B
        const modified = [];    // in both, but config changed
        const unchanged = [];   // in both, config same

        mapB.forEach((nb, key) => {
            if (!mapA.has(key)) {
                added.push(_normNode(nb));
            } else {
                const na = mapA.get(key);
                const diffs = _configDiff(na.config, nb.config);
                if (diffs.length) modified.push({ ..._normNode(nb), changes: diffs });
                else unchanged.push(_normNode(nb));
            }
        });
        mapA.forEach((na, key) => {
            if (!mapB.has(key)) removed.push(_normNode(na));
        });

        // Edge diff
        const edgesA = (snapA.edges || []).map(e => _edgeKey(nodesA, e));
        const edgesB = (snapB.edges || []).map(e => _edgeKey(nodesB, e));
        const setA = new Set(edgesA);
        const setB = new Set(edgesB);
        const edgesAdded = edgesB.filter(k => !setA.has(k));
        const edgesRemoved = edgesA.filter(k => !setB.has(k));

        return { added, removed, modified, unchanged, edgesAdded, edgesRemoved, labelA, labelB };
    }

    // Convert the live canvas state to snapshot format
    function _currentSnapshot() {
        return {
            nodes: nodes.map(n => ({
                id: n.id, node_type: n.type, label: n.label || '',
                position_x: n.x, position_y: n.y, config: n.config || {}, position: 0,
            })),
            edges: edges.map(e => ({
                id: e.id, source_node_id: e.sourceId, target_node_id: e.targetId,
                source_handle: e.sourceHandle || 'default', label: e.label || '',
            })),
        };
    }

    // Render a diff result into #diffBody
    function _renderDiff(result) {
        const { added, removed, modified, unchanged, edgesAdded, edgesRemoved, labelA, labelB } = result;

        // Summary bar
        const sumBar = document.getElementById('diffSummaryBar');
        if (sumBar) {
            sumBar.classList.remove('d-none');
            document.getElementById('diffSumAdded').textContent = `+ ${added.length} added`;
            document.getElementById('diffSumRemoved').textContent = `\u2212 ${removed.length} removed`;
            document.getElementById('diffSumModified').textContent = `\u00b1 ${modified.length} modified`;
            document.getElementById('diffSumUnchanged').textContent = `${unchanged.length} unchanged`;
            document.getElementById('diffSumEdges').textContent =
                `Edges: +${edgesAdded.length} / \u2212${edgesRemoved.length}`;
        }

        const body = document.getElementById('diffBody');
        if (!body) return;

        if (!added.length && !removed.length && !modified.length && !edgesAdded.length && !edgesRemoved.length) {
            body.innerHTML = `<div class="text-center text-success py-5">
                <i class="bi bi-check-circle-fill display-4 mb-3"></i>
                <p class="fw-semibold">No differences — these two versions are identical.</p>
            </div>`;
            return;
        }

        function nodeRow(n, cls, icon) {
            const cfgStr = Object.keys(n.config || {}).filter(k => !k.startsWith('_')).length
                ? Object.entries(n.config).filter(([k]) => !k.startsWith('_'))
                    .map(([k, v]) => `<span class="badge bg-secondary me-1 fw-normal">${escapeHtml(k)}: ${escapeHtml(String(v)).slice(0, 40)}</span>`).join('')
                : '<span class="text-muted small">no config</span>';
            return `<tr class="${cls}">
                <td><i class="bi ${icon} me-1"></i>${escapeHtml(n.type.replace(/_/g, ' '))}</td>
                <td>${escapeHtml(n.label || '\u2014')}</td>
                <td style="font-size:0.75rem;">${cfgStr}</td>
            </tr>`;
        }

        function modRow(n) {
            const changes = n.changes.map(c =>
                `<div class="mb-1"><strong class="small">${escapeHtml(c.key)}</strong><br>
                <span class="text-danger small font-monospace">\u2212 ${escapeHtml(JSON.stringify(c.from)).slice(0, 80)}</span><br>
                <span class="text-success small font-monospace">+ ${escapeHtml(JSON.stringify(c.to)).slice(0, 80)}</span></div>`
            ).join('');
            return `<tr>
                <td><span class="badge bg-warning text-dark">${escapeHtml(n.type.replace(/_/g, ' '))}</span></td>
                <td>${escapeHtml(n.label || '\u2014')}</td>
                <td style="font-size:0.75rem;">${changes}</td>
            </tr>`;
        }

        function section(title, colorCls, rows, emptyMsg) {
            if (!rows.length) return `<div class="mb-4">
                <h6 class="text-muted small text-uppercase mb-2">${title}</h6>
                <p class="text-muted small">${emptyMsg}</p></div>`;
            return `<div class="mb-4">
                <h6 class="${colorCls} small text-uppercase mb-2">${title} <span class="badge bg-secondary ms-1">${rows.length}</span></h6>
                <table class="table table-sm table-dark table-bordered mb-0" style="font-size:0.82rem;">
                    <thead class="table-secondary"><tr><th style="width:120px">Type</th><th style="width:160px">Label</th><th>Config</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>`;
        }

        function edgeSection(title, colorCls, edgeKeys, emptyMsg) {
            if (!edgeKeys.length) return `<div class="mb-4">
                <h6 class="text-muted small text-uppercase mb-2">${title}</h6>
                <p class="text-muted small">${emptyMsg}</p></div>`;
            const rows = edgeKeys.map(k =>
                `<tr><td class="font-monospace small" style="font-size:0.75rem;">${escapeHtml(k)}</td></tr>`
            ).join('');
            return `<div class="mb-4">
                <h6 class="${colorCls} small text-uppercase mb-2">${title} <span class="badge bg-secondary ms-1">${edgeKeys.length}</span></h6>
                <table class="table table-sm table-dark table-bordered mb-0">
                    <tbody>${rows}</tbody>
                </table></div>`;
        }

        const addedRows = added.map(n => nodeRow(n, 'table-success', 'bi-plus-circle-fill'));
        const removedRows = removed.map(n => nodeRow(n, 'table-danger', 'bi-dash-circle-fill'));
        const modRows = modified.map(modRow);

        body.innerHTML =
            `<p class="text-muted small mb-3"><strong>${escapeHtml(labelA)}</strong> \u2192 <strong>${escapeHtml(labelB)}</strong></p>` +
            section('Added nodes', 'text-success', addedRows, 'No nodes added.') +
            section('Removed nodes', 'text-danger', removedRows, 'No nodes removed.') +
            section('Modified nodes', 'text-warning', modRows, 'No nodes modified.') +
            edgeSection('Edges added', 'text-success', edgesAdded, 'No edges added.') +
            edgeSection('Edges removed', 'text-danger', edgesRemoved, 'No edges removed.');
    }

    // Fetch a version snapshot (or null to use current canvas)
    async function _fetchSnapshot(id) {
        if (id === 'current') return { snap: _currentSnapshot(), label: 'Current canvas' };
        const resp = await apiFetch(`/api/v1/flows/${flowId}/versions`);
        if (!resp || !resp.ok) throw new Error('Cannot fetch versions');
        const all = await resp.json();
        const v = all.find(x => x.id === id);
        if (!v) throw new Error('Version not found');
        const dt = new Date(v.saved_at).toLocaleString('en-ZA', { dateStyle: 'short', timeStyle: 'short' });
        return { snap: v.snapshot, label: `v${v.version_number} (${dt})` };
    }

    // Populate both selects in the diff modal with available versions
    async function _populateDiffSelects(presetLeftId) {
        if (!flowId) return;
        const leftSel = document.getElementById('diffLeftSel');
        const rightSel = document.getElementById('diffRightSel');
        if (!leftSel || !rightSel) return;

        const resp = await apiFetch(`/api/v1/flows/${flowId}/versions`);
        const versions = (resp && resp.ok) ? await resp.json() : [];

        function makeOpts(selected) {
            const cur = `<option value="current" ${selected === 'current' ? 'selected' : ''}>Current canvas</option>`;
            const vOpts = versions.map(v => {
                const dt = new Date(v.saved_at).toLocaleString('en-ZA', { dateStyle: 'short', timeStyle: 'short' });
                const sel = v.id === selected ? 'selected' : '';
                return `<option value="${v.id}" ${sel}>v${v.version_number} \u2014 ${escapeHtml(v.label || 'Untitled')} (${dt})</option>`;
            }).join('');
            return cur + vOpts;
        }

        leftSel.innerHTML = makeOpts(presetLeftId || 'current');
        // Right default: first saved version (index 0), or current if none
        const rightDefault = (presetLeftId && presetLeftId !== 'current') ? 'current' : (versions[0]?.id || 'current');
        rightSel.innerHTML = makeOpts(rightDefault);
    }

    // Open the diff modal  (versionId = the "left" side, target = "right", defaults to current)
    window._openDiff = async function(versionId, target = 'current') {
        // Close history modal first
        bootstrap.Modal.getInstance(document.getElementById('historyModal'))?.hide();

        // Reset body
        const body = document.getElementById('diffBody');
        if (body) body.innerHTML = '<p class="text-muted small text-center py-4">Loading\u2026</p>';
        const sumBar = document.getElementById('diffSummaryBar');
        if (sumBar) sumBar.classList.add('d-none');

        const modal = new bootstrap.Modal(document.getElementById('diffModal'));
        modal.show();

        await _populateDiffSelects(versionId);

        // Auto-run with defaults
        const leftSel = document.getElementById('diffLeftSel');
        const rightSel = document.getElementById('diffRightSel');
        if (leftSel) leftSel.value = versionId || 'current';
        if (rightSel) rightSel.value = target;

        await _runDiff();
    };

    async function _runDiff() {
        const leftId = document.getElementById('diffLeftSel')?.value;
        const rightId = document.getElementById('diffRightSel')?.value;
        if (!leftId || !rightId) return;
        if (leftId === rightId) {
            const body = document.getElementById('diffBody');
            if (body) body.innerHTML = '<p class="text-warning text-center py-4">Select two different versions to compare.</p>';
            return;
        }
        const body = document.getElementById('diffBody');
        if (body) body.innerHTML = '<p class="text-muted small text-center py-4"><span class="spinner-border spinner-border-sm me-2"></span>Computing diff\u2026</p>';
        try {
            const [{ snap: snapA, label: labA }, { snap: snapB, label: labB }] = await Promise.all([
                _fetchSnapshot(leftId),
                _fetchSnapshot(rightId),
            ]);
            _renderDiff(diffSnapshots(snapA, snapB, labA, labB));
        } catch (err) {
            if (body) body.innerHTML = `<p class="text-danger small text-center py-4">Diff failed: ${escapeHtml(err.message)}</p>`;
        }
    }

    // ───── Flow Simulator UI ─────

    let _simVarRawMode = false;

    function buildSimVarRows(ctx) {
        _simVarRawMode = false;
        const container = document.getElementById('simVarRows');
        if (!container) return;
        container.innerHTML = '';
        const entries = Object.entries(ctx || {});
        if (!entries.length) {
            _addSimVarRow('', '');
        } else {
            entries.forEach(([k, v]) =>
                _addSimVarRow(k, typeof v === 'object' ? JSON.stringify(v) : String(v))
            );
        }
        // Hide raw textarea when in row mode
        const ta = document.getElementById('testContextInput');
        if (ta) ta.classList.add('d-none');
        const rawBtn = document.getElementById('btnToggleRawCtx');
        if (rawBtn) rawBtn.textContent = 'JSON';
    }

    function _addSimVarRow(key, val) {
        const container = document.getElementById('simVarRows');
        if (!container) return;
        const row = document.createElement('div');
        row.className = 'd-flex gap-1 mb-1 sim-var-row align-items-center';
        row.innerHTML = `
            <input type="text" class="form-control form-control-sm sim-var-key" placeholder="variable" value="${escapeHtml(String(key || ''))}" style="flex:2">
            <input type="text" class="form-control form-control-sm sim-var-val" placeholder="value" value="${escapeHtml(String(val || ''))}" style="flex:3">
            <button type="button" class="btn btn-sm btn-outline-danger sim-var-del px-2" title="Remove">&times;</button>
        `;
        row.querySelector('.sim-var-del').addEventListener('click', () => row.remove());
        container.appendChild(row);
    }

    function getSimContext() {
        if (_simVarRawMode) {
            const raw = document.getElementById('testContextInput')?.value?.trim() || '{}';
            try { return JSON.parse(raw); } catch { return {}; }
        }
        const ctx = {};
        document.querySelectorAll('.sim-var-row').forEach(row => {
            const k = row.querySelector('.sim-var-key')?.value?.trim();
            const v = row.querySelector('.sim-var-val')?.value?.trim();
            if (k) {
                try { ctx[k] = JSON.parse(v); } catch { ctx[k] = v || ''; }
            }
        });
        return ctx;
    }

    function initTestPanel() {
        // Populate seed variable rows from sample context
        const sampleCtx = buildSampleContext();
        buildSimVarRows(sampleCtx);

        // ── Entry-point selector ─────────────────────────────────────────
        const entrySection = document.getElementById('simEntrySection');
        const entrySelect  = document.getElementById('simEntrySelect');
        const entryNodes   = nodes.filter(n => ENTRY_NODE_TYPES.has(n.type));
        if (entrySection && entrySelect) {
            entrySelect.innerHTML = '';
            entryNodes.forEach(n => {
                const icon = {
                    start_chat: '💬', start_whatsapp: '📱', start_api: '⚡',
                    start_voice: '📞', start_email: '📧', start_sms: '💬',
                    start_chat_ended: '❌', start_call_ended: '📵', start_internal_call: '🔁',
                    start_sla_breached: '⏰', start_contact_imported: '👤', start_contact_status_changed: '🔄',
                    start: '▶',
                }[n.type] || '▶';
                const lbl = n.config?.entry_label || n.config?.trigger_key || n.label || n.type.replace(/_/g, ' ');
                const opt = document.createElement('option');
                opt.value = n.id;
                opt.textContent = `${icon} ${lbl}`;
                entrySelect.appendChild(opt);
            });
            // Show selector only if the flow has more than one entry node
            entrySection.classList.toggle('d-none', entryNodes.length <= 1);
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
                <label class="form-label small fw-semibold">${escapeHtml(label)} <span class="text-muted">(\u2192 ${escapeHtml(varName)})</span></label>
                <input type="text" class="form-control form-control-sm test-node-input" data-node-id="${n.id}" data-var="${escapeHtml(varName)}" placeholder="Simulated user input\u2026">
            `;
            container.appendChild(group);
        });
    }

    async function runSimulation() {
        // Collect context from seed variable builder (or raw JSON textarea)
        const context = getSimContext();

        // Collect node inputs
        const inputs = {};
        document.querySelectorAll('.test-node-input').forEach(el => {
            const nid = el.dataset.nodeId;
            if (nid && el.value.trim()) inputs[nid] = el.value.trim();
        });

        // Entry node to simulate from (undefined = server picks first)
        const entryNodeId = (() => {
            const sel = document.getElementById('simEntrySelect');
            return sel && sel.closest('#simEntrySection') && !sel.closest('#simEntrySection').classList.contains('d-none')
                ? sel.value || null
                : null;
        })();

        // UI: loading
        const btn = document.getElementById('btnRunSim');
        if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running\u2026'; }

        try {
            const httpResp = await apiFetch(`/api/v1/flows/${flowId}/simulate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ context, inputs, entry_node_id: entryNodeId })
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
            // Entry Points
            start_chat:     'bg-info text-dark', start_whatsapp: 'bg-success',
            start_api:      'bg-purple',          start_voice:    'bg-orange',
            start_email:    'bg-primary',          start_sms:      'bg-teal',
            start_chat_ended: 'bg-secondary',     start_call_ended: 'bg-secondary',
            start_internal_call: 'bg-primary',    start_sla_breached: 'bg-danger',
            start_contact_imported: 'bg-info text-dark', start_contact_status_changed: 'bg-purple',
            start_chat_ended: 'bg-secondary',     start_call_ended: 'bg-secondary',
            start_internal_call: 'bg-primary',    start_sla_breached: 'bg-danger',
            start_contact_imported: 'bg-info text-dark', start_contact_status_changed: 'bg-purple',
            // Flow Control
            start: 'bg-success', end: 'bg-dark', message: 'bg-primary', condition: 'bg-warning text-dark',
            input: 'bg-info text-dark', menu: 'bg-info text-dark', dtmf: 'bg-info text-dark',
            set_variable: 'bg-secondary', http_request: 'bg-primary', ai_bot: 'bg-purple',
            transfer: 'bg-danger', queue: 'bg-danger', wait: 'bg-secondary',
            play_audio: 'bg-success', record: 'bg-warning text-dark', goto: 'bg-light text-dark',
            sub_flow: 'bg-light text-dark', webhook: 'bg-orange', switch: 'bg-warning text-dark',
            ab_split: 'bg-purple', loop: 'bg-success', time_gate: 'bg-info text-dark',
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

    // ───── Flow Analytics Overlay ─────

    /**
     * Lerp between two [r,g,b] colours.
     * t = 0 → a, t = 1 → b
     */
    function _lerpRgb(a, b, t) {
        return [
            Math.round(a[0] + (b[0] - a[0]) * t),
            Math.round(a[1] + (b[1] - a[1]) * t),
            Math.round(a[2] + (b[2] - a[2]) * t),
        ];
    }

    /**
     * Map 0–1 heat value to an rgb() string.
     * 0  = cool grey-blue,  0.5 = amber,  1 = hot red.
     */
    function _heatColor(t) {
        const cold   = [80,  90, 120];
        const warm   = [220, 140,  0];
        const hot    = [210,  30, 30];
        const [r, g, b] = t < 0.5
            ? _lerpRgb(cold, warm, t * 2)
            : _lerpRgb(warm, hot,  (t - 0.5) * 2);
        return `rgb(${r},${g},${b})`;
    }

    /**
     * Fetch analytics data then apply heatmap to nodes and edges.
     */
    async function loadAnalyticsOverlay() {
        if (!flowId) return;
        const resp = await apiFetch(`/api/v1/flows/${flowId}/analytics?window=${_analyticsWindow}`);
        if (!resp.ok) { console.warn('Analytics fetch failed'); return; }
        const data = await resp.json();

        // Support both old (array) and new (object with nodes/edges) response shapes
        const stats  = Array.isArray(data) ? data : (data.nodes  || []);
        const eStats = Array.isArray(data) ? []   : (data.edges  || []);

        _analyticsMap.clear();
        _analyticsEdgeMap.clear();
        stats.forEach(s => _analyticsMap.set(s.node_id, s));
        eStats.forEach(e => _analyticsEdgeMap.set(`${e.source_id}→${e.target_id}`, e));
        _analyticsMax = Math.max(1, ...stats.map(s => s.visit_count));

        _applyAnalyticsToNodes();
        renderEdges();  // re-draw to add traffic labels
    }

    function _applyAnalyticsToNodes() {
        nodes.forEach(n => {
            if (!n.el) return;
            const stat = _analyticsMap.get(n.id);
            const count = stat ? stat.visit_count : 0;
            const errorCount = stat ? (stat.error_count || 0) : 0;
            const abandonCount = stat ? (stat.abandon_count || 0) : 0;
            const t = count / _analyticsMax;
            const color = _heatColor(t);

            // Tint the node header
            const header = n.el.querySelector('.node-header');
            if (header) header.style.backgroundColor = color;

            // Remove any existing stats bar, then rebuild
            n.el.querySelectorAll('.analytics-stats-bar, .analytics-node-badge, .analytics-heat-bar, .analytics-error-badge, .analytics-abandon-badge').forEach(x => x.remove());

            // ── 3-part bottom stats strip ────────────────────────────────
            // Shows: [visits | ✕ abandons | ⚠ errors]
            const bar = document.createElement('div');
            bar.className = 'analytics-stats-bar';
            bar.title = [
                `Visits: ${count}`,
                `Disconnects: ${abandonCount}`,
                `Errors: ${errorCount}`,
                stat?.last_visited_at ? `Last: ${stat.last_visited_at}` : '',
            ].filter(Boolean).join('  |  ');

            // Visits segment (heat-coloured, left)
            const visSpan = document.createElement('span');
            visSpan.className = 'asb-visits';
            visSpan.style.background = count > 0 ? color : 'rgba(80,80,80,0.55)';
            visSpan.textContent = count > 999 ? `${(count/1000).toFixed(1)}k` : String(count);
            bar.appendChild(visSpan);

            // Disconnect / abandon segment (orange, always shown)
            const abSpan = document.createElement('span');
            abSpan.className = 'asb-abandon';
            abSpan.textContent = `\u2715 ${abandonCount}`;
            bar.appendChild(abSpan);

            // Error segment (red, always shown)
            const errSpan = document.createElement('span');
            errSpan.className = 'asb-error';
            errSpan.textContent = `\u26A0 ${errorCount}`;
            bar.appendChild(errSpan);

            n.el.appendChild(bar);
        });
    }

    function clearAnalyticsOverlay() {
        nodes.forEach(n => {
            if (!n.el) return;
            const header = n.el.querySelector('.node-header');
            if (header) header.style.backgroundColor = '';
            n.el.querySelectorAll('.analytics-stats-bar, .analytics-node-badge, .analytics-heat-bar, .analytics-error-badge, .analytics-abandon-badge').forEach(x => x.remove());
        });
        _analyticsMap.clear();
        _analyticsEdgeMap.clear();
        renderEdges();  // re-draw without traffic labels
    }

    async function toggleAnalyticsOverlay() {
        _analyticsActive = !_analyticsActive;
        const btn = document.getElementById('btnAnalyticsOverlay');
        if (_analyticsActive) {
            if (btn) { btn.classList.add('active', 'btn-info'); btn.classList.remove('btn-outline-secondary'); }
            await loadAnalyticsOverlay();
        } else {
            if (btn) { btn.classList.remove('active', 'btn-info'); btn.classList.add('btn-outline-secondary'); }
            clearAnalyticsOverlay();
        }
    }

    /** Set the analytics time window and reload if the overlay is already active. */
    async function setAnalyticsWindow(minutes) {
        _analyticsWindow = minutes;
        // Update active state in dropdown
        document.querySelectorAll('#analyticsWindowMenu .dropdown-item').forEach(el => {
            const w = parseInt(el.dataset.window, 10);
            el.classList.toggle('active', w === minutes);
        });
        // Update split-button label to show the chosen window
        const LABELS = { 0: 'All', 5: '5m', 10: '10m', 30: '30m', 60: '1h', 150: '150m', 1440: '1d' };
        const btn = document.getElementById('btnAnalyticsOverlay');
        if (btn) {
            const lbl = LABELS[minutes] ?? `${minutes}m`;
            btn.innerHTML = `<i class="bi bi-fire me-1"></i>Heatmap <span class="badge bg-secondary ms-1" style="font-size:0.65rem;">${lbl}</span>`;
        }
        // Refresh data if overlay is currently showing
        if (_analyticsActive) await loadAnalyticsOverlay();
    }

    // ───── Bulk Variable Editor ─────

    /** HTML-escape a string for safe attribute/text insertion */
    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /**
     * Open the bulk variable editor offcanvas.
     * Populates it with every set_variable node's fields.
     */
    function openVarEditor() {
        _renderVarEditor('');
        const filterInput = document.getElementById('varEditorFilter');
        if (filterInput) {
            filterInput.value = '';
            filterInput.oninput = () => _renderVarEditor(filterInput.value.trim().toLowerCase());
        }
        const saveBtn = document.getElementById('btnVarEditorSave');
        if (saveBtn) {
            saveBtn.onclick = () => {
                saveFlow();
                const oc = bootstrap.Offcanvas.getInstance(document.getElementById('varEditorOffcanvas'));
                if (oc) oc.hide();
            };
        }
        new bootstrap.Offcanvas(document.getElementById('varEditorOffcanvas')).show();
    }

    /**
     * Re-render the variable editor table, optionally filtered by a search string.
     * Changes write directly into node.config.fields[] in memory.
     */
    function _renderVarEditor(filter) {
        const svNodes = nodes.filter(n => n.type === 'set_variable');
        svNodes.forEach(n => ensureFieldsArray(n));

        const badge = document.getElementById('varEditorNodeCount');
        if (badge) badge.textContent = `${svNodes.length} node${svNodes.length !== 1 ? 's' : ''}`;

        const tbody = document.getElementById('varEditorBody');
        const empty = document.getElementById('varEditorEmpty');
        if (!tbody) return;

        if (svNodes.length === 0) {
            tbody.innerHTML = '';
            if (empty) empty.classList.remove('d-none');
            return;
        }
        if (empty) empty.classList.add('d-none');

        const rows = [];
        let totalVars = 0;

        svNodes.forEach((n, ni) => {
            const fields = n.config.fields || [];
            const nodeLabel = n.config.label || `Set Variable #${ni + 1}`;
            const nodeId = n.id;

            const matchingFields = fields
                .map((f, fi) => ({ f, fi }))
                .filter(({ f }) => {
                    if (!filter) return true;
                    return (f.name || '').toLowerCase().includes(filter)
                        || String(f.value ?? '').toLowerCase().includes(filter)
                        || nodeLabel.toLowerCase().includes(filter);
                });

            if (matchingFields.length === 0 && filter) return;
            totalVars += matchingFields.length;

            // Section header row for the node
            rows.push(`<tr class="table-dark">
                <td colspan="4" class="py-1 px-2">
                    <span class="text-info fw-semibold" style="font-size:0.8rem;">
                        <i class="bi bi-braces me-1 opacity-75"></i>${_esc(nodeLabel)}
                    </span>
                    <button class="btn btn-link btn-sm text-warning p-0 ms-2" style="font-size:0.75rem;"
                            title="Jump to this node on canvas"
                            onclick="window._varEditorJump('${nodeId}')">
                        <i class="bi bi-crosshair me-1"></i>Jump
                    </button>
                    <span class="text-muted ms-2" style="font-size:0.72rem;">${fields.length} var${fields.length !== 1 ? 's' : ''}</span>
                </td>
            </tr>`);

            if (matchingFields.length === 0) {
                rows.push(`<tr>
                    <td colspan="4" class="text-muted ps-3" style="font-size:0.78rem;font-style:italic;">
                        No variables defined yet.
                    </td>
                </tr>`);
            } else {
                matchingFields.forEach(({ f, fi }) => {
                    // Type select using FIELD_TYPES objects correctly
                    const typeOpts = FIELD_TYPES.map(t =>
                        `<option value="${t.value}"${t.value === f.type ? ' selected' : ''}>${t.label}</option>`
                    ).join('');

                    // Full-featured value widget (handles all types + expression + var-picker)
                    const valueWidget = fieldValueInput(f, fi);

                    rows.push(`<tr data-node-id="${nodeId}" data-field-idx="${fi}">
                        <td class="align-middle" style="width:26%;">
                            <input type="text" class="form-control form-control-sm ve-name border-0 bg-transparent"
                                   data-node-id="${nodeId}" data-field-idx="${fi}"
                                   value="${_esc(f.name || '')}" placeholder="variable_name"
                                   style="font-family:monospace;font-size:0.78rem;color:#e2b96f;">
                        </td>
                        <td class="align-middle" style="width:13%;">
                            <select class="form-select form-select-sm ve-type border-0 bg-transparent"
                                    data-node-id="${nodeId}" data-field-idx="${fi}"
                                    style="font-size:0.76rem;">
                                ${typeOpts}
                            </select>
                        </td>
                        <td class="align-middle">
                            ${valueWidget}
                        </td>
                        <td class="align-middle text-center" style="width:72px;">
                            <div class="d-flex align-items-center justify-content-center gap-1">
                                <div class="d-flex flex-column" style="gap:0;">
                                    <button class="btn btn-link p-0" style="font-size:0.65rem;line-height:1.1;color:#adb5bd;"
                                            title="Move up" ${fi === 0 ? 'disabled' : ''}
                                            onclick="window._varEditorMove('${nodeId}', ${fi}, -1)">
                                        <i class="bi bi-chevron-up"></i>
                                    </button>
                                    <button class="btn btn-link p-0" style="font-size:0.65rem;line-height:1.1;color:#adb5bd;"
                                            title="Move down" ${fi === fields.length - 1 ? 'disabled' : ''}
                                            onclick="window._varEditorMove('${nodeId}', ${fi}, 1)">
                                        <i class="bi bi-chevron-down"></i>
                                    </button>
                                </div>
                                <button class="btn btn-sm btn-link text-danger p-0"
                                        title="Remove this variable"
                                        onclick="window._varEditorRemove('${nodeId}', ${fi})">
                                    <i class="bi bi-trash2"></i>
                                </button>
                            </div>
                        </td>
                    </tr>`);
                });
            }

            // Add variable row (shown when no filter active)
            if (!filter) {
                rows.push(`<tr class="table-secondary">
                    <td colspan="4" class="ps-3 py-1">
                        <button class="btn btn-link btn-sm text-success p-0" style="font-size:0.78rem;"
                                onclick="window._varEditorAddField('${nodeId}')">
                            <i class="bi bi-plus-circle me-1"></i>Add variable to <em>${_esc(nodeLabel)}</em>
                        </button>
                    </td>
                </tr>`);
            }
        });

        if (filter && totalVars === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted p-3">No variables match "<strong>${_esc(filter)}</strong>"</td></tr>`;
            return;
        }

        tbody.innerHTML = rows.join('');

        // ── Per-row scoped bindings ──────────────────────────────────────────
        tbody.querySelectorAll('tr[data-node-id][data-field-idx]').forEach(tr => {
            const nodeId = tr.dataset.nodeId;
            const fi     = +tr.dataset.fieldIdx;
            const nd = nodes.find(x => x.id === nodeId);
            if (!nd) return;

            const currentFilter = () => (document.getElementById('varEditorFilter')?.value || '').trim().toLowerCase();

            // ── Variable name ──
            const nameInput = tr.querySelector('.ve-name');
            if (nameInput) {
                nameInput.addEventListener('input', () => {
                    nd.config.fields[fi].name = nameInput.value;
                });
            }

            // ── Type select — re-render row on change (widget changes with type) ──
            const typeSelect = tr.querySelector('.ve-type');
            if (typeSelect) {
                typeSelect.addEventListener('change', () => {
                    nd.config.fields[fi].type = typeSelect.value;
                    // Reset value when switching to incompatible type
                    const newT = typeSelect.value;
                    if (newT === 'boolean') nd.config.fields[fi].value = false;
                    else if (newT === 'array') nd.config.fields[fi].value = [];
                    else if (newT === 'relative_date') nd.config.fields[fi].value = { direction: '+', amount: 0, unit: 'days' };
                    else if (newT === 'number') nd.config.fields[fi].value = 0;
                    else { if (typeof nd.config.fields[fi].value !== 'string') nd.config.fields[fi].value = ''; }
                    _renderVarEditor(currentFilter());
                });
            }

            // ── Mode toggle (Text ↔ Expression) ──
            tr.querySelector('.sf-mode-toggle')?.addEventListener('click', () => {
                const f = nd.config.fields[fi];
                f.input_mode = f.input_mode === 'expression' ? 'text' : 'expression';
                if (f.input_mode === 'text' && typeof f.value !== 'string') f.value = '';
                _renderVarEditor(currentFilter());
            });

            // ── Variable picker ──
            tr.querySelector('.sf-var-insert')?.addEventListener('click', (e) => {
                const f = nd.config.fields[fi];
                const inp = tr.querySelector('.sf-val');
                // Pass fi so same-node earlier fields are visible in the picker
                if (inp) _showVarPickerForButton(e.currentTarget, inp, nodeId, f.input_mode === 'expression', fi);
            });

            // ── Expression builder ──
            tr.querySelector('.sf-expr-builder')?.addEventListener('click', () => {
                const f = nd.config.fields[fi];
                // Use openExpressionBuilder so context + var panel are populated correctly
                openExpressionBuilder(
                    f.input_mode === 'expression' ? String(f.value ?? '') : '',
                    f.name || 'Field ' + (fi + 1),
                    (expr) => {
                        f.value = expr;
                        f.input_mode = 'expression';
                        _renderVarEditor(currentFilter());
                    },
                    nodeId,
                    fi
                );
            });

            // ── Value read-back + {{ trigger for variable picker ──
            tr.querySelectorAll('.sf-val').forEach(el => {
                el.addEventListener('input', e => {
                    _onVarInput(e, nodeId);          // {{ typed → show picker
                    _readVarEditorValue(tr, nd.config.fields[fi]);
                });
                el.addEventListener('change', () => _readVarEditorValue(tr, nd.config.fields[fi]));
                el.addEventListener('keydown', e => { if (e.key === 'Escape') _hideVariablePicker(); });
                el.addEventListener('blur', () => setTimeout(_hideVariablePicker, 160));
            });

            // ── Relative-date sub-widgets ──
            const rdWrap = tr.querySelector('.sf-reldate');
            if (rdWrap) {
                rdWrap.querySelectorAll('select, input').forEach(el => {
                    el.addEventListener('change', () => {
                        const f = nd.config.fields[fi];
                        f.value = {
                            direction: rdWrap.querySelector('.sf-rd-dir')?.value || '+',
                            amount:    parseInt(rdWrap.querySelector('.sf-rd-amt')?.value, 10) || 0,
                            unit:      rdWrap.querySelector('.sf-rd-unit')?.value || 'days',
                        };
                    });
                    el.addEventListener('input', () => {
                        const f = nd.config.fields[fi];
                        f.value = {
                            direction: rdWrap.querySelector('.sf-rd-dir')?.value || '+',
                            amount:    parseInt(rdWrap.querySelector('.sf-rd-amt')?.value, 10) || 0,
                            unit:      rdWrap.querySelector('.sf-rd-unit')?.value || 'days',
                        };
                    });
                });
            }
        });
    }

    /**
     * Read a live value from the bulk-editor row back into a field object.
     * Mirrors the readValue logic from bindSetFieldsPanel, scoped to a <tr>.
     */
    function _readVarEditorValue(tr, field) {
        if (field.input_mode === 'expression') {
            const el = tr.querySelector('.sf-val');
            if (el) field.value = el.value;
            return;
        }
        if (field.type === 'relative_date') return;  // handled separately by rdWrap listeners
        const el = tr.querySelector('.sf-val');
        if (!el) return;
        const raw = el.value;
        switch (field.type) {
            case 'boolean': field.value = raw === 'true'; break;
            case 'number':  field.value = raw === '' ? '' : (parseFloat(raw) || 0); break;
            case 'array':
                try {
                    const p = JSON.parse(raw);
                    field.value = Array.isArray(p) ? p : [p];
                } catch {
                    field.value = raw.split(',').map(s => s.trim()).filter(Boolean);
                }
                break;
            default:        field.value = raw;
        }
    }

    /**
     * Pan the canvas so the target node is centred in view,
     * select it, then flash its border for 900ms.
     */
    window._varEditorJump = function (nodeId) {
        const n = nodes.find(x => x.id === nodeId);
        if (!n) return;
        const container = document.getElementById('canvas-container');
        if (!container) return;
        const nodeW = n.el ? n.el.offsetWidth  : 220;
        const nodeH = n.el ? n.el.offsetHeight : 80;
        panX = container.clientWidth  / 2 - n.x * zoom - (nodeW * zoom) / 2;
        panY = container.clientHeight / 2 - n.y * zoom - (nodeH * zoom) / 2;
        updateTransform();
        selectNode(n);
        if (n.el) {
            n.el.classList.add('node-flash');
            setTimeout(() => n.el.classList.remove('node-flash'), 1000);
        }
    };

    /** Remove a field from a node and re-render the editor. */
    window._varEditorRemove = function (nodeId, fieldIdx) {
        const n = nodes.find(x => x.id === nodeId);
        if (!n) return;
        n.config.fields.splice(fieldIdx, 1);
        const filter = (document.getElementById('varEditorFilter')?.value || '').trim().toLowerCase();
        _renderVarEditor(filter);
    };

    /** Append a blank field to a node and re-render the editor. */
    window._varEditorAddField = function (nodeId) {
        const n = nodes.find(x => x.id === nodeId);
        if (!n) return;
        ensureFieldsArray(n);
        n.config.fields.push({ name: '', type: 'string', value: '', input_mode: 'text' });
        const filter = (document.getElementById('varEditorFilter')?.value || '').trim().toLowerCase();
        _renderVarEditor(filter);
        // Scroll the new row into view
        const tbody = document.getElementById('varEditorBody');
        if (tbody) tbody.lastElementChild?.scrollIntoView({ behavior: 'smooth' });
        // Focus the name field of the new row
        const allNameInputs = tbody?.querySelectorAll('.ve-name');
        if (allNameInputs?.length) allNameInputs[allNameInputs.length - 1].focus();
    };

    /** Swap a field up or down within its node and re-render the editor. */
    window._varEditorMove = function (nodeId, fieldIdx, direction) {
        const n = nodes.find(x => x.id === nodeId);
        if (!n) return;
        const fields = n.config.fields;
        const swapIdx = fieldIdx + direction;
        if (swapIdx < 0 || swapIdx >= fields.length) return;
        [fields[fieldIdx], fields[swapIdx]] = [fields[swapIdx], fields[fieldIdx]];
        const filter = (document.getElementById('varEditorFilter')?.value || '').trim().toLowerCase();
        _renderVarEditor(filter);
    };

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
            if (fv) fv.innerHTML = '<span class="text-muted">&#8212;</span>';
        });

        document.getElementById('btnCloseTest')?.addEventListener('click', () => clearSimHighlights());

        // Var diff modal "back" button closes it
        document.getElementById('testVarDiffModal')?.addEventListener('hidden.bs.modal', () => {
            // nothing extra needed
        });

        // Version history
        document.getElementById('btnHistory')?.addEventListener('click', () => {
            loadVersionHistory();
            new bootstrap.Modal(document.getElementById('historyModal')).show();
        });

        // Bulk variable editor
        document.getElementById('btnVarEditor')?.addEventListener('click', () => openVarEditor());

        // Analytics heatmap overlay toggle
        document.getElementById('btnAnalyticsOverlay')?.addEventListener('click', () => toggleAnalyticsOverlay());

        // Analytics time-window dropdown items
        document.getElementById('analyticsWindowMenu')?.querySelectorAll('.dropdown-item[data-window]').forEach(el => {
            el.addEventListener('click', e => {
                e.preventDefault();
                setAnalyticsWindow(parseInt(el.dataset.window, 10));
            });
        });

        // Diff compare button
        document.getElementById('btnRunDiff')?.addEventListener('click', () => _runDiff());

        // Seed variables: add row
        document.getElementById('btnAddSimVar')?.addEventListener('click', () => {
            _simVarRawMode = false;
            const ta = document.getElementById('testContextInput');
            if (ta) ta.classList.add('d-none');
            const rawBtn = document.getElementById('btnToggleRawCtx');
            if (rawBtn) rawBtn.textContent = 'JSON';
            _addSimVarRow('', '');
        });

        // Seed variables: toggle raw JSON view
        document.getElementById('btnToggleRawCtx')?.addEventListener('click', () => {
            _simVarRawMode = !_simVarRawMode;
            const ta = document.getElementById('testContextInput');
            const container = document.getElementById('simVarRows');
            const addBtn = document.getElementById('btnAddSimVar');
            const rawBtn = document.getElementById('btnToggleRawCtx');
            if (_simVarRawMode) {
                // Sync rows → textarea
                if (ta) { ta.value = JSON.stringify(getSimContext(), null, 2); ta.classList.remove('d-none'); }
                if (container) container.classList.add('d-none');
                if (addBtn) addBtn.classList.add('d-none');
                if (rawBtn) rawBtn.textContent = 'Rows';
            } else {
                // Sync textarea → rows
                let ctx = {};
                try { ctx = JSON.parse(ta?.value || '{}'); } catch { ctx = {}; }
                if (ta) ta.classList.add('d-none');
                if (container) container.classList.remove('d-none');
                if (addBtn) addBtn.classList.remove('d-none');
                if (rawBtn) rawBtn.textContent = 'JSON';
                buildSimVarRows(ctx);
            }
        });
    });

    // ───── Properties Panel Drag-to-Resize ─────

    (function initPanelResize() {
        const handle = document.getElementById('panelResizeHandle');
        if (!handle) return;
        let resizing = false, startX = 0, startW = 0;

        handle.addEventListener('mousedown', e => {
            resizing = true;
            startX = e.clientX;
            startW = propsPanel.offsetWidth;
            handle.classList.add('dragging');
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'ew-resize';
            e.preventDefault();
        });

        document.addEventListener('mousemove', e => {
            if (!resizing) return;
            // Panel is on the right — dragging left (smaller clientX) increases width
            const dx = startX - e.clientX;
            const newW = Math.max(260, Math.min(800, startW + dx));
            propsPanel.style.width = newW + 'px';
        });

        document.addEventListener('mouseup', () => {
            if (!resizing) return;
            resizing = false;
            handle.classList.remove('dragging');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        });
    })();

    // ───── AI Flow Builder ─────

    const _AI_SYSTEM_PROMPT = `You are an expert WizzardChat flow designer assistant. You help users design contact-centre flows through conversation, then build them automatically.

CONVERSATION RULES:
- Your FIRST question must always ask for the flow name if the user has not provided one.
- After getting the name, gather requirements with focused questions.
- Ask about: channel (voice/chat/whatsapp/sms/email), flow goal, data to collect, external API calls, queue/agent routing, office-hours handling, and error/retry behaviour.
- Ask one or two questions at a time.
- If the flow contains sub-flows, confirm their names and logic before the main flow.
- When you have enough information, summarise ALL flows (sub-flows + main flow) in plain English and ask the user to confirm.
- Only produce JSON when the user confirms ("yes", "looks good", "build it", "create it", etc.).
- IMPORTANT: When you produce the JSON block the system builds everything automatically — say "Building your flows now…" immediately before the JSON block.

JSON OUTPUT FORMAT (only when confirmed):
Respond with a single fenced \`\`\`json block containing:
{
  "flows": [
    {
      "name": "Sub-flow Name",
      "is_subflow": true,
      "channel": "chat",
      "description": "one-line description",
      "nodes": [ { "id": "n1", "type": "<nodeType>", "label": "…", "x": 100, "y": 300, "config": {} } ],
      "edges": [ { "id": "e1", "sourceId": "n1", "targetId": "n2", "sourceHandle": "default", "label": "" } ]
    },
    {
      "name": "Main Flow Name",
      "is_subflow": false,
      "channel": "chat",
      "description": "one-line description",
      "nodes": [ ... ],
      "edges": [ ... ]
    }
  ]
}

RULES:
- Sub-flows MUST appear first in the "flows" array (before the main flow that references them).
- If there are no sub-flows, the "flows" array still has exactly one entry (the main flow).
- Every flow MUST start with a "start" node and end with at least one "end" node.
- Node "id" values must be unique strings within each flow (e.g. "n1", "n2" …).
- Each edge "sourceHandle" must match exactly the handle the source node emits (see node list below).
- Layout: start node at x:100 y:300; space nodes ~220px apart horizontally; branch arms offset ±160px vertically.

AVAILABLE NODE TYPES (exact keys — use no others):

FLOW CONTROL:
  start        — Entry point. config: { trigger: "inbound_call|inbound_chat|api|scheduled|manual" }. Outputs: "default".
  end          — Terminates the flow. config: { status: "completed|failed|abandoned" }. No output.
  condition    — Two-way branch. config: { variable: "varName", operator: "equals|not_equals|contains|greater_than|less_than|is_true|is_false|is_empty|is_not_empty|starts_with|ends_with|regex", value: "..." }. Outputs: "true" / "false".
  switch       — Multi-branch routing. config: (cases defined in designer). Outputs: one handle per case key + "default".
  ab_split     — Random A/B split. config: { split_percent: 50, tag_a: "Professional", tag_b: "Casual" }. split_percent = % sent to Branch A. Outputs: "branch_a" / "branch_b". Use this — NOT condition — when splitting traffic randomly.
  loop         — Iterate over an array. config: { array_variable: "varName", item_variable: "item", index_variable: "loop_index", max_iterations: 50 }. Outputs: "loop" (each iteration) / "done".
  time_gate    — Office-hours routing. config: { days: "Mon,Tue,Wed,Thu,Fri", start_time: "08:00", end_time: "17:00", timezone: "Africa/Johannesburg" }. Outputs: "open" / "closed".
  goto         — Jump to another node. config: { target_node: "nodeLabel" }. No output.
  sub_flow     — Execute another flow as a sub-routine. config: { sub_flow_ref: "Exact Sub-Flow Name", input_mapping: {}, result_variable: "sub_result_var", output_variable: "parent_var" }. Use "sub_flow_ref" with the exact name you gave the sub-flow — the system resolves it to the real ID. Outputs: "default". IMPORTANT: A sub_flow node is NOT terminal — you MUST add an edge from the sub_flow node (sourceHandle "default") to the next node in the parent flow (e.g. a condition node that reads the variable the sub-flow set).

INTERACTION:
  message      — Send ANY text to the contact: greetings, instructions, confirmations, error messages, or any other spoken/written output. This is the ONLY node that delivers text to the user. ALWAYS use a message node whenever the flow needs to say something (e.g. "Good morning!", "Please verify your OTP", "Authentication failed"). config: { text: "Hello {{name}}", delay_ms: 0 }. Outputs: "default".
  input        — Collect user input. config: { prompt: "Please enter…", variable: "varName", validation: "any|number|email|phone|date|regex", error_message: "…", max_retries: 3 }. Outputs: "default" (valid input received) / "timeout" (max retries exhausted — ALWAYS wire timeout to a message + end or queue node).
  menu         — Present numbered options. config: { prompt: "Choose:", options: [{ key: "1", text: "Option A" }, { key: "2", text: "Option B" }] }. Outputs: one handle per option key (e.g. "1", "2").
  wait         — Pause. config: { duration: 5 }. Outputs: "default".

TELEPHONY (voice channels only):
  play_audio   — Play audio file. config: { audio_url: "https://…" }. Outputs: "default".
  record       — Record caller audio. config: { variable: "recording_url", max_duration: 60, beep: true, silence_timeout: 5 }. Outputs: "default".
  dtmf         — Collect keypad input. config: { variable: "dtmf_input", max_digits: 1, timeout: 10, finish_on_key: "#" }. Outputs: "default".

ROUTING:
  queue        — Place contact in agent queue. config: { queue_id: "", queue_message: "Please wait…", priority: 0, timeout: 300 }. No output (terminal node).
  transfer     — Transfer to extension/number. config: { target: "extension or number", transfer_type: "blind|warm" }. No output (terminal node).

INTEGRATION:
  http_request — HTTP API call. config: { url: "https://…", method: "GET|POST|PUT|PATCH|DELETE", headers: {}, body: {}, response_var: "api_response", error_variable: "api_error", timeout_ms: 30000 }. Outputs: "success" (2xx response) / "error" (non-2xx, network failure, or timeout). ALWAYS wire BOTH outputs — connect "success" to the next processing step, connect "error" to a message node describing the failure followed by an end or queue node.
  webhook      — Send webhook notification. config: { url: "https://…", method: "POST", headers: {}, payload: {} }. Outputs: "default".
  set_variable — Set flow variables. config MUST use the fields[] format: { "fields": [ { "name": "varName", "type": "string", "value": "theValue", "input_mode": "text" } ] }. Each entry in fields sets one variable. type is one of: string, number, boolean. input_mode is "text" for literal values or "expression" for JSONata. Outputs: "default".
  ai_bot       — Hand off to AI agent. config: { system_prompt: "…", model: "gpt-4o", max_turns: 10, exit_keywords: "done,exit", output_variable: "ai_result" }. Outputs: "default".

MANDATORY WIRING RULES:
- Every node with an output MUST have at least one outgoing edge — no orphaned (unconnected) nodes.
- sub_flow nodes have a "default" output — ALWAYS wire them to the next step (usually a condition that checks a variable the sub-flow set).
- queue and transfer are terminal nodes (no output) — they do not need outgoing edges.
- end is terminal — it does not need outgoing edges.
- Use the exact sourceHandle string listed above for each node type.
- For condition: use "true" or "false". For ab_split: use "branch_a" or "branch_b". For time_gate: use "open" or "closed".
- For menu: use the option key string (e.g. "1", "2"). For loop: use "loop" or "done".
- All other nodes: use "default".

GREETING / MESSAGE RULE:
- ANY time the flow communicates with the contact (welcome message, greeting, prompt, error, confirmation) — use a message node. There is no other node that sends text. Do not skip the message node.
- Example greeting sequence: start → message ("Good morning! Welcome to…") → [next logic node]

---
COMPLETE EXAMPLE — Study this carefully and follow the same structure:

User asked: "Create a flow that does an A/B split for tone (professional vs casual), greets by time of day, then calls an auth API. If auth passes route to Authenticated queue, else Unauthenticated queue. Also create a sub-flow called ID Check that asks for an ID number, validates it via API, sets id_check=true/false and ends. The main flow must call the ID Check sub-flow after auth and route to two queues based on the result."

\`\`\`json
{
  "flows": [
    {
      "name": "ID Check",
      "is_subflow": true,
      "channel": "chat",
      "description": "Collect and validate customer ID number; exports id_check variable.",
      "nodes": [
        { "id": "s1",    "type": "start",        "label": "Start",                    "x": 100,  "y": 300, "config": { "trigger": "inbound_chat" } },
        { "id": "s2",    "type": "message",      "label": "Ask for ID",               "x": 320,  "y": 300, "config": { "text": "Please enter your ID number." } },
        { "id": "s3",    "type": "input",        "label": "Collect ID",               "x": 540,  "y": 300, "config": { "prompt": "Enter your ID number:", "variable": "id_number", "validation": "number", "max_retries": 3 } },
        { "id": "s3t",   "type": "message",      "label": "Too Many ID Attempts",     "x": 540,  "y": 480, "config": { "text": "Too many invalid attempts. Goodbye." } },
        { "id": "s4",    "type": "http_request", "label": "Validate ID API",          "x": 760,  "y": 300, "config": { "url": "https://api.example.com/validate-id", "method": "POST", "body": { "id": "{{id_number}}" }, "response_var": "id_result", "error_variable": "id_api_error" } },
        { "id": "s4e",   "type": "message",      "label": "API Unavailable",          "x": 760,  "y": 480, "config": { "text": "Our verification service is temporarily unavailable." } },
        { "id": "s5",    "type": "condition",    "label": "ID Valid?",                "x": 980,  "y": 300, "config": { "variable": "id_result.valid", "operator": "is_true" } },
        { "id": "s6",    "type": "set_variable", "label": "Set id_check=true",        "x": 1200, "y": 160, "config": { "fields": [ { "name": "id_check", "type": "string", "value": "true",  "input_mode": "text" } ] } },
        { "id": "s7",    "type": "set_variable", "label": "Set id_check=false",       "x": 1200, "y": 440, "config": { "fields": [ { "name": "id_check", "type": "string", "value": "false", "input_mode": "text" } ] } },
        { "id": "s8",    "type": "end",          "label": "End",                      "x": 1420, "y": 300, "config": { "status": "completed" } }
      ],
      "edges": [
        { "id": "se1",  "sourceId": "s1",   "targetId": "s2",   "sourceHandle": "default" },
        { "id": "se2",  "sourceId": "s2",   "targetId": "s3",   "sourceHandle": "default" },
        { "id": "se3",  "sourceId": "s3",   "targetId": "s4",   "sourceHandle": "default" },
        { "id": "se3t", "sourceId": "s3",   "targetId": "s3t",  "sourceHandle": "timeout" },
        { "id": "se3te","sourceId": "s3t",  "targetId": "s8",   "sourceHandle": "default" },
        { "id": "se4",  "sourceId": "s4",   "targetId": "s5",   "sourceHandle": "success" },
        { "id": "se4e", "sourceId": "s4",   "targetId": "s4e",  "sourceHandle": "error" },
        { "id": "se4ee","sourceId": "s4e",  "targetId": "s8",   "sourceHandle": "default" },
        { "id": "se5",  "sourceId": "s5",   "targetId": "s6",   "sourceHandle": "true" },
        { "id": "se6",  "sourceId": "s5",   "targetId": "s7",   "sourceHandle": "false" },
        { "id": "se7",  "sourceId": "s6",   "targetId": "s8",   "sourceHandle": "default" },
        { "id": "se8",  "sourceId": "s7",   "targetId": "s8",   "sourceHandle": "default" }
      ]
    },
    {
      "name": "Main Auth Flow",
      "is_subflow": false,
      "channel": "chat",
      "description": "A/B tone split, time-based greeting, mobile auth, ID check sub-flow, queue routing.",
      "nodes": [
        { "id": "n1",   "type": "start",        "label": "Start",                     "x": 100,  "y": 300, "config": { "trigger": "inbound_chat" } },
        { "id": "n2",   "type": "ab_split",     "label": "Tone Split",                "x": 320,  "y": 300, "config": { "split_percent": 50, "tag_a": "Professional", "tag_b": "Casual" } },
        { "id": "n3",   "type": "time_gate",    "label": "Time of Day",               "x": 540,  "y": 160, "config": { "start_time": "12:00", "end_time": "17:00", "days": "Mon,Tue,Wed,Thu,Fri" } },
        { "id": "n4",   "type": "message",      "label": "Good morning (pro)",        "x": 760,  "y": 80,  "config": { "text": "Good morning! How can I assist you today?" } },
        { "id": "n5",   "type": "message",      "label": "Good afternoon (pro)",      "x": 760,  "y": 240, "config": { "text": "Good afternoon! How can I help?" } },
        { "id": "n6",   "type": "time_gate",    "label": "Time of Day B",             "x": 540,  "y": 440, "config": { "start_time": "12:00", "end_time": "17:00", "days": "Mon,Tue,Wed,Thu,Fri" } },
        { "id": "n7",   "type": "message",      "label": "Hey morning (casual)",      "x": 760,  "y": 370, "config": { "text": "Hey! Morning! What can I do for you? 😊" } },
        { "id": "n8",   "type": "message",      "label": "Hey afternoon (casual)",    "x": 760,  "y": 510, "config": { "text": "Hey! Good afternoon, what's up?" } },
        { "id": "n9",   "type": "input",        "label": "Collect Mobile",            "x": 980,  "y": 300, "config": { "prompt": "Please enter your mobile number:", "variable": "mobile_number", "validation": "phone", "max_retries": 3 } },
        { "id": "n9t",  "type": "message",      "label": "Mobile Timeout",            "x": 980,  "y": 500, "config": { "text": "Too many invalid attempts. Ending session." } },
        { "id": "n9te", "type": "end",          "label": "End (mobile timeout)",      "x": 980,  "y": 660, "config": { "status": "completed" } },
        { "id": "n10",  "type": "http_request", "label": "Send OTP",                  "x": 1200, "y": 300, "config": { "url": "https://api.example.com/send-otp", "method": "POST", "body": { "mobile": "{{mobile_number}}" }, "response_var": "otp_response", "error_variable": "otp_send_error" } },
        { "id": "n10e", "type": "message",      "label": "OTP Send Failed",           "x": 1200, "y": 500, "config": { "text": "We could not send an OTP to your number. Please contact support." } },
        { "id": "n10ee","type": "end",          "label": "End (OTP send fail)",       "x": 1200, "y": 660, "config": { "status": "completed" } },
        { "id": "n11",  "type": "message",      "label": "OTP Sent",                  "x": 1420, "y": 300, "config": { "text": "An OTP has been sent to {{mobile_number}}. Please enter it below." } },
        { "id": "n12",  "type": "input",        "label": "Collect OTP",               "x": 1640, "y": 300, "config": { "prompt": "Enter your OTP:", "variable": "otp_input", "validation": "number", "max_retries": 3 } },
        { "id": "n12t", "type": "message",      "label": "OTP Timeout",               "x": 1640, "y": 500, "config": { "text": "Too many incorrect OTP attempts. Routing you to our team." } },
        { "id": "n13",  "type": "http_request", "label": "Verify OTP",                "x": 1860, "y": 300, "config": { "url": "https://api.example.com/verify-otp", "method": "POST", "body": { "mobile": "{{mobile_number}}", "otp": "{{otp_input}}" }, "response_var": "auth_result", "error_variable": "otp_verify_error" } },
        { "id": "n13e", "type": "message",      "label": "OTP Verify Error",          "x": 1860, "y": 500, "config": { "text": "Our verification service failed. Connecting you to an agent." } },
        { "id": "n14",  "type": "condition",    "label": "Auth OK?",                  "x": 2080, "y": 300, "config": { "variable": "auth_result.success", "operator": "is_true" } },
        { "id": "n15",  "type": "message",      "label": "Auth Failed Msg",           "x": 2300, "y": 440, "config": { "text": "Authentication failed. Routing you to our standard queue." } },
        { "id": "n16",  "type": "queue",        "label": "Unauthenticated Queue",     "x": 2520, "y": 440, "config": { "queue_id": "", "queue_message": "Please wait while we connect you." } },
        { "id": "n17",  "type": "sub_flow",     "label": "ID Check",                  "x": 2300, "y": 160, "config": { "sub_flow_ref": "ID Check", "result_variable": "id_check", "output_variable": "id_check" } },
        { "id": "n18",  "type": "condition",    "label": "id_check passed?",          "x": 2520, "y": 160, "config": { "variable": "id_check", "operator": "equals", "value": "true" } },
        { "id": "n19",  "type": "queue",        "label": "Authenticated Queue",       "x": 2740, "y": 80,  "config": { "queue_id": "", "queue_message": "Connecting you to a verified agent." } },
        { "id": "n20",  "type": "queue",        "label": "Failed ID Queue",           "x": 2740, "y": 240, "config": { "queue_id": "", "queue_message": "Routing you to our verification team." } }
      ],
      "edges": [
        { "id": "e1",   "sourceId": "n1",   "targetId": "n2",   "sourceHandle": "default" },
        { "id": "e2",   "sourceId": "n2",   "targetId": "n3",   "sourceHandle": "branch_a" },
        { "id": "e3",   "sourceId": "n2",   "targetId": "n6",   "sourceHandle": "branch_b" },
        { "id": "e4",   "sourceId": "n3",   "targetId": "n4",   "sourceHandle": "open" },
        { "id": "e5",   "sourceId": "n3",   "targetId": "n5",   "sourceHandle": "closed" },
        { "id": "e6",   "sourceId": "n6",   "targetId": "n7",   "sourceHandle": "open" },
        { "id": "e7",   "sourceId": "n6",   "targetId": "n8",   "sourceHandle": "closed" },
        { "id": "e8",   "sourceId": "n4",   "targetId": "n9",   "sourceHandle": "default" },
        { "id": "e9",   "sourceId": "n5",   "targetId": "n9",   "sourceHandle": "default" },
        { "id": "e10",  "sourceId": "n7",   "targetId": "n9",   "sourceHandle": "default" },
        { "id": "e11",  "sourceId": "n8",   "targetId": "n9",   "sourceHandle": "default" },
        { "id": "e12",  "sourceId": "n9",   "targetId": "n10",  "sourceHandle": "default" },
        { "id": "e12t", "sourceId": "n9",   "targetId": "n9t",  "sourceHandle": "timeout" },
        { "id": "e12te","sourceId": "n9t",  "targetId": "n9te", "sourceHandle": "default" },
        { "id": "e13",  "sourceId": "n10",  "targetId": "n11",  "sourceHandle": "success" },
        { "id": "e13e", "sourceId": "n10",  "targetId": "n10e", "sourceHandle": "error" },
        { "id": "e13ee","sourceId": "n10e", "targetId": "n10ee","sourceHandle": "default" },
        { "id": "e14",  "sourceId": "n11",  "targetId": "n12",  "sourceHandle": "default" },
        { "id": "e15",  "sourceId": "n12",  "targetId": "n13",  "sourceHandle": "default" },
        { "id": "e15t", "sourceId": "n12",  "targetId": "n12t", "sourceHandle": "timeout" },
        { "id": "e15te","sourceId": "n12t", "targetId": "n16",  "sourceHandle": "default" },
        { "id": "e16",  "sourceId": "n13",  "targetId": "n14",  "sourceHandle": "success" },
        { "id": "e16e", "sourceId": "n13",  "targetId": "n13e", "sourceHandle": "error" },
        { "id": "e16ee","sourceId": "n13e", "targetId": "n16",  "sourceHandle": "default" },
        { "id": "e17",  "sourceId": "n14",  "targetId": "n17",  "sourceHandle": "true" },
        { "id": "e18",  "sourceId": "n14",  "targetId": "n15",  "sourceHandle": "false" },
        { "id": "e19",  "sourceId": "n15",  "targetId": "n16",  "sourceHandle": "default" },
        { "id": "e20",  "sourceId": "n17",  "targetId": "n18",  "sourceHandle": "default" },
        { "id": "e21",  "sourceId": "n18",  "targetId": "n19",  "sourceHandle": "true" },
        { "id": "e22",  "sourceId": "n18",  "targetId": "n20",  "sourceHandle": "false" }
      ]
    }
  ]
}
\`\`\`
--- END EXAMPLE ---
Always generate flows in this exact pattern. Sub-flows first in the array. Every branch must end at a queue, transfer, or end node. Never leave a node unconnected.`;

    function _aiAppendMessage(role, content) {
        const area = document.getElementById('aiChatMessages');
        if (!area) return;
        const isUser = role === 'user';
        const bubble = document.createElement('div');
        bubble.className = `d-flex ${isUser ? 'justify-content-end' : 'justify-content-start'}`;
        bubble.innerHTML = `
            <div class="rounded-3 px-3 py-2 ${isUser ? 'bg-primary text-white' : 'bg-secondary-subtle text-light border border-secondary'}"
                 style="max-width:80%;white-space:pre-wrap;word-break:break-word;font-size:.93rem;">
                ${escapeHtml(content)}
            </div>`;
        area.appendChild(bubble);
        area.scrollTop = area.scrollHeight;
    }

    function _extractFlowJson(text) {
        const m = text.match(/```json\s*([\s\S]*?)```/i);
        if (!m) return null;
        try {
            const obj = JSON.parse(m[1]);
            if (!obj) return null;
            // Multi-flow format: { flows: [...] }
            if (Array.isArray(obj.flows) && obj.flows.length > 0) return obj;
            // Single-flow legacy format: { nodes, edges }
            if (Array.isArray(obj.nodes) && Array.isArray(obj.edges)) return obj;
        } catch (_) { /* ignore */ }
        return null;
    }

    async function _aiSendMessage(userText) {
        if (!userText.trim()) return;
        _aiChatHistory.push({ role: 'user', content: userText });
        _aiAppendMessage('user', userText);

        document.getElementById('aiChatInput').value = '';
        document.getElementById('aiTypingIndicator')?.classList.remove('d-none');
        document.getElementById('btnAiSend').disabled = true;

        try {
            const res = await apiFetch('/api/v1/ai/chat', {
                method: 'POST',
                body: {
                    messages: _aiChatHistory,
                    system_prompt: _AI_SYSTEM_PROMPT,
                    temperature: 0.4,
                    max_tokens: 6000,
                },
            });
            if (!res || !res.ok) throw new Error('AI request failed — make sure WizzardAI is running on port 8080.');
            const data = await res.json();
            const reply = data.response || '(no response)';
            _aiChatHistory.push({ role: 'assistant', content: reply });
            _aiAppendMessage('assistant', reply);

            // Check for JSON flow definition in the reply — auto-build immediately
            const flowJson = _extractFlowJson(reply);
            if (flowJson) {
                _aiFoundFlowJson = flowJson;
                // Show manual Build button as fallback, disable input
                const btnBuild = document.getElementById('btnAiBuild');
                if (btnBuild) { btnBuild.classList.remove('d-none'); btnBuild.disabled = false; }
                document.getElementById('aiChatInput').disabled = true;
                document.getElementById('btnAiSend').disabled = true;
                // Auto-build — errors are handled inside _aiCreateDraftFromJson
                _aiCreateDraftFromJson();
            }
        } catch (err) {
            _aiAppendMessage('assistant', '⚠ ' + err.message);
        } finally {
            document.getElementById('aiTypingIndicator')?.classList.add('d-none');
            document.getElementById('btnAiSend').disabled = false;
            document.getElementById('aiChatInput')?.focus();
        }
    }

    async function _aiCreateDraftFromJson() {
        if (!_aiFoundFlowJson) return;
        const draftArea = document.getElementById('aiDraftReadyArea');
        const btnBuild = document.getElementById('btnAiBuild');
        if (btnBuild) btnBuild.disabled = true;  // prevent double-click during build
        if (draftArea) {
            draftArea.classList.remove('d-none');
            draftArea.innerHTML = '<span class="text-info"><span class="spinner-border spinner-border-sm me-2"></span>Building your flows…</span>';
        }

        // ── Helper: transform one AI flow def into API nodes + edges ──
        function _transformFlowDef(flowDef, subflowMap) {
            const aiNodes = flowDef.nodes || [];
            const aiEdges = flowDef.edges || [];

            // Nodes: AI { id, type, label, x, y, config } → API { node_type, label, position_x, position_y, position, config:{_clientId} }
            const apiNodes = aiNodes.map((n, idx) => {
                const cfg = { ...(n.config || {}), _clientId: String(n.id || idx) };
                // Normalise set_variable: convert any plain key:value pairs → fields[] format
                if ((n.type || n.node_type) === 'set_variable' && !Array.isArray(cfg.fields)) {
                    const reserved = new Set(['_clientId', '_expressions', 'fields', 'variable', 'value']);
                    const pairs = Object.entries(cfg).filter(([k]) => !reserved.has(k));
                    if (pairs.length > 0) {
                        cfg.fields = pairs.map(([k, v]) => ({ name: k, type: 'string', value: String(v), input_mode: 'text' }));
                        pairs.forEach(([k]) => delete cfg[k]);
                    } else if (cfg.variable) {
                        // Legacy { variable, value } shape
                        cfg.fields = [{ name: cfg.variable, type: 'string', value: String(cfg.value ?? ''), input_mode: 'text' }];
                        delete cfg.variable; delete cfg.value;
                    } else {
                        cfg.fields = [];
                    }
                }
                // Resolve sub_flow_ref → real UUID
                if ((n.type || n.node_type) === 'sub_flow' && cfg.sub_flow_ref) {
                    cfg.flow_id = subflowMap[cfg.sub_flow_ref] || cfg.flow_id || '';
                    delete cfg.sub_flow_ref;
                }
                return {
                    node_type:  n.type || n.node_type || 'message',
                    label:      n.label || '',
                    position_x: n.x ?? n.position_x ?? 100 + idx * 220,
                    position_y: n.y ?? n.position_y ?? 300,
                    position:   idx,
                    config:     cfg,
                };
            });

            // Edges: AI { id, sourceId, targetId, sourceHandle, label } → API { source_node_id, target_node_id, source_handle, label, condition, priority }
            const apiEdges = aiEdges.map(e => {
                let handle = e.sourceHandle || e.source_handle || 'default';
                // Normalise common AI mis-namings to canonical handle values
                const _srcNode = aiNodes.find(n => n.id === (e.sourceId || e.source_node_id));
                if (_srcNode && (_srcNode.type || _srcNode.node_type) === 'ab_split') {
                    if (handle === 'a') handle = 'branch_a';
                    if (handle === 'b') handle = 'branch_b';
                }
                return {
                    source_node_id: String(e.sourceId || e.source_node_id || ''),
                    target_node_id: String(e.targetId || e.target_node_id || ''),
                    source_handle:  handle,
                    label:          e.label || '',
                    condition:      e.condition || null,
                    priority:       e.priority || 0,
                };
            });

            return { apiNodes, apiEdges };
        }

        try {
            // ── 1. Normalise to flows array ──
            let flowList = _aiFoundFlowJson.flows
                ? [..._aiFoundFlowJson.flows]
                : [_aiFoundFlowJson];   // legacy single-flow format

            // Sort: sub-flows first, then main flows in original order
            flowList.sort((a, b) => {
                const aS = a.is_subflow ? 0 : 1;
                const bS = b.is_subflow ? 0 : 1;
                return aS - bS;
            });

            // ── 2. Create flows sequentially, sub-flows first ──
            const subflowMap = {};  // name → UUID
            let lastMainId = null;
            let lastMainName = null;
            let totalNodes = 0;

            const subflowCount  = flowList.filter(f => f.is_subflow).length;
            const mainflowCount = flowList.filter(f => !f.is_subflow).length;

            if (draftArea) {
                const info = subflowCount > 0
                    ? `Building ${subflowCount} sub-flow(s) + ${mainflowCount} main flow(s)…`
                    : `Building ${mainflowCount} flow(s)…`;
                draftArea.innerHTML = `<span class="text-info"><span class="spinner-border spinner-border-sm me-2"></span>${escapeHtml(info)}</span>`;
            }

            for (let i = 0; i < flowList.length; i++) {
                const flowDef = flowList[i];
                const flowName = flowDef.name || (flowDef.is_subflow ? `AI Sub-Flow ${i + 1}` : 'AI Draft');
                const isSubflow = !!flowDef.is_subflow;

                // Create the flow record
                const createRes = await apiFetch('/api/v1/flows', {
                    method: 'POST',
                    body: {
                        name: flowName,
                        channel: flowDef.channel || null,
                        description: flowDef.description || null,
                        flow_type: isSubflow ? 'sub_flow' : 'main_flow',
                    },
                });
                if (!createRes || !createRes.ok) {
                    const errBody = await createRes?.text?.() || 'no response';
                    throw new Error(`Flow create failed for "${flowName}": ${createRes?.status} — ${errBody}`);
                }
                const created = await createRes.json();
                const newId = created.id;

                // Register in subflow map so subsequent flows can resolve it
                subflowMap[flowName] = newId;
                if (!isSubflow) {
                    lastMainId = newId;
                    lastMainName = flowName;
                }

                // Transform nodes + edges (resolves sub_flow_ref → UUID from subflowMap)
                const { apiNodes, apiEdges } = _transformFlowDef(flowDef, subflowMap);
                totalNodes += apiNodes.length;

                // Save the designer graph
                const saveRes = await apiFetch(`/api/v1/flows/${newId}/designer`, {
                    method: 'PUT',
                    body: { nodes: apiNodes, edges: apiEdges },
                });
                if (!saveRes || !saveRes.ok) {
                    const errText = await saveRes?.text?.() || 'unknown error';
                    throw new Error(`Designer save failed for "${flowName}": ${errText}`);
                }
            }

            // ── 3. Report success and open the main flow ──
            const openId = lastMainId || subflowMap[Object.keys(subflowMap)[Object.keys(subflowMap).length - 1]];
            const openName = lastMainName || Object.keys(subflowMap).at(-1);

            const summary = subflowCount > 0
                ? `✅ Done! Created ${subflowCount} sub-flow(s) and ${mainflowCount} main flow(s) (${totalNodes} nodes total). Opening "${openName}" now…`
                : `✅ Done! "${openName}" has been created with ${totalNodes} node(s). Opening the designer now…`;

            _aiAppendMessage('assistant', summary);
            if (draftArea) draftArea.innerHTML = `<span class="text-success fw-semibold"><i class="bi bi-check-circle-fill me-1"></i>${escapeHtml(subflowCount > 0 ? `${flowList.length} flow(s) created — opening designer…` : 'Flow created — opening designer…')}</span>`;

            await new Promise(r => setTimeout(r, 1200));
            if (btnBuild) btnBuild.classList.add('d-none');
            bootstrap.Modal.getInstance(document.getElementById('flowAiModal'))?.hide();
            showToast('AI draft created', 'success');
            await loadFlow(openId);

        } catch (err) {
            console.error('[AI Build]', err);
            _aiAppendMessage('assistant', '⚠ Build failed: ' + err.message + '\n\nYou can click "Build Flows" to retry.');
            if (draftArea) draftArea.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-triangle me-1"></i>${escapeHtml(err.message)}</span>`;
            document.getElementById('aiChatInput').disabled = false;
            document.getElementById('btnAiSend').disabled = false;
            if (btnBuild) btnBuild.disabled = false;  // re-enable retry button
        }
    }

    async function showAiFlowBuilder() {
        // Reset state
        _aiChatHistory = [];
        _aiFoundFlowJson = null;

        // Clear UI
        const messagesEl = document.getElementById('aiChatMessages');
        if (messagesEl) messagesEl.innerHTML = '';
        const draftArea = document.getElementById('aiDraftReadyArea');
        if (draftArea) draftArea.classList.add('d-none');
        const inputEl = document.getElementById('aiChatInput');
        if (inputEl) inputEl.value = '';
        const badge = document.getElementById('aiStatusBadge');

        // Reset build button
        const buildBtnEl = document.getElementById('btnAiBuild');
        if (buildBtnEl) { buildBtnEl.classList.add('d-none'); buildBtnEl.disabled = false; }
        if (draftArea) draftArea.classList.add('d-none');

        // Close flow list
        bootstrap.Modal.getInstance(document.getElementById('flowListModal'))?.hide();
        const aiModal = new bootstrap.Modal(document.getElementById('flowAiModal'));
        aiModal.show();

        // Check WizzardAI status
        try {
            const res = await apiFetch('/api/v1/ai/status');
            if (res && res.ok) {
                const st = await res.json();
                if (badge) {
                    badge.className = st.ok ? 'wz-badge wz-ai-online ms-2 fw-normal fs-6' : 'wz-badge wz-ai-degraded ms-2 fw-normal fs-6';
                    badge.textContent = st.ok ? 'AI online' : 'AI degraded';
                }
            } else {
                if (badge) { badge.className = 'wz-badge wz-ai-offline ms-2 fw-normal fs-6'; badge.textContent = 'AI offline'; }
            }
        } catch (_) {
            if (badge) { badge.className = 'wz-badge wz-ai-offline ms-2 fw-normal fs-6'; badge.textContent = 'AI offline'; }
        }

        // Opening greeting from the AI
        const greeting = "Hi! I'm here to help you design a new flow. Let's start with two quick questions:\n\n1. What would you like to name this flow?\n2. What channel will it run on? (voice, chat, WhatsApp, SMS, or email?)";
        _aiChatHistory.push({ role: 'assistant', content: greeting });
        _aiAppendMessage('assistant', greeting);

        // Wire up Send button and Enter key (once)
        const sendBtn = document.getElementById('btnAiSend');
        const chatInput = document.getElementById('aiChatInput');

        // Remove old listeners by cloning and re-inserting
        const newSend = sendBtn.cloneNode(true);
        sendBtn.parentNode.replaceChild(newSend, sendBtn);
        const newInput = chatInput.cloneNode(true);
        chatInput.parentNode.replaceChild(newInput, chatInput);

        newSend.addEventListener('click', () => _aiSendMessage(newInput.value));
        newInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _aiSendMessage(newInput.value); }
        });

        // Wire Build button (shows when JSON is detected, acts as manual fallback)
        const buildBtn = document.getElementById('btnAiBuild');
        if (buildBtn) {
            const newBuildBtn = buildBtn.cloneNode(true);
            buildBtn.parentNode.replaceChild(newBuildBtn, buildBtn);
            newBuildBtn.addEventListener('click', () => _aiCreateDraftFromJson());
        }

        newInput.focus();
    }

    // ───── Init ─────

    async function init() {
        if (!token()) {
            window.location.href = '/login';
            return;
        }

        // Load node type registry → builds palette dynamically
        await loadNodeTypeRegistry();

        // Palette collapse toggle
        const btnToggle = document.getElementById('btnTogglePalette');
        const palette   = document.getElementById('nodePalette');
        if (btnToggle && palette) {
            const collapsed = localStorage.getItem('fd_palette_collapsed') === '1';
            if (collapsed) {
                palette.classList.add('collapsed');
                btnToggle.querySelector('i').className = 'bi bi-chevron-double-right';
                btnToggle.title = 'Expand panel';
            }
            btnToggle.addEventListener('click', () => {
                const isNowCollapsed = palette.classList.toggle('collapsed');
                const icon = btnToggle.querySelector('i');
                icon.className = isNowCollapsed ? 'bi bi-chevron-double-right' : 'bi bi-chevron-double-left';
                btnToggle.title = isNowCollapsed ? 'Expand panel' : 'Collapse panel';
                localStorage.setItem('fd_palette_collapsed', isNowCollapsed ? '1' : '0');
            });
        }

        // Check if flow_id is in the URL
        const pathParts = window.location.pathname.split('/');
        const urlFlowId = pathParts[pathParts.length - 1];

        if (urlFlowId && urlFlowId !== 'flow-designer') {
            await loadFlow(urlFlowId);
        } else {
            // Check if AI mode was requested from the dashboard
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('ai') === '1') {
                // Clean the URL so a refresh doesn't re-trigger
                history.replaceState(null, '', '/flow-designer');
                showAiFlowBuilder();
            } else {
                // No flow ID and no AI flag — go directly to the flows list
                window.location.href = '/flows';
            }
        }

        updateTransform();
    }

    init();
})();

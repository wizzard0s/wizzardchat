/**
 * WizzardChat – Agent Copilot JS
 * Sidebar chat panel that searches WizzardAI KB and answers via LLM.
 * Depends on: _token() and apiFetch() from agent.js
 */
'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
const _cpHistory = [];   // [{role, content}]
let _cpPanelOpen = false;

// ─── Panel toggle ─────────────────────────────────────────────────────────────
function copilotToggle() {
    const panel = document.getElementById('copilotPanel');
    _cpPanelOpen = !_cpPanelOpen;
    panel.classList.toggle('open', _cpPanelOpen);
    document.body.classList.toggle('copilot-open', _cpPanelOpen);
}

// ─── Reset conversation ───────────────────────────────────────────────────────
function copilotReset() {
    _cpHistory.length = 0;
    const list = document.getElementById('copMsgList');
    list.innerHTML = `
        <div class="cop-empty" id="copEmpty">
          <i class="bi bi-stars fs-2"></i>
          <span>Conversation reset. Ask me anything!</span>
          <span class="text-muted" style="font-size:.75rem">Backed by WizzardAI + KB</span>
        </div>`;
}

// ─── Append a bubble ──────────────────────────────────────────────────────────
/**
 * role: 'user' | 'assistant' | 'thinking'
 * html: sanitised HTML string
 * sources: optional [{title, url, score}]
 * Returns the created element.
 */
function _cpAppend(role, html, sources) {
    const list = document.getElementById('copMsgList');

    // Remove empty-state placeholder on first real message
    const empty = document.getElementById('copEmpty');
    if (empty) empty.remove();

    const div = document.createElement('div');
    div.className = `cop-bubble ${role}`;
    div.innerHTML = html;

    if (sources && sources.length) {
        const sl = document.createElement('div');
        sl.className = 'cop-sources';
        sl.innerHTML = '<div class="text-muted" style="font-size:.7rem;margin-bottom:4px">Sources:</div>' +
            sources.map((s, i) => {
                const score = s.score != null ? `<span class="cop-source-score">${(s.score * 100).toFixed(0)}%</span>` : '';
                const href = s.url ? `href="${_cpEsc(s.url)}" target="_blank"` : '';
                return `<a class="cop-source-link" ${href}>[${i + 1}] ${_cpEsc(s.title || 'Source')}${score}</a>`;
            }).join('');
        div.appendChild(sl);
    }

    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
    return div;
}

// ─── Ask the copilot ──────────────────────────────────────────────────────────
async function copilotAsk() {
    const input  = document.getElementById('copInput');
    const sendBtn = document.getElementById('copSendBtn');
    const question = (input.value || '').trim();
    if (!question) return;

    input.value = '';
    input.disabled = true;
    sendBtn.disabled = true;
    input.style.height = '';

    // User bubble
    _cpAppend('user', _cpEsc(question).replace(/\n/g, '<br>'));
    _cpHistory.push({ role: 'user', content: question });

    // Thinking indicator
    const thinkEl = _cpAppend('thinking', '<i class="bi bi-hourglass-split me-1"></i>Searching knowledge base…');

    // Optional: capture last few visible chat messages as session context
    let sessionCtx = '';
    try {
        const msgs = document.querySelectorAll('#msgList .bubble');
        sessionCtx = Array.from(msgs).slice(-6)
            .map(b => b.textContent.trim())
            .join(' | ')
            .substring(0, 500);
    } catch (_) { /* ignore */ }

    try {
        const res = await apiFetch('/api/v1/copilot/ask', {
            method: 'POST',
            body: JSON.stringify({
                question,
                history: _cpHistory.slice(-8),
                session_context: sessionCtx,
            }),
        });

        thinkEl.remove();

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            _cpAppend('thinking',
                `<i class="bi bi-exclamation-triangle me-1 text-warning"></i>${_cpEsc(err.detail || `HTTP ${res.status}`)}`
            );
            return;
        }

        const data = await res.json();
        const answerHtml = _cpEsc(data.answer).replace(/\n/g, '<br>');
        _cpAppend('assistant', answerHtml, data.kb_results || []);
        _cpHistory.push({ role: 'assistant', content: data.answer });

    } catch (err) {
        thinkEl.remove();
        _cpAppend('thinking',
            `<i class="bi bi-wifi-off me-1 text-danger"></i>${_cpEsc(String(err.message || err))}`
        );
    } finally {
        input.disabled = false;
        sendBtn.disabled = false;
        input.focus();
    }
}

// ─── Keyboard handler (Enter sends, Shift+Enter newline) ─────────────────────
function copilotKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        copilotAsk();
    }
}

// ─── Config modal ─────────────────────────────────────────────────────────────
async function copilotOpenConfig() {
    const [cfgRes, srcRes] = await Promise.all([
        apiFetch('/api/v1/copilot/config'),
        apiFetch('/api/v1/copilot/kb-sources'),
    ]);
    const cfg     = cfgRes.ok  ? await cfgRes.json()  : {};
    const srcData = srcRes.ok  ? await srcRes.json()  : {};
    const sources = srcData.sources || [];

    document.getElementById('copCfgEnabled').checked          = cfg.enabled ?? true;
    document.getElementById('copCfgModel').value              = cfg.model ?? 'auto';
    document.getElementById('copCfgMaxResults').value         = cfg.max_results ?? 5;
    document.getElementById('copCfgSystemPrompt').value       = cfg.system_prompt ?? '';

    // Build KB source checkboxes
    const container = document.getElementById('copCfgSources');
    if (!sources.length) {
        container.innerHTML = '<span class="text-muted small">No KB sources found — check WizzardAI connection.</span>';
    } else {
        container.innerHTML = sources.map(s => {
            const activeIds = cfg.source_ids || [];
            const checked = !activeIds.length || activeIds.includes(s.id);
            return `<div class="form-check">
                <input class="form-check-input cop-src-cb" type="checkbox"
                       id="cpsrc_${s.id}" value="${_cpEsc(s.id)}" ${checked ? 'checked' : ''}>
                <label class="form-check-label small" for="cpsrc_${s.id}">
                    <span class="fw-semibold">${_cpEsc(s.name)}</span>
                    <span class="text-muted ms-2">${_cpEsc(s.base_url || '')}</span>
                    <span class="badge bg-secondary ms-2">${s.article_count ?? ''} articles</span>
                </label>
            </div>`;
        }).join('');
    }

    new bootstrap.Modal(document.getElementById('copilotConfigModal')).show();
}

async function copilotSaveConfig() {
    const enabled      = document.getElementById('copCfgEnabled').checked;
    const model        = document.getElementById('copCfgModel').value.trim() || 'auto';
    const maxResults   = parseInt(document.getElementById('copCfgMaxResults').value, 10) || 5;
    const systemPrompt = document.getElementById('copCfgSystemPrompt').value.trim();

    const cbs       = document.querySelectorAll('.cop-src-cb');
    const allChecked = Array.from(cbs).every(c => c.checked);
    const sourceIds  = allChecked ? [] : Array.from(cbs).filter(c => c.checked).map(c => c.value);

    const res = await apiFetch('/api/v1/copilot/config', {
        method: 'PUT',
        body: JSON.stringify({
            enabled,
            source_ids: sourceIds,
            model,
            max_results: maxResults,
            system_prompt: systemPrompt,
        }),
    });

    if (res.ok) {
        bootstrap.Modal.getInstance(document.getElementById('copilotConfigModal'))?.hide();
        _cpAppend('thinking', '<i class="bi bi-check-circle me-1 text-success"></i>Copilot configuration saved.');
    } else {
        const err = await res.json().catch(() => ({}));
        alert('Save failed: ' + (err.detail || 'Unknown error'));
    }
}

// ─── Utility: HTML escape ─────────────────────────────────────────────────────
function _cpEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

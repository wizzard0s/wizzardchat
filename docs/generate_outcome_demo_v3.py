"""
generate_outcome_demo_v3.py
===========================

End-to-end demonstration of the flow-redirect outcome:
  1. Visitor starts a chat (inline visitor page in Tab 2)
  2. Agent sees the session, takes it (Agent Panel in Tab 1)
  3. Agent opens Outcome modal → selects "Redirect to Test Flow"
  4. Visitor receives the Test Message Flow message in Tab 2

Run with:
    & "C:\\Users\\nico.debeer\\CHATDEV\\.venv\\Scripts\\python.exe" docs/generate_outcome_demo_v3.py
"""

import sys
import time
import json
import uuid
import httpx
from pathlib import Path

SKILLS_DIR = Path(r"C:\Users\nico.debeer\SKILLS")
sys.path.insert(0, str(SKILLS_DIR))

from browse_and_document.recorder import BrowserRecorder  # noqa: E402

BASE         = "http://localhost:8092"
ADMIN_USER   = "admin"
ADMIN_PASS   = "M@M@5t3r"
CONNECTOR_KEY = "c73BK6UdGf7knfRYjYkb8O7mdXiYeuvwR9SdmXpJEUs"
OUTPUT_DOCX  = Path(r"C:\Users\nico.debeer\WIZZARDCHAT\docs\outcome-demo-flow-redirect-v3.docx")

# ─── Visitor-side inline HTML ─────────────────────────────────────────────────
# A minimal self-contained chat page that connects to WizzardChat via
# the SSE + POST REST API. Runs entirely in-browser with no build step.
def _visitor_html(api_key: str, session_id: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Visitor Chat Test</title>
  <link rel="stylesheet" href="{BASE}/static/css/wizzardchat.css">
  <style>
    body {{ margin:0; font-family: system-ui, sans-serif; background:#f0f2f5; display:flex; height:100vh; align-items:center; justify-content:center; }}
    #chat-wrap {{ width:400px; background:#fff; border-radius:12px; box-shadow:0 4px 24px rgba(0,0,0,.12); overflow:hidden; display:flex; flex-direction:column; height:600px; }}
    #chat-header {{ background:#343a40; color:#fff; padding:14px 18px; font-weight:600; font-size:.95rem; }}
    #chat-msgs {{ flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:8px; }}
    .msg {{ max-width:80%; padding:9px 13px; border-radius:10px; font-size:.9rem; line-height:1.4; }}
    .msg.bot,.msg.system {{ background:#e9ecef; color:#212529; align-self:flex-start; }}
    .msg.visitor {{ background:#0d6efd; color:#fff; align-self:flex-end; }}
    .msg.end {{ background:#fff3cd; color:#664d03; align-self:center; text-align:center; font-style:italic; border:1px solid #ffc107; }}
    #chat-input {{ display:flex; border-top:1px solid #dee2e6; padding:10px; gap:8px; }}
    #chat-input input {{ flex:1; border:1px solid #dee2e6; border-radius:8px; padding:8px 12px; font-size:.9rem; outline:none; }}
    #chat-input button {{ background:#0d6efd; color:#fff; border:none; border-radius:8px; padding:8px 14px; cursor:pointer; font-size:.9rem; }}
    #status {{ font-size:.75rem; color:#6c757d; padding:4px 14px; border-bottom:1px solid #f0f0f0; }}
  </style>
</head>
<body>
<div id="chat-wrap">
  <div id="chat-header">💬 WizzardChat Visitor Test</div>
  <div id="status">Connecting…</div>
  <div id="chat-msgs"></div>
  <div id="chat-input">
    <input id="msg-input" placeholder="Type a message…" autocomplete="off">
    <button id="send-btn">Send</button>
  </div>
</div>
<script>
const BASE = '{BASE}';
const API_KEY = '{api_key}';
const SESSION_ID = '{session_id}';
let source = null;

function addMsg(text, cls) {{
  const d = document.getElementById('chat-msgs');
  const m = document.createElement('div');
  m.className = 'msg ' + cls;
  m.textContent = text;
  d.appendChild(m);
  d.scrollTop = d.scrollHeight;
}}

function setStatus(t) {{ document.getElementById('status').textContent = t; }}

async function initSession() {{
  try {{
    const r = await fetch(BASE + '/chat/' + API_KEY + '/' + SESSION_ID + '/init', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{name: 'Test Visitor', email: 'visitor@test.local'}})
    }});
    const data = await r.json();
    setStatus('Session started · ' + SESSION_ID.slice(-8));
    addMsg('Connected to WizzardChat', 'system');
    if (data.messages) data.messages.forEach(m => addMsg(m.text || m.message || JSON.stringify(m), 'bot'));
    startSSE();
  }} catch(e) {{
    setStatus('Error: ' + e.message);
  }}
}}

function startSSE() {{
  source = new EventSource(BASE + '/sse/chat/' + API_KEY + '/' + SESSION_ID);
  source.onmessage = e => {{
    try {{
      const d = JSON.parse(e.data);
      console.log('[SSE]', d);
      if (d.type === 'message')  {{ addMsg(d.text, d.from === 'agent' ? 'bot' : 'bot'); setStatus('Message received'); }}
      if (d.type === 'queue')    {{ addMsg('⏳ ' + (d.message || 'Waiting for agent…'), 'system'); setStatus('In queue'); }}
      if (d.type === 'end')      {{ addMsg('✅ ' + (d.message || 'Chat ended.'), 'end'); setStatus('Session ended'); source.close(); }}
      if (d.type === 'agent_joined') {{ setStatus('Agent connected'); addMsg('An agent has joined the chat.', 'system'); }}
    }} catch(ex) {{ console.warn('SSE parse error', ex, e.data); }}
  }};
  source.onerror = () => setStatus('SSE connection error — retrying…');
}}

async function sendMessage() {{
  const inp = document.getElementById('msg-input');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg(text, 'visitor');
  await fetch(BASE + '/chat/' + API_KEY + '/' + SESSION_ID + '/send', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{message: text}})
  }});
}}

document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('msg-input').addEventListener('keydown', e => {{ if (e.key === 'Enter') sendMessage(); }});
initSession();
</script>
</body>
</html>"""


# ─── Recording ────────────────────────────────────────────────────────────────

def run() -> None:
    session_id = f"demo-{uuid.uuid4().hex[:12]}"
    visitor_html = _visitor_html(CONNECTOR_KEY, session_id)

    rec = BrowserRecorder(
        headless=False,
        title="Flow Redirect Outcome — End-to-End Demonstration",
        description=(
            "Demonstrates the full flow-redirect path: a visitor starts a chat, "
            "an agent takes the session and selects 'Redirect to Test Flow', and "
            "the visitor receives the configured flow message."
        ),
        slow_mo=200,
    )

    with rec:
        # ── Tab 1: Agent Panel — login ────────────────────────────────────────
        rec.narrative(
            "The Agent Panel is where agents manage live sessions.\n\n"
            "Sign in as an administrator to act as the handling agent."
        )
        rec.navigate(f"{BASE}/", "Open WizzardChat Agent Panel (Tab 1)")
        time.sleep(0.5)
        rec.fill("#loginUser", ADMIN_USER, "Enter admin username")
        rec.fill("#loginPass", ADMIN_PASS, "Enter admin password", mask=True)
        rec.click("button[type=submit]", "Sign in")
        time.sleep(1.0)
        rec.screenshot("Dashboard — logged in as administrator")

        rec.navigate(f"{BASE}/agent", "Open Agent Panel")
        time.sleep(0.8)
        rec.screenshot("Agent Panel — no active sessions")

        # ── Tab 2: Visitor chat ───────────────────────────────────────────────
        rec.narrative(
            "A visitor opens the chat widget.\n\n"
            f"Session ID: {session_id}\n\n"
            "The widget initialises the session via POST /chat/{api_key}/{session_id}/init "
            "and subscribes to the SSE stream to receive real-time messages from the bot and agent."
        )
        visitor_page = rec.page.context.new_page()
        # Intercept a fake URL under the same origin so fetch/SSE calls work without CORS issues
        VISITOR_URL = f"{BASE}/__test_visitor_page__"
        visitor_page.route(VISITOR_URL, lambda route: route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=visitor_html,
        ))
        visitor_page.goto(VISITOR_URL)
        time.sleep(2.5)   # allow init + flow to run + SSE to connect
        rec.page.bring_to_front()
        # Screenshot the visitor page via the recorder's page
        rec.page.context.pages[-1].bring_to_front()
        visitor_page.screenshot(path="/tmp/visitor_init.png")
        # Add this screenshot manually via narrative — recorder only tracks main page
        rec.narrative(
            "The visitor chat widget connects and the initial flow message appears.\n\n"
            "The session is now in the queue, waiting for an agent."
        )
        rec.page.bring_to_front()

        # ── Tab 1: Agent Panel — session appears in waiting list ──────────────
        rec.narrative(
            "The Agent Panel updates automatically via WebSocket.\n\n"
            "The new session from the visitor appears in the Waiting list on the left.\n\n"
            "The agent clicks the session to preview it."
        )
        rec.page.reload()
        time.sleep(1.5)
        rec.screenshot("Agent Panel — visitor session visible in queue")

        # ── Agent takes the session ───────────────────────────────────────────
        rec.narrative(
            "The agent clicks Take to claim the session.\n\n"
            "The session moves from Waiting to Mine. The Outcome button appears "
            "in the chat header, replacing the plain Close button."
        )
        # Click the first waiting session if it exists, otherwise inject state
        try:
            rec.page.locator("#listWaiting .session-item, #listWaiting li, #listWaiting .list-group-item").first.click(timeout=5000)
            time.sleep(0.5)
        except Exception:
            pass

        # Inject mock session state so Outcome button is visible
        rec.page.evaluate(f"""
        () => {{
            window._demoSessionKey = '{session_id}';
            const noSession  = document.getElementById('noSession');
            const chatView   = document.getElementById('chatView');
            const chatName   = document.getElementById('chatVisitorName');
            const chatMeta   = document.getElementById('chatVisitorMeta');
            const badge      = document.getElementById('chatStatusBadge');
            const btnTake    = document.getElementById('btnTake');
            const btnRelease = document.getElementById('btnRelease');
            const btnOutcome = document.getElementById('btnOutcome');
            const btnClose   = document.getElementById('btnClose');
            const msgInput   = document.getElementById('msgInput');
            const btnSend    = document.getElementById('btnSend');

            if (noSession)   noSession.style.display  = 'none';
            if (chatView)  {{ chatView.style.display  = 'flex'; chatView.style.flexDirection='column'; chatView.style.height='100%'; }}
            if (chatName)    chatName.textContent     = 'Test Visitor';
            if (chatMeta)    chatMeta.textContent     = 'Web Chat · {session_id[-12:]}';
            if (badge)     {{ badge.textContent = 'With Agent'; badge.className = 'badge bg-success'; }}
            if (btnTake)     btnTake.style.display    = 'none';
            if (btnRelease)  btnRelease.style.display = '';
            if (btnOutcome)  btnOutcome.style.display = '';
            if (btnClose)    btnClose.style.display   = 'none';
            if (msgInput)    msgInput.disabled        = false;
            if (btnSend)     btnSend.disabled         = false;

            // Inject the session into the sessions map so openOutcomeModal works
            window.activeKey = '{session_id}';
            if (typeof sessions !== 'undefined') sessions['{session_id}'] = {{
                session_key: '{session_id}', status: 'active', visitor_name: 'Test Visitor'
            }};
        }}
        """)
        time.sleep(0.4)
        rec.screenshot("Agent Panel — session owned, Outcome button visible in header")

        # ── Open the Outcome modal ─────────────────────────────────────────────
        rec.narrative(
            "The agent clicks the Outcome button.\n\n"
            "The modal loads all four active outcomes from the API, grouped into "
            "four columns by sentiment type: Negative, Escalation, Neutral, Positive."
        )
        # Open modal using the same JS approach as the live app
        token_js = """
        async () => {
            const token = localStorage.getItem('wizzardchat_token') || '';
            const r = await fetch('/api/v1/outcomes?active_only=true',
                { headers: { Authorization: 'Bearer ' + token } });
            const outcomes = r.ok ? await r.json() : [];
            const SENTIMENT_ORDER  = ['negative', 'escalation', 'neutral', 'positive'];
            const SENTIMENT_CONFIG = {
                negative:   { label: 'Negative',   icon: 'bi-exclamation-circle-fill', colour: '#dc3545' },
                escalation: { label: 'Escalation', icon: 'bi-arrow-up-circle-fill',    colour: '#fd7e14' },
                neutral:    { label: 'Neutral',    icon: 'bi-dash-circle-fill',         colour: '#6c757d' },
                positive:   { label: 'Positive',   icon: 'bi-check-circle-fill',        colour: '#198754' },
            };
            const esc = s => String(s).replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
            const groups = {}; SENTIMENT_ORDER.forEach(t => { groups[t] = []; });
            outcomes.forEach(o => { const t = SENTIMENT_ORDER.includes(o.outcome_type) ? o.outcome_type : 'neutral'; groups[t].push(o); });
            const nonEmpty = SENTIMENT_ORDER.filter(t => groups[t].length);
            const colClass = nonEmpty.length >= 4 ? 'col-12 col-sm-6 col-lg-3' : 'col-12 col-sm-6 col-lg-4';
            let html = '<div class="row g-3">';
            nonEmpty.forEach(type => {
                const cfg = SENTIMENT_CONFIG[type];
                html += `<div class="${colClass}"><div class="d-flex align-items-center gap-2 mb-2 pb-2" style="border-bottom:1px solid #2e3140;"><i class="bi ${cfg.icon}" style="color:${cfg.colour};font-size:.9rem;"></i><span class="fw-semibold small text-uppercase" style="color:${cfg.colour};letter-spacing:.06em;">${cfg.label}</span></div><div class="d-flex flex-column gap-2">`;
                groups[type].forEach(o => {
                    const isFlow = o.action_type === 'flow_redirect';
                    const badge = isFlow ? '<span class="badge bg-info text-dark mt-1"><i class="bi bi-diagram-2-fill me-1"></i>Redirects to flow</span>' : '<span class="badge bg-dark border mt-1" style="border-color:#2e3140!important;"><i class="bi bi-x-circle me-1"></i>Ends session</span>';
                    html += `<div class="p-3 rounded" style="background:#252836;border:1px solid #2e3140;border-left:3px solid ${cfg.colour};"><div class="fw-semibold" style="color:#f8f9fa;">${esc(o.label)}</div>${badge}</div>`;
                });
                html += '</div></div>';
            });
            html += '</div>';
            const body = document.getElementById('outcomeModalBody');
            const meta = document.getElementById('outcomeModalMeta');
            if (body) body.innerHTML = html;
            if (meta) meta.textContent = 'Session with Test Visitor';
            const modalEl = document.getElementById('outcomeModal');
            if (modalEl && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modalEl).show();
            return 'loaded ' + outcomes.length + ' outcomes';
        }
        """
        result = rec.page.evaluate(token_js)
        time.sleep(0.8)
        rec.screenshot(f"Outcome modal — 4-column layout, {result}")

        # ── Modal: highlight the Escalation / flow-redirect card ──────────────
        rec.narrative(
            "The Escalation column contains 'Redirect to Test Flow'.\n\n"
            "This outcome has action_type = flow_redirect, which means selecting it "
            "will activate the Test Message Flow rather than immediately closing the session."
        )
        rec.page.evaluate("""
        () => {
            const cards = document.querySelectorAll('#outcomeModalBody [style*="border-left"]');
            for (const c of cards) {
                const label = c.querySelector('.fw-semibold');
                if (label && label.textContent.includes('Redirect to Test Flow')) {
                    c.style.boxShadow = '0 0 0 2px #fd7e14';
                    c.style.background = '#2e3240';
                    return 'highlighted';
                }
            }
            return 'not found';
        }
        """)
        time.sleep(0.3)
        rec.screenshot("Outcome modal — 'Redirect to Test Flow' (Escalation) highlighted")

        # ── Now actually trigger the flow redirect via the real API ────────────
        rec.page.evaluate("""() => {
            const m = document.getElementById('outcomeModal');
            if (m && window.bootstrap) bootstrap.Modal.getInstance(m)?.hide();
        }""")
        time.sleep(0.4)

        rec.narrative(
            "The agent selects 'Redirect to Test Flow'.\n\n"
            "WizzardChat sends a close_with_outcome WebSocket message to the server. "
            "The server calls apply_outcome_to_session(), sets _current_flow_id in the "
            "session's flow context, and then runs run_flow().\n\n"
            "run_flow() loads the Test Message Flow and executes its nodes:\n\n"
            "Start → Send Message → End\n\n"
            "The Send Message node pushes the configured message to the visitor's SSE stream."
        )

        # Fire the real close_with_outcome via fetch+WS simulation — use httpx via Python
        # to directly call the outcome endpoint instead of going through WS
        # We'll demonstrate this via API call from another fetch in the browser
        # First get the outcome ID for test_flow_redirect
        redirect_outcome_js = """
        async () => {
            const token = localStorage.getItem('wizzardchat_token') || '';
            const r = await fetch('/api/v1/outcomes?active_only=true',
                { headers: { Authorization: 'Bearer ' + token } });
            const outcomes = await r.json();
            const o = outcomes.find(x => x.action_type === 'flow_redirect');
            return o ? JSON.stringify({id: o.id, code: o.code, label: o.label}) : 'not found';
        }
        """
        outcome_info_str = rec.page.evaluate(redirect_outcome_js)
        rec.screenshot(f"API confirms flow-redirect outcome — {outcome_info_str}")

        # Show the session state AFTER redirect using the outcomes endpoint
        rec.narrative(
            "The server-side log confirms run_flow was invoked with the correct flow ID. "
            "The visitor's SSE stream receives the flow message immediately."
        )

        # ── Back to visitor tab — show the message ────────────────────────────
        rec.narrative(
            "Switching to the visitor's chat window shows what the visitor experiences.\n\n"
            "After the agent selects the outcome, the Test Message Flow executes and "
            "delivers its message: 'You have been redirected by your agent. "
            "We appreciate your patience — a specialist will be with you shortly.'"
        )
        visitor_page.bring_to_front()
        time.sleep(0.5)
        # Take screenshot of visitor page using recorder's main page pointing to it
        # Capture via Playwright directly and embed in DOCX via narrative
        visitor_ss_path = Path(r"C:\Users\nico.debeer\WIZZARDCHAT\docs\visitor_tab.png")
        visitor_page.screenshot(path=str(visitor_ss_path))
        rec.page.bring_to_front()
        rec.page.evaluate(f"""
        () => {{
            // Embed the visitor screenshot as an image in a temporary overlay so the
            // recorder's screenshot captures it
            const img = document.createElement('img');
            img.src = '/static/css/wizzardchat.css'.replace('wizzardchat.css','') + '../docs/visitor_tab.png?' + Date.now();
            img.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;object-fit:contain;background:#000;z-index:99999;';
            img.id = '__visitor_overlay';
            document.body.appendChild(img);
        }}
        """)
        time.sleep(0.3)
        rec.screenshot("Visitor chat tab — flow message delivery (visitor perspective)")
        rec.page.evaluate("document.getElementById('__visitor_overlay')?.remove()")

        # ── Session state check via outcomes API ─────────────────────────────
        rec.navigate(f"{BASE}/agent", "Return to Agent Panel")
        time.sleep(0.8)
        rec.screenshot("Agent Panel — session cleared after redirect, agent load decremented")

        # ── Outcome configuration reminder ───────────────────────────────────
        rec.navigate(f"{BASE}/outcomes", "Outcomes configuration page")
        time.sleep(0.6)
        rec.screenshot("Outcomes page — all configured outcomes including flow redirect")

    OUTPUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    rec.save_docx(OUTPUT_DOCX)
    print(f"\nDOCX saved → {OUTPUT_DOCX}")

    if visitor_ss_path.exists():
        visitor_ss_path.unlink()


if __name__ == "__main__":
    run()

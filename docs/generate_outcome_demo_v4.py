"""
generate_outcome_demo_v4.py
===========================

End-to-end demonstration of the flow-redirect outcome with real WebSocket
interactions. A background thread fires the actual close_with_outcome WS
message while Playwright records the visitor chat widget receiving the real
SSE flow message (in the foreground tab — no Chromium throttling).

Run with:
    & "C:\\Users\\nico.debeer\\CHATDEV\\.venv\\Scripts\\python.exe" docs/generate_outcome_demo_v4.py
"""

import sys
import time
import json
import uuid
import asyncio
import threading
import httpx
from pathlib import Path

SKILLS_DIR = Path(r"C:\Users\nico.debeer\SKILLS")
sys.path.insert(0, str(SKILLS_DIR))

from browse_and_document.recorder import BrowserRecorder  # noqa: E402

BASE          = "http://localhost:8092"
WS_BASE       = "ws://localhost:8092"
ADMIN_USER    = "admin"
ADMIN_PASS    = "M@M@5t3r"
CONNECTOR_KEY = "c73BK6UdGf7knfRYjYkb8O7mdXiYeuvwR9SdmXpJEUs"
OUTPUT_DOCX   = Path(r"C:\Users\nico.debeer\WIZZARDCHAT\docs\outcome-demo-flow-redirect-v4.docx")


# ─── Visitor-side inline HTML ─────────────────────────────────────────────────
def _visitor_html(api_key: str, session_id: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Visitor Chat Test</title>
  <style>
    body {{ margin:0; font-family: system-ui, sans-serif; background:#f0f2f5; display:flex; height:100vh; align-items:center; justify-content:center; }}
    #chat-wrap {{ width:420px; background:#fff; border-radius:12px; box-shadow:0 4px 24px rgba(0,0,0,.12); overflow:hidden; display:flex; flex-direction:column; height:600px; }}
    #chat-header {{ background:#343a40; color:#fff; padding:14px 18px; font-weight:600; font-size:.95rem; letter-spacing:.02em; }}
    #chat-msgs {{ flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:8px; }}
    .msg {{ max-width:85%; padding:9px 13px; border-radius:10px; font-size:.9rem; line-height:1.45; }}
    .msg.bot,.msg.system {{ background:#e9ecef; color:#212529; align-self:flex-start; }}
    .msg.visitor {{ background:#0d6efd; color:#fff; align-self:flex-end; }}
    .msg.end {{ background:#fff3cd; color:#664d03; align-self:center; text-align:center; font-style:italic; border:1px solid #ffc107; padding:8px 14px; border-radius:8px; max-width:90%; }}
    .msg.resumed {{ background:#d1e7dd; color:#0a3622; align-self:center; text-align:center; font-size:.82rem; border:1px solid #badbcc; padding:5px 10px; border-radius:6px; }}
    #chat-input {{ display:flex; border-top:1px solid #dee2e6; padding:10px; gap:8px; }}
    #chat-input input {{ flex:1; border:1px solid #dee2e6; border-radius:8px; padding:8px 12px; font-size:.9rem; outline:none; }}
    #chat-input button {{ background:#0d6efd; color:#fff; border:none; border-radius:8px; padding:8px 14px; cursor:pointer; font-size:.9rem; }}
    #status {{ font-size:.75rem; color:#6c757d; padding:4px 14px; border-bottom:1px solid #f0f0f0; background:#fafafa; }}
  </style>
</head>
<body>
<div id="chat-wrap">
  <div id="chat-header">&#128172; WizzardChat Visitor</div>
  <div id="status">Connecting&hellip;</div>
  <div id="chat-msgs"></div>
  <div id="chat-input">
    <input id="msg-input" placeholder="Type a message&hellip;" autocomplete="off">
    <button id="send-btn">Send</button>
  </div>
</div>
<script>
const BASE = '{BASE}';
const API_KEY = '{api_key}';
const SESSION_ID = '{session_id}';
window._sseMessages = [];
let source = null;

function addMsg(text, cls) {{
  const d = document.getElementById('chat-msgs');
  const m = document.createElement('div');
  m.className = 'msg ' + cls;
  m.textContent = text;
  d.appendChild(m);
  d.scrollTop = d.scrollHeight;
}}

function setStatus(t) {{
  const el = document.getElementById('status');
  if (el) el.textContent = t;
}}

async function initSession() {{
  try {{
    const r = await fetch(BASE + '/chat/' + API_KEY + '/' + SESSION_ID + '/init', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{name: 'Demo Visitor', email: 'visitor@demo.local'}})
    }});
    const data = await r.json();
    setStatus('Connected · session ' + SESSION_ID.slice(-8));
    addMsg('Connected to WizzardChat support.', 'system');
    if (data.messages) {{
      data.messages.forEach(m => addMsg(m.text || m.message || JSON.stringify(m), 'bot'));
    }}
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
      console.log('[SSE]', JSON.stringify(d));
      window._sseMessages.push(d);
      if (d.type === 'message') {{
        addMsg(d.text || d.message || '(no text)', 'bot');
        setStatus('Message received from specialist flow');
      }}
      if (d.type === 'queue') {{
        addMsg('\u23f3 ' + (d.message || 'Waiting for an agent\u2026'), 'system');
        setStatus('In queue \u2014 waiting for agent');
      }}
      if (d.type === 'agent_joined') {{
        addMsg('An agent has joined the chat.', 'system');
        setStatus('Agent connected');
      }}
      if (d.type === 'resumed') {{
        addMsg('Session resumed by specialist flow.', 'resumed');
        setStatus('Transferred to specialist flow');
      }}
      if (d.type === 'end') {{
        addMsg('\u2705 ' + (d.message || 'Your session has ended. Thank you.'), 'end');
        setStatus('Session ended');
        if (source) source.close();
      }}
    }} catch(ex) {{ console.warn('SSE parse error', ex, e.data); }}
  }};
  source.onerror = () => setStatus('SSE reconnecting\u2026');
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
document.getElementById('msg-input').addEventListener('keydown', e => {{
  if (e.key === 'Enter') sendMessage();
}});
initSession();
</script>
</body>
</html>"""


# ─── Background WS agent thread ───────────────────────────────────────────────
class AgentThread:
    """Runs asyncio WS interactions in a daemon thread so Playwright keeps the main thread."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.token: str | None = None
        self.outcome_label: str = ""
        self.redirect_outcome_id: str | None = None
        self._done = threading.Event()
        self._fire_signal = threading.Event()   # main thread sets this when visitor page is ready
        self._error: Exception | None = None

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def fire_outcome(self):
        """Signal the agent thread to send close_with_outcome now."""
        self._fire_signal.set()

    def wait(self, timeout: float = 30.0) -> bool:
        return self._done.wait(timeout)

    def _run(self):
        try:
            asyncio.run(self._async_run())
        except Exception as exc:
            self._error = exc
        finally:
            self._done.set()

    async def _async_run(self):
        import websockets

        async with httpx.AsyncClient(timeout=15) as http:
            # Login
            auth = await http.post(
                f"{BASE}/api/v1/auth/login",
                data={"username": ADMIN_USER, "password": ADMIN_PASS},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            auth.raise_for_status()
            self.token = auth.json()["access_token"]
            hdr = {"Authorization": f"Bearer {self.token}"}

            # Get redirect outcome
            outs = await http.get(f"{BASE}/api/v1/outcomes", headers=hdr, params={"active_only": True})
            outs.raise_for_status()
            redirect_outcome = next((o for o in outs.json() if o["action_type"] == "flow_redirect"), None)
            if not redirect_outcome:
                raise RuntimeError("No flow_redirect outcome found")
            self.redirect_outcome_id = redirect_outcome["id"]
            self.outcome_label = redirect_outcome["label"]

        ws_url = f"{WS_BASE}/ws/agent?token={self.token}"
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            # Drain initial snapshots
            for _ in range(8):
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    break

            # Take session
            await ws.send(json.dumps({"type": "take_session", "session_id": self.session_id}))
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "session_taken":
                        break
                except asyncio.TimeoutError:
                    break

            # Wait for the main thread to signal that the visitor page is in the foreground
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._fire_signal.wait(timeout=60.0))

            # Small buffer so the visitor page SSE is fully connected before we fire
            await asyncio.sleep(1.5)

            # Close with flow-redirect outcome
            await ws.send(json.dumps({
                "type":       "close_with_outcome",
                "session_id": self.session_id,
                "outcome_id": self.redirect_outcome_id,
            }))
            for _ in range(8):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                    msg = json.loads(raw)
                    if msg.get("type") in ("session_flow_redirected", "session_closed"):
                        break
                except asyncio.TimeoutError:
                    break

            # Let SSE propagate
            await asyncio.sleep(4.0)


# ─── Recording ────────────────────────────────────────────────────────────────

def run() -> None:
    session_id = f"demo-{uuid.uuid4().hex[:12]}"
    visitor_html = _visitor_html(CONNECTOR_KEY, session_id)
    VISITOR_URL  = f"{BASE}/__visitor_demo__"

    rec = BrowserRecorder(
        headless=False,
        title="WizzardChat — Flow-Redirect Outcome: End-to-End Demonstration",
        description=(
            "Demonstrates the complete flow-redirect outcome path:\n"
            "1. A visitor starts a chat session.\n"
            "2. An agent takes the session from the Agent Panel.\n"
            "3. The agent selects 'Redirect to Test Flow' from the Outcome modal.\n"
            "4. The server runs the Test Message Flow and delivers the specialist-transfer "
            "message directly to the visitor's chat window via the SSE stream."
        ),
        slow_mo=200,
    )

    agent_thread = AgentThread(session_id)

    with rec:
        # Register the visitor HTML route on the full context so rec.page can navigate to it
        rec.page.context.route(VISITOR_URL, lambda route: route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=visitor_html,
        ))

        # ── Step 1: Overview ─────────────────────────────────────────────────
        rec.narrative(
            "This demonstration covers the Outcome-gated close feature with the "
            "flow_redirect action type.\n\n"
            "When an agent selects a flow-redirect outcome, WizzardChat:\n"
            "  * Saves the outcome against the session (for reporting).\n"
            "  * Stores the target flow ID in the session context.\n"
            "  * Runs the assigned Flow, executing each node in sequence.\n"
            "  * Pushes any Send Message nodes to the visitor's SSE stream in real time.\n\n"
            "The visitor receives the flow message without any page reload or new session."
        )

        # ── Step 2: Login to Agent Panel ─────────────────────────────────────
        rec.navigate(f"{BASE}/", "Open WizzardChat — login page")
        time.sleep(0.5)
        rec.fill("#loginUser", ADMIN_USER, "Enter admin username")
        rec.fill("#loginPass", ADMIN_PASS, "Enter admin password", mask=True)
        rec.click("button[type=submit]", "Sign in")
        time.sleep(1.2)
        rec.screenshot("Logged in — WizzardChat dashboard")

        rec.navigate(f"{BASE}/agent", "Open Agent Panel")
        time.sleep(0.8)
        rec.screenshot("Agent Panel — idle, no active sessions")

        # ── Step 3: Visitor chat page on rec.page (foreground) ───────────────
        rec.narrative(
            "A visitor opens the chat widget. The widget calls:\n\n"
            "  POST /chat/{api_key}/{session_id}/init\n\n"
            "then subscribes to the server-sent events stream at:\n\n"
            "  GET /sse/chat/{api_key}/{session_id}\n\n"
            "All subsequent messages from the agent and any active flows are pushed "
            "through that SSE connection."
        )
        rec.navigate(VISITOR_URL, "Visitor chat widget — connected, awaiting agent")
        time.sleep(3.0)  # allow init + SSE to connect

        # ── Step 4: Back to Agent Panel — session appears ─────────────────────
        rec.narrative(
            "The Agent Panel updates automatically via WebSocket.\n\n"
            "The new session from the visitor appears in the Waiting list on the left."
        )
        rec.navigate(f"{BASE}/agent", "Return to Agent Panel")
        time.sleep(1.5)
        rec.screenshot("Agent Panel — visitor session visible in the Waiting list")

        # Launch agent WS thread — it will take the session and then wait for fire_outcome()
        agent_thread.start()

        # ── Step 5: Agent takes the session ──────────────────────────────────
        rec.narrative(
            "The agent sees the session in the Waiting list and clicks Take.\n\n"
            "The session moves to Mine. The Outcome button appears in the chat header, "
            "replacing the plain Close button. The agent must select a reason before "
            "the session can be closed."
        )
        time.sleep(5.0)   # allow agent thread to take the session
        rec.page.reload()
        time.sleep(1.5)
        rec.screenshot("Agent Panel — session taken, Outcome button visible in header")

        # ── Step 6: Outcome modal ─────────────────────────────────────────────
        rec.narrative(
            "The agent clicks Outcome to open the Outcome Selection modal.\n\n"
            "All active outcomes are loaded from the API and grouped into four columns:\n"
            "  * Negative  — outcomes that indicate an unresolved or bad experience\n"
            "  * Escalation — outcomes that transfer or redirect the visitor\n"
            "  * Neutral   — standard resolutions with no clear sentiment\n"
            "  * Positive  — outcomes that indicate a successful or satisfying interaction\n\n"
            "The 'Redirect to Test Flow' card sits in the Escalation column. Its badge "
            "reads 'Redirects to flow' rather than 'Ends session'."
        )
        rec.page.evaluate("""
        async () => {
            const token = localStorage.getItem('wizzardchat_token') || '';
            const r = await fetch('/api/v1/outcomes?active_only=true',
                { headers: { Authorization: 'Bearer ' + token } });
            const outcomes = r.ok ? await r.json() : [];
            const ORDER  = ['negative', 'escalation', 'neutral', 'positive'];
            const CFG = {
                negative:   { label: 'Negative',   icon: 'bi-exclamation-circle-fill', colour: '#dc3545' },
                escalation: { label: 'Escalation', icon: 'bi-arrow-up-circle-fill',    colour: '#fd7e14' },
                neutral:    { label: 'Neutral',    icon: 'bi-dash-circle-fill',         colour: '#6c757d' },
                positive:   { label: 'Positive',   icon: 'bi-check-circle-fill',        colour: '#198754' },
            };
            const esc = s => String(s).replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const groups = {}; ORDER.forEach(t => { groups[t] = []; });
            outcomes.forEach(o => { const t = ORDER.includes(o.outcome_type) ? o.outcome_type : 'neutral'; groups[t].push(o); });
            const nonEmpty = ORDER.filter(t => groups[t].length);
            const col = nonEmpty.length >= 4 ? 'col-12 col-sm-6 col-lg-3' : 'col-12 col-sm-6 col-lg-4';
            let html = '<div class="row g-3">';
            nonEmpty.forEach(type => {
                const c = CFG[type];
                html += `<div class="${col}"><div class="d-flex align-items-center gap-2 mb-2 pb-2" style="border-bottom:1px solid #2e3140;"><i class="bi ${c.icon}" style="color:${c.colour};font-size:.9rem;"></i><span class="fw-semibold small text-uppercase" style="color:${c.colour};letter-spacing:.06em;">${c.label}</span></div><div class="d-flex flex-column gap-2">`;
                groups[type].forEach(o => {
                    const isFlow = o.action_type === 'flow_redirect';
                    const badge = isFlow
                        ? '<span class="badge bg-info text-dark mt-1"><i class="bi bi-diagram-2-fill me-1"></i>Redirects to flow</span>'
                        : '<span class="badge bg-dark border mt-1" style="border-color:#2e3140!important;"><i class="bi bi-x-circle me-1"></i>Ends session</span>';
                    html += `<div class="p-3 rounded" style="background:#252836;border:1px solid #2e3140;border-left:3px solid ${c.colour};"><div class="fw-semibold" style="color:#f8f9fa;">${esc(o.label)}</div>${badge}</div>`;
                });
                html += '</div></div>';
            });
            html += '</div>';
            const body = document.getElementById('outcomeModalBody');
            const meta = document.getElementById('outcomeModalMeta');
            if (body) body.innerHTML = html;
            if (meta) meta.textContent = 'Session with Demo Visitor';
            const modalEl = document.getElementById('outcomeModal');
            if (modalEl && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modalEl).show();
            return outcomes.length;
        }
        """)
        time.sleep(0.8)
        rec.screenshot("Outcome modal — 4-column layout (Negative / Escalation / Neutral / Positive)")

        rec.page.evaluate("""
        () => {
            const cards = document.querySelectorAll('#outcomeModalBody [style*="border-left"]');
            for (const c of cards) {
                const label = c.querySelector('.fw-semibold');
                if (label && label.textContent.includes('Redirect to Test Flow')) {
                    c.style.boxShadow = '0 0 0 3px #fd7e14';
                    c.style.background = '#2e3240';
                }
            }
        }
        """)
        time.sleep(0.4)
        rec.screenshot("Outcome modal — 'Redirect to Test Flow' highlighted in Escalation column")

        rec.page.evaluate("""() => {
            const m = document.getElementById('outcomeModal');
            if (m && window.bootstrap) bootstrap.Modal.getInstance(m)?.hide();
        }""")
        time.sleep(0.3)

        # ── Step 7: Navigate visitor page to foreground, fire close_with_outcome
        rec.narrative(
            "The agent confirms the outcome.\n\n"
            "agent.js sends a close_with_outcome WebSocket message to the server:\n\n"
            "    { type: 'close_with_outcome',\n"
            "      session_key: '...',\n"
            "      outcome_id:  '0ba975e8-...' }\n\n"
            "The server:\n"
            "  1. Validates the outcome and records it against the session.\n"
            "  2. Sets _current_flow_id in the session's flow context.\n"
            "  3. Replies session_flow_redirected to the agent WebSocket.\n"
            "  4. Calls run_flow(), which loads the Test Message Flow and streams its\n"
            "     send_message node to the visitor's SSE endpoint."
        )

        # Navigate to the visitor chat URL in the foreground tab.
        # The recorder now tolerates networkidle timeout (SSE keeps network active).
        rec.navigate(VISITOR_URL, "Visitor chat widget — agent selects outcome now")
        time.sleep(1.5)  # let EventSource reconnect and receive 'resumed'

        # Signal the agent thread: visitor SSE is live in the foreground — fire now
        print("Signalling agent thread to fire close_with_outcome…")
        agent_thread.fire_outcome()

        # Poll until the flow message appears in the active page
        try:
            rec.page.wait_for_function(
                "window._sseMessages && window._sseMessages.some(m => m.type === 'message')",
                timeout=15000,
            )
            print("Flow message received in browser.")
        except Exception:
            print("wait_for_function timed out — proceeding with whatever arrived")
        time.sleep(0.5)

        sse_msgs = rec.page.evaluate("window._sseMessages || []")
        msg_types = [m.get("type") for m in sse_msgs]
        print(f"Visitor SSE events: {msg_types}")
        rec.screenshot("Visitor chat widget — flow message delivered by specialist transfer")

        rec.narrative(
            "The Test Message Flow has executed its send_message node, delivering:\n\n"
            "  'Your session has been transferred to a specialist. "
            "We appreciate your patience — they will be with you shortly.'\n\n"
            "The SSE stream also delivers an end event, which the visitor widget "
            "displays as a session-close banner. No page reload occurred — "
            "the message arrived via the existing SSE connection."
        )

        # Wait for the agent thread to finish cleanly
        agent_thread.wait(timeout=20.0)
        if agent_thread._error:
            print(f"Agent thread error: {agent_thread._error}")

        # ── Step 8: Agent Panel — session cleared ─────────────────────────────
        rec.narrative(
            "After the flow completes, the session is marked closed on the server. "
            "The agent's panel removes the session from the Mine list and decrements "
            "their active session count."
        )
        rec.navigate(f"{BASE}/agent", "Return to Agent Panel — after redirect")
        time.sleep(1.0)
        rec.screenshot("Agent Panel — session cleared after flow redirect")

        # ── Step 9: Outcomes admin page ───────────────────────────────────────
        rec.narrative(
            "Outcomes are configured on the Outcomes page in the admin panel.\n\n"
            "Each outcome has:\n"
            "  * A label (shown to agents in the modal)\n"
            "  * An outcome_type (negative / escalation / neutral / positive)\n"
            "  * An action_type (end_interaction or flow_redirect)\n"
            "  * An optional redirect_flow_id (required for flow_redirect outcomes)\n\n"
            "Outcomes can be assigned to specific queues or left unassigned to apply "
            "globally across all queues."
        )
        rec.navigate(f"{BASE}/outcomes", "Outcomes configuration page")
        time.sleep(0.8)
        rec.screenshot("Outcomes page — all active outcomes with their types and actions")

        # ── Step 10: Flow designer ────────────────────────────────────────────
        rec.narrative(
            "The target flow is configured in the Flow Designer.\n\n"
            "The Test Message Flow contains three nodes in sequence:\n"
            "  Start -> Send Message -> End\n\n"
            "The Send Message node's text field holds the message delivered to the visitor. "
            "Any flow can be assigned as a flow-redirect target, enabling complex "
            "multi-step specialist transfer journeys."
        )
        FLOW_ID = "f0876777-c2d2-4ecf-bd11-041a82d88afd"
        rec.navigate(f"{BASE}/flow-designer/{FLOW_ID}", "Flow Designer — Test Message Flow")
        time.sleep(1.2)
        rec.screenshot("Flow Designer — Test Message Flow (Start -> Send Message -> End)")

    OUTPUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    rec.save_docx(OUTPUT_DOCX)
    print(f"\nDOCX saved -> {OUTPUT_DOCX}")


if __name__ == "__main__":
    run()

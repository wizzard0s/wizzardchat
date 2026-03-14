"""
test_flow_redirect_e2e.py
=========================

Integration test that proves the flow-redirect outcome delivers the
configured flow message to the visitor's SSE stream.

Run with:
    & "C:\\Users\\nico.debeer\\CHATDEV\\.venv\\Scripts\\python.exe" docs\\test_flow_redirect_e2e.py
"""

import asyncio
import json
import uuid
import httpx
import websockets

BASE          = "http://localhost:8092"
WS_BASE       = "ws://localhost:8092"
ADMIN_USER    = "admin"
ADMIN_PASS    = "M@M@5t3r"
CONNECTOR_KEY = "c73BK6UdGf7knfRYjYkb8O7mdXiYeuvwR9SdmXpJEUs"


async def collect_sse_into(events: list, url: str, max_events: int = 30, timeout: float = 20.0):
    """Read SSE events into the provided list (shared by reference — survives cancellation)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 2)) as client:
            async with client.stream("GET", url) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        if raw:
                            try:
                                events.append(json.loads(raw))
                            except json.JSONDecodeError:
                                events.append({"raw": raw})
                    if len(events) >= max_events:
                        break
    except (httpx.ReadTimeout, httpx.RemoteProtocolError, asyncio.CancelledError, Exception):
        pass  # return whatever was collected


async def run_test():
    session_id = f"e2e-{uuid.uuid4().hex[:10]}"
    print(f"\n━━ Flow-Redirect E2E Test ━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Session: {session_id}\n")

    async with httpx.AsyncClient(timeout=15) as http:

        # ── 1. Login ──────────────────────────────────────────────────────────
        auth = await http.post(
            f"{BASE}/api/v1/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        auth.raise_for_status()
        token = auth.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"[1] ✅  Logged in as {ADMIN_USER}")

        # ── 2. Get the flow-redirect outcome ──────────────────────────────────
        outcomes_resp = await http.get(f"{BASE}/api/v1/outcomes", headers=headers, params={"active_only": True})
        outcomes_resp.raise_for_status()
        redirect_outcome = next((o for o in outcomes_resp.json() if o["action_type"] == "flow_redirect"), None)
        if not redirect_outcome:
            print("[2] ❌  No flow_redirect outcome found — run seed_outcomes_and_flow.py first")
            return
        print(f"[2] ✅  Redirect outcome: '{redirect_outcome['label']}' → flow {redirect_outcome['redirect_flow_id']}")

        # ── 3. Start visitor session ──────────────────────────────────────────
        init_url = f"{BASE}/chat/{CONNECTOR_KEY}/{session_id}/init"
        init_resp = await http.post(init_url, json={"name": "E2E Test Visitor"})
        if init_resp.status_code not in (200, 201):
            print(f"[3] ❌  Session init failed: {init_resp.status_code} {init_resp.text}")
            return
        init_data = init_resp.json()
        print(f"[3] ✅  Visitor session started: {init_resp.status_code}")
        if init_data.get("messages"):
            for m in init_data["messages"]:
                print(f"      → Bot: {m.get('text') or m.get('message', '')[:80]}")

        # ── 4. Subscribe to SSE (non-blocking) ───────────────────────────────
        sse_url = f"{BASE}/sse/chat/{CONNECTOR_KEY}/{session_id}"
        sse_events: list = []     # shared list — mutated in-place, survives task cancellation
        sse_task = asyncio.create_task(collect_sse_into(sse_events, sse_url, max_events=30, timeout=25.0))
        await asyncio.sleep(0.5)
        print(f"[4] ✅  SSE listener active on {sse_url}")

        # ── 5. Connect as agent via WebSocket ─────────────────────────────────
        ws_url = f"{WS_BASE}/ws/agent?token={token}"
        print(f"[5]    Connecting agent WS...")

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            print(f"[5] ✅  Agent WS connected")

            # Drain initial server-push messages (sessions snapshot, availability_set, etc.)
            for _ in range(8):
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    print(f"       Init msg: {msg.get('type', '?')}")
                except asyncio.TimeoutError:
                    break

            # ── 6. Send take_session ──────────────────────────────────────────
            await ws.send(json.dumps({"type": "take_session", "session_id": session_id}))
            print(f"[6]    take_session sent — draining responses…")
            for _ in range(10):
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    print(f"       Server: {msg.get('type','?')}")
                    if msg.get("type") in ("session_taken", "session_assigned"):
                        break
                except asyncio.TimeoutError:
                    break
            print(f"[6] ✅  take_session complete")

            # ── 7. Fetch outcomes for this session ────────────────────────────
            sess_outcomes = await http.get(
                f"{BASE}/api/v1/sessions/{session_id}/outcomes", headers=headers
            )
            sess_outcomes.raise_for_status()
            outcome_list = sess_outcomes.json()
            print(f"[7] ✅  Session has {len(outcome_list)} outcome(s):")
            for o in outcome_list:
                print(f"       [{o['outcome_type']:10s}] {o['label']} — {o['action_type']}")

            sel = next((o for o in outcome_list if o["action_type"] == "flow_redirect"), None)
            if not sel:
                print("[7] ⚠   No flow_redirect outcome in session outcomes — check queue assignment")
                sel = redirect_outcome  # use the one we know exists

            # ── 8. Send close_with_outcome ────────────────────────────────────
            await ws.send(json.dumps({
                "type":         "close_with_outcome",
                "session_id":   session_id,
                "outcome_id":   sel["id"],
                "outcome_code": sel["code"],
            }))
            print(f"[8]    Sent close_with_outcome → outcome: '{sel['label']}'")

            # Drain WS responses
            for _ in range(10):
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                    print(f"       Server: {msg.get('type','?')} outcome={msg.get('outcome_code','')}")
                    if msg.get("type") in ("session_closed", "session_flow_redirected"):
                        print(f"[8] ✅  Server confirmed: {msg['type']}")
                        break
                except asyncio.TimeoutError:
                    break

            # ── 9. Wait for SSE messages ──────────────────────────────────────
            print(f"[9]    Waiting for SSE events from flow…")
            await asyncio.sleep(6.0)  # let the flow run and SSE to flush
            sse_task.cancel()
            try:
                await sse_task        # let task finish cleanup; sse_events list already populated
            except (asyncio.CancelledError, Exception):
                pass

        # ── 10. Report SSE events ─────────────────────────────────────────────
        print(f"\n[10] SSE events received by visitor ({len(sse_events)} total):")
        msg_events = [e for e in sse_events if e.get("type") == "message"]
        end_events = [e for e in sse_events if e.get("type") == "end"]
        queue_events = [e for e in sse_events if e.get("type") == "queue"]

        for e in sse_events:
            t = e.get("type", "?")
            text = e.get("text") or e.get("message", "")
            print(f"     [{t:10s}] {str(text)[:100]}")

        print()
        if msg_events:
            print(f"✅  PASS — {len(msg_events)} message(s) delivered to visitor via SSE:")
            for m in msg_events:
                print(f"   → \"{m.get('text', '')}\"")
        elif end_events:
            print("⚠   Session ended — flow may have run but message was empty, or 'end' type sent instead")
        else:
            print("❌  FAIL — no messages delivered to visitor SSE; redirect flow did not run")

        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")


if __name__ == "__main__":
    asyncio.run(run_test())

"""
Build the Zyxel Router Installation test flow in WizzardChat via REST API.

Flow topology (left-to-right):

  start → greeting_msg → name_input → ask_model_msg → model_input
        → ai_bot (multi-turn) → closing_msg → end

The ai_bot node uses multi-turn mode (output_variable is blank) so it pauses
after each bot reply, waits for the visitor, then loops back through the node.
The conversation continues until the visitor types an exit keyword or reaches
max_turns — demonstrating the full up/down conversation cadence.

Run:
    cd c:\\Users\\nico.debeer\\CHATDEV
    .venv\\Scripts\\python docs\\create_zyxel_test_flow.py
"""

import requests

BASE  = "http://localhost:8092"
CTYPE = "application/x-www-form-urlencoded"
JTYPE = "application/json"


def post(url, *, data=None, json=None, headers):
    r = requests.request("POST" if data or json else "GET",
                         url, data=data, json=json, headers=headers)
    if not r.ok:
        raise RuntimeError(f"POST {url} → {r.status_code}: {r.text[:400]}")
    return r.json()


def put(url, *, json, headers):
    r = requests.put(url, json=json, headers=headers)
    if not r.ok:
        raise RuntimeError(f"PUT {url} → {r.status_code}: {r.text[:400]}")
    return r.json()


# ── 1. Auth ────────────────────────────────────────────────────────────────

token = post(f"{BASE}/api/v1/auth/login",
             data={"username": "admin", "password": "M@M@5t3r"},
             headers={"Content-Type": CTYPE})["access_token"]
HDR = {"Authorization": f"Bearer {token}", "Content-Type": JTYPE}
print(f"✓ Authenticated")


# ── 2. Create empty flow ───────────────────────────────────────────────────

flow = post(f"{BASE}/api/v1/flows",
            json={"name": "Zyxel Router Installation — AI Bot Demo",
                  "description": "Multi-turn AI Bot demo: Zyxel router setup support.",
                  "channel": "chat"},
            headers=HDR)
flow_id = flow["id"]
print(f"✓ Flow created: {flow_id}")


# ── 3. System prompt ───────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a friendly Zyxel technical-support specialist helping a home or \
small-business customer install their Zyxel router.

Your job:
1. Identify the customer's router model (already captured: {{router_model}}) \
and internet connection type (ADSL, VDSL, Fibre, LTE).
2. Provide clear, numbered installation steps tailored to their model and \
connection type.
3. If they mention error LEDs (red Power, WAN, or Internet), diagnose the \
cause and suggest a fix.
4. Ask ONE clarifying question at a time — be patient and concise.

Customer name: {{customer_name}}
Router model:  {{router_model}}

When the customer says their router is working, or when they type "done", \
"bye", or a similar farewell, confirm success and close warmly.\
"""


# ── 4. Create nodes one by one (captures real UUIDs) ──────────────────────

def add_node(node_type, label, x, y, config=None):
    return post(f"{BASE}/api/v1/flows/{flow_id}/nodes",
                json={"node_type": node_type, "label": label,
                      "position_x": x, "position_y": y,
                      "config": config or {}},
                headers=HDR)


n_start      = add_node("start",   "Start",                  60,   300)
n_greet      = add_node("message", "Greeting",               280,  300, {
    "message": (
        "Hi! 👋 Welcome to Zyxel router support. "
        "I'm here to help you get set up. "
        "What's your name?"
    )
})
n_input_name = add_node("input",   "Capture name",           500,  300, {
    "variable": "customer_name",
    "prompt":   "Please type your name:",
    "required": True,
})
n_ask_model  = add_node("message", "Ask router model",       720,  300, {
    "message": (
        "Nice to meet you, {{customer_name}}! "
        "Which Zyxel router model are you installing? "
        "(e.g. VMG3625, NBG7815, AX7501-B1…)"
    )
})
n_input_mdl  = add_node("input",   "Capture router model",   940,  300, {
    "variable": "router_model",
    "prompt":   "Enter your router model:",
    "required": True,
})
n_aibot      = add_node("ai_bot",  "Zyxel AI Support",       1160, 300, {
    "model":           "wizzardai://ollama/qwen3:8b",
    "system_prompt":   SYSTEM_PROMPT,
    "max_turns":       8,
    "temperature":     0.4,
    "exit_keywords":   "done, exit, bye, thanks, all good, works, working",
    "output_variable": "",          # blank = multi-turn loop mode
})
n_close      = add_node("message", "Closing",                1380, 300, {
    "message": (
        "Glad we could help! 🎉 "
        "Your Zyxel router should now be running, {{customer_name}}. "
        "Start a new chat any time you need support. Have a great day!"
    )
})
n_end        = add_node("end",     "End",                    1600, 300)

nodes_created = [n_start, n_greet, n_input_name, n_ask_model,
                 n_input_mdl, n_aibot, n_close, n_end]
print(f"✓ {len(nodes_created)} nodes created")


# ── 5. Wire edges ──────────────────────────────────────────────────────────

def add_edge(src_id, tgt_id, handle="default", label=""):
    return post(f"{BASE}/api/v1/flows/{flow_id}/edges",
                json={"source_node_id": src_id, "target_node_id": tgt_id,
                      "source_handle": handle, "label": label},
                headers=HDR)


wires = [
    (n_start["id"],     n_greet["id"],     "default", ""),
    (n_greet["id"],     n_input_name["id"],"default", ""),
    (n_input_name["id"],n_ask_model["id"], "default", ""),
    (n_ask_model["id"], n_input_mdl["id"], "default", ""),
    (n_input_mdl["id"], n_aibot["id"],     "default", ""),
    (n_aibot["id"],     n_close["id"],     "default", "max turns"),
    (n_aibot["id"],     n_close["id"],     "exit",    "exit keyword"),
    (n_close["id"],     n_end["id"],       "default", ""),
]

for src, tgt, handle, lbl in wires:
    add_edge(src, tgt, handle, lbl)
print(f"✓ {len(wires)} edges wired")


# ── 6. Publish ─────────────────────────────────────────────────────────────

post(f"{BASE}/api/v1/flows/{flow_id}/publish", json={}, headers=HDR)
print(f"✓ Flow published")


# ── 7. Summary ─────────────────────────────────────────────────────────────

print()
print("=" * 64)
print("ZYXEL ROUTER INSTALLATION — AI BOT DEMO FLOW")
print("=" * 64)
print(f"  Flow ID : {flow_id}")
print()
print("  Node sequence:")
for n in nodes_created:
    print(f"    [{n['node_type']:12s}]  {n['label']}")
print()
print(f"  Designer URL : http://localhost:8092")
print(f"  (open Flows, find 'Zyxel Router Installation — AI Bot Demo')")
print()
print("  Simulate multi-turn interaction:")
print(f"  POST http://localhost:8092/api/v1/flows/{flow_id}/simulate")
print("""  {
    "messages": [
      {"role":"user","content":"Alex"},
      {"role":"user","content":"VMG3625"},
      {"role":"user","content":"Internet light is red after plugging in"},
      {"role":"user","content":"I have VDSL fibre from Openserve"},
      {"role":"user","content":"I rebooted but still red"},
      {"role":"user","content":"Now it's green! Router is online"},
      {"role":"user","content":"done"}
    ]
  }""")

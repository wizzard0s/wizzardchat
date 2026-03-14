"""
Simulate the Zyxel Router Installation flow end-to-end and print
the conversation transcript showing every node transition.

The simulator API uses {node_id: value} inputs for input/menu nodes.
For ai_bot, the simulation returns a placeholder (no live LLM call).
"""
import requests, json, time

BASE    = "http://localhost:8092"
FLOW_ID = "59252871-7054-47db-a5db-9d6449e6fc80"

token = requests.post(
    f"{BASE}/api/v1/auth/login",
    data={"username": "admin", "password": "M@M@5t3r"},
    headers={"Content-Type": "application/x-www-form-urlencoded"},
).json()["access_token"]
HDR = {"Authorization": f"{token}", "Content-Type": "application/json"}
HDR["Authorization"] = f"Bearer {token}"

# ── Fetch node IDs ──────────────────────────────────────────────────────────
flow = requests.get(f"{BASE}/api/v1/flows/{FLOW_ID}", headers=HDR).json()
nodes_sorted = sorted(flow["nodes"], key=lambda n: n.get("position_x", 0))
# Order: start, greeting(msg), capture_name(input), ask_model(msg),
#        capture_model(input), ai_bot, closing(msg), end
(
    id_start, id_greet, id_input_name,
    id_ask_mdl, id_input_mdl, id_aibot,
    id_close, id_end
) = [n["id"] for n in nodes_sorted]

# ── Build inputs dict ─────────────────────────────────────────────────────
# Simulate a customer named Alex, with a VMG3625, internet LED red
inputs = {
    id_input_name: "Alex",
    id_input_mdl:  "Zyxel VMG3625-T20A",
}

print("=" * 68)
print("FLOW SIMULATION — Zyxel Router Installation AI Bot Demo")
print("=" * 68)
print(f"Flow ID  : {FLOW_ID}")
print(f"Customer : Alex  |  Model: Zyxel VMG3625-T20A")
print(f"Nodes    : {len(nodes_sorted)}  |  "
      f"Edges: {len(flow['edges'])}")
print()

t0 = time.time()
r  = requests.post(
    f"{BASE}/api/v1/flows/{FLOW_ID}/simulate",
    json={"inputs": inputs, "context": {}},
    headers=HDR,
    timeout=60,
)
elapsed = time.time() - t0

if not r.ok:
    print(f"ERROR {r.status_code}: {r.text[:600]}")
    raise SystemExit(1)

result = r.json()
status      = result.get("status", "?")
trace_steps = result.get("trace", [])
final_ctx   = result.get("final_context", {})

print(f"Status   : {status}")
print(f"Message  : {result.get('message', '')}")
print(f"Duration : {elapsed:.1f}s")
print(f"Steps    : {len(trace_steps)}")
print()

print("─" * 68)
print("TRANSCRIPT  (step | [node_type] label)")
print("─" * 68)

for step in trace_steps:
    s_num  = step.get("step", "?")
    ntype  = step.get("node_type", "?")
    label  = step.get("label", "?")
    output = step.get("output", "")
    note   = step.get("note", "")
    edge   = step.get("edge_taken", "")
    sstatus= step.get("status", "")
    ctx_after = step.get("context_after", {})

    # Node header
    edge_str = f"  →edge[{edge}]" if edge and edge != "default" else ""
    status_flag = f"  [{sstatus}]" if sstatus not in ("executed", "end") else ""
    print(f"\n  {s_num:2d}. [{ntype:12s}]  {label}{status_flag}{edge_str}")

    if note:
        # Word-wrap
        words = note.split()
        line, out_lines = [], []
        for w in words:
            if sum(len(x) + 1 for x in line) + len(w) > 60:
                out_lines.append(" ".join(line))
                line = []
            line.append(w)
        if line:
            out_lines.append(" ".join(line))
        for i, ln in enumerate(out_lines):
            prefix = "      Note  : " if i == 0 else "             "
            print(f"{prefix}{ln}")

    if isinstance(output, str) and output:
        words = output.split()
        line, out_lines = [], []
        for w in words:
            if sum(len(x) + 1 for x in line) + len(w) > 60:
                out_lines.append(" ".join(line))
                line = []
            line.append(w)
        if line:
            out_lines.append(" ".join(line))
        for i, ln in enumerate(out_lines):
            prefix = "      Bot   : " if i == 0 else "             "
            print(f"{prefix}{ln}")

    # Show context variables that changed in this step
    ctx_before = step.get("context_before", {})
    changed = {
        k: v for k, v in ctx_after.items()
        if not k.startswith("_") and ctx_after.get(k) != ctx_before.get(k)
        and isinstance(v, (str, int, float, bool))
    }
    if changed:
        print(f"      Vars   : {json.dumps(changed, ensure_ascii=False)[:80]}")

print()
print("─" * 68)
print("FINAL CONTEXT")
for k, v in final_ctx.items():
    if not k.startswith("_"):
        preview = str(v)[:80] if isinstance(v, str) else str(v)
        print(f"  {k:25s} = {preview}")
print()
print("Simulation complete.")
print()
print("NOTE: ai_bot node shows '[simulated]' in dry-run mode.")
print("For live AI responses, connect a visitor widget to this flow via a Connector.")
print(f"  Flow URL  : http://localhost:8092  (Flows → Zyxel Router Installation)")
print(f"  Flow ID   : {FLOW_ID}")

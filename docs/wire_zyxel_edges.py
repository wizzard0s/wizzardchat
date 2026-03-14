"""Fix the Zyxel flow: remove phantom node, verify edges, publish."""
import requests

BASE = "http://localhost:8092"
FLOW_ID = "59252871-7054-47db-a5db-9d6449e6fc80"

token = requests.post(
    f"{BASE}/api/v1/auth/login",
    data={"username": "admin", "password": "M@M@5t3r"},
    headers={"Content-Type": "application/x-www-form-urlencoded"},
).json()["access_token"]
HDR = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_flow():
    return requests.get(f"{BASE}/api/v1/flows/{FLOW_ID}", headers=HDR).json()


# 1. Remove phantom duplicate start node if present
flow = get_flow()
nodes = sorted(flow.get("nodes", []), key=lambda n: n.get("position_x", 0))
starts = [n for n in nodes if n["node_type"] == "start"]
if len(starts) > 1:
    # Keep x=60, delete the rest
    for extra in starts[1:]:
        nid = extra["id"]
        r = requests.delete(f"{BASE}/api/v1/flows/{FLOW_ID}/nodes/{nid}", headers=HDR)
        print(f"Deleted duplicate start {nid}: {r.status_code}")

# 2. Re-fetch and show current state
flow = get_flow()
nodes = sorted(flow.get("nodes", []), key=lambda n: n.get("position_x", 0))
edges = flow.get("edges", [])
print(f"\nNodes ({len(nodes)}):")
for n in nodes:
    print(f"  x={n['position_x']:5g}  {n['node_type']:12s}  {n['id'][:8]}  {n['label']}")

print(f"\nEdges ({len(edges)}):")
node_labels = {n["id"]: n["label"] for n in nodes}
for e in edges:
    src_label = node_labels.get(e["source_node_id"], e["source_node_id"][:8])
    tgt_label = node_labels.get(e["target_node_id"], e["target_node_id"][:8])
    print(f"  [{e['source_handle']:10s}]  {src_label} → {tgt_label}  «{e['label']}»")

# 3. Fill any missing edges
if len(nodes) == 8:
    n_start, n_greet, n_in_name, n_ask_mdl, n_in_mdl, n_aibot, n_close, n_end = (
        n["id"] for n in nodes
    )
    needed = [
        (n_start,   n_greet,   "default", ""),
        (n_greet,   n_in_name, "default", ""),
        (n_in_name, n_ask_mdl, "default", ""),
        (n_ask_mdl, n_in_mdl,  "default", ""),
        (n_in_mdl,  n_aibot,   "default", ""),
        (n_aibot,   n_close,   "default", "max turns"),
        (n_aibot,   n_close,   "exit",    "exit keyword"),
        (n_close,   n_end,     "default", ""),
    ]
    existing = {(e["source_node_id"], e["target_node_id"], e["source_handle"])
                for e in edges}
    added = 0
    for src, tgt, handle, lbl in needed:
        if (src, tgt, handle) not in existing:
            body = {"source_node_id": src, "target_node_id": tgt,
                    "source_handle": handle, "label": lbl}
            r = requests.post(f"{BASE}/api/v1/flows/{FLOW_ID}/edges",
                              json=body, headers=HDR)
            status = "✓" if r.status_code == 201 else "✗"
            print(f"  {status} Added edge [{handle}] {lbl}  ({r.status_code})")
            added += 1
    if added == 0:
        print("\nAll edges already present.")
else:
    print(f"\nWARN: expected 8 nodes, got {len(nodes)} — skipping edge check")

# 4. Publish
r = requests.post(f"{BASE}/api/v1/flows/{FLOW_ID}/publish", json={}, headers=HDR)
print(f"\n✓ Published: {r.status_code}")
print(f"\nFlow ID : {FLOW_ID}")
print("Open WizzardChat → Flows to find 'Zyxel Router Installation — AI Bot Demo'")

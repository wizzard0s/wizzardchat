"""
seed_outcomes_and_flow.py
=========================

Idempotent bootstrap script — creates the four standard outcomes plus
a "Test Message Flow" with a send_message node and assigns all four
outcomes to every existing queue.

Run with:
    & "C:\\Users\\nico.debeer\\CHATDEV\\.venv\\Scripts\\python.exe" docs/seed_outcomes_and_flow.py
"""

import sys
import json
import httpx

BASE       = "http://localhost:8092"
ADMIN_USER = "admin"
ADMIN_PASS = "M@M@5t3r"

# ──────────────────────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────────────────────

def login(client: httpx.Client) -> str:
    resp = client.post(
        f"{BASE}/api/v1/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    print("✅  Logged in")
    return token


# ──────────────────────────────────────────────────────────────────────────────
# Outcomes
# ──────────────────────────────────────────────────────────────────────────────

STANDARD_OUTCOMES = [
    {
        "code": "resolved",
        "label": "Resolved",
        "outcome_type": "positive",
        "action_type": "end_interaction",
        "description": "Issue resolved to the customer's satisfaction.",
        "is_active": True,
    },
    {
        "code": "unresolved",
        "label": "Unresolved",
        "outcome_type": "negative",
        "action_type": "end_interaction",
        "description": "Issue could not be resolved in this session.",
        "is_active": True,
    },
    {
        "code": "abandoned",
        "label": "Abandoned",
        "outcome_type": "negative",
        "action_type": "end_interaction",
        "description": "Customer disconnected before resolution.",
        "is_active": True,
    },
]


def ensure_outcome(client: httpx.Client, headers: dict, outcome_def: dict) -> dict:
    """Create an outcome if one with the same code does not already exist."""
    # Check existing
    existing = client.get(f"{BASE}/api/v1/outcomes", headers=headers, params={"active_only": False})
    existing.raise_for_status()
    for o in existing.json():
        if o["code"] == outcome_def["code"]:
            print(f"   ↩  Outcome '{outcome_def['code']}' already exists — skipping")
            return o

    resp = client.post(f"{BASE}/api/v1/outcomes", json=outcome_def, headers=headers)
    if resp.status_code not in (200, 201):
        print(f"   ⚠  Failed to create outcome '{outcome_def['code']}': {resp.status_code} {resp.text}")
        sys.exit(1)
    obj = resp.json()
    print(f"   ✅  Created outcome '{obj['code']}' (id={obj['id']})")
    return obj


# ──────────────────────────────────────────────────────────────────────────────
# Test flow
# ──────────────────────────────────────────────────────────────────────────────

FLOW_NAME = "Test Message Flow"

def ensure_test_flow(client: httpx.Client, headers: dict) -> str:
    """Return the UUID of the test flow, creating it if needed."""

    # Check for existing flow with the same name
    flows_resp = client.get(f"{BASE}/api/v1/flows", headers=headers)
    flows_resp.raise_for_status()
    for f in flows_resp.json():
        if f["name"] == FLOW_NAME:
            print(f"   ↩  Flow '{FLOW_NAME}' already exists — id={f['id']}")
            return f["id"]

    # 1. Create the flow
    flow_resp = client.post(
        f"{BASE}/api/v1/flows",
        json={"name": FLOW_NAME, "description": "Demo flow used to test flow_redirect outcomes.", "flow_type": "main_flow"},
        headers=headers,
    )
    flow_resp.raise_for_status()
    flow = flow_resp.json()
    flow_id = flow["id"]
    print(f"   ✅  Created flow '{FLOW_NAME}' (id={flow_id})")

    # Find the auto-created start node
    start_node_id = None
    for n in flow.get("nodes", []):
        if n["node_type"] == "start":
            start_node_id = n["id"]
            break

    # 2. Add a send_message node
    msg_resp = client.post(
        f"{BASE}/api/v1/flows/{flow_id}/nodes",
        json={
            "node_type": "send_message",
            "label": "Welcome Message",
            "position_x": 250,
            "position_y": 200,
            "position": 1,
            "config": {
                "message": (
                    "You have been redirected by your agent. "
                    "We appreciate your patience — a specialist will be with you shortly."
                )
            },
        },
        headers=headers,
    )
    msg_resp.raise_for_status()
    msg_node_id = msg_resp.json()["id"]
    print(f"   ✅  Added send_message node (id={msg_node_id})")

    # 3. Add an end node
    end_resp = client.post(
        f"{BASE}/api/v1/flows/{flow_id}/nodes",
        json={
            "node_type": "end",
            "label": "End",
            "position_x": 250,
            "position_y": 350,
            "position": 2,
            "config": {},
        },
        headers=headers,
    )
    end_resp.raise_for_status()
    end_node_id = end_resp.json()["id"]
    print(f"   ✅  Added end node (id={end_node_id})")

    # 4. Edge: start → send_message
    if start_node_id:
        e1 = client.post(
            f"{BASE}/api/v1/flows/{flow_id}/edges",
            json={"source_node_id": start_node_id, "target_node_id": msg_node_id, "source_handle": "default"},
            headers=headers,
        )
        e1.raise_for_status()

    # 5. Edge: send_message → end
    e2 = client.post(
        f"{BASE}/api/v1/flows/{flow_id}/edges",
        json={"source_node_id": msg_node_id, "target_node_id": end_node_id, "source_handle": "default"},
        headers=headers,
    )
    e2.raise_for_status()
    print(f"   ✅  Linked nodes (start → message → end)")

    # 6. Publish the flow
    pub_resp = client.post(f"{BASE}/api/v1/flows/{flow_id}/publish", headers=headers)
    if pub_resp.status_code == 200:
        print(f"   ✅  Flow published")
    else:
        print(f"   ⚠  Publish returned {pub_resp.status_code}: {pub_resp.text}")

    return flow_id


# ──────────────────────────────────────────────────────────────────────────────
# flow_redirect outcome
# ──────────────────────────────────────────────────────────────────────────────

def ensure_flow_redirect_outcome(client: httpx.Client, headers: dict, flow_id: str) -> dict:
    existing = client.get(f"{BASE}/api/v1/outcomes", headers=headers, params={"active_only": False})
    existing.raise_for_status()
    for o in existing.json():
        if o["code"] == "test_flow_redirect":
            print(f"   ↩  Outcome 'test_flow_redirect' already exists — skipping")
            # Ensure redirect_flow_id is correct
            return o

    outcome_def = {
        "code": "test_flow_redirect",
        "label": "Redirect to Test Flow",
        "outcome_type": "escalation",
        "action_type": "flow_redirect",
        "redirect_flow_id": flow_id,
        "description": "Redirects the visitor to the Test Message Flow for demonstration.",
        "is_active": True,
    }
    resp = client.post(f"{BASE}/api/v1/outcomes", json=outcome_def, headers=headers)
    if resp.status_code not in (200, 201):
        print(f"   ⚠  Failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    obj = resp.json()
    print(f"   ✅  Created outcome 'test_flow_redirect' (id={obj['id']})")
    return obj


# ──────────────────────────────────────────────────────────────────────────────
# Assign outcomes to all queues
# ──────────────────────────────────────────────────────────────────────────────

def assign_outcomes_to_queues(client: httpx.Client, headers: dict, outcome_ids: list[str]) -> None:
    queues_resp = client.get(f"{BASE}/api/v1/queues", headers=headers)
    queues_resp.raise_for_status()
    queues = queues_resp.json()

    if not queues:
        print("   ⚠  No queues found — create one in the UI and re-run this script")
        return

    for q in queues:
        # Merge existing outcome IDs with new ones (dedup)
        existing_ids: list = q.get("outcomes") or []
        # existing_ids may be a list of strings or dicts; normalise to str
        existing_str = [str(x["id"]) if isinstance(x, dict) else str(x) for x in existing_ids]
        merged = list(dict.fromkeys(existing_str + outcome_ids))  # preserve order, dedup

        # Build the PUT body using all required QueueCreate fields
        put_body = {
            "name": q["name"],
            "channel": q["channel"],
            "strategy": q.get("strategy", "round_robin"),
            "priority": q.get("priority", 0),
            "max_wait_time": q.get("max_wait_time", 300),
            "sla_threshold": q.get("sla_threshold", 30),
            "color": q.get("color", "#fd7e14"),
            "outcomes": merged,
            "is_active": q.get("is_active", True),
        }
        if q.get("description"):
            put_body["description"] = q["description"]
        if q.get("overflow_queue_id"):
            put_body["overflow_queue_id"] = str(q["overflow_queue_id"])
        if q.get("flow_id"):
            put_body["flow_id"] = str(q["flow_id"])
        if q.get("disconnect_timeout_seconds") is not None:
            put_body["disconnect_timeout_seconds"] = q["disconnect_timeout_seconds"]
        if q.get("disconnect_outcome_id"):
            put_body["disconnect_outcome_id"] = str(q["disconnect_outcome_id"])

        upd = client.put(f"{BASE}/api/v1/queues/{q['id']}", json=put_body, headers=headers)
        if upd.status_code == 200:
            print(f"   ✅  Queue '{q['name']}' updated with {len(merged)} outcome(s)")
        else:
            print(f"   ⚠  Queue '{q['name']}' update failed: {upd.status_code} {upd.text}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n── WizzardChat Outcome Seed ─────────────────────────────────────────")

    with httpx.Client(timeout=20) as client:
        token   = login(client)
        headers = {"Authorization": f"Bearer {token}"}

        print("\n[1] Standard outcomes")
        created_outcomes = []
        for od in STANDARD_OUTCOMES:
            created_outcomes.append(ensure_outcome(client, headers, od))

        print("\n[2] Test flow")
        flow_id = ensure_test_flow(client, headers)

        print("\n[3] Flow-redirect outcome")
        redirect_outcome = ensure_flow_redirect_outcome(client, headers, flow_id)
        created_outcomes.append(redirect_outcome)

        print("\n[4] Assign to queues")
        outcome_ids = [str(o["id"]) for o in created_outcomes]
        assign_outcomes_to_queues(client, headers, outcome_ids)

    print("\n── Done ─────────────────────────────────────────────────────────────")
    print("Outcomes seeded:")
    for o in created_outcomes:
        print(f"  [{o['outcome_type']:10s}] {o['label']:30s}  action={o['action_type']}")
    print()


if __name__ == "__main__":
    main()

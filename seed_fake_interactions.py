# seed_fake_interactions.py
# Full realistic seed for WizzardChat:
#   100 fake agents (SA names, bcrypt passwords)
#   500 fake contacts  (SA names, +27 phones, SA emails)
#   Agents linked to all queues via chat_queue_agents
#   12 weeks of realistic interactions distributed across agents, queues & contacts
#   Proper segments, message logs, CSAT/NPS
#
# Run with the WIZZARDCHAT venv:
#   python seed_fake_interactions.py
#
# DRY_RUN = True  -> preview counts only, no DB writes
# WIPE_FIRST = True (default) -> delete previous fake data before inserting

from __future__ import annotations

import json
import random
import uuid
from collections import Counter
from datetime import datetime, timedelta

import bcrypt
import psycopg2
from psycopg2.extras import execute_values

# ─── Config ───────────────────────────────────────────────────────────────────

DB_URL      = "host=127.0.0.1 port=5432 dbname=wizzardfrw user=postgres password=postgres"
SCHEMA      = "chat"
WEEKS_BACK  = 12
DRY_RUN     = False
WIPE_FIRST  = True

NUM_AGENTS   = 100
NUM_CONTACTS = 500

FAKE_TAG = "seed:fake"   # used in username/session_key prefix for easy cleanup

# ─── Real IDs already in the DB ───────────────────────────────────────────────

CONNECTOR_ID = "27abd3e2-88df-483c-8960-71ce2b90d4a6"   # testChat connector

QUEUES = [
    {"id": "bcbc20f2-753c-4802-b079-40d3c025f9cb", "name": "General Support", "weight": 50, "channel": "CHAT"},
    {"id": "1f714c67-156b-44d4-afd7-63901581cb31", "name": "test",             "weight": 35, "channel": "CHAT"},
    {"id": "445761b7-e0b8-426a-a892-8d5204dc7b10", "name": "WhatsApp Support", "weight": 15, "channel": "WHATSAPP"},
]

# ─── SA name pools ────────────────────────────────────────────────────────────

FIRST_NAMES = [
    # Zulu / Xhosa / Sotho
    "Sipho", "Themba", "Ayanda", "Nkosi", "Lungelo", "Bongani", "Siyanda",
    "Lungisa", "Mthokozisi", "Sifiso", "Khulekani", "Nhlanhla", "Mduduzi",
    "Sibusiso", "Thandeka", "Nomvula", "Zanele", "Nokwanda", "Ntombizodwa",
    "Ntombi", "Zodwa", "Nomsa", "Lindiwe", "Nompumelelo", "Busisiwe",
    "Nozipho", "Sindisiwe", "Phindile", "Nokuthula", "Simangele",
    "Lerato", "Dineo", "Palesa", "Mpho", "Kelebogile", "Refilwe",
    "Tebogo", "Boitumelo", "Karabo", "Lesego",
    # Afrikaans / Cape Malay
    "Pieter", "Jan", "Hendrik", "Francois", "Charl", "Gerrit", "Riaan",
    "Morne", "Hannes", "Danie", "Marelize", "Anri", "Liezel", "Charne",
    "Nadine", "Elizma", "Rene", "Ilze", "Sunette", "Carien",
    # Indian SA
    "Priya", "Kavitha", "Sharmila", "Nisha", "Devika", "Ashwin",
    "Rajan", "Krishen", "Suren", "Anil",
    # English SA
    "David", "Michael", "Sarah", "Emma", "Jessica", "Luke", "Ryan",
    "Keegan", "Brendan", "Taryn", "Jade", "Lara", "Shane", "Gareth",
    "Lauren", "Nicole", "Robyn", "Kyle", "Dean", "Tammy",
]

LAST_NAMES = [
    "Dlamini", "Nkosi", "Zulu", "Mthembu", "Khumalo", "Nxumalo", "Mhlongo",
    "Ngcobo", "Ntuli", "Mbatha", "Cele", "Mkhize", "Gumede", "Ndlovu",
    "Molefe", "Mokoena", "Sithole", "Mabaso", "Madlala", "Majola",
    "Luthuli", "Hadebe", "Shabalala", "Buthelezi", "Zungu",
    "Motsepe", "Naidoo", "Pillay", "Govender", "Moodley",
    "Singh", "Patel", "Reddy", "Chetty", "Perumal",
    "Van der Merwe", "Du Plessis", "Botha", "Pretorius", "Venter",
    "Fourie", "Joubert", "Swanepoel", "Coetzee", "Steyn",
    "Smith", "Jones", "Williams", "Brown", "Taylor",
    "Johnson", "Davis", "Wilson", "Anderson", "Martin",
]

SA_CITIES = [
    ("Johannesburg", "Gauteng", "2001"),
    ("Pretoria",     "Gauteng", "0001"),
    ("Cape Town",    "Western Cape", "8001"),
    ("Durban",       "KwaZulu-Natal", "4001"),
    ("Port Elizabeth","Eastern Cape", "6001"),
    ("Bloemfontein", "Free State", "9300"),
    ("East London",  "Eastern Cape", "5201"),
    ("Polokwane",    "Limpopo", "0700"),
    ("Nelspruit",    "Mpumalanga", "1200"),
    ("Kimberley",    "Northern Cape", "8300"),
]

VISITOR_MESSAGES = [
    ("Hi, I need help with my account", "Sure, I can help you with that. What seems to be the issue?"),
    ("My payment didn't go through", "I'm sorry to hear that. Let me look into your payment details."),
    ("I want to cancel my subscription", "I understand. Can I ask what's prompted the cancellation?"),
    ("When will my order arrive?", "Let me check the status of your order right now."),
    ("I keep getting an error when logging in", "Let's get that sorted. What error message are you seeing?"),
    ("I was overcharged on my last bill", "I apologise for the inconvenience. Let me pull up your billing history."),
    ("How do I reset my password?", "I can walk you through the password reset process."),
    ("The app keeps crashing", "That's frustrating. Which device are you using?"),
    ("I need to update my delivery address", "Of course. What's the new address you'd like to use?"),
    ("Can I get a refund?", "I'll check your account and see what options are available."),
    ("It's been 3 days and no response to my email", "I sincerely apologise for the delay. Let me escalate this for you."),
    ("I can't find my invoice", "Let me resend that invoice to your email address right now."),
]

# ─── Volume model ─────────────────────────────────────────────────────────────

BASE_VOLUMES = {
    8: 2,  9: 5, 10: 9, 11: 8, 12: 4,
    13: 6, 14: 9, 15: 7, 16: 5, 17: 3,
    18: 2, 19: 1,
}
WEEKDAY_MULTIPLIER = [1.0, 1.05, 0.95, 0.90, 0.85, 0.35, 0.15]   # Mon–Sun


def volume_for(dt: datetime) -> int:
    base = BASE_VOLUMES.get(dt.hour, 0)
    mul  = WEEKDAY_MULTIPLIER[dt.weekday()]
    avg  = base * mul
    if avg <= 0:
        return 0
    return random.randint(max(0, int(avg * 0.5)), max(1, int(avg * 1.8)))


# ─── Builders ─────────────────────────────────────────────────────────────────

def _sa_phone() -> str:
    prefix = random.choice(["60", "61", "72", "73", "74", "76", "78", "79",
                             "81", "82", "83", "84"])
    return f"+27{prefix}{random.randint(1000000, 9999999)}"


def _hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=10)).decode()


def build_agent(index: int) -> dict:
    first = random.choice(FIRST_NAMES)
    last  = random.choice(LAST_NAMES)
    slug  = f"fake.{first.lower().replace(' ', '')}.{last.lower().replace(' ', '')}_{index}"
    role  = "SUPERVISOR" if index % 10 == 0 else "AGENT"
    return {
        "id":               str(uuid.uuid4()),
        "email":            f"{slug}@fake.wizzard.local",
        "username":         slug,
        "hashed_password":  _hash_pw("Fake@gent1"),
        "full_name":        f"{first} {last}",
        "role":             role,
        "is_active":        True,
        "is_online":        False,
        "is_system_account": False,
        "auth_type":        "LOCAL",
        "max_concurrent_chats": random.choice([3, 4, 5, 6]),
        "languages":        json.dumps(["en"]),
        "phone_number":     _sa_phone(),
        "created_at":       datetime.utcnow(),
        "updated_at":       datetime.utcnow(),
    }


def build_contact(index: int) -> dict:
    first = random.choice(FIRST_NAMES)
    last  = random.choice(LAST_NAMES)
    city, state, postal = random.choice(SA_CITIES)
    slug  = f"{first.lower().replace(' ', '')}.{last.lower().replace(' ', '')}_{index}"
    phone = _sa_phone()
    return {
        "id":           str(uuid.uuid4()),
        "first_name":   first,
        "last_name":    last,
        "title":        random.choice(["Mr", "Ms", "Mrs", "Dr"]),
        "job_title":    random.choice(["Manager", "Director", "Analyst", "Consultant",
                                       "Engineer", "Accountant", "Teacher", "Nurse", None]),
        "company":      random.choice(["Acme Corp", "Telkom", "Vodacom", "MTN",
                                       "Standard Bank", "ABSA", "FNB", "Nedbank",
                                       "Discovery", "Old Mutual", None]),
        "email":        f"{slug}@fake.wizzard.local",
        "phone":        phone,
        "whatsapp_id":  phone,
        "address_line1": f"{random.randint(1, 999)} {random.choice(['Main', 'Church', 'Park', 'Oak', 'Long'])} Street",
        "city":         city,
        "state":        state,
        "postal_code":  postal,
        "country":      "South Africa",
        "status":       "ACTIVE",
        "created_at":   datetime.utcnow(),
        "updated_at":   datetime.utcnow(),
    }


def build_interaction(
    slot_start: datetime,
    queue: dict,
    agent_id: str,
    contact: dict,
) -> dict:
    iid      = uuid.uuid4()
    offset_s = random.uniform(0, 1800)
    created  = slot_start + timedelta(seconds=offset_s)

    wait_s      = random.uniform(10, 360)
    queue_start = created
    queue_end   = created + timedelta(seconds=wait_s)

    handle_s    = random.uniform(45, 1200)
    agent_start = queue_end
    agent_end   = agent_start + timedelta(seconds=handle_s)

    wrap_s      = random.uniform(15, 180)
    wrap_start  = agent_end
    last_act    = wrap_start + timedelta(seconds=wrap_s)

    abandoned = random.random() < 0.06   # 6% abandon rate

    if abandoned:
        segments   = [{"type": "queue", "started_at": queue_start.isoformat(),
                        "ended_at": queue_end.isoformat(),
                        "queue_id": queue["id"], "waited_seconds": round(wait_s, 1)}]
        wrap_time  = None
        eff_agent  = None
    else:
        segments = [
            {"type": "queue", "started_at": queue_start.isoformat(),
             "ended_at": queue_end.isoformat(),
             "queue_id": queue["id"], "waited_seconds": round(wait_s, 1)},
            {"type": "agent", "started_at": agent_start.isoformat(),
             "ended_at": agent_end.isoformat(), "agent_id": agent_id},
        ]
        wrap_time = int(wrap_s)
        eff_agent = agent_id

    # Message log — realistic exchange
    pair     = random.choice(VISITOR_MESSAGES)
    n_extra  = random.randint(0, 6)
    msgs     = [
        {"from": "visitor", "text": pair[0], "ts": created.isoformat()},
        {"from": "agent",   "text": pair[1],
         "ts": (created + timedelta(seconds=random.uniform(5, 30))).isoformat()},
    ]
    for i in range(n_extra):
        side = "visitor" if i % 2 == 0 else "agent"
        msgs.append({"from": side, "text": f"Follow-up message {i+1}",
                     "ts": (created + timedelta(seconds=60 * (i + 2))).isoformat()})

    # CSAT (30% chance)
    if not abandoned and random.random() < 0.30:
        csat = random.choices([1, 2, 3, 4, 5], weights=[2, 3, 10, 30, 55])[0]
        csat_submitted = agent_end + timedelta(minutes=random.randint(2, 30))
    else:
        csat = None
        csat_submitted = None

    # NPS (15% chance)
    if not abandoned and random.random() < 0.15:
        nps = random.choices(range(11), weights=[1,1,1,2,2,3,5,8,12,20,25])[0]
        nps_submitted = agent_end + timedelta(minutes=random.randint(5, 60))
    else:
        nps = None
        nps_submitted = None

    visitor_meta = {
        "name":  f"{contact['first_name']} {contact['last_name']}",
        "email": contact["email"],
        "phone": contact["phone"],
        "fake":  True,
    }

    return {
        "id":                str(iid),
        "connector_id":      CONNECTOR_ID,
        "session_key":       f"fake-{iid}",
        "visitor_metadata":  json.dumps(visitor_meta),
        "flow_context":      json.dumps({}),
        "waiting_node_id":   None,
        "queue_id":          queue["id"],
        "status":            "closed",
        "agent_id":          eff_agent,
        "message_log":       json.dumps(msgs),
        "created_at":        created,
        "last_activity_at":  last_act,
        "visitor_last_seen": last_act,
        "disconnect_outcome": "resolved" if not abandoned else "abandoned",
        "csat_score":        csat,
        "csat_comment":      None,
        "csat_submitted_at": csat_submitted,
        "nps_score":         nps,
        "nps_reason":        None,
        "nps_submitted_at":  nps_submitted,
        "notes":             random.choice([None, None, None,
                                            "Customer issue resolved satisfactorily.",
                                            "Escalated to billing team.",
                                            "Callback scheduled."]),
        "wrap_started_at":   wrap_start if not abandoned else None,
        "wrap_time":         wrap_time,
        "segments":          json.dumps(segments),
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WizzardChat — realistic fake data seeder")
    print("=" * 60)

    # ── 1. Build agent + contact lists ────────────────────────────
    print(f"\nBuilding {NUM_AGENTS} agents and {NUM_CONTACTS} contacts…")
    agents   = [build_agent(i)   for i in range(NUM_AGENTS)]
    contacts = [build_contact(i) for i in range(NUM_CONTACTS)]

    # ── 2. Build interaction rows ──────────────────────────────────
    now   = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(weeks=WEEKS_BACK)

    agent_ids = [a["id"] for a in agents]
    weights   = [q["weight"] for q in QUEUES]

    interactions: list[dict] = []
    slot = start
    while slot <= now:
        count = volume_for(slot)
        for _ in range(count):
            q       = random.choices(QUEUES, weights=weights, k=1)[0]
            agent   = random.choice(agent_ids)
            contact = random.choice(contacts)
            interactions.append(build_interaction(slot, q, agent, contact))
        slot += timedelta(minutes=30)

    print(f"Generated {len(interactions):,} interactions over {WEEKS_BACK} weeks")
    by_q = Counter(r["queue_id"] for r in interactions)
    for q in QUEUES:
        print(f"  {q['name']}: {by_q[q['id']]:,}")
    abandoned = sum(1 for r in interactions if r["disconnect_outcome"] == "abandoned")
    print(f"  Abandoned: {abandoned:,} ({abandoned/len(interactions)*100:.1f}%)")

    if DRY_RUN:
        print("\nDRY_RUN=True — no DB writes")
        return

    # ── 3. DB writes ───────────────────────────────────────────────
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()

        # ── Wipe previous fake data ──
        if WIPE_FIRST:
            print("\nWiping previous fake data…")
            cur.execute(f"DELETE FROM {SCHEMA}.chat_interactions WHERE session_key LIKE 'fake-%%'")
            print(f"  Removed {cur.rowcount:,} interactions")
            cur.execute(f"DELETE FROM {SCHEMA}.chat_queue_agents qa "
                        f"USING {SCHEMA}.chat_users u "
                        f"WHERE qa.user_id = u.id AND u.username LIKE 'fake.%%'")
            print(f"  Removed {cur.rowcount:,} queue-agent links")
            cur.execute(f"DELETE FROM {SCHEMA}.chat_users WHERE username LIKE 'fake.%%'")
            print(f"  Removed {cur.rowcount:,} agents")
            cur.execute(f"DELETE FROM {SCHEMA}.chat_contacts WHERE email LIKE '%%@fake.wizzard.local'")
            print(f"  Removed {cur.rowcount:,} contacts")
            conn.commit()

        # ── Insert agents ──
        print(f"\nInserting {len(agents):,} agents…")
        agent_cols = [
            "id", "email", "username", "hashed_password", "full_name",
            "role", "is_active", "is_online", "is_system_account", "auth_type",
            "max_concurrent_chats", "languages", "phone_number",
            "created_at", "updated_at",
        ]
        execute_values(
            cur,
            f"INSERT INTO {SCHEMA}.chat_users ({', '.join(agent_cols)}) VALUES %s "
            f"ON CONFLICT (username) DO NOTHING",
            [tuple(a[c] for c in agent_cols) for a in agents],
            page_size=200,
        )
        conn.commit()

        # Reload actual inserted agent IDs (avoid conflict skips)
        cur.execute(
            f"SELECT id FROM {SCHEMA}.chat_users WHERE username LIKE 'fake.%%'"
        )
        inserted_agent_ids = [str(row[0]) for row in cur.fetchall()]
        print(f"  {len(inserted_agent_ids):,} agents in DB")

        # ── Link every agent to all queues ──
        print("Linking agents to all queues…")
        qa_rows = [
            (q["id"], aid)
            for q in QUEUES
            for aid in inserted_agent_ids
        ]
        execute_values(
            cur,
            f"INSERT INTO {SCHEMA}.chat_queue_agents (queue_id, user_id) VALUES %s "
            f"ON CONFLICT DO NOTHING",
            qa_rows,
            page_size=500,
        )
        conn.commit()
        print(f"  {len(qa_rows):,} queue-agent links created")

        # ── Insert contacts ──
        print(f"\nInserting {len(contacts):,} contacts…")
        contact_cols = [
            "id", "first_name", "last_name", "title", "job_title", "company",
            "email", "phone", "whatsapp_id",
            "address_line1", "city", "state", "postal_code", "country",
            "status", "created_at", "updated_at",
        ]
        execute_values(
            cur,
            f"INSERT INTO {SCHEMA}.chat_contacts ({', '.join(contact_cols)}) VALUES %s "
            f"ON CONFLICT DO NOTHING",
            [tuple(c[k] for k in contact_cols) for c in contacts],
            page_size=200,
        )
        conn.commit()
        print(f"  Done")

        # ── Reassign interactions to only real inserted agent IDs ──
        for row in interactions:
            if row["agent_id"] and row["agent_id"] not in inserted_agent_ids:
                row["agent_id"] = random.choice(inserted_agent_ids) if inserted_agent_ids else None

        # ── Insert interactions ──
        print(f"\nInserting {len(interactions):,} interactions…")
        ix_cols = [
            "id", "connector_id", "session_key", "visitor_metadata", "flow_context",
            "waiting_node_id", "queue_id", "status", "agent_id", "message_log",
            "created_at", "last_activity_at", "visitor_last_seen", "disconnect_outcome",
            "csat_score", "csat_comment", "csat_submitted_at",
            "nps_score", "nps_reason", "nps_submitted_at",
            "notes", "wrap_started_at", "wrap_time", "segments",
        ]
        execute_values(
            cur,
            f"INSERT INTO {SCHEMA}.chat_interactions ({', '.join(ix_cols)}) VALUES %s",
            [tuple(r[c] for c in ix_cols) for r in interactions],
            page_size=500,
        )
        conn.commit()

        # ── Summary ──
        print("\n── Final counts ──────────────────────────────────────")
        for tbl, label in [
            ("chat_users     WHERE username LIKE 'fake.%%'",            "Fake agents"),
            ("chat_contacts  WHERE email    LIKE '%%@fake.wizzard.local'", "Fake contacts"),
            ("chat_interactions WHERE session_key LIKE 'fake-%%'",      "Fake interactions"),
        ]:
            cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{tbl}")
            print(f"  {label}: {cur.fetchone()[0]:,}")

    finally:
        conn.close()

    print("\nDone ✓")


if __name__ == "__main__":
    main()

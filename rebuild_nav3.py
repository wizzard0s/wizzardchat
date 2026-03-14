"""
rebuild_nav3.py
Transforms all non-agent templates to use the unified sidebar:
  - Replaces Bootstrap dropdown footer with agent-style user block + availability select
  - Moves user block above the nav <ul> (after logo)
  - Updates <nav> tag to remove Bootstrap inline sizing (handled by wizzardchat.css)
  - Removes lone <hr> before nav-ul; adds hr after availability select
"""

import pathlib, re

TMPL_DIR = pathlib.Path(r"C:\Users\nico.debeer\WIZZARDCHAT\templates")

# Templates to skip
SKIP = {"agent.html", "login.html", "flow_designer.html", "dialler.html"}

# ── Snippet to inject (after logo, before nav ul) ─────────────────────────────
USER_BLOCK = '''\
    <div class="d-flex align-items-center gap-2 mb-1">
        <span class="flex-fill text-truncate small" id="agentName">\u2013</span>
        <button class="btn btn-sm btn-outline-secondary" id="btnLogout" title="Sign out"><i class="bi bi-box-arrow-right"></i></button>
    </div>
    <select class="form-select form-select-sm av-offline mb-2" id="availabilitySelect" title="Set your availability">
        <option value="available">\U0001f7e2 Available</option>
        <option value="admin">\U0001f535 Admin</option>
        <option value="lunch">\U0001f7e1 Lunch</option>
        <option value="break">\U0001f7e0 Break</option>
        <option value="training">\U0001f7e3 Training</option>
        <option value="meeting">\U0001f535 Meeting</option>
        <option value="offline" selected>\u26ab Offline</option>
    </select>
    <hr class="border-secondary">'''

processed = 0

for f in sorted(TMPL_DIR.glob("*.html")):
    if f.name in SKIP:
        print(f"SKIP: {f.name}")
        continue

    html = f.read_text(encoding="utf-8")

    # ── 1. Update the <nav> opening tag ─────────────────────────────────────
    html = html.replace(
        '<nav id="sidebar" class="d-flex flex-column flex-shrink-0 p-3 text-bg-dark" style="width:220px;height:100vh;position:fixed;">',
        '<nav id="sidebar" class="p-3 text-white">'
    )

    # ── 2. Change mb-3 to mb-2 on logo link ─────────────────────────────────
    html = html.replace(
        '<a href="/" class="d-flex align-items-center mb-3 text-white text-decoration-none">',
        '<a href="/" class="d-flex align-items-center mb-2 text-white text-decoration-none">'
    )

    # ── 3. Replace <hr> + <ul nav> with user-block + hr + <ul nav> ──────────
    #    Pattern: standalone <hr> immediately before the nav ul
    html = re.sub(
        r'(\s*<hr>\n)(\s*<ul class="nav nav-pills flex-column flex-nowrap")',
        lambda m: "\n" + USER_BLOCK + "\n" + m.group(2),
        html,
        count=1
    )

    # ── 4. Remove trailing <hr> + Bootstrap dropdown ────────────────────────
    html = re.sub(
        r'\s*<hr>\s*\n\s*<div class="dropdown">.*?</div>\s*\n(\s*</nav>)',
        r'\n    \1',
        html,
        flags=re.DOTALL
    )

    f.write_text(html, encoding="utf-8")
    print(f"OK:   {f.name}")
    processed += 1

print(f"\nDone. {processed} files updated.")

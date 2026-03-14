"""
add_sidebar_js.py
Injects <script src="/static/js/sidebar.js"></script> into every template
that has a sidebar, placing it BEFORE the page-specific JS (or before </body>).
Skips: login.html, flow_designer.html, dialler.html (no sidebar).
"""
import pathlib, re

TMPL_DIR = pathlib.Path(r"C:\Users\nico.debeer\WIZZARDCHAT\templates")
SKIP = {"login.html", "flow_designer.html", "dialler.html"}
SIDEBAR_TAG = '<script src="/static/js/sidebar.js"></script>'

for f in sorted(TMPL_DIR.glob("*.html")):
    if f.name in SKIP:
        print(f"SKIP: {f.name}")
        continue

    html = f.read_text(encoding="utf-8")

    # Already has it?
    if "sidebar.js" in html:
        print(f"ALREADY: {f.name}")
        continue

    # Find the bootstrap bundle script (common to all pages) and insert sidebar.js after it
    bootstrap_tag = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>'
    if bootstrap_tag in html:
        new_html = html.replace(bootstrap_tag, bootstrap_tag + "\n    " + SIDEBAR_TAG, 1)
    else:
        # Fallback: insert before </body>
        new_html = html.replace("</body>", f"    {SIDEBAR_TAG}\n</body>", 1)

    f.write_text(new_html, encoding="utf-8")
    print(f"OK:   {f.name}")

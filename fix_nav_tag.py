"""fix_nav_tag.py - normalize the <nav id="sidebar"> opening tag in all non-agent templates"""
import pathlib, re

TMPL_DIR = pathlib.Path(r"C:\Users\nico.debeer\WIZZARDCHAT\templates")
SKIP = {"agent.html", "login.html", "flow_designer.html", "dialler.html"}

for f in sorted(TMPL_DIR.glob("*.html")):
    if f.name in SKIP:
        continue
    html = f.read_text(encoding="utf-8")
    new = re.sub(
        r'<nav id="sidebar" class="[^"]*"(\s+style="[^"]*")?>',
        '<nav id="sidebar" class="p-3 text-white">',
        html, count=1
    )
    if new != html:
        f.write_text(new, encoding="utf-8")
        print(f"Fixed: {f.name}")
    else:
        print(f"OK:    {f.name}")

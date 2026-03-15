"""
Playwright test: integration tabs feature in WizzardChat.
Creates a queue with YouTube + CNN URLs and a campaign with News24,
then verifies the UI shows the Integrations tab and saves correctly.
"""
import asyncio
import os
import json
from pathlib import Path
from playwright.async_api import async_playwright

BASE = "http://localhost:8092"
SHOTS = Path(__file__).parent / "screenshots"
SHOTS.mkdir(exist_ok=True)

ADMIN_USER = "admin"
ADMIN_PASS = "M@M@5t3r"

_token = None


async def get_token(page):
    """Retrieve JWT token from localStorage."""
    t = await page.evaluate("localStorage.getItem('wizzardchat_token')")
    return t


async def api_call(page, method, path, body=None):
    """Make an authenticated API call via JS fetch inside the page."""
    js = f"""
    (async () => {{
        const tok = localStorage.getItem('wizzardchat_token');
        const opts = {{ method: {json.dumps(method)}, headers: {{ 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }} }};
        {f"opts.body = JSON.stringify({json.dumps(body)});" if body else ""}
        const r = await fetch({json.dumps(BASE + path)}, opts);
        return {{ status: r.status, body: await r.json().catch(() => ({{}})) }};
    }})()
    """
    return await page.evaluate(js)


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.wait_for_selector("#username", timeout=5_000)
    await page.fill("#username", ADMIN_USER)
    await page.fill("#password", ADMIN_PASS)
    await page.screenshot(path=str(SHOTS / "00_login.png"))
    await page.click("button[type=submit]")
    await page.wait_for_url("**/", timeout=15_000)
    print(f"  logged in (now at {page.url})")


async def ensure_queue(page):
    """Create a test queue if none exists; return queue id."""
    r = await api_call(page, "GET", "/api/v1/queues")
    queues = r["body"] if isinstance(r["body"], list) else []
    if queues:
        print(f"  using existing queue: {queues[0]['name']} ({queues[0]['id']})")
        return queues[0]["id"]
    # Create one
    r = await api_call(page, "POST", "/api/v1/queues", {
        "name": "Test Chat Queue",
        "channel": "chat",
        "strategy": "round_robin",
    })
    assert r["status"] == 200, f"Queue create failed: {r}"
    qid = r["body"]["id"]
    print(f"  created queue id={qid}")
    return qid


async def ensure_campaign(page):
    """Create a test campaign if none exists; return campaign id."""
    r = await api_call(page, "GET", "/api/v1/campaigns")
    cdata = r["body"] if isinstance(r["body"], list) else []
    if cdata:
        print(f"  using existing campaign: {cdata[0]['name']} ({cdata[0]['id']})")
        return cdata[0]["id"]
    r = await api_call(page, "POST", "/api/v1/campaigns", {
        "name": "Test Outbound",
        "campaign_type": "manual",
        "channel": "chat",
        "status": "draft",
    })
    assert r["status"] == 200, f"Campaign create failed: {r}"
    cid = r["body"]["id"]
    print(f"  created campaign id={cid}")
    return cid


async def test_queues_integration_tab(page, queue_id):
    print(f"\n[1] Queue {queue_id} — add integration URLs")
    await page.goto(f"{BASE}/queues")
    await page.wait_for_load_state("networkidle", timeout=8_000)
    await page.screenshot(path=str(SHOTS / "01_queues_list.png"), full_page=False)

    card_count = await page.locator(".queue-card").count()
    print(f"  found {card_count} queue cards")

    # Click the first queue card
    first_card = page.locator(".queue-card").first
    # Collect ALL console messages
    errors = []
    all_msgs = []
    page.on("console", lambda msg: all_msgs.append(f"{msg.type}: {msg.text}") or (errors.append(msg.text) if msg.type == "error" else None))
    # Get onclick to see which ID the card uses
    onclick_val = await first_card.get_attribute("onclick")
    print(f"  first card onclick: {onclick_val}")
    # Extract UUID from onclick attr
    q_id = onclick_val.split("'")[1]
    # Call openQueueModal via evaluate — this WILL surface hidden JS errors
    try:
        await page.evaluate(f"openQueueModal('{q_id}')")
        await page.wait_for_timeout(1000)
        modal_class = await page.locator("#queueModal").get_attribute("class")
        print(f"  #queueModal class after evaluate call: {modal_class}")
    except Exception as e:
        print(f"  openQueueModal(id) threw: {e}")
    await page.screenshot(path=str(SHOTS / "02a_after_evaluate_call.png"))
    await page.wait_for_selector("#queueModal.show", timeout=8_000)

    # Click Integrations tab
    integ_tab = page.locator("[data-bs-target='#tabQIntegrations']")
    await integ_tab.click()
    await page.wait_for_selector("#tabQIntegrations.show, #tabQIntegrations.active", timeout=3_000)
    await page.screenshot(path=str(SHOTS / "02_queue_integrations_tab.png"), full_page=False)

    # Fill slot 1 — YouTube
    await page.fill("#qSlotName_1", "YouTube")
    await page.fill("#qSlotUrl_1", "https://www.youtube.com/")
    # Fill slot 2 — CNN
    await page.fill("#qSlotName_2", "CNN News")
    await page.fill("#qSlotUrl_2", "https://edition.cnn.com/")
    # Enable override
    override = page.locator("#qOverrideCampaign")
    if not await override.is_checked():
        await override.check()
    await page.screenshot(path=str(SHOTS / "03_queue_integration_slots_filled.png"), full_page=False)

    # Save
    await page.click("button[onclick='saveQueue()']")
    await page.wait_for_selector(".modal", state="hidden", timeout=8_000)
    await page.screenshot(path=str(SHOTS / "04_queue_saved.png"), full_page=False)
    print("  queue integration URLs saved")


async def test_campaigns_integration_tab(page, campaign_id):
    print(f"\n[2] Campaign {campaign_id} — add integration URL")
    await page.goto(f"{BASE}/campaigns")
    await page.wait_for_load_state("networkidle", timeout=8_000)
    await page.screenshot(path=str(SHOTS / "05_campaigns_list.png"), full_page=False)

    card_count = await page.locator(".campaign-card").count()
    print(f"  found {card_count} campaign cards")

    # Open first campaign modal
    first_card = page.locator(".campaign-card").first
    await first_card.click(timeout=8_000)
    await page.wait_for_selector("#campaignModal.show", timeout=8_000)

    # Click Integrations tab
    integ_tab = page.locator("[data-bs-target='#tabCIntegrations']")
    await integ_tab.click()
    await page.wait_for_selector("#tabCIntegrations.show, #tabCIntegrations.active", timeout=3_000)

    await page.fill("#cSlotName_1", "News24")
    await page.fill("#cSlotUrl_1", "https://www.news24.com/")
    await page.screenshot(path=str(SHOTS / "06_campaign_integration_slots_filled.png"), full_page=False)

    # Save
    await page.click("button[onclick='saveCampaign()']")
    await page.wait_for_selector(".modal", state="hidden", timeout=8_000)
    print("  campaign integration URLs saved")


async def test_agent_panel(page):
    print("\n[3] Agent panel — verify integration tab bar DOM elements")
    await page.goto(f"{BASE}/agent")
    await page.wait_for_load_state("networkidle", timeout=10_000)
    await page.screenshot(path=str(SHOTS / "07_agent_panel_idle.png"), full_page=False)

    # Check that the integration tab bar element is in the DOM
    bar = page.locator("#integrationTabBar")
    assert await bar.count() > 0, "#integrationTabBar not found in DOM"
    # Check iSlot elements
    for i in range(1, 6):
        slot = page.locator(f"#iSlot_{i}")
        assert await slot.count() > 0, f"#iSlot_{i} not found"
    # Verify chatSlot wrapper exists
    chat_slot = page.locator("#chatSlot")
    assert await chat_slot.count() > 0, "#chatSlot not found"
    print("  #integrationTabBar, #chatSlot, and #iSlot_1..5 present in DOM OK")
    await page.screenshot(path=str(SHOTS / "08_agent_dom_verified.png"), full_page=False)


async def verify_queue_saved(page, queue_id):
    """Re-open the queue and verify integration_urls persisted."""
    print("\n[4] Verify queue integration URLs persisted via API")
    r = await api_call(page, "GET", f"/api/v1/queues/{queue_id}")
    integ = r["body"].get("integration_urls", {})
    slots = integ.get("slots", [])
    override = integ.get("override_campaign", False)
    print(f"  slots: {slots}")
    print(f"  override_campaign: {override}")
    assert len(slots) >= 2, f"Expected >=2 slots, got {slots}"
    assert slots[0]["name"] == "YouTube"
    assert slots[1]["name"] == "CNN News"
    assert override is True
    print("  API verification passed OK")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        try:
            await login(page)
            await page.goto(f"{BASE}/queues")  # ensure we're on a page with full app context
            await page.wait_for_load_state("networkidle")

            queue_id = await ensure_queue(page)
            campaign_id = await ensure_campaign(page)

            await test_queues_integration_tab(page, queue_id)
            await test_campaigns_integration_tab(page, campaign_id)
            await verify_queue_saved(page, queue_id)
            await test_agent_panel(page)

            print(f"\nAll checks passed. Screenshots in: {SHOTS}")
        except Exception as e:
            await page.screenshot(path=str(SHOTS / "error.png"), full_page=False)
            print(f"\nFAILED: {e}")
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())



async def test_queues_integration_tab(page):
    print("\n[1] Queue — add integration URLs")
    await page.goto(f"{BASE}/queues")
    await page.wait_for_load_state("networkidle", timeout=8_000)
    await page.screenshot(path=str(SHOTS / "01_queues_list.png"), full_page=False)

    # Check how many queue cards exist
    card_count = await page.locator(".queue-card").count()
    print(f"  found {card_count} queue cards")
    await page.screenshot(path=str(SHOTS / "01b_queues_debug.png"), full_page=True)

    if card_count == 0:
        print("  no queues found — skipping queue test")
        return

    # Click the first queue card
    first_card = page.locator(".queue-card").first
    await first_card.click(timeout=10_000)
    await page.wait_for_selector(".modal.show", timeout=5_000)

    # Click Integrations tab
    integ_tab = page.locator("[data-bs-target='#tabQIntegrations']")
    await integ_tab.click()
    await page.wait_for_selector("#tabQIntegrations.show, #tabQIntegrations.active", timeout=3_000)
    await page.screenshot(path=str(SHOTS / "02_queue_integrations_tab.png"), full_page=False)

    # Fill slot 1 — YouTube
    await page.fill("#qSlotName_1", "YouTube")
    await page.fill("#qSlotUrl_1", "https://www.youtube.com/")
    # Fill slot 2 — CNN
    await page.fill("#qSlotName_2", "CNN News")
    await page.fill("#qSlotUrl_2", "https://edition.cnn.com/")
    # Enable override
    override = page.locator("#qOverrideCampaign")
    if not await override.is_checked():
        await override.check()
    await page.screenshot(path=str(SHOTS / "03_queue_integration_slots_filled.png"), full_page=False)

    # Save
    await page.click("button[onclick='saveQueue()']")
    await page.wait_for_selector(".modal", state="hidden", timeout=8_000)
    await page.screenshot(path=str(SHOTS / "04_queue_saved.png"), full_page=False)
    print("  queue integration URLs saved")


async def test_campaigns_integration_tab(page):
    print("\n[2] Campaign — add integration URL")
    await page.goto(f"{BASE}/campaigns")
    await page.wait_for_load_state("networkidle", timeout=8_000)
    await page.screenshot(path=str(SHOTS / "05_campaigns_list.png"), full_page=False)

    # Open first campaign modal (campaign-card with onclick="openCampaignModal(...)")
    first_card = page.locator(".campaign-card").first
    await first_card.click(timeout=10_000)
    await page.wait_for_selector(".modal.show", timeout=5_000)

    # Click Integrations tab
    integ_tab = page.locator("[data-bs-target='#tabCIntegrations']")
    await integ_tab.click()
    await page.wait_for_selector("#tabCIntegrations.show, #tabCIntegrations.active", timeout=3_000)

    await page.fill("#cSlotName_1", "News24")
    await page.fill("#cSlotUrl_1", "https://www.news24.com/")
    await page.screenshot(path=str(SHOTS / "06_campaign_integration_slots_filled.png"), full_page=False)

    # Save
    await page.click("button[onclick='saveCampaign()']")
    await page.wait_for_selector(".modal", state="hidden", timeout=8_000)
    print("  campaign integration URLs saved")


async def test_agent_panel(page):
    print("\n[3] Agent panel — verify integration tab bar appears")
    await page.goto(f"{BASE}/agent")
    await page.wait_for_load_state("networkidle", timeout=10_000)
    await page.screenshot(path=str(SHOTS / "07_agent_panel_idle.png"), full_page=False)

    # Check that the integration tab bar element is in the DOM
    bar = page.locator("#integrationTabBar")
    assert await bar.count() > 0, "#integrationTabBar not found in DOM"
    # Check iSlot elements
    for i in range(1, 6):
        slot = page.locator(f"#iSlot_{i}")
        assert await slot.count() > 0, f"#iSlot_{i} not found"
    print("  #integrationTabBar and #iSlot_1..5 present in DOM")
    await page.screenshot(path=str(SHOTS / "08_agent_dom_verified.png"), full_page=False)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        try:
            await login(page)
            await test_queues_integration_tab(page)
            await test_campaigns_integration_tab(page)
            await test_agent_panel(page)
            print(f"\nAll checks passed. Screenshots in: {SHOTS}")
        except Exception as e:
            await page.screenshot(path=str(SHOTS / "error.png"), full_page=False)
            print(f"\nFAILED: {e}")
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

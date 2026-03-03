"""Playwright E2E tests for WizzardChat UI."""

import pytest


def test_login_page_loads(page):
    """Homepage loads and shows the login modal."""
    page.goto("/")
    page.wait_for_selector("#loginModal", state="visible", timeout=5000)
    assert page.locator("#loginUser").is_visible()
    assert page.locator("#loginPass").is_visible()


def test_login_flow(page):
    """Full login via the UI form."""
    page.goto("/")
    page.wait_for_selector("#loginModal", state="visible", timeout=5000)
    page.fill("#loginUser", "admin")
    page.fill("#loginPass", "M@M@5t3r")
    page.click("#loginForm button[type='submit']")
    # After login the modal closes and username appears
    page.wait_for_selector("#currentUser", timeout=5000)
    assert page.inner_text("#currentUser") != ""


def test_navigation_sections(authed_page):
    """Sidebar navigation loads each section without errors."""
    page = authed_page
    for section in ["flows", "users", "campaigns", "queues", "contacts", "settings"]:
        link = page.locator(f"[data-section='{section}']")
        if link.count() > 0:
            link.click()
            page.wait_for_timeout(500)
            # Should not see a JS error alert
            assert page.locator(".alert-danger:visible").count() == 0


def test_flow_designer_loads(authed_page):
    """Flow designer page opens and shows canvas."""
    page = authed_page
    page.goto("/flow-designer")
    page.wait_for_selector("#canvas", timeout=5000)
    assert page.locator("#canvas").is_visible()
    assert page.locator("#edgeSvg").is_visible()

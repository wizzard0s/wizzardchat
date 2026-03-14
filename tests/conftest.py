"""Shared Playwright fixtures for WizzardChat E2E tests."""

import os
import pytest
from playwright.sync_api import sync_playwright, Page, BrowserContext

BASE_URL = os.getenv("WIZZARDCHAT_URL", "http://127.0.0.1:8091")
ADMIN_USER = os.getenv("WIZZARDCHAT_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("WIZZARDCHAT_ADMIN_PASS")  # must be set in env — no default


@pytest.fixture(scope="session")
def browser():
    """Launch a browser once per test session."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def context(browser) -> BrowserContext:
    """Fresh browser context (isolated cookies/storage) per test."""
    ctx = browser.new_context(base_url=BASE_URL)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context) -> Page:
    """Fresh page per test."""
    pg = context.new_page()
    yield pg
    pg.close()


@pytest.fixture
def auth_token() -> str:
    """Get a valid JWT token via the login API (no browser needed)."""
    import httpx

    resp = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture
def authed_page(context, auth_token) -> Page:
    """Page with auth token pre-loaded in localStorage."""
    pg = context.new_page()
    pg.goto("/")
    pg.evaluate(f"localStorage.setItem('wizzardchat_token', '{auth_token}')")
    pg.goto("/")
    yield pg
    pg.close()

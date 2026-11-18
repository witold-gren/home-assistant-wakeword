"""The login page in a real browser (Playwright + installed Chrome; skipped when missing)."""

import threading

import pytest

from wakeword.studio.server import make_server

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def base(household_dir, tmp_path):
    server = make_server(household_dir, ("admin", "pa:ss"), port=0, verbose=False, secret_folder=tmp_path / "secret")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def browser():
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:  # noqa: BLE001 - no Chrome on this computer
            pytest.skip(f"Chrome not available: {err}")
        yield browser
        browser.close()


def test_login_page_in_polish_and_dark(base, browser):
    page = browser.new_context(color_scheme="dark").new_page()
    page.goto(base + "/")  # not logged in: the login page
    assert page.url.endswith("/login")
    page.goto(base + "/login?lang=pl")
    assert page.locator("h1").inner_text() == "Studio słów budzących"
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.fill("input[name=user]", "admin")
    page.fill("input[name=password]", "wrong")
    page.click("button[type=submit]")
    page.wait_for_selector("#error:text('Zły użytkownik albo hasło.')")
    page.fill("input[name=password]", "pa:ss")
    page.click("button[type=submit]")
    page.wait_for_url(base + "/")
    assert page.locator("wakeword-studio").count() == 1


def test_login_page_in_english_and_light(base, browser):
    page = browser.new_context(color_scheme="light", locale="en-US").new_page()
    page.goto(base + "/login")
    assert page.locator("button[type=submit]").inner_text() == "Log in"
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert "config/env" in page.locator(".hint").inner_text()

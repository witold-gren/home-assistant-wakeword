"""The studio in a real browser (Playwright + installed Chrome; skipped when missing), on the demo household."""

from pathlib import Path
import sys
import threading
import time

import pytest
import yaml

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "docs"))

playwright = pytest.importorskip("playwright.sync_api")
studio_demo = pytest.importorskip("studio_demo")
screenshots = pytest.importorskip("demo_household")

from wakeword import elevenlabs, ha_sync  # noqa: E402
from wakeword.trainer import runner as runner_module  # noqa: E402
from wakeword.trainer import server as trainer_module  # noqa: E402


@pytest.fixture
def studio(tmp_path, monkeypatch):
    # start_studio changes these for the demo; they come back after the test
    monkeypatch.setattr(runner_module.LocalRunner, "status", runner_module.LocalRunner.status)
    monkeypatch.setattr(ha_sync, "CONFIG_FILE", ha_sync.CONFIG_FILE)
    monkeypatch.setattr(elevenlabs, "KEY_FILE", elevenlabs.KEY_FILE)
    monkeypatch.setattr(trainer_module, "POLL_SECONDS", 0)
    server, base = studio_demo.start_studio(tmp_path)
    yield server, base
    server.shutdown()


@pytest.fixture
def page(studio):
    _server, base = studio
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:  # noqa: BLE001 - no Chrome on this computer
            pytest.skip(f"Chrome not available: {err}")
        context = browser.new_context(viewport={"width": 1500, "height": 950}, color_scheme="dark")
        context.add_init_script("localStorage.setItem('wakeword-studio-lang', 'en');")
        context.add_init_script("localStorage.setItem('wakeword-studio-tour', 'done');")  # its own tests: test_studio_tour
        page = context.new_page()
        page.errors = []
        page.on("pageerror", lambda err: page.errors.append(str(err)))
        page.goto(base + "/login")
        page.fill("input[name=user]", "demo")
        page.fill("input[name=password]", "demo")
        page.click("button[type=submit]")
        page.wait_for_selector(".view-host > *")
        yield page
        assert page.errors == []
        browser.close()


def household_file(studio):
    return yaml.safe_load((studio[0].studio.household / "household.yaml").read_text(encoding="utf-8"))


def go(page, node):
    page.click(f"[data-node='{node}']")
    page.wait_for_selector(f"[data-view='{node}'] > *")


def test_tree_and_views_open(page):
    assert page.locator("h1").inner_text() == "Wake word studio"
    for node in ("overview", "people", "person/anna", "words", "word/hej_jarvis", "devices", "recordings", "background",
                 "piper", "elevenlabs", "samples", "train-data", "train-run", "train-live", "models", "export",
                 "targets", "ha", "power", "hf", "account", "look", "jobs"):
        page.evaluate(f"location.hash = '#/{node}'")
        page.wait_for_selector(f"[data-view='{node}'] > *")
        assert not page.locator(".view-host pre.terminal:has-text('Error')").count(), node
    assert page.locator("[data-node='person/ola'].warn").count() == 1  # Hej Robo 11/18
    page.fill("[data-search]", "robo")
    assert page.locator("[data-node='word/hej_robo']").count() == 1
    assert page.locator("[data-node='word/hej_jarvis']").count() == 0


def test_draft_undo_save_history(page, studio):
    go(page, "people")
    page.fill("[data-new-person]", "tomek")
    page.click("[data-add-person]")
    page.wait_for_selector("[data-person='tomek']")
    assert page.get_attribute("[data-draft-state]", "data-draft-state") == "draft"
    assert "tomek" not in [s["id"] for s in household_file(studio)["speakers"]]  # only a draft
    page.click("[data-undo]")
    page.wait_for_selector("[data-person='tomek']", state="detached")
    page.click("[data-redo]")
    page.wait_for_selector("[data-person='tomek']")
    page.wait_for_timeout(1200)  # the draft is kept on the server
    page.reload()
    page.wait_for_selector("[data-node='person/tomek']")
    assert page.get_attribute("[data-draft-state]", "data-draft-state") == "draft"
    page.click("[data-save]")
    page.wait_for_selector("[data-dialog='save'] [data-diff]")
    assert "person/tomek" in page.inner_text("[data-changes]")
    page.fill("[data-save-note]", "tomek added")
    page.click("[data-save-confirm]")
    page.wait_for_selector("[data-notice='ok']")
    assert [s["id"] for s in household_file(studio)["speakers"]][-1] == "tomek"
    assert page.get_attribute("[data-draft-state]", "data-draft-state") == "clean"
    page.click("[data-history]")
    page.wait_for_selector("[data-version]")
    assert "tomek added" in page.inner_text("[data-dialog='history']")
    page.click("[data-version]")
    page.wait_for_selector("[data-restore]")
    page.click("[data-restore]")
    page.wait_for_selector("[data-node='person/tomek']", state="detached")
    assert page.get_attribute("[data-draft-state]", "data-draft-state") == "draft"
    assert "tomek" in [s["id"] for s in household_file(studio)["speakers"]]  # restored only as a draft


def test_side_yaml_and_whole_file(page):
    go(page, "word/hej_jarvis")
    side = page.locator("[data-side-yaml-text]")
    side.fill(side.input_value().replace("wake_word: Hej Jarvis", "wake_word: Hej Dżarwis"))
    page.wait_for_function("document.querySelector('[data-wake-word]').value === 'Hej Dżarwis'")
    side.fill("hej_jarvis: [")
    page.wait_for_selector("[data-side-yaml] .field-error")
    page.click("[data-yaml]")
    whole = page.locator("[data-yaml-all] textarea")
    assert "Hej Dżarwis" in whole.input_value()
    whole.fill("- not a mapping")
    page.wait_for_selector("[data-yaml-error]")


def test_conflict_needs_save_anyway(page, studio):
    go(page, "targets")
    page.fill("[data-target='adult']", "14")
    page.wait_for_timeout(1200)
    file = studio[0].studio.household / "household.yaml"
    file.write_text(file.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # changed elsewhere meanwhile
    page.click("[data-save]")
    page.click("[data-save-confirm]")
    page.wait_for_selector("[data-save-conflict]")
    page.click("[data-save-force]")
    page.wait_for_selector("[data-notice='ok']")
    assert household_file(studio)["targets"]["adult"] == 14


def test_theme_language_and_menu(page):
    page.click("[data-theme-button]")
    first = page.evaluate("document.documentElement.dataset.theme")
    page.click("[data-theme-button]")
    assert page.evaluate("document.documentElement.dataset.theme") != first
    go(page, "look")  # the full view: language and theme as fields
    page.select_option("[data-language]", "pl")
    page.wait_for_function("document.querySelector('h1').textContent === 'Studio słów budzących'")
    page.click("[data-menu]")
    assert page.locator("[data-menu-pop] [data-logout]").count() == 1


def test_gear_opens_a_pop_up_and_leaves_the_view(page):
    """⚙ opens a pop-up under itself (like ☰), not another view: the centre and the address stay."""
    go(page, "targets")
    url = page.url
    page.click("[data-settings]")
    pop = page.locator("[data-gear-pop]")
    assert pop.is_visible()
    # the icons of the shared standard: ⚙ = cog-outline, the full view = palette-outline
    assert page.locator("[data-settings] ha-icon").get_attribute("icon") == "mdi:cog-outline"
    assert page.locator("[data-gear-all] ha-icon").get_attribute("icon") == "mdi:palette-outline"
    heights = page.eval_on_selector_all("[data-theme-seg] button", "bs => bs.map(b => b.getBoundingClientRect().height)")
    assert max(heights) - min(heights) < 1 and max(heights) < 40  # every label on one line („Jak system” too)
    assert page.url == url and page.locator("[data-view='targets'] > *").count() > 0
    box, button = pop.bounding_box(), page.locator("[data-settings]").bounding_box()
    assert box["y"] >= button["y"] + button["height"] - 1  # under the button
    assert abs((box["x"] + box["width"]) - (button["x"] + button["width"])) < 2  # aligned to its right edge

    page.click("[data-theme-choice='light']")  # works at once, the pop-up stays
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert pop.is_visible() and page.locator("[data-theme-choice='light']").get_attribute("aria-pressed") == "true"
    page.click("[data-language-choice='pl']")
    page.wait_for_function("document.querySelector('h1').textContent === 'Studio słów budzących'")
    assert pop.is_visible() and page.url == url
    assert page.locator("[data-language-choice='pl']").get_attribute("aria-pressed") == "true"


def test_gear_closes_with_escape_a_click_outside_and_again(page):
    for close in ("escape", "outside", "again"):
        page.click("[data-settings]")
        assert page.locator("[data-gear-pop]").is_visible()
        if close == "escape":
            page.keyboard.press("Escape")
        elif close == "outside":
            page.click("h1")
        else:
            page.click("[data-settings]")
        assert page.locator("[data-gear-pop]").count() == 0, close


def test_gear_leads_to_the_full_view_and_the_menus_close_each_other(page):
    page.click("[data-settings]")
    page.click("[data-gear-all]")
    page.wait_for_selector("[data-view='look'] [data-language]")
    assert page.locator("[data-gear-pop]").count() == 0
    page.click("[data-menu]")
    page.click("[data-settings]")  # ⚙ closes ☰
    assert page.locator("[data-menu-pop]").count() == 0 and page.locator("[data-gear-pop]").is_visible()
    page.click("[data-menu]")  # and ☰ closes ⚙
    assert page.locator("[data-gear-pop]").count() == 0 and page.locator("[data-menu-pop]").is_visible()


def test_the_menu_closes_with_escape_and_a_click_outside(page):
    page.click("[data-menu]")
    page.keyboard.press("Escape")
    assert page.locator("[data-menu-pop]").count() == 0
    page.click("[data-menu]")
    page.click("h1")
    assert page.locator("[data-menu-pop]").count() == 0


def test_training_starts_with_a_preset_and_live_follows(page, studio):
    server, _base = studio
    go(page, "train-run")
    page.click("[data-preset='family']")
    assert page.input_value("#negative-weight") == "30"
    page.fill("#steps", "2000")
    page.click("#start")
    page.wait_for_selector("[data-view='train-live'] > *")  # the live view opens
    studio_demo.set_log(server, screenshots.training_log(time.time() - 600, 2000, finished=False), running=True)
    page.wait_for_selector("[data-view='train-live'] .tile")
    page.wait_for_selector("[data-training-pill]")
    log = (server.studio.household / "data" / "build" / "train.log").read_text()
    assert "--all" not in log and "hej_jarvis" in log  # train.sh got the chosen word


ALL_VIEWS = ("overview", "people", "person/anna", "words", "word/hej_jarvis", "devices", "recordings", "background",
             "piper", "elevenlabs", "samples", "train-data", "train-run", "train-live", "models", "export",
             "targets", "ha", "power", "hf", "account", "jobs")


def test_only_the_top_bar_question_mark_opens_the_documentation(page):
    top = page.locator("header.top [data-docs]")
    assert top.get_attribute("href") == "/docs/en/" and top.get_attribute("target") == "_blank"
    for node in ALL_VIEWS:
        page.evaluate(f"location.hash = '#/{node}'")
        page.wait_for_selector(f"[data-view='{node}'] > *")
        # no "?" next to fields, and no "?" inside a view leads away from the studio
        assert page.locator(".view-host .field-q, .view-host [data-guide]").count() == 0, node
        assert page.locator(".view-host a[href^='/docs/']").count() == 0, node
        heads = page.locator(f"[data-view='{node}'] .card-head")
        for i in range(heads.count()):
            assert heads.nth(i).locator(".help-btn").count() <= 1, node  # at most one "?" per card


def test_question_mark_of_a_card_opens_a_help_window(page):
    go(page, "train-run")
    pages_before = len(page.context.pages)
    button = page.locator("[data-view='train-run'] .help-btn").first
    button.click()
    pop = page.wait_for_selector("[data-help-pop]")
    assert len(page.context.pages) == pages_before  # nothing opened in a new tab
    box, view = pop.bounding_box(), page.viewport_size
    assert box["x"] >= 0 and box["y"] >= 0 and box["x"] + box["width"] <= view["width"]  # inside the screen
    assert pop.query_selector(".help-pop-body").inner_text().strip()  # the text of this one thing
    more = pop.query_selector(".help-pop-more a")
    if more:  # the guide only as an extra, at its chapter's anchor
        assert more.get_attribute("target") == "_blank" and "#" in more.get_attribute("href")
    page.keyboard.press("Escape")
    page.wait_for_selector("[data-help-pop]", state="detached")
    button.click()
    page.wait_for_selector("[data-help-pop]")
    page.mouse.click(5, view["height"] - 5)  # beside it
    page.wait_for_selector("[data-help-pop]", state="detached")
    button.click()
    page.wait_for_selector("[data-help-pop]")
    button.click()  # the same "?" again
    page.wait_for_selector("[data-help-pop]", state="detached")
    button.click()
    page.wait_for_selector("[data-help-pop]")
    go(page, "models")  # another view closes it
    assert page.locator("[data-help-pop]").count() == 0


# --- performance: the studio never hangs (gpu-studio standard, section 9a) -------------------------------

def slow_state(server, monkeypatch, seconds):
    """The state answers after `seconds`; returns the counters of state calls (now running, most at once, all)."""
    calls = {"now": 0, "most": 0, "all": 0}
    original = server.studio.call
    lock = threading.Lock()

    def call(message, user="", trusted=False):
        if message.get("type") != "state":
            return original(message, user, trusted)
        with lock:
            calls["now"] += 1
            calls["all"] += 1
            calls["most"] = max(calls["most"], calls["now"])
        try:
            time.sleep(seconds)
            return original(message, user, trusted)
        finally:
            with lock:
                calls["now"] -= 1

    monkeypatch.setattr(server.studio, "call", call)
    return calls


def test_a_slow_server_never_gets_a_queue_of_state_requests(page, studio, monkeypatch):
    calls = slow_state(studio[0], monkeypatch, 3)  # slower than the 2 s between polls
    time.sleep(10)
    assert calls["all"] >= 2 and calls["most"] == 1


def test_a_tab_in_the_background_does_not_poll(page, studio, monkeypatch):
    calls = slow_state(studio[0], monkeypatch, 0)
    page.evaluate("""() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    }""")
    time.sleep(2.5)  # a poll already on its way may still end
    before = calls["all"]
    time.sleep(5)
    assert calls["all"] == before
    page.evaluate("""() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      document.dispatchEvent(new Event("visibilitychange"));
    }""")
    deadline = time.time() + 3
    while calls["all"] == before and time.time() < deadline:
        time.sleep(0.05)
    assert calls["all"] > before  # back: asked at once


def test_a_request_without_an_answer_ends_with_a_message(page, studio, monkeypatch):
    slow_state(studio[0], monkeypatch, 4)
    message = page.evaluate("""async () => {
      const common = await import("/static/views/common.js");
      try { await common.call("state", {}, { timeout: 1000 }); return "answered"; }
      catch (err) { return err.message; }
    }""")
    assert "1 s" in message and "answered" not in message


def test_large_data_draws_without_long_tasks(page, studio):
    server = studio[0]
    real = server.studio.household / "data" / "real"
    take = next(real.rglob("*.wav"))
    for i in range(1500):  # a big household: 1500 more takes of one person
        (take.parent / f"bulk_{i:04d}_normal.wav").write_bytes(take.read_bytes())
    page.evaluate("""() => {
      window.__longTasks = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__longTasks.push(entry.duration);
      }).observe({ type: "longtask", buffered: false });
    }""")
    for node in ALL_VIEWS:
        page.evaluate(f"location.hash = '#/{node}'")
        page.wait_for_selector(f"[data-view='{node}'] > *")
    go(page, "recordings")
    page.wait_for_selector("[data-view='recordings'] .rec-group")
    group = page.locator("[data-view='recordings'] details.rec-group").filter(has_text=f"{take.parent.name}").filter(
        has_text="15").first
    group.locator("summary strong").click()  # opening a group of 1500 draws the first 200
    page.wait_for_selector("[data-view='recordings'] [data-more-rows]")
    assert page.locator("[data-view='recordings'] details[open] .rec-row").count() <= 200
    page.locator("[data-view='recordings'] details[open] [data-pick]").first.check()
    assert "(1)" in page.locator("[data-delete-picked]").inner_text()  # the count follows without a redraw
    page.wait_for_timeout(500)
    longest = max(page.evaluate("window.__longTasks") or [0])
    assert longest < 500, f"the page was blocked for {longest:.0f} ms"


def test_power_off_countdown_shows_in_the_top_bar_and_cancels(page, studio):
    server = studio[0]
    server.studio.power_off = {"after_training": False, "at": time.time() + 95}
    pill = page.wait_for_selector("[data-power-countdown-top]", timeout=15000)
    assert "Off in 1:3" in pill.inner_text()  # minutes:seconds, counting down
    page.click("[data-power-cancel-top]")
    page.wait_for_selector("[data-power-countdown-top]", state="detached", timeout=15000)
    assert server.studio.power_off["at"] is None


def test_power_off_box_next_to_start(page, studio):
    server = studio[0]
    # a connection that leads nowhere (a closed port on this computer) - never a real Home Assistant
    ha_sync._write_config({"url": "http://127.0.0.1:9", "token": "x" * 40,
                           "power": {"switch": "switch.gpu_machine"}})
    page.reload()
    page.wait_for_selector(".view-host > *")
    go(page, "train-run")
    page.wait_for_selector("#power-after-start")
    page.check("#power-after-start")
    deadline = time.time() + 10
    while not server.studio.power_off["after_training"] and time.time() < deadline:
        time.sleep(0.1)
    assert server.studio.power_off["after_training"]


def test_one_draft_save_at_a_time_on_a_slow_server(page, studio, monkeypatch):
    """A save slower than the typing pause never runs twice at once; the last one carries the last change."""
    server = studio[0]
    saves = {"now": 0, "most": 0, "all": 0, "last": None}
    original = server.studio.call
    lock = threading.Lock()

    def call(message, user="", trusted=False):
        if message.get("type") != "draft/save":
            return original(message, user, trusted)
        with lock:
            saves["now"] += 1
            saves["all"] += 1
            saves["most"] = max(saves["most"], saves["now"])
        try:
            time.sleep(1.5)
            saves["last"] = [s["id"] for s in message["data"]["speakers"]]
            return original(message, user, trusted)
        finally:
            with lock:
                saves["now"] -= 1

    monkeypatch.setattr(server.studio, "call", call)
    go(page, "people")
    names = ["kasia", "marek", "ewa", "basia"]
    for name in names:  # a change every 0.9 s, the draft waits 0.8 s, the save takes 1.5 s
        page.fill("[data-new-person]", name)
        page.click("[data-add-person]")
        page.wait_for_selector(f"[data-person='{name}']")
        page.wait_for_timeout(900)
    deadline = time.time() + 10
    while (saves["now"] or saves["last"] is None or names[-1] not in saves["last"]) and time.time() < deadline:
        time.sleep(0.1)
    assert saves["most"] == 1 and saves["all"] < len(names)
    assert set(names) <= set(saves["last"])  # the last save has every change


def test_side_columns_fold_and_unfold(page):
    def middle():
        return page.locator("[data-middle]").bounding_box()["width"]

    wide = middle()
    page.click("[data-tree] [data-fold-column='left']")  # the button on the column
    page.wait_for_selector("[data-column-strip='left'] [data-fold-column='left']")  # a strip stays, with its button
    assert page.locator("[data-tree]").count() == 0 and middle() > wide + 150
    page.keyboard.press("Control+Alt+KeyB")  # the shortcut of the right column
    page.wait_for_selector("[data-column-strip='right']")
    assert page.locator("[data-side]").count() == 0
    widest = middle()
    page.reload()  # remembered
    page.wait_for_selector(".view-host > *")
    assert page.locator("[data-column-strip='left']").count() == 1 and page.locator("[data-column-strip='right']").count() == 1
    assert abs(middle() - widest) < 2
    page.keyboard.press("Control+KeyB")
    page.wait_for_selector("[data-tree]")
    page.click("[data-column-strip='right'] [data-fold-column='right']")
    page.wait_for_selector("[data-side]")
    assert abs(middle() - wide) < 2  # the widths from before folding are back
    assert "Ctrl/⌘+B" in page.get_attribute("[data-tree] [data-fold-column='left']", "title")


def test_a_trusted_network_shows_no_logout(page, studio):
    from wakeword.studio.auth import parse_networks

    server, _base = studio
    server.auth.trusted_networks = parse_networks("127.0.0.0/8")
    page.reload()
    page.wait_for_selector(".view-host > *")
    page.click("[data-menu]")
    assert "STUDIO_TRUSTED_NETWORKS" in page.inner_text("[data-who]")
    assert page.locator("[data-menu-pop] [data-logout]").count() == 0
    go(page, "account")
    assert page.locator("[data-view='account'] [data-trusted]").count() == 1


def test_false_wakes_per_word_device_and_day(page):
    go(page, "false-wakes")
    page.wait_for_selector("[data-fw-summary] .tile")
    assert page.locator("[data-fw-summary] .tile").count() == 5
    jarvis = page.locator("[data-fw-word='Hej Jarvis']")
    assert jarvis.locator(".fw-better").count() == 1  # fewer false wakes after the new model (the demo's log)
    assert page.locator("[data-fw-devices] tr").nth(1).inner_text().startswith("Pokój dzieci")
    assert page.locator("[data-fw-days] .fw-day").count() >= 30
    assert page.locator("[data-fw-recent] tr").count() > 1
    # another day for the model: asked again with it
    page.fill("[data-fw-deployed='hej_jarvis']", "2026-11-01")
    page.dispatch_event("[data-fw-deployed='hej_jarvis']", "change")
    page.wait_for_function("document.querySelector(\"[data-fw-deployed='hej_jarvis']\")?.value === '2026-11-01'")
    page.select_option("[data-fw-since]", "7")
    page.wait_for_selector("[data-fw-summary] .tile")
    assert page.locator("[data-fw-days] .fw-day").count() <= 8


def test_the_job_output_fills_the_right_column(page, studio):
    studio[0].studio.call({"type": "action", "action": "check"})  # a job, so its output shows on the side
    go(page, "train-data")
    page.wait_for_selector("[data-side-job]")
    page.wait_for_timeout(500)
    side, job = (page.locator(sel).bounding_box() for sel in ("[data-side]", "[data-side-job-card]"))
    assert job["y"] + job["height"] >= side["y"] + side["height"] - 30  # down to the foot of the column
    assert page.locator("[data-side-job]").bounding_box()["height"] > 300


def focused(page):
    """Which part of the studio's question window has the focus: ok, cancel, input or None."""
    return page.evaluate("""() => {
        const a = document.activeElement;
        if (!a?.closest('dialog.ask')) return null;
        return a.hasAttribute('data-ask-ok') ? 'ok' : a.hasAttribute('data-ask-cancel') ? 'cancel'
            : a.hasAttribute('data-ask-input') ? 'input' : 'other';
    }""")


def test_rename_a_word_in_the_studio_window(page, studio):
    native = []
    page.on("dialog", lambda dialog: (native.append(dialog.type), dialog.dismiss()))
    go(page, "word/hej_jarvis")
    page.click("[data-rename='hej_jarvis']")
    box = page.locator("dialog.ask[role='alertdialog'][aria-modal='true']")
    box.wait_for()
    field = box.locator("[data-ask-input]")
    assert field.input_value() == "hej_jarvis"
    assert focused(page) == "input"
    assert page.evaluate("(() => { const f = document.activeElement; return [f.selectionStart, f.selectionEnd]; })()") == [0, 10]
    assert box.locator("[data-ask-ok]").inner_text() == "Rename"
    assert "hej_jarvis" in box.locator("h2").inner_text()
    # Esc cancels: nothing renamed, the focus back on the link that opened it
    page.keyboard.press("Escape")
    box.wait_for(state="detached")
    assert page.evaluate("document.activeElement.getAttribute('data-rename')") == "hej_jarvis"
    assert "hej_jarvis" in household_file(studio)["words"]
    # Cancel gives nothing either
    page.click("[data-rename='hej_jarvis']")
    box.locator("[data-ask-cancel]").click()
    box.wait_for(state="detached")
    assert "hej_jarvis" in household_file(studio)["words"]
    # a new id, Enter in the field confirms
    page.click("[data-rename='hej_jarvis']")
    field.fill("hej_dzarwis")
    field.press("Enter")
    page.wait_for_selector(".toast.ok:has-text('hej_dzarwis')")
    words = household_file(studio)["words"]
    assert "hej_dzarwis" in words and "hej_jarvis" not in words
    assert native == []


def test_a_dangerous_question_starts_on_cancel_and_keeps_the_focus_inside(page):
    native = []
    page.on("dialog", lambda dialog: (native.append(dialog.type), dialog.dismiss()))
    go(page, "people")
    remove = "[data-remove-person='anna']"
    box = page.locator("dialog.ask")
    page.click(remove)
    box.wait_for()
    assert box.locator("[data-ask-ok]").inner_text() == "Remove"
    assert "danger" in box.locator("[data-ask-ok]").get_attribute("class")
    assert focused(page) == "cancel"
    # Enter alone never removes: it presses Cancel
    page.keyboard.press("Enter")
    box.wait_for(state="detached")
    assert page.locator("[data-person='anna']").count() == 1
    assert page.evaluate("document.activeElement.getAttribute('data-remove-person')") == "anna"
    # Tab goes round inside the window
    page.click(remove)
    box.wait_for()
    page.keyboard.press("Tab")
    assert focused(page) == "ok"
    page.keyboard.press("Tab")
    assert focused(page) == "cancel"
    page.keyboard.press("Shift+Tab")
    assert focused(page) == "ok"
    # a click beside the window cancels
    page.mouse.click(5, 5)
    box.wait_for(state="detached")
    assert page.locator("[data-person='anna']").count() == 1
    # the action button does it
    page.click(remove)
    box.locator("[data-ask-ok]").click()
    page.wait_for_selector("[data-person='anna']", state="detached")
    assert native == []

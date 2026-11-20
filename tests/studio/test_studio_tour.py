"""The tour of the studio and its lessons in a real browser (gpu-studio standard, section 5a), on the demo household."""

import pytest

from tests.studio.test_studio_browser import household_file, page, playwright, studio  # noqa: F401 - fixtures

TOUR = "document.querySelector('wakeword-studio-tour')"
BUBBLE = f"{TOUR}?.shadowRoot?.querySelector('[data-tour-bubble]')"
# the steps of the lessons may wait for a node to be drawn and the frame follows every 400 ms
STEP_TIMEOUT = 5000


@pytest.fixture
def fresh_page(studio):  # noqa: F811 - the imported fixture
    """A browser that has never seen the studio: the tour starts by itself."""
    _server, base = studio
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:  # noqa: BLE001 - no Chrome on this computer
            pytest.skip(f"Chrome not available: {err}")
        context = browser.new_context(viewport={"width": 1500, "height": 950}, color_scheme="dark")
        context.add_init_script("localStorage.setItem('wakeword-studio-lang', 'en');")
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


def step(tab) -> str | None:
    return tab.evaluate(f"{BUBBLE}?.dataset.tourBubble ?? null")


def press(tab, name: str) -> None:
    tab.evaluate(f"{TOUR}.shadowRoot.querySelector('[data-tour-{name}]').click()")


def wait_step(tab, key: str) -> None:
    tab.wait_for_function(f"{BUBBLE}?.dataset.tourBubble === {key!r}", timeout=STEP_TIMEOUT)


def lessons(tab) -> list[dict]:
    """Every lesson with its steps: key, whether it has targets, waits for a click or starts work on the machine."""
    return tab.evaluate("""async () => {
      const { LESSONS } = await import('/static/lessons.js');
      return LESSONS.map((lesson) => ({ key: lesson.key, group: lesson.group, nodes: lesson.nodes, needs: lesson.needs ?? null,
        steps: lesson.steps.map((s) => ({ key: s.key, framed: typeof s.targets === 'function' || s.targets.length > 0,
          click: s.advance === 'click', heavy: s.note === 'heavy',
          targets: typeof s.targets === 'function' ? 'function' : s.targets.join(' '), shared: s.shared ?? null })) }));
    }""")


def test_the_tour_starts_by_itself_once_and_goes_through_every_part(fresh_page, studio):  # noqa: F811
    fresh_page.wait_for_function(f"{BUBBLE}?.dataset.tourBubble === 'welcome'")
    seen = []
    while (key := step(fresh_page)) is not None:
        seen.append(key)
        if key != "welcome":
            assert fresh_page.evaluate(f"Boolean({TOUR}.shadowRoot.querySelector('[data-tour-frame]'))"), key
        press(fresh_page, "next")
        fresh_page.wait_for_function(f"({BUBBLE}?.dataset.tourBubble ?? null) !== {key!r}")
    assert seen[:3] == ["welcome", "tree", "middle"]
    assert {"draft", "save", "help", "menu"} <= set(seen)
    assert fresh_page.evaluate("localStorage.getItem('wakeword-studio-tour')") == "done"
    fresh_page.reload()
    fresh_page.wait_for_selector(".view-host > *")
    fresh_page.wait_for_timeout(500)
    assert fresh_page.locator("wakeword-studio-tour").count() == 0  # once in a browser


def test_escape_ends_the_tour_and_the_gear_opens_it_again(fresh_page):
    wait_step(fresh_page, "welcome")
    fresh_page.keyboard.press("ArrowRight")
    wait_step(fresh_page, "tree")
    fresh_page.keyboard.press("Escape")
    fresh_page.wait_for_selector("wakeword-studio-tour", state="detached")
    fresh_page.click("[data-settings]")
    fresh_page.click("[data-tour-start]")
    wait_step(fresh_page, "welcome")


def test_a_folded_column_leaves_its_step_out(fresh_page):
    wait_step(fresh_page, "welcome")
    fresh_page.keyboard.press("Escape")
    fresh_page.click("[data-fold-column='right']")
    fresh_page.click("[data-settings]")
    fresh_page.click("[data-tour-start]")
    wait_step(fresh_page, "welcome")
    seen = []
    while (key := step(fresh_page)) is not None:
        seen.append(key)
        press(fresh_page, "next")
        fresh_page.wait_for_function(f"({BUBBLE}?.dataset.tourBubble ?? null) !== {key!r}")
    assert "side" not in seen


def test_every_lesson_frames_every_step_on_the_demo(page):  # noqa: F811
    missing = []
    for lesson in lessons(page):
        page.evaluate(f"document.querySelector('wakeword-studio')._startLesson({lesson['key']!r})")
        for item in lesson["steps"]:
            try:
                wait_step(page, item["key"])
            except playwright.TimeoutError:
                missing.append(f"{lesson['key']}/{item['key']}: no bubble")
                break
            if item["framed"]:
                try:
                    page.wait_for_function(f"Boolean({TOUR}.shadowRoot.querySelector('[data-tour-frame]'))",
                                           timeout=STEP_TIMEOUT)
                except playwright.TimeoutError:
                    missing.append(f"{lesson['key']}/{item['key']}: nothing framed ({item['targets']})")
            texts = page.evaluate(f"[{BUBBLE}.querySelector('h3').textContent, {BUBBLE}.querySelector('p').textContent]")
            assert all(text and "lesson_" not in text for text in texts), (lesson["key"], item["key"], texts)
            press(page, "next")
        page.wait_for_selector("wakeword-studio-tour", state="detached")
    assert missing == []
    done = page.evaluate("JSON.parse(localStorage.getItem('wakeword-studio-lessons'))")
    assert sorted(done) == sorted(lesson["key"] for lesson in lessons(page))


def test_lessons_wait_only_for_what_the_draft_can_undo(page):  # noqa: F811
    allowed = {"[data-add-person]", "[data-add-word]", "[data-settings]"}
    for lesson in lessons(page):
        for item in lesson["steps"]:
            if item["click"]:
                assert item["targets"] in allowed, (lesson["key"], item["key"])
            if item["heavy"]:
                assert not item["click"], (lesson["key"], item["key"])


def test_a_lesson_waits_for_the_framed_button_and_a_click_beside_it_does_nothing(page, studio):  # noqa: F811
    page.evaluate("document.querySelector('wakeword-studio')._startLesson('add_person')")
    wait_step(page, "name")
    page.fill("[data-new-person]", "tomek")
    page.keyboard.press("Enter")  # typing in the field: Enter stays the field's
    page.wait_for_timeout(300)
    assert step(page) == "name"
    press(page, "next")
    wait_step(page, "add")
    assert page.evaluate(f"Boolean({BUBBLE}.querySelector('[data-tour-try]'))")
    page.mouse.click(5, 900)  # beside the frame: blocked
    page.wait_for_timeout(600)
    assert step(page) == "add"
    page.click("[data-add-person]")
    wait_step(page, "tree")
    page.wait_for_selector("[data-node='person/tomek']")
    assert "tomek" not in [s["id"] for s in household_file(studio)["speakers"]]  # only in the draft


def test_escape_in_the_middle_does_not_count_the_lesson_as_done(page):  # noqa: F811
    page.evaluate("document.querySelector('wakeword-studio')._startLesson('targets')")
    wait_step(page, "fields")
    page.keyboard.press("Escape")
    page.wait_for_selector("wakeword-studio-tour", state="detached")
    assert page.evaluate("localStorage.getItem('wakeword-studio-lessons')") in (None, "[]")


def test_the_gear_lists_the_lessons_in_groups_and_starts_one(page):  # noqa: F811
    page.click("[data-settings]")
    page.click("[data-lessons-open]")
    page.wait_for_selector("[data-dialog='lessons'] [data-lesson]")
    assert page.locator("[data-dialog='lessons'] [data-lesson]").count() == len(lessons(page))
    assert page.locator("[data-dialog='lessons'] .lessons-group").count() == 3
    page.click("[data-lesson='look']")
    page.wait_for_selector("[data-dialog='lessons']", state="detached")
    wait_step(page, "gear")
    page.click("[data-settings]")  # the framed ⚙: the lesson goes on into the pop-up
    wait_step(page, "theme")
    press(page, "next")
    wait_step(page, "language")
    assert page.locator("[data-gear-pop]").count() == 1  # Next of the lesson does not close what it shows
    page.keyboard.press("Escape")
    page.wait_for_selector("wakeword-studio-tour", state="detached")
    page.wait_for_selector("[data-gear-pop]", state="detached")  # what the lesson opened closes with it


def test_the_question_mark_of_a_view_offers_its_lesson(page):  # noqa: F811
    page.click("[data-node='people']")
    page.wait_for_selector("[data-view='people'] [data-help]")
    page.click("[data-view='people'] [data-help]")
    page.click("[data-help-lesson='add_person']")
    wait_step(page, "name")


def test_every_node_of_the_tree_has_a_lesson(page):  # noqa: F811
    missing = page.evaluate("""async () => {
      const { VIEWS } = await import('/static/outline.js');
      const { lessonForNode } = await import('/static/lessons.js');
      return [...VIEWS, 'person/x', 'word/x', 'rec/x', 'look']
        .filter((key) => !lessonForNode(key));
    }""")
    assert missing == []


def test_the_bubble_never_covers_what_it_explains(page):  # noqa: F811
    places = page.evaluate("""async () => {
      const { bubbleAt } = await import('/static/tour.js');
      const low = { left: 340, top: 820, width: 360, height: 60 };  // a button at the foot of the window, left of the middle
      return { low: bubbleAt(low, 'left', { height: 200 }, 1500, 920), none: bubbleAt(null, 'left', { height: 200 }, 1500, 920) };
    }""")
    low = places["low"]
    assert low["left"] >= 340 + 360 or low["top"] + 200 <= 820  # beside or above the button, not over it
    assert places["none"]["left"] == (1500 - 360) / 2

"""Questions are windows of the studio (views/common.js ask), never window.confirm / alert / prompt."""

import re
from pathlib import Path

WWW = Path(__file__).resolve().parents[2] / "wakeword" / "studio" / "www"
NATIVE = re.compile(r"(?<![\w.$])(?:window\.)?(confirm|alert|prompt)\s*\(")


def test_no_native_browser_dialogs():
    found = []
    for path in sorted(WWW.rglob("*.js")):
        if "vendor" in path.relative_to(WWW).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//", 1)[0]
            if NATIVE.search(code):
                found.append(f"{path.relative_to(WWW)}:{number}: {line.strip()}")
    assert found == [], "use ask() from views/common.js:\n" + "\n".join(found)


def test_the_pattern_finds_native_dialogs_and_leaves_texts_alone():
    for code in (
        'prompt("x")',
        "window.confirm(text)",
        " alert (1)",
        "if (confirm(q)) go();",
    ):
        assert NATIVE.search(code), code
    for code in (
        't("rename_prompt", {})',
        't("confirm_stop")',
        "common.ask(q)",
        "this.confirm(x)",
    ):
        assert not NATIVE.search(code), code

"""The studio's page agrees with itself: every text in both languages, every icon drawn offline."""

import json
from pathlib import Path
import re

from wakeword.languages import get_pack
from wakeword.studio import make_icons

WWW = Path(make_icons.WWW)
TEXT_CALL = re.compile(r"""\b(?:t|_t)\(\s*["']([a-z0-9_]+)["']""")


def studio_strings() -> dict:
    """STRINGS of i18n.js, read as JSON-like text (keys and values on one line each)."""
    text = (WWW / "i18n.js").read_text(encoding="utf-8")
    result = {}
    for language in ("en", "pl"):
        block = re.search(rf"\n  {language}: {{\n(.*?)\n  }},", text, re.S).group(1)
        result[language] = set(re.findall(r"^\s+([a-z0-9_]+):", block, re.M))
    return result


def used_keys() -> set[str]:
    keys = set()
    for file in WWW.rglob("*.js"):
        if "vendor" not in file.parts:
            keys.update(TEXT_CALL.findall(file.read_text(encoding="utf-8")))
    return keys


def test_every_text_exists_in_polish_and_english():
    studio = studio_strings()
    assert studio["en"] == studio["pl"]
    for language in ("en", "pl"):
        pack = get_pack(language)
        known = studio[language] | set(pack.TRAINER)
        # "advice_" + kind: a prefix of keys made at run time
        missing = sorted(key for key in used_keys() if key not in known and not key.endswith("_"))
        assert missing == [], f"{language}: {missing}"


def test_every_icon_is_drawn_without_a_cdn():
    table = (WWW / "vendor" / "mdi.js").read_text(encoding="utf-8")
    icons = json.loads(table.split("export const ICONS = ", 1)[1].rstrip().rstrip(";"))
    missing = sorted(make_icons.used_icons() - set(icons))
    assert missing == [], f"run make icons: {missing}"


def test_icon_names():
    assert make_icons.js_name("mdi:chevron-down") == "mdiChevronDown"
    assert make_icons.js_name("mdi:home-assistant") == "mdiHomeAssistant"


def test_no_text_points_to_the_old_panel():
    """1.0.0 removed the old panel (make ui, its numbered cards, SSH, "Fetch models" / "Send to machine"): no text
    of the studio or of the language packs mentions it any more."""
    import re

    from wakeword.languages import en, pl

    old = re.compile(r"Fetch models|Pobierz modele|Fetch samples|Pobierz próbki|Send to machine|Wyślij na maszynę"
                     r"|send again|wyślij jeszcze|\bcard \d|\bkart[aeyi]? \d|\bkarcie \d|make ui|ui-remote|train-ui"
                     r"|ssh-copy-id|\?token=")
    texts = {f"{pack.__name__}.{group}.{key}": str(value) for pack in (en, pl)
             for group in ("TRAINER", "TRAINER_HELP") for key, value in getattr(pack, group).items()}
    texts["i18n.js"] = (WWW / "i18n.js").read_text(encoding="utf-8")
    found = [f"{where}: {match.group(0)}" for where, text in texts.items() for match in [old.search(text)] if match]
    assert not found, "\n".join(found)

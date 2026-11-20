"""The studio's page agrees with itself: every text in both languages, every icon drawn offline."""

import json
from pathlib import Path
import re

from wakeword.languages import get_pack
from wakeword.studio import make_icons

WWW = Path(make_icons.WWW)
TEXT_CALL = re.compile(r"""\b(?:t|_t)\(\s*["']([a-z0-9_]+)["']""")


def strings_of(file: str) -> dict:
    """The texts of a file (`en: {` … `pl: {`), read as JSON-like text (keys and values on one line each)."""
    text = (WWW / file).read_text(encoding="utf-8")
    result = {}
    for language in ("en", "pl"):
        block = re.search(rf"\n  {language}: {{\n(.*?)\n  }},", text, re.S).group(1)
        result[language] = set(re.findall(r"^\s+([a-z0-9_]+):", block, re.M))
    return result


def studio_strings() -> dict:
    """STRINGS of i18n.js and the texts of the tour and the lessons (tour-texts.js), which i18n.js joins in."""
    own, tour = strings_of("i18n.js"), strings_of("tour-texts.js")
    return {language: own[language] | tour[language] for language in ("en", "pl")}


def test_tour_texts_exist_in_polish_and_english_and_do_not_shadow_the_editor():
    own, tour = strings_of("i18n.js"), strings_of("tour-texts.js")
    assert tour["en"] == tour["pl"]
    assert not tour["en"] & own["en"]  # Object.assign would replace an editor's text


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
    texts["tour-texts.js"] = (WWW / "tour-texts.js").read_text(encoding="utf-8")
    # what the training machine prints shows in the studio's log too
    root = WWW.parents[2]
    for path in [*(root / "train").glob("*.sh"), *(root / "train").glob("*.py"), *(root / "wakeword" / "trainer").glob("*.py")]:
        texts[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    found = [f"{where}: {match.group(0)}" for where, text in texts.items() for match in [old.search(text)] if match]
    assert not found, "\n".join(found)


def test_lessons_name_the_buttons_as_the_studio_shows_them():
    """A lesson that frames a button calls it by its label (the user looked for "Fetch recordings" that is "Sync with HA")."""
    from wakeword.languages import get_pack

    text = (WWW / "tour-texts.js").read_text(encoding="utf-8")
    for language in ("en", "pl"):
        block = re.search(rf"\n  {language}: {{\n(.*?)\n  }},", text, re.S).group(1)
        title = re.search(r'lesson_record_pull_title: "([^"]+)"', block).group(1)
        assert title == get_pack(language).TRAINER["ha_pull"], language

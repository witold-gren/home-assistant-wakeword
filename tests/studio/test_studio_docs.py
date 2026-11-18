"""The studio's chapters of the guide agree with the code: pictures, links, the weights of the sets."""

from pathlib import Path
import re

from wakeword.training_config import DEFAULT_WEIGHTS, WEIGHT_PRESETS

ROOT = Path(__file__).parents[2]


def chapter(lang: str, name: str) -> str:
    return (ROOT / "docs" / lang / name).read_text(encoding="utf-8")


def test_pictures_exist_and_the_demo_makes_them():
    demo = (ROOT / "docs" / "studio_demo.py").read_text(encoding="utf-8")
    made = set(re.findall(r'"(studio-[a-z-]+)": ', demo))
    shown = {}
    for lang in ("pl", "en"):  # the studio chapter and the step-by-step guide
        text = chapter(lang, "11-studio.md") + chapter(lang, "13-studio-step-by-step.md")
        shown[lang] = set(re.findall(rf"\.\./assets/screens/{lang}/(studio-[a-z-]+)\.png", text))
        for name in shown[lang]:
            assert (ROOT / "docs" / "assets" / "screens" / lang / f"{name}.png").is_file(), f"{lang}/{name}: make studio shots"
    # every picture the demo makes is shown, the same in both languages
    assert shown["pl"] == shown["en"] == made


def test_the_step_by_step_guide_covers_every_node_of_the_tree():
    """13-studio-step-by-step.md: every node of the studio's tree is in the map, in both languages."""
    import json

    outline = (ROOT / "wakeword" / "studio" / "www" / "outline.js").read_text(encoding="utf-8")
    keys = re.findall(r't\("(n_\w+)"\)', outline)
    strings = (ROOT / "wakeword" / "studio" / "www" / "i18n.js").read_text(encoding="utf-8")
    english, polish = strings[: strings.index("pl: {")], strings[strings.index("pl: {"):]
    for lang, part in (("en", english), ("pl", polish)):
        guide = chapter(lang, "13-studio-step-by-step.md")
        for key in keys:
            label = json.loads(re.search(rf"^\s+{key}: (\".*?\"),$", part, re.M).group(1))
            assert label in guide, f"{lang}: {label} ({key}) missing in the guide"


def test_readme_links_the_chapters():
    for readme, lang in (("README.md", "en"), ("README.pl.md", "pl")):
        text = (ROOT / readme).read_text(encoding="utf-8")
        assert f"docs/{lang}/11-studio.md" in text and f"docs/{lang}/12-training-well.md" in text


def number(value: float, lang: str) -> str:
    text = f"{value:g}"
    return text.replace(".", ",") if lang == "pl" else text


def test_the_weights_table_is_the_code():
    for lang in ("pl", "en"):
        rows = {}
        for line in chapter(lang, "12-training-well.md").splitlines():
            found = re.match(r"\| [+−] [^|]*?`(\w+)`", line)
            if found:
                rows[found.group(1)] = line
            elif line.startswith("| + ElevenLabs |"):  # the only set named without its key
                rows["elevenlabs"] = line
        for name, default in DEFAULT_WEIGHTS.items():
            row = rows[name]
            cells = [cell.strip().strip("*") for cell in row.strip("|").split("|")]
            expected = [number(default, lang), number(WEIGHT_PRESETS["family"]["weights"][name], lang),
                        number(WEIGHT_PRESETS["neutral"]["weights"][name], lang)]
            assert cells[1:4] == expected, f"{lang} {name}: {cells[1:4]} != {expected}"


# --- the documentation site (gpu-studio standard, section 8) ---------------------------------------------

DOCS = ROOT / "docs"
HEADING = re.compile(r"^#{1,6} .*\{#([\w-]+)\}\s*$", re.M)


def pages(lang: str) -> set[str]:
    return {p.name for p in (DOCS / lang).glob("*.md") if p.name != "changelog.md"}  # changelog: made by the hook


def anchors(lang: str, page: str) -> list[str]:
    text = re.sub(r"^```.*?^```", "", (DOCS / lang / page).read_text(encoding="utf-8"), flags=re.M | re.S)
    return HEADING.findall(text)


def test_both_languages_have_the_same_pages_and_anchors():
    assert pages("pl") == pages("en") and {"index.md", "faq.md", "11-studio.md", "12-training-well.md"} <= pages("en")
    for page in pages("en"):
        assert anchors("pl", page) == anchors("en", page), page
        assert len(set(anchors("en", page))) == len(anchors("en", page)), f"{page}: an anchor twice"


def test_every_page_is_in_the_navigation():
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    nav = set(re.findall(r"([\w-]+\.md)\s*$", config[config.index("\nnav:"):config.index("\nmarkdown_extensions:")], re.M))
    assert pages("en") | {"changelog.md"} == nav


def test_every_help_link_of_the_studio_leads_to_an_anchor():
    common = (ROOT / "wakeword" / "studio" / "www" / "views" / "common.js").read_text(encoding="utf-8")
    links = dict(re.findall(r'^\s+(\w+): "([\w-]+\.html#[\w-]+)",$', common[common.index("DOCS_LINKS"):], re.M))
    assert len(links) >= 9
    for key, target in links.items():
        page, anchor = target.split("#")
        for lang in ("pl", "en"):
            assert anchor in anchors(lang, page.replace(".html", ".md")), f"{key}: {lang}/{target}"


def test_raw_html_pictures_point_from_the_page_place():
    # raw HTML is not rewritten by MkDocs: English pages are at the site's root, Polish ones in pl/
    for lang, prefix in (("en", "assets/"), ("pl", "../assets/")):
        for page in pages(lang):
            for src in re.findall(r'<img src="([^"]+)"', (DOCS / lang / page).read_text(encoding="utf-8")):
                assert src.startswith(prefix), f"{lang}/{page}: {src}"
                assert (DOCS / src.removeprefix("../")).is_file(), src


def test_the_site_builds_strictly(tmp_path):
    mkdocs = ROOT / ".venv" / "bin" / "mkdocs"
    if not mkdocs.exists():
        import pytest

        pytest.skip("mkdocs not installed (pip install -e '.[docs]')")
    import os
    import subprocess

    result = subprocess.run([str(mkdocs), "build", "--strict", "--site-dir", str(tmp_path / "site")], cwd=ROOT,
                            capture_output=True, text=True, env={**os.environ, "NO_MKDOCS_2_WARNING": "1"})
    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "site" / "pl" / "11-studio.html").is_file() and (tmp_path / "site" / "12-training-well.html").is_file()

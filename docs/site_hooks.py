"""MkDocs hook of the documentation site (mkdocs.yml).

The changelog lives at the top of the repository, where GitHub shows it; the site needs it in both language
folders. Before each build it is copied there (only when it changed, so `mkdocs serve` does not rebuild in a
loop). The copies are not kept in git (.gitignore).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLES = {"en": "# Changes {#changes}\n\n", "pl": "# Lista zmian {#changes}\n\n(Lista zmian jest prowadzona po angielsku.)\n\n"}


def changelog_page(lang: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]  # the page's own title instead
    return TITLES[lang] + "\n".join(lines).lstrip("\n")


def on_pre_build(config, **kwargs) -> None:
    for lang in TITLES:
        path = ROOT / "docs" / lang / "changelog.md"
        text = changelog_page(lang)
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")

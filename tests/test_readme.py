"""The README shows the current app: the studio, not the old panel (gone in 1.0.0)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name, lang", [("README.md", "en"), ("README.pl.md", "pl")])
def test_the_first_picture_is_the_studio(name, lang):
    text = (ROOT / name).read_text(encoding="utf-8")
    pictures = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    assert pictures and pictures[0] == f"docs/assets/screens/{lang}/studio-overview.png"
    assert f"screens/{lang}/overview.png" not in text  # the old panel's screenshot
    intro = text.split("\n## ", 1)[0]
    assert "make ui" not in intro and "SSH" not in intro

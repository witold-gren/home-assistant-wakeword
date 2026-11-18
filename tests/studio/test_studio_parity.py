"""docs/design/parity.md: every feature of the training panel has its place in the studio's code."""

from pathlib import Path
import re

ROOT = Path(__file__).parents[2]
PARITY = ROOT / "docs" / "design" / "parity.md"
WWW = ROOT / "wakeword" / "studio" / "www"


def rows():
    for line in PARITY.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] not in ("Feature", "---") and not set(cells[0]) <= {"-"}:
            yield cells


def studio_code() -> str:
    return "\n".join(file.read_text(encoding="utf-8") for file in WWW.rglob("*")
                     if file.suffix in (".js", ".html") and "vendor" not in file.parts)


def test_every_feature_has_its_code():
    code = studio_code()
    missing = []
    for feature, _old, studio, evidence in rows():
        if evidence.startswith("—"):
            assert len(evidence) > 5, f"{feature}: say why it is left out"
            continue
        for token in re.findall(r"`([^`]+)`", evidence):
            if token not in code:
                missing.append(f"{feature}: {token}")
    assert missing == []


def test_the_list_covers_the_panel():
    features = list(rows())
    assert len(features) >= 40
    left_out = [f for f in features if f[3].startswith("—")]
    assert len(left_out) == 6  # SSH, rsync, fetch, switching on, machine model, access token

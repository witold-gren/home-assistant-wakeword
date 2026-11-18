"""The repository is public: nothing of the household that uses it goes in (home network, private domains,
paths of the computers, secrets)."""

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).parents[1]
PRIVATE = re.compile(
    r"\b10\.20\.\d+\.\d+"  # the home network
    r"|docs\.witoldgren\.pl|greenetsmarthome"  # private sites
    r"|/Users/witold|/home/witold"  # paths of the author's computers (examples use made-up users)
    r"|eyJ[A-Za-z0-9_-]{30,}|\bsk_[a-f0-9]{30,}|\bhf_[A-Za-z0-9]{30,}|BEGIN [A-Z ]*PRIVATE KEY"  # tokens and keys
)


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line and (ROOT / line).is_file()]


def test_no_private_data_in_the_repository():
    found = []
    for path in tracked_files():
        if path.suffix in {".png", ".wav", ".tflite", ".ico", ".h5"} or path.name == "test_no_private_data.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if PRIVATE.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
    assert not found, "private data:\n" + "\n".join(found)

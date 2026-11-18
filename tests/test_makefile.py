"""The Makefile follows the shared commands of every app (~/Home Assistant/standards/gpu-studio.md, section 2):
every target described in English and Polish, the groups Start / GPU machine / Development first and in this
order, the Start commands need only Docker, one name for one thing."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
DESCRIBED = dict(re.findall(r"^([a-z0-9-]+):.*?## (.+)$", MAKEFILE, re.MULTILINE))

GROUPS = {
    "1. Start": {"help", "demo", "demo-clean", "docs", "docs-serve", "doctor"},
    "2. GPU machine": {"install", "deploy", "login", "logs", "status", "stop", "uninstall", "docker-up", "docker-down", "docker-logs",
                       "docker-shell"},
    "3. Development": {"setup", "demo-local", "test", "test-browser", "test-docker", "test-all", "lint", "format",
                       "docs-build", "screenshots", "icons", "clean"},
}


def groups() -> dict[str, list[str]]:
    """The targets of each `##@` group, in the order of the Makefile."""
    found: dict[str, list[str]] = {}
    current = None
    for line in MAKEFILE.splitlines():
        if line.startswith("##@ "):
            current = line[4:].split(" | ")[0]
            found[current] = []
        elif current and (match := re.match(r"^([a-z0-9-]+):.*?## ", line)):
            found[current].append(match.group(1))
    return found


def prerequisites(target: str) -> list[str]:
    line = next(line for line in MAKEFILE.splitlines() if line.startswith(f"{target}:"))
    return line.split(":", 1)[1].split("##")[0].split()


def recipe(target: str) -> str:
    return re.search(rf"^{target}:.*\n((?:\t.*\n|  .*\n)*)", MAKEFILE, re.MULTILINE).group(1)


def test_every_target_is_described_in_both_languages():
    phony = set(re.search(r"^\.PHONY: (.+?)(?<!\\)$", MAKEFILE, re.MULTILINE | re.DOTALL).group(1)
                .replace("\\\n", " ").split())
    assert phony == set(DESCRIBED)
    for target, text in DESCRIBED.items():
        english, _, polish = text.partition(" | ")
        assert english and polish, target


def test_the_standard_groups_come_first_in_order_with_their_targets():
    found = groups()
    names = list(found)
    for position, (prefix, targets) in enumerate(GROUPS.items()):
        assert names[position].startswith(prefix), names
        assert set(found[names[position]]) == targets, (prefix, set(found[names[position]]) ^ targets)


def test_start_and_machine_commands_need_no_python_environment():
    for target in GROUPS["1. Start"] | GROUPS["2. GPU machine"]:
        assert "setup" not in prerequisites(target), target
        assert "$(VENV)" not in recipe(target) and "$(PIP)" not in recipe(target), target
    for target in ("demo", "docs-serve", "docs-build"):
        assert "$(NEED_DOCKER)" in recipe(target), target


def test_the_development_environment_comes_from_uv():
    assert re.search(r"^PYTHON_VERSION \?= 3\.12$", MAKEFILE, re.MULTILINE)
    assert "uv venv -q --python $(PYTHON_VERSION) $(VENV)" in MAKEFILE
    assert "PIP := uv pip install" in MAKEFILE
    assert "$(VENV)/bin/pip" not in MAKEFILE and "brew install python" not in MAKEFILE


def test_tests_docker_and_all_mean_the_same_as_everywhere():
    assert '-m "not docker"' in recipe("test") and "-m docker" in recipe("test-docker")
    assert prerequisites("test-all") == ["lint", "test", "test-browser", "test-docker"]
    assert "ruff check " in recipe("lint") and "ruff format --check" in recipe("lint")
    assert "ruff check --fix" in recipe("format") and "ruff format wakeword" in recipe("format")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"docker: ' in pyproject  # the marker is registered


def test_docs_build_in_the_docs_stage_of_the_dockerfile():
    assert "docker build --target docs-site" in recipe("docs-build") and "dest=site" in recipe("docs-build")
    assert prerequisites("docs") == ["docs-build"]
    assert "mkdocs serve -a 0.0.0.0:8000" in recipe("docs-serve") and "$(DOCS_PORT):8000" in recipe("docs-serve")
    # the live preview at the root (the published site_url has a path that would hide every page behind it)
    assert "SITE_URL=http://127.0.0.1:$(DOCS_PORT)/" in recipe("docs-serve")
    assert "site_url: !ENV [SITE_URL," in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM scratch AS docs-site" in dockerfile and "COPY --from=docs /site /" in dockerfile


def test_one_name_for_one_thing():
    # no aliases (a target that only runs another one) and none of the old names
    for target in DESCRIBED:
        assert recipe(target).strip() or target in {"setup", "test-all"}, f"{target} is an alias"
    assert not {"studio", "studio-docker", "docs-pages", "studio-install", "studio-demo"} & set(DESCRIBED)


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
@pytest.mark.parametrize("lang, expected", [("en", "1. Start - only Docker Desktop"),
                                            ("pl", "1. Start - wystarczy Docker Desktop")])
def test_make_help(lang, expected):
    result = subprocess.run(["make", "-s", "help", f"HELP_LANG={lang}"], cwd=ROOT, capture_output=True, text=True,
                            check=True)
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert expected in plain and "train-ui" not in plain  # targets, not CLI commands
    assert plain.index("  demo ") < plain.index("  install ") < plain.index("  setup ")


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
def test_doctor_checks_without_installing(tmp_path):
    result = subprocess.run(["make", "-s", "doctor", f"HOME={tmp_path}", "GPU_HOST="], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, check=False)
    out = result.stdout
    for thing in ("Docker", "git", "ssh", "rsync", "GPU_HOST", "uv", "Google Chrome"):
        assert thing in out, thing
    assert "==> Python environment" not in out  # it did not run setup


def test_the_machine_address_comes_from_the_shared_file():
    assert "-include $(HOME)/.config/gpu-studio/host.mk" in MAKEFILE
    assert MAKEFILE.index("gpu-studio/host.mk") < MAKEFILE.index("-include Makefile.local")
    assert not re.search(r"^GPU_HOST\s*\??=", MAKEFILE, re.MULTILINE)  # no address in the repository
    assert re.search(r"^DEMO_PORT \?= 8766$", MAKEFILE, re.MULTILINE)  # the demo = the studio's port + 1
    assert re.search(r"^DOCS_PORT \?= 9766$", MAKEFILE, re.MULTILINE)  # the docs = the demo + 1000


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
@pytest.mark.parametrize("target", ["install", "deploy", "login", "logs", "status", "stop", "uninstall"])
def test_without_a_machine_address_it_says_where_to_put_it(tmp_path, target):
    local = ROOT / "Makefile.local"
    if local.exists() and re.search(r"^GPU_HOST", local.read_text(encoding="utf-8"), re.MULTILINE):
        pytest.skip("this computer's Makefile.local sets GPU_HOST")
    result = subprocess.run(["make", "-s", target, f"HOME={tmp_path}"], cwd=ROOT, capture_output=True, text=True,
                            check=False)
    assert result.returncode != 0
    assert "~/.config/gpu-studio/host.mk" in result.stdout + result.stderr

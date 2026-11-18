"""The "Try it on a Mac" section (gpu-studio standard, section 8b): only Docker Desktop is needed, `make demo` builds
the demo image and runs it. The same short section in both READMEs and on both languages of the documentation
site, with the command, the demo port from the Makefile and the login."""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = (REPO / "Makefile").read_text()

HEADINGS = {
    "README.md": "## Try it on a Mac",
    "README.pl.md": "## Wypróbuj na Macu",
    "docs/en/11-studio.md": "## Try it on a Mac {#try-on-a-mac}",
    "docs/pl/11-studio.md": "## Wypróbuj na Macu {#try-on-a-mac}",
}


def demo_port() -> str:
    match = re.search(r"^DEMO_PORT \?= (\d+)$", MAKEFILE, re.MULTILINE)
    assert match, "DEMO_PORT is missing in the Makefile"
    return match.group(1)


def target(name: str) -> str:
    """The recipe of a make target: its line and the indented lines under it."""
    match = re.search(rf"^{re.escape(name)}:.*\n((?:\t.*\n|  .*\n)*)", MAKEFILE, re.MULTILINE)
    assert match, f"no make target {name}"
    return match.group(0)


def section(path: str) -> str:
    text = (REPO / path).read_text(encoding="utf-8")
    heading = HEADINGS[path]
    assert heading in text, f"{path}: no '{heading}'"
    rest = text.split(heading, 1)[1]
    return rest.split("\n## ", 1)[0]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("path", sorted(HEADINGS))
def test_section_gives_docker_command_address_login_and_tests(path):
    body = section(path)
    assert "Docker Desktop" in body
    assert "make demo" in body and "make demo-clean" in body
    assert f"localhost:{demo_port()}" in body
    assert "`demo` / `demo`" in body
    assert "Ctrl+C" in body
    for command in ("make test", "make test-browser", "make docs", "make setup"):
        assert command in body, f"{path}: {command} missing"
    # trying the app needs no tools: no brew, uv or pip in the section
    for tool in ("brew ", "uv ", "pip install"):
        assert tool not in body, f"{path}: '{tool}' in the section"


@pytest.mark.parametrize("path", ["README.md", "README.pl.md"])
def test_readme_section_is_short_and_comes_before_the_details(path):
    text = (REPO / path).read_text(encoding="utf-8")
    start = text.index(HEADINGS[path])
    assert len(section(path).strip().splitlines()) <= 14
    # It comes before the installation details; the old panel (make ui) is gone since 1.0.0.
    assert start < text.index("make install"), f"{path}: 'make install' comes before the section"
    assert "make ui" not in text and "train-ui" not in text


def test_make_demo_builds_and_runs_the_image_with_the_demo_port():
    recipe = target("demo")
    first = recipe.splitlines()[0]
    assert "setup" not in first.split("##")[0], "make demo must not need the Python environment"
    assert "$(NEED_DOCKER)" in recipe
    assert "docker build --target demo" in recipe
    assert "docker run --rm --init" in recipe
    assert "-p 127.0.0.1:$(DEMO_PORT):$(DEMO_PORT)" in recipe
    assert "--host 0.0.0.0 --port $(DEMO_PORT)" in recipe
    assert f"localhost:{demo_port()}" in first and "demo/demo" in first


def test_demo_local_and_demo_clean_exist():
    assert "docs/studio_demo.py --port $(DEMO_PORT)" in target("demo-local")
    assert "docker image rm $(DEMO_IMAGE)" in target("demo-clean")


@pytest.mark.parametrize("command", ["demo", "docs", "docs-build", "docs-serve"])
def test_without_docker_the_start_commands_say_what_to_install(tmp_path, command):
    """No docker on PATH: a clear message, no build attempt, no Python environment."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("sh", "make", "echo", "test", "env"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    result = subprocess.run(["make", "-s", command], cwd=REPO, capture_output=True, text=True, check=False,
                            env={"PATH": str(bin_dir), "HOME": str(tmp_path)}, timeout=30)
    assert result.returncode != 0
    assert "Docker Desktop" in result.stdout + result.stderr
    assert "docker build" not in result.stdout and "uv" not in result.stdout


def test_demo_leaves_nothing_behind_after_ctrl_c(tmp_path):
    """make demo-local: after Ctrl+C the demo's temporary folder is gone."""
    port = free_port()
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    demo = subprocess.Popen(
        [sys.executable, str(REPO / "docs" / "studio_demo.py"), "--port", str(port)],
        cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        line = demo.stdout.readline()
        assert "Demo studio" in line and f"localhost:{port}" in line, line
        assert any(tmp_path.iterdir()), "the demo works in the temporary folder"
        demo.send_signal(signal.SIGINT)
        assert demo.wait(timeout=20) == 0
    finally:
        if demo.poll() is None:
            demo.kill()
    assert not any(tmp_path.iterdir()), list(tmp_path.iterdir())


def docker_works() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=False).returncode == 0


needs_docker = pytest.mark.skipif(not docker_works(), reason="Docker is not running")


@pytest.mark.docker
@needs_docker
def test_demo_image_serves_the_studio_and_leaves_no_container():
    """make demo for real: build the image, run it on a free port, log in, stop it - no container is left."""
    port = free_port()
    name = f"wakeword-studio-demo-test-{port}"
    run = ["make", "-s", "demo", f"DEMO_PORT={port}", f"DEMO_CONTAINER={name}"]
    demo = subprocess.Popen(run, cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 900  # the first build takes minutes, later ones seconds
        while True:
            try:
                with urllib.request.urlopen(f"{base}/api/health", timeout=2) as answer:
                    if answer.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            assert demo.poll() is None, demo.stdout.read()
            assert time.time() < deadline, "the demo did not answer"
            time.sleep(1)
        with urllib.request.urlopen(f"{base}/login", timeout=5) as answer:
            assert answer.status == 200
        login = urllib.request.Request(f"{base}/api/login", method="POST",
                                       data=json.dumps({"user": "demo", "password": "demo"}).encode(),
                                       headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(login, timeout=5) as answer:
            assert answer.status == 200 and "Set-Cookie" in answer.headers
    finally:
        subprocess.run(["docker", "container", "stop", "-t", "5", name], capture_output=True, timeout=60, check=False)
        demo.wait(timeout=60)
    left = subprocess.run(["docker", "ps", "-a", "-q", "--filter", f"name={name}"],
                          capture_output=True, text=True, timeout=30, check=False).stdout.strip()
    assert left == "", "the demo container stayed"


@pytest.mark.docker
@needs_docker
def test_docs_build_in_docker_writes_the_site():
    """make docs-build without Python: the docs stage of the Dockerfile, the site written to ./site."""
    result = subprocess.run(["make", "-s", "docs-build"], cwd=REPO, capture_output=True, text=True, timeout=900,
                            check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    for page in ("index.html", "pl/index.html", "11-studio.html", "pl/11-studio.html"):
        assert (REPO / "site" / page).is_file(), page
    assert "try-on-a-mac" in (REPO / "site" / "pl" / "11-studio.html").read_text(encoding="utf-8")
    # readable by the web server of docs-hub (docker --output writes the folder as 700)
    assert (REPO / "site").stat().st_mode & 0o055 == 0o055

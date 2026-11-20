"""The Docker files of the studio agree with the code (no Docker needed to run these)."""

from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).parents[2]
DOCKER = ROOT / "docker"


def test_compose_runs_the_studio_with_the_gpu_and_restarts_with_the_machine():
    service = yaml.safe_load((DOCKER / "compose.yaml").read_text(encoding="utf-8"))["services"]["studio"]
    assert service["restart"] == "unless-stopped"
    assert service["env_file"] == "./config/env"
    assert service["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]
    data = [volume for volume in service["volumes"] if not volume.endswith(":ro")]  # the time zone is read-only
    targets = {volume.rsplit(":", 1)[1] for volume in data}  # ${STUDIO_WORK:-…} has a colon
    assert targets == {"/data/household", "/data/work", "/home/wakeword/.cache/huggingface", "/home/wakeword/.config/wakeword"}


def test_image_trains_with_its_own_environment_and_starts_the_studio():
    dockerfile = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    assert "VENV=/opt/venv" in dockerfile and "touch /opt/venv/.installed" in dockerfile
    assert "WAKEWORD_HOUSEHOLD=/data/household" in dockerfile and "WORK=/data/work" in dockerfile
    assert 'CMD ["wakeword", "studio", "--host", "0.0.0.0", "--port", "8765"]' in dockerfile
    assert "/api/health" in dockerfile
    assert 'pip install -e "/app[evaluate]"' in dockerfile  # train/ and docs/ stay next to the code
    train = (ROOT / "train" / "train.sh").read_text(encoding="utf-8")
    assert 'VENV="${VENV:-$WORK/venv}"' in train and '[ ! -f "$VENV/.installed" ]' in train


def test_secrets_and_data_never_go_into_the_image_or_git():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for path in ("docker/config", "docker/data", "docker/.env", "data", "backup", ".git"):
        assert path in ignored
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert {"docker/data/", "docker/config/", "docker/.env"} <= set(gitignore)


def test_install_script_writes_a_private_login():
    script = DOCKER / "install-ubuntu.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    text = script.read_text(encoding="utf-8")
    assert "umask 077" in text and 'chmod 600 "$ENV_FILE"' in text and "secrets.token_urlsafe" in text
    assert "WAKEWORD_UI_AUTH=admin:" in text and "systemctl enable --now docker" in text


def test_show_login_reads_the_env_file(tmp_path):
    copy = tmp_path / "install-ubuntu.sh"
    copy.write_text((DOCKER / "install-ubuntu.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "env").write_text("WAKEWORD_UI_AUTH=admin:pa:ss\n", encoding="utf-8")
    out = subprocess.run(["bash", str(copy), "--show-login"], capture_output=True, text=True, check=True).stdout
    assert out == "user: admin\npassword: pa:ss\n"


def test_the_image_builds_the_documentation_and_checks_its_imports():
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "AS docs" in dockerfile and "mkdocs build --strict" in dockerfile
    assert "COPY --from=docs --chown=wakeword:wakeword /site /app/site" in dockerfile
    assert 'python -c "import tensorflow, microwakeword, audiomentations"' in dockerfile
    assert 'python -c "import wakeword.studio.server, wakeword.trainer.server"' in dockerfile
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert "site" in ignored and "docs" not in ignored and "mkdocs.yml" not in ignored


def test_the_installer_switches_an_old_panel_off_first():
    script = (ROOT / "docker" / "install-ubuntu.sh").read_text(encoding="utf-8")
    assert "systemctl --user disable --now" in script and "list-unit-files 'wakeword*'" in script
    assert 'ss -Hltn "sport = :$port"' in script  # an old "make ui-remote" on the same port is named, not fought


def test_the_demo_stage_is_light_and_not_the_one_compose_builds():
    """make demo builds --target demo: no training libraries, no compilers; the GPU studio stays the last stage."""
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    stages = dockerfile.split("\nFROM ")
    demo = next(stage for stage in stages if stage.split("\n", 1)[0].endswith(" AS demo"))
    for heavy in ("tensorflow", "requirements-train", "microWakeWord", "build-essential", "[evaluate]", "apt-get"):
        assert heavy not in demo, f"the demo stage installs {heavy}"
    assert 'CMD ["python", "docs/studio_demo.py", "--host", "0.0.0.0", "--port", "8766"]' in demo
    assert "COPY --from=docs" in demo and "import studio_demo" in demo
    last = stages[-1]
    assert last.split("\n", 1)[0].endswith(" AS studio") and "wakeword\", \"studio\"" in last
    compose = (ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8")
    assert "target: studio" in compose  # named: never the last stage by chance


def test_compose_builds_the_named_studio_stage_not_the_last_by_chance():
    """docker compose build without a target takes the LAST stage (Piper Voice Cloner started its demo on the
    machine that way): the target is named, exists and is not the demo."""
    service = yaml.safe_load((DOCKER / "compose.yaml").read_text(encoding="utf-8"))["services"]["studio"]
    target = service["build"]["target"]
    dockerfile = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    stages = [line.split(" AS ")[1].strip() for line in dockerfile.splitlines() if line.startswith("FROM ") and " AS " in line]
    assert target == "studio" and target in stages and target != "demo"


def test_torch_comes_from_the_cuda_12_index_and_no_cuda_13_package_gets_in():
    """torch from PyPI brings CUDA 13 libraries next to TensorFlow's CUDA 12 ones: one family in the image."""
    dockerfile = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG TORCH_INDEX=https://download.pytorch.org/whl/cu126" in dockerfile
    torch_at = dockerfile.index('pip install --index-url "$TORCH_INDEX" torch torchaudio')
    assert torch_at < dockerfile.index("pip install -r /tmp/requirements-train.txt")
    assert "grep -vi -- '-cu12=='" in dockerfile  # the build fails on any other nvidia-* package


def test_tensorflow_finds_cusolver():
    """TensorFlow 2.21's libtensorflow_framework lacks nvidia/cusolver/lib in its RUNPATH (2026-11-18: no GPU)."""
    dockerfile = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV CUSOLVER_LIB=/opt/venv/lib/python3.12/site-packages/nvidia/cusolver/lib" in dockerfile
    assert "ENV LD_LIBRARY_PATH=$CUSOLVER_LIB" in dockerfile
    assert 'test -f "$CUSOLVER_LIB/libcusolver.so.11"' in dockerfile
    # after the heavy layer: changing it never downloads the training libraries again
    assert dockerfile.index("ENV LD_LIBRARY_PATH") > dockerfile.index("pip install -r /tmp/requirements-train.txt")
    assert "FROM python:3.12-slim-bookworm AS studio" in dockerfile  # the path above names python3.12


def test_the_installer_and_status_check_tensorflow_on_the_gpu_not_only_nvidia_smi():
    script = (DOCKER / "install-ubuntu.sh").read_text(encoding="utf-8")
    assert 'tf.config.list_physical_devices("GPU")' in script and "--gpu-check)" in script
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    status = makefile[makefile.index("\nstatus:"):].split("\n\n", 1)[0]
    assert "docker/install-ubuntu.sh --gpu-check" in status


def test_the_container_keeps_the_machines_time_zone():
    """The wake log of Home Assistant is local time; a container in UTC would shift "Model since" by hours."""
    service = yaml.safe_load((DOCKER / "compose.yaml").read_text(encoding="utf-8"))["services"]["studio"]
    assert "/etc/localtime:/etc/localtime:ro" in service["volumes"]

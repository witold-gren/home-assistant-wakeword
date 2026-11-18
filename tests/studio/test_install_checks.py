"""docker/install-ubuntu.sh on a pretend machine: only basic tools on PATH, fakes of nvidia-smi, docker,
systemctl, ss and sudo, no $USER - each missing piece stops it with the hint that fixes it."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
BASIC = ("bash", "sh", "sed", "awk", "grep", "head", "cat", "mkdir", "chmod", "dirname", "id", "env",
         "python3", "printf", "tr", "cut", "hostname", "rm", "touch", "mv")

FAKES = {
    "nvidia-smi": """#!/bin/sh
case "$FAKE_NVIDIA" in silent) exit 9 ;; esac
case "$*" in *driver_version*) [ "$FAKE_NVIDIA" = old ] && echo 470.256.02 || echo 580.178.04 ;; *) echo GPU 0: RTX ;; esac
""",
    "docker": """#!/bin/sh
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  info) [ "$FAKE_DOCKER" = noaccess ] && exit 1
        case "$*" in *Runtimes*) [ "$FAKE_DOCKER" = notoolkit ] && echo '{"runc":{}}' || echo '{"nvidia":{}}' ;; esac
        exit 0 ;;
  compose)
    case "$*" in
      *" version"*) [ "$FAKE_DOCKER" = nocompose ] && exit 1; echo v2 ;;
      *" up "*) [ "$FAKE_DOCKER" = buildfail ] && { echo "build failed" >&2; exit 17; }; exit 0 ;;
      *TF_GPU_CHECK*|*tensorflow*) [ "$FAKE_TF" = nogpu ] && { echo "TensorFlow: no GPU" >&2; exit 1; }
                                   echo "TensorFlow 2.21.0: 1 GPU, a matrix product on the GPU works" ;;
      *nvidia-smi*) echo "NVIDIA GeForce RTX 4090, 24564 MiB" ;;
      *) exit 0 ;;
    esac ;;
esac
""",
    "systemctl": "#!/bin/sh\necho \"systemctl $*\" >> \"$FAKE_LOG\"\nexit 0\n",
    "ss": "#!/bin/sh\nexit 0\n",
    "sudo": "#!/bin/sh\necho \"sudo $*\" >> \"$FAKE_LOG\"\nexit 0\n",
    "df": "#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity Mounted'\necho '/dev/x 1 1 900000000 1% /'\n",
}


@pytest.fixture
def machine(tmp_path):
    """(run, folder): run(**fake settings) -> CompletedProcess of a copy of the installer."""
    docker = tmp_path / "app" / "docker"
    docker.mkdir(parents=True)
    shutil.copy(ROOT / "docker" / "install-ubuntu.sh", docker / "install-ubuntu.sh")
    shutil.copy(ROOT / "docker" / "compose.yaml", docker / "compose.yaml")
    (docker.parent / "pyproject.toml").write_text('[project]\nname = "home-assistant-wakeword"\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in BASIC:
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    fakes = {}
    for name, body in FAKES.items():
        fake = tmp_path / "fakes" / name
        fake.parent.mkdir(exist_ok=True)
        fake.write_text(body)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        fakes[name] = fake
    log = tmp_path / "calls.log"

    def run(*args, missing=(), stdin="", extra_env=None, **settings):
        for name, fake in fakes.items():
            link = bin_dir / name
            if link.exists() or link.is_symlink():
                link.unlink()
            if name not in missing:
                link.symlink_to(fake)
        env = {"PATH": str(bin_dir), "HOME": str(tmp_path), "FAKE_LOG": str(log),
               **{f"FAKE_{k.upper()}": v for k, v in settings.items()}, **(extra_env or {})}  # no USER on purpose
        return subprocess.run([str(bin_dir / "bash"), str(docker / "install-ubuntu.sh"), *args], env=env,
                              input=stdin, capture_output=True, text=True, timeout=60, check=False)

    run.log = log
    return run, docker


@pytest.mark.parametrize(("missing", "settings", "hint"), [
    (("nvidia-smi",), {}, "NVIDIA driver is missing"),
    ((), {"nvidia": "silent"}, "does not answer"),
    ((), {"nvidia": "old"}, "470.256.02 is too old"),
    (("docker",), {}, "Docker is missing"),
    ((), {"docker": "nocompose"}, "Docker Compose plugin is missing"),
    ((), {"docker": "notoolkit"}, "NVIDIA Container Toolkit is missing"),
])  # fmt: skip
def test_a_missing_piece_stops_with_its_fix(machine, missing, settings, hint):
    run, docker = machine
    result = run(missing=missing, **settings)
    assert result.returncode != 0
    assert hint in result.stderr
    assert not (docker / "config" / "env").exists()  # nothing written before the checks pass


def test_no_docker_access_names_the_user_even_without_user_variable(machine):
    run, _ = machine
    result = run(docker="noaccess")
    assert result.returncode != 0
    user = subprocess.run(["id", "-un"], capture_output=True, text=True, check=True).stdout.strip()
    assert f"sudo usermod -aG docker {user} (then" in result.stderr
    assert "unbound variable" not in result.stderr


def test_a_failed_build_stops_before_ready(machine):
    run, _ = machine
    result = run(docker="buildfail")
    assert result.returncode == 17 and "build failed" in result.stderr
    assert "ready:" not in result.stdout


def test_a_full_install_writes_a_private_login_and_checks_tensorflow_on_the_gpu(machine):
    run, docker = machine
    result = run()
    assert result.returncode == 0, result.stderr
    assert "a matrix product on the GPU works" in result.stdout and "ready:" in result.stdout
    env_file = docker / "config" / "env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    password = env_file.read_text()
    assert password.startswith("WAKEWORD_UI_AUTH=admin:")
    assert f"UID={os.getuid()}" in (docker / ".env").read_text()
    calls = run.log.read_text()
    assert "compose -f" in calls and "up -d --build" in calls
    # running it again (an update) keeps the login
    assert run().returncode == 0
    assert env_file.read_text() == password


def test_tensorflow_without_the_gpu_is_a_loud_warning(machine):
    run, _ = machine
    result = run(tf="nogpu")
    assert result.returncode == 0
    assert "TensorFlow in the container does not see the GPU" in result.stdout


def test_stop_only_stops_the_containers(machine):
    run, _ = machine
    result = run("--stop")
    assert result.returncode == 0 and "stays off after a restart" in result.stdout
    assert "compose -f" in run.log.read_text() and " stop" in run.log.read_text()


def _installed(run, docker, tmp_path, data_inside: bool):
    assert run().returncode == 0
    outside = tmp_path / "household-outside"
    outside.mkdir()
    (outside / "household.yaml").write_text("people: []\n")
    if data_inside:
        (docker / "data" / "household").mkdir(parents=True, exist_ok=True)
    else:  # installed with STUDIO_HOUSEHOLD/WORK/HF outside: no docker/data (the first run made the default one)
        shutil.rmtree(docker / "data")
        (docker / ".env").write_text(f"UID=1\nSTUDIO_HOUSEHOLD={outside}\nSTUDIO_WORK={outside}\nSTUDIO_HF={outside}\n")
    return outside


def test_uninstall_asks_first_and_removes_nothing_without_yes(machine, tmp_path):
    run, docker = machine
    _installed(run, docker, tmp_path, data_inside=False)
    result = run("--uninstall", stdin="no\n")
    assert result.returncode != 0 and "nothing removed" in result.stderr
    assert "This removes:" in result.stdout and "It keeps the data:" in result.stdout
    assert (docker / "config" / "env").exists() and docker.parent.exists()


def test_uninstall_removes_the_code_and_keeps_data_outside(machine, tmp_path):
    run, docker = machine
    outside = _installed(run, docker, tmp_path, data_inside=False)
    result = run("--uninstall", stdin="yes\n")
    assert result.returncode == 0, result.stderr
    assert not docker.parent.exists()  # the code folder is gone
    assert (outside / "household.yaml").exists()  # the data stays
    assert "image rm wakeword-studio:latest" in run.log.read_text()


def test_uninstall_keeps_the_code_folder_when_the_data_lies_inside(machine, tmp_path):
    run, docker = machine
    _installed(run, docker, tmp_path, data_inside=True)
    result = run("--uninstall", "--yes")
    assert result.returncode == 0, result.stderr
    assert not (docker / "config").exists() and not (docker / ".env").exists()
    assert (docker / "data" / "household").is_dir() and (docker.parent / "pyproject.toml").exists()


def test_uninstall_never_removes_another_project(machine):
    run, docker = machine
    (docker.parent / "pyproject.toml").write_text('[project]\nname = "something-else"\n')
    result = run("--uninstall", "--yes")
    assert result.returncode != 0 and "is not the wake word studio" in result.stderr
    assert docker.parent.exists() and "compose" not in (run.log.read_text() if run.log.exists() else "")


def test_the_trusted_networks_go_into_the_env_file_and_can_be_removed(machine):
    run, docker = machine
    env_file = docker / "config" / "env"
    assert run().returncode == 0
    assert "STUDIO_TRUSTED_NETWORKS" not in env_file.read_text()  # not asked for: the login from everywhere
    result = run(extra_env={"STUDIO_TRUSTED_NETWORKS": "192.168.1.0/24"})
    assert result.returncode == 0 and "no login from: 192.168.1.0/24" in result.stdout
    text = env_file.read_text()
    assert text.count("STUDIO_TRUSTED_NETWORKS=192.168.1.0/24") == 1 and text.startswith("WAKEWORD_UI_AUTH=admin:")
    assert run(extra_env={"STUDIO_TRUSTED_NETWORKS": "192.168.1.0/24"}).returncode == 0
    assert env_file.read_text().count("STUDIO_TRUSTED_NETWORKS=") == 1  # replaced, not added twice
    assert run(extra_env={"STUDIO_TRUSTED_NETWORKS": ""}).returncode == 0
    assert "STUDIO_TRUSTED_NETWORKS" not in env_file.read_text() and env_file.read_text().startswith("WAKEWORD_UI_AUTH=")
    assert oct(env_file.stat().st_mode)[-3:] == "600"

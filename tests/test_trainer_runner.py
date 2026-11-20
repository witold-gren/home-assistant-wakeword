import subprocess
import time
from pathlib import Path

import pytest

from wakeword.trainer.runner import LOG, PID, LocalRunner, parse_gpu, train_command


def test_train_command():
    assert (
        train_command(["dzarwis", "wajana"], 40000, False, "../household")
        == "STEPS=40000 train/train.sh ../household dzarwis wajana"
    )
    assert (
        train_command([], None, True, "/x y") == "TRAIN=0 train/train.sh '/x y' --all"
    )


def test_train_command_set_weights():
    assert (
        train_command(["w"], None, False, "h", weights={"real": 6.0, "synthetic": 1.5})
        == "SET_WEIGHTS=real=6,synthetic=1.5 train/train.sh h w"
    )


def test_train_command_negative_weight():
    assert (
        train_command(["w"], 10000, False, "h", 40)
        == "STEPS=10000 NEG_WEIGHT=40 train/train.sh h w"
    )
    assert (
        train_command(["w"], None, False, "h", 12.5)
        == "NEG_WEIGHT=12.5 train/train.sh h w"
    )


def test_parse_gpu():
    gpu = parse_gpu("NVIDIA GeForce RTX 4090, 87, 5123, 24564, 64, 301.25")
    assert gpu == {
        "name": "NVIDIA GeForce RTX 4090",
        "utilization": 87.0,
        "memory_used": 5123.0,
        "memory_total": 24564.0,
        "temperature": 64.0,
        "power": 301.25,
    }
    assert parse_gpu("NVIDIA, [N/A], 1, 2, 3, [N/A]")["power"] is None
    assert parse_gpu("garbage") is None


class Done:
    def __init__(self, code=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = code, out, err


def fake_repo(tmp_path, body: str):
    repo = tmp_path / "repo"
    (repo / "train").mkdir(parents=True)
    script = repo / "train" / "train.sh"
    script.write_text("#!/usr/bin/env bash\n" + body)
    script.chmod(0o755)
    return repo


def test_local_runner(tmp_path):
    household = tmp_path / "home"
    household.mkdir()
    repo = fake_repo(
        tmp_path, 'echo "args: $* steps=$STEPS"; echo "==> w: training"; sleep 30\n'
    )
    runner = LocalRunner(repo, household)
    runner.start(["w"], 500, False)
    deadline = time.time() + 5
    while time.time() < deadline and b"training" not in runner.status(0).log:
        time.sleep(0.05)
    status = runner.status(0)
    assert status.running
    assert b"args: " + str(household).encode() + b" w steps=500" in status.log
    assert (household / PID).exists() and (household / LOG).exists()
    assert runner.status(len(b"args")).log.startswith(b": ")
    runner.stop()
    deadline = time.time() + 5
    while time.time() < deadline and runner.running():
        time.sleep(0.05)
    assert not runner.running()


def test_local_runner_without_pid(tmp_path):
    runner = LocalRunner(tmp_path, tmp_path)
    assert not runner.running()
    runner.stop()  # nothing to stop
    (tmp_path / "data" / "build").mkdir(parents=True)
    (tmp_path / PID).write_text("999999999")
    assert not runner.running()
    assert "host:" in runner.check()


def test_check_script_reports_a_missing_venv_package(tmp_path):
    """Ubuntu 24.04: python3 is there, but python3.12-venv is not - the check must say what to install."""

    from wakeword.trainer.runner import CHECK_SCRIPT

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, works in (
        ("python3", False),
        ("python3.12", False),
        ("python3.11", True),
    ):
        fake = bin_dir / name
        fake.write_text(
            "#!/bin/sh\n"
            'case "$2" in *ensurepip*) exit %d;; esac\necho 3.12\n'
            % (0 if works else 1)
        )
        fake.chmod(0o755)
    run = lambda path: (
        subprocess.run(
            ["bash", "-c", CHECK_SCRIPT],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={"PATH": path},
        ).stdout
    )
    assert "venv: python3.11" in run(f"{bin_dir}:/usr/bin:/bin")
    (bin_dir / "python3.11").unlink()
    assert (
        "venv: MISSING (sudo apt install -y python3.12-venv python3.12-dev build-essential)"
        in run(f"{bin_dir}:/usr/bin:/bin")
    )


def wait_for(condition, seconds: float = 5.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


TOKEN = "hf_" + "A1b2C3d4" * 4


def test_local_hf_token_saved_private_and_removed(tmp_path):
    from wakeword.trainer.runner import save_local_hf_token

    save_local_hf_token(TOKEN, home=tmp_path)
    path = tmp_path / ".cache" / "huggingface" / "token"
    assert path.read_text() == TOKEN and oct(path.stat().st_mode & 0o777) == "0o600"
    save_local_hf_token("", home=tmp_path)
    assert not path.exists()


def test_check_script_reports_the_hf_token(tmp_path):

    from wakeword.trainer.runner import CHECK_SCRIPT

    run = lambda: (
        subprocess.run(
            ["bash", "-c", CHECK_SCRIPT],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        ).stdout
    )
    assert "hugging face token: no (optional)" in run()
    (tmp_path / ".cache" / "huggingface").mkdir(parents=True)
    (tmp_path / ".cache" / "huggingface" / "token").write_text(TOKEN)
    out = run()
    assert "hugging face token: yes" in out and TOKEN not in out


def test_local_status_reports_the_hf_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = LocalRunner(tmp_path / "repo", tmp_path / "home")
    assert runner.status(0).hf_token is False
    from wakeword.trainer.runner import save_local_hf_token

    save_local_hf_token(TOKEN)
    assert runner.status(0).hf_token is True


def test_train_command_passes_the_learning_rates():
    command = train_command(
        ["robo"], 20000, False, "../household", 30, [0.0005, 0.0001]
    )
    assert command.startswith(
        "STEPS=20000 NEG_WEIGHT=30 LEARNING_RATES=0.0005,0.0001 train/train.sh"
    )
    assert "LEARNING_RATES" not in train_command(
        ["robo"], None, False, "../household", None, []
    )


def test_choosing_the_base_runs_train_sh_without_training():
    command = train_command(
        ["robo"], 20000, False, "../household", 30, [0.001], base="20261028-221357"
    )
    assert (
        command == "BASE=20261028-221357 train/train.sh ../household robo"
    )  # nothing else: no training


def test_models_listed_on_this_computer(tmp_path):
    repo = Path(__file__).parents[1]
    home = tmp_path / "home"
    (home / "data" / "build" / "robo").mkdir(parents=True)
    runner = LocalRunner(repo, home)
    assert runner.list_models("robo") == {
        "word": "robo",
        "models": [],
        "base": None,
        "trained": False,
    }


def test_models_from_an_older_machine_say_what_to_do(tmp_path):

    from wakeword.trainer.runner import _models_answer

    old = subprocess.CompletedProcess(
        [],
        2,
        b"",
        b"python3: can't open file 'train/models.py': [Errno 2] No such file",
    )
    with pytest.raises(RuntimeError, match="make deploy"):
        _models_answer(old)


def test_the_log_kept_with_a_model_is_read_on_this_computer(tmp_path):
    import gzip

    repo = Path(__file__).parents[1]
    home = tmp_path / "home"
    model = home / "data" / "build" / "robo" / "models" / "20261029-143440"
    model.mkdir(parents=True)
    (model / "train.log.gz").write_bytes(
        gzip.compress(b"==> robo: training\nAUC 0.3\n")
    )
    runner = LocalRunner(repo, home)
    assert runner.model_log("robo", "20261029-143440").endswith("AUC 0.3\n")
    with pytest.raises(RuntimeError, match="no log kept"):
        runner.model_log("robo", "20261029-000000")


def test_household_test_runs_in_the_training_venv(tmp_path):
    local = LocalRunner(tmp_path / "repo", tmp_path / "home").evaluate_command("robo")
    assert (
        local[:2] == ["bash", "-c"]
        and f"-H {tmp_path / 'home'} evaluate-models robo --missing" in local[2]
    )
    assert (
        '"${VENV:-${WORK:-$HOME/wakeword-work}/venv}/bin/python" -m wakeword'
        in local[2]
    )


def test_local_runner_starts_the_real_train_script_the_way_the_studio_does(
    tmp_path, monkeypatch
):
    """No fake repository: the command the studio builds reaches the real train/train.sh (Piper Voice Cloner's
    jobs ended in 0.1 s with exit 0 and an empty log - its tests always used a fake CLI). Here train.sh stops
    at choosing a Python, before any install or download: the log says why and the exit code is not 0."""
    monkeypatch.setenv("WORK", str(tmp_path / "work"))
    monkeypatch.setenv("VENV", str(tmp_path / "work" / "venv"))
    monkeypatch.setenv("PYTHON", "no-such-python")
    household = tmp_path / "home"
    household.mkdir()
    runner = LocalRunner(Path(__file__).parents[1], household)
    runner.start(["hey_home"], 500, False)
    runner._process.wait(timeout=30)
    assert runner._process.returncode == 1
    log = runner.status(0).log.decode()
    assert "no Python here can create a virtual environment" in log
    assert not (tmp_path / "work" / "venv").exists()  # nothing installed


def test_local_runner_lists_models_with_the_real_script(tmp_path):
    household = tmp_path / "home"
    household.mkdir()
    answer = LocalRunner(Path(__file__).parents[1], household).list_models("hey_home")
    assert (
        answer["word"] == "hey_home"
        and answer["models"] == []
        and answer["trained"] is False
    )

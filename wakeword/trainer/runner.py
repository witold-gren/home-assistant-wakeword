"""Run training on this machine (the studio's container).

Training runs detached (it survives closing the browser) and writes ``data/build/train.log`` and
``train.pid`` in the household folder. The studio only reads that log.
"""

from __future__ import annotations

import gzip
import json
import os
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LOG = "data/build/train.log"
PID = "data/build/train.pid"
MAX_READ = 2_000_000  # bytes of log per poll


@dataclass
class Status:
    running: bool
    log: bytes  # new log bytes from the requested offset
    gpu: dict | None  # utilization, memory_used, memory_total, temperature, power (None = no GPU)
    hf_token: bool | None = None  # a Hugging Face token saved on the machine (only whether - never the value)


GPU_QUERY = ("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw "
             "--format=csv,noheader,nounits")


def parse_gpu(line: str) -> dict | None:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        return None

    def number(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None

    return {"name": parts[0], "utilization": number(parts[1]), "memory_used": number(parts[2]),
            "memory_total": number(parts[3]), "temperature": number(parts[4]), "power": number(parts[5])}


# the venv train.sh makes (VENV, default $WORK/venv, WORK default ~/wakeword-work; /opt/venv in the Docker image):
# numpy, soundfile, pymicro-features, ai-edge-litert
EVALUATE_PYTHON = '"${VENV:-${WORK:-$HOME/wakeword-work}/venv}/bin/python"'


def train_command(words: list[str], steps: int | None, convert_only: bool, household: str,
                  negative_weight: float | None = None, learning_rates: list[float] | None = None,
                  base: str | None = None, weights: dict[str, float] | None = None) -> str:
    """The train.sh call (run from the repository folder); ``base``: only choose the model the next run starts from."""
    if base:
        args = " ".join(shlex.quote(w) for w in words)
        return f"BASE={shlex.quote(base)} train/train.sh {shlex.quote(household)} {args}"
    env = []
    if steps:
        env.append(f"STEPS={int(steps)}")
    if negative_weight:
        env.append(f"NEG_WEIGHT={float(negative_weight):g}")
    if learning_rates:
        env.append("LEARNING_RATES=" + ",".join(f"{float(r):g}" for r in learning_rates))
    if weights:  # set names are checked (training_config.check_weights): letters and _ only
        env.append("SET_WEIGHTS=" + ",".join(f"{name}={float(w):g}" for name, w in weights.items()))
    if convert_only:
        env.append("TRAIN=0")
    args = " ".join(shlex.quote(w) for w in words) if words else "--all"
    return " ".join([*env, "train/train.sh", shlex.quote(household), args])


def _models_answer(result: subprocess.CompletedProcess) -> dict:
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace").strip()
        if "models.py" in error and ("No such file" in error or "can't open" in error):
            error = "the training scripts are older than the studio - update the studio on the machine (make deploy)"
        raise RuntimeError(error or "listing the models failed")
    return json.loads(result.stdout)


def _log_answer(result: subprocess.CompletedProcess) -> str:
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or "reading the model's log failed")
    return gzip.decompress(result.stdout).decode(errors="replace")


class LocalRunner:
    """Training on this computer (e.g. the UI runs on the GPU machine itself)."""

    def __init__(self, repo: Path, household: Path) -> None:
        self.repo = Path(repo)
        self.household = Path(household)

    def _path(self, relative: str) -> Path:
        return self.household / relative

    def start(self, words: list[str], steps: int | None, convert_only: bool,
              negative_weight: float | None = None, learning_rates: list[float] | None = None,
              base: str | None = None, weights: dict[str, float] | None = None) -> None:
        log = self._path(LOG)
        log.parent.mkdir(parents=True, exist_ok=True)
        command = train_command(words, steps, convert_only, str(self.household), negative_weight, learning_rates, base,
                                weights)
        with log.open("wb") as out:
            process = subprocess.Popen(["bash", "-c", command], cwd=self.repo, stdout=out, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
        self._path(PID).write_text(str(process.pid))
        self._process = process  # keep a reference so the child is reaped

    def list_models(self, word: str) -> dict:
        """The kept models of a word (train/models.py list)."""
        result = subprocess.run([sys.executable, str(self.repo / "train" / "models.py"), "list", str(self.household), word],
                                capture_output=True, timeout=60, check=False)
        return _models_answer(result)

    def rename_word(self, old: str, new: str) -> str | None:
        """Nothing more to do: the household folder here is the one rename_word already changed."""
        return None

    def evaluate_command(self, word: str) -> list[str]:
        """The household test of the kept models, in the training venv (its TFLite runtime)."""
        return ["bash", "-c", (f"cd {shlex.quote(str(self.repo))} && {EVALUATE_PYTHON} -m wakeword "
                              f"-H {shlex.quote(str(self.household))} evaluate-models {shlex.quote(word)} --missing")]

    def model_log(self, word: str, model_id: str) -> str:
        """The log kept with a model (train/models.py log), as text."""
        result = subprocess.run([sys.executable, str(self.repo / "train" / "models.py"), "log", str(self.household), word,
                                 model_id], capture_output=True, timeout=60, check=False)
        return _log_answer(result)

    def _pid(self) -> int | None:
        try:
            return int(self._path(PID).read_text().strip())
        except (OSError, ValueError):
            return None

    def running(self) -> bool:
        process = getattr(self, "_process", None)
        if process is not None:
            return process.poll() is None
        pid = self._pid()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def stop(self) -> None:
        pid = self._pid()
        if pid is not None and self.running():
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass

    def status(self, offset: int) -> Status:
        log = b""
        try:
            with self._path(LOG).open("rb") as handle:
                handle.seek(offset)
                log = handle.read(MAX_READ)
        except OSError:
            pass
        gpu = None
        try:
            result = subprocess.run(GPU_QUERY.split(), capture_output=True, text=True, timeout=5, check=False)
            if result.returncode == 0 and result.stdout.strip():
                gpu = parse_gpu(result.stdout.strip().splitlines()[0])
        except (OSError, subprocess.TimeoutExpired):
            pass
        token = Path.home() / ".cache" / "huggingface" / "token"
        return Status(self.running(), log, gpu, token.is_file() and token.stat().st_size > 0)

    def check(self) -> str:
        result = subprocess.run(["bash", "-c", CHECK_SCRIPT], capture_output=True, text=True, timeout=30, check=False)
        return result.stdout + result.stderr

    def save_hf_token(self, token: str) -> None:
        save_local_hf_token(token)


# Hugging Face token on the training machine, where huggingface_hub looks for it by itself.
# Passed on stdin (not in the command line, which other users could see) and never kept here.


def save_local_hf_token(token: str, home: Path | None = None) -> None:
    path = (home or Path.home()) / ".cache" / "huggingface" / "token"
    if not token:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(token)
    path.chmod(0o600)


CHECK_SCRIPT = (
    "echo \"host: $(hostname)\"; "
    "(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null"
    " | sed 's/^/gpu: /') || echo 'gpu: none (nvidia-smi not found)'; "
    "echo \"python: $(python3 --version 2>&1)\"; "
    # the same choice as train.sh: the first Python that can create a venv
    "venv=; for p in python3.12 python3.11 python3.10; do "
    "command -v $p >/dev/null 2>&1 && $p -c 'import ensurepip, venv' 2>/dev/null && { venv=$p; break; }; done; "
    r"""v=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null); """
    r"""[ -n "$venv" ] && echo "venv: $venv" """
    r"""|| echo "venv: MISSING (sudo apt install -y python$v-venv python$v-dev build-essential)"; """
    "echo \"free disk: $(df -h . | awk 'NR==2{print $4}')\"; "
    "for tool in rsync ffmpeg wget unzip git; do command -v $tool >/dev/null && echo \"$tool: yes\" || echo \"$tool: MISSING\"; done; "
    "[ -s ~/.cache/huggingface/token ] && echo 'hugging face token: yes' || echo 'hugging face token: no (optional)'"
)


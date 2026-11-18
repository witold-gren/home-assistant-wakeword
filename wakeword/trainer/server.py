"""The studio's training backend: the household, recordings, voices, preparing, training on this machine
(``train/train.sh`` in the container), models, evaluation, export and Home Assistant - independent of HTTP
(``wakeword.studio.server`` serves it), so tests can drive it directly."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from dataclasses import asdict
from pathlib import Path

import yaml

from .. import elevenlabs, ha_sync, power
from ..dataset import list_takes
from ..export import TRAINED_MODEL
from ..household import (
    GROUPS,
    HOUSEHOLD_FILE,
    STOCK_WORDS,
    Household,
    HouseholdError,
    load_household,
)
from ..languages import AVAILABLE, get_pack
from ..recordings import delete_recordings, list_recordings, recording_path
from ..scaffold import esphome_devices, read_raw, rename_word, save_raw
from ..synthetic import PIPER_VOICES, build_dir
from ..training_config import (
    DEFAULT_WEIGHTS,
    WEIGHT_PRESETS,
    changed_since_prepare,
    check_weights,
)
from . import progress as progress_module
from .models import local_model
from .models import rank as rank_models
from .runner import CHECK_SCRIPT, LocalRunner

REPO = Path(__file__).resolve().parents[2]
HF_TOKEN_PATTERN = re.compile(r"^hf_[A-Za-z0-9]{20,}$")
DOCS = REPO / "docs"  # the documentation's Markdown sources
SITE = REPO / "site"  # the documentation built by MkDocs (make docs): English at its root, Polish in pl/
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".json": "application/json; charset=utf-8", ".yaml": "text/plain; charset=utf-8",
                 ".xml": "application/xml"}
POLL_SECONDS = 3.0


def docs_path(name: str) -> tuple[Path, str]:
    """/docs/<lang>/<page> -> (folder, file) in the built documentation (SITE): English lives at its root."""
    lang, _, rest = name.partition("/")
    if lang == "en":
        name = rest  # English pages are the site's root; pl/ and the shared files (assets/, search/) stay as they are
    if not name or name.endswith("/"):
        name += "index.html"
    return SITE, name


ESPHOME_CACHE_SECONDS = 60  # the device list from Home Assistant, asked again after this
COOKIE = "wakeword_trainer"
MAX_JOB_LINES = 400
HF_REPO_PATTERN = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")
MODEL_ID_PATTERN = re.compile(r"^(\d{8}-\d{6}|new)$")  # train/models.py


class Job:
    """A local command sequence (rsync, prepare, evaluate …) with its output."""

    def __init__(self, name: str, commands: list[list[str]], cwd: Path) -> None:
        self.name = name
        self.commands = commands
        self.cwd = cwd
        self.lines: deque[str] = deque(maxlen=MAX_JOB_LINES)
        self.running = True
        self.code: int | None = None
        self.started = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        code = 0
        for command in self.commands:
            self.lines.append("$ " + " ".join(command[:3]) + (" …" if len(command) > 3 else ""))
            try:
                process = subprocess.Popen(command, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, text=True, errors="replace")
            except OSError as err:
                self.lines.append(f"error: {err}")
                code = 127
                break
            assert process.stdout is not None
            for line in process.stdout:
                self.lines.append(line.rstrip("\n").rsplit("\r", 1)[-1])
            code = process.wait()
            if code != 0:
                break
        self.code = code
        self.running = False

    def as_dict(self) -> dict:
        return {"name": self.name, "running": self.running, "code": self.code, "started": self.started,
                "lines": list(self.lines)[-150:]}


class Trainer:
    """State of the studio's training (independent of HTTP, so tests can drive it directly)."""

    def __init__(self, household: Path, repo: Path = REPO) -> None:
        self.household = Path(household).resolve()
        self._load()  # fail early on a broken household.yaml (a missing one is created in the panel)
        self.repo = Path(repo)
        self.lock = threading.Lock()
        self.job: Job | None = None
        self._esphome_cache: tuple[float, list[dict]] | None = None  # (time, devices) read from Home Assistant
        self._machine_cache: tuple[float, dict] | None = None  # (time, plug/power/state) from Home Assistant
        self._checked = False  # the machine answered (or failed to) at least once
        self._refreshing = False  # a background check of the machine and Home Assistant is running
        self.log = bytearray()
        self.started_at: float | None = None
        self.running = False
        self.gpu: dict | None = None
        self.hf_token: bool | None = None  # token on the training machine (None = not known yet)
        self.remote_error: str | None = None
        self._progress = progress_module.Progress()
        self._polled = 0.0
        self._runner: LocalRunner | None = None

    def _load(self) -> Household | None:
        """The household (words may still be missing); None when household.yaml does not exist yet."""
        if not (self.household / HOUSEHOLD_FILE).exists():
            return None
        return load_household(self.household, require_words=False)

    def _require(self) -> Household:
        household = self._load()
        if household is None:
            raise RuntimeError("create the household first (people and words)")
        return household

    # --- household editing ---------------------------------------------------------------------
    def household_data(self) -> dict:
        household = self._load()
        data = read_raw(self.household) if household else {
            "ui_language": "pl", "speakers": [], "words": {}, "targets": {"adult": 12, "child": 18, "held_out": 3},
            "devices": {}, "voices": {}}
        counts = {}
        if household:
            for word in household.words.values():
                counts[word.id] = {sid: len(list_takes(household, word.id, sid)) for sid in household.speakers}
        return {
            "exists": household is not None,
            "data": data,
            "counts": counts,
            "languages": sorted(PIPER_VOICES),
            "default_voices": {lang: list(voices) for lang, voices in PIPER_VOICES.items()},
            "elevenlabs_models": list(elevenlabs.MODELS),
            "elevenlabs_variants": len(elevenlabs.VARIANTS),
            "ui_languages": list(AVAILABLE),
            "stock_words": sorted(STOCK_WORDS),
            "groups": list(GROUPS),
            "esphome": self.esphome_devices(),
        }

    def esphome_devices(self) -> list[dict]:
        """Voice devices for the Devices tab: from Home Assistant's API when connected, else a local folder
        (WAKEWORD_ESPHOME, e.g. the mounted share, or next to the household in /config/wakeword)."""
        if ha_sync.load_connection().ready:
            now = time.time()
            if self._esphome_cache and now - self._esphome_cache[0] < ESPHOME_CACHE_SECONDS:
                return self._esphome_cache[1]
            try:
                devices = ha_sync.Client().esphome_devices()
                self._esphome_cache = (now, devices)
                return devices
            except ha_sync.HaError:
                pass  # e.g. an older integration: the folder, if there is one
        return esphome_devices(Path(os.environ.get("WAKEWORD_ESPHOME") or self.household.parent / "esphome"))

    def save_household(self, data: dict) -> str | None:
        """Save household.yaml here and send it to Home Assistant; returns why it could not be sent."""
        try:
            save_raw(self.household, data)
        except HouseholdError as err:
            raise ValueError(str(err)) from err
        return self._push_household()

    def _push_household(self) -> str | None:
        if not ha_sync.load_connection().ready:
            return None
        try:  # the satellites ask for the people and words of this file
            ha_sync.push_household(self.household)
        except ha_sync.HaError as err:
            return str(err)
        return None

    def rename_word(self, old: str, new: str) -> str | None:
        """A word's id changed here and on Home Assistant; returns why it could not be sent there."""
        if self.job is not None and self.job.running:
            raise RuntimeError("wait until the current job ends")
        if self.poll(force=True)["running"]:  # the machine's folders are renamed too
            raise RuntimeError("wait until the training ends")
        try:
            rename_word(self.household, old, new.strip())
        except HouseholdError as err:
            raise ValueError(str(err)) from err
        warnings = [self._push_household()]
        machine = self.runner().rename_word(old, new.strip())
        if machine:
            warnings.append(f"training machine: {machine}")
        return "; ".join(w for w in warnings if w) or None

    def training_log(self) -> str:
        """The whole training log as a terminal shows it (the state carries only its tail)."""
        with self.lock:
            text = self.log.decode(errors="replace")
        return "\n".join(progress_module.clean_lines(text))

    # --- recordings on disk ----------------------------------------------------------------------
    def hf_voices(self, repo: str) -> list[str]:
        """Piper voices (<voice>.onnx next to <voice>.onnx.json) at the top of a Hugging Face model repository."""
        repo = repo.strip().removeprefix("https://huggingface.co/").strip("/")
        if not HF_REPO_PATTERN.match(repo):
            raise ValueError("give a Hugging Face repository as owner/name, e.g. WitoldG/polish_piper_models")
        url = f"https://huggingface.co/api/models/{repo}/tree/main"
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                files = json.load(response)
        except (OSError, ValueError) as err:
            raise ValueError(f"cannot read huggingface.co/{repo}: {err}") from err
        names = {f.get("path", "") for f in files if f.get("type") == "file"}
        voices = sorted(name.removesuffix(".onnx") for name in names
                        if name.endswith(".onnx") and f"{name}.json" in names)
        if not voices:
            raise ValueError(f"no Piper voices (.onnx + .onnx.json) in huggingface.co/{repo}")
        return [f"{repo}/{voice}" for voice in voices]

    # --- ElevenLabs (on this computer; the key never leaves ~/.config/wakeword) -------------------

    def save_elevenlabs_key(self, key: str) -> None:
        elevenlabs.save_key(key)

    def elevenlabs_voices(self, language: str, sync: bool = False) -> list[dict]:
        household = self._require()
        return elevenlabs.sync_voices(household, language) if sync else elevenlabs.cached_voices(household, language)

    def elevenlabs_test(self, voice_id: str, word: str, language: str, model: str) -> bytes:
        """The first spelling of the word in one voice, plain settings - to hear it before choosing."""
        household = self._require()
        self._known_word(word)
        if not elevenlabs.VOICE_ID_PATTERN.match(voice_id):
            raise ValueError("not an ElevenLabs voice id")
        if model not in elevenlabs.MODELS:
            raise ValueError(f"model: one of {', '.join(elevenlabs.MODELS)}")
        text = elevenlabs.texts_for(household, word, language)[0]
        try:
            samples = elevenlabs.speak(elevenlabs.client(), voice_id, text, model, elevenlabs.VARIANTS[0], seed=1,
                                       language=language)
        except RuntimeError as err:
            elevenlabs.learn_from(household, err)
            if elevenlabs.voice_refused(err):  # listed apart, skipped by "Generate takes"
                voice = next((v for v in elevenlabs.cached_voices(household, language) if v["id"] == voice_id), {})
                elevenlabs.remember_broken(household, voice_id, str(err), voice.get("name", ""))
            raise
        elevenlabs.learn_paid(household, voice_id, language)
        return elevenlabs.wav_bytes(samples)

    def elevenlabs_add(self, voice_id: str, language: str) -> None:
        household = self._require()
        voice = next((v for v in elevenlabs.cached_voices(household, language) if v["id"] == voice_id), None)
        if not voice or not voice.get("owner"):
            raise ValueError("not a Voice Library voice of the last synchronisation")
        elevenlabs.add_to_account(voice)

    def elevenlabs_restore(self, voice_id: str) -> None:
        """A refused voice back in the list - to test it again."""
        elevenlabs.forget_broken(self._require(), voice_id)

    def elevenlabs_generate(self, words: list[str]) -> None:
        for word in words:
            self._known_word(word)
        if not elevenlabs.load_key():
            raise ValueError("no ElevenLabs API key - save it first")
        self._start_job("elevenlabs", [self._wakeword("elevenlabs", *words)])

    def recordings(self) -> dict:
        return list_recordings(self.household)

    def recording_audio(self, relative: str) -> bytes:
        return recording_path(self.household, relative).read_bytes()

    def delete_recordings(self, paths: list[str]) -> str:
        if self.job is not None and self.job.running:
            raise RuntimeError("wait until the current job ends")
        backup = delete_recordings(self.household, paths)
        return str(backup.relative_to(self.household))

    # --- where training runs -------------------------------------------------------------------
    def runner(self) -> LocalRunner:
        # one instance: the runner keeps its process object (reaped when it ends)
        if self._runner is None:
            self._runner = LocalRunner(self.repo, self.household)
        return self._runner

    # --- local jobs ----------------------------------------------------------------------------
    def _start_job(self, name: str, commands: list[list[str]]) -> None:
        if self.job is not None and self.job.running:
            raise RuntimeError(f"'{self.job.name}' is still running")
        self.job = Job(name, commands, self.repo)

    def _wakeword(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "wakeword", "-H", str(self.household), *args]

    def check(self) -> None:
        self._start_job("check", [["bash", "-c", CHECK_SCRIPT]])

    def save_hf_token(self, token: str) -> None:
        """Put a Hugging Face token on the training machine (empty = remove it); never stored here."""
        token = token.strip()
        if token and not HF_TOKEN_PATTERN.match(token):
            raise ValueError("this is not a Hugging Face token (hf_…)")  # the value is never echoed
        self.runner().save_hf_token(token)
        with self.lock:
            self.hf_token = bool(token)  # shown at once, confirmed by the next poll

    def prepare(self, words: list[str], force: bool) -> None:
        for word in words:
            self._known_word(word)
        selection = words or ["--all"]
        prepare = self._wakeword("prepare", *selection, *(["--force"] if force else []))
        # the newest takes recorded through the satellites first (skipped when HA is not set or not reachable)
        pull = [self._wakeword("ha-pull", "--optional")] if ha_sync.load_connection().ready else []
        self._start_job("prepare", [*pull, prepare])

    def ha_pull(self) -> None:
        if not ha_sync.load_connection().ready:
            raise ValueError("set the Home Assistant address and token first")
        # by hand, at any time: household.yaml there first (the satellites ask for its people and words),
        # then the new recordings here
        self._start_job("ha_pull", [self._wakeword("ha-push"), self._wakeword("ha-pull")])

    def ha_connection(self, url: str, token: str | None) -> None:
        """Save the connection (a rejected token may be asked again) and check it with one request."""
        ha_sync.save_connection(url, token)
        self._machine_cache = None
        self._esphome_cache = None
        if not ha_sync.load_connection().ready:
            return
        try:
            ha_sync.check_connection()
        except ha_sync.HaError as err:
            raise ValueError(f"saved, but {err}") from None

    # --- the training machine's power, through Home Assistant (wakeword/power.py) ------------------
    MACHINE_CACHE = 10.0

    def save_power(self, data: dict) -> None:
        settings = power.PowerSettings(switch=str(data.get("switch", "")).strip(), sensor=str(data.get("sensor", "")).strip(),
                                       off_watts=float(data.get("off_watts") or 5))
        power.save_power(settings)
        self._machine_cache = None

    def machine(self) -> dict | None:
        """The plug, its power and whether the machine is on (header button); None when not set up."""
        settings = power.load_power()
        if not settings.ready or not ha_sync.load_connection().ready:
            return None
        if ha_sync.token_rejected():  # never asked again with this token (ip_ban counts each 401)
            return {"machine": "rejected", "error": ha_sync.REJECTED_MESSAGE}
        cached = self._machine_cache
        if cached and time.time() - cached[0] < self.MACHINE_CACHE:
            return cached[1]
        try:
            answer = power.machine_state(ha_sync.Client(), settings, True)  # the studio runs on the machine itself
        except ha_sync.HaError as err:
            answer = {"machine": "unknown", "error": str(err)}
        self._machine_cache = (time.time(), answer)
        return answer

    def machine_cached(self) -> dict | None:
        """The last known machine state for the page ({"machine": "checking"} before the first answer)."""
        settings = power.load_power()
        if not settings.ready or not ha_sync.load_connection().ready:
            return None
        if ha_sync.token_rejected():
            return {"machine": "rejected", "error": ha_sync.REJECTED_MESSAGE}
        cached = self._machine_cache
        return cached[1] if cached else {"machine": "checking"}

    def switch_machine(self, on: bool) -> None:
        """Flip the machine's switch in Home Assistant (it shuts the system down before cutting the plug)."""
        settings = power.load_power()
        if not settings.ready:
            raise ValueError("set the machine's switch and power sensor first (Settings → Home Assistant)")
        if not on and self.poll(force=True)["running"]:
            raise RuntimeError("a training is running on the machine - stop it first or wait until it ends")
        try:
            power.switch_machine(ha_sync.Client(), settings, on)
        except ha_sync.HaError as err:
            raise RuntimeError(str(err)) from None
        self._machine_cache = None

    def ha_entities(self) -> dict:
        """Candidates for the power settings: switches and power sensors (W)."""
        entities = ha_sync.Client().entities()

        def pick(test):
            return sorted(({"id": e["entity_id"], "name": e.get("attributes", {}).get("friendly_name") or ""}
                           for e in entities if test(e)), key=lambda e: e["id"])

        return {"switches": pick(lambda e: e["entity_id"].startswith(("switch.", "input_boolean."))),
                "sensors": pick(lambda e: e["entity_id"].startswith("sensor.")
                                and e.get("attributes", {}).get("unit_of_measurement") == "W")}

    def evaluate(self, word: str) -> None:
        self._known_word(word)
        self._start_job("evaluate", [self._wakeword("evaluate", word)])

    def export(self, cutoff: float) -> None:
        if not 0 < cutoff < 1:
            raise ValueError("cutoff must be between 0 and 1")
        words = [w for w in self.words() if w["trained"]]
        if not words:
            raise RuntimeError("no trained model yet - fetch the models first")
        to_ha = ["--ha"] if ha_sync.load_connection().ready else []  # the models go straight to /config/esphome
        self._start_job("export", [self._wakeword("export", *[w["id"] for w in words], "--cutoff", str(cutoff), *to_ha)])

    def _known_word(self, word: str) -> None:
        if word not in self._require().words:
            raise ValueError(f"unknown word '{word}'")

    # --- training ------------------------------------------------------------------------------
    def start(self, words: list[str], steps: int | None, convert_only: bool,
              negative_weight: float | None = None, learning_rates: list[float] | None = None,
              weights: dict | None = None) -> None:
        for word in words:
            self._known_word(word)
        if steps is not None and not 100 <= steps <= 500_000:
            raise ValueError("steps: 100-500000")
        if negative_weight is not None and not 1 <= negative_weight <= 200:
            raise ValueError("negative weight: 1-200")
        if learning_rates and (len(learning_rates) > 4 or not all(1e-6 <= r <= 0.01 for r in learning_rates)):
            raise ValueError("learning rate: 1-4 values (one per phase) between 0.000001 and 0.01")
        weights = check_weights(weights or {})
        if not convert_only:  # the machine trains on what Prepare made: an edit since would be left out
            household = self._require()
            for word in words:
                changed = changed_since_prepare(household, word)
                if changed:
                    raise ValueError(f"{word}: {', '.join(changed)} changed since Prepare - prepare the word again")
        if self.poll(force=True)["running"]:
            raise RuntimeError("training is already running")
        self.runner().start(words, steps, convert_only, negative_weight, learning_rates or None, weights=weights or None)
        with self.lock:
            self.log.clear()
            self._progress = progress_module.Progress()
            self.started_at = time.time()
            self._polled = 0.0

    def models(self, word: str) -> dict:
        """The kept models of a word on the training machine, scored (card 6: Models)."""
        self._known_word(word)
        return rank_models(self.runner().list_models(word))

    def evaluate_models(self, word: str) -> None:
        """The household test of the word's kept models on the machine (the ones not measured yet)."""
        self._known_word(word)
        if self.poll(force=True)["running"]:
            raise RuntimeError("wait until the training ends")
        self._start_job("evaluate_models", [self.runner().evaluate_command(word)])

    def model_progress(self, word: str, model_id: str) -> dict:
        """The chart and the final test of a kept model, read again from the log kept with it."""
        self._known_word(word)
        if not MODEL_ID_PATTERN.match(model_id) or model_id == "new":
            raise ValueError("not a model id")
        progress = progress_module.parse(self.runner().model_log(word, model_id))
        if word not in progress.words:
            raise ValueError("the kept log has no training of this word")
        return progress.words[word].as_dict()

    def choose_model(self, word: str, model_id: str) -> None:
        """The model the next training of the word starts from (``new``: from scratch)."""
        self._known_word(word)
        if not MODEL_ID_PATTERN.match(model_id):
            raise ValueError("not a model id")
        if self.poll(force=True)["running"]:
            raise RuntimeError("wait until the training ends")
        self.runner().start([word], None, False, base=model_id)
        with self.lock:
            self.log.clear()
            self._progress = progress_module.Progress()
            self.started_at = time.time()
            self._polled = 0.0

    def stop(self) -> None:
        self.runner().stop()
        with self.lock:
            self._polled = 0.0

    def poll(self, force: bool = False) -> dict:
        """Read new log bytes and the GPU state (at most every POLL_SECONDS), outside the lock: nothing else
        (the page, the log) waits for nvidia-smi."""
        with self.lock:
            if not force and time.time() - self._polled < POLL_SECONDS:
                return self._status()
            self._polled = time.time()
            offset = len(self.log)
            runner = self.runner()
        try:
            status = runner.status(offset)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as err:
            with self.lock:
                self.remote_error, self._checked = str(err) or type(err).__name__, True
                return self._status()
        with self.lock:
            self.remote_error, self._checked = None, True
            self.running, self.gpu, self.hf_token = status.running, status.gpu, status.hf_token
            if status.log and len(self.log) == offset:  # a check running at the same time already added it
                self.log.extend(status.log)
                self._progress = progress_module.parse(self.log.decode(errors="replace"))
            return self._status()

    def _status(self) -> dict:
        return {"running": self.running, "gpu": self.gpu, "error": self.remote_error, "hf_token": self.hf_token,
                "checking": not self._checked}

    def refresh_in_background(self) -> None:
        """Ask the machine and Home Assistant in a thread: the page always gets the last known state at once."""
        with self.lock:
            if self._refreshing:
                return
            self._refreshing = True

        def work() -> None:
            try:
                self.poll()
                self.machine()
            except Exception as err:  # noqa: BLE001 - said on the page, never "checking" for ever
                with self.lock:
                    self.remote_error, self._checked = f"{type(err).__name__}: {err}", True
            finally:
                self._refreshing = False

        threading.Thread(target=work, name="machine-check", daemon=True).start()

    # --- state for the page ----------------------------------------------------------------------
    def words(self) -> list[dict]:
        household = self._load()
        if household is None:
            return []
        result = []
        for word in household.words.values():
            folder = build_dir(household, word.id)
            steps = negative_weight = None
            params = folder / "training_parameters.yaml"
            if params.exists():
                try:
                    config = yaml.safe_load(params.read_text(encoding="utf-8"))
                    steps = sum(config.get("training_steps") or [])
                    negative_weight = (config.get("negative_class_weight") or [None])[-1]
                except (yaml.YAMLError, AttributeError, TypeError):
                    steps = negative_weight = None
            # takes on disk per person (quality is checked by `prepare` itself)
            takes = {sid: [len(list_takes(household, word.id, sid)), household.targets.for_group(household.speakers[sid].group)]
                     for sid in word.speakers}
            result.append({"id": word.id, "wake_word": word.wake_word, "speakers": list(word.speakers),
                           "takes": takes, "complete": bool(takes) and all(d >= t for d, t in takes.values()),
                           "prepared": params.exists(), "trained": (folder / TRAINED_MODEL).exists(), "steps": steps,
                           "negative_weight": negative_weight, "model": local_model(folder)})
        return result

    def state(self, language: str | None = None) -> dict:
        self.refresh_in_background()
        with self.lock:
            training = self._status()
        household = self._load()
        # the page may switch the language; default: ui_language of household.yaml
        pack = get_pack(language or (household.ui_language if household else "pl"))
        return {
            "household": {"name": self.household.name, "path": str(self.household), "exists": household is not None},
            "ui": pack.TRAINER,
            "help": pack.TRAINER_HELP,
            "language": pack.__name__.rsplit(".", 1)[-1],
            "languages": list(AVAILABLE),
            "elevenlabs_key": bool(elevenlabs.load_key()),
            "home_assistant": self.home_assistant(),
            "machine": self.machine_cached(),
            "set_weights": {"defaults": DEFAULT_WEIGHTS, "presets": WEIGHT_PRESETS},
            "elevenlabs_account": elevenlabs.account(household) if household else {},
            "elevenlabs_free": list(elevenlabs.FREE_CATEGORIES),
            "words": self.words(),
            "job": self.job.as_dict() if self.job else None,
            "training": {
                **training,
                "started_at": self.started_at,
                "progress": self._progress.as_dict(),
                "log": progress_module.tail(self.log.decode(errors="replace"), 160),
            },
            "good": progress_module.GOOD,
        }

    def home_assistant(self) -> dict:
        """The connection (never the token) and the last pull."""
        connection = ha_sync.load_connection()
        state = ha_sync.read_state(self.household)
        return {"url": connection.url, "token": bool(connection.token), "rejected": ha_sync.token_rejected(),
                "last_pull": state.get("last_pull"),
                "household": state.get("household", ""), "recordings": len(state.get("files", {})),
                "power": asdict(power.load_power())}

    def action(self, data: dict) -> str | None:
        name = data.get("action")
        if name == "check":
            self.check()
        elif name == "prepare":
            self.prepare(list(data.get("words") or []), bool(data.get("force")))
        elif name == "start":
            steps, weight = data.get("steps"), data.get("negative_weight")
            rates = data.get("learning_rates") or []
            self.start(list(data.get("words") or []), int(steps) if steps else None, bool(data.get("convert_only")),
                       float(weight) if weight else None, [float(r) for r in rates], dict(data.get("weights") or {}))
        elif name == "stop":
            self.stop()
        elif name == "evaluate":
            self.evaluate(str(data.get("word", "")))
        elif name == "export":
            self.export(float(data.get("cutoff", 0.97)))
        elif name == "delete_recordings":
            self.delete_recordings([str(x) for x in data.get("paths") or []])
        elif name == "hf_token":
            self.save_hf_token(str(data.get("token", "")))
        elif name == "elevenlabs_key":
            self.save_elevenlabs_key(str(data.get("key", "")))
        elif name == "elevenlabs_add":
            self.elevenlabs_add(str(data.get("voice", "")), str(data.get("language", "")))
        elif name == "elevenlabs_restore":
            self.elevenlabs_restore(str(data.get("voice", "")))
        elif name == "elevenlabs_generate":
            self.elevenlabs_generate([str(w) for w in data.get("words") or []])
        elif name == "ha_connection":
            token = data.get("token")
            self.ha_connection(str(data.get("url", "")), None if token is None else str(token))
        elif name == "ha_pull":
            self.ha_pull()
        elif name == "power_settings":
            self.save_power(data)
        elif name == "machine_off":
            self.switch_machine(False)
        elif name == "evaluate_models":
            self.evaluate_models(str(data.get("word", "")))
        elif name == "choose_model":
            self.choose_model(str(data.get("word", "")), str(data.get("model", "")))
        elif name == "rename_word":
            return self.rename_word(str(data.get("word", "")), str(data.get("new_id", "")))
        else:
            raise ValueError(f"unknown action '{name}'")


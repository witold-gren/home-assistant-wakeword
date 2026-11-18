"""The wake word spoken by ElevenLabs voices: clean takes of the word only (no noise, no reverb).

Runs on this computer (the panel or ``wakeword elevenlabs``), not on the training machine:

- the API key is kept outside the household folder, in ``~/.config/wakeword/elevenlabs.json``
  (only readable by its owner; ``ELEVENLABS_API_KEY`` wins) - the household folder usually lives in
  the Home Assistant configuration and its backups;
- ``sync_voices`` lists the voices of a language - the Voice Library (shared voices with a preview)
  and the account's own voices - into ``data/elevenlabs/voices-<language>.json``;
- ``generate`` reads every spelling of the word ("how it sounds") in the language of each chosen
  voice, ``count`` takes each with a different speed, stability, style and loudness, as 16 kHz mono
  WAV into ``data/elevenlabs/<word>/<voice>_<spelling>/``. A finished group keeps its text in
  ``.complete``; an interrupted one is finished, a changed text is made again.

Background, reverb and negatives come from the public datasets and the household's recordings as
before - the training config adds these takes as their own positive set.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import threading
import time
from pathlib import Path
import re
import shutil
from typing import Callable, Iterable

import numpy as np

from .household import Household
from .recordings import read_index, scan_group, write_index

KEY_FILE = Path.home() / ".config" / "wakeword" / "elevenlabs.json"
ELEVENLABS_DIR = "elevenlabs"
DONE = ".complete"
RATE = 16000
MODELS = ("eleven_multilingual_v2", "eleven_v3", "eleven_flash_v2_5", "eleven_turbo_v2_5")
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_COUNT = 5
MAX_COUNT = 50
MAX_LIBRARY_VOICES = 500
CONCURRENCY = 4  # requests at once (Creator allows 5, Starter 3 - a 429 waits and tries again)
# 409: a library voice is added to the account on its first use - two requests for it at once collide
RETRY_STATUS = (409, 429, 500, 502, 503, 504)
RETRY_WAITS = (2, 5, 10, 20, 40)
# refusals of one voice (e.g. 400 "is not fine-tuned and cannot be used", 404 voice not found):
# that voice is skipped and remembered, the others go on
VOICE_REFUSAL_STATUS = (400, 404)  # seconds before the 2nd ... 6th try
PROGRESS_EVERY = 50
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,}$")
# On the free plan the API speaks only with these voices of the account; Voice Library voices (also
# those added to the account, "professional") answer 402 "Free users cannot use library voices via the API".
FREE_CATEGORIES = ("premade", "cloned", "generated")
FREE_REFUSAL = "Free users cannot use library voices"
VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{8,40}$")


@dataclass(frozen=True)
class Variant:
    """How one take differs: speed 0.7-1.2, stability (lower = livelier), style, loudness."""

    speed: float
    stability: float
    style: float
    gain_db: float


# Take i uses VARIANTS[i % len]: normal, slower, faster, lively, calm, quieter, louder ...
VARIANTS = (
    Variant(1.0, 0.5, 0.0, 0.0),
    Variant(0.85, 0.5, 0.0, 0.0),
    Variant(1.15, 0.5, 0.0, 0.0),
    Variant(1.0, 0.25, 0.4, 0.0),
    Variant(1.0, 0.85, 0.0, 0.0),
    Variant(0.95, 0.4, 0.1, -10.0),
    Variant(1.05, 0.6, 0.0, 4.0),
    Variant(0.8, 0.35, 0.2, 0.0),
    Variant(1.2, 0.7, 0.0, -4.0),
    Variant(0.9, 0.3, 0.5, 2.0),
)


# --- the API key ------------------------------------------------------------------------------


def load_key(file: Path | None = None) -> str:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"].strip()
    file = file or KEY_FILE
    if not file.is_file():
        return ""
    return str(json.loads(file.read_text(encoding="utf-8")).get("api_key") or "")


def save_key(key: str, file: Path | None = None) -> None:
    """Keep the key (empty = remove it); never logged or sent back to the page."""
    file = file or KEY_FILE
    key = key.strip()
    if not key:
        file.unlink(missing_ok=True)
        return
    if not KEY_PATTERN.match(key):
        raise ValueError("this does not look like an ElevenLabs API key")  # the value is never echoed
    file.parent.mkdir(parents=True, exist_ok=True)
    file.touch(mode=0o600)
    file.chmod(0o600)
    file.write_text(json.dumps({"api_key": key}) + "\n", encoding="utf-8")


def client(key: str | None = None):
    from elevenlabs import ElevenLabs

    key = key if key is not None else load_key()
    if not key:
        raise ValueError("no ElevenLabs API key - save it in the panel (card 1 → ElevenLabs)")
    return ElevenLabs(api_key=key)


class ApiError(RuntimeError):
    """An ElevenLabs refusal, explained; ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def voice_refused(err: Exception) -> bool:
    """The refusal is about this voice, not the key, the plan or the service."""
    return getattr(err, "status", None) in VOICE_REFUSAL_STATUS and "voice" in str(err).lower()


def explain(err: Exception) -> str:
    """A short reason from an API error (the body, never the request with the key)."""
    body = getattr(err, "body", None)
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("status")
    status = getattr(err, "status_code", None)
    return f"ElevenLabs {status}: {detail or body or err}" if status else str(err)


# --- voices -------------------------------------------------------------------------------------


def voices_file(household: Household, language: str) -> Path:
    return household.data_dir / ELEVENLABS_DIR / f"voices-{language}.json"


def _verified(voice, language: str) -> list:
    return [v for v in getattr(voice, "verified_languages", None) or [] if getattr(v, "language", None) == language]


def _preview(voice, language: str) -> str | None:
    """A preview in this language (from multilingual v2 when there is one), else the voice's default one."""
    previews = [v for v in _verified(voice, language) if getattr(v, "preview_url", None)]
    previews.sort(key=lambda v: getattr(v, "model_id", "") != DEFAULT_MODEL)
    return previews[0].preview_url if previews else getattr(voice, "preview_url", None)


def _speech(voice, language: str, native: str | None) -> dict:
    """native: the voice's own language; speaks: verified by ElevenLabs in `language`."""
    native = (native or "").split("-")[0].lower()
    verified = bool(_verified(voice, language))
    return {"native": native, "speaks": verified or native == language}


def library_voices(api, language: str, limit: int = MAX_LIBRARY_VOICES) -> list[dict]:
    voices, page = [], 0
    while len(voices) < limit:
        response = api.voices.get_shared(language=language, page_size=100, page=page)
        for voice in response.voices:
            voices.append({
                "id": voice.voice_id, "owner": voice.public_owner_id, "name": voice.name, "source": "library",
                "gender": voice.gender or "", "age": voice.age or "", "accent": voice.accent or "",
                "description": (voice.description or voice.descriptive or "")[:200],
                "preview": _preview(voice, language), "added": bool(getattr(voice, "is_added_by_user", False)),
                **_speech(voice, language, voice.language), "category": "library",
            })
        if not response.has_more:
            break
        page += 1
    return voices[:limit]


def own_voices(api, language: str) -> list[dict]:
    """The account's voices (cloned, generated, added from the library): any may speak the language."""
    voices, token = [], None
    while True:
        response = api.voices.search(page_size=100, next_page_token=token)
        for voice in response.voices:
            labels = voice.labels or {}
            voices.append({
                "id": voice.voice_id, "owner": "", "name": voice.name, "source": "own",
                "gender": labels.get("gender", ""), "age": labels.get("age", ""), "accent": labels.get("accent", ""),
                "description": (voice.description or "")[:200], "preview": _preview(voice, language), "added": True,
                **_speech(voice, language, labels.get("language")), "category": voice.category or "",
            })
        token = getattr(response, "next_page_token", None)
        if not getattr(response, "has_more", False) or not token:
            return voices


def sync_voices(household: Household, language: str, api=None) -> list[dict]:
    """Own voices and the Voice Library of the language - native speakers first; saved for the panel."""
    if not re.fullmatch(r"[a-z]{2,3}", language):
        raise ValueError("language: a code like pl or en")
    api = api or client()
    try:
        voices = own_voices(api, language)
        known = {v["id"] for v in voices}
        voices += [v for v in library_voices(api, language) if v["id"] not in known]
        # native speakers of the language, then voices verified in it, then the rest (e.g. English premade)
        voices.sort(key=lambda v: (v["native"] != language, not v["speaks"]))
    except Exception as err:  # noqa: BLE001 - the API's own errors, shown in the panel
        raise RuntimeError(explain(err)) from err
    read_plan(household, api)
    file = voices_file(household, language)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(voices, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return voices


def account_file(household: Household) -> Path:
    return household.data_dir / ELEVENLABS_DIR / "account.json"


def account(household: Household) -> dict:
    """What is known about the plan: {"tier": "free" | ..., "used", "limit"} (empty: not known)."""
    file = account_file(household)
    return json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}


def remember_account(household: Household, **info) -> None:
    file = account_file(household)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({**account(household), **info}) + "\n", encoding="utf-8")


def read_plan(household: Household, api) -> None:
    """The plan and the characters left, if the key may read them (permission user_read)."""
    try:
        subscription = api.user.subscription.get()
    except Exception:  # noqa: BLE001 - the key without user_read: learnt from a refusal instead
        return
    remember_account(household, tier=str(subscription.tier), used=subscription.character_count,
                     limit=subscription.character_limit)


def learn_from(household: Household, err: Exception) -> None:
    """A 402 for a library voice means the free plan."""
    if FREE_REFUSAL in str(err):
        remember_account(household, tier="free")


def broken_voices(household: Household) -> dict[str, dict]:
    """Voices ElevenLabs refused to speak with: {voice id: {"name", "reason"}} - listed apart in the panel."""
    return account(household).get("broken", {})


def remember_broken(household: Household, voice_id: str, reason: str, name: str = "") -> None:
    remember_account(household, broken={**broken_voices(household), voice_id: {"name": name, "reason": reason}})


def forget_broken(household: Household, voice_id: str) -> None:
    """Back in the list (e.g. the voice was fine-tuned since)."""
    remember_account(household, broken={k: v for k, v in broken_voices(household).items() if k != voice_id})


def learn_paid(household: Household, voice_id: str, language: str) -> None:
    """A voice that spoke: not broken (any more); a library one: the plan is not (or no longer) the free one."""
    if voice_id in broken_voices(household):
        forget_broken(household, voice_id)
    voice = next((v for v in cached_voices(household, language) if v["id"] == voice_id), None)
    if voice and voice.get("category") not in FREE_CATEGORIES and account(household).get("tier") == "free":
        remember_account(household, tier="paid")


def cached_voices(household: Household, language: str) -> list[dict]:
    file = voices_file(household, language)
    return json.loads(file.read_text(encoding="utf-8")) if file.is_file() else []


def add_to_account(voice: dict, api=None) -> str:
    """Add a Voice Library voice to "My Voices" (uses a voice slot of the account)."""
    api = api or client()
    try:
        return api.voices.share(voice["owner"], voice["id"], new_name=voice["name"][:80]).voice_id
    except Exception as err:  # noqa: BLE001
        raise RuntimeError(explain(err)) from err


# --- speech -------------------------------------------------------------------------------------


def texts_for(household: Household, word: str, language: str) -> tuple[str, ...]:
    """The spellings ("how it sounds") of the word in a language."""
    texts = household.words[word].spellings.get(language, ())
    if not texts:
        raise ValueError(f"'{word}' has no spelling in '{language}' - add one in the Words tab")
    return texts


def speak(api, voice_id: str, text: str, model: str, variant: Variant, seed: int,
          language: str | None = None) -> np.ndarray:
    """One take as 16 kHz float samples (-1..1), loudness of the variant applied."""
    from elevenlabs import VoiceSettings

    # multilingual_v2 recognises the language by itself and refuses language_code
    options = {"language_code": language} if language and model != "eleven_multilingual_v2" else {}
    for wait in (*RETRY_WAITS, None):
        try:
            audio = b"".join(api.text_to_speech.convert(
                voice_id, text=text, model_id=model, output_format="pcm_16000", seed=seed,
                voice_settings=VoiceSettings(stability=variant.stability, similarity_boost=0.75, style=variant.style,
                                             speed=variant.speed, use_speaker_boost=True),
                **options))
            break
        except Exception as err:  # noqa: BLE001
            # too many requests at once or a hiccup of the service: wait and try again
            status = getattr(err, "status_code", None)
            if wait is None or status not in RETRY_STATUS:
                raise ApiError(explain(err), status) from err
            time.sleep(wait)
    samples = np.frombuffer(audio[: len(audio) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
    samples *= 10 ** (variant.gain_db / 20)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    return samples / peak * 0.98 if peak > 0.98 else samples


def wav_bytes(samples: np.ndarray) -> bytes:
    import io

    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, samples, RATE, subtype="PCM_16", format="WAV")
    return buffer.getvalue()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "voice"


def group_dir(household: Household, word: str, voice: dict, index: int) -> Path:
    return household.data_dir / ELEVENLABS_DIR / word / f"{slug(voice['name'])}-{voice['id'][:8]}_{index:02d}"


def plan(household: Household, word: str) -> list[tuple[dict, str, str, Path]]:
    """(voice, language, text, folder) for every chosen voice and spelling of its language."""
    jobs = []
    for voice in household.elevenlabs.get("voices", []):
        texts = household.words[word].spellings.get(voice["language"], ())
        for index, text in enumerate(texts):
            jobs.append((voice, voice["language"], text, group_dir(household, word, voice, index)))
    return jobs


def generate(household: Household, word: str, api=None, log: Callable[[str], None] = print) -> int:
    """Make the missing takes of every chosen voice (CONCURRENCY at once); returns how many were made now."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import soundfile as sf

    jobs = plan(household, word)
    drop_stale(household, word, log)
    if not jobs:
        log(f"{word}: no ElevenLabs voices chosen for its languages - nothing to do")
        return 0
    settings = household.elevenlabs
    model, count = settings.get("model", DEFAULT_MODEL), int(settings.get("count", DEFAULT_COUNT))
    api = api or client()
    broken = broken_voices(household)
    for voice in {v["id"]: v for v, *_ in jobs if v["id"] in broken}.values():
        log(f"skipped, ElevenLabs refused this voice before: {voice['name']} ({broken[voice['id']]['reason']})")
    jobs = [job for job in jobs if job[0]["id"] not in broken]
    base = household.data_dir / ELEVENLABS_DIR / word
    base.mkdir(parents=True, exist_ok=True)
    # the list of takes for the panel, kept as they are made (see recordings.INDEX)
    old_index = read_index(base) or {}
    index: dict[str, dict[str, float]] = {}

    # what is missing: whole groups whose text, model or count changed, takes of interrupted ones
    tasks, groups, skipped = [], [], 0
    for voice, language, text, folder in jobs:
        stamp = f"{model}|{count}|{text}"
        if (folder / DONE).is_file() and (folder / DONE).read_text(encoding="utf-8") == stamp:
            skipped += 1
            index[folder.name] = old_index.get(folder.name) or scan_group(folder)
            continue
        if (folder / DONE).is_file():
            for old in folder.glob("*.wav"):
                old.unlink()
            (folder / DONE).unlink()
        folder.mkdir(parents=True, exist_ok=True)
        index[folder.name] = scan_group(folder)  # takes of an interrupted run
        groups.append((folder, stamp))
        tasks += [(voice, language, text, folder, i) for i in range(count) if not (folder / f"{i:05d}.wav").is_file()]
    tasks = interleave(tasks)
    log(f"{word}: {len(jobs)} groups ({len(jobs) - skipped} to make, {skipped} already complete), "
        f"{len(tasks)} takes with {CONCURRENCY} requests at once")

    refused: dict[str, str] = {}  # voice id → reason, found during this run

    def make(task) -> bool:
        voice, language, text, folder, i = task
        if voice["id"] in refused:
            return False
        samples = speak(api, voice["id"], text, model, VARIANTS[i % len(VARIANTS)], seed=i + 1, language=language)
        tmp = folder / f".{i:05d}.wav"
        sf.write(tmp, samples, RATE, subtype="PCM_16")
        tmp.rename(folder / f"{i:05d}.wav")
        index[folder.name][f"{i:05d}.wav"] = round(len(samples) / RATE, 2)
        return True

    made, lock, started = 0, threading.Lock(), time.time()
    try:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {pool.submit(make, task): task for task in tasks}
            for future in as_completed(futures):
                voice, language, text = futures[future][:3]
                try:
                    if not future.result():
                        continue
                except RuntimeError as err:
                    if voice_refused(err):  # this voice only: the others go on
                        if voice["id"] not in refused:  # results are read here, in one thread
                            refused[voice["id"]] = str(err)
                            remember_broken(household, voice["id"], str(err), voice["name"])
                            log(f"  skipping {voice['name']}: {err}")
                        continue
                    pool.shutdown(cancel_futures=True)  # the takes made so far stay: a next run resumes
                    learn_from(household, err)
                    raise RuntimeError(f"{voice['name']} '{text}': {err}") from err
                with lock:
                    made += 1
                    if made % PROGRESS_EVERY == 0 or made == len(tasks):
                        left = (time.time() - started) / made * (len(tasks) - made)
                        log(f"  {made}/{len(tasks)} takes, {time.time() - started:.0f} s, about {left:.0f} s left")
        by_folder = {folder: voice["id"] for voice, _, _, folder in jobs}
        for folder, stamp in groups:
            if by_folder[folder] in refused:  # nothing usable from that voice: not kept for training
                shutil.rmtree(folder, ignore_errors=True)
                index.pop(folder.name, None)
            else:
                (folder / DONE).write_text(stamp, encoding="utf-8")
    finally:  # an interrupted run too: the takes made so far are listed in the panel
        write_index(base, index)
    chosen = {voice["id"] for voice, *_ in plan(household, word)}
    usable = {voice["id"] for voice, *_ in jobs} - set(refused)
    log(f"ElevenLabs takes for {word} are ready: {len(jobs)} groups, {made} made now; "
        f"voices with takes: {len(usable)} of {len(chosen)} chosen, {len(chosen) - len(usable)} skipped")
    if refused:
        log(f"{len(refused)} voices skipped - ElevenLabs refused them (marked in the ElevenLabs tab, "
            "untick them there):")
        names = {voice["id"]: voice["name"] for voice, *_ in jobs}
        for voice_id, reason in refused.items():
            log(f"  {names[voice_id]}: {reason}")
    return made


def takes_summary(household: Household, word: str) -> tuple[int, int] | None:
    """(takes, voices) of the word from the list kept by generate() - None when there are none."""
    index = read_index(household.data_dir / ELEVENLABS_DIR / word)
    if not index:
        return None
    takes = sum(len(files) for files in index.values())
    voices = {re.sub(r"_\d+$", "", group) for group, files in index.items() if files}
    return (takes, len(voices)) if takes else None


def interleave(tasks: list[tuple]) -> list[tuple]:
    """One take of every voice in turn: requests made at once go to different voices (no 409)."""
    by_voice: dict[str, list[tuple]] = {}
    for task in tasks:
        by_voice.setdefault(task[0]["id"], []).append(task)
    queues = list(by_voice.values())
    return [queue[i] for i in range(max(map(len, queues), default=0)) for queue in queues if i < len(queue)]


def drop_stale(household: Household, word: str, log: Callable[[str], None] = print) -> list[Path]:
    """Takes of voices, languages or spellings no longer chosen out of training (also run by Prepare)."""
    stale = _stale_groups(household, word, {folder for *_, folder in plan(household, word)})
    for folder in stale:
        log(f"{word}: ElevenLabs takes no longer chosen, moved to data/backup: {folder.name}")
    return stale


def _stale_groups(household: Household, word: str, keep: Iterable[Path]) -> list[Path]:
    """Groups of voices or spellings no longer chosen go to data/backup (they would still be trained on)."""

    base = household.data_dir / ELEVENLABS_DIR / word
    keep = set(keep)
    stale = [p for p in sorted(base.iterdir()) if p.is_dir() and p not in keep] if base.is_dir() else []
    if stale:
        target = household.data_dir / "backup" / f"elevenlabs-{time.strftime('%Y%m%d-%H%M%S')}" / word
        target.mkdir(parents=True, exist_ok=True)
        for folder in stale:
            shutil.move(str(folder), target / folder.name)
    return stale


def estimate(household: Household, word: str) -> dict:
    """What a generation costs: takes and characters (ElevenLabs bills characters)."""
    count = int(household.elevenlabs.get("count", DEFAULT_COUNT))
    broken = broken_voices(household)
    jobs = [job for job in plan(household, word) if job[0]["id"] not in broken]
    return {"groups": len(jobs), "takes": len(jobs) * count, "characters": sum(len(t) for _, _, t, _ in jobs) * count}

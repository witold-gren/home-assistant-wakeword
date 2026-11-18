"""The household file: people, wake words and which word runs on which device.

A household lives in ``households/<name>/household.yaml``; recordings and generated data in
``households/<name>/data/`` (git-ignored). Every word is trained on the recordings of everyone who
uses it; the household's other words become negatives of each word.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

HOUSEHOLD_FILE = "household.yaml"
GROUPS = ("adult", "child")
# Wake words that ship with ESPHome / Home Assistant Voice and may be used on devices as they are.
STOCK_WORDS = {"okay_nabu", "hey_jarvis", "hey_mycroft", "alexa"}
# Home Assistant Voice PE has two assistant slots, each with one wake word.
MAX_WORDS_PER_DEVICE = 2
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
DEVICE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# A Piper voice: "pl_PL-gosia-medium" (rhasspy/piper-voices) or "<owner>/<repo>/<voice>" on Hugging Face.
VOICE_PATTERN = re.compile(r"^(?:[A-Za-z0-9][\w.-]*/[\w.-]+/)?[A-Za-z0-9][\w.-]*$")


class HouseholdError(ValueError):
    """The household file is invalid; the message says what to fix."""


@dataclass(frozen=True)
class Speaker:
    id: str
    group: str  # adult | child


@dataclass(frozen=True)
class Word:
    id: str
    wake_word: str
    trained_languages: tuple[str, ...]
    speakers: tuple[str, ...]  # speaker ids who record and use the word
    spellings: dict[str, tuple[str, ...]]  # TTS language -> texts to synthesise
    sound_alikes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Targets:
    adult: int = 12
    child: int = 18
    held_out: int = 3

    def for_group(self, group: str) -> int:
        return self.child if group == "child" else self.adult


@dataclass
class Household:
    root: Path
    ui_language: str
    speakers: dict[str, Speaker]
    words: dict[str, Word]
    targets: Targets
    devices: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Piper voices per language for the synthetic speech; a language missing here uses the defaults,
    # an empty list means no Piper voices (English still has the multi-speaker generator)
    voices: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # ElevenLabs takes of the words: {"model", "count", "voices": [{"id", "name", "language", "owner"}]}
    elevenlabs: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    def real_dir(self, word: str, speaker: str | None = None) -> Path:
        """Where the recordings of `word` (by `speaker`) are kept."""
        path = self.data_dir / "real" / word
        return path / speaker if speaker else path

    def words_for(self, speaker: str) -> list[Word]:
        """Words `speaker` has to record, in file order."""
        return [w for w in self.words.values() if speaker in w.speakers]

    def other_words(self, word: str) -> list[Word]:
        """The household's other words — negatives when training `word`."""
        return [w for w in self.words.values() if w.id != word]


def _require(data: dict[str, Any], key: str, where: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise HouseholdError(f"{where}: missing '{key}'")
    return data[key]


def _texts(value: Any, where: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise HouseholdError(f"{where}: expected a list of texts")
    return tuple(v.strip() for v in value)


def parse_household(data: dict[str, Any], root: Path, require_words: bool = True) -> Household:
    """Validate the parsed YAML and build a Household (`require_words=False` while setting up)."""
    if not isinstance(data, dict):
        raise HouseholdError("household.yaml: expected a mapping at the top level")

    speakers: dict[str, Speaker] = {}
    for i, raw in enumerate(_require(data, "speakers", "household") or []):
        where = f"speakers[{i}]"
        if not isinstance(raw, dict):
            raise HouseholdError(f"{where}: expected id and group")
        sid = str(_require(raw, "id", where))
        group = str(raw.get("group", "adult"))
        if not ID_PATTERN.match(sid):
            raise HouseholdError(f"{where}: id '{sid}' — use lowercase letters, digits and _")
        if group not in GROUPS:
            raise HouseholdError(f"{where}: group '{group}' — use one of {', '.join(GROUPS)}")
        if sid in speakers:
            raise HouseholdError(f"{where}: duplicate speaker '{sid}'")
        speakers[sid] = Speaker(sid, group)
    if not speakers:
        raise HouseholdError("household: add at least one speaker")

    words: dict[str, Word] = {}
    raw_words = _require(data, "words", "household") if require_words else (data.get("words") or {})
    if not isinstance(raw_words, dict):
        raise HouseholdError("words: expected a mapping of word id -> settings")
    for wid, raw in raw_words.items():
        where = f"words.{wid}"
        wid = str(wid)
        if not ID_PATTERN.match(wid):
            raise HouseholdError(f"{where}: id — use lowercase letters, digits and _")
        if wid in STOCK_WORDS:
            raise HouseholdError(f"{where}: '{wid}' is a stock model name, pick another id")
        if not isinstance(raw, dict):
            raise HouseholdError(f"{where}: expected settings")
        who = raw.get("speakers", "all")
        if who == "all":
            who_ids = tuple(speakers)
        else:
            who_ids = _texts(who, f"{where}.speakers")
            unknown = [s for s in who_ids if s not in speakers]
            if unknown:
                raise HouseholdError(f"{where}.speakers: unknown speaker(s) {', '.join(unknown)}")
        spellings_raw = _require(raw, "spellings", where)
        if not isinstance(spellings_raw, dict) or not spellings_raw:
            raise HouseholdError(f"{where}.spellings: expected language -> list of texts")
        spellings = {
            str(lang): _texts(texts, f"{where}.spellings.{lang}")
            for lang, texts in spellings_raw.items()
        }
        languages = _texts(raw.get("trained_languages", list(spellings)[:1]), f"{where}.trained_languages")
        words[wid] = Word(
            id=wid,
            wake_word=str(_require(raw, "wake_word", where)),
            trained_languages=languages,
            speakers=who_ids,
            spellings=spellings,
            sound_alikes=_texts(raw.get("sound_alikes", []) or [], f"{where}.sound_alikes")
            if raw.get("sound_alikes")
            else (),
        )
    if not words and require_words:
        raise HouseholdError("household: add at least one word")

    raw_targets = data.get("targets") or {}
    try:
        targets = Targets(
            adult=int(raw_targets.get("adult", Targets.adult)),
            child=int(raw_targets.get("child", Targets.child)),
            held_out=int(raw_targets.get("held_out", Targets.held_out)),
        )
    except (TypeError, ValueError) as err:
        raise HouseholdError(f"targets: {err}") from err
    if min(targets.adult, targets.child) <= targets.held_out:
        raise HouseholdError("targets: held_out must be smaller than the takes per person")

    devices: dict[str, tuple[str, ...]] = {}
    for device, assigned in (data.get("devices") or {}).items():
        device = str(device)
        where = f"devices.{device}"
        if not DEVICE_PATTERN.match(device):
            raise HouseholdError(f"{where}: use the ESPHome device name (lowercase, -, _)")
        ids = _texts(assigned, where)
        if len(ids) > MAX_WORDS_PER_DEVICE:
            raise HouseholdError(
                f"{where}: at most {MAX_WORDS_PER_DEVICE} wake words (Voice PE has two slots)"
            )
        unknown = [w for w in ids if w not in words and w not in STOCK_WORDS]
        if unknown:
            raise HouseholdError(f"{where}: unknown word(s) {', '.join(unknown)}")
        devices[device] = ids

    voices: dict[str, tuple[str, ...]] = {}
    for language, listed in (data.get("voices") or {}).items():
        where = f"voices.{language}"
        names = _texts(listed, where) if listed else ()
        wrong = [v for v in names if not VOICE_PATTERN.match(v)]
        if wrong:
            raise HouseholdError(f"{where}: not a Piper voice: {', '.join(wrong)} "
                                 "(e.g. pl_PL-gosia-medium or WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium)")
        voices[str(language)] = names

    elevenlabs = _elevenlabs(data.get("elevenlabs") or {})

    return Household(
        root=root,
        ui_language=str(data.get("ui_language", "en")),
        speakers=speakers,
        words=words,
        targets=targets,
        devices=devices,
        voices=voices,
        elevenlabs=elevenlabs,
    )


def _elevenlabs(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HouseholdError("elevenlabs: expected a mapping (model, count, voices)")
    model = str(raw.get("model") or "eleven_multilingual_v2")
    try:
        count = int(raw.get("count", 5))
    except (TypeError, ValueError) as err:
        raise HouseholdError("elevenlabs.count: a number of takes per spelling") from err
    if not 1 <= count <= 50:
        raise HouseholdError("elevenlabs.count: 1-50 takes per spelling")
    voices = []
    for index, voice in enumerate(raw.get("voices") or []):
        where = f"elevenlabs.voices[{index}]"
        if not isinstance(voice, dict) or not re.fullmatch(r"[A-Za-z0-9]{8,40}", str(voice.get("id", ""))):
            raise HouseholdError(f"{where}: needs the voice id")
        if not re.fullmatch(r"[a-z]{2,3}", str(voice.get("language", ""))):
            raise HouseholdError(f"{where}: needs the language (e.g. pl) whose spellings it reads")
        voices.append({"id": str(voice["id"]), "name": str(voice.get("name") or voice["id"])[:80],
                       "language": str(voice["language"]), "owner": str(voice.get("owner") or "")})
    return {"model": model, "count": count, "voices": voices} if raw else {}


def load_household(path: Path | str, require_words: bool = True) -> Household:
    """Load `household.yaml` from a household directory (or the file itself)."""
    path = Path(path)
    file = path / HOUSEHOLD_FILE if path.is_dir() else path
    if not file.exists():
        raise HouseholdError(
            f"no household.yaml in {file.parent.resolve()} — create one with `wakeword init`, "
            "or point to an existing one with -H <folder> or WAKEWORD_HOUSEHOLD=<folder>"
        )
    with file.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return parse_household(data, file.parent, require_words)

"""Create a household and add people and words without editing YAML by hand."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import yaml

from .household import HOUSEHOLD_FILE, Household, HouseholdError, parse_household

TEMPLATE = """\
# Household for training wake words — see docs/en/02-plan-your-household.md
ui_language: {ui_language}   # language of the recorder (en, pl …)

speakers:                # everyone who will say a wake word; group: adult | child
{speakers}

words: {{}}               # add words with: wakeword add-word

targets:
  adult: 12              # takes per adult per word
  child: 18              # children's voices vary more — more takes
  held_out: 3            # takes per person kept aside for testing

devices: {{}}             # ESPHome device name: [up to 2 words]
"""


def init_household(root: Path, speakers: list[tuple[str, str]], ui_language: str = "en") -> Path:
    """Create `root/household.yaml` with the given (id, group) speakers."""
    root = Path(root)
    file = root / HOUSEHOLD_FILE
    if file.exists():
        raise HouseholdError(f"{file} already exists")
    if not speakers:
        raise HouseholdError("add at least one speaker (--speaker id:group)")
    lines = "\n".join(f"  - id: {sid}\n    group: {group}" for sid, group in speakers)
    text = TEMPLATE.format(ui_language=ui_language, speakers=lines)
    # Validate before writing; words are added later.
    data = yaml.safe_load(text)
    parse_household(data, root, require_words=False)
    root.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# Recordings stay at home\ndata/\n", encoding="utf-8")
    return file


def _update(root: Path, change) -> Household:
    """Apply `change(data)` to the YAML, validate, back up the old file and save."""
    file = Path(root) / HOUSEHOLD_FILE if Path(root).is_dir() else Path(root)
    if not file.exists():
        raise HouseholdError(f"{file}: not found — run `wakeword init` first")
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    change(data)
    household = parse_household(data, file.parent, require_words=False)
    shutil.copyfile(file, file.with_suffix(".yaml.bak"))
    file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return household


def add_speaker(root: Path, sid: str, group: str = "adult", words: list[str] | None = None) -> Household:
    """Add a speaker; `words` adds them to those words' speaker lists."""

    def change(data):
        data.setdefault("speakers", []).append({"id": sid, "group": group})
        for wid in words or []:
            entry = (data.get("words") or {}).get(wid)
            if entry is None:
                raise HouseholdError(f"unknown word '{wid}'")
            if entry.get("speakers", "all") != "all":
                entry["speakers"] = [*entry["speakers"], sid]

    return _update(root, change)


def add_word(root: Path, wid: str, wake_word: str, spellings: dict[str, list[str]],
             speakers: list[str] | None = None, trained_languages: list[str] | None = None,
             sound_alikes: list[str] | None = None) -> Household:
    """Add a word (speakers default to everyone)."""

    def change(data):
        words = data.get("words") or {}
        if wid in words:
            raise HouseholdError(f"word '{wid}' already exists")
        entry: dict[str, Any] = {"wake_word": wake_word}
        if trained_languages:
            entry["trained_languages"] = trained_languages
        entry["speakers"] = speakers or "all"
        entry["spellings"] = spellings
        if sound_alikes:
            entry["sound_alikes"] = sound_alikes
        words[wid] = entry
        data["words"] = words

    return _update(root, change)


def set_device(root: Path, device: str, words: list[str]) -> Household:
    """Assign up to two words to an ESPHome device."""

    def change(data):
        devices = data.get("devices") or {}
        devices[device] = words
        data["devices"] = devices

    return _update(root, change)


VOICE_MARKERS = ("home-assistant-voice", "voice_assistant:", "micro_wake_word:")


def esphome_devices(folder: Path) -> list[dict[str, str]]:
    """Voice devices configured in an ESPHome folder (usually /config/esphome next to the household).

    The device name comes from the YAML (`substitutions: name:` or `esphome: name:`), which can
    differ from the file name - e.g. home-assistant-voice-1a2b3c.yaml holds salon-ha-voice.
    Read as text, so `!secret` tags and packages need no resolving.
    """
    import re

    devices = []
    for path in sorted(Path(folder).glob("*.yaml")) if Path(folder).is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(marker in text for marker in VOICE_MARKERS):
            continue
        found = {}
        for key in ("name", "friendly_name"):
            for match in re.finditer(rf"^\s+{key}:\s*[\"']?([^\"'\n#]+?)[\"']?\s*(?:#.*)?$", text, re.MULTILINE):
                if "${" not in match.group(1):
                    found[key] = match.group(1).strip()
                    break
        name = found.get("name", path.stem)
        devices.append({"name": name, "friendly_name": found.get("friendly_name", name), "file": path.name})
    return devices


# --- whole-file editing (the training panel) ---------------------------------------------------

POLISH = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def word_id(wake_word: str) -> str:
    """A file-safe id for a wake word: "Dżarwis" -> "dzarwis", "Optimus Prime" -> "optimus_prime"."""
    import re
    import unicodedata

    text = wake_word.translate(POLISH)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "word"


def read_raw(root: Path) -> dict[str, Any]:
    """household.yaml as plain data with every optional part filled in (for editing)."""
    file = Path(root) / HOUSEHOLD_FILE
    if not file.exists():
        raise HouseholdError(f"{file}: not found — run `wakeword init` first")
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    words = {}
    for wid, raw in (data.get("words") or {}).items():
        raw = raw or {}
        spellings = {lang: ([texts] if isinstance(texts, str) else list(texts or []))
                     for lang, texts in (raw.get("spellings") or {}).items()}
        speakers = raw.get("speakers", "all")
        words[str(wid)] = {
            "wake_word": raw.get("wake_word", wid),
            "trained_languages": list(raw.get("trained_languages") or list(spellings)[:1]),
            "speakers": "all" if speakers == "all" else ([speakers] if isinstance(speakers, str) else list(speakers)),
            "spellings": spellings,
            "sound_alikes": list(raw.get("sound_alikes") or []),
        }
    targets = {"adult": 12, "child": 18, "held_out": 3, **(data.get("targets") or {})}
    devices = {str(d): ([w] if isinstance(w, str) else list(w or [])) for d, w in (data.get("devices") or {}).items()}
    return {
        "ui_language": data.get("ui_language", "en"),
        "speakers": [{"id": str(s.get("id")), "group": s.get("group", "adult")} for s in data.get("speakers") or []],
        "words": words,
        "targets": targets,
        "devices": devices,
        "voices": {str(lang): list(v or []) for lang, v in (data.get("voices") or {}).items()},
        "elevenlabs": dict(data.get("elevenlabs") or {}),
    }


def save_raw(root: Path, data: dict[str, Any]) -> Household:
    """Validate and write a whole household (previous version kept as household.yaml.bak)."""
    file = Path(root) / HOUSEHOLD_FILE
    clean = {
        "ui_language": str(data.get("ui_language") or "en"),
        "speakers": [{"id": str(s["id"]).strip(), "group": s.get("group", "adult")} for s in data.get("speakers") or []],
        "words": {},
        "targets": {k: int(v) for k, v in (data.get("targets") or {}).items() if k in ("adult", "child", "held_out")},
        "devices": {},
    }
    for wid, raw in (data.get("words") or {}).items():
        entry: dict[str, Any] = {"wake_word": str(raw.get("wake_word") or wid).strip()}
        if raw.get("trained_languages"):
            entry["trained_languages"] = [str(x) for x in raw["trained_languages"]]
        speakers = raw.get("speakers", "all")
        entry["speakers"] = "all" if speakers == "all" else [str(s) for s in speakers]
        entry["spellings"] = {str(lang): [t.strip() for t in texts if str(t).strip()]
                              for lang, texts in (raw.get("spellings") or {}).items()
                              if [t for t in texts if str(t).strip()]}
        sound_alikes = [s.strip() for s in raw.get("sound_alikes") or [] if str(s).strip()]
        if sound_alikes:
            entry["sound_alikes"] = sound_alikes
        clean["words"][str(wid).strip()] = entry
    for device, words in (data.get("devices") or {}).items():
        words = [w for w in words if w]
        if str(device).strip() and words:
            clean["devices"][str(device).strip()] = words
    # an empty list is kept: "no Piper voices for this language" (missing = the default voices)
    voices = {str(lang).strip(): list(dict.fromkeys(str(v).strip() for v in listed or [] if str(v).strip()))
              for lang, listed in (data.get("voices") or {}).items() if str(lang).strip()}
    if voices:
        clean["voices"] = voices
    elevenlabs = data.get("elevenlabs") or {}
    # written only once something differs from the defaults (no voices, multilingual v2, 5 takes)
    if (elevenlabs.get("voices") or elevenlabs.get("model") not in (None, "", "eleven_multilingual_v2")
            or int(elevenlabs.get("count") or 5) != 5):
        clean["elevenlabs"] = {"model": str(elevenlabs.get("model") or "eleven_multilingual_v2"),
                               "count": int(elevenlabs.get("count") or 5),
                               "voices": [{k: str(v.get(k) or "") for k in ("id", "name", "language", "owner")}
                                          for v in elevenlabs.get("voices") or []]}
    household = parse_household(clean, file.parent, require_words=False)
    if file.exists():
        shutil.copyfile(file, file.with_suffix(".yaml.bak"))
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("# Wake word household - edited in the wake word studio\n"
                    + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return household


# what `prepare`, `preview` and the training derive from a word - rebuilt after a rename
DERIVED = ("expanded/{id}", "splits/{id}.csv", "preview/{id}")
# kept under the new id: ElevenLabs takes (paid for) and the build with its trained and kept models
# and the synthetic speech (made on the training machine: when the panel runs there)
RENAMED = ("elevenlabs/{id}", "build/{id}", "synthetic/{id}")
# what Prepare writes into the build: paths with the old id inside - the word is prepared again
PREPARE_FILES = ("features.json", "training_parameters.yaml", "synthetic.sh", "prepared.json")


def rename_word(root: Path, old: str, new: str) -> Household:
    """Change a word's id: household.yaml, devices, the recordings folder and recordings.csv.

    ElevenLabs takes and the build (trained and kept models) follow the new id; the files Prepare
    writes and the other prepared data (expanded, splits, preview) go to data/backup/ - prepare again.
    The display name (`wake_word`) is not touched; it can be edited freely without this.
    """
    import csv
    import io
    import time

    from .household import ID_PATTERN

    root = Path(root)
    data = read_raw(root)
    if old not in data["words"]:
        raise HouseholdError(f"unknown word '{old}'")
    if not ID_PATTERN.match(new):
        raise HouseholdError(f"'{new}': use lowercase letters, digits and _")
    if new in data["words"]:
        raise HouseholdError(f"word '{new}' already exists")
    data_dir = root / "data"
    for folder in ("real/{id}", *RENAMED):
        if (data_dir / folder.format(id=new)).exists():
            raise HouseholdError(f"data/{folder.format(id=new)} already exists — move it away first")

    data["words"] = {(new if wid == old else wid): word for wid, word in data["words"].items()}
    data["devices"] = {d: [new if w == old else w for w in words] for d, words in data["devices"].items()}
    household = save_raw(root, data)

    if (data_dir / "real" / old).exists():
        (data_dir / "real" / old).rename(data_dir / "real" / new)
    log = data_dir / "real" / "recordings.csv"
    if log.exists():
        rows = list(csv.reader(io.StringIO(log.read_text(encoding="utf-8"))))
        prefix_old, prefix_new = f"data/real/{old}/", f"data/real/{new}/"
        for row in rows[1:]:
            if len(row) >= 3 and row[2] == old:
                row[2] = new
                if row[1].startswith(prefix_old):
                    row[1] = prefix_new + row[1].removeprefix(prefix_old)
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerows(rows)
        log.write_text(out.getvalue(), encoding="utf-8")

    backup = data_dir / "backup" / f"renamed-{old}-{time.strftime('%Y%m%d-%H%M%S')}"
    moved = [pattern.format(id=old) for pattern in DERIVED]
    moved += [f"build/{old}/{name}" for name in PREPARE_FILES]
    for relative in moved:
        path = data_dir / relative
        if path.exists():
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
    for pattern in RENAMED:
        if (data_dir / pattern.format(id=old)).exists():
            (data_dir / pattern.format(id=old)).rename(data_dir / pattern.format(id=new))
    return household

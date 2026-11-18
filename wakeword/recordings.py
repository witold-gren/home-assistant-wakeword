"""Browse and delete the household's recordings (the training panel's "Recordings" tab).

Files are addressed by their path inside ``data/``: ``real/<word>/<speaker>/<file>.wav`` for
wake word takes, ``background/<file>.wav`` for home background and
``build/<word>/synthetic_preview/<positive|negative>/<file>.wav`` for a few synthetic clips brought
back from the training machine (listen only). Deleting moves them to
``data/backup/deleted-<time>/`` so a mistake can be undone by moving them back.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import shutil
import time

import soundfile as sf

from .augment import BACKGROUND_DIR
from .dataset import parse_take

REAL_DIR = "real"
AREAS = (REAL_DIR, BACKGROUND_DIR)
PREVIEW_DIR = "synthetic_preview"  # train/synth_preview.py
PREVIEW_KINDS = ("positive", "negative")
ELEVENLABS_DIR = "elevenlabs"  # wakeword/elevenlabs.py: data/elevenlabs/<word>/<voice>_<spelling>/


WAV_HEADER = 44  # soundfile's header of a plain 16-bit PCM WAV
PCM_BYTES_PER_SECOND = 16000 * 2  # 16 kHz mono 16-bit, as wakeword/elevenlabs.py writes them


def _describe(path: Path, data_dir: Path, pcm16k: bool = False) -> dict:
    """``pcm16k``: a file this project wrote - the length from its size, without opening it
    (thousands of ElevenLabs takes on the Home Assistant share took long to read one by one)."""
    stat = path.stat()
    if pcm16k:
        seconds = round(max(stat.st_size - WAV_HEADER, 0) / PCM_BYTES_PER_SECOND, 2)
    else:
        try:
            seconds = round(sf.info(str(path)).duration, 2)
        except (RuntimeError, OSError):  # unreadable file - still listed so it can be removed
            seconds = None
    return {
        "path": path.relative_to(data_dir).as_posix(),
        "name": path.name,
        "seconds": seconds,
        "size": stat.st_size,
        "time": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def list_recordings(root: Path) -> dict:
    """Every take on disk grouped by word and speaker (also words/people no longer in the household)."""
    data_dir = Path(root) / "data"
    groups = []
    real = data_dir / REAL_DIR
    for word_dir in sorted(p for p in real.iterdir() if p.is_dir()) if real.is_dir() else []:
        for speaker_dir in sorted(p for p in word_dir.iterdir() if p.is_dir()):
            files = []
            for path in sorted(speaker_dir.glob("*.wav")):
                take = parse_take(path)
                files.append({**_describe(path, data_dir), "variant": take.variant if take else None,
                              "index": take.index if take else None})
            if files:
                files.sort(key=lambda f: (f["index"] is None, f["index"] or 0, f["name"]))
                groups.append({"word": word_dir.name, "speaker": speaker_dir.name, "files": files})
    background = data_dir / BACKGROUND_DIR
    backgrounds = [_describe(p, data_dir) for p in sorted(background.glob("*.wav"))] if background.is_dir() else []
    return {"takes": groups, "background": backgrounds, "synthetic": _synthetic(data_dir),
            "elevenlabs": _elevenlabs(data_dir)}


# data/elevenlabs/<word>/index.json: {group: {file: seconds}} - one file read instead of ~1000 folders and
# ~3000 files on the Home Assistant share (a minute over SMB); written by wakeword/elevenlabs.py generate()
INDEX = "index.json"


def scan_group(group: Path) -> dict[str, float]:
    """The takes of one ElevenLabs group: {file: seconds}, the length from the size (16 kHz mono 16-bit)."""
    takes = {}
    for entry in os.scandir(group):
        if entry.name[0].isdigit() and entry.name.endswith(".wav"):
            takes[entry.name] = round(max(entry.stat().st_size - WAV_HEADER, 0) / PCM_BYTES_PER_SECOND, 2)
    return dict(sorted(takes.items()))


def read_index(word_dir: Path) -> dict[str, dict[str, float]] | None:
    try:
        return json.loads((word_dir / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_index(word_dir: Path, groups: dict[str, dict[str, float]]) -> None:
    tmp = word_dir / f".{INDEX}"
    tmp.write_text(json.dumps(dict(sorted(groups.items())), separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(word_dir / INDEX)


def _elevenlabs(data_dir: Path) -> list[dict]:
    """ElevenLabs takes to listen to, per word and voice group (made on this computer)."""
    base = data_dir / ELEVENLABS_DIR
    groups = []
    for word_dir in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        folders = sorted(entry.name for entry in os.scandir(word_dir) if entry.is_dir())
        index = read_index(word_dir)
        if index is None or sorted(index) != folders:  # made before the index or changed by hand
            index = {name: scan_group(word_dir / name) for name in folders}
            write_index(word_dir, index)
        stamp = datetime.fromtimestamp((word_dir / INDEX).stat().st_mtime).isoformat(timespec="seconds")
        for name in folders:
            files = [{"path": f"{ELEVENLABS_DIR}/{word_dir.name}/{name}/{file}", "name": file, "seconds": seconds,
                      "size": None, "time": stamp} for file, seconds in index[name].items()]
            if files:
                groups.append({"word": word_dir.name, "group": name, "files": files})
    return groups


def _synthetic(data_dir: Path) -> list[dict]:
    """Synthetic clips to listen to, per word and kind (spoken word / sound-alikes)."""
    build = data_dir / "build"
    groups = []
    for word_dir in sorted(p for p in build.iterdir() if p.is_dir()) if build.is_dir() else []:
        for kind in PREVIEW_KINDS:
            files = [_describe(p, data_dir) for p in sorted((word_dir / PREVIEW_DIR / kind).glob("*.wav"))]
            if files:
                groups.append({"word": word_dir.name, "kind": kind, "files": files})
    return groups


def recording_path(root: Path, relative: str) -> Path:
    """The file behind a listed path; refuses anything outside data/real and data/background."""
    data_dir = (Path(root) / "data").resolve()
    path = (data_dir / relative).resolve()
    allowed = [data_dir / area for area in AREAS]
    preview = (data_dir / "build") in path.parents and path.parent.parent.name == PREVIEW_DIR
    preview = preview or (data_dir / ELEVENLABS_DIR) in path.parents
    if path.suffix != ".wav" or not (preview or any(area in path.parents for area in allowed)):
        raise ValueError(f"not a recording: {relative}")
    if not path.is_file():
        raise ValueError(f"no such recording: {relative}")
    return path


def delete_recordings(root: Path, paths: list[str]) -> Path:
    """Move recordings to data/backup/deleted-<time>/ (same layout); returns that folder."""
    data_dir = (Path(root) / "data").resolve()
    files = [recording_path(root, p) for p in paths]  # all checked before anything moves
    if any(PREVIEW_DIR in p.parts or (data_dir / ELEVENLABS_DIR) in p.parents for p in files):
        raise ValueError("synthetic clips are for listening only")
    if not files:
        raise ValueError("nothing to delete")
    backup = data_dir / "backup" / f"deleted-{time.strftime('%Y%m%d-%H%M%S')}"
    for path in files:
        target = backup / path.relative_to(data_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        folder = path.parent
        while folder != data_dir and folder.parent != data_dir and not any(folder.iterdir()):
            folder.rmdir()  # drop emptied speaker/word folders, keep data/real and data/background
            folder = folder.parent
    return backup

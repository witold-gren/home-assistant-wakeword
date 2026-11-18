#!/usr/bin/env python3
"""Augment the audio of every feature set in features.json and compute microWakeWord features.

Run from the household folder on the training machine (train/train.sh does it):

    python make_features.py data/build/<word>/features.json --assets <assets folder>

For each set that is not precomputed, its sources (files and folders of WAVs) are collected into
``data/build/<word>/staging/<set>/`` (16 kHz copies or links), then augmented and turned into
spectrograms in ``features/<set>/{training,validation,testing}/<set>_mmap`` — the layout the
training config expects. A set is rebuilt only when its source files changed (a signature of
paths, sizes and modification times is kept next to the features).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

SIGNATURE_FILE = ".sources"
# Augmentation makes one 3.2 s clip per file: a long negative recording (home background, minutes)
# would give a single clip, so negatives longer than two chunks are cut into 3 s pieces first.
CHUNK_SECONDS = 3.0
AUGMENTATION_PROBABILITIES = {
    "SevenBandParametricEQ": 0.1,
    "TanhDistortion": 0.1,
    "PitchShift": 0.1,
    "BandStopFilter": 0.1,
    "AddColorNoise": 0.1,
    "AddBackgroundNoise": 0.75,
    "Gain": 1.0,
    "RIR": 0.5,
}


def collect(sources: list[str], root: Path) -> list[Path]:
    """All WAV files of the sources (files or folders, searched recursively), sorted."""
    files: list[Path] = []
    for source in sources:
        path = root / source
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            # ".00003.wav": a take still being written (or left by an interrupted run)
            files.extend(sorted(f for f in path.rglob("*.wav") if not f.name.startswith(".")))
    return files


def signature(files: list[Path], entry: dict) -> str:
    """Changes when a source file is added, removed or modified, or the repeat count changes."""
    digest = hashlib.sha1(f"repeat={entry['repeat']}".encode())
    for file in files:
        stat = file.stat()
        digest.update(f"{file}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def is_current(out: Path, sig: str) -> bool:
    marker = out / SIGNATURE_FILE
    return marker.exists() and marker.read_text().strip() == sig


def _read_16k(file: Path):
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(str(file), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if rate == 16000:
        return mono
    n = int(round(len(mono) * 16000 / rate))
    return np.interp(np.linspace(0, len(mono), n, endpoint=False), np.arange(len(mono)), mono)


def stage(files: list[Path], folder: Path, root: Path, chunk_seconds: float | None = None) -> int:
    """Put 16 kHz WAVs into `folder` (links, or converted copies; unique names from the paths).

    With `chunk_seconds`, files longer than two chunks are cut into chunks (the rest under a second
    is dropped). Returns the number of clips staged.
    """
    import soundfile as sf

    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    count = 0
    for file in files:
        name = file.relative_to(root).as_posix().replace("/", "__")
        info = sf.info(str(file))
        if chunk_seconds and info.duration > 2 * chunk_seconds:
            samples = _read_16k(file)
            size = int(chunk_seconds * 16000)
            for index, start in enumerate(range(0, len(samples) - 16000 + 1, size)):
                sf.write(str(folder / f"{name[:-4]}__{index:05d}.wav"), samples[start:start + size], 16000,
                         subtype="PCM_16")
                count += 1
        elif info.samplerate == 16000:
            os.symlink(file.resolve(), folder / name)
            count += 1
        else:
            sf.write(str(folder / name), _read_16k(file), 16000, subtype="PCM_16")
            count += 1
    return count


def build_set(entry: dict, root: Path, staging: Path, assets: Path) -> None:
    from microwakeword.audio.augmentation import Augmentation
    from microwakeword.audio.clips import Clips
    from microwakeword.audio.spectrograms import SpectrogramGeneration
    from mmap_ninja.ragged import RaggedMmap

    name = entry["name"]
    out = root / entry["features_dir"]
    files = collect(entry["sources"], root)
    sig = signature(files, entry)
    if is_current(out, sig):
        print(f"{name}: up to date, skipped")
        return
    if out.exists():
        shutil.rmtree(out)
    count = stage(files, staging / name, root, None if entry.get("truth", True) else CHUNK_SECONDS)
    if count == 0:
        print(f"{name}: no audio found in {entry['sources']} — skipped")
        return
    print(f"{name}: {count} clips from {len(files)} files", flush=True)
    clips = Clips(input_directory=str(staging / name), file_pattern="*.wav", max_clip_duration_s=None,
                  remove_silence=False, random_split_seed=10, split_count=0.1)
    augmenter = Augmentation(
        augmentation_duration_s=3.2,
        augmentation_probabilities=AUGMENTATION_PROBABILITIES,
        impulse_paths=[str(assets / "mit_rirs")],
        background_paths=[str(assets / "fma_16k"), str(assets / "audioset_16k")],
        background_min_snr_db=-5,
        background_max_snr_db=10,
        min_jitter_s=0.195,
        max_jitter_s=0.205,
    )
    for split, split_name, repeat, slide in (
        ("training", "train", entry["repeat"], 10),
        ("validation", "validation", 1, 10),
        ("testing", "test", 1, 1),
    ):
        spectrograms = SpectrogramGeneration(clips=clips, augmenter=augmenter, slide_frames=slide, step_ms=10)
        (out / split).mkdir(parents=True, exist_ok=True)  # mmap_ninja creates only the last folder
        RaggedMmap.from_generator(
            out_dir=str(out / split / f"{name}_mmap"),
            sample_generator=spectrograms.spectrogram_generator(split=split_name, repeat=repeat),
            batch_size=100,
            verbose=True,
        )
    (out / SIGNATURE_FILE).write_text(sig + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path, help="data/build/<word>/features.json")
    parser.add_argument("--assets", type=Path, required=True, help="folder from download_assets.py")
    parser.add_argument("--root", type=Path, default=Path("."), help="household folder")
    args = parser.parse_args()
    plan = json.loads(args.features.read_text(encoding="utf-8"))
    staging = args.features.parent / "staging"
    for entry in plan["sets"]:
        if entry["precomputed"]:
            if not (args.root / entry["features_dir"]).exists():
                raise SystemExit(f"{entry['features_dir']} missing — run download_assets.py and link it")
            continue
        build_set(entry, args.root, staging, args.assets)
    print(f"features for {plan['word']} are ready")


if __name__ == "__main__":
    main()

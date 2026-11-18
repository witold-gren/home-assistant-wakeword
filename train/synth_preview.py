#!/usr/bin/env python3
"""A few clips of every synthetic group, small enough to bring back to the Mac and listen to.

    python train/synth_preview.py <household folder> [per group]

For every word: data/synthetic/<word>/<positive|negative>/<group>/ → the first and a middle clip
copied to data/build/<word>/synthetic_preview/<positive|negative>/<group>_<clip>.wav.
"Fetch samples" in card 4 of the panel brings them to the Mac and lists them there to listen to.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

KINDS = ("positive", "negative")


def pick(files: list[Path], per_group: int) -> list[Path]:
    """Evenly spread clips (the first, then further ones - different speed, noise and speakers)."""
    if len(files) <= per_group:
        return files
    step = len(files) / per_group
    return [files[int(i * step)] for i in range(per_group)]


def make_preview(household: Path, per_group: int = 3) -> dict[str, int]:
    made = {}
    synthetic = household / "data" / "synthetic"
    for word_dir in sorted(p for p in synthetic.iterdir() if p.is_dir()) if synthetic.is_dir() else []:
        target = household / "data" / "build" / word_dir.name / "synthetic_preview"
        if not target.parent.is_dir():
            continue  # a word that is not prepared any more
        shutil.rmtree(target, ignore_errors=True)
        count = 0
        for kind in KINDS:
            for group in sorted(p for p in (word_dir / kind).glob("*") if p.is_dir()):
                files = sorted(f for f in group.glob("*.wav") if not f.name.startswith("."))
                for clip in pick(files, per_group):
                    out = target / kind / f"{group.name}_{clip.stem}.wav"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(clip, out)
                    count += 1
        made[word_dir.name] = count
    return made


def main() -> None:
    household = Path(sys.argv[1])
    per_group = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for word, count in make_preview(household, per_group).items():
        print(f"{word}: {count} synthetic clips to listen to in data/build/{word}/synthetic_preview "
              "(panel card 4: Fetch samples)", flush=True)


if __name__ == "__main__":
    main()

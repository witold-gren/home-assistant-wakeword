#!/usr/bin/env python3
"""One Piper voice reading one text `count` times with varied speed and noise (called by synthetic.sh).

The voice is loaded once for the whole group (starting Piper for every clip reloaded the 60 MB
model each time: ~1 s per clip instead of a few ms). Clips are written as 16 kHz mono 16-bit
``00000.wav`` … through a temporary name, so an interrupted run never leaves a half-written clip;
the next run makes only the missing ones. ``.complete`` marks a finished group and holds its text:
a group whose text changed in household.yaml is made again.

A voice is a name from rhasspy/piper-voices (``pl_PL-gosia-medium``) or ``<owner>/<repo>/<voice>``
on Hugging Face (``WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium``): ``<voice>.onnx`` and
``<voice>.onnx.json`` from that repository.

Every line it prints says what really happens: whether the voice was downloaded or already there,
how many clips are made (or resumed, or skipped), progress every 50 clips and the time taken.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import time
from typing import Callable

DONE = ".complete"
RATE = 16000
PROGRESS_EVERY = 50
NOISE_W = 0.8


def settings(index: int, length_scales: list[float], noise_scales: list[float]) -> tuple[float, float]:
    """Speed and noise of clip `index`: every combination in turn (same order as before)."""
    return (length_scales[index % len(length_scales)],
            noise_scales[(index // len(length_scales)) % len(noise_scales)])


def to_16k(samples, rate: int):
    import numpy as np

    samples = np.asarray(samples, dtype=np.float32)
    if rate != RATE:
        from math import gcd

        from scipy.signal import resample_poly

        common = gcd(RATE, rate)
        samples = resample_poly(samples, RATE // common, rate // common).astype(np.float32)
    return samples


def ensure_voice(voice: str, voices_dir: Path, log: Callable[[str], None]) -> Path:
    repo, _, name = voice.rpartition("/")
    model = voices_dir / f"{name}.onnx"
    if model.is_file() and model.with_suffix(".onnx.json").is_file():
        log(f"voice {name}: already downloaded")
        return model
    voices_dir.mkdir(parents=True, exist_ok=True)
    if repo:
        log(f"voice {name}: downloading from huggingface.co/{repo} to {voices_dir}")
        from huggingface_hub import hf_hub_download

        for file in (f"{name}.onnx.json", f"{name}.onnx"):  # the small one first: a wrong name fails fast
            hf_hub_download(repo, file, local_dir=voices_dir)
        return model
    log(f"voice {name}: downloading to {voices_dir}")
    from piper.download_voices import download_voice

    download_voice(name, voices_dir)
    return model


def is_complete(out: Path, text: str) -> bool:
    """Finished with this text (an empty marker comes from before the text was kept: trusted)."""
    marker = out / DONE
    if not marker.is_file():
        return False
    kept = marker.read_text(encoding="utf-8").strip()
    return not kept or kept == text


def make_clips(out: Path, count: int, clip: Callable[[int], tuple[object, int]], label: str,
               describe: str, log: Callable[[str], None] = print, text: str = "") -> int:
    """Write the missing clips of a group; returns how many were made now."""
    import soundfile as sf

    out.mkdir(parents=True, exist_ok=True)
    if is_complete(out, text):
        log(f"{label} skip, already complete: {describe}")
        return 0
    if (out / DONE).exists():  # made for another text: all clips again
        log(f"{label} the text changed, making the group again: {describe}")
        for old in out.glob("*.wav"):
            old.unlink()
        (out / DONE).unlink()
    for leftover in [*out.glob(".*.wav"), out / "raw.wav"]:  # half-written clips of an interrupted run
        leftover.unlink(missing_ok=True)
    present = set()
    for path in out.glob("[0-9]*.wav"):
        if not path.stem.isdigit():
            continue
        try:  # a clip cut short by an interrupted ffmpeg (older script) is made again
            usable = sf.info(str(path)).frames > 0
        except RuntimeError:
            usable = False
        if usable:
            present.add(int(path.stem))
        else:
            path.unlink()
    missing = [i for i in range(count) if i not in present]
    if missing:
        resumed = f" (resuming: {count - len(missing)} already there)" if present else ""
        log(f"{label} {describe}: making {len(missing)} of {count} clips{resumed} → {out}")
        started = time.time()
        for made, index in enumerate(missing, 1):
            samples, rate = clip(index)
            tmp = out / f".{index:05d}.wav"
            sf.write(tmp, to_16k(samples, rate), RATE, subtype="PCM_16")
            tmp.rename(out / f"{index:05d}.wav")
            if made % PROGRESS_EVERY == 0 or made == len(missing):
                log(f"{label}   {count - len(missing) + made}/{count} clips, {time.time() - started:.0f} s")
    else:
        log(f"{label} {describe}: all {count} clips already there")
    (out / DONE).write_text(text, encoding="utf-8")
    return len(missing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voices-dir", type=Path, required=True)
    parser.add_argument("--label", default="", help="e.g. [3/27] - position in the whole synthesis")
    parser.add_argument("--length-scales", type=float, nargs="+", default=[0.8, 0.9, 1.0, 1.1, 1.25])
    parser.add_argument("--noise-scales", type=float, nargs="+", default=[0.5, 0.667, 0.9])
    args = parser.parse_args()
    log = lambda line: print(line, flush=True)  # noqa: E731 - the panel follows the log live
    describe = f"{args.voice.rsplit('/', 1)[-1]} '{args.text}'"
    if is_complete(args.out, args.text):
        log(f"{args.label} skip, already complete: {describe}")
        return

    voice = None

    def clip(index: int):
        nonlocal voice
        import numpy as np
        from piper import PiperVoice, SynthesisConfig

        if voice is None:
            voice = PiperVoice.load(ensure_voice(args.voice, args.voices_dir, log))
        length_scale, noise_scale = settings(index, args.length_scales, args.noise_scales)
        config = SynthesisConfig(length_scale=length_scale, noise_scale=noise_scale, noise_w_scale=NOISE_W)
        chunks = list(voice.synthesize(args.text, syn_config=config))
        return np.concatenate([c.audio_float_array for c in chunks]), chunks[0].sample_rate

    make_clips(args.out, args.count, clip, args.label, describe, log, args.text)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download the augmentation and negative data microWakeWord training needs (run once).

Same sources as microWakeWord's training notebook:

- mit_rirs/          room impulse responses (reverb)
- audioset_16k/      background noise (a few parts of AudioSet's balanced set)
- fma_16k/           background music (Free Music Archive, extra small)
- negative_datasets/ ready spectrogram features: speech, dinner_party, no_speech, dinner_party_eval

Everything comes from Hugging Face datasets: downloads resume after an interruption and use the
token saved by the training panel / `huggingface-cli login` (optional - higher rate limits).
A folder counts as ready only when its ``.complete`` marker exists, so a run that stopped half-way
is redone instead of being trusted.

The data has mixed licences — models trained with it are for personal, non-commercial use.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

NEGATIVE_REPO = "kahrendt/microwakeword"
NEGATIVE_FILES = ["dinner_party.zip", "dinner_party_eval.zip", "no_speech.zip", "speech.zip"]
# AudioSet moved from bal_trainNN.tar archives to parquet files (~0.7 GB, ~500 ten-second clips each);
# four parts give about as much background as the old single archive
AUDIOSET_REPO = "agkphysics/AudioSet"
AUDIOSET_PARTS = [f"data/bal_train/{index:02d}.parquet" for index in range(4)]
LEGACY_AUDIOSET_TAR = "bal_train09.tar"
FMA_REPO, FMA_FILE = "mchl914/fma_xsmall", "fma_xs.zip"
RIRS_REPO = "davidscripka/MIT_environmental_impulse_responses"
RIRS_COUNT = 270  # files in the MIT set - an older run without the marker is complete with all of them
DONE = ".complete"
RATE = 16000


def hf_file(repo: str, filename: str, folder: Path) -> Path:
    """One file of a Hugging Face dataset, saved under `folder` (resumable, uses the saved token)."""
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo, filename=filename, repo_type="dataset", local_dir=str(folder)))


def is_done(folder: Path) -> bool:
    return (folder / DONE).exists()


def mark_done(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / DONE).touch()


def write_wav(path: Path, samples) -> None:
    import numpy as np
    import scipy.io.wavfile

    scipy.io.wavfile.write(path, RATE, (np.clip(samples, -1, 1) * 32767).astype(np.int16))


def decode_16k(data: bytes):
    """Encoded audio (flac, ogg, mp3, wav …) -> mono float samples at 16 kHz."""
    from io import BytesIO
    from math import gcd

    import numpy as np
    from scipy.signal import resample_poly
    import soundfile as sf

    samples, rate = sf.read(BytesIO(data), dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if rate != RATE:
        common = gcd(RATE, rate)
        samples = resample_poly(samples, RATE // common, rate // common).astype(np.float32)
    return samples


def parquet_audio(path: Path):
    """(clip id, encoded audio) from a parquet file of a Hugging Face audio dataset.

    Read with pyarrow directly: files written by newer `datasets` releases carry feature types
    the version used for training cannot parse.
    """
    import pyarrow.parquet as pq

    for batch in pq.ParquetFile(path).iter_batches(batch_size=64, columns=["video_id", "audio"]):
        for clip, audio in zip(batch.column("video_id").to_pylist(), batch.column("audio").to_pylist()):
            if audio and audio.get("bytes"):
                yield clip, audio["bytes"]


def save_16k(files: list[Path], out_dir: Path) -> None:
    import datasets
    from tqdm import tqdm

    out_dir.mkdir(parents=True, exist_ok=True)
    data = datasets.Dataset.from_dict({"audio": [str(f) for f in files]})
    data = data.cast_column("audio", datasets.Audio(sampling_rate=RATE))
    for row in tqdm(data, desc=out_dir.name):
        write_wav(out_dir / Path(row["audio"]["path"]).with_suffix(".wav").name, row["audio"]["array"])


def rirs(assets: Path, fetch=hf_file) -> None:
    out_dir = assets / "mit_rirs"
    if is_done(out_dir):
        return
    if out_dir.is_dir() and len(list(out_dir.glob("*.wav"))) >= RIRS_COUNT:
        return mark_done(out_dir)
    import datasets
    from tqdm import tqdm

    out_dir.mkdir(parents=True, exist_ok=True)
    # not streaming: a streamed dataset can crash the interpreter on exit, failing train.sh
    rows = datasets.load_dataset(RIRS_REPO, split="train")
    rows = rows.cast_column("audio", datasets.Audio(sampling_rate=RATE))
    for index, row in enumerate(tqdm(rows, desc="mit_rirs")):
        name = Path(row["audio"].get("path") or f"rir_{index:04d}.wav").with_suffix(".wav").name
        write_wav(out_dir / name, row["audio"]["array"])
    mark_done(out_dir)


def audioset(assets: Path, fetch=hf_file) -> None:
    out_dir = assets / "audioset_16k"
    if is_done(out_dir):
        return
    (assets / "audioset" / LEGACY_AUDIOSET_TAR).unlink(missing_ok=True)  # empty file of a failed old download
    from tqdm import tqdm

    out_dir.mkdir(parents=True, exist_ok=True)
    for part in AUDIOSET_PARTS:
        path = fetch(AUDIOSET_REPO, part, assets / "audioset")
        for clip, data in tqdm(parquet_audio(path), desc=f"audioset {Path(part).stem}"):
            try:
                samples = decode_16k(data)
            except RuntimeError:  # a broken clip - skip it, there are hundreds more
                continue
            write_wav(out_dir / f"{clip}.wav", samples)
    mark_done(out_dir)


def fma(assets: Path, fetch=hf_file) -> None:
    out_dir = assets / "fma_16k"
    if is_done(out_dir):
        return
    archive = fetch(FMA_REPO, FMA_FILE, assets / "fma")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(archive.parent)
    save_16k(sorted((assets / "fma").glob("**/*.mp3")), out_dir)
    mark_done(out_dir)


def negatives(assets: Path, fetch=hf_file) -> None:
    out_dir = assets / "negative_datasets"
    for name in NEGATIVE_FILES:
        marker = out_dir / f".{name.removesuffix('.zip')}{DONE}"
        if marker.exists():
            continue
        archive = fetch(NEGATIVE_REPO, name, out_dir)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(out_dir)
        archive.unlink()
        marker.touch()


STEPS = (rirs, audioset, fma, negatives)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("assets", type=Path, help="folder for the downloaded data (~20 GB)")
    args = parser.parse_args()
    for step in STEPS:
        step(args.assets)
    print(f"assets ready in {args.assets}")


if __name__ == "__main__":
    main()

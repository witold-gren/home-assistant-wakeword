"""Audio helpers: 16 kHz mono WAV in and out, ffmpeg conversion, trimming, loudness, quality stats.

microWakeWord works on 16 kHz, 16-bit, mono audio, so everything is normalised to that.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import BinaryIO

import numpy as np
import soundfile as sf

SAMPLE_RATE = 16000
CLIP_LEVEL = 0.999  # |sample| at or above this counts as clipped
FRAME_MS = 20


class AudioError(RuntimeError):
    """An audio file could not be read or converted."""


def read_wav(path: Path | str | BinaryIO) -> tuple[np.ndarray, int]:
    """Read any soundfile-readable file (path or file object) as float32 mono in [-1, 1] plus its
    sample rate."""
    source = str(path) if isinstance(path, (str, Path)) else path
    try:
        data, rate = sf.read(source, dtype="float32", always_2d=True)
    except (RuntimeError, sf.LibsndfileError) as err:
        raise AudioError(f"{path}: {err}") from err
    return data.mean(axis=1), rate


def write_wav(path: Path | str, samples: np.ndarray, rate: int = SAMPLE_RATE) -> Path:
    """Write float samples as 16-bit PCM WAV (creating parent directories)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(samples, -1.0, 1.0), rate, subtype="PCM_16")
    return path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def convert_to_wav(src: Path | str, dst: Path | str) -> Path:
    """Convert any audio file (m4a, mp3, webm, wav…) to 16 kHz mono 16-bit WAV with ffmpeg."""
    if not ffmpeg_available():
        raise AudioError("ffmpeg not found — install it (macOS: brew install ffmpeg)")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(dst)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AudioError(f"{src}: ffmpeg failed: {result.stderr.strip()}")
    return dst


def resample(samples: np.ndarray, rate: int, target: int = SAMPLE_RATE) -> np.ndarray:
    """Linear-interpolation resampling (enough for already band-limited speech at 16 kHz)."""
    if rate == target or len(samples) == 0:
        return samples.astype(np.float32)
    duration = len(samples) / rate
    n_out = max(1, round(duration * target))
    x_old = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def dbfs(value: float) -> float:
    """Level of an RMS / peak value in dBFS (-inf for silence)."""
    return float(20 * np.log10(value)) if value > 0 else float("-inf")


def frame_levels(samples: np.ndarray, rate: int = SAMPLE_RATE, frame_ms: int = FRAME_MS) -> np.ndarray:
    """RMS level in dBFS of consecutive frames."""
    size = max(1, rate * frame_ms // 1000)
    n = len(samples) // size
    if n == 0:
        return np.array([dbfs(float(np.sqrt(np.mean(samples**2)))) if len(samples) else -np.inf])
    frames = samples[: n * size].reshape(n, size)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    with np.errstate(divide="ignore"):
        return 20 * np.log10(np.maximum(rms, 1e-10))


# --- where the word is: kept identical in wakeword/audio.py and the integration's take.py ---------
NOISE_PERCENTILE = 0.1  # the quietest 10 % of frames tell the background level
WORD_MARGIN_DB = 10.0  # the word stands out at least this much from the background
WORD_RANGE_DB = 30.0  # and is never more than this below its loudest frame
WORD_GAP_FRAMES = 25  # 0.5 s - a pause inside the word ("hej … dżarwis") keeps it one piece
WORD_EDGE_DB = 4.0  # the word's quiet start and end: still this much above the background
MIN_SNR_DB = 8.0  # loudest frame above the background - less and the word is lost in noise
SILENCE_DB = -120.0


def noise_floor(levels) -> float:
    """Background level: a low percentile of the frame levels (dBFS)."""
    ordered = sorted(max(level, SILENCE_DB) for level in levels)  # digital silence counts as very quiet
    return ordered[int(NOISE_PERCENTILE * (len(ordered) - 1))] if ordered else SILENCE_DB


def word_frames(levels) -> tuple[int, int] | None:
    """First and last frame of the word, or None for silence.

    Frames louder than the background (by WORD_MARGIN_DB) form segments; pauses up to
    WORD_GAP_FRAMES stay inside one segment. The segment with the most energy above the background
    is the word - other sounds before or after it (a door, a cough, the TV) are left out, while
    the noise under the word stays part of it. Its edges then follow the sound down to
    WORD_EDGE_DB above the background.
    """
    levels = list(levels)
    if not levels or max(levels) < -70:
        return None
    peak, floor = max(levels), noise_floor(levels)
    cut = max(peak - WORD_RANGE_DB, min(floor + WORD_MARGIN_DB, peak))
    best, best_score = None, -1.0
    start = last = None
    score = 0.0
    for i, level in enumerate(levels + [float("-inf")] * (WORD_GAP_FRAMES + 1)):
        if level >= cut:
            if start is None:
                start, score = i, 0.0
            last = i
            score += 10 ** ((level - floor) / 10)
        elif start is not None and i - last > WORD_GAP_FRAMES:
            if score > best_score:
                best, best_score = (start, last), score
            start = None
    # widen to the quiet start and end of the word (soft consonants, fade-out)
    first, end = best
    edge = max(floor + WORD_EDGE_DB, peak - WORD_RANGE_DB)
    while first > 0 and levels[first - 1] >= edge:
        first -= 1
    while end < len(levels) - 1 and levels[end + 1] >= edge:
        end += 1
    return first, end


def snr_db(levels) -> float:
    """How far the loudest frame stands out from the background (dB)."""
    levels = list(levels)
    return max(levels) - noise_floor(levels) if levels else 0.0


def speech_bounds(
    samples: np.ndarray, rate: int = SAMPLE_RATE, pad_ms: int = 150
) -> tuple[int, int]:
    """Sample range of the word (see word_frames), widened by `pad_ms`. Returns (0, 0) for silence."""
    frames = word_frames(frame_levels(samples, rate).tolist()) if len(samples) else None
    if frames is None:
        return 0, 0
    size = rate * FRAME_MS // 1000
    pad = rate * pad_ms // 1000
    return max(0, frames[0] * size - pad), min(len(samples), (frames[1] + 1) * size + pad)


def trim_silence(samples: np.ndarray, rate: int = SAMPLE_RATE, pad_ms: int = 150) -> np.ndarray:
    """Cut leading and trailing silence, keeping `pad_ms` around the speech."""
    start, end = speech_bounds(samples, rate, pad_ms=pad_ms)
    return samples[start:end] if end > start else samples[:0]


def normalize_peak(samples: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    """Scale so the loudest sample sits at `peak_db` dBFS (silence stays silence)."""
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak <= 0:
        return samples
    return (samples * (10 ** (peak_db / 20) / peak)).astype(np.float32)


@dataclass(frozen=True)
class AudioStats:
    """Quality numbers of one recording."""

    duration: float  # seconds
    rate: int
    peak_db: float
    rms_db: float  # loudness of the speech part
    clipped: float  # share of clipped samples
    speech: float  # seconds of speech (between speech_bounds)
    snr_db: float = 99.0  # loudest frame above the background noise

    @property
    def is_silent(self) -> bool:
        return self.speech <= 0


def analyze(samples: np.ndarray, rate: int) -> AudioStats:
    """Duration, levels, clipping and speech length of a recording."""
    if not len(samples):
        return AudioStats(0.0, rate, float("-inf"), float("-inf"), 0.0, 0.0)
    start, end = speech_bounds(samples, rate, pad_ms=0)
    speech = samples[start:end] if end > start else samples[:0]
    rms = float(np.sqrt(np.mean(speech**2))) if len(speech) else 0.0
    return AudioStats(
        duration=len(samples) / rate,
        rate=rate,
        peak_db=dbfs(float(np.max(np.abs(samples)))),
        rms_db=dbfs(rms),
        clipped=float(np.mean(np.abs(samples) >= CLIP_LEVEL)),
        speech=(end - start) / rate,
        snr_db=snr_db(frame_levels(samples, rate).tolist()),
    )

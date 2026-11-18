"""Voice expansion: turn each household take into several "new speakers".

Pure numpy, so it runs anywhere:

- tempo: phase-vocoder time stretch (pitch unchanged),
- voice: resampling shifts pitch *and* formants together — what a shorter or longer vocal tract
  sounds like (a bit like a child or a bigger adult) — then the length is restored by the stretch.

Only training takes are expanded (the test split stays untouched, otherwise the test would measure
the model on near-copies of what it trained on).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import shutil

import numpy as np

from .audio import SAMPLE_RATE, normalize_peak, read_wav, write_wav
from .dataset import read_split
from .household import Household

N_FFT = 512
HOP = 128

# Grid of (semitones, tempo). Children already have high voices, so they are shifted down more than
# up; adults both ways.
GRID = {
    "adult": [(-3.0, 1.0), (-1.5, 0.92), (1.5, 1.08), (3.0, 1.0), (4.5, 0.95), (-1.5, 1.1), (2.0, 0.9), (0.0, 1.15)],
    "child": [(-4.0, 1.0), (-2.5, 0.92), (-1.0, 1.08), (1.5, 1.0), (-3.0, 1.1), (0.0, 0.88), (-5.0, 0.95), (1.0, 1.15)],
}
EXPANDED_DIR = "expanded"


def _stft(samples: np.ndarray) -> np.ndarray:
    window = np.hanning(N_FFT)
    padded = np.pad(samples, (N_FFT, N_FFT))
    n = 1 + (len(padded) - N_FFT) // HOP
    frames = np.stack([padded[i * HOP: i * HOP + N_FFT] * window for i in range(n)])
    return np.fft.rfft(frames, axis=1)


def _istft(spec: np.ndarray, length: int) -> np.ndarray:
    window = np.hanning(N_FFT)
    frames = np.fft.irfft(spec, n=N_FFT, axis=1) * window
    out = np.zeros(HOP * (len(frames) - 1) + N_FFT)
    norm = np.zeros_like(out)
    for i, frame in enumerate(frames):
        out[i * HOP: i * HOP + N_FFT] += frame
        norm[i * HOP: i * HOP + N_FFT] += window**2
    out /= np.maximum(norm, 1e-8)
    out = out[N_FFT:]
    if len(out) < length:
        out = np.pad(out, (0, length - len(out)))
    return out[:length]


def time_stretch(samples: np.ndarray, tempo: float) -> np.ndarray:
    """Change the speed by `tempo` (1.1 = 10 % faster, shorter) without changing the pitch."""
    if tempo <= 0:
        raise ValueError("tempo must be positive")
    if abs(tempo - 1.0) < 1e-6 or len(samples) < N_FFT:
        return samples.astype(np.float32)
    spec = _stft(samples.astype(np.float64))
    steps = np.arange(0, len(spec) - 1, tempo)
    expected = 2 * np.pi * HOP * np.arange(spec.shape[1]) / N_FFT
    phase = np.angle(spec[0])
    out = np.empty((len(steps), spec.shape[1]), dtype=np.complex128)
    for k, step in enumerate(steps):
        i = int(step)
        frac = step - i
        mag = (1 - frac) * np.abs(spec[i]) + frac * np.abs(spec[i + 1])
        out[k] = mag * np.exp(1j * phase)
        delta = np.angle(spec[i + 1]) - np.angle(spec[i]) - expected
        delta -= 2 * np.pi * np.round(delta / (2 * np.pi))
        phase += expected + delta
    length = int(round(len(samples) / tempo))
    return _istft(out, length).astype(np.float32)


def shift_voice(samples: np.ndarray, semitones: float) -> np.ndarray:
    """Shift pitch and formants by `semitones`, keeping the duration."""
    if abs(semitones) < 1e-6 or not len(samples):
        return samples.astype(np.float32)
    factor = 2 ** (semitones / 12)
    n_out = max(1, int(round(len(samples) / factor)))
    x_new = np.linspace(0, len(samples) - 1, n_out)
    resampled = np.interp(x_new, np.arange(len(samples)), samples)
    restored = time_stretch(resampled, len(resampled) / len(samples))
    if len(restored) != len(samples):
        restored = np.resize(restored, len(samples)) if len(restored) > len(samples) else np.pad(
            restored, (0, len(samples) - len(restored)))
    return restored.astype(np.float32)


@dataclass(frozen=True)
class Variant:
    semitones: float
    tempo: float

    @property
    def suffix(self) -> str:
        return f"p{self.semitones:+.1f}_t{self.tempo:.2f}"


def pick_variants(group: str, count: int, rng: random.Random) -> list[Variant]:
    """`count` variants from the group's grid (all of them, shuffled, when count >= grid size)."""
    grid = [Variant(s, t) for s, t in GRID.get(group, GRID["adult"])]
    rng.shuffle(grid)
    return grid[: max(0, count)]


def expand_take(samples: np.ndarray, variant: Variant) -> np.ndarray:
    out = time_stretch(shift_voice(samples, variant.semitones), variant.tempo)
    return normalize_peak(out, -1.0)


def expanded_dir(household: Household, word: str) -> Path:
    return household.data_dir / EXPANDED_DIR / word


def expand_word(household: Household, word: str, per_take: int = 6, seed: int = 0) -> list[Path]:
    """Expand the training takes of `word` (from the split) into `data/expanded/<word>/`.

    The folder is rebuilt from scratch, so the result always matches the current split."""
    rows = [r for r in read_split(household, word) if r.split == "train"]
    target = expanded_dir(household, word)
    if target.exists():
        shutil.rmtree(target)
    written: list[Path] = []
    for row in rows:
        samples, rate = read_wav(row.path)
        if rate != SAMPLE_RATE:
            raise ValueError(f"{row.path}: expected {SAMPLE_RATE} Hz, run `wakeword check`")
        rng = random.Random(f"{seed}:{row.path.name}")
        for variant in pick_variants(row.group, per_take, rng):
            path = target / row.speaker / f"{row.path.stem}__{variant.suffix}.wav"
            written.append(write_wav(path, expand_take(samples, variant)))
    return written

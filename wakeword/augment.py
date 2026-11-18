"""Augmentation preview: hear what training will do to your recordings.

microWakeWord augments the clips itself during training (background noise, room impulse responses,
EQ, gain). This module does a simplified version of the same on the Mac, so you can listen and
check that the result still sounds like a person saying the word in a real room — and that your
home background recordings (``data/background/*.wav``) are usable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import shutil

import numpy as np

from .audio import SAMPLE_RATE, normalize_peak, read_wav, resample, write_wav
from .dataset import list_takes
from .household import Household

BACKGROUND_DIR = "background"
PREVIEW_DIR = "preview"


def pink_noise(length: int, rng: np.random.Generator) -> np.ndarray:
    """1/f noise — a stand-in background when no home recordings exist yet."""
    spectrum = np.fft.rfft(rng.standard_normal(length))
    freqs = np.fft.rfftfreq(length)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
    pink = np.fft.irfft(spectrum / np.sqrt(freqs), n=length)
    return (pink / (np.max(np.abs(pink)) or 1.0) * 0.5).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if len(samples) else 0.0


def fit_length(background: np.ndarray, length: int, rng: np.random.Generator) -> np.ndarray:
    """Loop or crop `background` to `length` samples starting at a random point."""
    if not len(background):
        return np.zeros(length, dtype=np.float32)
    if len(background) < length:
        background = np.tile(background, int(np.ceil(length / len(background))) + 1)
    start = int(rng.integers(0, len(background) - length + 1))
    return background[start: start + length]


def mix_at_snr(speech: np.ndarray, background: np.ndarray, snr_db: float,
               rng: np.random.Generator) -> np.ndarray:
    """Add `background` under `speech` so speech is `snr_db` dB louder (lower = noisier)."""
    noise = fit_length(background, len(speech), rng)
    speech_level, noise_level = rms(speech), rms(noise)
    if noise_level == 0 or speech_level == 0:
        return speech.astype(np.float32)
    scale = speech_level / (noise_level * 10 ** (snr_db / 20))
    return (speech + noise * scale).astype(np.float32)


def synthetic_rir(rt60: float, rng: np.random.Generator, rate: int = SAMPLE_RATE) -> np.ndarray:
    """A room impulse response: direct sound plus exponentially decaying noise (`rt60` seconds)."""
    length = max(1, int(rt60 * rate))
    t = np.arange(length) / rate
    tail = rng.standard_normal(length) * np.exp(-6.9 * t / max(rt60, 1e-3))
    tail[0] = 0.0
    rir = 0.4 * tail / (np.max(np.abs(tail)) or 1.0)
    rir[0] = 1.0
    return rir.astype(np.float32)


def reverberate(samples: np.ndarray, rir: np.ndarray) -> np.ndarray:
    """Convolve with an impulse response, keeping the original length and peak level."""
    if not len(samples):
        return samples
    n = len(samples) + len(rir) - 1
    size = 1 << (n - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(samples, size) * np.fft.rfft(rir, size), size)[: len(samples)]
    peak_in = float(np.max(np.abs(samples)))
    peak_out = float(np.max(np.abs(wet))) or 1.0
    return (wet * (peak_in / peak_out)).astype(np.float32)


def band_limit(samples: np.ndarray, low: float, high: float, rate: int = SAMPLE_RATE) -> np.ndarray:
    """Keep only `low`–`high` Hz (a cheap speaker / far microphone / phone EQ)."""
    if not len(samples):
        return samples
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    spectrum[(freqs < low) | (freqs > high)] = 0
    return np.fft.irfft(spectrum, n=len(samples)).astype(np.float32)


def gain(samples: np.ndarray, db: float) -> np.ndarray:
    return (samples * 10 ** (db / 20)).astype(np.float32)


@dataclass(frozen=True)
class Recipe:
    """One random augmentation chain (stored in the preview file name)."""

    rt60: float  # 0 = no reverb
    low: float
    high: float
    snr_db: float | None  # None = no background
    gain_db: float

    @property
    def label(self) -> str:
        parts = [f"rt{self.rt60:.1f}" if self.rt60 else "dry", f"eq{int(self.low)}-{int(self.high)}"]
        parts.append(f"snr{self.snr_db:.0f}" if self.snr_db is not None else "clean")
        parts.append(f"g{self.gain_db:+.0f}")
        return "_".join(parts)


def random_recipe(rng: random.Random) -> Recipe:
    return Recipe(
        rt60=rng.choice([0.0, 0.3, 0.5, 0.8]),
        low=rng.choice([60.0, 150.0, 300.0]),
        high=rng.choice([7900.0, 6000.0, 3800.0]),
        snr_db=rng.choice([None, 20.0, 10.0, 5.0]),
        gain_db=rng.choice([-12.0, -6.0, 0.0]),
    )


def apply(samples: np.ndarray, recipe: Recipe, background: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = samples
    if recipe.rt60:
        out = reverberate(out, synthetic_rir(recipe.rt60, rng))
    out = band_limit(out, recipe.low, recipe.high)
    if recipe.snr_db is not None:
        out = mix_at_snr(out, background, recipe.snr_db, rng)
    out = normalize_peak(out, -1.0)
    return np.clip(gain(out, recipe.gain_db), -1.0, 1.0)


def load_backgrounds(household: Household) -> list[tuple[str, np.ndarray]]:
    """Home background recordings from `data/background/` (any rate, resampled to 16 kHz)."""
    folder = household.data_dir / BACKGROUND_DIR
    result = []
    for path in sorted(folder.glob("*.wav")) if folder.is_dir() else []:
        samples, rate = read_wav(path)
        result.append((path.stem, resample(samples, rate)))
    return result


def preview_word(household: Household, word: str, count: int = 8, seed: int = 0) -> list[Path]:
    """Write `count` augmented versions of random takes of `word` to `data/preview/<word>/`."""
    takes = [t for sid in household.words[word].speakers for t in list_takes(household, word, sid)]
    if not takes:
        raise FileNotFoundError(f"no recordings of '{word}' yet — record or import some first")
    target = household.data_dir / PREVIEW_DIR / word
    if target.exists():
        shutil.rmtree(target)
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    backgrounds = load_backgrounds(household) or [("pink", pink_noise(SAMPLE_RATE * 10, np_rng))]
    written = []
    for i in range(count):
        take = rng.choice(takes)
        name, background = rng.choice(backgrounds)
        recipe = random_recipe(rng)
        samples, _ = read_wav(take.path)
        out = apply(samples, recipe, background, np_rng)
        bg = f"_{name}" if recipe.snr_db is not None else ""
        path = target / f"{i:02d}_{take.path.stem}_{recipe.label}{bg}.wav"
        written.append(write_wav(path, out))
    return written

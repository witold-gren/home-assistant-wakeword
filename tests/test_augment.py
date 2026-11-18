import random

import numpy as np
import pytest

from wakeword import audio, augment
from wakeword.audio import SAMPLE_RATE

from .conftest import noise, record_takes, silence, tone


def test_pink_noise_is_bounded_and_low_heavy():
    rng = np.random.default_rng(0)
    samples = augment.pink_noise(SAMPLE_RATE, rng)
    assert len(samples) == SAMPLE_RATE and np.max(np.abs(samples)) <= 0.5 + 1e-6
    spectrum = np.abs(np.fft.rfft(samples)) ** 2
    freqs = np.fft.rfftfreq(len(samples), 1 / SAMPLE_RATE)
    assert spectrum[(freqs > 50) & (freqs < 500)].mean() > spectrum[freqs > 4000].mean()


def test_fit_length():
    rng = np.random.default_rng(0)
    assert len(augment.fit_length(tone(0.1), 5000, rng)) == 5000
    assert len(augment.fit_length(tone(1.0), 5000, rng)) == 5000
    assert not augment.fit_length(np.zeros(0, dtype=np.float32), 10, rng).any()


@pytest.mark.parametrize("snr", [20.0, 5.0, 0.0])
def test_mix_at_snr(snr):
    rng = np.random.default_rng(0)
    speech = tone(1.0)
    background = noise(2.0)
    mixed = augment.mix_at_snr(speech, background, snr, rng)
    added = mixed - speech
    measured = 20 * np.log10(augment.rms(speech) / augment.rms(added))
    assert measured == pytest.approx(snr, abs=0.1)


def test_mix_with_silent_background():
    rng = np.random.default_rng(0)
    speech = tone(0.3)
    assert np.array_equal(augment.mix_at_snr(speech, silence(1), 10, rng), speech)


def test_rir_and_reverb():
    rng = np.random.default_rng(0)
    rir = augment.synthetic_rir(0.5, rng)
    assert len(rir) == SAMPLE_RATE // 2 and rir[0] == 1.0
    assert np.abs(rir[-200:]).max() < np.abs(rir[1:200]).max()
    click = np.zeros(SAMPLE_RATE, dtype=np.float32)
    click[100] = 0.5
    wet = augment.reverberate(click, rir)
    assert len(wet) == len(click)
    assert np.max(np.abs(wet)) == pytest.approx(0.5, abs=1e-4)
    assert np.abs(wet[2000:4000]).max() > 0  # a tail exists
    assert augment.reverberate(click[:0], rir).size == 0


def test_band_limit():
    mixed = tone(1.0, freq=100) + tone(1.0, freq=1000) + tone(1.0, freq=7000)
    out = augment.band_limit(mixed, 300, 3800)
    spectrum = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(len(out), 1 / SAMPLE_RATE)
    level = lambda f: spectrum[np.argmin(np.abs(freqs - f))]
    assert level(1000) > 100 * max(level(100), level(7000))
    assert augment.band_limit(mixed[:0], 1, 2).size == 0


def test_gain():
    assert np.max(augment.gain(tone(0.1, level=0.5), -6)) == pytest.approx(0.25, rel=0.01)


def test_recipe_label_and_apply():
    recipe = augment.Recipe(rt60=0.5, low=150, high=6000, snr_db=10, gain_db=-6)
    assert recipe.label == "rt0.5_eq150-6000_snr10_g-6"
    assert augment.Recipe(0, 60, 7900, None, 0).label == "dry_eq60-7900_clean_g+0"
    rng = np.random.default_rng(0)
    out = augment.apply(tone(0.5, level=0.9), recipe, noise(1.0), rng)
    assert len(out) == int(0.5 * SAMPLE_RATE)
    assert np.max(np.abs(out)) <= 1.0
    assert audio.dbfs(float(np.max(np.abs(out)))) == pytest.approx(-7, abs=0.2)


def test_random_recipe_is_seeded():
    assert augment.random_recipe(random.Random(3)) == augment.random_recipe(random.Random(3))


def test_preview_word(household):
    record_takes(household, "robo", "kid", 3)
    written = augment.preview_word(household, "robo", count=5, seed=2)
    assert len(written) == 5
    assert all(p.parent == household.data_dir / "preview" / "robo" for p in written)
    for path in written:
        samples, rate = audio.read_wav(path)
        assert rate == SAMPLE_RATE and np.max(np.abs(samples)) <= 1.0
    assert len(augment.preview_word(household, "robo", count=2)) == 2
    assert len(list((household.data_dir / "preview" / "robo").glob("*.wav"))) == 2


def test_preview_uses_home_background(household):
    record_takes(household, "robo", "kid", 1)
    audio.write_wav(household.data_dir / "background" / "tv.wav", noise(3.0, rate=8000), rate=8000)
    assert augment.load_backgrounds(household)[0][0] == "tv"
    assert len(augment.load_backgrounds(household)[0][1]) == 3 * SAMPLE_RATE
    names = [p.name for p in augment.preview_word(household, "robo", count=12)]
    assert any(n.endswith("_tv.wav") for n in names)
    assert not any("_pink" in n for n in names)


def test_preview_without_recordings(household):
    with pytest.raises(FileNotFoundError, match="no recordings"):
        augment.preview_word(household, "robo")

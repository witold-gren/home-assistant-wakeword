import random

import numpy as np
import pytest

from wakeword import audio, dataset, expand
from wakeword.audio import SAMPLE_RATE

from .conftest import record_takes, tone


def dominant(samples):
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return np.fft.rfftfreq(len(samples), 1 / SAMPLE_RATE)[np.argmax(spectrum)]


@pytest.mark.parametrize("tempo", [0.8, 1.1, 1.25])
def test_time_stretch_changes_length_not_pitch(tempo):
    samples = tone(1.0, freq=500)
    out = expand.time_stretch(samples, tempo)
    assert len(out) == round(len(samples) / tempo)
    assert dominant(out) == pytest.approx(500, abs=15)
    assert out.dtype == np.float32


def test_time_stretch_edge_cases():
    samples = tone(0.5)
    assert np.array_equal(expand.time_stretch(samples, 1.0), samples)
    short = tone(0.01)
    assert np.array_equal(expand.time_stretch(short, 1.2), short)
    with pytest.raises(ValueError):
        expand.time_stretch(samples, 0)


@pytest.mark.parametrize("semitones", [-3.0, 2.0, 4.5])
def test_shift_voice_changes_pitch_not_length(semitones):
    samples = tone(1.0, freq=400)
    out = expand.shift_voice(samples, semitones)
    assert len(out) == len(samples)
    assert dominant(out) == pytest.approx(400 * 2 ** (semitones / 12), rel=0.04)


def test_shift_voice_noop():
    samples = tone(0.2)
    assert np.array_equal(expand.shift_voice(samples, 0), samples)
    assert expand.shift_voice(samples[:0], 2).size == 0


def test_variants():
    variants = expand.pick_variants("child", 3, random.Random(1))
    assert len(variants) == 3 and len(set(variants)) == 3
    assert all((v.semitones, v.tempo) in expand.GRID["child"] for v in variants)
    assert len(expand.pick_variants("adult", 99, random.Random(1))) == len(expand.GRID["adult"])
    assert expand.pick_variants("unknown", 2, random.Random(1))[0] in [
        expand.Variant(s, t) for s, t in expand.GRID["adult"]]
    assert expand.Variant(-1.5, 0.92).suffix == "p-1.5_t0.92"


def test_expand_take_no_clipping():
    out = expand.expand_take(tone(0.8, level=0.9), expand.Variant(3.0, 0.9))
    assert np.max(np.abs(out)) <= 10 ** (-1 / 20) + 1e-3


def test_expand_word_uses_training_takes_only(household):
    record_takes(household, "robo", "kid", 6)
    rows = dataset.split_word(household, "robo")
    dataset.write_split(household, rows, "robo")
    written = expand.expand_word(household, "robo", per_take=2)
    train = [r for r in rows if r.split == "train"]
    assert len(written) == 2 * len(train)
    stems = {p.name.split("__")[0] for p in written}
    assert stems == {r.path.stem for r in train}
    assert all(p.parent == household.data_dir / "expanded" / "robo" / "kid" for p in written)
    # Rebuilt from scratch on the next run.
    again = expand.expand_word(household, "robo", per_take=1)
    assert len(list((household.data_dir / "expanded" / "robo").rglob("*.wav"))) == len(again)


def test_expand_word_rejects_wrong_rate(household):
    path = household.real_dir("robo", "kid") / "kid_000_near.wav"
    audio.write_wav(path, tone(0.5), rate=8000)
    dataset.write_split(household, [dataset.SplitRow(path, "robo", "kid", "child", "train")], "robo")
    with pytest.raises(ValueError, match="16000"):
        expand.expand_word(household, "robo")

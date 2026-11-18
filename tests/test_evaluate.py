import math

import numpy as np
import pytest

from wakeword import audio, dataset, evaluate
from wakeword.audio import SAMPLE_RATE

from .conftest import noise, record_takes, utterance


def test_window_means():
    probs = np.array([0, 1, 1, 1, 0], dtype=float)
    assert np.allclose(evaluate.window_means(probs, 3), [2 / 3, 1, 2 / 3])
    assert np.array_equal(evaluate.window_means(probs, 1), probs)
    assert evaluate.window_means(probs, 9).size == 0


def test_detections_with_refractory():
    probs = np.zeros(300)
    probs[10:15] = 1.0
    probs[20:25] = 1.0  # within 2 s of the first — same wake
    probs[200:205] = 1.0
    assert evaluate.detections(probs, 0.9, 5) == [14, 204]
    assert evaluate.detections(probs, 0.9, 5, refractory_steps=1) == [14, 24, 204]
    assert evaluate.detections(probs * 0.5, 0.9, 5) == []


def test_peak():
    assert evaluate.peak(np.array([0.2, 0.9, 1.0, 0.8]), 2) == pytest.approx(0.95)
    assert evaluate.peak(np.array([0.5]), 3) == 0.0


def take(speaker, group, peak):
    return evaluate.TakeScore(None, speaker, group, peak)


def test_frr_and_false_wakes():
    scores = [take("a", "adult", 0.99), take("a", "adult", 0.9), take("b", "child", 0.5)]
    assert evaluate.frr(scores, 0.95) == pytest.approx(2 / 3)
    assert math.isnan(evaluate.frr([], 0.9))
    probs = np.zeros(1000)
    probs[100:110] = 1
    bg = [evaluate.BackgroundScore(None, 0.5, probs)]
    assert evaluate.false_wakes_per_hour(bg, 0.9, 5) == 2.0
    assert math.isnan(evaluate.false_wakes_per_hour([], 0.9, 5))


def test_report_rows_and_recommendation():
    takes = [take("dad", "adult", 0.99), take("dad", "adult", 0.96),
             take("kid", "child", 0.94), take("kid", "child", 0.985)]
    probs = np.zeros(2000)
    probs[500:505] = 0.955  # one false wake below 0.96
    report = evaluate.Report("w", 5, takes, [evaluate.BackgroundScore(None, 1.0, probs)])
    rows = report.rows([0.9, 0.95, 0.97])
    assert rows[0]["frr"] == 0 and rows[0]["fa_per_hour"] == 1.0
    assert rows[2]["frr:dad"] == 0.5 and rows[2]["frr_child"] == 0.5
    assert report.recommend(max_frr=0.0, max_fa=1.0, cutoffs=[0.9, 0.95]) == 0.9
    assert report.recommend(max_frr=0.0, max_fa=0.5, cutoffs=[0.9, 0.95]) is None
    text = evaluate.format_report(report, [0.9, 0.95])
    assert "dad" in text and "kid" in text and "fa_per_hour" in text
    assert "recommended cutoff: none" in text


def test_recommend_without_background():
    report = evaluate.Report("w", 5, [take("dad", "adult", 0.99)], [])
    assert report.recommend(cutoffs=[0.9, 0.99]) == 0.9
    assert "—" in evaluate.format_report(report, [0.9])
    assert evaluate.format_report(report, []) == "no data"


class LoudnessModel:
    """Fake model: probability = how loud the step is (speech ≈ 1, silence ≈ 0)."""

    def probabilities(self, samples):
        step = SAMPLE_RATE * evaluate.STEP_MS // 1000
        n = len(samples) // step
        levels = np.sqrt(np.mean(samples[: n * step].reshape(n, step) ** 2, axis=1))
        return np.clip(levels * 10, 0, 1)


def test_evaluate_word_end_to_end(household):
    record_takes(household, "hey_tony", "dad", 4)
    record_takes(household, "hey_tony", "kid", 6)
    dataset.write_split(household, dataset.split_word(household, "hey_tony"), "hey_tony")
    audio.write_wav(household.data_dir / "background" / "tv.wav", noise(10.0, level=0.2))
    audio.write_wav(household.data_dir / "background" / "kitchen.wav", noise(10.0, level=0.2))
    report = evaluate.evaluate_word(LoudnessModel(), household, "hey_tony", window=3)
    assert {t.speaker for t in report.takes} == {"dad", "kid"}
    assert all(t.peak > 0.9 for t in report.takes)
    # only the test part of the home background: never trained on
    assert [b.path for b in report.backgrounds] == dataset.split_background(household)[1]
    assert report.backgrounds[0].hours == pytest.approx(10 / 3600)
    assert report.rows([0.9])[0]["fa_per_hour"] > 0


def test_background_split_keeps_test_recordings_out_of_training(household):
    from wakeword import augment, training_config

    assert dataset.BACKGROUND_FOLDER == augment.BACKGROUND_DIR
    folder = household.data_dir / "background"
    assert dataset.split_background(household) == ([], [])
    audio.write_wav(folder / "salon_1.wav", noise(1.0))
    assert dataset.split_background(household) == ([folder / "salon_1.wav"], [])  # a single one: for training
    for i in range(2, 13):
        audio.write_wav(folder / f"salon_{i}.wav", noise(1.0))
    train, test = dataset.split_background(household)
    assert test and train and not set(train) & set(test) and len(train) + len(test) == 12
    audio.write_wav(folder / "salon_13.wav", noise(1.0))  # a new recording does not move the old ones
    train2, test2 = dataset.split_background(household)
    assert set(test) <= set(test2) and set(train) <= set(train2)
    # the training config takes only the training part
    record_takes(household, "robo", "kid", 6)
    dataset.write_split(household, dataset.split_word(household, "robo"), "robo")
    sets = {s.name: s for s in training_config.feature_sets(household, "robo")}
    assert sorted(sets["background"].sources) == sorted(f"data/background/{f.name}" for f in train2)


def test_household_result_per_person_and_home_background():
    takes = [take("dad", "adult", 0.99), take("dad", "adult", 0.96), take("kid", "child", 0.94), take("kid", "child", 0.985)]
    probs = np.zeros(2000)
    probs[500:505] = 0.955  # one false wake below 0.96
    report = evaluate.Report("w", 5, takes, [evaluate.BackgroundScore(None, 0.5, probs)])
    result = evaluate.household_result(report, [0.90, 0.95, 0.96, 0.97])
    assert result["takes"] == {"dad": 2, "kid": 2} and result["hours"] == 0.5
    rows = {r["cutoff"]: r for r in result["curve"]}
    assert rows[0.95]["false_wakes"] == 1 and rows[0.95]["fa_per_day"] == 48.0  # 1 in half an hour
    assert rows[0.96]["false_wakes"] == 0 and rows[0.96]["missed"] == {"dad": 0, "kid": 1}
    # 0.96: kid misses 1 of 2 (50% = 10× the 5% goal) without false wakes; 0.95: 48 a day (48×)
    best = result["best"]
    assert best["cutoff"] == 0.96 and best["times"] == pytest.approx(10.0) and not best["ready"]
    perfect = evaluate.Report("w", 5, [take("dad", "adult", 0.99)], [evaluate.BackgroundScore(None, 1.0, np.zeros(100))])
    best = evaluate.household_result(perfect, [0.90, 0.95, 0.98])["best"]
    assert best["ready"] and best["cutoff"] == 0.98  # the same score: the highest cutoff (safest at home)
    assert evaluate.household_result(evaluate.Report("w", 5, [], []))["best"] is None


def test_evaluate_word_explicit_background(household):
    record_takes(household, "robo", "kid", 6)
    dataset.write_split(household, dataset.split_word(household, "robo"), "robo")
    report = evaluate.evaluate_word(LoudnessModel(), household, "robo", background=[])
    assert report.backgrounds == []


def test_tflite_model_needs_extras(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("pymicro_features"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="evaluate"):
        evaluate.TFLiteModel("x.tflite")

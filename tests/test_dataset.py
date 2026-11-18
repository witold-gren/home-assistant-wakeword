from pathlib import Path

import numpy as np
import pytest

from wakeword import audio, dataset
from wakeword.audio import SAMPLE_RATE
from wakeword.languages import TAKE_ORDER

from .conftest import noise, record_takes, silence, tone, utterance


def test_parse_take():
    take = dataset.parse_take(Path("x/daughter_1_007_far.wav"))
    assert (take.speaker, take.index, take.variant) == ("daughter_1", 7, "far")
    assert dataset.parse_take(Path("x/dad_007_other_side.wav")).variant == "other_side"
    assert dataset.parse_take(Path("x/jarvis_1.wav")) is None
    assert dataset.parse_take(Path("x/dad_7_far.wav")) is None


def test_next_take_follows_variant_order(household):
    first = dataset.next_take(household, "hey_tony", "dad")
    assert first.index == 0 and first.variant == TAKE_ORDER[0]
    assert first.path == household.real_dir("hey_tony", "dad") / "dad_000_near.wav"
    record_takes(household, "hey_tony", "dad", 2)
    second = dataset.next_take(household, "hey_tony", "dad")
    assert second.index == 2 and second.variant == TAKE_ORDER[2]
    assert dataset.next_take(household, "hey_tony", "dad", "imported").variant == "imported"


def test_list_takes_ignores_other_files(household):
    record_takes(household, "hey_tony", "dad", 3)
    folder = household.real_dir("hey_tony", "dad")
    (folder / "notes.txt").write_text("x")
    audio.write_wav(folder / "kid_000_near.wav", utterance())
    assert [t.index for t in dataset.list_takes(household, "hey_tony", "dad")] == [0, 1, 2]
    assert dataset.list_takes(household, "robo", "kid") == []


@pytest.mark.parametrize(
    "samples, rate, expected",
    [
        (utterance(), SAMPLE_RATE, []),
        (silence(1.0), SAMPLE_RATE, ["no_speech"]),
        (utterance(speech=0.1), SAMPLE_RATE, ["too_short"]),
        (utterance(speech=4.0), SAMPLE_RATE, ["too_long"]),
        (utterance(level=0.003), SAMPLE_RATE, ["too_quiet"]),
        (np.clip(utterance(level=3.0), -1, 1), SAMPLE_RATE, ["clipped"]),
        (audio.resample(utterance(), SAMPLE_RATE, 44100), 44100, ["wrong_rate"]),
        (utterance(pad=1.0) + noise(2.6, level=0.25), SAMPLE_RATE, ["too_noisy"]),
    ],
)
def test_quality_issues(samples, rate, expected):
    assert dataset.quality_issues(audio.analyze(samples, rate)) == expected


def test_prepare_take_trims_resamples_normalises():
    raw = np.concatenate([silence(2.0), utterance(level=0.1), silence(2.0)])
    raw44 = audio.resample(raw, SAMPLE_RATE, 44100)
    out = dataset.prepare_take(raw44, 44100)
    assert len(out) / SAMPLE_RATE < 2.0
    assert audio.dbfs(float(np.max(np.abs(out)))) == pytest.approx(-1.0, abs=0.1)
    assert dataset.prepare_take(silence(0.5), SAMPLE_RATE).size == silence(0.5).size


def test_save_take(household):
    take, issues = dataset.save_take(household, "hey_tony", "kid", utterance(), SAMPLE_RATE)
    assert issues == [] and take.path.exists()
    data, rate = audio.read_wav(take.path)
    assert rate == SAMPLE_RATE
    take, issues = dataset.save_take(household, "hey_tony", "kid", silence(1), SAMPLE_RATE)
    assert issues == ["no_speech"] and not take.path.exists()


def test_import_files(household, tmp_path):
    import soundfile as sf

    src = tmp_path / "memo.flac"
    sf.write(str(src), audio.resample(utterance(), SAMPLE_RATE, 48000), 48000)
    wav = audio.write_wav(tmp_path / "jarvis_1.wav", utterance())
    bad = tmp_path / "broken.m4a"
    bad.write_bytes(b"nope")
    results = dataset.import_files(household, "hey_tony", "dad", [src, wav, bad])
    assert [r[1].path.name if r[1] else None for r in results] == [
        "dad_000_imported.wav", "dad_001_imported.wav", None]
    assert results[2][2][0].startswith("unreadable")


def test_import_validates_word_and_speaker(household, tmp_path):
    with pytest.raises(ValueError, match="unknown word"):
        dataset.import_files(household, "nope", "dad", [])
    with pytest.raises(ValueError, match="does not use"):
        dataset.import_files(household, "robo", "dad", [])


def test_check_matrix(household):
    record_takes(household, "hey_tony", "dad", 4)
    record_takes(household, "hey_tony", "kid", 2)
    record_takes(household, "robo", "kid", 6)
    bad = household.real_dir("robo", "kid") / "kid_006_far.wav"
    audio.write_wav(bad, np.clip(utterance(level=3.0), -1, 1))
    (household.real_dir("robo", "kid") / "random.wav").write_bytes(b"x")
    report = dataset.check_household(household)
    assert report.cell("hey_tony", "dad").complete
    kid_tony = report.cell("hey_tony", "kid")
    assert (kid_tony.good, kid_tony.target, kid_tony.missing) == (2, 6, 4)
    assert report.cell("robo", "kid").good == 6
    assert ("robo", "dad") not in report.cells
    assert [p.take.path.name for p in report.problems()] == ["kid_006_far.wav"]
    assert [p.name for p in report.stray] == ["random.wav"]
    assert not report.complete

    matrix = dataset.format_matrix(report)
    lines = matrix.splitlines()
    assert lines[1].startswith("dad") and "4/4 ✓" in lines[1] and "—" in lines[1]
    assert "2/6" in lines[2] and "6/6 ✓" in lines[2]
    text = dataset.format_report(report)
    assert "kid / hey_tony: 4 more take(s)" in text
    assert "clipped" in text and "random.wav" in text


def test_check_unreadable_take(household):
    folder = household.real_dir("hey_tony", "dad")
    folder.mkdir(parents=True)
    (folder / "dad_000_near.wav").write_bytes(b"broken")
    report = dataset.check_household(household)
    assert report.cell("hey_tony", "dad").takes[0].issues == ["unreadable"]


def test_check_complete(household):
    record_takes(household, "hey_tony", "dad", 4)
    record_takes(household, "hey_tony", "kid", 6)
    record_takes(household, "robo", "kid", 6)
    report = dataset.check_household(household)
    assert report.complete
    assert "All recordings are complete." in dataset.format_report(report)


def test_missing_variants(household):
    for variant in ("near", "far"):
        take = dataset.next_take(household, "hey_tony", "dad", variant)
        audio.write_wav(take.path, utterance())
    cell = dataset.check_household(household).cell("hey_tony", "dad")
    assert cell.missing_variants == list(TAKE_ORDER[2:4])


def test_split_is_stable_and_per_person(household):
    record_takes(household, "hey_tony", "dad", 4)
    record_takes(household, "hey_tony", "kid", 6)
    rows = dataset.split_word(household, "hey_tony", seed=1)
    assert len(rows) == 10
    by = {(r.speaker, r.split) for r in rows}
    assert ("dad", "test") in by and ("kid", "test") in by
    assert sum(r.split == "test" for r in rows) == 2  # held_out=1 per person
    assert rows == dataset.split_word(household, "hey_tony", seed=1)
    assert {r.group for r in rows if r.speaker == "kid"} == {"child"}


def test_split_prefers_different_variants(household):
    for variant in ("near", "near", "far", "loud"):
        take = dataset.next_take(household, "hey_tony", "dad", variant)
        audio.write_wav(take.path, utterance())
    rows = dataset.split_word(household, "hey_tony", held_out=3)
    test = [r.path.name.split("_", 2)[2] for r in rows if r.split == "test"]
    assert sorted(test) == ["far.wav", "loud.wav", "near.wav"]


def test_split_keeps_one_for_training(household):
    record_takes(household, "hey_tony", "dad", 2)
    rows = dataset.split_word(household, "hey_tony", held_out=5)
    dad = [r.split for r in rows if r.speaker == "dad"]
    assert sorted(dad) == ["test", "train"]


def test_split_csv_roundtrip(household):
    record_takes(household, "robo", "kid", 6)
    rows = dataset.split_word(household, "robo")
    path = dataset.write_split(household, rows, "robo")
    assert path == household.data_dir / "splits" / "robo.csv"
    assert "data/real/robo/kid/" in path.read_text()
    assert dataset.read_split(household, "robo") == rows


def test_read_split_missing(household):
    with pytest.raises(FileNotFoundError, match="wakeword split"):
        dataset.read_split(household, "robo")


def test_save_take_from_other_rate_has_no_rate_issue(household):
    raw = audio.resample(utterance(), SAMPLE_RATE, 44100)
    take, issues = dataset.save_take(household, "hey_tony", "dad", raw, 44100)
    assert issues == [] and audio.read_wav(take.path)[1] == SAMPLE_RATE


def test_report_suggests_a_few_variants(household):
    text = dataset.format_report(dataset.check_household(household))
    assert "kid / robo: 6 more take(s) — e.g. near, far, quiet, loud …" in text

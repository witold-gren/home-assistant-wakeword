import numpy as np
import pytest

from wakeword import audio
from wakeword.audio import SAMPLE_RATE

from .conftest import noise, silence, tone, utterance


def test_write_read_roundtrip(tmp_path):
    samples = tone(0.5)
    path = audio.write_wav(tmp_path / "a" / "b.wav", samples)
    data, rate = audio.read_wav(path)
    assert rate == SAMPLE_RATE
    assert len(data) == len(samples)
    assert np.max(np.abs(data - samples)) < 1e-3


def test_read_stereo_is_mixed_to_mono(tmp_path):
    import soundfile as sf

    stereo = np.stack([tone(0.2), -tone(0.2)], axis=1)
    sf.write(str(tmp_path / "s.wav"), stereo, SAMPLE_RATE)
    data, _ = audio.read_wav(tmp_path / "s.wav")
    assert data.ndim == 1
    assert np.max(np.abs(data)) < 1e-3


def test_read_bad_file(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(audio.AudioError):
        audio.read_wav(bad)


def test_write_clips(tmp_path):
    path = audio.write_wav(tmp_path / "loud.wav", np.full(100, 3.0, dtype=np.float32))
    data, _ = audio.read_wav(path)
    assert np.max(data) <= 1.0


def test_resample():
    samples = tone(1.0, rate=48000)
    out = audio.resample(samples, 48000)
    assert len(out) == SAMPLE_RATE
    assert out.dtype == np.float32
    assert audio.resample(samples[:0], 48000).size == 0
    same = tone(0.1)
    assert np.array_equal(audio.resample(same, SAMPLE_RATE), same)


def test_dbfs():
    assert audio.dbfs(1.0) == 0.0
    assert audio.dbfs(0.1) == pytest.approx(-20.0)
    assert audio.dbfs(0.0) == float("-inf")


def test_frame_levels():
    levels = audio.frame_levels(np.concatenate([silence(0.1), tone(0.1, level=1.0)]))
    assert len(levels) == 10
    assert levels[0] < -150
    assert levels[-1] == pytest.approx(-3.0, abs=0.1)
    assert len(audio.frame_levels(tone(0.005))) == 1
    assert audio.frame_levels(np.zeros(0, dtype=np.float32))[0] == -np.inf


def test_speech_bounds_and_trim():
    samples = utterance(speech=0.6, pad=0.5)
    start, end = audio.speech_bounds(samples, pad_ms=0)
    assert 0.4 * SAMPLE_RATE < start < 0.6 * SAMPLE_RATE
    assert 1.0 * SAMPLE_RATE < end < 1.2 * SAMPLE_RATE
    trimmed = audio.trim_silence(samples, pad_ms=100)
    assert 0.5 < len(trimmed) / SAMPLE_RATE < 0.9


def test_silence_has_no_speech():
    assert audio.speech_bounds(silence(1.0)) == (0, 0)
    assert audio.speech_bounds(noise(1.0, level=1e-5)) == (0, 0)
    assert audio.trim_silence(silence(1.0)).size == 0
    assert audio.speech_bounds(np.zeros(0, dtype=np.float32)) == (0, 0)


def test_normalize_peak():
    out = audio.normalize_peak(tone(0.2, level=0.1), peak_db=-1.0)
    assert audio.dbfs(float(np.max(np.abs(out)))) == pytest.approx(-1.0, abs=0.05)
    zeros = silence(0.1)
    assert np.array_equal(audio.normalize_peak(zeros), zeros)


def test_analyze():
    stats = audio.analyze(utterance(level=0.3), SAMPLE_RATE)
    assert stats.duration == pytest.approx(1.6, abs=0.01)
    assert stats.peak_db == pytest.approx(audio.dbfs(0.3), abs=0.5)
    assert -30 < stats.rms_db < -10
    assert stats.clipped == 0
    assert 0.3 < stats.speech < 0.8
    assert not stats.is_silent


def test_analyze_clipped_and_silent():
    clipped = audio.analyze(np.clip(tone(0.5, level=2.0), -1, 1), SAMPLE_RATE)
    assert clipped.clipped > 0.3
    quiet = audio.analyze(silence(0.5), SAMPLE_RATE)
    assert quiet.is_silent
    empty = audio.analyze(np.zeros(0, dtype=np.float32), SAMPLE_RATE)
    assert empty.duration == 0 and empty.is_silent


@pytest.mark.skipif(not audio.ffmpeg_available(), reason="ffmpeg not installed")
def test_convert_to_wav(tmp_path):
    import soundfile as sf

    src = tmp_path / "in.flac"
    sf.write(str(src), np.stack([tone(0.5, rate=44100)] * 2, axis=1), 44100)
    dst = audio.convert_to_wav(src, tmp_path / "out" / "x.wav")
    info = sf.info(str(dst))
    assert (info.samplerate, info.channels, info.subtype) == (SAMPLE_RATE, 1, "PCM_16")


@pytest.mark.skipif(not audio.ffmpeg_available(), reason="ffmpeg not installed")
def test_convert_bad_input(tmp_path):
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"nope")
    with pytest.raises(audio.AudioError, match="ffmpeg failed"):
        audio.convert_to_wav(bad, tmp_path / "x.wav")


def test_convert_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: None)
    with pytest.raises(audio.AudioError, match="ffmpeg not found"):
        audio.convert_to_wav(tmp_path / "a.m4a", tmp_path / "a.wav")


def _word_in_noise(noise_level: float, extra_at: float | None = None) -> np.ndarray:
    """1 s silence-free background noise around a 0.6 s word at 1.0 s (and maybe a short knock)."""
    samples = noise(3.5, level=noise_level, seed=3)
    word = utterance(speech=0.6, pad=0.0)
    samples[16000:16000 + len(word)] += word
    if extra_at is not None:
        knock = utterance(speech=0.15, pad=0.0, freq=900.0)
        start = int(extra_at * SAMPLE_RATE)
        samples[start:start + len(knock)] += knock
    return samples


@pytest.mark.parametrize("level", [0.001, 0.01, 0.02])
def test_word_in_background_noise_is_not_the_whole_recording(level):
    stats = audio.analyze(_word_in_noise(level), SAMPLE_RATE)
    assert 0.3 < stats.speech < 0.8  # the word, not the 3.5 s of noise around it
    assert stats.snr_db > 10


def test_a_separate_sound_after_the_word_is_left_out():
    start, end = audio.speech_bounds(_word_in_noise(0.01, extra_at=2.6), pad_ms=0)
    assert end < 1.8 * SAMPLE_RATE


def test_word_drowned_in_noise():
    stats = audio.analyze(_word_in_noise(0.2), SAMPLE_RATE)
    assert stats.snr_db < audio.MIN_SNR_DB


def test_word_frames_keeps_a_pause_inside_the_word():
    levels = [-60.0] * 20 + [-10.0] * 10 + [-60.0] * 15 + [-12.0] * 20 + [-60.0] * 20  # "hej … dżarwis"
    assert audio.word_frames(levels) == (20, 64)
    levels = [-60.0] * 20 + [-10.0] * 10 + [-60.0] * 40 + [-30.0] * 5 + [-60.0] * 10  # word, then a far knock
    assert audio.word_frames(levels) == (20, 29)
    assert audio.word_frames([-80.0] * 10) is None and audio.word_frames([]) is None

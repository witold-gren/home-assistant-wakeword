"""The Wake Word Recorder integration (its own repository, home-assistant-wake-word-recorder) must
match the toolkit: take.py finds the word exactly like wakeword/audio.py, names takes the way the
dataset reads them, and reads the toolkit's household files - loaded here without Home Assistant.

Set WAKE_WORD_RECORDER to its folder; by default the repository next to this one. Without it these
tests are skipped."""

import importlib.util
import os
from pathlib import Path
import re
import sys
import types

import numpy as np
import pytest
import yaml

from wakeword import audio

from .conftest import noise, utterance

ROOT = Path(__file__).resolve().parent.parent
FOLDER = Path(
    os.environ.get(
        "WAKE_WORD_RECORDER",
        ROOT.parent / "home-assistant-wake-word-recorder" / "custom_components" / "wake_word_recorder",
    )
)
pytestmark = pytest.mark.skipif(not (FOLDER / "take.py").is_file(), reason=f"no Wake Word Recorder in {FOLDER}")


def _load_take():
    package = types.ModuleType("wwr_standalone")
    package.__path__ = [str(FOLDER)]
    sys.modules.setdefault("wwr_standalone", package)
    for name in ("household", "messages", "take"):
        full = f"wwr_standalone.{name}"
        if full not in sys.modules:
            spec = importlib.util.spec_from_file_location(full, FOLDER / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[full] = module
            spec.loader.exec_module(module)
    return sys.modules["wwr_standalone.take"]


def _module(name):
    _load_take()
    return sys.modules[f"wwr_standalone.{name}"]


def _to_pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2").tobytes()


def test_same_word_detection_as_the_integration():
    take = _load_take()
    word = utterance(speech=0.6, pad=0.0)
    knock = utterance(speech=0.15, pad=0.0, freq=900.0)
    cases = [utterance()]
    for level, extra in [(0.02, None), (0.01, 2.6), (0.001, 1.9), (0.3, None)]:
        samples = noise(4.0, level=level, seed=5)
        samples[16000:16000 + len(word)] += word
        if extra:
            samples[int(extra * 16000):int(extra * 16000) + len(knock)] += knock
        cases.append(samples)
    for samples in cases:
        pcm = _to_pcm(samples)
        floats = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        assert take.speech_bounds(take.to_samples(pcm), pad_ms=0) == audio.speech_bounds(floats, pad_ms=0)
        assert take.word_frames(take.frame_levels(take.to_samples(pcm))) == audio.word_frames(
            audio.frame_levels(floats).tolist())


def test_same_constants_as_the_integration():
    take = _load_take()
    for name in ("NOISE_PERCENTILE", "WORD_MARGIN_DB", "WORD_RANGE_DB", "WORD_GAP_FRAMES", "WORD_EDGE_DB",
                 "MIN_SNR_DB", "SILENCE_DB"):
        assert getattr(take, name) == getattr(audio, name), name
    assert take.MIN_SPEECH == 0.25 and take.MAX_SPEECH == 3.0


def test_same_takes_and_messages_as_the_toolkit():
    from wakeword import languages as toolkit_languages

    messages = _module("messages")
    assert messages.TAKE_ORDER == toolkit_languages.TAKE_ORDER


def test_take_names_are_read_by_the_dataset():
    toolkit = (ROOT / "wakeword" / "dataset.py").read_text()
    pattern = re.search(r'TAKE_PATTERN = re.compile\(r"(.+?)"\)', toolkit).group(1)
    assert pattern == _load_take().TAKE_PATTERN.pattern


@pytest.mark.parametrize("name", ["family", "single"])
def test_the_integration_reads_the_toolkit_examples(name):
    household = _module("household").load(ROOT / "households" / "examples" / name)
    assert household.words and household.speakers
    if name == "family":
        assert household.words["wajana"].speakers == ("daughter1", "daughter2", "mum")
        assert household.target("son") == 18
        assert household.words["dzarwis"].wake_word == "Dżarwis"


def test_a_household_created_by_the_integration_is_valid_for_the_toolkit(tmp_path):
    from wakeword.household import parse_household

    _module("household").create(tmp_path / "home", [("tomek", "adult"), ("ola", "child")], "pl")
    data = yaml.safe_load((tmp_path / "home" / "household.yaml").read_text())
    household = parse_household(data, tmp_path / "home", require_words=False)
    assert household.speakers["ola"].group == "child"

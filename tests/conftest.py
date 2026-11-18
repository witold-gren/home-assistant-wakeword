"""Shared fixtures: synthetic audio and small households."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from wakeword.audio import SAMPLE_RATE, write_wav


@pytest.fixture(autouse=True)
def no_home_assistant_of_this_computer(tmp_path_factory, monkeypatch):
    """The Home Assistant connection saved on this computer must not reach the tests (nor the real HA)."""
    from wakeword import ha_sync

    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path_factory.mktemp("ha") / "home_assistant.json")
    monkeypatch.delenv("WAKEWORD_HA_URL", raising=False)
    monkeypatch.delenv("WAKEWORD_HA_TOKEN", raising=False)
    # make exports the Home Assistant share's esphome folder for the Devices tab: never in tests
    monkeypatch.delenv("WAKEWORD_ESPHOME", raising=False)


@pytest.fixture(autouse=True)
def only_this_computer(monkeypatch):
    """Tests talk to fake servers on 127.0.0.1 only.

    Many tests save http://homeassistant.local:8123 with a made-up token; a request a test forgot to fake
    would reach the real Home Assistant, and every 401 is a failed login for its ip_ban.
    """
    import ipaddress
    from urllib import error, parse, request

    real_urlopen = request.urlopen

    def urlopen(url, *args, **kwargs):
        host = parse.urlsplit(url.full_url if isinstance(url, request.Request) else url).hostname or ""
        try:
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            raise error.URLError(f"tests never leave this computer ({host})")
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(request, "urlopen", urlopen)


def tone(seconds: float, freq: float = 440.0, level: float = 0.3, rate: int = SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(seconds: float, rate: int = SAMPLE_RATE) -> np.ndarray:
    return np.zeros(int(seconds * rate), dtype=np.float32)


def noise(seconds: float, level: float = 0.05, rate: int = SAMPLE_RATE, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (level * rng.standard_normal(int(seconds * rate))).astype(np.float32)


def utterance(speech: float = 0.6, pad: float = 0.5, level: float = 0.3, freq: float = 300.0) -> np.ndarray:
    """A fake take: silence, a 'word' (harmonic tone), silence."""
    t = np.arange(int(speech * SAMPLE_RATE)) / SAMPLE_RATE
    word = sum(np.sin(2 * np.pi * freq * k * t) / k for k in (1, 2, 3))
    word = (level * word / np.max(np.abs(word)) * np.hanning(len(t))).astype(np.float32)
    return np.concatenate([silence(pad), word, silence(pad)])


MINIMAL = {
    "ui_language": "en",
    "speakers": [
        {"id": "dad", "group": "adult"},
        {"id": "kid", "group": "child"},
    ],
    "words": {
        "hey_tony": {
            "wake_word": "Hey Tony",
            "spellings": {"en": ["hey tony", "hey toni"]},
            "sound_alikes": ["hey tommy"],
        },
        "robo": {
            "wake_word": "Robo",
            "speakers": ["kid"],
            "trained_languages": ["pl"],
            "spellings": {"pl": ["robo"], "en": ["robo"]},
        },
    },
    "targets": {"adult": 4, "child": 6, "held_out": 1},
    "devices": {"office-voice": ["hey_tony", "okay_nabu"], "kid-room": ["robo"]},
}


@pytest.fixture
def household_data() -> dict:
    import copy

    return copy.deepcopy(MINIMAL)


@pytest.fixture
def household_dir(tmp_path: Path, household_data: dict) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    (root / "household.yaml").write_text(yaml.safe_dump(household_data), encoding="utf-8")
    return root


@pytest.fixture
def household(household_dir: Path):
    from wakeword.household import load_household

    return load_household(household_dir)


def record_takes(household, word: str, speaker: str, count: int, **kwargs) -> list[Path]:
    """Write `count` fake takes of `word` by `speaker` into the household's data folder."""
    paths = []
    for i in range(count):
        path = household.real_dir(word, speaker) / f"{speaker}_{i:03d}_normal.wav"
        paths.append(write_wav(path, utterance(freq=200 + 10 * i, **kwargs)))
    return paths

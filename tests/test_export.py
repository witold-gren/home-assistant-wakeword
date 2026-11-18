import json

import pytest
import yaml

from wakeword import export
from wakeword.synthetic import build_dir


def test_manifest(household):
    data = export.manifest(household, "robo", cutoff=0.95, window=4, author="me")
    assert data == {
        "type": "micro",
        "wake_word": "Robo",
        "author": "me",
        "model": "robo.tflite",
        "trained_languages": ["pl"],
        "version": 2,
        "micro": {
            "probability_cutoff": 0.95,
            "sliding_window_size": 4,
            "feature_step_size": 10,
            "tensor_arena_size": export.TENSOR_ARENA_SIZE,
            "minimum_esphome_version": export.MINIMUM_ESPHOME_VERSION,
        },
    }
    assert export.manifest(household, "robo", website="https://x")["website"] == "https://x"
    assert export.manifest(household, "robo")["author"] == "home"


@pytest.mark.parametrize("kwargs", [{"cutoff": 1.0}, {"cutoff": 0}, {"window": 0}])
def test_manifest_validation(household, kwargs):
    with pytest.raises(ValueError):
        export.manifest(household, "robo", **kwargs)


def test_export_word(household, tmp_path):
    with pytest.raises(FileNotFoundError, match="train the model"):
        export.export_word(household, "robo")
    trained = build_dir(household, "robo") / export.TRAINED_MODEL
    trained.parent.mkdir(parents=True)
    trained.write_bytes(b"TFL3")
    tflite, manifest = export.export_word(household, "robo", cutoff=0.9)
    assert tflite.read_bytes() == b"TFL3"
    assert tflite.parent == household.data_dir / "export" / "wake_words"
    assert json.loads(manifest.read_text())["micro"]["probability_cutoff"] == 0.9
    other = tmp_path / "m.tflite"
    other.write_bytes(b"X")
    assert export.export_word(household, "robo", model=other)[0].read_bytes() == b"X"


def test_device_yaml(household):
    text = export.device_yaml(household, "office-voice")
    snippet = yaml.safe_load(text)
    assert snippet == {"micro_wake_word": {"models": [{"model": "wake_words/hey_tony.json", "id": "hey_tony"}]}}
    assert "assistant slot 1 wake word: Hey Tony" in text
    assert "assistant slot 2 wake word: Okay Nabu" in text
    remote = yaml.safe_load(export.device_yaml(household, "kid-room", "https://example.org/ww/"))
    assert remote["micro_wake_word"]["models"][0]["model"] == "https://example.org/ww/robo.json"


def test_device_yaml_stock_only(household_data, tmp_path):
    from wakeword.household import parse_household

    household_data["devices"] = {"hall": ["okay_nabu", "hey_jarvis"]}
    household = parse_household(household_data, tmp_path)
    text = export.device_yaml(household, "hall")
    assert yaml.safe_load(text) is None
    assert "nothing to add" in text


def test_write_device_snippets(household):
    paths = export.write_device_snippets(household)
    assert sorted(p.name for p in paths) == ["kid-room.yaml", "office-voice.yaml"]

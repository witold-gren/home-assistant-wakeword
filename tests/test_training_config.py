import json

import pytest
import yaml

from wakeword import dataset, training_config

from .conftest import record_takes


@pytest.fixture
def split(household):
    record_takes(household, "hey_tony", "dad", 4)
    record_takes(household, "hey_tony", "kid", 6)
    record_takes(household, "robo", "kid", 6)
    for word in household.words:
        dataset.write_split(household, dataset.split_word(household, word), word)
    return household


def by_name(sets):
    return {s.name: s for s in sets}


def test_feature_sets(split):
    sets = by_name(training_config.feature_sets(split, "hey_tony"))
    assert list(sets) == ["real", "expanded", "synthetic", "sound_alikes", "other_words",
                          "speech", "dinner_party", "no_speech", "dinner_party_eval"]
    real = sets["real"]
    assert real.truth and real.sampling_weight == 3.0
    assert len(real.sources) == 8  # 10 takes - 1 held out per person
    test = {r.path for r in dataset.read_split(split, "hey_tony") if r.split == "test"}
    assert not any(src in {p.relative_to(split.root).as_posix() for p in test} for src in real.sources)
    assert sets["other_words"].sources == ["data/real/robo", "data/synthetic/robo/positive"]
    assert not sets["sound_alikes"].truth
    assert sets["speech"].features_dir == "negative_datasets/speech"
    assert sets["real"].features_dir == "features/real"
    assert sets["dinner_party_eval"].sampling_weight == 0
    assert sets["dinner_party_eval"].truncation_strategy == "split"


def test_optional_sets(split):
    from wakeword import audio

    from .conftest import noise

    audio.write_wav(split.data_dir / "background" / "salon.wav", noise(1.0))  # one recording: for training
    (split.data_dir / "false_wakes" / "robo").mkdir(parents=True)
    names = [s.name for s in training_config.feature_sets(split, "robo")]
    assert "background" in names and "false_wakes" in names
    assert "sound_alikes" not in names  # robo has none


def test_errors(household, split):
    with pytest.raises(ValueError, match="unknown word"):
        training_config.feature_sets(split, "nope")


def test_no_training_takes(household):
    dataset.write_split(household, [], "robo")
    with pytest.raises(ValueError, match="no training takes"):
        training_config.feature_sets(household, "robo")


def test_write_build(split):
    paths = training_config.write_build(split, "hey_tony", steps=1234)
    params = yaml.safe_load(paths["training_parameters"].read_text())
    # three phases with a falling learning rate, the same weights in each
    assert params["training_steps"] == [617, 370, 247] and sum(params["training_steps"]) == 1234
    assert params["learning_rates"] == [0.001, 0.0003, 0.0001]
    assert params["negative_class_weight"] == [20, 20, 20] and params["positive_class_weight"] == [1, 1, 1]
    assert params["train_dir"] == "data/build/hey_tony/trained"
    first = params["features"][0]
    assert first == {"features_dir": "features/real", "sampling_weight": 3.0, "penalty_weight": 1.0,
                     "truth": True, "truncation_strategy": "truncate_start", "type": "mmap"}
    assert params["maximization_metric"] == "average_viable_recall"
    features = json.loads(paths["features"].read_text())
    assert features["word"] == "hey_tony"
    assert features["sets"][0]["repeat"] == 50
    assert features["sets"][-1]["precomputed"] is True
    assert paths["training_parameters"].read_text().startswith("# microWakeWord")


def test_changes_since_prepare_are_found(split):
    from dataclasses import replace

    from wakeword.household import load_household
    from wakeword.scaffold import read_raw, save_raw

    assert training_config.changed_since_prepare(split, "hey_tony") == []  # never prepared (or by an older panel)
    training_config.write_build(split, "hey_tony", steps=1234)
    assert training_config.changed_since_prepare(split, "hey_tony") == []
    data = read_raw(split.root)
    data["words"]["hey_tony"]["spellings"]["uk"] = ["hey toni"]  # e.g. a language added by mistake
    data["voices"] = {**(data.get("voices") or {}), "uk": ["uk_UA-lada-x_low"]}
    save_raw(split.root, data)
    changed = load_household(split.root)
    assert training_config.changed_since_prepare(changed, "hey_tony") == ["spellings", "voices"]
    edited = replace(split, words={**split.words, "hey_tony": replace(split.words["hey_tony"], sound_alikes=("hey pony", "hey tonik"))})
    assert training_config.changed_since_prepare(edited, "hey_tony") == ["sound_alikes"]

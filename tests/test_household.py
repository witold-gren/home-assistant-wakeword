from pathlib import Path

import pytest
import yaml

from wakeword.household import (
    HouseholdError,
    Targets,
    load_household,
    parse_household,
)

ROOT = Path(__file__).resolve().parent.parent


def test_load_minimal(household):
    assert household.name == "home"
    assert household.ui_language == "en"
    assert list(household.speakers) == ["dad", "kid"]
    assert household.speakers["kid"].group == "child"
    tony = household.words["hey_tony"]
    assert tony.speakers == ("dad", "kid")  # default: all
    assert tony.trained_languages == ("en",)  # default: first spellings language
    assert tony.spellings == {"en": ("hey tony", "hey toni")}
    assert tony.sound_alikes == ("hey tommy",)
    robo = household.words["robo"]
    assert robo.speakers == ("kid",)
    assert robo.trained_languages == ("pl",)
    assert robo.sound_alikes == ()
    assert household.targets == Targets(adult=4, child=6, held_out=1)
    assert household.devices == {"office-voice": ("hey_tony", "okay_nabu"), "kid-room": ("robo",)}


def test_paths_and_lookups(household):
    assert household.data_dir == household.root / "data"
    assert household.real_dir("robo") == household.root / "data" / "real" / "robo"
    assert household.real_dir("robo", "kid") == household.root / "data" / "real" / "robo" / "kid"
    assert [w.id for w in household.words_for("kid")] == ["hey_tony", "robo"]
    assert [w.id for w in household.words_for("dad")] == ["hey_tony"]
    assert [w.id for w in household.other_words("robo")] == ["hey_tony"]


def test_load_file_path(household_dir):
    assert load_household(household_dir / "household.yaml").root == household_dir


def test_missing_file(tmp_path):
    with pytest.raises(HouseholdError, match="no household.yaml in .*wakeword init.*-H"):
        load_household(tmp_path)


def test_targets_for_group():
    targets = Targets(adult=10, child=15)
    assert targets.for_group("adult") == 10
    assert targets.for_group("child") == 15


@pytest.mark.parametrize("name", ["family", "single"])
def test_examples_are_valid(name):
    household = load_household(ROOT / "households" / "examples" / name)
    assert household.words
    for device, words in household.devices.items():
        assert len(words) <= 2, device


def test_family_example_matches_the_story():
    household = load_household(ROOT / "households" / "examples" / "family")
    assert set(household.words["dzarwis"].speakers) == set(household.speakers)
    assert "son" in household.words["optimus_prime"].speakers
    assert {"daughter1", "daughter2"} <= set(household.words["wajana"].speakers)


def mutate(data, path, value):
    target = data
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


DELETE = object()


@pytest.mark.parametrize(
    "path, value, message",
    [
        (["speakers"], DELETE, "missing 'speakers'"),
        (["speakers"], [], "at least one speaker"),
        (["speakers", 0], "dad", "expected id and group"),
        (["speakers", 0, "id"], "Dad", "lowercase"),
        (["speakers", 0, "group"], "teen", "group 'teen'"),
        (["speakers", 1, "id"], "dad", "duplicate speaker"),
        (["words"], DELETE, "missing 'words'"),
        (["words"], ["hey_tony"], "expected a mapping"),
        (["words", "hey_tony", "speakers"], ["mum"], "unknown speaker"),
        (["words", "hey_tony", "spellings"], DELETE, "missing 'spellings'"),
        (["words", "hey_tony", "spellings"], {"en": []}, "list of texts"),
        (["words", "hey_tony", "spellings"], ["hey tony"], "language -> list"),
        (["words", "hey_tony", "wake_word"], DELETE, "missing 'wake_word'"),
        (["words", "hey_tony"], "Hey Tony", "expected settings"),
        (["words", "okay_nabu"], {"wake_word": "x", "spellings": {"en": ["x"]}}, "stock model"),
        (["words", "Bad-Id"], {"wake_word": "x", "spellings": {"en": ["x"]}}, "lowercase"),
        (["targets", "held_out"], 4, "held_out must be smaller"),
        (["targets", "adult"], "many", "targets"),
        (["devices", "Office Voice"], ["hey_tony"], "ESPHome device name"),
        (["devices", "office-voice"], ["hey_tony", "robo", "okay_nabu"], "at most 2"),
        (["devices", "office-voice"], ["hey_siri"], "unknown word"),
    ],
)
def test_invalid(household_data, tmp_path, path, value, message):
    with pytest.raises(HouseholdError, match=message):
        parse_household(mutate(household_data, path, value), tmp_path)


def test_no_words(household_data, tmp_path):
    household_data["words"] = {}
    with pytest.raises(HouseholdError, match="at least one word"):
        parse_household(household_data, tmp_path)


def test_top_level_not_mapping(tmp_path):
    with pytest.raises(HouseholdError, match="mapping"):
        parse_household(["x"], tmp_path)


def test_single_text_allowed(household_data, tmp_path):
    household_data["words"]["hey_tony"]["spellings"] = {"en": "hey tony"}
    household_data["devices"] = {"office-voice": "hey_tony"}
    household = parse_household(household_data, tmp_path)
    assert household.words["hey_tony"].spellings == {"en": ("hey tony",)}
    assert household.devices == {"office-voice": ("hey_tony",)}


def test_defaults_without_optional_sections(household_data, tmp_path):
    for key in ("targets", "devices", "ui_language"):
        del household_data[key]
    household = parse_household(household_data, tmp_path)
    assert household.targets == Targets()
    assert household.devices == {}
    assert household.ui_language == "en"


def test_yaml_roundtrip_of_examples_is_plain_yaml():
    text = (ROOT / "households" / "examples" / "family" / "household.yaml").read_text(encoding="utf-8")
    assert isinstance(yaml.safe_load(text), dict)

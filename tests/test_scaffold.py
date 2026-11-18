import pytest
import yaml

from wakeword import scaffold
from wakeword.household import HouseholdError, load_household


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "home"
    scaffold.init_household(root, [("dad", "adult"), ("ola", "child")], ui_language="pl")
    return root


def test_init(root):
    text = (root / "household.yaml").read_text()
    data = yaml.safe_load(text)
    assert data["ui_language"] == "pl"
    assert data["speakers"] == [{"id": "dad", "group": "adult"}, {"id": "ola", "group": "child"}]
    assert data["words"] == {} and data["devices"] == {}
    assert "# Household" in text
    assert (root / ".gitignore").read_text().strip().endswith("data/")


def test_init_errors(root, tmp_path):
    with pytest.raises(HouseholdError, match="already exists"):
        scaffold.init_household(root, [("x", "adult")])
    with pytest.raises(HouseholdError, match="at least one speaker"):
        scaffold.init_household(tmp_path / "b", [])
    with pytest.raises(HouseholdError, match="group"):
        scaffold.init_household(tmp_path / "c", [("x", "teen")])
    assert not (tmp_path / "c").exists()


def test_add_word_speaker_device(root):
    scaffold.add_word(root, "wajana", "Wajana", {"pl": ["wajana"], "en": ["vaiana"]},
                      speakers=["ola"], sound_alikes=["banana"])
    scaffold.add_word(root, "dzarwis", "Dżarwis", {"pl": ["dżarwis"]}, trained_languages=["pl"])
    scaffold.add_speaker(root, "mum", "adult", words=["wajana"])
    household = scaffold.set_device(root, "girls-voice", ["dzarwis", "wajana"])
    assert household.words["wajana"].speakers == ("ola", "mum")
    assert household.words["dzarwis"].speakers == ("dad", "ola", "mum")  # "all" includes newcomers
    assert household.words["wajana"].sound_alikes == ("banana",)
    assert household.devices == {"girls-voice": ("dzarwis", "wajana")}
    assert load_household(root).words["dzarwis"].wake_word == "Dżarwis"
    assert (root / "household.yaml.bak").exists()
    assert "Dżarwis" in (root / "household.yaml").read_text(encoding="utf-8")


def test_invalid_changes_are_not_saved(root):
    before = (root / "household.yaml").read_text()
    with pytest.raises(HouseholdError, match="duplicate"):
        scaffold.add_speaker(root, "dad")
    with pytest.raises(HouseholdError, match="unknown word"):
        scaffold.add_speaker(root, "mum", words=["nope"])
    with pytest.raises(HouseholdError, match="at most 2"):
        scaffold.set_device(root, "x", ["okay_nabu", "hey_jarvis", "alexa"])
    assert (root / "household.yaml").read_text() == before


def test_duplicate_word(root):
    scaffold.add_word(root, "w", "W", {"en": ["w"]})
    with pytest.raises(HouseholdError, match="already exists"):
        scaffold.add_word(root, "w", "W", {"en": ["w"]})


def test_update_missing(tmp_path):
    with pytest.raises(HouseholdError, match="wakeword init"):
        scaffold.add_speaker(tmp_path, "x")


def test_add_speaker_before_any_word(root):
    household = scaffold.add_speaker(root, "mum")
    assert list(household.speakers) == ["dad", "ola", "mum"] and household.words == {}


def test_word_id():
    assert scaffold.word_id("Dżarwis") == "dzarwis"
    assert scaffold.word_id("Optimus Prime") == "optimus_prime"
    assert scaffold.word_id("Hej, Żółwiu!") == "hej_zolwiu"
    assert scaffold.word_id("!!!") == "word"


def test_read_and_save_raw(root):
    scaffold.add_word(root, "wajana", "Wajana", {"pl": ["wajana"], "en": "vaiana"}, speakers=["ola"],
                      sound_alikes=["banana"])
    data = scaffold.read_raw(root)
    assert data["speakers"] == [{"id": "dad", "group": "adult"}, {"id": "ola", "group": "child"}]
    assert data["words"]["wajana"] == {"wake_word": "Wajana", "trained_languages": ["pl"], "speakers": ["ola"],
                                       "spellings": {"pl": ["wajana"], "en": ["vaiana"]}, "sound_alikes": ["banana"]}
    assert data["targets"] == {"adult": 12, "child": 18, "held_out": 3}
    data["speakers"].append({"id": "mum", "group": "adult"})
    data["words"]["wajana"]["speakers"] = ["ola", "mum"]
    data["words"]["wajana"]["spellings"]["en"] = ["  ", "vaiana "]
    data["words"]["dzarwis"] = {"wake_word": "Dżarwis", "speakers": "all", "spellings": {"pl": ["dżarwis"], "en": []},
                                "sound_alikes": ["", "darwin"], "trained_languages": ["pl"]}
    data["devices"] = {"girls-voice": ["dzarwis", "wajana"], "empty": [""]}
    household = scaffold.save_raw(root, data)
    assert household.words["wajana"].speakers == ("ola", "mum")
    assert household.words["dzarwis"].spellings == {"pl": ("dżarwis",)}
    assert household.words["dzarwis"].sound_alikes == ("darwin",)
    assert household.devices == {"girls-voice": ("dzarwis", "wajana")}
    assert (root / "household.yaml.bak").exists()
    assert scaffold.read_raw(root)["words"]["wajana"]["spellings"]["en"] == ["vaiana"]


def test_save_raw_rejects_invalid(root):
    data = scaffold.read_raw(root)
    before = (root / "household.yaml").read_text()
    data["devices"] = {"x": ["okay_nabu", "hey_jarvis", "alexa"]}
    with pytest.raises(HouseholdError, match="at most 2"):
        scaffold.save_raw(root, data)
    data["devices"] = {}
    data["speakers"].append({"id": "Bad Id", "group": "adult"})
    with pytest.raises(HouseholdError, match="lowercase"):
        scaffold.save_raw(root, data)
    assert (root / "household.yaml").read_text() == before


def test_read_raw_missing(tmp_path):
    with pytest.raises(HouseholdError, match="wakeword init"):
        scaffold.read_raw(tmp_path)


def test_esphome_devices_reads_names_from_yaml(tmp_path):
    from wakeword.scaffold import esphome_devices

    (tmp_path / "home-assistant-voice-1a2b3c.yaml").write_text(
        'substitutions:\n  name: salon-ha-voice\n  friendly_name: "Salon Voice"\n'
        "packages:\n  voice: github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml\n"
        "esphome:\n  name: ${name}\n  friendly_name: ${friendly_name}\n", encoding="utf-8")
    (tmp_path / "onju.yaml").write_text("esphome:\n  name: onju  # comment\nmicro_wake_word:\n", encoding="utf-8")
    (tmp_path / "coffee.yaml").write_text("esphome:\n  name: coffee\n", encoding="utf-8")
    (tmp_path / "secrets.yaml").write_text("wifi: !secret x\n", encoding="utf-8")

    assert esphome_devices(tmp_path) == [
        {"name": "salon-ha-voice", "friendly_name": "Salon Voice",
         "file": "home-assistant-voice-1a2b3c.yaml"},
        {"name": "onju", "friendly_name": "onju", "file": "onju.yaml"},
    ]
    assert esphome_devices(tmp_path / "missing") == []


def test_rename_word_moves_recordings_and_prepared_data(root):
    scaffold.add_word(root, "dzarwis", "Dżarwis", {"pl": ["dżarwis"]})
    scaffold.add_word(root, "wajana", "Wajana", {"pl": ["wajana"]})
    scaffold.set_device(root, "salon", ["dzarwis", "wajana"])
    data = root / "data"
    (data / "real" / "dzarwis" / "dad").mkdir(parents=True)
    (data / "real" / "dzarwis" / "dad" / "dad_000_near.wav").write_bytes(b"x")
    (data / "real" / "recordings.csv").write_text(
        "time,file,word,speaker,satellite\n"
        "t1,data/real/dzarwis/dad/dad_000_near.wav,dzarwis,dad,sat\n"
        "t2,data/real/wajana/ola/ola_000_near.wav,wajana,ola,sat\n", encoding="utf-8")
    (data / "build" / "dzarwis" / "models" / "20261029-174914").mkdir(parents=True)
    (data / "build" / "dzarwis" / "features.json").write_text('{"sources": ["data/real/dzarwis"]}', encoding="utf-8")
    (data / "elevenlabs" / "dzarwis" / "kuba-o11yegU3_00").mkdir(parents=True)
    (data / "elevenlabs" / "dzarwis" / "kuba-o11yegU3_00" / "00000.wav").write_bytes(b"paid for")
    (data / "synthetic" / "dzarwis" / "positive").mkdir(parents=True)
    (data / "splits").mkdir()
    (data / "splits" / "dzarwis.csv").write_text("path\n", encoding="utf-8")

    household = scaffold.rename_word(root, "dzarwis", "hej_jarvis")

    assert list(household.words) == ["hej_jarvis", "wajana"]  # order kept
    assert household.words["hej_jarvis"].wake_word == "Dżarwis"
    assert household.devices == {"salon": ("hej_jarvis", "wajana")}
    assert (data / "real" / "hej_jarvis" / "dad" / "dad_000_near.wav").exists()
    assert not (data / "real" / "dzarwis").exists()
    log = (data / "real" / "recordings.csv").read_text(encoding="utf-8").splitlines()
    assert log[1] == "t1,data/real/hej_jarvis/dad/dad_000_near.wav,hej_jarvis,dad,sat"
    assert log[2].endswith("wajana,ola,sat")
    assert not (data / "build" / "dzarwis").exists() and not (data / "splits" / "dzarwis.csv").exists()
    # ElevenLabs takes (paid for), kept models and synthetic speech follow the new id
    assert (data / "elevenlabs" / "hej_jarvis" / "kuba-o11yegU3_00" / "00000.wav").read_bytes() == b"paid for"
    assert (data / "build" / "hej_jarvis" / "models" / "20261029-174914").is_dir()
    assert (data / "synthetic" / "hej_jarvis" / "positive").is_dir()
    assert not (data / "elevenlabs" / "dzarwis").exists() and not (data / "synthetic" / "dzarwis").exists()
    # what Prepare wrote has the old id inside: aside, so the word is prepared again
    assert not (data / "build" / "hej_jarvis" / "features.json").exists()
    backup = next((data / "backup").iterdir())
    assert backup.name.startswith("renamed-dzarwis-")
    assert (backup / "build" / "dzarwis" / "features.json").is_file() and (backup / "splits" / "dzarwis.csv").exists()


def test_rename_word_errors(root):
    scaffold.add_word(root, "dzarwis", "Dżarwis", {"pl": ["dżarwis"]})
    scaffold.add_word(root, "wajana", "Wajana", {"pl": ["wajana"]})
    with pytest.raises(HouseholdError, match="unknown word"):
        scaffold.rename_word(root, "nope", "x")
    with pytest.raises(HouseholdError, match="lowercase"):
        scaffold.rename_word(root, "dzarwis", "Hej Jarvis")
    with pytest.raises(HouseholdError, match="already exists"):
        scaffold.rename_word(root, "dzarwis", "wajana")
    (root / "data" / "real" / "hej").mkdir(parents=True)
    with pytest.raises(HouseholdError, match="data/real/hej already exists"):
        scaffold.rename_word(root, "dzarwis", "hej")
    (root / "data" / "elevenlabs" / "hej2").mkdir(parents=True)  # takes of the new id would be mixed
    with pytest.raises(HouseholdError, match="data/elevenlabs/hej2 already exists"):
        scaffold.rename_word(root, "dzarwis", "hej2")
    assert list(load_household(root).words) == ["dzarwis", "wajana"]


def test_save_raw_keeps_the_order_of_people_and_words(root):
    scaffold.add_word(root, "dzarwis", "Dżarwis", {"pl": ["dżarwis"]})
    scaffold.add_word(root, "wajana", "Wajana", {"pl": ["wajana"]}, speakers=["dad", "ola"])
    data = scaffold.read_raw(root)
    data["speakers"].reverse()
    data["words"] = {"wajana": data["words"]["wajana"], "dzarwis": data["words"]["dzarwis"]}
    data["words"]["wajana"]["speakers"] = ["ola", "dad"]
    scaffold.save_raw(root, data)

    saved = yaml.safe_load((root / "household.yaml").read_text(encoding="utf-8"))
    assert [s["id"] for s in saved["speakers"]] == ["ola", "dad"]
    assert list(saved["words"]) == ["wajana", "dzarwis"]
    assert saved["words"]["wajana"]["speakers"] == ["ola", "dad"]
    assert list(load_household(root).words) == ["wajana", "dzarwis"]

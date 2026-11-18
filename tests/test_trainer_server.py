import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from wakeword.trainer import server as server_module
from wakeword.trainer.server import Trainer

from .conftest import record_takes
from .test_trainer_runner import fake_repo

LOG = Path(__file__).parent / "trainer_log.txt"


def wait(predicate, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def local(tmp_path, household_dir, monkeypatch):
    monkeypatch.setattr(server_module, "POLL_SECONDS", 0)
    repo = fake_repo(tmp_path, f'echo "args: $*"; cat "{LOG}"; sleep "${{SLEEP:-0}}"\n')
    return Trainer(household_dir, repo=repo)


def test_state_and_words(local, household):
    record_takes(household, "robo", "kid", 6)
    state = local.state()
    assert state["household"]["name"] == "home"
    assert state["ui"]["start"] == "Start training"
    assert "config" not in state and "access" not in state  # no SSH machine, no panel token (1.0.0)
    assert [w["id"] for w in state["words"]] == ["hey_tony", "robo"]
    assert state["words"][0] == {"id": "hey_tony", "wake_word": "Hey Tony", "speakers": ["dad", "kid"],
                                 "takes": {"dad": [0, 4], "kid": [0, 6]}, "complete": False,
                                 "prepared": False, "trained": False, "steps": None,
                                 "negative_weight": None, "model": None}
    json.dumps(state)


def test_training_run_is_followed(local, household):
    local.start(["robo"], 1000, False)
    assert wait(lambda: local.state()["training"]["progress"]["words"].get("dzarwis", {}).get("stage") == "done")
    state = local.state()
    assert state["training"]["log"].startswith("args: ")
    assert "robo" in state["training"]["log"].splitlines()[0]
    words = state["training"]["progress"]["words"]
    assert words["dzarwis"]["recommended_cutoff"] == 0.97
    assert wait(lambda: not local.state()["training"]["running"])


def test_cannot_start_twice_and_stop(local, monkeypatch):
    monkeypatch.setenv("SLEEP", "30")
    local.start([], None, False)
    assert wait(lambda: local.poll(force=True)["running"])
    with pytest.raises(RuntimeError, match="already running"):
        local.start([], None, False)
    local.stop()
    assert wait(lambda: not local.poll(force=True)["running"])


def test_start_validation(local):
    with pytest.raises(ValueError, match="unknown word"):
        local.start(["nope"], None, False)
    with pytest.raises(ValueError, match="steps"):
        local.start(["robo"], 5, False)
    with pytest.raises(ValueError, match="negative weight"):
        local.start(["robo"], None, False, 500)


def test_jobs(local):
    local.check()
    assert wait(lambda: not local.job.running)
    assert any(line.startswith("host:") for line in local.job.lines) and local.job.code == 0
    local.prepare([], force=False)  # incomplete recordings -> wakeword exits with 1
    assert wait(lambda: not local.job.running, 30)
    assert local.job.code == 1 and any("not complete" in line for line in local.job.lines)
    with pytest.raises(RuntimeError, match="no trained model"):
        local.export(0.97)
    with pytest.raises(ValueError):
        local.export(1.5)
    with pytest.raises(ValueError, match="unknown word"):
        local.evaluate("nope")


def test_one_job_at_a_time(local, tmp_path):
    local._start_job("slow", [["sleep", "2"]])
    with pytest.raises(RuntimeError, match="still running"):
        local.check()


def test_job_with_missing_program(local):
    local._start_job("broken", [["/nonexistent/program"]])
    assert wait(lambda: not local.job.running)
    assert local.job.code == 127






def test_action_dispatch(local):
    with pytest.raises(ValueError, match="unknown action"):
        local.action({"action": "dance"})
    local.action({"action": "check"})
    assert local.job.name == "check"




class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def call(url, data=None, cookie=None):
    request = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                     method="POST" if data is not None else "GET")
    if cookie:
        request.add_header("Cookie", cookie)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()










def test_language_switch(local):
    assert local.state()["language"] == "en"  # ui_language of the household
    polish = local.state("pl")
    assert polish["language"] == "pl" and polish["ui"]["start"] == "Rozpocznij trening"
    assert polish["languages"] == ["en", "pl"]
    assert local.state("xx")["language"] == "en"
    assert polish["ui"]["stop"] == "Zatrzymaj"


def test_prepare_selected_words(local, monkeypatch):
    started = {}
    monkeypatch.setattr(local, "_start_job", lambda name, commands: started.update(commands=commands))
    local.prepare(["robo"], force=True)
    assert started["commands"][0][-3:] == ["prepare", "robo", "--force"]
    local.prepare([], force=False)
    assert started["commands"][0][-2:] == ["prepare", "--all"]
    with pytest.raises(ValueError, match="unknown word"):
        local.prepare(["nope"], force=False)


def test_help_texts_in_state(local):
    state = local.state("pl")
    assert set(state["help"]) == {"household", "machine", "words", "data", "training", "results", "live", "progress", "models",
                                  "log"}
    assert "Docker" in state["help"]["machine"] and state["ui"]["help"] == "Co się tutaj dzieje?"
    for text in state["help"].values():  # the studio trains on this machine: no SSH, no copying (1.0.0)
        assert "ssh-copy-id" not in text and "rsync" not in text








def test_household_editing(local, household):
    record_takes(household, "robo", "kid", 2)
    data = local.household_data()
    assert data["exists"] and data["counts"]["robo"] == {"dad": 0, "kid": 2}
    assert "pl" in data["languages"] and "okay_nabu" in data["stock_words"] and data["groups"] == ["adult", "child"]
    edited = data["data"]
    edited["speakers"].append({"id": "mum", "group": "adult"})
    edited["words"]["dzarwis"] = {"wake_word": "Dżarwis", "trained_languages": ["pl"], "speakers": ["mum", "dad"],
                                  "spellings": {"pl": ["dżarwis"]}, "sound_alikes": []}
    edited["devices"]["bedroom"] = ["dzarwis", "okay_nabu"]
    local.save_household(edited)
    assert [w["id"] for w in local.words()] == ["hey_tony", "robo", "dzarwis"]
    assert local.household_data()["data"]["words"]["dzarwis"]["speakers"] == ["mum", "dad"]
    edited["devices"]["bedroom"] = ["dzarwis", "okay_nabu", "alexa"]
    with pytest.raises(ValueError, match="at most 2"):
        local.save_household(edited)


def test_household_without_words_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "POLL_SECONDS", 0)
    home = tmp_path / "home"
    trainer = Trainer(home, repo=tmp_path)  # no household.yaml yet
    state = trainer.state()
    assert state["household"]["exists"] is False and state["words"] == [] and state["language"] == "pl"
    assert trainer.household_data()["exists"] is False
    with pytest.raises(RuntimeError, match="create the household"):
        trainer.evaluate("x")
    # created in the panel with people only (as the HA integration does)
    trainer.save_household({"ui_language": "pl", "speakers": [{"id": "tomek", "group": "adult"}], "words": {},
                            "targets": {"adult": 12, "child": 18, "held_out": 3}, "devices": {}})
    assert trainer.state()["household"]["exists"] is True
    assert trainer.household_data()["data"]["speakers"] == [{"id": "tomek", "group": "adult"}]






def test_household_lists_esphome_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "POLL_SECONDS", 0)
    (tmp_path / "esphome").mkdir()
    (tmp_path / "esphome" / "salon.yaml").write_text(
        "substitutions:\n  name: salon-ha-voice\n  friendly_name: Salon\nvoice_assistant:\n", encoding="utf-8")
    trainer = Trainer(tmp_path / "wakeword", repo=tmp_path)  # household folder next to esphome
    assert trainer.household_data()["esphome"] == [
        {"name": "salon-ha-voice", "friendly_name": "Salon", "file": "salon.yaml"}]
    assert trainer.state("pl")["ui"]["title"] == "Home Assistant Wakeword"


def test_rename_word_action(local, household):
    record_takes(household, "robo", "kid", 2)
    local.action({"action": "rename_word", "word": "robo", "new_id": "robot"})
    assert local.household_data()["counts"]["robot"] == {"dad": 0, "kid": 2}
    with pytest.raises(ValueError, match="unknown word"):
        local.action({"action": "rename_word", "word": "robo", "new_id": "x"})




def test_words_report_missing_takes(local, household):
    words = {w["id"]: w for w in local.words()}
    assert words["robo"]["takes"] == {"kid": [0, 6]} and words["robo"]["complete"] is False
    record_takes(household, "robo", "kid", 6)
    words = {w["id"]: w for w in local.words()}
    assert words["robo"]["takes"] == {"kid": [6, 6]} and words["robo"]["complete"] is True


def test_whole_training_log_for_copying(local):
    """The page shows the last 160 lines; the copy button gets all of it, progress bars resolved."""
    lines = [f"line {i}" for i in range(500)]
    local.log.extend(("\n".join(lines) + "\nVal 1/10\rVal 10/10\n").encode())
    text = local.training_log()
    assert text.splitlines()[:2] == ["line 0", "line 1"] and "line 499" in text
    assert "Val 10/10" in text and "Val 1/10" not in text




def test_hf_token_action(local, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    token = "hf_" + "Zz9" * 10
    local.action({"action": "hf_token", "token": f"  {token}\n"})
    path = tmp_path / ".cache" / "huggingface" / "token"
    assert path.read_text() == token
    assert local.state()["training"]["hf_token"] is True
    with pytest.raises(ValueError) as err:
        local.action({"action": "hf_token", "token": "my-password-123"})
    assert "my-password-123" not in str(err.value)  # the value is never echoed
    local.action({"action": "hf_token", "token": ""})
    assert not path.exists()
    assert local.poll(force=True)["hf_token"] is False
    assert token not in json.dumps(local.state())  # the panel state never carries the token


def test_hf_voices_lists_piper_voices_of_a_repository(local, monkeypatch):
    import io

    tree = [{"type": "file", "path": "pl_PL-meski_wg_glos-medium.onnx"},
            {"type": "file", "path": "pl_PL-meski_wg_glos-medium.onnx.json"},
            {"type": "file", "path": "lonely.onnx"}, {"type": "file", "path": "README.md"},
            {"type": "directory", "path": "old"}]
    opened = []

    def urlopen(url, timeout):
        opened.append(url)
        return io.BytesIO(json.dumps(tree).encode())

    monkeypatch.setattr(server_module.urllib.request, "urlopen", urlopen)
    assert local.hf_voices("https://huggingface.co/WitoldG/polish_piper_models/") == [
        "WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium"]
    assert opened == ["https://huggingface.co/api/models/WitoldG/polish_piper_models/tree/main"]
    with pytest.raises(ValueError, match="owner/name"):
        local.hf_voices("not a repo")
    tree[:] = [{"type": "file", "path": "README.md"}]
    with pytest.raises(ValueError, match="no Piper voices"):
        local.hf_voices("someone/empty")
    assert local.household_data()["default_voices"]["pl"][0] == "pl_PL-gosia-medium"








def test_elevenlabs_actions(local, monkeypatch, tmp_path):
    from wakeword import elevenlabs

    monkeypatch.setattr(elevenlabs, "KEY_FILE", tmp_path / "key.json")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert local.state()["elevenlabs_key"] is False
    word = next(iter(local._require().words))
    with pytest.raises(ValueError, match="API key"):
        local.elevenlabs_generate([word])
    local.action({"action": "elevenlabs_key", "key": "sk_" + "b" * 40})
    state = local.state()
    assert state["elevenlabs_key"] is True and "sk_" not in json.dumps(state)  # never sent back

    started = {}
    monkeypatch.setattr(local, "_start_job", lambda name, commands: started.update(name=name, commands=commands))
    local.action({"action": "elevenlabs_generate", "words": [word]})
    assert started["name"] == "elevenlabs" and started["commands"][0][-2:] == ["elevenlabs", word]
    with pytest.raises(ValueError, match="unknown word"):
        local.elevenlabs_generate(["nope"])

    spoken = {}
    monkeypatch.setattr(elevenlabs, "client", lambda key=None: "api")
    monkeypatch.setattr(elevenlabs, "speak", lambda api, voice, text, model, variant, seed, language=None:
                        spoken.update(voice=voice, text=text, model=model, language=language) or np.zeros(1600))
    language, texts = next(iter(local._require().words[word].spellings.items()))
    audio = local.elevenlabs_test("abcdefgh1234", word, language, "eleven_v3")
    assert audio[:4] == b"RIFF" and spoken == {"voice": "abcdefgh1234", "text": texts[0], "model": "eleven_v3",
                                               "language": language}
    with pytest.raises(ValueError, match="voice id"):
        local.elevenlabs_test("../etc", word, language, "eleven_v3")
    with pytest.raises(ValueError, match="model"):
        local.elevenlabs_test("abcdefgh1234", word, language, "gpt")

    def refused(*args, **kwargs):
        raise elevenlabs.ApiError("ElevenLabs 400: Voice 'brokenvoice1' is not fine-tuned and cannot be used.", 400)

    monkeypatch.setattr(elevenlabs, "speak", refused)
    with pytest.raises(RuntimeError, match="fine-tuned"):
        local.elevenlabs_test("brokenvoice1", word, language, "eleven_v3")
    assert "fine-tuned" in local.state()["elevenlabs_account"]["broken"]["brokenvoice1"]["reason"]  # marked in the list
    assert local.elevenlabs_voices("pl") == []  # nothing synchronised yet
    with pytest.raises(ValueError, match="Voice Library"):
        local.elevenlabs_add("abcdefgh1234", "pl")


def test_home_assistant_connection_pull_and_household_sent(local, household_dir, tmp_path, monkeypatch):
    from wakeword import ha_sync
    from wakeword.scaffold import read_raw

    from .test_ha_sync import TOKEN, FakeHa

    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")
    monkeypatch.delenv("WAKEWORD_HA_URL", raising=False)
    monkeypatch.delenv("WAKEWORD_HA_TOKEN", raising=False)
    ha = FakeHa(tmp_path / "ha")
    try:
        assert local.state()["home_assistant"]["token"] is False
        with pytest.raises(ValueError, match="address and token"):
            local.ha_pull()
        started = {}
        monkeypatch.setattr(local, "_start_job", lambda name, commands: started.update(name=name, commands=commands))
        local.action({"action": "prepare", "words": []})
        assert len(started["commands"]) == 1  # no Home Assistant: Prepare only

        local.action({"action": "ha_connection", "url": ha.url, "token": TOKEN})
        state = local.state()["home_assistant"]
        assert state["url"] == ha.url and state["token"] is True and TOKEN not in json.dumps(local.state())
        local.action({"action": "ha_connection", "url": ha.url})  # the address again: the token stays
        assert ha_sync.load_connection().token == TOKEN

        local.action({"action": "prepare", "words": []})
        assert [c[-2:] for c in started["commands"][:1]] == [["ha-pull", "--optional"]]
        local.action({"action": "ha_pull"})
        assert started["name"] == "ha_pull" and [c[-1] for c in started["commands"]] == ["ha-push", "ha-pull"]

        # a save here goes to Home Assistant too; when it cannot, it is saved here and said so
        assert local.save_household(read_raw(household_dir)) is None and "speakers" in ha.put
        ha_sync.save_connection("http://127.0.0.1:9", None)
        warning = local.save_household(read_raw(household_dir))
        assert "cannot be reached" in warning and (household_dir / "household.yaml").is_file()

        # a new id of a word goes there too: Home Assistant must not keep asking for the old one
        ha_sync.save_connection(ha.url, None)
        old = next(iter(read_raw(household_dir)["words"]))
        assert local.action({"action": "rename_word", "word": old, "new_id": "hej_optimus"}) is None
        assert "hej_optimus:" in ha.put and f"{old}:" not in ha.put
        ha_sync.save_connection("http://127.0.0.1:9", None)
        warning = local.action({"action": "rename_word", "word": "hej_optimus", "new_id": "optimus"})
        assert "cannot be reached" in warning and "optimus" in read_raw(household_dir)["words"]
    finally:
        ha.server.shutdown()


def test_learning_rates_checked_before_training(local, monkeypatch):
    started = {}
    monkeypatch.setattr(local.runner(), "start", lambda *args, **kwargs: started.update(args=args, kwargs=kwargs))
    word = next(iter(local._require().words))
    for bad in ([0.5], [0.001] * 5, [0]):
        with pytest.raises(ValueError, match="learning rate"):
            local.action({"action": "start", "words": [word], "learning_rates": bad})
    local.action({"action": "start", "words": [word], "learning_rates": ["0.0005", 0.0001]})
    assert started["args"][-1] == [0.0005, 0.0001]
    local.action({"action": "start", "words": [word]})
    assert started["args"][-1] is None and started["kwargs"]["weights"] is None  # automatic
    local.action({"action": "start", "words": [word], "weights": {"real": "6", "synthetic": 1}})  # card 5: family
    assert started["kwargs"]["weights"] == {"real": 6.0, "synthetic": 1.0}
    for bad, match in (({"nope": 1}, "unknown set"), ({"real": 99}, "weight of real")):
        with pytest.raises(ValueError, match=match):
            local.action({"action": "start", "words": [word], "weights": bad})



def test_models_scored_and_the_base_chosen(local, monkeypatch):
    word = next(iter(local._require().words))
    listing = {"word": word, "base": "20261028-222907", "trained": True, "models": [
        {"id": "20261028-221357", "auc": 0.30, "roc": [[0.93, 0.0629, 0.75]], "run": {}, "current": False},
        {"id": "20261028-222907", "auc": 0.56, "roc": [[0.99, 0.073, 0.937]], "run": {}, "current": True}]}
    monkeypatch.setattr(local.runner(), "list_models", lambda w: json.loads(json.dumps(listing)))
    answer = local.models(word)
    assert answer["best"] == "20261028-221357" and answer["models"][0]["score"]["cutoff"] == 0.93
    with pytest.raises(ValueError, match="unknown word"):
        local.models("nope")

    started = {}
    monkeypatch.setattr(local.runner(), "start", lambda *args, **kwargs: started.update(args=args, kwargs=kwargs))
    local.action({"action": "choose_model", "word": word, "model": "20261028-221357"})
    assert started["args"][0] == [word] and started["kwargs"] == {"base": "20261028-221357"}
    local.action({"action": "choose_model", "word": word, "model": "new"})
    assert started["kwargs"] == {"base": "new"}
    with pytest.raises(ValueError, match="model id"):
        local.action({"action": "choose_model", "word": word, "model": "../x"})


def test_models_help_explains_the_cutoff(local):
    for language, words in (("pl", ("próg 0,93", "0,99", "Próg ustawiasz przy eksporcie")),
                            ("en", ("cutoff 0.93", "0.99", "You set the cutoff when exporting"))):
        text = local.state(language)["help"]["models"]
        assert all(w in text for w in words), language



def test_a_kept_model_shows_its_chart_again(local, monkeypatch):
    import sys
    import time

    sys.path.insert(0, str(Path(__file__).parents[1] / "docs"))
    import demo_household as screenshots

    word = next(iter(local._require().words))
    log = screenshots.training_log(time.time() - 3600, 20000, finished=True).replace("hej_jarvis", word)
    monkeypatch.setattr(local.runner(), "model_log", lambda w, model: log)
    progress = local.model_progress(word, "20261029-143440")
    assert progress["word"] == word and len(progress["points"]) > 5 and progress["roc"]
    assert progress["phases"] == [[10000, 0.001], [6000, 0.0003], [4000, 0.0001]]
    for bad in ("new", "../x"):
        with pytest.raises(ValueError, match="model id"):
            local.model_progress(word, bad)
    monkeypatch.setattr(local.runner(), "model_log", lambda w, model: "==> other: training\n")
    with pytest.raises(ValueError, match="no training of this word"):
        local.model_progress(word, "20261029-143440")


def test_devices_come_from_home_assistant_when_connected(local, household_dir, tmp_path, monkeypatch):
    from wakeword import ha_sync

    calls = []

    class FakeClient:
        def esphome_devices(self):
            calls.append(1)
            return [{"name": "sypialnia-ha-voice", "friendly_name": "Sypialnia", "file": "sypialnia-ha-voice.yaml"}]

    monkeypatch.setattr(ha_sync, "Client", FakeClient)
    folder = tmp_path / "esphome"
    folder.mkdir()
    (folder / "salon.yaml").write_text("esphome:\n  name: salon-voice\nvoice_assistant:\n")
    monkeypatch.setenv("WAKEWORD_ESPHOME", str(folder))
    assert [d["name"] for d in local.household_data()["esphome"]] == ["salon-voice"]  # not connected: the folder
    ha_sync.save_connection("http://homeassistant.local:8123", "t" * 40)
    assert [d["name"] for d in local.household_data()["esphome"]] == ["sypialnia-ha-voice"]
    local.household_data()
    assert len(calls) == 1  # asked again only after a minute

    started = {}
    monkeypatch.setattr(local, "_start_job", lambda name, commands: started.update(commands=commands))
    monkeypatch.setattr(local, "words", lambda: [{"id": "robo", "trained": True}])
    local.export(0.97)
    assert started["commands"][0][-1] == "--ha"  # the models go straight to /config/esphome/wake_words




def test_training_refused_after_an_edit_until_prepared_again(local, household_dir, monkeypatch):
    from wakeword.scaffold import read_raw, save_raw
    from wakeword.training_config import write_build

    started = []
    monkeypatch.setattr(local.runner(), "start", lambda *args, **kwargs: started.append(args))
    from wakeword import dataset

    household = local._require()
    word = "robo"
    record_takes(household, word, "kid", 6)
    dataset.write_split(household, dataset.split_word(household, word), word)
    write_build(household, word)  # what Prepare writes, prepared.json included
    data = read_raw(household_dir)
    data["words"][word]["spellings"]["uk"] = ["hey robo"]
    save_raw(household_dir, data)
    with pytest.raises(ValueError, match="spellings.*changed since Prepare"):
        local.action({"action": "start", "words": [word]})
    local.action({"action": "start", "words": [word], "convert_only": True})  # only converting: allowed
    write_build(local._require(), word)  # prepared again
    local.action({"action": "start", "words": [word]})
    assert len(started) == 2


def test_machine_power_through_home_assistant(local, tmp_path, monkeypatch):
    from wakeword import ha_sync, power

    from .test_power import FakeHa

    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")
    assert local.machine() is None and local.state()["machine"] is None  # not set up: no header button
    ha_sync.save_connection("http://homeassistant.local:8123", "t" * 40)
    fake = FakeHa()
    monkeypatch.setattr(ha_sync, "Client", lambda *args: fake)
    fake.entities = lambda timeout=10: [
        {"entity_id": "switch.maszyna_gpu", "attributes": {"friendly_name": "Maszyna GPU"}},
        {"entity_id": "sensor.plug_power", "attributes": {"unit_of_measurement": "W"}},
        {"entity_id": "sensor.temperature", "attributes": {"unit_of_measurement": "°C"}}]
    entities = local.ha_entities()
    assert [e["id"] for e in entities["sensors"]] == ["sensor.plug_power"]  # only power sensors (W)
    assert entities["switches"] == [{"id": "switch.maszyna_gpu", "name": "Maszyna GPU"}]
    local.action({"action": "power_settings", "switch": "switch.maszyna_gpu", "sensor": "sensor.plug_power"})
    assert power.load_power().ready and local.state()["home_assistant"]["power"]["switch"] == "switch.maszyna_gpu"
    assert local.machine() == {"switch": "on", "watts": 54.3, "machine": "on"}

    monkeypatch.setattr(local, "poll", lambda force=False: {"running": True})
    with pytest.raises(RuntimeError, match="training is running"):  # never cut a training
        local.action({"action": "machine_off"})
    local.switch_machine(True)  # switching on is fine while a training runs (Home Assistant does it on its own)
    monkeypatch.setattr(local, "poll", lambda force=False: {"running": False})
    local.action({"action": "machine_off"})
    assert fake.calls == ["switch.turn_on switch.maszyna_gpu", "switch.turn_off switch.maszyna_gpu"]
    with pytest.raises(ValueError, match="sensor"):
        local.action({"action": "power_settings", "switch": "switch.maszyna_gpu", "sensor": "switch.plug"})


def test_household_test_of_the_models_started_on_the_machine(local, monkeypatch):
    started = {}
    monkeypatch.setattr(local, "_start_job", lambda name, commands: started.update(name=name, commands=commands))
    monkeypatch.setattr(local, "poll", lambda force=False: {"running": False})
    local.action({"action": "evaluate_models", "word": "robo"})
    assert started["name"] == "evaluate_models" and "evaluate-models robo --missing" in started["commands"][0][-1]
    with pytest.raises(ValueError, match="unknown word"):
        local.action({"action": "evaluate_models", "word": "nope"})
    monkeypatch.setattr(local, "poll", lambda force=False: {"running": True})
    with pytest.raises(RuntimeError, match="training ends"):
        local.action({"action": "evaluate_models", "word": "robo"})


def test_page_answered_at_once_while_a_machine_that_is_off_is_checked(local, monkeypatch, tmp_path):
    """A switched-off machine takes the SSH timeout to answer: the page must not wait for it."""
    import subprocess

    from wakeword import ha_sync, power

    release = threading.Event()

    def slow_status(offset):
        release.wait(5)  # like ssh -o ConnectTimeout=10 to a machine that is off
        raise subprocess.TimeoutExpired("ssh", 10)

    monkeypatch.setattr(local.runner(), "status", slow_status)
    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")
    ha_sync.save_connection("http://homeassistant.local:8123", "t" * 40)
    power.save_power(power.PowerSettings(switch="switch.maszyna_gpu", sensor="sensor.plug_power"))
    monkeypatch.setattr(local, "machine", lambda: release.wait(5))
    started = time.time()
    state = local.state()
    assert time.time() - started < 1
    assert state["training"]["checking"] and state["machine"] == {"machine": "checking"}
    assert local.training_log() == ""  # the lock is free while the machine is asked
    release.set()
    assert wait(lambda: not local.state()["training"]["checking"])
    assert "timed out" in local.state()["training"]["error"]

    # an unexpected failure of the check is said too - never "checking" for ever
    local._checked, local._polled = False, 0.0
    monkeypatch.setattr(local.runner(), "status", lambda offset: 1 / 0)
    local.state()
    assert wait(lambda: not local.state()["training"]["checking"])
    assert "ZeroDivisionError" in local.state()["training"]["error"]


def test_rejected_token_stops_every_question_until_the_connection_is_saved(local, tmp_path, monkeypatch):
    """Each 401 is a failed login for Home Assistant's ip_ban: the panel asks once, then waits for a save."""
    from wakeword import ha_sync, power

    from .test_ha_sync import TOKEN, FakeHa

    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")
    monkeypatch.delenv("WAKEWORD_HA_URL", raising=False)
    monkeypatch.delenv("WAKEWORD_HA_TOKEN", raising=False)
    ha = FakeHa(tmp_path / "ha")
    try:
        with pytest.raises(ValueError, match="saved, but Home Assistant 401"):  # "Save" checks at once
            local.action({"action": "ha_connection", "url": ha.url, "token": "b" * 40})
        assert ha.requests == ["/api/"] and local.state()["home_assistant"]["rejected"] is True
        local.action({"action": "power_settings", "switch": "switch.maszyna_gpu", "sensor": "sensor.plug_power"})
        assert power.load_power().ready
        for _ in range(3):  # the page asks every 2 s: Home Assistant is not asked
            assert local.machine()["machine"] == "rejected" and local.machine_cached()["machine"] == "rejected"
        with pytest.raises(ha_sync.HaError, match="not asked again"):
            local.ha_entities()
        with pytest.raises(RuntimeError, match="not asked again"):
            local.switch_machine(True)
        local.esphome_devices()  # the local folder instead
        assert "not asked again" in local._push_household()  # household.yaml kept here, said so
        assert ha.requests == ["/api/"]

        local.action({"action": "ha_connection", "url": ha.url, "token": TOKEN})  # a good token: asked again
        assert ha.requests[-1] == "/api/" and len(ha.requests) == 2
        assert local.state()["home_assistant"]["rejected"] is False
        assert local.machine()["machine"] != "rejected"
    finally:
        ha.server.shutdown()


def test_tests_never_read_the_real_esphome_folder():
    """make test exports WAKEWORD_ESPHOME=/Volumes/config/esphome (the real devices): the tests drop it."""
    import os

    assert "WAKEWORD_ESPHOME" not in os.environ

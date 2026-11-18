import json
import shutil

import pytest
import yaml

from wakeword import cli, dataset
from wakeword.audio import write_wav
from wakeword.export import TRAINED_MODEL
from wakeword.synthetic import build_dir

from .conftest import record_takes, utterance


def run(*argv):
    return cli.main([str(a) for a in argv])


def test_setup_commands(tmp_path, capsys):
    home = tmp_path / "home"
    assert run("-H", home, "init", "--speaker", "dad", "--speaker", "ola:child", "--ui-language", "pl") == 0
    assert run("-H", home, "add-word", "dzarwis", "Dżarwis", "--spelling", "pl=dżarwis, dżarwys",
               "--spelling", "en=jarvis", "--language", "pl", "--sound-alike", "darwin") == 0
    assert run("-H", home, "add-speaker", "mum") == 0
    assert run("-H", home, "add-word", "wajana", "Wajana", "--spelling", "pl=wajana",
               "--speaker", "ola") == 0
    assert run("-H", home, "add-speaker", "ela", "--group", "child", "--word", "wajana") == 0
    assert run("-H", home, "set-device", "girls-voice", "dzarwis", "wajana") == 0
    data = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
    assert data["words"]["dzarwis"]["spellings"] == {"pl": ["dżarwis", "dżarwys"], "en": ["jarvis"]}
    assert data["words"]["wajana"]["speakers"] == ["ola", "ela"]
    assert data["devices"] == {"girls-voice": ["dzarwis", "wajana"]}
    assert "girls-voice: dzarwis, wajana" in capsys.readouterr().out


def test_errors_are_reported(tmp_path, capsys):
    assert run("-H", tmp_path, "check") == 2
    assert "wakeword init" in capsys.readouterr().err
    run("-H", tmp_path, "init", "--speaker", "dad")
    assert run("-H", tmp_path, "add-word", "w", "W", "--spelling", "nolanguage") == 2
    assert "language=text" in capsys.readouterr().err
    assert run("-H", tmp_path, "set-device", "x", "nope") == 2


def test_word_selection(household_dir, capsys):
    assert run("-H", household_dir, "split") == 2
    assert "--all" in capsys.readouterr().err
    assert run("-H", household_dir, "split", "nope") == 2
    assert "known: hey_tony, robo" in capsys.readouterr().err


def test_import_and_check(household_dir, tmp_path, capsys):
    files = [write_wav(tmp_path / f"memo{i}.wav", utterance()) for i in range(2)]
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"x")
    assert run("-H", household_dir, "import", "robo", "--speaker", "kid", *files) == 0
    assert run("-H", household_dir, "import", "robo", "--speaker", "kid", bad) == 1
    out = capsys.readouterr().out
    assert "kid_000_imported.wav" in out and "not imported" in out
    assert run("-H", household_dir, "check") == 1
    assert "2/6" in capsys.readouterr().out


def complete(household):
    record_takes(household, "hey_tony", "dad", 4)
    record_takes(household, "hey_tony", "kid", 6)
    record_takes(household, "robo", "kid", 6)


def test_prepare_pipeline(household, household_dir, capsys):
    assert run("-H", household_dir, "prepare", "--all", "--positives", "10", "--per-voice", "2") == 1
    assert "not complete" in capsys.readouterr().out
    complete(household)
    assert run("-H", household_dir, "check") == 0
    assert run("-H", household_dir, "prepare", "--all", "--positives", "10", "--per-voice", "2",
               "--per-take", "1", "--steps", "500") == 0
    out = capsys.readouterr().out
    assert "train/train.sh" in out
    assert "robo: ElevenLabs none" in out  # optional, said so instead of left out
    for word in ("hey_tony", "robo"):
        folder = build_dir(household, word)
        assert (folder / "synthetic.sh").exists()
        assert yaml.safe_load((folder / "training_parameters.yaml").read_text())["training_steps"] == [250, 150, 100]
        assert json.loads((folder / "features.json").read_text())["word"] == word
        assert dataset.read_split(household, word)
    assert len(list((household.data_dir / "expanded" / "robo").rglob("*.wav"))) == 5


def test_preview_command(household, household_dir, capsys):
    record_takes(household, "robo", "kid", 2)
    assert run("-H", household_dir, "preview", "robo", "--count", "3") == 0
    assert "3 files" in capsys.readouterr().out


def test_export_command(household, household_dir, capsys):
    assert run("-H", household_dir, "export") == 0  # device snippets only
    trained = build_dir(household, "robo") / TRAINED_MODEL
    trained.parent.mkdir(parents=True)
    trained.write_bytes(b"TFL3")
    assert run("-H", household_dir, "export", "robo", "--cutoff", "0.9", "--url", "https://x/ww") == 0
    out = capsys.readouterr().out
    assert "robo.json" in out and "kid-room.yaml" in out
    snippet = (household.data_dir / "export" / "devices" / "kid-room.yaml").read_text()
    assert "https://x/ww/robo.json" in snippet
    assert run("-H", household_dir, "export", "hey_tony") == 2


def test_export_sends_the_models_to_home_assistant(household, household_dir, capsys, monkeypatch):
    from pathlib import Path

    from wakeword import ha_sync

    sent = []

    class FakeClient:
        def upload_wake_word(self, path):
            sent.append(Path(path).name)
            return f"esphome/wake_words/{Path(path).name}"

        def esphome_devices(self):
            return [{"name": "kid-room", "friendly_name": "Kid room", "file": "home-assistant-voice-1a2b3c.yaml"}]

    monkeypatch.setattr(ha_sync, "Client", FakeClient)
    trained = build_dir(household, "robo") / TRAINED_MODEL
    trained.parent.mkdir(parents=True)
    trained.write_bytes(b"TFL3")
    assert run("-H", household_dir, "export", "robo", "--ha") == 0
    assert sent == ["robo.tflite", "robo.json"]
    out = capsys.readouterr().out
    assert "Home Assistant: esphome/wake_words/robo.json" in out
    # where each snippet goes and the snippet itself, ready to copy
    assert "--- kid-room: paste below `packages:` in ESPHome → home-assistant-voice-1a2b3c.yaml" in out
    assert "micro_wake_word:\n  models:\n    - model: wake_words/robo.json" in out


def test_evaluate_needs_extras_or_model(household, household_dir, capsys, monkeypatch):
    from wakeword import evaluate

    def broken(self, path):
        raise RuntimeError("install the evaluation extras")

    monkeypatch.setattr(evaluate.TFLiteModel, "__init__", broken)
    record_takes(household, "robo", "kid", 6)
    run("-H", household_dir, "split", "robo")
    assert run("-H", household_dir, "evaluate", "robo") == 2
    assert "evaluation extras" in capsys.readouterr().err


def test_evaluate_with_fake_model(household, household_dir, capsys, monkeypatch):
    from wakeword import evaluate

    from .test_evaluate import LoudnessModel

    monkeypatch.setattr(evaluate, "TFLiteModel", lambda path: LoudnessModel())
    record_takes(household, "robo", "kid", 6)
    run("-H", household_dir, "split", "robo")
    assert run("-H", household_dir, "evaluate", "robo", "--window", "3") == 0
    assert "recommended cutoff" in capsys.readouterr().out


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")
def test_make_cert_command(household, household_dir, capsys):
    assert run("-H", household_dir, "make-cert", "--address", "127.0.0.1") == 0
    assert (household.data_dir / "certs" / "cert.pem").exists()


def test_env_household(household_dir, monkeypatch, capsys):
    monkeypatch.setenv("WAKEWORD_HOUSEHOLD", str(household_dir))
    assert cli.main(["check"]) == 1


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    from wakeword import __version__

    assert f"wakeword {__version__}" in capsys.readouterr().out


@pytest.mark.parametrize("http", [True, False])
def test_record_command(household, household_dir, capsys, monkeypatch, http):
    import wakeword.recorder as recorder
    from wakeword.recorder import certs

    calls = {}
    monkeypatch.setattr(recorder, "serve", lambda root, **kwargs: calls.update(root=root, **kwargs))
    monkeypatch.setattr(certs, "make_cert", lambda folder: (folder / "c.pem", folder / "k.pem"))
    monkeypatch.setattr(certs, "local_addresses", lambda: ["10.0.0.2"])
    args = ["-H", household_dir, "record", "--port", "9000"] + (["--http"] if http else [])
    assert run(*args) == 0
    out = capsys.readouterr().out
    if http:
        assert "http://10.0.0.2:9000/" in out and calls["cert"] is None
    else:
        assert "https://10.0.0.2:9000/" in out and calls["cert"].name == "c.pem"
    assert calls["root"] == household.root and calls["port"] == 9000


def test_prepare_checks_only_the_chosen_words(household, household_dir, capsys):
    record_takes(household, "robo", "kid", 6)  # hey_tony has no recordings at all
    assert run("-H", household_dir, "prepare", "hey_tony", "--positives", "10", "--per-voice", "1") == 1
    assert "dad / hey_tony: 0/4" in capsys.readouterr().out
    assert run("-H", household_dir, "prepare", "robo", "--positives", "10", "--per-voice", "1", "--per-take", "1") == 0
    assert (build_dir(household, "robo") / "training_parameters.yaml").exists()
    assert not (build_dir(household, "hey_tony") / "training_parameters.yaml").exists()


def test_config_says_how_many_elevenlabs_takes_go_in(household, household_dir, capsys):
    from wakeword.recordings import write_index

    complete(household)
    base = household.data_dir / "elevenlabs" / "robo"
    for group in ("bartosz-k9StxIPT_00", "bartosz-k9StxIPT_01", "aleksandra-abcdefgh_00"):
        (base / group).mkdir(parents=True)
    write_index(base, {"bartosz-k9StxIPT_00": {"00000.wav": 0.7, "00001.wav": 0.8},
                       "bartosz-k9StxIPT_01": {"00000.wav": 0.7}, "aleksandra-abcdefgh_00": {"00000.wav": 0.9}})
    assert run("-H", household_dir, "split", "robo") == 0
    assert run("-H", household_dir, "config", "robo") == 0
    assert "robo: ElevenLabs 4 takes from 2 voices (data/elevenlabs/robo)" in capsys.readouterr().out


def test_evaluate_models_writes_the_household_test_next_to_each_model(household_dir, monkeypatch, capsys):
    import json

    from wakeword import audio, evaluate
    from wakeword.household import load_household

    from .conftest import noise, record_takes
    from .test_evaluate import LoudnessModel

    household = load_household(household_dir)
    record_takes(household, "robo", "kid", 6)
    dataset.write_split(household, dataset.split_word(household, "robo"), "robo")
    for name in ("a.wav", "b.wav"):
        audio.write_wav(household.data_dir / "background" / name, noise(5.0, level=0.01))
    models = household.data_dir / "build" / "robo" / "models"
    for model_id in ("20261030-140621", "20261030-160135"):
        (models / model_id).mkdir(parents=True)
        (models / model_id / "stream_state_internal_quant.tflite").write_bytes(b"TFL3")
    (models / "base").write_text("20261030-140621")  # not a model folder
    measured = []
    monkeypatch.setattr(evaluate, "TFLiteModel", lambda path: measured.append(path) or LoudnessModel())
    assert cli.main(["-H", str(household_dir), "evaluate-models", "robo", "--missing"]) in (0, None)
    result = json.loads((models / "20261030-140621" / "household.json").read_text())
    held_out = sum(1 for row in dataset.read_split(household, "robo") if row.split == "test")
    assert result["takes"] == {"kid": held_out} and result["best"]["cutoff"] >= 0.5 and result["inputs"]
    assert len(measured) == 2 and "worst person misses" in capsys.readouterr().out
    assert cli.main(["-H", str(household_dir), "evaluate-models", "robo", "--missing"]) in (0, None)
    assert len(measured) == 2  # measured on these takes already: skipped
    before = dataset.split_background(household)[1]
    for name in ("c.wav", "d.wav", "e.wav", "f.wav", "g.wav"):
        audio.write_wav(household.data_dir / "background" / name, noise(5.0, level=0.01))
    changed = dataset.split_background(household)[1] != before
    cli.main(["-H", str(household_dir), "evaluate-models", "robo", "--missing"])
    assert len(measured) == (4 if changed else 2)  # a new test recording: measured again; a training one: not

"""train/models.py on the training machine: every run kept, compared, and the base of the next run chosen."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).parents[1] / "train" / "models.py"
spec = importlib.util.spec_from_file_location("train_models", SCRIPT)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)

ROC_A = "AUC 0.30388\nCutoff 1.00: frr=1.0000; faph=0.000\nCutoff 0.99: frr=0.1097; faph=0.375\nCutoff 0.93: frr=0.0629; faph=0.750\n"
ROC_B = "AUC 0.56240\nCutoff 1.00: frr=1.0000; faph=0.000\nCutoff 0.99: frr=0.0730; faph=0.937\n"


def trained(home: Path, weights: bytes, roc: str) -> Path:
    folder = home / "data" / "build" / "robo" / "trained"
    (folder / models.STREAM_DIR).mkdir(parents=True, exist_ok=True)
    (folder / models.WEIGHTS).write_bytes(weights)
    (folder / models.STREAM_DIR / models.TFLITE).write_bytes(b"TFL3" + weights)
    (folder / models.STREAM_DIR / models.ROC).write_text(roc)
    (folder / "restore").mkdir(exist_ok=True)
    (folder / "restore" / "checkpoint").write_text("ckpt of the last run")
    return folder


def test_roc_of_the_final_test():
    assert models.parse_roc(ROC_A) == {"auc": 0.30388, "roc": [[1.0, 1.0, 0.0], [0.99, 0.1097, 0.375], [0.93, 0.0629, 0.75]]}
    assert models.parse_roc("") == {"auc": None, "roc": []}


def test_older_copies_and_the_current_model_are_listed(tmp_path):
    legacy = tmp_path / "data" / "backup" / "training-robo-20261028-221357"
    (legacy / models.STREAM_DIR).mkdir(parents=True)
    (legacy / models.WEIGHTS).write_bytes(b"run-3")
    (legacy / models.STREAM_DIR / models.ROC).write_text(ROC_A)
    (tmp_path / "data" / "backup" / "training-other-20261028-000000").mkdir()  # another word
    trained(tmp_path, b"run-4", ROC_B)
    run = tmp_path / "data/build/robo/training_parameters.run.yaml"
    run.write_text("training_steps: [10000, 10000]\nnegative_class_weight: [30.0, 30.0]\nlearning_rates: [0.0003, 0.0001]\n")
    listing = models.list_models(tmp_path, "robo")
    # the older copy, and the model of the last run with that run's settings (the start of the next run)
    assert [m["id"] for m in listing["models"]][0] == "20261028-221357" and len(listing["models"]) == 2
    old, last = listing["models"]
    assert old["auc"] == 0.30388 and old["current"] is False and old["run"]["from"] == legacy.name
    assert last["current"] and last["run"]["steps"] == 20000 and listing["base"] == last["id"]
    run.unlink()

    # a run that ended now is kept with its settings, as the start of the next run
    config = tmp_path / "run.yaml"
    config.write_text("training_steps: [10000, 10000]\nnegative_class_weight: [30.0, 30.0]\nlearning_rates: [0.0003, 0.0001]\n"
                      "features:\n- {features_dir: features/real, sampling_weight: 6.0}\n"
                      "- {features_dir: negative_datasets/dinner_party_eval, sampling_weight: 0.0}\n")
    pytest.importorskip("yaml")
    trained(tmp_path, b"run-5", ROC_B)  # a run that ended now, kept by train.sh with its start time
    kept = models.archive(tmp_path, "robo", config, started=1793218519)
    listing = models.list_models(tmp_path, "robo")
    new = next(m for m in listing["models"] if m["id"] == kept)
    assert new["current"] and new["auc"] == 0.5624
    assert new["run"]["steps"] == 20000 and new["run"]["negative_weight"] == 30.0
    assert new["run"]["learning_rates"] == [0.0003, 0.0001] and new["run"]["started"] == 1793218519
    assert new["run"]["weights"] == {"real": 6.0}  # the sets' weights of the run (card 5), the test-only set left out
    # the same weights again ("convert only"): no second copy, the test refreshed
    (tmp_path / "data/build/robo/trained" / models.STREAM_DIR / models.ROC).write_text(ROC_A)
    assert models.archive(tmp_path, "robo") == kept
    assert len(models.list_models(tmp_path, "robo")["models"]) == 3
    assert models.list_models(tmp_path, "robo")["models"][-1]["auc"] == 0.30388


def test_choosing_a_kept_model_as_the_start_of_the_next_run(tmp_path):
    trained(tmp_path, b"run-3", ROC_A)
    first = models.archive(tmp_path, "robo")
    trained(tmp_path, b"run-4", ROC_B)
    models.select(tmp_path, "robo", first)
    folder = tmp_path / "data/build/robo/trained"
    assert (folder / models.WEIGHTS).read_bytes() == b"run-3"
    assert (folder / models.STREAM_DIR / models.ROC).read_text() == ROC_A
    assert not (folder / "restore").exists()  # set_base.py makes it from the chosen weights
    listing = models.list_models(tmp_path, "robo")
    assert listing["base"] == first and len(listing["models"]) == 2  # run 4 was kept before it was replaced
    assert [m["current"] for m in listing["models"]] == [True, False]
    with pytest.raises(ValueError, match="no such model"):
        models.select(tmp_path, "robo", "20200101-000000")
    with pytest.raises(ValueError, match="not a model id"):
        models.select(tmp_path, "robo", "../../etc")


def test_next_run_from_scratch_keeps_everything(tmp_path):
    trained(tmp_path, b"run-4", ROC_B)
    models.select(tmp_path, "robo", models.NEW)
    assert not (tmp_path / "data/build/robo/trained").exists()
    assert list((tmp_path / "data" / "backup").glob("trained-robo-*/" + models.WEIGHTS))
    listing = models.list_models(tmp_path, "robo")
    assert listing["base"] == "new" and len(listing["models"]) == 1 and not listing["trained"]


def test_command_line_prints_json(tmp_path):
    trained(tmp_path, b"run-4", ROC_B)
    models.archive(tmp_path, "robo")
    result = subprocess.run([sys.executable, str(SCRIPT), "list", str(tmp_path), "robo"], capture_output=True, check=True)
    assert json.loads(result.stdout)["models"][0]["auc"] == 0.5624
    bad = subprocess.run([sys.executable, str(SCRIPT), "select", str(tmp_path), "robo", "nope"], capture_output=True)
    assert bad.returncode == 2 and b"not a model id" in bad.stderr


def test_train_sh_keeps_every_run_and_can_only_choose_the_base():
    text = (Path(__file__).parents[1] / "train" / "train.sh").read_text()
    assert 'models.py" archive "$HOUSEHOLD" "$word" --config "$config" --started "$started" --log' in text
    assert 'models.py" select "$HOUSEHOLD" "$word" "$BASE"' in text and "set_base.py" in text
    assert text.index('if [ -n "${BASE:-}" ]') < text.index("# 3. Synthetic speech")  # no synthesis, no training
    assert text.count('"${MODEL_ARGS[@]}"') == 2  # one architecture for training and for the base


def test_every_model_gets_a_polish_name_for_good(tmp_path):
    legacy = tmp_path / "data" / "backup" / "training-robo-20261028-221357"
    legacy.mkdir(parents=True)
    (legacy / models.WEIGHTS).write_bytes(b"run-3")
    trained(tmp_path, b"run-4", ROC_B)
    first = models.list_models(tmp_path, "robo")
    names = [m["run"]["name"] for m in first["models"]]
    assert len(names) == 2 and len(set(names)) == 2
    adjective, noun = names[0].split("_")
    assert adjective in models.ADJECTIVES or adjective[:-1] + "y" in models.ADJECTIVES or adjective[:-1] + "i" in models.ADJECTIVES
    assert noun in models.NOUNS["m"] + models.NOUNS["f"]
    # feminine nouns get the feminine adjective (mała gruszka, not mały gruszka)
    for model_id in ("20261028-212257", "20261028-222907", "20261028-234401", "20261029-100000"):
        adjective, noun = models.model_name(model_id, set()).split("_")
        assert (noun in models.NOUNS["f"]) == adjective.endswith("a")
    # the same name on every listing, written next to the model
    assert [m["run"]["name"] for m in models.list_models(tmp_path, "robo")["models"]] == names
    assert json.loads((tmp_path / "data/build/robo/models/20261028-221357/run.json").read_text())["name"] == names[0]
    # a taken name is not given twice
    taken = models.model_name("20261028-221357", set())
    assert models.model_name("20261028-221357", {taken}) != taken


def test_the_log_of_a_run_is_kept_with_its_model_only_at_its_end(tmp_path):
    import gzip

    log = tmp_path / "data" / "build" / "train.log"
    trained(tmp_path, b"run-4", ROC_B)
    log.write_text("==> robo: training\nlog of the next run\n")
    before = models.archive(tmp_path, "robo")  # before a run: train.log is the new run's
    assert not models.list_models(tmp_path, "robo")["models"][0]["chart"]
    trained(tmp_path, b"run-5", ROC_A)
    log.write_text("==> robo: training\nStep 500 ...\nAUC 0.30388\n")
    after = models.archive(tmp_path, "robo", with_log=True)
    listing = {m["id"]: m for m in models.list_models(tmp_path, "robo")["models"]}
    assert listing[after]["chart"] and not listing[before]["chart"]
    assert gzip.decompress(models.read_log(tmp_path, "robo", after)).decode().endswith("AUC 0.30388\n")
    with pytest.raises(ValueError, match="no log"):
        models.read_log(tmp_path, "robo", before)
    with pytest.raises(ValueError, match="not a model id"):
        models.read_log(tmp_path, "robo", "../x")
    result = subprocess.run([sys.executable, str(SCRIPT), "log", str(tmp_path), "robo", after], capture_output=True, check=True)
    assert gzip.decompress(result.stdout).startswith(b"==> robo: training")



def test_household_test_listed_without_its_curve(tmp_path):
    trained(tmp_path, b"run-1", ROC_A)
    kept = models.archive(tmp_path, "robo")
    folder = models.models_dir(tmp_path, "robo") / kept
    (folder / models.HOUSEHOLD).write_text(json.dumps({"hours": 0.3, "takes": {"tomek": 3}, "curve": [{"cutoff": 0.5}],
                                                       "best": {"cutoff": 0.95, "times": 0.8}}))
    listed = next(m for m in models.list_models(tmp_path, "robo")["models"] if m["id"] == kept)
    assert listed["household"] == {"hours": 0.3, "takes": {"tomek": 3}, "best": {"cutoff": 0.95, "times": 0.8}}
    (folder / models.HOUSEHOLD).write_text("broken")
    assert next(m for m in models.list_models(tmp_path, "robo")["models"] if m["id"] == kept)["household"] is None

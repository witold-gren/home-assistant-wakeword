from pathlib import Path

from wakeword.trainer import progress

LOG = (Path(__file__).parent / "trainer_log.txt").read_text(encoding="utf-8")


def test_parse_full_log():
    result = progress.parse(LOG)
    assert list(result.words) == ["dzarwis", "wajana"]
    assert result.current_word == "wajana"
    assert result.stage == "wajana: training"
    assert not result.finished
    assert any("something broke" in e for e in result.errors)

    dz = result.words["dzarwis"]
    assert dz.stage == "done"
    assert dz.model.endswith("stream_state_internal_quant.tflite")
    assert [p.step for p in dz.points] == [500, 1000]
    last = dz.points[-1]
    assert (last.avr, last.faph, last.recall_no_faph, last.cutoff_no_faph) == (0.931, 0.42, 86.25, 0.96)
    assert dz.train_accuracy == 99.1 and dz.last_step == 1000
    assert dz.best_avr == 0.931 and dz.best_cutoff == 0.96
    assert dz.auc == 0.0312 and len(dz.roc) == 4
    assert dz.recommended_cutoff == 0.97
    assert dz.verdict() == "good"

    wa = result.words["wajana"]
    assert wa.stage == "training" and wa.verdict() == "bad" and wa.roc == []


def test_verdicts_during_training():
    word = progress.WordProgress("w")
    assert word.verdict() == "unknown"
    word.points.append(progress.Point(500, 0.8, 2.0, 90, 50, 0.99, 95, 0.1))
    assert word.verdict() == "ok"
    word.points.append(progress.Point(1000, 0.92, 0.8, 95, 85, 0.96, 98, 0.05))
    assert word.verdict() == "good"
    word.roc = [progress.RocPoint(0.97, 0.08, 0.3)]
    assert word.recommended_cutoff is None and word.verdict() == "bad"


def test_finished_and_stage_testing():
    text = "==> dzarwis: training\nI AUC 0.05\n==> done — copy the household folder back\n"
    result = progress.parse(text)
    assert result.finished and result.words["dzarwis"].stage == "testing"


def test_clean_lines_and_tail():
    assert progress.clean_lines("a\rb\rc\nd") == ["c", "d"]
    assert progress.tail("1\n2\n3", 2) == "2\n3"


def test_errors_before_any_word():
    result = progress.parse("TensorFlow does not see a GPU - training would run on the CPU (many times slower).\n")
    assert result.errors and result.words == {}


def test_as_dict_is_json_ready():
    import json

    data = progress.parse(LOG).as_dict()
    json.dumps(data)
    assert data["words"]["dzarwis"]["recommended_cutoff"] == 0.97
    assert data["words"]["dzarwis"]["verdict"] == "good"


STEP_LINE = ("I1026 10:20:01.000 1 train.py:316] Step #{}: rate 0.001000, accuracy 99.10%, recall 97.80%, "
             "precision 98.95%, cross entropy 0.031000\n")


def test_percent_and_time_left():
    text = ("==> hej_jarvis: training\n"
            "training plan: steps=20000 started=1000 negative_weight=20\n"
            + STEP_LINE.format(500) + STEP_LINE.format(5000))
    word = progress.parse(text).words["hej_jarvis"]
    assert (word.total_steps, word.started_at, word.negative_weight, word.step) == (20000, 1000.0, 20.0, 5000)
    assert word.percent == 25.0
    # 5000 steps in 1000 s -> 15000 steps left take 3000 s
    assert word.remaining_seconds(2000) == 3000
    data = progress.parse(text).as_dict(now=2000)["words"]["hej_jarvis"]
    assert (data["step"], data["percent"], data["remaining_seconds"], data["advice"]) == (5000, 25.0, 3000, None)


def test_a_next_run_counts_from_step_one():
    """microWakeWord restarts the step counter in every run (it only restores the weights)."""
    text = ("==> w: training\ntraining plan: steps=20000 started=0\n" + STEP_LINE.format(20000)
            + "==> w: model ready → x\n==> w: features\n==> w: training\n"
            "training plan: steps=10000 started=5000 negative_weight=40\n" + STEP_LINE.format(500))
    word = progress.parse(text).words["w"]
    assert (word.total_steps, word.negative_weight, word.last_step, word.percent) == (10000, 40.0, 500, 5.0)
    assert word.remaining_seconds(5100) == 1900


def test_no_time_left_without_plan_or_after_training():
    word = progress.parse("==> w: training\nStep 500 (nonstreaming): x\n").words["w"]
    assert word.percent is None and word.remaining_seconds(100) is None
    text = "==> w: training\ntraining plan: steps=100 started=0\nI AUC 0.05\n"
    word = progress.parse(text).words["w"]
    assert word.stage == "testing" and word.remaining_seconds(100) is None


def run_with(avrs, roc, steps=20000, weight=20.0):
    word = progress.WordProgress("w", stage="done", total_steps=steps, negative_weight=weight)
    word.points = [progress.Point(500 * (i + 1), avr, 0.5, 90, 80, 0.97, 98, 0.05) for i, avr in enumerate(avrs)]
    word.roc = [progress.RocPoint(*p) for p in roc]
    return word


FLAT = [0.80, 0.90, 0.93, 0.94, 0.94, 0.94, 0.94, 0.94]
RISING = [0.70, 0.75, 0.80, 0.84, 0.86, 0.88, 0.90, 0.93]
GOOD_ROC = [(0.90, 0.02, 1.2), (0.97, 0.04, 0.3), (0.99, 0.09, 0.0)]
NOISY_ROC = [(0.90, 0.02, 3.0), (0.97, 0.04, 1.4), (0.99, 0.08, 0.6)]  # catches words, wakes too often
DEAF_ROC = [(0.90, 0.09, 0.4), (0.97, 0.15, 0.1), (0.99, 0.30, 0.0)]  # quiet, misses words


def test_advice_waits_for_the_final_test():
    assert run_with(FLAT, []).advice() is None


def test_advice_ready():
    advice = run_with(FLAT, GOOD_ROC).advice()
    assert advice["kind"] == "ready" and advice["change"] == {} and advice["facts"]["cutoff"] == 0.97


def test_advice_ready_but_still_improving():
    advice = run_with(RISING, GOOD_ROC).advice()
    assert advice["kind"] == "ready_more_steps" and advice["change"] == {"steps": progress.MORE_STEPS}


def test_advice_more_steps_when_still_learning():
    assert run_with(RISING, NOISY_ROC).advice()["kind"] == "more_steps"
    # enough steps already: more data, not more steps
    assert run_with(RISING, NOISY_ROC, steps=80000).advice()["kind"] == "raise_negative_weight"


def test_advice_too_many_false_wakes():
    advice = run_with(FLAT, NOISY_ROC).advice()
    assert advice["kind"] == "raise_negative_weight"
    assert advice["change"] == {"steps": progress.TUNE_STEPS, "negative_weight": 40}
    assert advice["facts"]["faph_at_good_frr"] == 1.4  # fewest false wakes while catching 95 % of words
    assert run_with(FLAT, NOISY_ROC, weight=60).advice()["change"]["negative_weight"] == 80


def test_advice_too_many_misses():
    advice = run_with(FLAT, DEAF_ROC).advice()
    assert advice["kind"] == "lower_negative_weight"
    assert advice["change"] == {"steps": progress.TUNE_STEPS, "negative_weight": 12}
    assert advice["facts"]["frr_at_good_faph"] == 0.09


def test_advice_weak_model_needs_recordings():
    assert run_with([0.4, 0.5, 0.55, 0.6, 0.6, 0.6, 0.6, 0.6], NOISY_ROC).advice()["kind"] == "more_data"
    # nothing left to tune
    bad = [(0.9, 0.2, 2.0), (0.99, 0.3, 1.0)]
    assert run_with(FLAT, bad, steps=80000).advice()["kind"] == "more_data"
    advice = run_with(FLAT, bad).advice()
    assert advice["kind"] == "more_steps_mixed" and advice["change"] == {"steps": progress.MORE_STEPS}


def test_advice_uses_the_default_weight_without_a_plan():
    word = run_with(FLAT, NOISY_ROC, weight=None)
    assert word.advice()["change"]["negative_weight"] == 40
    assert word.advice(default_negative_weight=10)["change"]["negative_weight"] == 20


def _heredocs(script: str) -> list[str]:
    parts = script.split("<<'PY'\n")[1:]
    return [part.split("\nPY\n", 1)[0] for part in parts]


def test_train_script_overrides_and_logs_the_plan(tmp_path):
    import subprocess
    import sys

    import yaml

    script = (Path(__file__).parents[1] / "train" / "train.sh").read_text(encoding="utf-8")
    override, plan = _heredocs(script)[:2]
    config = tmp_path / "params.yaml"
    config.write_text(yaml.safe_dump({"training_steps": [20000], "learning_rates": [0.001],
                                      "negative_class_weight": [20], "positive_class_weight": [1]}))
    out = tmp_path / "run.yaml"
    subprocess.run([sys.executable, "-c", override, str(config), "40000", "35", str(out)], check=True)
    run = yaml.safe_load(out.read_text())
    assert run["training_steps"] == [20000, 12000, 8000] and run["negative_class_weight"] == [35.0] * 3
    assert run["learning_rates"] == [0.001, 0.0003, 0.0001] and run["positive_class_weight"] == [1] * 3
    # train.sh splits STEPS exactly like the config written on the Mac
    from wakeword.training_config import SCHEDULE, split_steps

    assert run["training_steps"] == split_steps(40000)
    assert run["learning_rates"] == [rate for _, rate in SCHEDULE]
    subprocess.run([sys.executable, "-c", override, str(config), "", "50", str(out)], check=True)
    assert yaml.safe_load(out.read_text())["training_steps"] == [20000]
    line = subprocess.run([sys.executable, "-c", plan, str(out)], check=True, capture_output=True, text=True).stdout
    match = progress.PLAN.match(line.strip())
    assert match and match["steps"] == "20000" and match["negative_weight"] == "50" and match["phases"] == "20000:0.001"
    subprocess.run([sys.executable, "-c", override, str(config), "40000", "35", str(out)], check=True)
    line = subprocess.run([sys.executable, "-c", plan, str(out)], check=True, capture_output=True, text=True).stdout
    word = progress.parse(f"==> w: training\n{line}").words["w"]
    assert word.phases == [[20000, 0.001], [12000, 0.0003], [8000, 0.0001]]  # the bands of the chart
    # SET_WEIGHTS (card 5: family / neutral): the sampling weight of the named sets, the others as prepared
    config.write_text(yaml.safe_dump({"training_steps": [20000], "learning_rates": [0.001], "negative_class_weight": [20],
                                      "features": [{"features_dir": "features/real", "sampling_weight": 3.0},
                                                   {"features_dir": "features/synthetic", "sampling_weight": 2.0},
                                                   {"features_dir": "negative_datasets/speech", "sampling_weight": 10.0},
                                                   {"features_dir": "negative_datasets/dinner_party_eval",
                                                    "sampling_weight": 0.0}]}))
    subprocess.run([sys.executable, "-c", override, str(config), "", "", str(out), "", "", "real=6,synthetic=1,speech=12"],
                   check=True)
    weights = {f["features_dir"]: f["sampling_weight"] for f in yaml.safe_load(out.read_text())["features"]}
    assert weights == {"features/real": 6.0, "features/synthetic": 1.0, "negative_datasets/speech": 12.0,
                       "negative_datasets/dinner_party_eval": 0.0}
    line = subprocess.run([sys.executable, "-c", plan, str(out)], check=True, capture_output=True, text=True).stdout
    assert progress.PLAN.match(line.strip())["weights"] == "real:6,synthetic:1,speech:12"
    assert 'NEG_WEIGHT' in script and 'models.py" archive "$HOUSEHOLD" "$word"' in script  # the model before a run kept


def _pick_python(tmp_path, pythons: dict[str, bool], chosen: str | None = None):
    """Run train.sh's pick_python with fake interpreters (True = can create a venv)."""
    import subprocess

    script = (Path(__file__).parents[1] / "train" / "train.sh").read_text(encoding="utf-8")
    function = script[script.index("pick_python() {"):]
    function = function[:function.index("\n}\n") + 3]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, works in pythons.items():
        fake = bin_dir / name
        fake.write_text("#!/bin/sh\n"
                        'case "$2" in *ensurepip*) exit %d;; esac\necho 3.12\n' % (0 if works else 1))
        fake.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    if chosen:
        env["PYTHON"] = chosen
    return subprocess.run(["bash", "-c", function + "pick_python"], capture_output=True, text=True, env=env)


def test_train_script_picks_a_python_that_can_create_a_venv(tmp_path):
    # Ubuntu 24.04 after an upgrade: python3.10 left without venv, python3.12 with python3.12-venv
    result = _pick_python(tmp_path, {"python3.10": False, "python3.12": True})
    assert result.returncode == 0 and result.stdout.strip() == "python3.12"
    assert _pick_python(tmp_path, {"python3.11": True, "python3.12": False}).stdout.strip() == "python3.11"
    # PYTHON chosen by hand is the only candidate
    assert _pick_python(tmp_path, {"python3.10": True}, chosen="python3.10").stdout.strip() == "python3.10"


def test_train_script_explains_a_missing_venv_package(tmp_path):
    result = _pick_python(tmp_path, {"python3.10": False, "python3.12": False, "python3": False})
    assert result.returncode == 1 and result.stdout == ""
    assert "sudo apt install -y python3.12-venv python3.12-dev build-essential" in result.stderr
    script = (Path(__file__).parents[1] / "train" / "train.sh").read_text(encoding="utf-8")
    assert 'removing the incomplete venv' in script and '[ ! -f "$VENV/bin/activate" ]' in script


def test_advice_unstable_training_is_repeated_before_tuning():
    """The first real run: the main score jumped 0.09-0.85 to the end, the advice said lower the weight."""
    jumping = [0.76, 0.75, 0.10, 0.26, 0.62, 0.74, 0.44, 0.85, 0.59, 0.88, 0.09, 0.83, 0.16, 0.80, 0.53, 0.30]
    advice = run_with(jumping, DEAF_ROC).advice()
    assert advice["kind"] == "unstable" and advice["change"] == {"steps": 20000}
    assert (advice["facts"]["avr_low"], advice["facts"]["avr_high"]) == (0.09, 0.88)
    # a settled run is tuned as before; a good final test is ready whatever the curve did
    assert run_with(FLAT, DEAF_ROC).advice()["kind"] == "lower_negative_weight"
    assert run_with(jumping, GOOD_ROC).advice()["kind"] == "ready"


# the run of 2026-10-28: FRR 8 % at 1.1 false wakes/h, and a cutoff of 1.0 that never wakes at all
CLOSE_NOISY_ROC = [(1.0, 1.0, 0.0), (0.99, 0.0802, 1.125), (0.98, 0.0678, 1.5), (0.97, 0.0593, 2.0)]


def test_advice_never_waking_is_no_answer():
    # the quiet cutoff that misses every word made "lower the weight" out of a run that wakes too often
    advice = run_with(FLAT, CLOSE_NOISY_ROC).advice()
    assert advice["kind"] == "close_raise_negative_weight"
    assert advice["change"] == {"steps": progress.TUNE_STEPS, "negative_weight": 30}
    assert "frr_at_good_faph" not in advice["facts"]
    assert advice["facts"]["balance_cutoff"] == 0.99 and advice["facts"]["balance_faph"] == 1.125


def test_advice_close_but_misses_words():
    roc = [(1.0, 1.0, 0.0), (0.95, 0.15, 0.55), (0.9, 0.12, 0.8)]  # at 0.9: 2.4× the FRR goal, 1.6× the faph one
    advice = run_with(FLAT, roc).advice()
    assert advice["kind"] == "close_lower_negative_weight" and advice["change"]["negative_weight"] == 15
    assert advice["facts"]["balance_cutoff"] == 0.9


# the next run (weight 30): each goal on its own cutoff, both a little out of reach
BOTH_SIDES_ROC = [(1.0, 1.0, 0.0), (0.99, 0.1097, 0.375), (0.98, 0.093, 0.562), (0.93, 0.0629, 0.75),
                  (0.92, 0.0606, 0.937), (0.89, 0.0521, 1.125), (0.86, 0.0465, 1.312), (0.83, 0.0423, 2.0)]


def test_advice_both_goals_apart_is_not_a_weight_question():
    advice = run_with(FLAT, BOTH_SIDES_ROC, steps=10000, weight=30).advice()
    assert advice["kind"] == "more_steps_mixed" and advice["change"] == {"steps": progress.MORE_STEPS}
    assert advice["facts"]["balance_cutoff"] == 0.93


def test_a_plan_without_phases_still_reads():
    word = progress.parse("==> w: training\ntraining plan: steps=10000 started=5 negative_weight=30\n").words["w"]
    assert word.total_steps == 10000 and word.phases == []


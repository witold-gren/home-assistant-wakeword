import subprocess

import pytest

from wakeword import synthetic


def test_plan_jobs(household):
    jobs = synthetic.plan_jobs(household, "hey_tony", positives=1000, per_voice=30, negatives=300)
    gen = [j for j in jobs if j.engine == "generator" and j.truth]
    assert [j.text for j in gen] == ["hey tony", "hey toni"]
    assert all(j.count == 500 for j in gen)
    piper_pos = [j for j in jobs if j.engine == "piper" and j.truth]
    assert len(piper_pos) == 2 * len(synthetic.PIPER_VOICES["en"])
    assert all(j.count == 30 for j in piper_pos)
    negatives = [j for j in jobs if not j.truth]
    assert {j.text for j in negatives} == {"hey tommy"}
    assert all(j.count == 10 for j in negatives if j.engine == "piper")
    assert all(j.output.startswith("synthetic/hey_tony/negative/") for j in negatives)
    assert len({j.output for j in jobs}) == len(jobs)


def test_plan_jobs_native_language(household):
    jobs = synthetic.plan_jobs(household, "robo", per_voice=10)
    pl = [j for j in jobs if j.language == "pl"]
    assert {j.voice for j in pl} == set(synthetic.PIPER_VOICES["pl"])
    assert all(j.engine == "piper" for j in pl)
    assert not [j for j in jobs if not j.truth]  # robo has no sound-alikes


def test_sound_alikes_in_trained_language_and_english(household_data, tmp_path):
    from wakeword.household import parse_household

    household_data["words"]["robo"]["sound_alikes"] = ["rower"]
    household = parse_household(household_data, tmp_path)
    jobs = [j for j in synthetic.plan_jobs(household, "robo") if not j.truth]
    assert {j.language for j in jobs} == {"pl", "en"}


def test_voices_for():
    assert synthetic.voices_for("pl") == synthetic.PIPER_VOICES["pl"]
    assert synthetic.voices_for("pl", {"pl": ("my_voice",)}) == ("my_voice",)
    with pytest.raises(ValueError, match="--voice"):
        synthetic.voices_for("xx")


def test_script(household):
    jobs = synthetic.plan_jobs(household, "hey_tony", positives=10, per_voice=2, negatives=4)
    path = synthetic.write_script(household, "hey_tony", jobs)
    assert path == household.data_dir / "build" / "hey_tony" / "synthetic.sh"
    assert path.stat().st_mode & 0o111
    text = path.read_text()
    total = len(jobs)
    assert f"generator '[1/{total}]' 'hey tony' 5 data/synthetic/hey_tony/positive/en_generator_00" in text
    assert "en_US-lessac-medium 'hey tommy'" in text and f"[{total}/{total}]" in text
    assert "piper_sample_generator" in text and '"$SYNTH_PIPER"' in text
    assert "piper.download_voices" not in text  # synth_piper.py downloads a voice only when missing
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_script_quotes_texts(household_data, tmp_path):
    from wakeword.household import parse_household

    household_data["words"]["robo"]["spellings"]["pl"] = ["it's \"robo\" $HOME"]
    household = parse_household(household_data, tmp_path)
    text = synthetic.render_script(household, "robo", synthetic.plan_jobs(household, "robo"))
    assert "'it'\"'\"'s \"robo\" $HOME'" in text


def test_summary(household):
    jobs = synthetic.plan_jobs(household, "hey_tony", positives=100, per_voice=3, negatives=8)
    text = synthetic.summary(jobs)
    assert " en generator positive     100" in text
    assert "negative" in text


FAKE_PYTHON = """#!/bin/bash
# stands in for python: the generator writes $max clips, synth_piper records its call
if [ "$1" = "-m" ] && [ "$2" = "piper_sample_generator" ]; then
  while [ $# -gt 0 ]; do case "$1" in --max-samples) n="$2";; --output-dir) out="$2";; esac; shift; done
  for i in $(seq 1 "$n"); do : > "$out/$i.wav"; done
  exit 0
fi
script="$1"; shift
echo "piper $*" >> "$CALLS"
while [ $# -gt 0 ]; do case "$1" in --out) out="$2";; --label) label="$2";; esac; shift; done
mkdir -p "$out"; touch "$out/.complete"; echo "$label piper done"
"""


def test_script_runs_logs_and_skips_finished_groups(household, tmp_path):
    jobs = synthetic.plan_jobs(household, "hey_tony", positives=6, per_voice=2, negatives=4)
    script = synthetic.write_script(household, "hey_tony", jobs)
    python = tmp_path / "python"
    python.write_text(FAKE_PYTHON)
    python.chmod(0o755)
    calls = tmp_path / "calls.txt"
    env = {"PATH": "/usr/bin:/bin", "PYTHON": str(python), "PSG_MODEL": "model.pt", "PIPER_VOICES_DIR": "voices",
           "SYNTH_PIPER": "synth_piper.py", "CALLS": str(calls)}
    run = lambda: subprocess.run(["bash", str(script)], cwd=household.root, env=env,  # noqa: E731
                                 capture_output=True, text=True, check=True).stdout
    first = run()
    total = len(jobs)
    assert "[1/" in first and "en generator 'hey tony': making 3 clips" in first
    assert "3/3 clips" in first and f"is ready: {total} groups" in first
    generated = household.data_dir / "synthetic" / "hey_tony" / "positive" / "en_generator_00"
    assert (generated / ".complete").exists() and len(list(generated.glob("*.wav"))) == 3
    assert "--voices-dir voices" in calls.read_text() and "--length-scales 0.8 0.9 1.0 1.1 1.25" in calls.read_text()

    # an interrupted generator group (clips but no marker) is made again; finished ones are skipped
    (generated / ".complete").unlink()
    (generated / "1.wav").unlink()
    second = run()
    assert "skip, already complete: en generator 'hey toni'" in second
    assert "en generator 'hey tony': making 3 clips" in second
    assert len(list(generated.glob("*.wav"))) == 3


HF_VOICE = "WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium"


def test_household_voices_replace_the_defaults(household_data, tmp_path):
    from wakeword.household import parse_household

    household_data["voices"] = {"pl": [HF_VOICE, "pl_PL-darkman-medium"], "en": []}
    household_data["words"]["robo"]["sound_alikes"] = ["rower"]
    household = parse_household(household_data, tmp_path)
    jobs = synthetic.plan_jobs(household, "robo", per_voice=10)
    assert {j.voice for j in jobs if j.language == "pl"} == {HF_VOICE, "pl_PL-darkman-medium"}
    # folders are named after the voice, without the repository
    assert any(j.output.endswith("/positive/pl_PL-meski_wg_glos-medium_00") for j in jobs)
    # no English Piper voices: English sound-alikes come from the generator only
    assert {j.engine for j in jobs if j.language == "en"} == {"generator"}
    # the command line still wins
    jobs = synthetic.plan_jobs(household, "robo", per_voice=10, voices={"pl": ("pl_PL-gosia-medium",)})
    assert {j.voice for j in jobs if j.language == "pl"} == {"pl_PL-gosia-medium"}


def test_a_language_without_voices_is_refused_except_english():
    assert synthetic.voices_for("en", {"en": ()}) == ()
    with pytest.raises(ValueError, match="Settings"):
        synthetic.voices_for("pl", {"pl": ()})
    assert synthetic.voice_name(HF_VOICE) == "pl_PL-meski_wg_glos-medium"
    assert synthetic.voice_name("pl_PL-gosia-medium") == "pl_PL-gosia-medium"


def test_household_voices_are_checked_and_saved(household_data, tmp_path):
    from wakeword.household import HouseholdError, parse_household
    from wakeword.scaffold import read_raw, save_raw

    household_data["voices"] = {"pl": ["bad voice"]}
    with pytest.raises(HouseholdError, match="voices.pl"):
        parse_household(household_data, tmp_path)
    household_data["voices"] = {"pl": [HF_VOICE, HF_VOICE, " pl_PL-darkman-medium "], "en": []}
    saved = save_raw(tmp_path, household_data)
    assert saved.voices == {"pl": (HF_VOICE, "pl_PL-darkman-medium"), "en": ()}
    assert read_raw(tmp_path)["voices"] == {"pl": [HF_VOICE, "pl_PL-darkman-medium"], "en": []}
    del household_data["voices"]
    save_raw(tmp_path, household_data)  # no choice = the default voices, nothing written
    assert "voices" not in (tmp_path / "household.yaml").read_text()


def test_script_moves_groups_no_longer_chosen_aside(household_data, tmp_path):
    from wakeword.household import parse_household

    household_data["voices"] = {"pl": ["pl_PL-darkman-medium"]}
    household = parse_household(household_data, tmp_path)
    old = household.data_dir / "synthetic" / "robo" / "positive"
    for name in ("pl_PL-gosia-medium_00", "pl_PL-darkman-medium_00"):
        (old / name).mkdir(parents=True)
        (old / name / "00000.wav").write_bytes(b"x")
        (old / name / ".complete").touch()
    script = synthetic.write_script(household, "robo", synthetic.plan_jobs(household, "robo", per_voice=2))
    python = tmp_path / "python"
    python.write_text(FAKE_PYTHON)
    python.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "PYTHON": str(python), "PSG_MODEL": "model.pt", "PIPER_VOICES_DIR": "voices",
           "SYNTH_PIPER": "synth_piper.py", "CALLS": str(tmp_path / "calls.txt")}
    out = subprocess.run(["bash", str(script)], cwd=household.root, env=env, capture_output=True, text=True,
                         check=True).stdout
    assert "no longer chosen" in out and "synthetic/robo/positive/pl_PL-gosia-medium_00" in out
    assert not (old / "pl_PL-gosia-medium_00").exists() and (old / "pl_PL-darkman-medium_00" / "00000.wav").exists()
    moved = list((household.data_dir / "backup").glob("synthetic-*/synthetic/robo/positive/pl_PL-gosia-medium_00"))
    assert len(moved) == 1 and (moved[0] / "00000.wav").exists()


def test_generator_group_made_again_when_its_text_changed(household, tmp_path):
    jobs = [j for j in synthetic.plan_jobs(household, "hey_tony", positives=4, per_voice=1, negatives=2)
            if j.engine == "generator" and j.truth][:1]
    script = synthetic.write_script(household, "hey_tony", jobs)
    python = tmp_path / "python"
    python.write_text(FAKE_PYTHON)
    python.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "PYTHON": str(python), "PSG_MODEL": "model.pt", "PIPER_VOICES_DIR": "voices",
           "SYNTH_PIPER": "synth_piper.py", "CALLS": str(tmp_path / "calls.txt")}
    run = lambda: subprocess.run(["bash", str(script)], cwd=household.root, env=env,  # noqa: E731
                                 capture_output=True, text=True, check=True).stdout
    run()
    group = household.data_dir / "synthetic" / "hey_tony" / "positive" / "en_generator_00"
    assert (group / ".complete").read_text() == jobs[0].text
    assert "skip, already complete" in run()
    (group / ".complete").write_text("another text")
    assert "the text changed" in run() and (group / ".complete").read_text() == jobs[0].text
    (group / ".complete").write_text("")  # a marker from before the text was kept is trusted
    assert "skip, already complete" in run()

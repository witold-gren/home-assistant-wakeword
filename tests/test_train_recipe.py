"""The training recipe runs on another machine; here we check what can be checked without a GPU."""

import importlib.util
import json
from pathlib import Path
import py_compile
import subprocess

import pytest
import soundfile as sf

from wakeword import dataset, training_config
from wakeword.audio import write_wav

from .conftest import record_takes, tone, utterance

TRAIN = Path(__file__).resolve().parent.parent / "train"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TRAIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scripts_compile():
    subprocess.run(["bash", "-n", str(TRAIN / "train.sh")], check=True)
    for script in TRAIN.glob("*.py"):
        py_compile.compile(str(script), doraise=True)
    assert "microWakeWord" in (TRAIN / "train.sh").read_text()


def test_train_sh_usage():
    result = subprocess.run(["bash", str(TRAIN / "train.sh")], capture_output=True, text=True)
    assert result.returncode == 1 and "train/train.sh <household folder>" in result.stdout


def test_collect_and_stage(household, tmp_path):
    mf = load("make_features")
    record_takes(household, "robo", "kid", 2)
    write_wav(household.data_dir / "synthetic" / "robo" / "positive" / "v" / "0.wav", tone(0.3), rate=22050)
    files = mf.collect(["data/real/robo", "data/synthetic/robo/positive", "data/missing"], household.root)
    assert len(files) == 3
    staging = tmp_path / "staging"
    assert mf.stage(files, staging, household.root) == 3
    names = sorted(p.name for p in staging.iterdir())
    assert names[0].startswith("data__real__robo__kid__")
    converted = staging / "data__synthetic__robo__positive__v__0.wav"
    assert not converted.is_symlink() and sf.info(str(converted)).samplerate == 16000
    linked = staging / names[0]
    assert linked.is_symlink()
    mf.stage(files[:1], staging, household.root)  # rebuilt from scratch
    assert len(list(staging.iterdir())) == 1


def test_features_plan_matches_make_features(household):
    """make_features.py reads the keys write_build produces."""
    record_takes(household, "robo", "kid", 6)
    dataset.write_split(household, dataset.split_word(household, "robo"), "robo")
    plan = json.loads(training_config.write_build(household, "robo")["features"].read_text())
    for entry in plan["sets"]:
        assert {"name", "features_dir", "sources", "repeat", "precomputed"} <= set(entry)


def test_signature_tracks_source_changes(household, tmp_path):
    mf = load("make_features")
    paths = record_takes(household, "robo", "kid", 2)
    entry = {"repeat": 50}
    sig = mf.signature(paths, entry)
    assert sig == mf.signature(paths, entry)
    assert sig != mf.signature(paths[:1], entry)
    assert sig != mf.signature(paths, {"repeat": 5})
    write_wav(paths[0], utterance(level=0.1))
    import os
    os.utime(paths[0], ns=(1, 1))
    assert sig != mf.signature(paths, entry)
    out = tmp_path / "features" / "real"
    assert not mf.is_current(out, sig)
    out.mkdir(parents=True)
    (out / mf.SIGNATURE_FILE).write_text(sig + "\n")
    assert mf.is_current(out, sig)


def test_english_generator_gets_piper_train_and_its_config():
    """PyPI's piper-sample-generator lacks piper_train and the generator's .pt.json (ModuleNotFoundError)."""
    from pathlib import Path

    script = (Path(__file__).parents[1] / "train" / "train.sh").read_text(encoding="utf-8")
    assert 'version("piper-sample-generator")' in script  # sources of the installed release
    assert "https://github.com/rhasspy/piper-sample-generator" in script and "advice.detachedHead=false" in script
    assert "piper_train_src.pth" in script and '"$GENERATOR.json"' in script
    assert 'python -c "import piper_train.vits.commons"' in script


def test_audiomentations_new_enough_for_microwakeword():
    """piper-sample-generator pins 0.33.0, microWakeWord needs AddColorNoise (AttributeError otherwise)."""
    from pathlib import Path

    script = (Path(__file__).parents[1] / "train" / "train.sh").read_text(encoding="utf-8")
    check = script.index("audiomentations.AddColorNoise")
    assert script.index('touch "$VENV/.installed"') < check < script.index("# 2. Data for augmentation")
    assert 'pip install -q -U "audiomentations>=0.36"' in script


def test_tensorboard_for_training_statistics():
    """TensorFlow 2.20+ has no TensorBoard; microWakeWord's tf.summary.scalar stopped training at step 500."""
    from pathlib import Path

    train = Path(__file__).parents[1] / "train"
    script = (train / "train.sh").read_text(encoding="utf-8")
    check = script.index('python -c "import tensorboard"')
    assert script.index('touch "$VENV/.installed"') < check < script.index("# 2. Data for augmentation")
    assert "pip install -q tensorboard" in script
    requirements = (train / "requirements-train.txt").read_text(encoding="utf-8").splitlines()
    assert "tensorboard" in requirements


def test_long_negatives_are_cut_into_chunks(household, tmp_path):
    """75 min of home background must not become one 3.2 s clip per file."""
    import numpy as np

    mf = load("make_features")
    background = household.data_dir / "background"
    write_wav(background / "salon.wav", np.zeros(16000 * 20, dtype=np.float32))  # 20 s
    write_wav(background / "short.wav", np.zeros(16000 * 4, dtype=np.float32))  # 4 s: kept whole
    files = mf.collect(["data/background"], household.root)
    staging = tmp_path / "staging"
    assert mf.stage(files, staging, household.root, chunk_seconds=3.0) == 8  # 7 pieces + the short file
    chunks = sorted(staging.glob("data__background__salon__*.wav"))
    assert [sf.info(str(c)).duration for c in chunks] == [3.0] * 6 + [2.0]  # the rest over a second stays
    assert mf.stage(files, staging, household.root) == 2  # positives: never cut


def fake_microwakeword(monkeypatch, made):
    """Stand-ins with microWakeWord's behaviour that matters: mmap_ninja creates only the last folder."""
    import sys
    import types

    class Clips:
        def __init__(self, input_directory, **kwargs):
            self.files = sorted(Path(input_directory).glob("*.wav"))

    class SpectrogramGeneration:
        def __init__(self, clips, augmenter, slide_frames, step_ms):
            self.clips = clips

        def spectrogram_generator(self, split, repeat):
            return iter(range(len(self.clips.files) * repeat))

    class RaggedMmap:
        @staticmethod
        def from_generator(out_dir, sample_generator, batch_size, verbose):
            Path(out_dir).mkdir(exist_ok=True)  # FileNotFoundError when the parent is missing
            made.append((Path(out_dir), len(list(sample_generator))))

    modules = {
        "microwakeword": types.ModuleType("microwakeword"),
        "microwakeword.audio": types.ModuleType("microwakeword.audio"),
        "microwakeword.audio.augmentation": types.SimpleNamespace(Augmentation=lambda **kwargs: None),
        "microwakeword.audio.clips": types.SimpleNamespace(Clips=Clips),
        "microwakeword.audio.spectrograms": types.SimpleNamespace(SpectrogramGeneration=SpectrogramGeneration),
        "mmap_ninja": types.ModuleType("mmap_ninja"),
        "mmap_ninja.ragged": types.SimpleNamespace(RaggedMmap=RaggedMmap),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_build_set_creates_the_split_folders(household, tmp_path, monkeypatch):
    mf = load("make_features")
    made = []
    fake_microwakeword(monkeypatch, made)
    record_takes(household, "robo", "kid", 3)
    entry = {"name": "real", "features_dir": "features/real", "sources": ["data/real/robo"], "repeat": 2,
             "truth": True}
    mf.build_set(entry, household.root, tmp_path / "staging", tmp_path / "assets")
    out = household.root / "features" / "real"
    assert [(p.relative_to(out).as_posix(), n) for p, n in made] == [
        ("training/real_mmap", 6), ("validation/real_mmap", 3), ("testing/real_mmap", 3)]
    assert (out / mf.SIGNATURE_FILE).exists()
    made.clear()
    mf.build_set(entry, household.root, tmp_path / "staging", tmp_path / "assets")
    assert made == []  # unchanged sources: skipped


def _run_override(tmp_path, steps="", weight="", cont="", rates=""):
    """The config override of train.sh (STEPS, NEG_WEIGHT, continuing), run as the script runs it."""
    import subprocess
    import sys

    import yaml

    from wakeword.training_config import SCHEDULE

    text = (Path(__file__).parents[1] / "train" / "train.sh").read_text()
    marker = "<<'PY'\n"
    start = text.index(marker, text.index('"$CONTINUE"')) + len(marker)
    code = text[start:text.index("\nPY\n", start)]
    config = tmp_path / "training_parameters.yaml"
    config.write_text(yaml.safe_dump({"training_steps": [10000, 6000, 4000], "learning_rates": [r for _, r in SCHEDULE],
                                      "negative_class_weight": [20.0] * 3, "positive_class_weight": [1.0] * 3}))
    out = tmp_path / "run.yaml"
    subprocess.run([sys.executable, "-c", code, str(config), steps, weight, str(out), cont, rates], check=True)
    return yaml.safe_load(out.read_text())


def test_continuing_starts_at_a_lower_learning_rate(tmp_path):
    from wakeword.training_config import FINE_TUNE, SCHEDULE

    fresh = _run_override(tmp_path, steps="20000")
    assert fresh["training_steps"] == [10000, 6000, 4000] and fresh["learning_rates"] == [r for _, r in SCHEDULE]
    more = _run_override(tmp_path, steps="20000", weight="30", cont="1")
    assert more["training_steps"] == [10000, 10000] and more["learning_rates"] == [r for _, r in FINE_TUNE]
    assert more["negative_class_weight"] == [30.0, 30.0] and more["positive_class_weight"] == [1.0, 1.0]
    same = _run_override(tmp_path, cont="1")  # no STEPS: the steps of the plan
    assert same["training_steps"] == [10000, 10000]


def test_learning_rates_from_the_panel(tmp_path):
    two = _run_override(tmp_path, steps="20000", rates="0.0005,0.0001", cont="1")  # wins over FINE_TUNE
    assert two["training_steps"] == [10000, 10000] and two["learning_rates"] == [0.0005, 0.0001]
    four = _run_override(tmp_path, steps="10000", rates="0.001,0.0005,0.0002,0.0001")
    assert four["training_steps"] == [4000, 3000, 2000, 1000] and len(four["negative_class_weight"]) == 4
    one = _run_override(tmp_path, rates="0.0002")  # the steps of the plan, one phase
    assert one["training_steps"] == [20000] and one["learning_rates"] == [0.0002]


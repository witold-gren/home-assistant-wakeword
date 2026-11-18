"""microWakeWord training configuration for one word of the household.

Produces two files in ``data/build/<word>/``:

- ``features.json`` — which audio goes into which feature set (read by ``train/make_features.py``
  on the training machine, which augments the audio and computes the spectrogram features),
- ``training_parameters.yaml`` — the config for ``microwakeword.model_train_eval``.

Feature sets and why they are weighted the way they are:

========================  =====  ==============================================================
set                       truth  content
========================  =====  ==============================================================
real                      yes    the household's training takes — the voices that matter most
expanded                  yes    the same takes with shifted voice and tempo
synthetic                 yes    TTS: English generator + native voices reading phonetic spellings
elevenlabs (optional)     yes    ElevenLabs voices chosen in the panel reading the spellings
sound_alikes              no     TTS of phrases that sound similar (hard negatives)
other_words               no     the household's other wake words (recordings + TTS), so e.g. the
                                 shared word never wakes a device listening for a personal one
background (optional)     no     the household's own background recordings
false_wakes (optional)    no     clips that woke a device by mistake (added over time)
speech / dinner_party /   no     public negative datasets (pre-computed features)
no_speech
dinner_party_eval         no     public set used to measure false wakes per hour during training
========================  =====  ==============================================================
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

import yaml

from .dataset import read_split, split_background
from .expand import EXPANDED_DIR
from .household import Household
from .elevenlabs import ELEVENLABS_DIR
from .synthetic import SYNTHETIC_DIR, build_dir, voices_for

PREPARED_FILE = "prepared.json"  # in data/build/<word>/: what the word was prepared with

# How often each set is sampled in training (sampling_weight). Card 5 of the panel can override them
# per run (train.sh SET_WEIGHTS); the two presets there:
# - family: the household's voices and the home's sounds count most - the model reacts very well to
#   the family and almost never wakes by itself at home (it may react worse to strangers);
# - neutral: the word itself for anyone - synthetic and ElevenLabs voices count most.
DEFAULT_WEIGHTS = {"real": 3.0, "expanded": 2.0, "elevenlabs": 2.5, "synthetic": 2.0, "sound_alikes": 3.0,
                   "other_words": 4.0, "background": 3.0, "false_wakes": 5.0, "speech": 10.0,
                   "dinner_party": 10.0, "no_speech": 5.0}
WEIGHT_PRESETS = {
    "family": {"negative_weight": 30.0, "weights": {
        "real": 6.0, "expanded": 4.0, "elevenlabs": 1.5, "synthetic": 1.0, "sound_alikes": 3.0, "other_words": 4.0,
        "background": 8.0, "false_wakes": 8.0, "speech": 10.0, "dinner_party": 10.0, "no_speech": 5.0}},
    "neutral": {"negative_weight": 20.0, "weights": {
        "real": 2.0, "expanded": 1.0, "elevenlabs": 3.0, "synthetic": 3.0, "sound_alikes": 3.0, "other_words": 4.0,
        "background": 3.0, "false_wakes": 5.0, "speech": 10.0, "dinner_party": 10.0, "no_speech": 5.0}},
}
MAX_WEIGHT = 50.0


def check_weights(weights: dict) -> dict[str, float]:
    """The sets' weights chosen in the panel: known sets, 0-MAX_WEIGHT each."""
    checked = {}
    for name, value in (weights or {}).items():
        if name not in DEFAULT_WEIGHTS:
            raise ValueError(f"unknown set '{name}'")
        value = float(value)
        if not 0 <= value <= MAX_WEIGHT:
            raise ValueError(f"weight of {name}: 0-{MAX_WEIGHT:g}")
        checked[name] = value
    return checked

NEGATIVE_DATASETS = "negative_datasets"  # folder on the training machine, see train/train.sh
FALSE_WAKES_DIR = "false_wakes"
FEATURES_DIR = "features"


@dataclass
class FeatureSet:
    name: str
    truth: bool
    sampling_weight: float
    penalty_weight: float = 1.0
    truncation_strategy: str = "truncate_start"
    sources: list[str] = field(default_factory=list)  # files or folders, relative to the household
    repeat: int = 1  # augmentation passes over the training split (more for small sets)
    precomputed: bool = False  # public datasets come as ready features

    @property
    def features_dir(self) -> str:
        return f"{NEGATIVE_DATASETS}/{self.name}" if self.precomputed else f"{FEATURES_DIR}/{self.name}"


def _rel(household: Household, path: Path) -> str:
    return path.relative_to(household.root).as_posix()


def feature_sets(household: Household, word: str) -> list[FeatureSet]:
    """The feature sets for training `word`, sources resolved against the household folder."""
    if word not in household.words:
        raise ValueError(f"unknown word '{word}'")
    data = household.data_dir
    train_takes = [r.path for r in read_split(household, word) if r.split == "train"]
    if not train_takes:
        raise ValueError(f"no training takes for '{word}' — record, check and split first")

    sets = [
        # Few files, so each is augmented many times; the highest weight — these are the real voices.
        FeatureSet("real", True, DEFAULT_WEIGHTS["real"], sources=[_rel(household, p) for p in train_takes], repeat=50),
        FeatureSet("expanded", True, DEFAULT_WEIGHTS["expanded"], sources=[_rel(household, data / EXPANDED_DIR / word)], repeat=5),
        FeatureSet("synthetic", True, DEFAULT_WEIGHTS["synthetic"],
                   sources=[_rel(household, data / SYNTHETIC_DIR / word / "positive")], repeat=2),
    ]
    if (data / ELEVENLABS_DIR / word).is_dir():
        # natural takes, a little more weight than Piper; a few hundred are augmented 10 times, thousands
        # fewer times, so they never outnumber the other sets (about 20,000 augmented clips at most)
        takes = sum(1 for f in (data / ELEVENLABS_DIR / word).rglob("[0-9]*.wav"))
        sets.append(FeatureSet("elevenlabs", True, DEFAULT_WEIGHTS["elevenlabs"], sources=[_rel(household, data / ELEVENLABS_DIR / word)],
                               repeat=max(2, min(10, round(20000 / max(takes, 1))))))
    if household.words[word].sound_alikes:
        sets.append(FeatureSet("sound_alikes", False, DEFAULT_WEIGHTS["sound_alikes"], truncation_strategy="random",
                               sources=[_rel(household, data / SYNTHETIC_DIR / word / "negative")],
                               repeat=2))
    others = household.other_words(word)
    if others:
        sources = []
        for other in others:
            sources.append(_rel(household, household.real_dir(other.id)))
            sources.append(_rel(household, data / SYNTHETIC_DIR / other.id / "positive"))
            if (data / ELEVENLABS_DIR / other.id).is_dir():
                sources.append(_rel(household, data / ELEVENLABS_DIR / other.id))
        sets.append(FeatureSet("other_words", False, DEFAULT_WEIGHTS["other_words"], truncation_strategy="random",
                               sources=sources, repeat=3))
    background, _ = split_background(household)  # the test recordings stay out (evaluate.py: false wakes at home)
    if background:
        sets.append(FeatureSet("background", False, DEFAULT_WEIGHTS["background"], truncation_strategy="random",
                               sources=[_rel(household, f) for f in background], repeat=1))
    if (data / FALSE_WAKES_DIR / word).is_dir():
        sets.append(FeatureSet("false_wakes", False, DEFAULT_WEIGHTS["false_wakes"], truncation_strategy="random",
                               sources=[_rel(household, data / FALSE_WAKES_DIR / word)], repeat=3))
    sets += [
        FeatureSet("speech", False, DEFAULT_WEIGHTS["speech"], truncation_strategy="random", precomputed=True),
        FeatureSet("dinner_party", False, DEFAULT_WEIGHTS["dinner_party"], truncation_strategy="random", precomputed=True),
        FeatureSet("no_speech", False, DEFAULT_WEIGHTS["no_speech"], truncation_strategy="random", precomputed=True),
        FeatureSet("dinner_party_eval", False, 0.0, truncation_strategy="split", precomputed=True),
    ]
    return sets


# Learning rate falling in three phases (share of the steps, rate). One rate for all the steps made
# the validation jump between "too eager" and "too strict" until the very end (first real run:
# average viable recall 0.1-0.88 every 500 steps). train/train.sh splits STEPS the same way.
SCHEDULE = ((0.5, 0.001), (0.3, 0.0003), (0.2, 0.0001))
# A run that continues from the weights of a finished one (train.sh, --restore_checkpoint) starts lower:
# 0.001 again shook the learnt model (AVR 0.07 at one validation) before it settled.
FINE_TUNE = ((0.5, 0.0003), (0.5, 0.0001))


def split_steps(steps: int) -> list[int]:
    """`steps` divided over the phases of SCHEDULE (the last one takes what rounding leaves)."""
    parts = [int(steps * share) for share, _ in SCHEDULE[:-1]]
    return [*parts, steps - sum(parts)]


def training_parameters(household: Household, word: str, sets: list[FeatureSet],
                        steps: int = 20000, negative_weight: int = 20, batch_size: int = 128) -> dict:
    """The dict for training_parameters.yaml (keys as in microWakeWord's training notebook)."""
    return {
        "window_step_ms": 10,
        "train_dir": f"data/build/{word}/trained",
        "features": [
            {
                "features_dir": s.features_dir,
                "sampling_weight": s.sampling_weight,
                "penalty_weight": s.penalty_weight,
                "truth": s.truth,
                "truncation_strategy": s.truncation_strategy,
                "type": "mmap",
            }
            for s in sets
        ],
        "training_steps": split_steps(steps),
        "positive_class_weight": [1] * len(SCHEDULE),
        "negative_class_weight": [negative_weight] * len(SCHEDULE),
        "learning_rates": [rate for _, rate in SCHEDULE],
        "batch_size": batch_size,
        "time_mask_max_size": [0],
        "time_mask_count": [0],
        "freq_mask_max_size": [0],
        "freq_mask_count": [0],
        "eval_step_interval": 500,
        "clip_duration_ms": 1500,
        "target_minimization": 0.9,
        "minimization_metric": None,
        "maximization_metric": "average_viable_recall",
    }


def write_build(household: Household, word: str, **kwargs) -> dict[str, Path]:
    """Write features.json and training_parameters.yaml for `word`."""
    sets = feature_sets(household, word)
    folder = build_dir(household, word)
    folder.mkdir(parents=True, exist_ok=True)
    features = folder / "features.json"
    features.write_text(json.dumps(
        {"word": word, "household": household.name,
         "sets": [asdict(s) | {"features_dir": s.features_dir} for s in sets]},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    params = folder / "training_parameters.yaml"
    header = (f"# microWakeWord training config for '{word}' — generated by `wakeword config`.\n"
              "# Paths are relative to the household folder on the training machine.\n")
    params.write_text(header + yaml.safe_dump(training_parameters(household, word, sets, **kwargs),
                                              sort_keys=False, allow_unicode=True), encoding="utf-8")
    (folder / PREPARED_FILE).write_text(json.dumps(prepared_inputs(household, word), indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    return {"features": features, "training_parameters": params}


def prepared_inputs(household: Household, word: str) -> dict:
    """What the word's training data is made from: its spellings, sound-alikes, Piper and ElevenLabs voices."""
    from .elevenlabs import plan

    entry = household.words[word]
    languages = sorted(entry.spellings)
    voices = {}
    for language in languages:
        try:
            voices[language] = list(voices_for(language, household.voices))
        except ValueError:  # no voices for the language: Prepare says so itself
            voices[language] = []
    return {"spellings": {lang: list(entry.spellings[lang]) for lang in languages},
            "sound_alikes": list(entry.sound_alikes), "voices": voices,
            "elevenlabs": sorted(folder.name for *_, folder in plan(household, word))}


def changed_since_prepare(household: Household, word: str) -> list[str]:
    """What changed in household.yaml since the word was prepared ([] also for a build from before this check)."""
    try:
        before = json.loads((build_dir(household, word) / PREPARED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    now = prepared_inputs(household, word)
    return [key for key in now if before.get(key) != now[key]]

"""The made-up household of the studio's demo, browser tests and screenshots (docs/studio_demo.py):
three people, two words, recordings, synthetic samples, two kept training runs and a training log - nothing
real is read."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wakeword.scaffold import save_raw
from wakeword.trainer import runner as runner_module
from wakeword.trainer import server as server_module

VARIANTS = ["near", "far", "quiet", "loud", "fast", "slow", "question", "tired", "cheerful", "background",
            "other_side", "normal", "near", "far", "quiet", "loud", "fast", "slow"]
DEMO_GPU = {"name": "NVIDIA GeForce RTX 4090", "utilization": 71.0, "memory_used": 5120.0,
            "memory_total": 24564.0, "temperature": 62.0, "power": 238.0}

HOUSEHOLD = {
    "ui_language": "pl",
    "speakers": [{"id": "anna", "group": "adult"}, {"id": "piotr", "group": "adult"},
                 {"id": "ola", "group": "child"}],
    "words": {
        "hej_jarvis": {"wake_word": "Hej Jarvis", "trained_languages": ["pl"], "speakers": "all",
                       "spellings": {"pl": ["hej dżarwis", "hej dżarwys"], "en": ["hey jarvis"]},
                       "sound_alikes": ["hej harwis", "hej darwin"]},
        "hej_robo": {"wake_word": "Hej Robo", "trained_languages": ["pl"], "speakers": ["ola"],
                     "spellings": {"pl": ["hej robo"]}, "sound_alikes": ["hej rower"]},
    },
    "targets": {"adult": 12, "child": 18, "held_out": 3},
    "devices": {"salon-voice": ["hej_jarvis"], "pokoj-oli-voice": ["hej_robo", "hej_jarvis"]},
    "elevenlabs": {"model": "eleven_multilingual_v2", "count": 5, "voices": [
        {"id": "demo00000001", "name": "Marek", "language": "pl", "owner": "demo"},
        {"id": "demo00000002", "name": "Aleksandra", "language": "pl", "owner": "demo"}]},
}
TAKES = {("hej_jarvis", "anna"): 12, ("hej_jarvis", "piotr"): 12, ("hej_jarvis", "ola"): 18, ("hej_robo", "ola"): 11}

def validation(step: int, avr: float, faph: float) -> list[str]:
    return [
        (f"I1028 train.py:316] Step #{step}: rate 0.001000, accuracy 99.10%, recall 97.80%, precision 98.95%, "
        "cross entropy 0.031000"),
        (f"I1028 train.py:344] Step {step} (nonstreaming): Validation: recall at no faph = 82.000 with cutoff 0.97, "
        f"accuracy = 98.70%, recall = 95.10%, precision = 98.00%, ambient false positives = 3, estimated false "
        f"positives per hour = {faph}, loss = 0.05, auc = 0.99, average viable recall = {avr}"),
        (f"I1028 train.py:452] So far the best minimization quantity is 0.000 with best maximization quantity of "
        f"{avr * 100:.5f}%; no faph cutoff is 0.97"),
    ]


def training_log(started: float, steps_done: int, finished: bool) -> str:
    lines = ["==> creating venv in /home/anna/wakeword-work/venv with python3.12",
             "==> downloading augmentation data and negative datasets (first run only)",
             "assets ready in /home/anna/wakeword-work/assets",
             "==> synthetic speech: data/build/hej_jarvis/synthetic.sh",
             "synthetic speech for hej_jarvis is ready",
             "==> hej_jarvis: features", "==> hej_jarvis: training",
             (f"training plan: steps=20000 started={int(started)} negative_weight=20 "
             "phases=10000:0.001,6000:0.0003,4000:0.0001")]
    curve = [0.62, 0.74, 0.81, 0.85, 0.88, 0.90, 0.91, 0.92, 0.925, 0.93]
    for index, step in enumerate(range(500, steps_done + 1, 500)):
        avr = curve[index] if index < len(curve) else 0.931
        lines += validation(step, avr, round(max(1.2, 3.0 - index * 0.2), 2))
    if finished:
        lines += ["I1028 test.py:390] AUC 0.04100",
                  "I1028 test.py:396] Cutoff 0.90: frr=0.0200; faph=3.100",
                  "I1028 test.py:396] Cutoff 0.97: frr=0.0410; faph=1.400",
                  "I1028 test.py:396] Cutoff 0.99: frr=0.0800; faph=0.600",
                  "==> hej_jarvis: model ready → data/build/hej_jarvis/trained/model.tflite"]
    return "\n".join(lines) + "\n"


def make_household(root: Path) -> Path:
    home = root / "wakeword"
    home.mkdir(parents=True)
    save_raw(home, HOUSEHOLD)
    tone = (0.2 * np.sin(np.linspace(0, 2 * np.pi * 220 * 0.8, 12800))).astype(np.float32)
    for (word, speaker), count in TAKES.items():
        folder = home / "data" / "real" / word / speaker
        folder.mkdir(parents=True)
        for index in range(count):
            sf.write(folder / f"{speaker}_{index:03d}_{VARIANTS[index]}.wav", tone, 16000)
    background = home / "data" / "background"
    background.mkdir(parents=True)
    for name in ("salon_20261027_1904.wav", "kuchnia_20261027_2005.wav"):
        sf.write(background / name, np.zeros(16000 * 30, dtype=np.float32), 16000)
    build = home / "data" / "build" / "hej_jarvis"
    build.mkdir(parents=True)
    (build / "training_parameters.yaml").write_text("training_steps: [20000]\nnegative_class_weight: [20]\n")
    preview = build / "synthetic_preview"
    for kind, names in (("positive", ["pl_PL-gosia-medium_00_00000", "pl_PL-gosia-medium_01_00100",
                                      "pl_PL-darkman-medium_00_00000", "en_US-amy-medium_00_00000",
                                      "en_generator_00_00000"]),
                        ("negative", ["pl_PL-gosia-medium_00_00000", "en_US-amy-medium_00_00000"])):
        (preview / kind).mkdir(parents=True)
        for name in names:
            sf.write(preview / kind / f"{name}.wav", tone, 16000)
    # ElevenLabs: a synchronised voice list (made up) and takes of one chosen voice
    eleven = home / "data" / "elevenlabs"
    eleven.mkdir(parents=True)
    (eleven / "voices-pl.json").write_text(json.dumps([
        {"id": f"demo{i:08d}", "owner": "demo", "name": name, "source": source, "gender": gender, "age": age,
         "accent": "polish", "description": description, "preview": None, "added": source == "own",
         "native": native, "speaks": native == "pl" or source == "library"}
        for i, (name, source, gender, age, description, native) in enumerate([
            ("Marek", "library", "male", "middle_aged", "spokojny, ciepły lektor", "pl"),
            ("Aleksandra", "library", "female", "young", "radosna, wyraźna dykcja", "pl"),
            ("Tomasz", "library", "male", "old", "niski, głęboki głos", "pl"),
            ("Kasia", "library", "female", "young", "naturalna, rozmowa", "pl"),
            ("Emily", "library", "female", "young", "warm narrator, verified in Polish", "en"),
            ("Anna — mój głos", "own", "female", "middle_aged", "klon głosu z nagrań", "pl"),
            ("Rachel", "own", "female", "young", "premade English voice", "en")])], ensure_ascii=False))
    takes = eleven / "hej_jarvis" / "marek-demo0000_00"
    takes.mkdir(parents=True)
    for index in range(3):
        sf.write(takes / f"{index:05d}.wav", tone, 16000)
    model = build / server_module.TRAINED_MODEL
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"demo")
    # two kept runs of hej_jarvis for Training → Models (made-up final tests): an older one and the current one
    stream, weights, tflite, roc = ("tflite_stream_state_internal_quant", "best_weights.weights.h5",
                                    "stream_state_internal_quant.tflite", "tflite_streaming_roc.txt")
    older = home / "data" / "backup" / "training-hej_jarvis-20261028-212257"
    (older / stream).mkdir(parents=True)
    (older / weights).write_bytes(b"run-1")
    (older / stream / roc).write_text("AUC 0.41200\nCutoff 1.00: frr=1.0000; faph=0.000\n"
                                      "Cutoff 0.99: frr=0.1420; faph=0.375\nCutoff 0.95: frr=0.0810; faph=1.125\n")
    current = build / "trained"
    (current / stream).mkdir(parents=True, exist_ok=True)
    (current / weights).write_bytes(b"run-2")
    (current / stream / tflite).write_bytes(b"TFL3run-2")
    (current / stream / roc).write_text("AUC 0.63100\nCutoff 1.00: frr=1.0000; faph=0.000\n"
                                        "Cutoff 0.99: frr=0.0610; faph=0.188\nCutoff 0.97: frr=0.0420; faph=0.375\n"
                                        "Cutoff 0.93: frr=0.0290; faph=0.938\n")
    (build / "training_parameters.run.yaml").write_text(
        "training_steps: [20000]\nnegative_class_weight: [20.0]\nlearning_rates: [0.001]\n")
    esphome = root / "esphome"
    esphome.mkdir()
    for name, friendly in (("salon-voice", "Salon Voice"), ("pokoj-oli-voice", "Pokój Oli Voice")):
        (esphome / f"{name}.yaml").write_text(
            f"substitutions:\n  name: {name}\n  friendly_name: {friendly}\npackages:\n"
            "  voice: github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml\n")
    return home


class Demo:
    """What the pretend training machine reports."""

    def __init__(self) -> None:
        self.running = False
        self.log = ""

    def status(self, _runner, offset: int):
        return runner_module.Status(self.running, self.log.encode()[offset:], DEMO_GPU, True)



def demo_wake_log(now: datetime | None = None, deployed_days_ago: int = 10):
    """A made-up wake log of the demo's satellites (Wake Word Recorder's /wake_log): before the new Hej Jarvis
    model went out a few false wakes a day in the children's room, after it rarely; a source for
    Trainer.wake_log_source."""
    now = now or datetime.now()
    rows = []
    devices = [("Salon", "Salon Voice"), ("Kuchnia", "Kuchnia Voice"), ("Pokój dzieci", "Pokój dzieci Voice")]
    commands = ["Która godzina?", "Zgaś światło w salonie.", "Włącz muzykę.", "Jaka jest pogoda?"]
    false_texts = [("no_speech", ""), ("command", "Dziękuję za oglądanie!"), ("command", "Nie!"), ("cancelled", "")]
    for back in range(30, -1, -1):
        day = now - timedelta(days=back)
        before = back > deployed_days_ago
        for hour, (area, device) in zip((8, 13, 19), devices):
            when = day.replace(hour=hour, minute=7 * (back % 8), second=0, microsecond=0)
            if when <= now:
                rows.append((when, area, device, "Hej Jarvis", "command", commands[(back + hour) % 4], "action_done"))
        for n in range(3 if before else (1 if back % 3 == 0 else 0)):
            when = day.replace(hour=2 + 5 * n, minute=11, second=n, microsecond=0)
            outcome, text = false_texts[(back + n) % 4]
            if when <= now:
                rows.append((when, "Pokój dzieci", "Pokój dzieci Voice", "Hej Jarvis", outcome, text, ""))
        if back % 4 == 0:
            when = day.replace(hour=21, minute=0, second=0, microsecond=0)
            if when <= now:
                rows.append((when, "Salon", "Salon Voice", "Hej Robo", "no_speech", "", ""))
        if back in (20, 21):
            when = day.replace(hour=17, minute=30, second=0, microsecond=0)
            rows.append((when, "Kuchnia", "Kuchnia Voice", "Hej Jarvis", "command", "wake word take", "action_done"))
    rows.sort()

    def source(since: str) -> dict:
        chosen = [{"timestamp": when.strftime("%Y-%m-%d %H:%M:%S"), "area": area, "device": device, "wake_word": word,
                   "pipeline": "Wake word recording" if text == "wake word take" else f"{area} {word}",
                   "outcome": outcome, "text": text, "response": response, "seconds": 4.0,
                   "recorder": text == "wake word take"}
                  for when, area, device, word, outcome, text, response in rows
                  if not since or when.strftime("%Y-%m-%d") >= since]
        return {"rows": chosen, "total": len(chosen)}

    return source

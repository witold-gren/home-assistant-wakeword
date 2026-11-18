"""Evaluate a trained model on what matters at home.

- false rejections (FRR) per person and per group on the held-out takes — a model that works for
  the parents but not for the children is not done,
- false wakes per hour on the household's background recordings,
- a table over probability cutoffs, so you pick the cutoff instead of guessing it.

The metric code works on probability sequences and is independent of how they were produced.
:class:`TFLiteModel` produces them from a streaming ``.tflite`` model the same way ESPHome does; it
needs the optional packages ``pymicro-features`` and ``ai-edge-litert`` (``pip install .[evaluate]``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np

from .audio import SAMPLE_RATE, read_wav, resample
from .dataset import read_split, split_background
from .household import Household

CUTOFFS = (0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99)
STEP_MS = 30  # one model output per 3 feature frames of 10 ms
REFRACTORY_S = 2.0  # after a detection the device is busy; count one wake, not several
TAIL_PAD_S = 0.5  # silence after a take, so the window can fill after the word ends


class Model(Protocol):
    def probabilities(self, samples: np.ndarray) -> np.ndarray:
        """Wake word probability for every step of `samples` (16 kHz), starting from a clean state."""


def window_means(probabilities: np.ndarray, window: int) -> np.ndarray:
    """Sliding-window average as ESPHome computes it (a value only once the window is full)."""
    if window <= 1 or len(probabilities) < window:
        return probabilities if window <= 1 else np.zeros(0)
    kernel = np.ones(window) / window
    return np.convolve(probabilities, kernel, mode="valid")


def detections(probabilities: np.ndarray, cutoff: float, window: int,
               refractory_steps: int = int(REFRACTORY_S * 1000 / STEP_MS)) -> list[int]:
    """Step indices where the device would wake."""
    means = window_means(np.asarray(probabilities, dtype=np.float64), window)
    found: list[int] = []
    next_allowed = 0
    for i in np.flatnonzero(means >= cutoff):
        if i >= next_allowed:
            found.append(int(i) + window - 1)
            next_allowed = i + refractory_steps
    return found


def peak(probabilities: np.ndarray, window: int) -> float:
    """Highest window average — a take is detected when this reaches the cutoff."""
    means = window_means(np.asarray(probabilities, dtype=np.float64), window)
    return float(means.max()) if len(means) else 0.0


@dataclass(frozen=True)
class TakeScore:
    path: Path
    speaker: str
    group: str
    peak: float


@dataclass(frozen=True)
class BackgroundScore:
    path: Path
    hours: float
    probabilities: np.ndarray


def frr(scores: Iterable[TakeScore], cutoff: float) -> float:
    scores = list(scores)
    return sum(s.peak < cutoff for s in scores) / len(scores) if scores else float("nan")


def false_wakes_per_hour(backgrounds: list[BackgroundScore], cutoff: float, window: int) -> float:
    hours = sum(b.hours for b in backgrounds)
    if hours <= 0:
        return float("nan")
    wakes = sum(len(detections(b.probabilities, cutoff, window)) for b in backgrounds)
    return wakes / hours


@dataclass
class Report:
    word: str
    window: int
    takes: list[TakeScore]
    backgrounds: list[BackgroundScore]

    def rows(self, cutoffs: Iterable[float] = CUTOFFS) -> list[dict]:
        """One row per cutoff: FRR overall, per group, per person, and false wakes per hour."""
        speakers = sorted({t.speaker for t in self.takes})
        groups = sorted({t.group for t in self.takes})
        rows = []
        for cutoff in cutoffs:
            row = {"cutoff": cutoff, "frr": frr(self.takes, cutoff)}
            for group in groups:
                row[f"frr_{group}"] = frr((t for t in self.takes if t.group == group), cutoff)
            for speaker in speakers:
                row[f"frr:{speaker}"] = frr((t for t in self.takes if t.speaker == speaker), cutoff)
            row["fa_per_hour"] = false_wakes_per_hour(self.backgrounds, cutoff, self.window)
            rows.append(row)
        return rows

    def recommend(self, max_frr: float = 0.05, max_fa: float = 0.5,
                  cutoffs: Iterable[float] = CUTOFFS) -> float | None:
        """Lowest cutoff where every person's FRR ≤ max_frr and false wakes/h ≤ max_fa (when
        background was measured); None when no cutoff meets both."""
        for row in self.rows(cutoffs):
            person_frr = [v for k, v in row.items() if k.startswith("frr:")]
            fa = row["fa_per_hour"]
            if person_frr and max(person_frr) <= max_frr and (np.isnan(fa) or fa <= max_fa):
                return row["cutoff"]
        return None


def format_report(report: Report, cutoffs: Iterable[float] = CUTOFFS) -> str:
    rows = report.rows(cutoffs)
    if not rows:
        return "no data"
    keys = [k for k in rows[0] if k != "cutoff"]
    header = "cutoff  " + "  ".join(f"{k.replace('frr:', ''):>10}" for k in keys)

    def cell(key, value):
        if np.isnan(value):
            return f"{'—':>10}"
        return f"{value:>10.2f}" if key == "fa_per_hour" else f"{value * 100:>9.1f}%"

    lines = [f"word: {report.word}   takes: {len(report.takes)}   background: "
             f"{sum(b.hours for b in report.backgrounds):.2f} h   window: {report.window}",
             "FRR = share of held-out takes missed; fa_per_hour = false wakes per hour of background",
             header]
    for row in rows:
        lines.append(f"{row['cutoff']:<6.2f}  " + "  ".join(cell(k, row[k]) for k in keys))
    best = report.recommend(cutoffs=cutoffs)
    lines.append("recommended cutoff: " + (f"{best:.2f}" if best is not None else
                 "none meets FRR ≤ 5 % per person and ≤ 0.5 false wakes/h — more data needed"))
    return "\n".join(lines)


# --- "Household" in the Models card: the family's held-out takes and the home's test background ---------

FAMILY_MAX_FRR = 0.05  # every person: at most 1 take in 20 missed
FAMILY_MAX_FA_PER_DAY = 1.0  # at most one false wake a day at home
FINE_CUTOFFS = tuple(round(0.50 + 0.01 * i, 2) for i in range(50))  # 0.50 ... 0.99
HOUSEHOLD_FILE = "household.json"  # next to the kept model (data/build/<word>/models/<id>/)


def household_result(report: Report, cutoffs: Iterable[float] = FINE_CUTOFFS) -> dict:
    """Every cutoff with the misses per person and the false wakes at home, and the best cutoff.

    The score ("times") is the worse of the two goals: the worst person's misses against 5 % and the
    false wakes a day against 1 - lower is better, at most 1 = both goals met. Among cutoffs scoring
    the same: fewer takes missed in all, then the highest cutoff (fewer false wakes where the test
    cannot tell)."""
    hours = sum(b.hours for b in report.backgrounds)
    takes: dict[str, int] = {}
    for take in report.takes:
        takes[take.speaker] = takes.get(take.speaker, 0) + 1
    curve = []
    for cutoff in cutoffs:
        missed = {person: sum(t.peak < cutoff for t in report.takes if t.speaker == person) for person in takes}
        worst = max((missed[p] / takes[p] for p in takes), default=None)
        wakes = sum(len(detections(b.probabilities, cutoff, report.window)) for b in report.backgrounds)
        per_day = wakes / hours * 24 if hours > 0 else None
        parts = [x for x in (worst / FAMILY_MAX_FRR if worst is not None else None,
                             per_day / FAMILY_MAX_FA_PER_DAY if per_day is not None else None) if x is not None]
        curve.append({"cutoff": cutoff, "missed": missed, "frr_worst": worst, "false_wakes": wakes,
                      "fa_per_day": per_day, "times": max(parts) if parts else None})
    scored = [row for row in curve if row["times"] is not None]
    best = min(scored, key=lambda row: (row["times"], sum(row["missed"].values()), -row["cutoff"])) if scored else None
    if best is not None:
        best = {**best, "ready": best["times"] <= 1}
    return {"window": report.window, "hours": round(hours, 4), "takes": takes, "curve": curve, "best": best}


def inputs_signature(household: Household, word: str, window: int) -> str:
    """What the household test was measured on: a model is measured again when this changes."""
    import hashlib

    takes = sorted(str(row.path.name) for row in read_split(household, word) if row.split == "test")
    background = [f"{f.name}:{f.stat().st_size}" for f in split_background(household)[1]]
    return hashlib.md5(repr((takes, background, window)).encode()).hexdigest()


def score_takes(model: Model, household: Household, word: str, window: int) -> list[TakeScore]:
    scores = []
    for row in read_split(household, word):
        if row.split != "test":
            continue
        samples, rate = read_wav(row.path)
        samples = np.concatenate([resample(samples, rate), np.zeros(int(TAIL_PAD_S * SAMPLE_RATE), np.float32)])
        scores.append(TakeScore(row.path, row.speaker, row.group, peak(model.probabilities(samples), window)))
    return scores


def score_backgrounds(model: Model, files: list[Path]) -> list[BackgroundScore]:
    result = []
    for path in files:
        samples, rate = read_wav(path)
        samples = resample(samples, rate)
        result.append(BackgroundScore(path, len(samples) / SAMPLE_RATE / 3600, model.probabilities(samples)))
    return result


def evaluate_word(model: Model, household: Household, word: str, window: int = 5,
                  background: list[Path] | None = None) -> Report:
    """Score the held-out takes of `word` and the background recordings (default: the test part of
    data/background - dataset.split_background - never trained on)."""
    if background is None:
        background = split_background(household)[1]
    return Report(word, window, score_takes(model, household, word, window),
                  score_backgrounds(model, background))


class TFLiteModel:
    """A streaming microWakeWord model run like ESPHome runs it (optional dependencies)."""

    def __init__(self, path: Path | str):
        try:
            from pymicro_features import MicroFrontend  # noqa: F401
        except ImportError as err:
            raise RuntimeError("install the evaluation extras: pip install '.[evaluate]'") from err
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError as err:
                raise RuntimeError("install ai-edge-litert (pip install '.[evaluate]')") from err
        self.path = Path(path)
        self._interpreter_cls = Interpreter

    def _features(self, samples: np.ndarray) -> np.ndarray:
        from pymicro_features import MicroFrontend

        frontend = MicroFrontend()
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        frames = []
        chunk = 160 * 2  # 10 ms of 16-bit audio
        offset = 0
        while offset + chunk <= len(pcm):
            result = frontend.process_samples(pcm[offset: offset + chunk])
            offset += result.samples_read * 2
            if result.features:
                frames.append(result.features)
            if result.samples_read == 0:
                break
        return np.array(frames, dtype=np.float32).reshape(-1, 40)

    def probabilities(self, samples: np.ndarray) -> np.ndarray:
        interpreter = self._interpreter_cls(model_path=str(self.path))
        interpreter.allocate_tensors()
        inp = interpreter.get_input_details()[0]
        out = interpreter.get_output_details()[0]
        stride = int(inp["shape"][1])
        in_scale, in_zero = inp["quantization"]
        out_scale, out_zero = out["quantization"]
        features = self._features(samples)
        probs = []
        for start in range(0, len(features) - stride + 1, stride):
            block = features[start: start + stride]
            quant = np.clip(np.round(block / in_scale + in_zero), -128, 127).astype(inp["dtype"])
            interpreter.set_tensor(inp["index"], quant.reshape(inp["shape"]))
            interpreter.invoke()
            raw = interpreter.get_tensor(out["index"]).reshape(-1)[0]
            probs.append((float(raw) - out_zero) * out_scale)
        return np.array(probs, dtype=np.float64)

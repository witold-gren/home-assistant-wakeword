"""Read the training log (train/train.sh + microWakeWord) into stages and metrics.

The log is the only interface to the training machine: train.sh prints ``==> <word>: <stage>``
lines, microWakeWord prints a validation line every 500 steps and, at the end, the streaming test
(``AUC …`` and ``Cutoff 0.97: frr=…; faph=…``).
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

STAGE = re.compile(r"^==> (?P<text>.+)$")
WORD_STAGE = re.compile(r"^(?P<word>[a-z0-9_]+): (?P<stage>features|training|model ready.*)$")
STEP = re.compile(
    r"Step #(?P<step>\d+): rate (?P<rate>[\d.e+-]+), accuracy (?P<accuracy>[\d.]+)%, recall (?P<recall>[\d.]+)%, "
    r"precision (?P<precision>[\d.]+)%, cross entropy (?P<loss>[\d.e+-]+)"
)
VALIDATION = re.compile(
    r"Step (?P<step>\d+) \(nonstreaming\): Validation: recall at no faph = (?P<recall_no_faph>[\d.]+) with cutoff "
    r"(?P<cutoff_no_faph>[\d.]+), accuracy = (?P<accuracy>[\d.]+)%, recall = (?P<recall>[\d.]+)%, precision = "
    r"(?P<precision>[\d.]+)%, ambient false positives = (?P<false_positives>\d+), estimated false positives per "
    r"hour = (?P<faph>[\d.]+), loss = (?P<loss>[\d.e+-]+), auc = (?P<auc>[\d.]+), average viable recall = "
    r"(?P<avr>[\d.]+)"
)
BEST = re.compile(r"So far the best minimization quantity is [\d.]+ with best maximization quantity of "
                  r"(?P<avr>[\d.]+)%; no faph cutoff is (?P<cutoff>[\d.]+)")
AUC = re.compile(r"\bAUC (?P<auc>[\d.]+)")
CUTOFF = re.compile(r"Cutoff (?P<cutoff>[\d.]+): frr=(?P<frr>[\d.]+); faph=(?P<faph>[\d.]+)")
PLAN = re.compile(r"^training plan: steps=(?P<steps>\d+) started=(?P<started>\d+)"
                  r"(?: negative_weight=(?P<negative_weight>[\d.]+))?"
                  r"(?: phases=(?P<phases>[\d.:e,-]+))?"  # steps:learning rate of every phase
                  r"(?: weights=(?P<weights>[a-z_\d.:e,-]*))?$")  # set:sampling weight (Training → Parameters and start)
ERROR = re.compile(r"(Traceback \(most recent call last\)|^\w*Error: |no model produced|TensorFlow does not see a GPU"
                   r"|^error: )")

# What "good" means (docs: chapter 9 "How to follow training")
GOOD = {"avr": 0.90, "very_good_avr": 0.95, "faph": 0.5, "faph_ok": 1.0, "recall_no_faph": 80.0, "frr": 0.05}

# The advice after the final test: what to change for the next run
DEFAULT_NEGATIVE_WEIGHT = 20.0  # wakeword.training_config
MORE_STEPS = 20000  # a next run continues from the saved state for this many steps
TUNE_STEPS = 10000  # steps of a run that only changes the negative weight
MAX_NEGATIVE_WEIGHT = 80.0
MIN_NEGATIVE_WEIGHT = 5.0
MAX_TOTAL_STEPS = 80000  # beyond this more steps rarely help - more data does
WEAK_AVR = 0.75  # below this after a whole run the recordings, not the parameters, are the problem
# the main score jumping more than this in the second half: the learning rate never settled, and which
# weights were kept was luck - train again before tuning anything (first real run: 0.09-0.85)
UNSTABLE_SPREAD = 0.4
# misses words and wakes falsely: tune the side that misses its goal by this much more than the other
CLEARLY_WORSE = 1.3


@dataclass
class Point:
    step: int
    avr: float
    faph: float
    recall: float
    recall_no_faph: float
    cutoff_no_faph: float
    accuracy: float
    loss: float


@dataclass
class RocPoint:
    cutoff: float
    frr: float
    faph: float


@dataclass
class WordProgress:
    word: str
    stage: str = "waiting"  # waiting | features | training | testing | done
    train_accuracy: float | None = None
    train_loss: float | None = None
    last_step: int = 0
    points: list[Point] = field(default_factory=list)
    best_avr: float | None = None
    best_cutoff: float | None = None
    auc: float | None = None
    roc: list[RocPoint] = field(default_factory=list)
    model: str | None = None
    total_steps: int | None = None  # from train.sh's "training plan" line
    started_at: float | None = None  # when this run's training began (machine clock)
    negative_weight: float | None = None  # negative_class_weight of this run
    phases: list[list[float]] = field(default_factory=list)  # [steps, learning rate] per phase (the chart's bands)

    @property
    def step(self) -> int:
        return max(self.last_step, self.points[-1].step if self.points else 0)

    @property
    def percent(self) -> float | None:
        if not self.total_steps:
            return None
        return round(min(100.0, 100 * self.step / self.total_steps), 1)

    def remaining_seconds(self, now: float) -> float | None:
        """Time left at the pace of this run so far (None until it can be estimated).

        microWakeWord counts every run from step 1 (a next run loads the saved weights but not the
        step) and logs a step every 500, so the first estimate comes with step 500.
        """
        if self.stage != "training" or not self.total_steps or self.started_at is None:
            return None
        elapsed = now - self.started_at
        if self.step <= 0 or elapsed <= 0:
            return None
        return max(0.0, (self.total_steps - self.step) * elapsed / self.step)

    def still_improving(self) -> bool:
        """The best validation came in the last quarter of the run, clearly above the earlier best."""
        if len(self.points) < 4:
            return False
        split = len(self.points) * 3 // 4
        return max(p.avr for p in self.points[split:]) > max(p.avr for p in self.points[:split]) + 0.005

    def advice(self, default_negative_weight: float = DEFAULT_NEGATIVE_WEIGHT) -> dict | None:
        """What to do after the final test: deploy, or which parameter to change and why.

        {"kind": ..., "change": {"steps": n, "negative_weight": w}, "facts": {...numbers for the text}}
        """
        if not self.roc:
            return None
        weight = self.negative_weight or default_negative_weight
        total = self.total_steps or 0
        best_avr = max((p.avr for p in self.points), default=None)
        pick = self.recommended_cutoff
        facts = {"steps": total or None, "negative_weight": weight, "best_avr": best_avr, "cutoff": pick}
        # the best the final test offers on each side of the trade-off; a cutoff the model never
        # reaches (it misses every word) is quiet but no answer - it made "lower the weight" out of every run
        usable = [p for p in self.roc if p.frr < 1.0]
        catch = [p for p in usable if p.frr <= GOOD["frr"]]
        quiet = [p for p in usable if p.faph <= GOOD["faph"]]
        if catch:
            facts["faph_at_good_frr"] = min(p.faph for p in catch)
        if quiet:
            facts["frr_at_good_faph"] = min(p.frr for p in quiet)
        improving = self.still_improving() and total < MAX_TOTAL_STEPS

        def result(kind: str, **change) -> dict:
            return {"kind": kind, "change": change, "facts": facts}

        if pick is not None:
            return result("ready_more_steps", steps=MORE_STEPS) if improving else result("ready")
        late = [p.avr for p in self.points[len(self.points) // 2:]]
        if len(late) >= 4 and max(late) - min(late) > UNSTABLE_SPREAD:
            facts.update(avr_low=min(late), avr_high=max(late))
            return result("unstable", steps=total or MORE_STEPS)
        if improving:
            return result("more_steps", steps=MORE_STEPS)
        if best_avr is not None and best_avr < WEAK_AVR:
            return result("more_data")
        # only one goal within reach: move the weight towards the other one; both (but not together):
        # the balance below decides - doubling the weight there trades one miss for another
        if catch and not quiet and weight < MAX_NEGATIVE_WEIGHT:
            return result("raise_negative_weight", steps=TUNE_STEPS,
                          negative_weight=min(MAX_NEGATIVE_WEIGHT, round(weight * 2)))
        if quiet and not catch and weight > MIN_NEGATIVE_WEIGHT:
            return result("lower_negative_weight", steps=TUNE_STEPS,
                          negative_weight=max(MIN_NEGATIVE_WEIGHT, round(weight * 0.6)))
        if usable:
            # neither goal reached: at the most balanced cutoff, which goal is missed by far more?
            missed = lambda p: (p.frr / GOOD["frr"], p.faph / GOOD["faph"])
            balanced = min(usable, key=lambda p: max(missed(p)))
            frr_times, faph_times = missed(balanced)
            facts.update(balance_cutoff=balanced.cutoff, balance_frr=balanced.frr, balance_faph=balanced.faph)
            if faph_times > frr_times * CLEARLY_WORSE and weight < MAX_NEGATIVE_WEIGHT:
                return result("close_raise_negative_weight", steps=TUNE_STEPS,
                              negative_weight=min(MAX_NEGATIVE_WEIGHT, round(weight * 1.5)))
            if frr_times > faph_times * CLEARLY_WORSE and weight > MIN_NEGATIVE_WEIGHT:
                return result("close_lower_negative_weight", steps=TUNE_STEPS,
                              negative_weight=max(MIN_NEGATIVE_WEIGHT, round(weight * 0.75)))
        if total and total < MAX_TOTAL_STEPS:
            return result("more_steps_mixed", steps=MORE_STEPS)  # misses words and wakes falsely
        return result("more_data")

    @property
    def recommended_cutoff(self) -> float | None:
        """Lowest cutoff of the final test with frr ≤ 5 % and ≤ 0.5 false wakes per hour."""
        good = [p for p in self.roc if p.frr <= GOOD["frr"] and p.faph <= GOOD["faph"]]
        return min(good, key=lambda p: p.cutoff).cutoff if good else None

    def verdict(self) -> str:
        """good | ok | bad | unknown - from the final test or, during training, the last validation."""
        if self.roc:
            return "good" if self.recommended_cutoff is not None else "bad"
        if not self.points:
            return "unknown"
        last = self.points[-1]
        if last.avr >= GOOD["avr"] and last.faph <= GOOD["faph_ok"]:
            return "good"
        if last.avr >= 0.75:
            return "ok"
        return "bad"

    def as_dict(self, now: float | None = None) -> dict:
        data = asdict(self)
        data["recommended_cutoff"] = self.recommended_cutoff
        data["verdict"] = self.verdict()
        data["step"] = self.step
        data["percent"] = self.percent
        data["remaining_seconds"] = self.remaining_seconds(time.time() if now is None else now)
        data["advice"] = self.advice()
        return data


@dataclass
class Progress:
    stage: str = ""  # last ==> line
    current_word: str | None = None
    words: dict[str, WordProgress] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    finished: bool = False

    def word(self, name: str) -> WordProgress:
        if name not in self.words:
            self.words[name] = WordProgress(name)
        return self.words[name]

    def as_dict(self, now: float | None = None) -> dict:
        return {
            "stage": self.stage,
            "current_word": self.current_word,
            "finished": self.finished,
            "errors": self.errors[-5:],
            "words": {k: v.as_dict(now) for k, v in self.words.items()},
        }


def clean_lines(text: str) -> list[str]:
    """Log lines as a terminal shows them (progress bars rewrite a line with carriage returns)."""
    return [line.rsplit("\r", 1)[-1] for line in text.replace("\r\n", "\n").split("\n")]


def parse(text: str) -> Progress:
    progress = Progress()
    word: WordProgress | None = None
    for line in clean_lines(text):
        if match := STAGE.match(line):
            stage = match["text"].strip()
            progress.stage = stage
            if stage.startswith("done"):
                progress.finished = True
            if ws := WORD_STAGE.match(stage):
                word = progress.word(ws["word"])
                progress.current_word = word.word
                name = ws["stage"]
                if name.startswith("model ready"):
                    word.stage = "done"
                    word.model = name.split("→", 1)[-1].strip() if "→" in name else None
                else:
                    word.stage = name
            continue
        if word is None:
            if ERROR.search(line):
                progress.errors.append(line.strip())
            continue
        if match := PLAN.match(line.strip()):
            word.total_steps, word.started_at = int(match["steps"]), float(match["started"])
            word.negative_weight = float(match["negative_weight"]) if match["negative_weight"] else None
            word.phases = [[int(steps), float(rate)] for steps, rate in
                           (part.split(":") for part in match["phases"].split(","))] if match["phases"] else []
            continue
        if match := VALIDATION.search(line):
            word.points.append(Point(
                step=int(match["step"]), avr=float(match["avr"]), faph=float(match["faph"]),
                recall=float(match["recall"]), recall_no_faph=float(match["recall_no_faph"]),
                cutoff_no_faph=float(match["cutoff_no_faph"]), accuracy=float(match["accuracy"]),
                loss=float(match["loss"]),
            ))
        elif match := STEP.search(line):
            word.last_step = int(match["step"])
            word.train_accuracy = float(match["accuracy"])
            word.train_loss = float(match["loss"])
        elif match := BEST.search(line):
            word.best_avr = round(float(match["avr"]) / 100, 6)
            word.best_cutoff = float(match["cutoff"])
        elif match := AUC.search(line):
            word.auc = float(match["auc"])
            word.roc = []
            if word.stage == "training":
                word.stage = "testing"
        elif match := CUTOFF.search(line):
            word.roc.append(RocPoint(float(match["cutoff"]), float(match["frr"]), float(match["faph"])))
        elif ERROR.search(line):
            progress.errors.append(line.strip())
    return progress


def tail(text: str, lines: int = 200) -> str:
    return "\n".join(clean_lines(text)[-lines:])

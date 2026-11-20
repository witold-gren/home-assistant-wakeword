"""Which of the kept models of a word is best, and why (the studio's Training → Models).

Every model has a final test: for each cutoff, how many words it misses (FRR) and how often it wakes
by itself (false wakes per hour). The goals are at most 5 % missed and at most 0.5 false wakes per
hour (progress.GOOD). A model is scored at its most balanced cutoff: how many times over the goal
it is on the worse of the two - 1 or less means both goals met. The lowest score is best; with the
same score the smaller AUC (the whole curve) decides.

That test is "neutral": mostly synthetic voices and public recordings - the word for anyone. The
"household" test (wakeword evaluate-models, household.json next to the model) measures the family's
held-out takes per person and false wakes in the home's own background; scored the same way against
its goals (evaluate.FAMILY_MAX_FRR, FAMILY_MAX_FA_PER_DAY). Both bests are given; the panel ranks by
the one chosen.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from .progress import GOOD

MODEL_ID = re.compile(r"^\d{8}-\d{6}$")  # train/models.py
WEIGHTS = "best_weights.weights.h5"


def best_point(roc: list[list[float]]) -> dict | None:
    """The cutoff to judge a model by: the lowest that meets both goals, else the most balanced one."""
    usable = [(cutoff, frr, faph) for cutoff, frr, faph in roc if frr < 1.0]  # 1.0: never wakes at all
    if not usable:
        return None

    def times(point) -> float:
        return max(point[1] / GOOD["frr"], point[2] / GOOD["faph"])

    ready = [p for p in usable if p[1] <= GOOD["frr"] and p[2] <= GOOD["faph"]]
    cutoff, frr, faph = min(ready, key=lambda p: p[0]) if ready else min(usable, key=times)
    return {"cutoff": cutoff, "frr": frr, "faph": faph, "times": round(times((cutoff, frr, faph)), 3),
            "ready": bool(ready)}


def rank(listing: dict) -> dict:
    """The listing of train/models.py with both scores per model and the best one of each.

    "best": the neutral test (score); "best_household": the household test (household_score)."""
    for model in listing["models"]:
        model["score"] = best_point(model.get("roc") or [])
        best = (model.get("household") or {}).get("best")
        model["household_score"] = best if best and best.get("times") is not None else None
    scored = [m for m in listing["models"] if m["score"]]
    best = min(scored, key=lambda m: (m["score"]["times"], m["auc"] if m["auc"] is not None else 9)) if scored else None
    listing["best"] = best["id"] if best else None
    # the household test: the lowest score, then the neutral one (a tie on a few takes is common)
    scored = [m for m in listing["models"] if m["household_score"]]
    best = min(scored, key=lambda m: (m["household_score"]["times"],
                                      m["score"]["times"] if m["score"] else 99)) if scored else None
    listing["best_household"] = best["id"] if best else None
    return listing


@lru_cache(maxsize=256)
def _md5(path: str, mtime: float, size: int) -> str:  # mtime and size: a changed file is read again
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return _md5(str(path), stat.st_mtime, stat.st_size)


def local_model(build: Path) -> dict | None:
    """Which kept model is in trained/ on this computer (the one the last training or Choose put there): what export takes.

    {"id", "name", "number"} - the number in the order the models were made, as in the Models card.
    """
    current = _digest(Path(build) / "trained" / WEIGHTS)
    folder = Path(build) / "models"
    if current is None or not folder.is_dir():
        return None
    ids = sorted(p.name for p in folder.iterdir() if p.is_dir() and MODEL_ID.match(p.name))
    for number, model_id in enumerate(ids, 1):
        if _digest(folder / model_id / WEIGHTS) == current:
            try:
                name = json.loads((folder / model_id / "run.json").read_text(encoding="utf-8")).get("name", "")
            except (OSError, ValueError):
                name = ""
            return {"id": model_id, "name": name, "number": number}
    return None

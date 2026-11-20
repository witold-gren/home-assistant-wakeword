#!/usr/bin/env python3
"""Trained models of a word on the training machine: list them, keep each run's model, choose the base.

    python3 train/models.py list    <household> <word>
    python3 train/models.py archive <household> <word> [--config <training_parameters.run.yaml>] [--started <unix time>]
    python3 train/models.py select  <household> <word> <model id | new>
    python3 train/models.py log     <household> <word> <model id>      (the run's log, gzip, to stdout)

Every finished run is kept in ``data/build/<word>/models/<id>/`` (id = the time it was kept,
``20261028-221357``): its best weights, the streaming model, the final test
(``tflite_streaming_roc.txt``) and ``run.json`` (steps, negative weight, learning rates, times).
Copies an older train.sh left in ``data/backup/training-<word>-<time>/`` are taken in on listing.

The next training continues from ``trained/restore/`` - the state the last run ended with.
``select`` puts a kept model in ``trained/`` instead (train/set_base.py then makes the checkpoint
from its weights) or, with ``new``, moves ``trained/`` aside so the next run starts from scratch.
``models/base`` says which model the next run starts from.

Standard library only (also run by the panel over SSH with the system python3); ``archive`` reads
the run's YAML with PyYAML from the training venv.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import sys
import time

WEIGHTS = "best_weights.weights.h5"
STREAM_DIR = "tflite_stream_state_internal_quant"
TFLITE = "stream_state_internal_quant.tflite"
ROC = "tflite_streaming_roc.txt"
RUN = "run.json"
LOG = "train.log.gz"  # the run's log: the panel draws its chart and final test again from it
HOUSEHOLD = "household.json"  # the household test (wakeword evaluate-models): family takes, home background
TRAIN_LOG = "train.log"  # data/build/train.log, written by train.sh
BASE = "base"
NEW = "new"
# a name to tell models apart (Polish, like the household's words): adjective + noun in the right gender
ADJECTIVES = ("mały", "duży", "gruby", "chudy", "szybki", "wolny", "cichy", "głośny", "czerwony", "zielony", "żółty",
              "niebieski", "złoty", "srebrny", "wesoły", "sprytny", "dzielny", "senny", "ciepły", "zimny", "słodki",
              "kwaśny", "ostry", "miękki", "twardy", "jasny", "ciemny", "dziki", "rudy", "biały")
NOUNS = {"m": ("ananas", "ogórek", "pomidor", "kot", "lis", "jeż", "borsuk", "bóbr", "orzech", "kasztan", "grzyb",
               "księżyc", "kamień", "wiatr", "ptak", "żółw", "miś", "banan", "burak", "słonecznik"),
         "f": ("gruszka", "śliwka", "cebula", "marchewka", "sowa", "wiewiórka", "truskawka", "malina", "chmura",
               "gwiazda", "rzeka", "pszczoła", "kaczka", "żaba", "morela", "wiśnia", "papryka", "dynia", "róża", "foka")}
LEGACY = re.compile(r"^training-(?P<word>.+)-(?P<id>\d{8}-\d{6})$")
ID = re.compile(r"^\d{8}-\d{6}$")


def word_dir(household: Path, word: str) -> Path:
    return Path(household) / "data" / "build" / word


def models_dir(household: Path, word: str) -> Path:
    return word_dir(household, word) / "models"


def trained_dir(household: Path, word: str) -> Path:
    return word_dir(household, word) / "trained"


def parse_roc(text: str) -> dict:
    """``AUC 0.30388`` and ``Cutoff 0.99: frr=0.1097; faph=0.375`` lines of microWakeWord's final test."""
    auc = re.search(r"AUC ([\d.]+)", text)
    roc = [[float(m[1]), float(m[2]), float(m[3])]
           for m in re.finditer(r"Cutoff ([\d.]+): frr=([\d.]+); faph=([\d.]+)", text)]
    return {"auc": float(auc[1]) if auc else None, "roc": roc}


def _md5(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.md5()  # noqa: S324 - tells copies apart, not security
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_name(model_id: str, taken: set[str]) -> str:
    """"gruby_ogórek", "cicha_sowa": the same id gives the same name, unless another model of the word has it."""
    rng = random.Random(model_id)
    while True:
        gender = rng.choice(("m", "f"))
        adjective = rng.choice(ADJECTIVES)
        if gender == "f":
            adjective = adjective[:-1] + "a"  # mały → mała, szybki → szybka
        name = f"{adjective}_{rng.choice(NOUNS[gender])}"
        if name not in taken:
            return name


def _names(folder: Path) -> set[str]:
    names = set()
    for run in folder.glob(f"*/{RUN}") if folder.is_dir() else []:
        try:
            names.add(json.loads(run.read_text(encoding="utf-8")).get("name"))
        except (OSError, ValueError):
            pass
    return names - {None}


def _keep(source_weights: Path, source_stream: Path, target: Path, run: dict) -> None:
    run.setdefault("name", model_name(target.name, _names(target.parent)))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_weights, target / WEIGHTS)
    for name in (TFLITE, ROC):
        if (source_stream / name).is_file():
            shutil.copyfile(source_stream / name, target / name)
    (target / RUN).write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def import_legacy(household: Path, word: str) -> None:
    """Copies of the model an older train.sh made before each run (data/backup/training-<word>-<time>)."""
    backup = Path(household) / "data" / "backup"
    for folder in sorted(backup.glob(f"training-{word}-*")) if backup.is_dir() else []:
        match = LEGACY.match(folder.name)
        target = models_dir(household, word) / match["id"] if match and match["word"] == word else None
        if target is None or target.exists() or not (folder / WEIGHTS).is_file():
            continue
        _keep(folder / WEIGHTS, folder / STREAM_DIR, target,
              {"note": "kept by an older train.sh before the next run", "from": folder.name})


def read_base(household: Path, word: str) -> str | None:
    marker = models_dir(household, word) / BASE
    return marker.read_text(encoding="utf-8").strip() or None if marker.is_file() else None


def write_base(household: Path, word: str, model_id: str) -> None:
    folder = models_dir(household, word)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / BASE).write_text(model_id + "\n", encoding="utf-8")


def list_models(household: Path, word: str) -> dict:
    import_legacy(household, word)
    # the model of the last run, when it ended before runs were kept: on the list with that run's settings
    run_config = word_dir(household, word) / "training_parameters.run.yaml"
    try:
        kept = archive(household, word, run_config if run_config.is_file() else None)
    except ImportError:  # the system python3 over SSH, without PyYAML: the settings stay unknown
        kept = archive(household, word)
    if kept and read_base(household, word) is None:
        write_base(household, word, kept)  # the next run continues from where this one ended
    current = _md5(trained_dir(household, word) / WEIGHTS)
    models = []
    folder = models_dir(household, word)
    for model in sorted(p for p in folder.iterdir() if p.is_dir() and ID.match(p.name)) if folder.is_dir() else []:
        try:
            run = json.loads((model / RUN).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            run = {}
        if not run.get("name"):  # kept before models had names: one for good
            run["name"] = model_name(model.name, _names(folder))
            (model / RUN).write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        roc = parse_roc((model / ROC).read_text(encoding="utf-8")) if (model / ROC).is_file() else {"auc": None, "roc": []}
        try:
            household_test = json.loads((model / HOUSEHOLD).read_text(encoding="utf-8"))
            household_test.pop("curve", None)  # the panel needs the best cutoff, not every one
        except (OSError, ValueError):
            household_test = None
        models.append({"id": model.name, "run": run, **roc, "chart": (model / LOG).is_file(), "household": household_test,
                       "current": current is not None and _md5(model / WEIGHTS) == current})
    return {"word": word, "models": models, "base": read_base(household, word),
            "trained": current is not None}


def archive(household: Path, word: str, config: Path | None = None, started: float | None = None,
            with_log: bool = False) -> str | None:
    """Keep the model now in trained/ (a run just ended, or one trained before models were kept).

    The same weights kept already: only the final test of that model is refreshed (e.g. after
    "convert only"). ``with_log``: only at the end of a run - before a run train.log holds the new one.
    Returns the model id.
    """
    trained = trained_dir(household, word)
    weights = trained / WEIGHTS
    if not weights.is_file():
        return None
    import_legacy(household, word)
    digest = _md5(weights)
    folder = models_dir(household, word)
    for model in sorted(folder.iterdir()) if folder.is_dir() else []:
        if model.is_dir() and _md5(model / WEIGHTS) == digest:
            if (trained / STREAM_DIR / ROC).is_file():
                shutil.copyfile(trained / STREAM_DIR / ROC, model / ROC)
            return model.name
    run: dict = {"finished": int(time.time())}
    if started:
        run["started"] = int(started)
    if config and Path(config).is_file():
        import yaml  # the training venv

        parameters = yaml.safe_load(Path(config).read_text(encoding="utf-8"))
        run.update(steps=sum(int(s) for s in parameters.get("training_steps", [])),
                   negative_weight=(parameters.get("negative_class_weight") or [None])[-1],
                   learning_rates=parameters.get("learning_rates"), base=read_base(household, word),
                   weights={f["features_dir"].rstrip("/").rsplit("/", 1)[-1]: f["sampling_weight"]
                            for f in parameters.get("features", []) if f.get("sampling_weight")})
    moment = time.time()
    while (folder / (model_id := time.strftime("%Y%m%d-%H%M%S", time.localtime(moment)))).exists():
        moment += 1  # two kept in one second: the next free one
    _keep(weights, trained / STREAM_DIR, folder / model_id, run)
    if with_log:
        keep_log(household, folder / model_id)
    return model_id


def keep_log(household: Path, model: Path) -> None:
    """The log of the run that just ended, next to its model (compressed: it is mostly progress bars)."""
    log = Path(household) / "data" / "build" / TRAIN_LOG
    if log.is_file() and not (model / LOG).is_file():
        (model / LOG).write_bytes(gzip.compress(log.read_bytes()))


def read_log(household: Path, word: str, model_id: str) -> bytes:
    if not ID.match(model_id):
        raise ValueError(f"not a model id: {model_id}")
    log = models_dir(household, word) / model_id / LOG
    if not log.is_file():
        raise ValueError(f"no log kept with model {model_id}")
    return log.read_bytes()


def select(household: Path, word: str, model_id: str) -> None:
    """The model the next run starts from (``new``: from scratch). The checkpoint: train/set_base.py."""
    trained = trained_dir(household, word)
    if model_id == NEW:
        if trained.is_dir():
            archive(household, word)  # nothing trained is lost
            aside = Path(household) / "data" / "backup" / f"trained-{word}-{time.strftime('%Y%m%d-%H%M%S')}"
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trained), aside)
        write_base(household, word, NEW)
        return
    if not ID.match(model_id):
        raise ValueError(f"not a model id: {model_id}")
    model = models_dir(household, word) / model_id
    if not (model / WEIGHTS).is_file():
        raise ValueError(f"no such model: {model_id}")
    archive(household, word)  # the model trained now stays on the list
    (trained / STREAM_DIR).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(model / WEIGHTS, trained / WEIGHTS)
    for name in (TFLITE, ROC):
        target = trained / STREAM_DIR / name
        if (model / name).is_file():
            shutil.copyfile(model / name, target)
        else:
            target.unlink(missing_ok=True)
    shutil.rmtree(trained / "restore", ignore_errors=True)  # set_base.py writes the new one
    write_base(household, word, model_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["list", "archive", "select", "log"])
    parser.add_argument("household", type=Path)
    parser.add_argument("word")
    parser.add_argument("model", nargs="?")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--started", type=float)
    parser.add_argument("--log", action="store_true", help="archive: keep data/build/train.log with the model")
    args = parser.parse_args()
    try:
        if args.command == "list":
            print(json.dumps(list_models(args.household, args.word)))
        elif args.command == "archive":
            model_id = archive(args.household, args.word, args.config, args.started, args.log)
            if model_id:
                write_base(args.household, args.word, model_id)  # the next run continues from this one
                print(f"{args.word}: model kept as {model_id} (studio: Training → Models)")
        elif args.command == "log":
            sys.stdout.buffer.write(read_log(args.household, args.word, args.model or ""))
        else:
            select(args.household, args.word, args.model or "")
            print(f"{args.word}: the next training starts from {args.model}")
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command line: ``wakeword <command>`` — run ``wakeword --help`` for the list."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import __version__
from .household import HouseholdError, load_household

TRAIN_HINT = ("On the training machine run:\n"
              "  train/train.sh {household} {word}\n"
              "(see docs/en/06-training.md)")


def _household(args):
    return load_household(args.household)


def _speakers(values: list[str]) -> list[tuple[str, str]]:
    result = []
    for value in values:
        sid, _, group = value.partition(":")
        result.append((sid, group or "adult"))
    return result


def _spellings(values: list[str]) -> dict[str, list[str]]:
    """`pl=dżarwis,dżarwys` → {"pl": ["dżarwis", "dżarwys"]}."""
    result: dict[str, list[str]] = {}
    for value in values:
        lang, sep, texts = value.partition("=")
        if not sep or not texts:
            raise HouseholdError(f"--spelling '{value}': use language=text[,text…]")
        result.setdefault(lang.strip(), []).extend(t.strip() for t in texts.split(",") if t.strip())
    return result


def _words(household, args) -> list[str]:
    if getattr(args, "all", False):
        return list(household.words)
    if not args.word:
        raise HouseholdError("name a word or use --all")
    for word in args.word:
        if word not in household.words:
            raise HouseholdError(f"unknown word '{word}' (known: {', '.join(household.words)})")
    return args.word


# --- commands ---------------------------------------------------------------------------------

def cmd_init(args):
    from .scaffold import init_household

    file = init_household(args.household, _speakers(args.speaker), args.ui_language)
    print(f"created {file}\nnext: wakeword add-word …")


def cmd_add_speaker(args):
    from .scaffold import add_speaker

    household = add_speaker(args.household, args.id, args.group, args.word)
    print(f"speakers: {', '.join(household.speakers)}")


def cmd_add_word(args):
    from .scaffold import add_word

    household = add_word(args.household, args.id, args.wake_word, _spellings(args.spelling),
                         speakers=args.speaker, trained_languages=args.language,
                         sound_alikes=args.sound_alike)
    word = household.words[args.id]
    print(f"{word.id}: '{word.wake_word}' for {', '.join(word.speakers)}")


def cmd_set_device(args):
    from .scaffold import set_device

    household = set_device(args.household, args.device, args.words)
    print(f"{args.device}: {', '.join(household.devices[args.device])}")


def cmd_make_cert(args):
    from .recorder.certs import make_cert

    household = _household(args)
    cert, key = make_cert(household.data_dir / "certs", args.address or None)
    print(f"certificate: {cert}\nkey: {key}")


def cmd_record(args):
    from .recorder import serve
    from .recorder.certs import local_addresses, make_cert

    household = _household(args)
    cert = key = None
    if not args.http:
        folder = household.data_dir / "certs"
        cert, key = folder / "cert.pem", folder / "key.pem"
        if not cert.exists():
            cert, key = make_cert(folder)
    scheme = "http" if args.http else "https"
    print(f"Recorder for '{household.name}' — open on a phone or computer in the same network:")
    for address in local_addresses():
        print(f"  {scheme}://{address}:{args.port}/")
    if not args.http:
        print("The browser warns about the certificate (it is your own) — accept it once.")
    print("Ctrl+C stops the recorder.")
    serve(household.root, host=args.host, port=args.port, cert=cert, key=key)


def cmd_studio(args):
    from .studio import serve

    root = Path(args.household or os.environ.get("WAKEWORD_HOUSEHOLD") or ".")
    serve(root, host=args.host, port=args.port)


def cmd_import(args):
    from .dataset import import_files

    household = _household(args)
    results = import_files(household, args.word[0], args.speaker, [Path(f) for f in args.files])
    failed = 0
    for src, take, issues in results:
        target = take.path.name if take else "not imported"
        note = f" ({', '.join(issues)})" if issues else ""
        failed += take is None
        print(f"{src} → {target}{note}")
    return 1 if failed else 0


def cmd_check(args):
    from .dataset import check_household, format_report

    report = check_household(_household(args))
    print(format_report(report))
    return 0 if report.complete else 1


def cmd_split(args):
    from .dataset import split_word, write_split

    household = _household(args)
    for word in _words(household, args):
        rows = split_word(household, word, args.held_out, args.seed)
        path = write_split(household, rows, word)
        test = sum(r.split == "test" for r in rows)
        print(f"{word}: {len(rows) - test} train, {test} test → {path}")


def cmd_expand(args):
    from .expand import expand_word

    household = _household(args)
    for word in _words(household, args):
        written = expand_word(household, word, args.per_take, args.seed)
        print(f"{word}: {len(written)} expanded takes")


def cmd_preview(args):
    from .augment import preview_word

    household = _household(args)
    for word in _words(household, args):
        written = preview_word(household, word, args.count, args.seed)
        print(f"{word}: {len(written)} files in {written[0].parent} — listen to them")


def _voices(values: list[str]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for value in values or []:
        lang, sep, voice = value.partition("=")
        if not sep:
            raise HouseholdError(f"--voice '{value}': use language=voice")
        result.setdefault(lang, []).append(voice)
    return {k: tuple(v) for k, v in result.items()}


def cmd_synthetic(args):
    from .synthetic import plan_jobs, summary, write_script

    household = _household(args)
    for word in _words(household, args):
        jobs = plan_jobs(household, word, args.positives, args.per_voice, args.negatives, _voices(args.voice))
        path = write_script(household, word, jobs)
        print(f"{word}: {path}\n{summary(jobs)}")


def cmd_elevenlabs(args):
    from .elevenlabs import generate

    household = _household(args)
    for word in _words(household, args):
        generate(household, word, log=lambda line: print(line, flush=True))


def cmd_ha_pull(args):
    from .ha_sync import HaError, pull

    try:
        pull(args.household, log=lambda line: print(line, flush=True))
    except HaError as err:
        if not args.optional:
            raise
        print(f"Home Assistant skipped: {err}", flush=True)  # e.g. before Prepare, HA restarting


def cmd_ha_push(args):
    from .ha_sync import push_household

    push_household(args.household)
    print("household.yaml sent to Home Assistant")


def cmd_config(args):
    from .elevenlabs import drop_stale, takes_summary
    from .training_config import write_build

    household = _household(args)
    for word in _words(household, args):
        drop_stale(household, word)  # a removed language or voice: its takes must not be trained on
        paths = write_build(household, word, steps=args.steps)
        eleven = takes_summary(household, word)
        print(f"{word}: ElevenLabs " + (f"{eleven[0]} takes from {eleven[1]} voices (data/elevenlabs/{word})" if eleven
                                        else "none - optional, the ElevenLabs tab of the panel"))
        print(f"{word}: {paths['training_parameters']}\n       {paths['features']}")


def cmd_prepare(args):
    """split + expand + synthetic + config: everything the training machine needs."""
    from .dataset import check_household, format_report

    household = _household(args)
    report = check_household(household)
    # only the chosen words must be complete (e.g. a test word recorded by one person)
    words = set(_words(household, args))
    missing = [c for (word, _), c in report.cells.items() if word in words and not c.complete]
    if missing and not args.force:
        print(format_report(report))
        print("\nRecordings are not complete — record the rest or use --force:")
        for cell in missing:
            print(f"  {cell.speaker} / {cell.word}: {cell.good}/{cell.target}")
        return 1
    for step in (cmd_split, cmd_expand, cmd_synthetic, cmd_config):
        step(args)
    for word in _words(household, args):
        print(TRAIN_HINT.format(household=household.root, word=word))
    return 0


def cmd_evaluate(args):
    from .evaluate import CUTOFFS, TFLiteModel, evaluate_word, format_report
    from .export import TRAINED_MODEL
    from .synthetic import build_dir

    household = _household(args)
    word = _words(household, args)[0]
    model = Path(args.model) if args.model else build_dir(household, word) / TRAINED_MODEL
    report = evaluate_word(TFLiteModel(model), household, word, args.window,
                           [Path(p) for p in args.background] if args.background else None)
    print(format_report(report, CUTOFFS))


def cmd_evaluate_models(args):
    """The household test of every kept model of a word (on the training machine): household.json next to it."""
    import json
    import time

    from .evaluate import HOUSEHOLD_FILE, TFLiteModel, evaluate_word, household_result, inputs_signature
    from .synthetic import build_dir

    household = _household(args)
    word = _words(household, args)[0]
    signature = inputs_signature(household, word, args.window)
    folder = build_dir(household, word) / "models"
    for model in sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []:
        tflite, out = model / "stream_state_internal_quant.tflite", model / HOUSEHOLD_FILE
        if not tflite.is_file():
            continue
        if args.missing and out.is_file():
            try:
                if json.loads(out.read_text(encoding="utf-8")).get("inputs") == signature:
                    continue  # measured on the same takes and background
            except ValueError:
                pass
        started = time.time()
        result = household_result(evaluate_word(TFLiteModel(tflite), household, word, args.window))
        result["inputs"] = signature
        out.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
        best = result["best"]
        print(f"{word} {model.name}: " + (
            f"cutoff {best['cutoff']:.2f}: worst person misses {best['frr_worst'] * 100:.0f}%, "
            f"{best['false_wakes']} false wakes in {result['hours']:.2f} h of home background, "
            f"{best['times']:.1f}× the household goal" if best else "no held-out takes or background")
              + f" ({time.time() - started:.0f} s)", flush=True)


def cmd_export(args):
    from .export import export_dir, export_word, write_device_snippets

    household = _household(args)
    exported = []
    for word in _words(household, args) if (args.word or args.all) else []:
        for path in export_word(household, word, Path(args.model) if args.model else None,
                                cutoff=args.cutoff, window=args.window, author=args.author):
            print(path)
            exported.append(path)
    snippets = write_device_snippets(household, args.url)
    for path in snippets:
        print(path)
    if args.ha and exported:
        from .ha_sync import Client

        client = Client()
        for path in exported:  # no copying by hand: the device YAMLs find them at wake_words/<word>.json
            print(f"Home Assistant: {client.upload_wake_word(path)}", flush=True)
        # which YAML of the ESPHome dashboard each snippet goes into, and the snippet itself to copy
        files = {d["name"]: d["file"] for d in client.esphome_devices()}
        for path in snippets:
            target = files.get(path.stem)
            where = f"ESPHome → {target}" if target else "the device's ESPHome YAML"
            print(f"\n--- {path.stem}: paste below `packages:` in {where}, then Install ---\n{path.read_text()}", end="")
        print("\nThen in Home Assistant pick the wake word on the device's page.")
    else:
        print(f"Copy {export_dir(household) / 'wake_words'} to /config/esphome/wake_words/ (or your web server)"
              " and add each device's snippet to its ESPHome YAML.")


# --- parser -----------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wakeword", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-H", "--household", type=Path,
                        default=Path(os.environ.get("WAKEWORD_HOUSEHOLD", ".")),
                        help="household folder (default: $WAKEWORD_HOUSEHOLD or the current folder)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    def words_arg(p, nargs="*"):
        p.add_argument("word", nargs=nargs, help="word id(s)")
        if nargs == "*":
            p.add_argument("--all", action="store_true", help="every word of the household")

    p = add("init", cmd_init, "create household.yaml")
    p.add_argument("--speaker", action="append", default=[], metavar="ID[:GROUP]",
                   help="a person, group adult (default) or child; repeat for everyone")
    p.add_argument("--ui-language", default="en", help="recorder language (en, pl …)")

    p = add("add-speaker", cmd_add_speaker, "add a person")
    p.add_argument("id")
    p.add_argument("--group", default="adult", choices=["adult", "child"])
    p.add_argument("--word", action="append", default=[], help="also add them to this word")

    p = add("add-word", cmd_add_word, "add a wake word")
    p.add_argument("id", help="lowercase id, e.g. hey_tony")
    p.add_argument("wake_word", help="how it is written, e.g. 'Hey Tony'")
    p.add_argument("--spelling", action="append", default=[], required=True, metavar="LANG=TEXT[,TEXT]",
                   help="text for TTS in a language; phonetic spellings give the accent")
    p.add_argument("--speaker", action="append", help="who uses it (default: everyone)")
    p.add_argument("--language", action="append", help="trained language(s) for the manifest")
    p.add_argument("--sound-alike", action="append", help="similar phrase that must not wake")

    p = add("set-device", cmd_set_device, "assign up to two words to an ESPHome device")
    p.add_argument("device")
    p.add_argument("words", nargs="+")

    p = add("make-cert", cmd_make_cert, "create the recorder's HTTPS certificate")
    p.add_argument("--address", action="append", help="IP address to include (default: detected)")

    p = add("record", cmd_record, "start the web recorder")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8443)
    p.add_argument("--http", action="store_true", help="plain HTTP (microphone works on localhost only)")

    p = add("studio", cmd_studio, "wake word studio: the editor in the browser, login from WAKEWORD_UI_AUTH (Docker)")
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside the container")
    p.add_argument("--port", type=int, default=8765)

    p = add("import", cmd_import, "import audio files (m4a, mp3, wav …) as takes")
    words_arg(p, nargs=1)
    p.add_argument("--speaker", required=True)
    p.add_argument("files", nargs="+")

    add("check", cmd_check, "check recordings: person × word matrix and problems")

    p = add("split", cmd_split, "hold out takes per person for testing")
    words_arg(p)
    p.add_argument("--held-out", type=int, help="takes per person (default: targets.held_out)")
    p.add_argument("--seed", type=int, default=0)

    p = add("expand", cmd_expand, "multiply training takes with shifted voice and tempo")
    words_arg(p)
    p.add_argument("--per-take", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)

    p = add("preview", cmd_preview, "write augmented examples to listen to")
    words_arg(p)
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)

    def synthetic_args(p):
        p.add_argument("--positives", type=int, default=20000, help="English generator clips per word")
        p.add_argument("--per-voice", type=int, default=300, help="clips per text and Piper voice")
        p.add_argument("--negatives", type=int, default=4000, help="sound-alike clips")
        p.add_argument("--voice", action="append", metavar="LANG=VOICE", help="Piper voice to use")

    p = add("synthetic", cmd_synthetic, "write the synthetic speech script for the training machine")
    words_arg(p)
    synthetic_args(p)

    p = add("ha-pull", cmd_ha_pull, "bring new recordings (and household.yaml when missing) from Home Assistant")
    p.add_argument("--optional", action="store_true", help="go on without them when Home Assistant cannot be asked")
    add("ha-push", cmd_ha_push, "send household.yaml to Home Assistant")

    p = add("elevenlabs", cmd_elevenlabs, "generate takes of the word with the ElevenLabs voices chosen in the panel")
    words_arg(p)

    p = add("config", cmd_config, "write the microWakeWord training config")
    words_arg(p)
    p.add_argument("--steps", type=int, default=20000)

    p = add("prepare", cmd_prepare, "split + expand + synthetic + config in one go")
    words_arg(p)
    synthetic_args(p)
    p.add_argument("--held-out", type=int)
    p.add_argument("--per-take", type=int, default=6)
    p.add_argument("--steps", type=int, default=20000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--force", action="store_true", help="even when recordings are incomplete")

    p = add("evaluate", cmd_evaluate, "FRR per person and false wakes per hour of a trained model")
    words_arg(p, nargs=1)
    p.add_argument("--model", help="path to the .tflite (default: the trained one)")
    p.add_argument("--window", type=int, default=5)
    p.add_argument("--background", action="append", help="background WAV (default: data/background)")

    p = add("evaluate-models", cmd_evaluate_models,
            "household test of the kept models (held-out family takes, test part of the home background)")
    words_arg(p, nargs=1)
    p.add_argument("--window", type=int, default=5)
    p.add_argument("--missing", action="store_true", help="only models not measured on these takes and background yet")

    p = add("export", cmd_export, "manifest + ESPHome snippets per device")
    p.add_argument("--ha", action="store_true", help="send the models to Home Assistant's /config/esphome/wake_words/")
    words_arg(p)
    p.add_argument("--model", help="path to the .tflite (default: the trained one)")
    p.add_argument("--cutoff", type=float, default=0.97)
    p.add_argument("--window", type=int, default=5)
    p.add_argument("--author", default="")
    p.add_argument("--url", help="base URL where the models will be served (default: local wake_words/)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (HouseholdError, ValueError, FileNotFoundError, RuntimeError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

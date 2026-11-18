"""Synthetic speech jobs: a shell script that generates the word (and its sound-alikes) with TTS.

Nothing is generated here — the script runs later on the training machine (see ``train/train.sh``).

- English spellings use piper-sample-generator with the multi-speaker LibriTTS-R generator
  (~900 voices, randomised speaker mixing) — the main source of variety.
- Every other language uses ordinary Piper voices of that language reading the phonetic spellings
  from household.yaml (``dżarwis`` for “Jarvis”) — this is where the accent comes from — with
  varied speed and noise, each run is a different take.
- Sound-alikes are generated the same way and become negatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

from .household import Household

GENERATOR_MODEL = "en_US-libritts_r-medium.pt"
GENERATOR_URL = f"https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/{GENERATOR_MODEL}"
MAX_SPEAKERS = 900  # LibriTTS-R has 904; the last ones have few samples and cause artefacts
# Default Piper voices per language (https://huggingface.co/rhasspy/piper-voices). A household chooses
# its own in household.yaml `voices` (also "<owner>/<repo>/<voice>" from Hugging Face), the command
# line with --voice.
PIPER_VOICES: dict[str, tuple[str, ...]] = {
    "en": ("en_US-lessac-medium", "en_US-amy-medium", "en_GB-alan-medium", "en_GB-alba-medium"),
    "pl": ("pl_PL-gosia-medium", "pl_PL-darkman-medium", "pl_PL-mc_speech-medium"),
    "de": ("de_DE-thorsten-medium", "de_DE-eva_k-x_low", "de_DE-karlsson-low"),
    "es": ("es_ES-davefx-medium", "es_ES-sharvard-medium", "es_MX-claude-high"),
    "fr": ("fr_FR-siwis-medium", "fr_FR-upmc-medium", "fr_FR-tom-medium"),
    "it": ("it_IT-riccardo-x_low", "it_IT-paola-medium"),
    "nl": ("nl_NL-mls-medium", "nl_BE-nathalie-medium"),
    "cs": ("cs_CZ-jirka-medium",),
    "uk": ("uk_UA-lada-x_low", "uk_UA-ukrainian_tts-medium"),
}
LENGTH_SCALES = (0.8, 0.9, 1.0, 1.1, 1.25)
NOISE_SCALES = (0.5, 0.667, 0.9)

SYNTHETIC_DIR = "synthetic"
BUILD_DIR = "build"


@dataclass(frozen=True)
class Job:
    engine: str  # generator | piper
    language: str
    text: str
    voice: str
    count: int
    output: str  # relative to the household data folder
    truth: bool


def voice_name(voice: str) -> str:
    """"WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium" -> "pl_PL-meski_wg_glos-medium"."""
    return voice.rsplit("/", 1)[-1]


def voices_for(language: str, override: dict[str, tuple[str, ...]] | None = None) -> tuple[str, ...]:
    """The chosen voices of a language (an empty choice is allowed for English: the generator remains)."""
    override = override or {}
    voices = override[language] if language in override else PIPER_VOICES.get(language, ())
    if not voices and language != "en":
        raise ValueError(f"no Piper voices for '{language}' — choose them in the panel (Settings → voices) "
                         f"or pass --voice {language}=<voice>")
    return voices


def plan_jobs(household: Household, word: str, positives: int = 20000, per_voice: int = 300,
              negatives: int = 4000, voices: dict[str, tuple[str, ...]] | None = None) -> list[Job]:
    """Jobs for the word's spellings (positives) and sound-alikes (negatives).

    `positives` is spread over the English generator; other languages get `per_voice` takes per
    text and voice. Sound-alikes get `negatives` in total, split the same way."""
    entry = household.words[word]
    voices = {**household.voices, **(voices or {})}
    jobs: list[Job] = []

    def add(texts: tuple[str, ...], language: str, total: int, folder: str, truth: bool) -> None:
        if language == "en":
            each = max(1, total // len(texts))
            for i, text in enumerate(texts):
                jobs.append(Job("generator", "en", text, GENERATOR_MODEL, each,
                                f"{SYNTHETIC_DIR}/{word}/{folder}/en_generator_{i:02d}", truth))
        voice_list = voices_for(language, voices)
        each = per_voice if truth else max(1, per_voice // 3)
        for i, text in enumerate(texts):
            for voice in voice_list:
                jobs.append(Job("piper", language, text, voice, each,
                                f"{SYNTHETIC_DIR}/{word}/{folder}/{voice_name(voice)}_{i:02d}", truth))

    for language, texts in entry.spellings.items():
        add(texts, language, positives, "positive", True)
    if entry.sound_alikes:
        # Sound-alikes are spoken in the word's first trained language and in English.
        languages = dict.fromkeys([entry.trained_languages[0], "en"])
        for language in languages:
            add(entry.sound_alikes, language, negatives // len(languages), "negative", False)
    return jobs


def _quote(value: str) -> str:
    return shlex.quote(value)


def render_script(household: Household, word: str, jobs: list[Job]) -> str:
    """A bash script that runs the jobs on the training machine (paths relative to the household).

    Every group logs what really happens: "[3/27] <voice> '<text>': making 300 of 300 clips",
    progress, time, or "skip, already complete". A finished group gets a ``.complete`` marker, so an
    interrupted group is finished (Piper) or redone (generator) instead of being taken as ready.
    """
    lines = [
        "#!/usr/bin/env bash",
        f"# Synthetic speech for the wake word '{word}' — generated by `wakeword synthetic`.",
        "# Run from the household folder on the training machine (train/train.sh does it).",
        "set -euo pipefail",
        ': "${PSG_MODEL:?set PSG_MODEL to the path of ' + GENERATOR_MODEL + '}"',
        ': "${PIPER_VOICES_DIR:?set PIPER_VOICES_DIR to a folder for Piper voices}"',
        ': "${SYNTH_PIPER:?set SYNTH_PIPER to train/synth_piper.py (train/train.sh does it)}"',
        'PYTHON="${PYTHON:-python3}"',
        f"LENGTH_SCALES=({' '.join(str(s) for s in LENGTH_SCALES)})",
        f"NOISE_SCALES=({' '.join(str(s) for s in NOISE_SCALES)})",
        "",
        "# generator <label> <text> <count> <output dir>: multi-speaker English generator",
        "generator() {",
        '  local label="$1" text="$2" count="$3" out="$4"',
        "  # .complete holds the group's text (empty: from before the text was kept)",
        '  if [ -f "$out/.complete" ] && { [ ! -s "$out/.complete" ] || [ "$(cat "$out/.complete")" = "$text" ]; }; then',
        '    echo "$label skip, already complete: en generator \'$text\'"; return',
        "  fi",
        '  if [ -f "$out/.complete" ]; then echo "$label the text changed, making the group again"; rm -rf "$out"; fi',
        "  # (no such folder yet is fine: the count is 0, not an error that stops the script)",
        '  local have; have=$( (find "$out" -name "*.wav" 2>/dev/null || true) | wc -l); have=$((have))',
        '  if [ "$have" -ge "$count" ]; then',
        '    echo "$label en generator \'$text\': all $count clips already there"; printf %s "$text" > "$out/.complete"; return',
        "  fi",
        "  # the generator cannot resume - an interrupted group starts again",
        '  rm -rf "$out"; mkdir -p "$out"',
        f'  echo "$label en generator \'$text\': making $count clips with up to {MAX_SPEAKERS} voices → $out"',
        "  local started=$SECONDS",
        '  "$PYTHON" -m piper_sample_generator "$text" --model "$PSG_MODEL" --max-samples "$count" \\',
        f'    --max-speakers {MAX_SPEAKERS} --batch-size "${{BATCH_SIZE:-100}}" --output-dir "$out"',
        '  have=$(find "$out" -name "*.wav" | wc -l); echo "$label   $((have))/$count clips, $((SECONDS - started)) s"',
        '  printf %s "$text" > "$out/.complete"',
        "}",
        "",
        "# piper_voice <label> <voice> <text> <count> <output dir>: one Piper voice, varied speed and noise",
        "# (train/synth_piper.py loads the voice once for the whole group)",
        "piper_voice() {",
        '  "$PYTHON" "$SYNTH_PIPER" --label "$1" --voice "$2" --text "$3" --count "$4" --out "$5" \\',
        '    --voices-dir "$PIPER_VOICES_DIR" --length-scales "${LENGTH_SCALES[@]}" --noise-scales "${NOISE_SCALES[@]}"',
        "}",
        "",
    ]
    # groups of voices or texts no longer chosen would still go into training (features take the
    # whole positive/negative folder) - they are moved aside, not deleted
    keep = sorted({job.output.rsplit("/", 1)[-1] for job in jobs})
    lines += [
        f"KEEP=({' '.join(_quote(name) for name in keep)})",
        'STALE="data/backup/synthetic-$(date +%Y%m%d-%H%M%S)"',
        f"for group in data/{SYNTHETIC_DIR}/{word}/positive/* data/{SYNTHETIC_DIR}/{word}/negative/*; do",
        '  [ -d "$group" ] || continue',
        '  case " ${KEEP[*]} " in *" $(basename "$group") "*) continue ;; esac',
        '  mkdir -p "$STALE/$(dirname "${group#data/}")"',
        '  mv "$group" "$STALE/${group#data/}"',
        '  echo "no longer chosen, moved to $STALE: ${group#data/}"',
        "done",
        "",
    ]
    total = len(jobs)
    for index, job in enumerate(jobs, 1):
        out = _quote(f"data/{job.output}")
        label = _quote(f"[{index}/{total}]")
        if job.engine == "generator":
            lines.append(f"generator {label} {_quote(job.text)} {job.count} {out}")
        else:
            lines.append(f"piper_voice {label} {_quote(job.voice)} {_quote(job.text)} {job.count} {out}")
    lines.append("")
    lines.append(f'echo "synthetic speech for {word} is ready: {total} groups, {sum(j.count for j in jobs)} clips"')
    return "\n".join(lines) + "\n"


def build_dir(household: Household, word: str) -> Path:
    return household.data_dir / BUILD_DIR / word


def write_script(household: Household, word: str, jobs: list[Job]) -> Path:
    path = build_dir(household, word) / "synthetic.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_script(household, word, jobs), encoding="utf-8")
    path.chmod(0o755)
    return path


def summary(jobs: list[Job]) -> str:
    """How many clips per language and kind the script will make."""
    totals: dict[tuple[str, str, bool], int] = {}
    for job in jobs:
        key = (job.language, job.engine, job.truth)
        totals[key] = totals.get(key, 0) + job.count
    lines = []
    for (language, engine, truth), count in sorted(totals.items()):
        kind = "positive" if truth else "negative"
        lines.append(f"{language:>3} {engine:<9} {kind:<8} {count:>7}")
    return "\n".join(lines)

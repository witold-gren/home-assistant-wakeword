"""Household recordings: naming, import, quality check (person × word matrix) and the test split.

Takes are stored as ``data/real/<word>/<speaker>/<speaker>_<NNN>_<variant>.wav`` (16 kHz mono),
where ``variant`` is a delivery variant from :mod:`wakeword.languages` or ``imported``.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
import random
import re
import tempfile

import numpy as np

from .audio import (
    MIN_SNR_DB,
    SAMPLE_RATE,
    AudioError,
    AudioStats,
    analyze,
    convert_to_wav,
    normalize_peak,
    read_wav,
    resample,
    trim_silence,
    write_wav,
)
from .household import Household
from .languages import TAKE_ORDER, take_variant

TAKE_PATTERN = re.compile(r"^(?P<speaker>[a-z0-9_]+?)_(?P<index>\d{3})_(?P<variant>[a-z_]+)\.wav$")
IMPORTED = "imported"

# Quality limits of a single take.
MIN_SPEECH = 0.25  # s — shorter is a click or a cut-off word
MAX_SPEECH = 3.0  # s — longer is probably a sentence, not the wake word
MIN_RMS_DB = -42.0  # quieter speech is mostly noise after augmentation
MAX_CLIPPED = 0.001  # share of clipped samples

SPLITS_DIR = "splits"


@dataclass(frozen=True)
class Take:
    path: Path
    speaker: str
    index: int
    variant: str


def parse_take(path: Path) -> Take | None:
    """Take info from a file name, None for files that do not follow the naming."""
    match = TAKE_PATTERN.match(path.name)
    if not match:
        return None
    return Take(path, match["speaker"], int(match["index"]), match["variant"])


def list_takes(household: Household, word: str, speaker: str) -> list[Take]:
    """Takes of `word` by `speaker`, ordered by index."""
    folder = household.real_dir(word, speaker)
    if not folder.is_dir():
        return []
    takes = [t for p in folder.glob("*.wav") if (t := parse_take(p)) and t.speaker == speaker]
    return sorted(takes, key=lambda t: t.index)


def next_take(household: Household, word: str, speaker: str, variant: str | None = None) -> Take:
    """Where the next take goes; the variant follows TAKE_ORDER unless given."""
    takes = list_takes(household, word, speaker)
    index = takes[-1].index + 1 if takes else 0
    variant = variant or take_variant(len(takes))
    path = household.real_dir(word, speaker) / f"{speaker}_{index:03d}_{variant}.wav"
    return Take(path, speaker, index, variant)


def quality_issues(stats: AudioStats) -> list[str]:
    """Problem ids of a take (empty when it is fine): no_speech, too_short, too_long, too_quiet,
    clipped, too_noisy, wrong_rate."""
    if stats.is_silent:
        return ["no_speech"]
    issues = []
    if stats.rate != SAMPLE_RATE:
        issues.append("wrong_rate")
    if stats.speech < MIN_SPEECH:
        issues.append("too_short")
    if stats.speech > MAX_SPEECH:
        issues.append("too_long")
    if stats.rms_db < MIN_RMS_DB:
        issues.append("too_quiet")
    if stats.clipped > MAX_CLIPPED:
        issues.append("clipped")
    if stats.snr_db < MIN_SNR_DB:
        # the word's length and loudness mean nothing when it cannot be told from the noise
        issues = [i for i in issues if i not in ("too_short", "too_long", "too_quiet")] + ["too_noisy"]
    return issues


def prepare_take(samples, rate: int):
    """Clean a raw recording for storage: 16 kHz, silence trimmed (with padding), peak at -1 dBFS."""
    samples = resample(samples, rate, SAMPLE_RATE)
    trimmed = trim_silence(samples, SAMPLE_RATE, pad_ms=250)
    if len(trimmed):
        samples = trimmed
    return normalize_peak(samples, -1.0)


def save_take(household: Household, word: str, speaker: str, samples, rate: int,
              variant: str | None = None) -> tuple[Take, list[str]]:
    """Check and store one recording; returns the take and its quality issues.

    Recordings without speech are not stored (the take path is returned but no file exists)."""
    stats = analyze(samples, rate)
    # The take is converted to 16 kHz below, so the input rate is not a problem.
    issues = [i for i in quality_issues(stats) if i != "wrong_rate"]
    take = next_take(household, word, speaker, variant)
    if "no_speech" in issues:
        return take, issues
    # Clipping is judged on the raw audio, before normalising hides it.
    write_wav(take.path, prepare_take(samples, rate))
    return take, issues


def import_files(household: Household, word: str, speaker: str, files: list[Path]) -> list[tuple[Path, Take | None, list[str]]]:
    """Import recordings in any format (iPhone Voice Memos .m4a, .mp3, .wav …) as takes."""
    if word not in household.words:
        raise ValueError(f"unknown word '{word}'")
    if speaker not in household.words[word].speakers:
        raise ValueError(f"'{speaker}' does not use the word '{word}' (see household.yaml)")
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, src in enumerate(files):
            src = Path(src)
            try:
                try:
                    samples, rate = read_wav(src)
                except AudioError:
                    samples, rate = read_wav(convert_to_wav(src, Path(tmp) / f"{i}.wav"))
            except AudioError as err:
                results.append((src, None, [f"unreadable: {err}"]))
                continue
            take, issues = save_take(household, word, speaker, samples, rate, IMPORTED)
            results.append((src, take if take.path.exists() else None, issues))
    return results


@dataclass
class TakeReport:
    take: Take
    stats: AudioStats
    issues: list[str]

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass
class CellReport:
    """One person × word cell of the check matrix."""

    word: str
    speaker: str
    target: int
    takes: list[TakeReport] = field(default_factory=list)

    @property
    def good(self) -> int:
        return sum(t.ok for t in self.takes)

    @property
    def missing(self) -> int:
        return max(0, self.target - self.good)

    @property
    def missing_variants(self) -> list[str]:
        """Delivery variants that have no good take yet (recorded ones only, imports don't count)."""
        have = {t.take.variant for t in self.takes if t.ok}
        wanted = TAKE_ORDER[: min(self.target, len(TAKE_ORDER))]
        return [v for v in wanted if v not in have]

    @property
    def complete(self) -> bool:
        return self.missing == 0


@dataclass
class CheckReport:
    household: Household
    cells: dict[tuple[str, str], CellReport]
    stray: list[Path]  # files in data/real that do not follow the naming

    def cell(self, word: str, speaker: str) -> CellReport:
        return self.cells[(word, speaker)]

    @property
    def complete(self) -> bool:
        return all(c.complete for c in self.cells.values()) and not self.stray

    def problems(self) -> list[TakeReport]:
        return [t for c in self.cells.values() for t in c.takes if not t.ok]


def check_household(household: Household) -> CheckReport:
    """Check every take of every person for every word they use."""
    cells: dict[tuple[str, str], CellReport] = {}
    stray: list[Path] = []
    for word in household.words.values():
        for sid in word.speakers:
            target = household.targets.for_group(household.speakers[sid].group)
            cell = CellReport(word.id, sid, target)
            for take in list_takes(household, word.id, sid):
                try:
                    samples, rate = read_wav(take.path)
                    stats = analyze(samples, rate)
                    issues = quality_issues(stats)
                except AudioError:
                    stats = analyze(np.zeros(0, dtype=np.float32), SAMPLE_RATE)
                    issues = ["unreadable"]
                cell.takes.append(TakeReport(take, stats, issues))
            cells[(word.id, sid)] = cell
            folder = household.real_dir(word.id, sid)
            if folder.is_dir():
                stray += [p for p in sorted(folder.iterdir()) if p.is_file() and not _is_take(p, sid)]
    return CheckReport(household, cells, stray)


def _is_take(path: Path, speaker: str) -> bool:
    take = parse_take(path)
    return take is not None and take.speaker == speaker


def format_matrix(report: CheckReport) -> str:
    """Person × word table: good/target, ✓ when complete, — when the person doesn't use the word."""
    household = report.household
    words = list(household.words)
    width = max(len(s) for s in household.speakers) + 2
    col = max(9, *(len(w) + 2 for w in words))
    lines = [" " * width + "".join(w.ljust(col) for w in words)]
    for sid in household.speakers:
        row = sid.ljust(width)
        for wid in words:
            cell = report.cells.get((wid, sid))
            if cell is None:
                text = "—"
            else:
                text = f"{cell.good}/{cell.target}" + (" ✓" if cell.complete else "")
            row += text.ljust(col)
        lines.append(row.rstrip())
    return "\n".join(lines)


def format_report(report: CheckReport) -> str:
    lines = [format_matrix(report), ""]
    for cell in report.cells.values():
        if cell.missing:
            wanted = cell.missing_variants[: min(cell.missing, 4)]
            variants = ", ".join(wanted) + (" …" if len(cell.missing_variants) > len(wanted) else "")
            lines.append(f"{cell.speaker} / {cell.word}: {cell.missing} more take(s)"
                         + (f" — e.g. {variants}" if wanted else ""))
    for take in report.problems():
        lines.append(f"problem: {take.take.path.name} ({take.take.path.parent.parent.name}): "
                     f"{', '.join(take.issues)}")
    for path in report.stray:
        lines.append(f"not a take (rename or remove): {path}")
    if report.complete:
        lines.append("All recordings are complete.")
    return "\n".join(lines).rstrip()


# --- test split -----------------------------------------------------------------------------

@dataclass(frozen=True)
class SplitRow:
    path: Path
    word: str
    speaker: str
    group: str
    split: str  # train | test


def split_word(household: Household, word: str, held_out: int | None = None, seed: int = 0) -> list[SplitRow]:
    """Hold out `held_out` good takes per person for testing; the rest is for training.

    The choice is random but stable (seeded by word and person), and tries to hold out different
    delivery variants, so the test set is as varied as the training set."""
    held_out = household.targets.held_out if held_out is None else held_out
    report = check_household(household)
    rows: list[SplitRow] = []
    for sid in household.words[word].speakers:
        group = household.speakers[sid].group
        good = [t.take for t in report.cell(word, sid).takes if t.ok]
        rng = random.Random(f"{seed}:{word}:{sid}")
        shuffled = good[:]
        rng.shuffle(shuffled)
        test: list[Take] = []
        seen: set[str] = set()
        for take in shuffled:  # one per variant first
            if len(test) < held_out and take.variant not in seen:
                test.append(take)
                seen.add(take.variant)
        for take in shuffled:
            if len(test) < held_out and take not in test:
                test.append(take)
        # Never hold out everything: keep at least one take for training.
        if len(test) >= len(good) and good:
            test = test[: len(good) - 1]
        test_paths = {t.path for t in test}
        for take in good:
            rows.append(SplitRow(take.path, word, sid, group, "test" if take.path in test_paths else "train"))
    return rows


def split_path(household: Household, word: str) -> Path:
    return household.data_dir / SPLITS_DIR / f"{word}.csv"


def write_split(household: Household, rows: list[SplitRow], word: str) -> Path:
    path = split_path(household, word)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "word", "speaker", "group", "split"])
        for row in rows:
            writer.writerow([row.path.relative_to(household.root).as_posix(), row.word, row.speaker,
                             row.group, row.split])
    return path


def read_split(household: Household, word: str) -> list[SplitRow]:
    path = split_path(household, word)
    if not path.exists():
        raise FileNotFoundError(f"{path}: run `wakeword split` first")
    with path.open(encoding="utf-8") as handle:
        return [SplitRow(household.root / r["path"], r["word"], r["speaker"], r["group"], r["split"])
                for r in csv.DictReader(handle)]


# --- the home's background recordings: most for training, some only for the test ------------------

BACKGROUND_FOLDER = "background"  # data/background (augment.BACKGROUND_DIR)
BACKGROUND_TEST_EVERY = 4  # about every 4th recording (chosen by its name) is never trained on


def split_background(household: Household) -> tuple[list[Path], list[Path]]:
    """(train, test) recordings of data/background.

    The test ones measure false wakes at home honestly - a model never heard them. Chosen by a hash
    of the file name, so a new recording never moves the old ones between the two; a single recording
    is for training, with two or more at least one is for the test.
    """
    folder = household.data_dir / BACKGROUND_FOLDER
    files = sorted(folder.glob("*.wav")) if folder.is_dir() else []
    if len(files) < 2:
        return files, []
    test = [f for f in files if int(hashlib.md5(f.name.encode()).hexdigest(), 16) % BACKGROUND_TEST_EVERY == 0]
    if not test and len(files) >= 2:
        test = [files[-1]]
    return [f for f in files if f not in test], test

"""False wakes of the satellites: the wake log of Home Assistant, sorted out and counted.

Wake Word Recorder writes every wake of a satellite to ``/config/assist/wake_word_log.csv`` and hands
it out through ``GET /api/wake_word_recorder/wake_log`` (ha_sync.Client.wake_log). Each wake is put in
one kind:

- ``command``       - speech to text heard a real command: a true wake;
- ``no_speech``     - the satellite woke and nobody said anything: the surest false wake;
- ``hallucination`` - Whisper's usual text for silence or noise ("Dziękuję za oglądanie", "Thanks for
                      watching"): a false wake;
- ``short``         - one word that did nothing ("Nie!", "Cześć!"): most likely a false wake;
- ``cancelled``     - the run ended before speech to text: unclear, counted apart;
- ``duplicate``     - another satellite took the same word first: someone said it, not false;
- ``error``         - the run failed;
- ``recorder``      - a take of Wake Word Recorder: no wake of the household, left out.

The goal of a good model is at most one false wake a day per satellite (chapter 12). The counts are
per day of the period, per device, per wake word and - for a word the studio trained - before and
after its model went to Home Assistant (the time of the exported file, or a day given by hand).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

FALSE_KINDS = ("no_speech", "hallucination", "short")
KINDS = ("command", "no_speech", "hallucination", "short", "cancelled", "duplicate", "error")
GOAL_PER_DAY = 1.0  # at most one false wake a day (chapter 12)
RECENT = 60  # the newest suspect wakes listed

# Whisper's usual text for silence or noise (subtitles of videos it learnt on), lower case, in parts
HALLUCINATIONS = (
    "dziękuję za oglądanie", "dzięki za oglądanie", "dziękuje za oglądanie", "w kolejnych odcinkach",
    "do zobaczenia w następnym", "napisy stworzone przez", "amara.org", "subskrybuj", "zasubskrybuj",
    "thanks for watching", "thank you for watching", "subtitles by", "please subscribe", "like and subscribe",
)
# a whole text that is only this is a hallucination too (a short "Dziękuję." on silence)
HALLUCINATION_WHOLE = {"dziękuję", "dziękuje", "dzięki", "koniec", "thank you", "thanks", "you", "bye", "the end"}
DONE = {"action_done", "query_answer"}
_WORD = re.compile(r"\w+", re.UNICODE)


def _plain(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def kind(row: dict) -> str:
    """The kind of one row of the wake log (see the module)."""
    if row.get("recorder"):
        return "recorder"
    outcome = row.get("outcome") or ""
    if outcome == "duplicate":
        return "duplicate"
    if outcome == "no_speech":
        return "no_speech"
    if outcome == "cancelled":
        return "cancelled"
    if outcome != "command":
        return "error"
    text = (row.get("text") or "").lower()
    plain = _plain(text)
    if not plain:
        return "no_speech"
    if plain in HALLUCINATION_WHOLE or any(part in text for part in HALLUCINATIONS):
        return "hallucination"
    if len(plain.split()) == 1 and (row.get("response") or "") not in DONE:
        return "short"
    return "command"


def same_word(a: str, b: str) -> bool:
    """One wake word written two ways ("Hej Jarvis" / "hej jarvis"); "Hey Jarvis" is another model."""
    return _plain(a) == _plain(b)


def _stamp(text: str) -> datetime | None:
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _days(start: datetime, end: datetime) -> float:
    """The length of a period in days, at least an hour (a model sent today has a short "after")."""
    return max((end - start).total_seconds() / 86400, 1 / 24)


def _rate(false: int, days: float) -> float:
    return round(false / days, 2)


def analyse(rows: list[dict], since: str, now: datetime, words: list[dict] | None = None) -> dict:
    """The false wakes of `rows` (the wake log from the day `since`, YYYY-MM-DD) up to `now`.

    `words`: the studio's words [{"id", "wake_word", "deployed": "YYYY-MM-DD HH:MM:SS" | None}] - their
    wakes are compared before and after `deployed`.
    """
    start = datetime.strptime(since, "%Y-%m-%d")
    kinds: Counter = Counter()
    devices: dict = defaultdict(lambda: {"wakes": 0, "false": 0, "area": ""})
    by_word: dict = defaultdict(lambda: {"wakes": 0, "false": 0, "rows": []})
    by_day: dict = defaultdict(lambda: {"wakes": 0, "false": 0})
    recent = []
    first = None
    logged_from = None  # the first row of the period, the recorder's too: the log may be younger than the period
    for row in rows:
        when = _stamp(row.get("timestamp") or "")
        if when is None or when < start:
            continue
        logged_from = logged_from or when
        what = kind(row)
        if what == "recorder":
            kinds["recorder"] += 1
            continue
        first = first or when
        false = what in FALSE_KINDS
        kinds[what] += 1
        device = devices[row.get("device") or "?"]
        device["area"] = row.get("area") or device["area"]
        word = by_word[row.get("wake_word") or "?"]
        day = by_day[when.strftime("%Y-%m-%d")]
        for bucket in (device, word, day):
            bucket["wakes"] += 1
            bucket["false"] += false
        word["rows"].append((when, false))
        if false or what == "cancelled":
            recent.append({"timestamp": row["timestamp"], "device": row.get("device") or "", "area": row.get("area") or "",
                           "wake_word": row.get("wake_word") or "", "kind": what, "text": row.get("text") or "",
                           "seconds": row.get("seconds") or 0})
    # the days counted: from the period's first day, or from the day the log began when that is later
    begin = max(start, logged_from.replace(hour=0, minute=0, second=0)) if logged_from else start
    period = _days(begin, now)
    false_total = sum(kinds[name] for name in FALSE_KINDS)
    word_list = []
    for name, data in sorted(by_word.items(), key=lambda item: -item[1]["false"]):
        own = next((w for w in words or [] if same_word(w["wake_word"], name)), None)
        entry = {"wake_word": name, "wakes": data["wakes"], "false": data["false"], "per_day": _rate(data["false"], period),
                 "word": own["id"] if own else None, "deployed": own.get("deployed") if own else None,
                 "before": None, "after": None}
        deployed = _stamp(entry["deployed"] or "")
        if deployed and begin < deployed < now:
            before = [false for when, false in data["rows"] if when < deployed]
            after = [false for when, false in data["rows"] if when >= deployed]
            entry["before"] = {"days": round(_days(begin, deployed), 1), "wakes": len(before), "false": sum(before),
                               "per_day": _rate(sum(before), _days(begin, deployed))}
            entry["after"] = {"days": round(_days(deployed, now), 1), "wakes": len(after), "false": sum(after),
                              "per_day": _rate(sum(after), _days(deployed, now))}
        word_list.append(entry)
    day_list = []
    for offset in range(int(period) + 1):
        day = (begin + timedelta(days=offset)).strftime("%Y-%m-%d")
        if day <= now.strftime("%Y-%m-%d"):
            day_list.append({"day": day, **by_day.get(day, {"wakes": 0, "false": 0})})
    return {
        "since": since,
        "begin": begin.strftime("%Y-%m-%d"),
        "days": round(period, 1),
        "first": first.strftime("%Y-%m-%d %H:%M:%S") if first else None,
        "wakes": sum(kinds[name] for name in KINDS),
        "false": false_total,
        "per_day": _rate(false_total, period),
        "goal_per_day": GOAL_PER_DAY,
        "kinds": {name: kinds[name] for name in (*KINDS, "recorder")},
        "devices": sorted(({"device": name, "area": data["area"], "wakes": data["wakes"], "false": data["false"],
                            "per_day": _rate(data["false"], period)} for name, data in devices.items()),
                          key=lambda item: (-item["false"], item["device"])),
        "words": word_list,
        "by_day": day_list,
        "recent": recent[-RECENT:][::-1],
    }

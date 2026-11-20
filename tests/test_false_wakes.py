"""False wakes of the satellites: the kinds of the wake log, the counts and before/after a model."""

import json
import os
import time
from datetime import datetime

import pytest

from wakeword import ha_sync
from wakeword.false_wakes import analyse, kind, same_word
from wakeword.studio.server import Studio
from wakeword.trainer import server as trainer_module


def row(stamp, outcome="command", text="", device="Salon Voice", word="Hej Jarvis", response="", recorder=False):
    return {"timestamp": stamp, "area": device.split()[0], "device": device, "wake_word": word, "pipeline": "",
            "outcome": outcome, "text": text, "response": response, "seconds": 3.0, "recorder": recorder}


@pytest.mark.parametrize(("data", "expected"), [
    (row("2026-11-01 10:00:00", "command", "Która godzina?", response="action_done"), "command"),
    (row("2026-11-01 10:00:00", "no_speech"), "no_speech"),
    (row("2026-11-01 10:00:00", "command", "  "), "no_speech"),
    (row("2026-11-01 10:00:00", "command", "Dziękuje za oglądanie!"), "hallucination"),
    (row("2026-11-01 10:00:00", "command", "Wielkie dzięki i do zobaczenia w kolejnych odcinkach."), "hallucination"),
    (row("2026-11-01 10:00:00", "command", "Thanks for watching!"), "hallucination"),
    (row("2026-11-01 10:00:00", "command", "Koniec."), "hallucination"),
    (row("2026-11-01 10:00:00", "command", "Nie!", response="no_intent_match"), "short"),
    (row("2026-11-01 10:00:00", "command", "Stop", response="action_done"), "command"),  # one word that did something
    (row("2026-11-01 10:00:00", "cancelled"), "cancelled"),
    (row("2026-11-01 10:00:00", "duplicate"), "duplicate"),
    (row("2026-11-01 10:00:00", "ConnectionNotEstablishedAPIError"), "error"),
    (row("2026-11-01 10:00:00", "command", "wake word take", recorder=True), "recorder"),
])
def test_kind(data, expected):
    assert kind(data) == expected


def test_same_word_ignores_case_and_punctuation_but_not_another_model():
    assert same_word("Hej Jarvis", "hej  jarvis!")
    assert not same_word("Hej Jarvis", "Hey Jarvis")


def test_counts_per_device_word_and_day_without_the_recorder():
    rows = [
        row("2026-11-01 02:00:00", "no_speech", device="Pokój Voice"),
        row("2026-11-01 08:00:00", "command", "Włącz światło", response="action_done"),
        row("2026-11-02 03:00:00", "command", "Dziękuję za oglądanie", device="Pokój Voice"),
        row("2026-11-02 09:00:00", "duplicate"),
        row("2026-11-02 10:00:00", "cancelled", device="Pokój Voice"),
        row("2026-11-02 11:00:00", "command", "wake word take", recorder=True),
        row("2026-10-30 11:00:00", "no_speech"),  # before the period
    ]
    result = analyse(rows, "2026-11-01", datetime(2026, 11, 3, 0, 0))
    assert result["days"] == 2.0 and result["wakes"] == 5 and result["false"] == 2 and result["per_day"] == 1.0
    assert result["kinds"]["recorder"] == 1 and result["kinds"]["duplicate"] == 1 and result["kinds"]["cancelled"] == 1
    assert result["devices"][0] == {"device": "Pokój Voice", "area": "Pokój", "wakes": 3, "false": 2, "per_day": 1.0}
    assert [d["day"] for d in result["by_day"]] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert result["by_day"][1] == {"day": "2026-11-02", "wakes": 3, "false": 1}
    assert [r["kind"] for r in result["recent"]] == ["cancelled", "hallucination", "no_speech"]  # newest first
    assert result["first"] == "2026-11-01 02:00:00"


def test_before_and_after_the_model_of_a_word_trained_here():
    rows = [row(f"2026-11-{day:02d} 02:00:00", "no_speech") for day in (1, 2, 3, 4)]
    rows += [row("2026-11-08 02:00:00", "no_speech"), row("2026-11-09 12:00:00", "command", "Która godzina?", response="action_done")]
    rows += [row("2026-11-05 02:00:00", "no_speech", word="Okay Nabu")]
    words = [{"id": "hej_jarvis", "wake_word": "Hej Jarvis", "deployed": "2026-11-05 00:00:00"}]
    result = analyse(rows, "2026-11-01", datetime(2026, 11, 11, 0, 0), words)
    jarvis = next(w for w in result["words"] if w["wake_word"] == "Hej Jarvis")
    assert jarvis["word"] == "hej_jarvis"
    assert jarvis["before"] == {"days": 4.0, "wakes": 4, "false": 4, "per_day": 1.0}
    assert jarvis["after"] == {"days": 6.0, "wakes": 2, "false": 1, "per_day": 0.17}
    nabu = next(w for w in result["words"] if w["wake_word"] == "Okay Nabu")
    assert nabu["word"] is None and nabu["before"] is None  # not trained here: no comparison


def test_a_log_younger_than_the_period_counts_from_its_first_day():
    rows = [row("2026-11-04 08:00:00", "command", "wake word take", recorder=True),
            row("2026-11-05 02:00:00", "no_speech"), row("2026-11-06 02:00:00", "no_speech")]
    result = analyse(rows, "2026-10-21", datetime(2026, 11, 7, 0, 0))
    assert result["begin"] == "2026-11-04" and result["days"] == 3.0 and result["per_day"] == 0.67
    assert result["by_day"][0]["day"] == "2026-11-04"


def test_a_model_sent_outside_the_period_has_no_comparison():
    words = [{"id": "hej_jarvis", "wake_word": "Hej Jarvis", "deployed": "2026-10-01 00:00:00"}]
    result = analyse([row("2026-11-02 02:00:00", "no_speech")], "2026-11-01", datetime(2026, 11, 3), words)
    assert result["words"][0]["before"] is None


@pytest.fixture
def studio(tmp_path, household_dir, monkeypatch):
    monkeypatch.setattr(trainer_module, "POLL_SECONDS", 0)
    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")  # no connection
    for name in ("WAKEWORD_HA_URL", "WAKEWORD_HA_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return Studio(household_dir, repo=tmp_path)


def test_the_studio_call_compares_a_word_from_its_exported_model(studio, household_dir):
    today = datetime.now()
    asked = []

    def source(since):
        asked.append(since)
        earlier = datetime.fromtimestamp(time.time() - 5 * 86400)  # the log began before the model
        return {"rows": [row(earlier.strftime("%Y-%m-%d 12:00:00"), "command", "Która godzina?", word="Hey Tony",
                             response="action_done"),
                         row(today.strftime("%Y-%m-%d 01:00:00"), "no_speech", word="Hey Tony")], "total": 2}

    studio.wake_log_source = source
    exported = household_dir / "data" / "export" / "wake_words" / "hey_tony.tflite"  # where export puts it
    exported.parent.mkdir(parents=True, exist_ok=True)
    exported.write_bytes(b"TFL3")
    two_days_ago = time.time() - 2 * 86400
    os.utime(exported, (two_days_ago, two_days_ago))
    result = studio.call({"type": "false_wakes", "since": "2026-11-01"})
    assert asked == ["2026-11-01"] and result["total_rows"] == 2
    tony = result["words"][0]
    assert tony["word"] == "hey_tony" and tony["deployed"][:10] == datetime.fromtimestamp(two_days_ago).strftime("%Y-%m-%d")
    assert tony["after"]["false"] == 1 and tony["before"]["false"] == 0
    # a day set by hand wins over the file
    result = studio.call({"type": "false_wakes", "since": "2026-11-01", "deployed": {"hey_tony": "2026-11-02"}})
    assert result["words"][0]["deployed"] == "2026-11-02 00:00:00"
    with pytest.raises(ValueError):
        studio.call({"type": "false_wakes", "since": "yesterday"})
    with pytest.raises(ValueError):
        studio.call({"type": "false_wakes", "since": "2026-11-01", "deployed": {"hey_tony": "soon"}})


def test_without_home_assistant_the_view_says_so(studio):
    with pytest.raises(ha_sync.HaError, match="no Home Assistant connection"):
        studio.call({"type": "false_wakes"})


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self.body


def test_the_client_asks_wake_word_recorder(monkeypatch):
    client = ha_sync.Client(ha_sync.Connection("http://ha.invalid:8123", "token"))
    opened = []

    def fake_open(path, query=None, **kwargs):
        opened.append((path, query))
        return _Response(json.dumps({"rows": [], "total": 0}).encode())

    monkeypatch.setattr(client, "_open", fake_open)
    monkeypatch.setattr(json, "load", lambda response: json.loads(response.read()))
    assert client.wake_log("2026-11-01") == {"rows": [], "total": 0}
    assert opened == [("/wake_log", {"since": "2026-11-01"})]

    def too_old(path, query=None, **kwargs):
        raise ha_sync.HaError("Home Assistant answered 404: Not Found")

    monkeypatch.setattr(client, "_open", too_old)
    with pytest.raises(ha_sync.HaError, match="0.3.0"):
        client.wake_log()

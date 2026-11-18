"""Recordings from Home Assistant through the Wake Word Recorder API, with a pretend Home Assistant."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from wakeword import ha_sync

TOKEN = "a" * 40
HOUSEHOLD = "speakers:\n  - id: tomek\n    group: adult\nwords: {}\n"


class FakeHa:
    """data/real, data/background and household.yaml of a Home Assistant, served like the integration."""

    def __init__(self, root: Path):
        self.root = root
        self.put = None
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=b"", kind="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.end_headers()
                self.wfile.write(body)

            def _authorised(self):
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._send(401, b"401: Unauthorized", "text/plain")
                    return False
                return True

            def do_GET(self):
                url = urlparse(self.path)
                owner.requests.append(url.path)
                if not self._authorised():
                    return
                if url.path == "/api/wake_word_recorder/files":
                    files = [{"path": p.relative_to(owner.root).as_posix(), "size": p.stat().st_size,
                              "mtime": p.stat().st_mtime}
                             for p in sorted((owner.root / "data").rglob("*")) if p.is_file()]
                    self._send(200, json.dumps({"household": "wakeword", "files": files}).encode())
                elif url.path == "/api/wake_word_recorder/file":
                    path = owner.root / parse_qs(url.query)["path"][0]
                    self._send(200, path.read_bytes(), "audio/wav") if path.is_file() else self._send(404, b'{"message":"no such recording"}')
                elif url.path == "/api/":
                    self._send(200, b'{"message": "API running."}')
                elif url.path == "/api/wake_word_recorder/household":
                    self._send(200, (owner.root / "household.yaml").read_bytes(), "application/yaml")
                else:
                    self._send(404, b"404: Not Found", "text/plain")

            def do_PUT(self):
                if not self._authorised():
                    return
                owner.put = self.rfile.read(int(self.headers["Content-Length"])).decode()
                self._send(200, b'{"saved": true}')

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def add(self, relative: str, data: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


@pytest.fixture
def ha(tmp_path):
    fake = FakeHa(tmp_path / "ha")
    fake.add("household.yaml", HOUSEHOLD.encode())
    fake.add("data/real/hej_jarvis/tomek/tomek_000_near.wav", b"RIFF-0")
    fake.add("data/real/hej_jarvis/tomek/tomek_001_far.wav", b"RIFF-01")
    fake.add("data/background/salon_20261028_2100.wav", b"RIFF-background")
    fake.add("data/real/recordings.csv", b"time,file,word,speaker,satellite\n"
             b"t0,data/real/hej_jarvis/tomek/tomek_000_near.wav,hej_jarvis,tomek,sat\n"
             b"t1,data/real/hej_jarvis/tomek/tomek_001_far.wav,hej_jarvis,tomek,sat\n")
    yield fake
    fake.server.shutdown()


@pytest.fixture(autouse=True)
def no_real_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")
    monkeypatch.delenv("WAKEWORD_HA_URL", raising=False)
    monkeypatch.delenv("WAKEWORD_HA_TOKEN", raising=False)


def client(ha) -> ha_sync.Client:
    return ha_sync.Client(ha_sync.Connection(ha.url, TOKEN))


def test_connection_kept_outside_the_household_for_its_owner_only(monkeypatch):
    assert not ha_sync.load_connection().ready
    ha_sync.save_connection("http://homeassistant.local:8123/", TOKEN)
    assert ha_sync.load_connection() == ha_sync.Connection("http://homeassistant.local:8123", TOKEN)
    assert ha_sync.CONFIG_FILE.stat().st_mode & 0o077 == 0
    ha_sync.save_connection("http://10.0.0.2:8123", None)  # the address only: the token stays
    assert ha_sync.load_connection().token == TOKEN
    with pytest.raises(ValueError, match="token") as err:
        ha_sync.save_connection("http://10.0.0.2:8123", "bad token!")
    assert "bad token" not in str(err.value)
    with pytest.raises(ValueError, match="address"):
        ha_sync.save_connection("homeassistant.local", None)
    monkeypatch.setenv("WAKEWORD_HA_TOKEN", "b" * 40)
    assert ha_sync.load_connection().token == "b" * 40
    monkeypatch.delenv("WAKEWORD_HA_TOKEN")
    ha_sync.save_connection("", "")
    assert not ha_sync.CONFIG_FILE.exists()
    with pytest.raises(ha_sync.HaError, match="no Home Assistant connection"):
        ha_sync.Client()


def test_pull_brings_new_recordings_once(ha, tmp_path):
    home = tmp_path / "home"
    counts = ha_sync.pull(home, client(ha), log=lambda line: None)
    assert counts["new"] == 3 and counts["log_rows"] == 2
    assert (home / "household.yaml").read_text() == HOUSEHOLD  # none here yet: brought too
    assert (home / "data/real/hej_jarvis/tomek/tomek_001_far.wav").read_bytes() == b"RIFF-01"
    assert (home / "data/background/salon_20261028_2100.wav").is_file()
    assert not list(home.rglob(".*.part"))

    # a new take on Home Assistant; one deleted here (moved to data/backup) stays deleted
    ha.add("data/real/hej_jarvis/tomek/tomek_002_quiet.wav", b"RIFF-002")
    with (ha.root / "data/real/recordings.csv").open("a") as log:
        log.write("t2,data/real/hej_jarvis/tomek/tomek_002_quiet.wav,hej_jarvis,tomek,sat\n")
    (home / "data/real/hej_jarvis/tomek/tomek_000_near.wav").unlink()
    counts = ha_sync.pull(home, client(ha), log=lambda line: None)
    assert counts["new"] == 1 and counts["known"] == 3 and counts["log_rows"] == 1
    assert not (home / "data/real/hej_jarvis/tomek/tomek_000_near.wav").exists()
    rows = (home / "data/real/recordings.csv").read_text().splitlines()
    assert rows[0] == "time,file,word,speaker,satellite" and len(rows) == 4
    assert ha_sync.read_state(home)["household"] == "wakeword"


def test_pull_counts_a_copied_folder_as_brought(ha, tmp_path):
    home = tmp_path / "home"
    for relative in ("data/real/hej_jarvis/tomek/tomek_000_near.wav", "data/background/salon_20261028_2100.wav"):
        (home / relative).parent.mkdir(parents=True, exist_ok=True)
        (home / relative).write_bytes((ha.root / relative).read_bytes())
    (home / "household.yaml").write_text("speakers: []\n")  # here first: kept, not replaced
    counts = ha_sync.pull(home, client(ha), log=lambda line: None)
    assert counts["new"] == 1 and counts["known"] == 2
    assert (home / "household.yaml").read_text() == "speakers: []\n"


def test_household_sent_back(ha, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "household.yaml").write_text(HOUSEHOLD + "# edited in the panel\n")
    ha_sync.push_household(home, client(ha))
    assert ha.put.endswith("# edited in the panel\n")


def test_refusals_said_in_plain_words(ha, tmp_path):
    wrong = ha_sync.Client(ha_sync.Connection(ha.url, "b" * 40))
    with pytest.raises(ha_sync.HaError, match="401: the token is wrong"):
        wrong.files()
    assert "403" in ha_sync.explain(403, "") and "administrator" in ha_sync.explain(403, "")
    assert "update the Wake Word Recorder" in ha_sync.explain(404, "404: Not Found")
    assert ha_sync.explain(404, '{"message": "no such recording"}') == "Home Assistant 404: no such recording"
    gone = ha_sync.Client(ha_sync.Connection("http://127.0.0.1:9", TOKEN))
    with pytest.raises(ha_sync.HaError, match="cannot be reached"):
        gone.files()
    assert TOKEN not in str(ha.requests)


def test_rejected_token_never_sent_again_until_saved_anew(ha):
    # every 401 is a failed login for Home Assistant's ip_ban: one, then nothing until a new save
    ha_sync.save_connection(ha.url, "b" * 40)
    with pytest.raises(ha_sync.TokenRejected, match="401: the token is wrong"):
        ha_sync.Client().files()
    assert ha_sync.token_rejected()
    asked = len(ha.requests)
    for call in (lambda: ha_sync.Client().files(), lambda: ha_sync.Client().entity_state("switch.x"),
                 ha_sync.check_connection):
        with pytest.raises(ha_sync.TokenRejected, match="not asked again"):
            call()
    assert len(ha.requests) == asked  # Home Assistant never asked
    ha_sync.save_connection(ha.url, None)  # "Save" with the same token: asked once more
    assert not ha_sync.token_rejected()
    with pytest.raises(ha_sync.TokenRejected):
        ha_sync.check_connection()
    assert len(ha.requests) == asked + 1 and ha_sync.token_rejected()
    ha_sync.save_connection(ha.url, TOKEN)  # the right token
    ha_sync.check_connection()
    assert not ha_sync.token_rejected() and ha.requests[-1] == "/api/"


def test_other_refusals_do_not_stop_the_questions(ha):
    ha_sync.save_connection(ha.url, TOKEN)
    with pytest.raises(ha_sync.HaError, match="404") as err:
        ha_sync.Client().entity_state("switch.x")
    assert not isinstance(err.value, ha_sync.TokenRejected) and not ha_sync.token_rejected()
    gone = ha_sync.Client(ha_sync.Connection("http://127.0.0.1:9", TOKEN))
    with pytest.raises(ha_sync.HaError, match="cannot be reached"):
        gone.files()
    assert not ha_sync.token_rejected()


def test_rejected_token_from_the_environment_remembered_too(ha, monkeypatch):
    monkeypatch.setenv("WAKEWORD_HA_URL", ha.url)
    monkeypatch.setenv("WAKEWORD_HA_TOKEN", "b" * 40)
    with pytest.raises(ha_sync.TokenRejected):
        ha_sync.check_connection()
    assert ha_sync.token_rejected() and ha_sync.CONFIG_FILE.stat().st_mode & 0o077 == 0


def test_esphome_devices_and_models_through_the_api(ha, tmp_path):
    import json as json_module

    devices = [{"name": "sypialnia-ha-voice", "friendly_name": "Sypialnia", "file": "sypialnia-ha-voice.yaml"}]
    sent = {}
    handler = ha.server.RequestHandlerClass
    original_get, original_put = handler.do_GET, handler.do_PUT

    def do_get(self):
        if self.path == "/api/wake_word_recorder/esphome":
            body = json_module.dumps({"devices": devices}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
            return
        original_get(self)

    def do_put(self):
        if self.path.startswith("/api/wake_word_recorder/wake_words/"):
            name = self.path.rsplit("/", 1)[1]
            sent[name] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json_module.dumps({"saved": f"esphome/wake_words/{name}"}).encode())
            return
        original_put(self)

    handler.do_GET, handler.do_PUT = do_get, do_put
    try:
        assert client(ha).esphome_devices() == devices
        model = tmp_path / "hej_jarvis.tflite"
        model.write_bytes(b"TFL3")
        assert client(ha).upload_wake_word(model) == "esphome/wake_words/hej_jarvis.tflite"
        assert sent == {"hej_jarvis.tflite": b"TFL3"}
    finally:
        handler.do_GET, handler.do_PUT = original_get, original_put


def test_home_assistant_name_looked_up_once_ipv4_first(monkeypatch):
    """macOS waits 5 s for an IPv6 answer of homeassistant.local on every request: asked once, IPv4."""
    import socket

    asked = []

    def getaddrinfo(host, port, family=0, kind=0):
        asked.append((host, family))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.4", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(ha_sync, "_resolved", {})
    url, headers = ha_sync._direct_url("http://homeassistant.local:8123/api/states/switch.x")
    assert url == "http://192.168.1.4:8123/api/states/switch.x" and headers == {"Host": "homeassistant.local:8123"}
    ha_sync._direct_url("http://homeassistant.local:8123/api/states/sensor.y")
    assert asked == [("homeassistant.local", socket.AF_INET)]  # kept
    assert ha_sync._direct_url("https://ha.example.com/api") == ("https://ha.example.com/api", {})  # the certificate
    assert ha_sync._direct_url("http://10.0.0.2:8123/api") == ("http://10.0.0.2:8123/api", {})


def test_home_assistant_name_not_found_leaves_the_url(monkeypatch):
    import socket

    def fail(*args):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr(ha_sync, "_resolved", {})
    assert ha_sync._direct_url("http://nope.local:8123/api") == ("http://nope.local:8123/api", {})


def test_tests_never_reach_a_real_home_assistant():
    """conftest stops every request that would leave this computer - a made-up token is a failed login."""
    client = ha_sync.Client(ha_sync.Connection("http://10.255.255.1:8123", "t" * 40))
    with pytest.raises(ha_sync.HaError, match="tests never leave this computer"):
        client.entity_state("switch.machine")

"""The studio's server: the editor's calls, the draft and history, power off after training, login over HTTP."""

import json
import threading
from pathlib import Path

import pytest
import yaml

from wakeword import __version__
from wakeword.studio import server as studio_module
from wakeword.studio.drafts import Conflict
from wakeword.studio.server import POWER_OFF_DELAY, Studio, make_server
from wakeword.trainer import server as trainer_module

from ..conftest import record_takes
from ..test_trainer_runner import fake_repo
from ..test_trainer_server import LOG, call, wait

PASSWORD = ("admin", "pa:ss")


@pytest.fixture
def studio(tmp_path, household_dir, monkeypatch):
    monkeypatch.setattr(trainer_module, "POLL_SECONDS", 0)
    repo = fake_repo(tmp_path, f'echo "args: $*"; cat "{LOG}"; sleep "${{SLEEP:-0}}"\n')
    return Studio(household_dir, repo=repo)


def data_of(studio):
    return yaml.safe_load((studio.household / "household.yaml").read_text(encoding="utf-8"))


def test_training_always_on_this_machine(studio):
    """No SSH mode any more (1.0.0): one local runner, and the old panel's machine actions are unknown."""
    from wakeword.trainer.runner import LocalRunner

    assert isinstance(studio.runner(), LocalRunner) and not hasattr(studio, "set_config")
    for action in ("sync", "fetch", "fetch_samples", "machine_on", "panel_access"):
        with pytest.raises(ValueError, match="unknown action"):
            studio.call({"type": "action", "action": action})
    assert not {"config", "access", "ssh_keys"} & set(studio.state())
    with pytest.raises(ValueError, match="unknown call"):
        studio.call({"type": "nope"})


def test_a_missing_household_folder_is_created(tmp_path):
    studio = Studio(tmp_path / "new-home")
    view = studio.call({"type": "household/get"})
    assert view["exists"] is False and view["draft"] is None and (tmp_path / "new-home").is_dir()


def test_state_carries_the_studio_part(studio, household):
    record_takes(household, "robo", "kid", 2)
    state = studio.call({"type": "state", "language": "pl"}, user="admin")
    assert state["language"] == "pl" and state["studio"]["user"] == "admin"
    assert state["studio"]["power_off"] == {"after_training": False, "at": None}
    assert {w["id"] for w in state["words"]} == {"hey_tony", "robo"}


def test_draft_save_and_history(studio):
    view = studio.call({"type": "household/get"})
    data = view["data"]
    data["speakers"].append({"id": "mum", "group": "adult"})
    studio.call({"type": "draft/save", "data": data, "base": view["hash"]})
    assert studio.call({"type": "household/get"})["draft"]["data"]["speakers"][-1]["id"] == "mum"
    assert [s["id"] for s in data_of(studio)["speakers"]] == ["dad", "kid"]  # nothing saved before "Save"
    answer = studio.call({"type": "household/save", "data": data, "base": view["hash"], "note": "mum"}, user="admin")
    assert answer["ok"] and answer["warning"] is None
    assert [s["id"] for s in data_of(studio)["speakers"]] == ["dad", "kid", "mum"]
    view = studio.call({"type": "household/get"})
    assert view["draft"] is None and view["hash"] == answer["hash"]
    versions = studio.call({"type": "history/list"})["versions"]
    assert len(versions) == 1 and versions[0]["user"] == "admin" and versions[0]["note"] == "mum"
    old = studio.call({"type": "history/get", "id": versions[0]["id"]})["text"]
    assert "mum" not in old
    restored = studio.call({"type": "history/restore", "id": versions[0]["id"]})["data"]
    assert [s["id"] for s in restored["speakers"]] == ["dad", "kid"]
    assert studio.call({"type": "household/get"})["draft"]["data"] == restored
    assert [s["id"] for s in data_of(studio)["speakers"]] == ["dad", "kid", "mum"]  # still only a draft


def test_save_refuses_a_file_changed_meanwhile_and_bad_data(studio):
    view = studio.call({"type": "household/get"})
    (studio.household / "household.yaml").write_text(
        (studio.household / "household.yaml").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Conflict):
        studio.call({"type": "household/save", "data": view["data"], "base": view["hash"]})
    studio.call({"type": "household/save", "data": view["data"], "base": view["hash"], "force": True})
    view = studio.call({"type": "household/get"})
    broken = {**view["data"], "speakers": [{"id": "Bad Id!", "group": "adult"}]}
    with pytest.raises(ValueError):
        studio.call({"type": "household/save", "data": broken, "base": view["hash"]})
    assert len(studio.call({"type": "history/list"})["versions"]) == 1  # the refused save left no version


def test_actions_and_lists_go_to_the_training_panel(studio, household):
    record_takes(household, "robo", "kid", 6)
    assert studio.call({"type": "action", "action": "check"})["ok"]
    assert wait(lambda: not studio.job.running)
    assert studio.call({"type": "recordings"})["takes"]
    assert "voices" in studio.call({"type": "elevenlabs/voices", "language": "pl"})
    assert studio.call({"type": "training_log"}) == {"text": ""}


def test_machine_goes_off_after_training_unless_cancelled(studio, monkeypatch):
    clock = [1000.0]
    studio.clock = lambda: clock[0]
    switched = []
    monkeypatch.setattr(studio, "switch_machine", lambda on: switched.append(on))
    assert studio.call({"type": "power/off_after_training", "enabled": True}) == {"after_training": True, "at": None}
    studio.running = True
    studio.tick()
    studio.running = False
    studio.tick()  # the training ended: the countdown starts
    assert studio.power_off["at"] == 1000.0 + POWER_OFF_DELAY and switched == []
    clock[0] += POWER_OFF_DELAY + 1
    studio.tick()
    assert switched == [False] and studio.power_off == {"after_training": False, "at": None}
    studio.call({"type": "power/off_after_training", "enabled": True})
    studio.running = True
    studio.tick()
    studio.running = False
    studio.tick()
    studio.call({"type": "power/cancel"})
    clock[0] += POWER_OFF_DELAY + 1
    studio.tick()
    assert switched == [False]


class FakeJob:
    def __init__(self, running=True):
        self.running = running

    def as_dict(self):
        return {}


def test_power_off_waits_for_a_job_and_reports_a_failure(studio):
    clock = [0.0]
    studio.clock = lambda: clock[0]
    studio.call({"type": "power/off_after_training", "enabled": True})
    studio.running = True
    studio.tick()
    studio.running = False
    studio.job = FakeJob()  # the training's export (or a command started by hand) runs
    studio.tick()
    assert studio.power_off["at"] is None  # paused while it runs
    clock[0] = 500.0
    studio.job.running = False
    studio.tick()  # now the countdown starts
    assert studio.power_off["at"] == 500.0 + POWER_OFF_DELAY
    clock[0] += POWER_OFF_DELAY
    studio.tick()  # no switch set in Home Assistant: said in the state, not raised
    assert "switch" in studio.power_off_error
    assert studio.call({"type": "state"})["studio"]["power_off_error"] == studio.power_off_error


def test_a_job_started_during_the_countdown_pauses_it(studio, monkeypatch):
    clock = [0.0]
    studio.clock = lambda: clock[0]
    switched = []
    monkeypatch.setattr(studio, "switch_machine", lambda on: switched.append(on))
    studio.call({"type": "power/off_after_training", "enabled": True})
    studio.running = True
    studio.tick()
    studio.running = False
    studio.tick()
    clock[0] = 60.0
    studio.job = FakeJob()
    studio.tick()
    assert studio.power_off["at"] is None
    clock[0] = 1000.0
    studio.tick()
    assert switched == []  # never while something runs
    studio.job.running = False
    studio.tick()
    assert studio.power_off["at"] == 1000.0 + POWER_OFF_DELAY
    clock[0] += POWER_OFF_DELAY
    studio.tick()
    assert switched == [False]


def test_stop_by_hand_never_switches_the_machine_off(studio, monkeypatch):
    clock = [0.0]
    studio.clock = lambda: clock[0]
    switched = []
    monkeypatch.setattr(studio, "switch_machine", lambda on: switched.append(on))
    monkeypatch.setattr(type(studio).__mro__[1], "stop", lambda self: None)  # the runner: nothing to kill here
    studio.call({"type": "power/off_after_training", "enabled": True})
    studio.running = True
    studio.tick()
    studio.stop()
    studio.running = False
    studio.tick()
    clock[0] += 10 * POWER_OFF_DELAY
    studio.tick()
    assert switched == [] and studio.power_off == {"after_training": True, "at": None}  # still ticked
    studio.running = True  # the next training ends by itself (well or with an error): now it switches off
    studio.tick()
    studio.running = False
    studio.tick()
    clock[0] += POWER_OFF_DELAY
    studio.tick()
    assert switched == [False]


def test_a_restart_drops_the_countdown(studio, household_dir):
    studio.power_off = {"after_training": True, "at": 1.0}
    again = Studio(household_dir, studio.repo)
    assert again.power_off == {"after_training": False, "at": None}  # nothing is switched off after a restart


@pytest.fixture
def http(studio, household_dir, tmp_path):
    server = make_server(household_dir, PASSWORD, port=0, verbose=False, secret_folder=tmp_path / "secret",
                         repo=studio.repo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def login(base, user="admin", password="pa:ss"):
    return call(base + "/api/login", {"user": user, "password": password})


def test_nothing_without_login(http):
    status, _, body = call(http + "/api/health")
    assert status == 200
    # the right app answers (a demo started by mistake says so)
    assert json.loads(body) == {"ok": True, "app": "wakeword-studio", "mode": "studio", "version": __version__}
    status, headers, _ = call(http + "/")
    assert status == 303 and headers["Location"] == "/login"
    status, _, body = call(http + "/login")
    assert status == 200 and b"/api/login" in body
    assert call(http + "/favicon.svg")[0] == 200
    for path in ("/api/recording?path=x", "/docs/", "/static/main.js"):
        assert call(http + path)[0] in (303, 401)
    status, _, body = call(http + "/api/call", {"type": "state"})
    assert status == 401 and json.loads(body)["login"] is True


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A tiny built documentation: English at the root, Polish in pl/ (as MkDocs with static-i18n makes it)."""
    root = tmp_path / "site"
    (root / "pl").mkdir(parents=True)
    (root / "index.html").write_text("<h1>Start</h1>")
    (root / "11-studio.html").write_text("<h1>The studio</h1>")
    (root / "pl" / "index.html").write_text("<h1>Start PL</h1>")
    (root / "pl" / "11-studio.html").write_text("<h1>Studio</h1>")
    monkeypatch.setattr(trainer_module, "SITE", root)
    return root


def test_the_documentation_is_served_behind_the_login(http, site):
    assert call(http + "/docs/pl/11-studio.html")[0] == 401
    cookie = login(http)[1]["Set-Cookie"].split(";")[0]
    for path, text in (("/docs/", b"Start"), ("/docs/en/", b"Start"), ("/docs/en/11-studio.html", b"The studio"),
                       ("/docs/pl/", b"Start PL"), ("/docs/pl/11-studio.html", b"<h1>Studio")):
        status, _, body = call(http + path, cookie=cookie)
        assert status == 200 and text in body, path
    assert call(http + "/docs/pl/../../server.py", cookie=cookie)[0] == 404


def test_without_a_built_documentation_it_says_how_to_build_it(http, tmp_path, monkeypatch):
    monkeypatch.setattr(trainer_module, "SITE", tmp_path / "nothing")
    cookie = login(http)[1]["Set-Cookie"].split(";")[0]
    status, _, body = call(http + "/docs/pl/", cookie=cookie)
    assert status == 404 and "make docs" in json.loads(body)["error"]


def test_login_call_and_logout(http, site):
    status, _, body = login(http, password="wrong")
    assert status == 401 and json.loads(body)["error"] == "wrong user or password"
    status, headers, _ = login(http)
    assert status == 200 and "HttpOnly" in headers["Set-Cookie"]
    cookie = headers["Set-Cookie"].split(";")[0]
    status, _, body = call(http + "/api/call", {"type": "state"}, cookie=cookie)
    assert status == 200 and json.loads(body)["studio"]["user"] == "admin"
    status, _, body = call(http + "/", cookie=cookie)
    assert status == 200 and b"wakeword-studio" in body
    assert call(http + "/docs/", cookie=cookie)[0] == 200
    assert call(http + "/static/../server.py", cookie=cookie)[0] == 404
    status, _, body = call(http + "/api/call", {"type": "nope"}, cookie=cookie)
    assert status == 400 and "unknown call" in json.loads(body)["error"]
    status, headers, _ = call(http + "/api/logout", {})
    assert "Max-Age=0" in headers["Set-Cookie"]


def test_conflict_is_409_and_a_pause_after_wrong_passwords(http):
    cookie = login(http)[1]["Set-Cookie"].split(";")[0]
    status, _, body = call(http + "/api/call", {"type": "household/save", "data": {}, "base": "old"}, cookie=cookie)
    assert status == 409 and json.loads(body)["conflict"] is True
    for _ in range(5):
        status, _, body = login(http, password="wrong")
    assert status == 401 and json.loads(body)["retry_after"] > 0
    assert login(http)[0] == 401  # the right password waits too


def test_recording_audio_over_http(http, household):
    cookie = login(http)[1]["Set-Cookie"].split(";")[0]
    path = record_takes(household, "robo", "kid", 1)[0]
    relative = path.relative_to(household.root / "data").as_posix()
    status, headers, body = call(f"{http}/api/recording?path={relative}", cookie=cookie)
    assert status == 200 and headers["Content-Type"] == "audio/wav" and body[:4] == b"RIFF"
    assert call(f"{http}/api/recording?path=../../etc/passwd", cookie=cookie)[0] == 400


def test_cli_studio_needs_the_login(monkeypatch, tmp_path):
    from wakeword import cli

    monkeypatch.delenv("WAKEWORD_UI_AUTH", raising=False)
    with pytest.raises(SystemExit, match="WAKEWORD_UI_AUTH"):
        cli.main(["-H", str(tmp_path), "studio", "--port", "0"])
    served = []
    monkeypatch.setenv("WAKEWORD_UI_AUTH", "admin:x")
    monkeypatch.setattr(studio_module, "make_server", lambda *a, **k: served.append((a, k)) or _Stopped())
    cli.main(["-H", str(tmp_path), "studio", "--port", "0"])
    assert served[0][0][1] == ("admin", "x")


class _Stopped:
    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass


def test_the_demo_says_it_is_the_demo(tmp_path, monkeypatch):
    """make status reads /api/health: a demo image started on the machine by mistake must not look like the studio."""
    import sys

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "docs"))
    sys.modules.pop("studio_demo", None)
    import studio_demo

    from wakeword import elevenlabs, ha_sync
    from wakeword.trainer import runner as runner_module

    # start_studio swaps these for the demo - give them back after the test
    monkeypatch.setattr(runner_module.LocalRunner, "status", runner_module.LocalRunner.status)
    monkeypatch.setattr(ha_sync, "CONFIG_FILE", ha_sync.CONFIG_FILE)
    monkeypatch.setattr(elevenlabs, "KEY_FILE", elevenlabs.KEY_FILE)
    server, base = studio_demo.start_studio(tmp_path)
    try:
        status, _, body = call(base + "/api/health")
        assert status == 200 and json.loads(body)["mode"] == "demo"
    finally:
        server.shutdown()
        server.server_close()


def test_page_gone_before_the_answer_is_not_an_error(studio, tmp_path):
    """A reload while /api/call is answered: the closed connection is let go, no traceback in the log."""
    from http import HTTPStatus

    from wakeword.studio.auth import Auth

    class Gone:
        def write(self, data):
            raise BrokenPipeError(32, "Broken pipe")

    handler_class = studio_module._handler(studio, Auth(("admin", "pa:ss"), tmp_path / "secret"))
    handler = handler_class.__new__(handler_class)
    handler.request_version, handler.requestline, handler.command = "HTTP/1.1", "POST /api/call HTTP/1.1", "POST"
    handler.client_address, handler.close_connection, handler.wfile = ("127.0.0.1", 1), False, Gone()
    handler.log_request = lambda *args: None
    handler._json({"ok": True}, HTTPStatus.OK)
    assert handler.close_connection is True

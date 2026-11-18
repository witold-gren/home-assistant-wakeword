"""The training machine switched on and off through its plug in Home Assistant."""

from __future__ import annotations

import json

import pytest

from wakeword import ha_sync, power


class FakeHa:
    """States and service calls of Home Assistant, as Client answers them."""

    def __init__(self, switch="on", watts="54.3"):
        self.states = {"switch.maszyna_gpu": switch, "sensor.plug_power": watts}
        self.calls = []

    def entity_state(self, entity_id, timeout=5):
        return {"state": self.states[entity_id], "attributes": {}}

    def call_service(self, domain, service, entity_id, timeout=10):
        self.calls.append(f"{domain}.{service} {entity_id}")


SETTINGS = power.PowerSettings(switch="switch.maszyna_gpu", sensor="sensor.plug_power", off_watts=5)


@pytest.fixture(autouse=True)
def config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ha_sync, "CONFIG_FILE", tmp_path / "config" / "home_assistant.json")


def test_settings_kept_next_to_the_connection():
    assert not power.load_power().ready
    ha_sync.save_connection("http://homeassistant.local:8123", "t" * 40)
    power.save_power(power.PowerSettings(switch="switch.maszyna_gpu", sensor="sensor.plug_power", off_watts="7"))
    assert power.load_power() == power.PowerSettings("switch.maszyna_gpu", "sensor.plug_power", 7.0)
    ha_sync.save_connection("http://10.0.0.2:8123", None)  # the connection changed: the power settings stay
    assert power.load_power().switch == "switch.maszyna_gpu" and ha_sync.load_connection().token == "t" * 40
    assert ha_sync.CONFIG_FILE.stat().st_mode & 0o077 == 0
    for bad, match in ((power.PowerSettings(switch="sensor.plug", sensor="sensor.x"), "switch"),
                       (power.PowerSettings(switch="switch.plug", sensor="switch.x"), "sensor"),
                       (power.PowerSettings(switch="switch.plug", sensor="sensor.x", off_watts=0), "threshold")):
        with pytest.raises(ValueError, match=match):
            power.save_power(bad)


def test_state_for_the_header():
    state = lambda ha, reachable=False: power.machine_state(ha, SETTINGS, reachable)  # noqa: E731
    assert state(FakeHa(), reachable=True) == {"switch": "on", "watts": 54.3, "machine": "on"}
    assert state(FakeHa())["machine"] == "starting"  # on, the SSH port not answering yet
    assert state(FakeHa(switch="off", watts="48"))["machine"] == "stopping"  # Home Assistant shutting it down
    assert state(FakeHa(switch="off", watts="0.4"))["machine"] == "off"
    assert state(FakeHa(switch="unavailable", watts="unavailable")) == {"switch": "unavailable", "watts": None,
                                                                       "machine": "unknown"}


def test_switch_flipped_in_home_assistant():
    ha = FakeHa()
    power.switch_machine(ha, SETTINGS, on=False)
    power.switch_machine(ha, SETTINGS, on=True)
    assert ha.calls == ["switch.turn_off switch.maszyna_gpu", "switch.turn_on switch.maszyna_gpu"]


def test_home_assistant_states_and_services_over_http(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _answer(self, body):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization")))
            self._answer({"entity_id": "switch.plug", "state": "on"} if self.path == "/api/states/switch.plug"
                         else [{"entity_id": "sensor.p", "attributes": {"unit_of_measurement": "W"}}])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(("POST", self.path, body))
            self._answer([])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = ha_sync.Client(ha_sync.Connection(f"http://127.0.0.1:{server.server_address[1]}", "t" * 40))
        assert client.entity_state("switch.plug")["state"] == "on"
        assert client.entities()[0]["entity_id"] == "sensor.p"
        client.call_service("switch", "turn_off", "switch.plug")
        assert seen[0] == ("GET", "/api/states/switch.plug", "Bearer " + "t" * 40)
        assert seen[-1] == ("POST", "/api/services/switch/turn_off", {"entity_id": "switch.plug"})
    finally:
        server.shutdown()

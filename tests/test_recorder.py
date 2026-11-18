import io
import json
import shutil
import ssl
import threading
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest
import soundfile as sf

from wakeword.audio import SAMPLE_RATE
from wakeword.recorder import certs, make_server
from wakeword.recorder.server import Recorder, RecorderError

from .conftest import silence, utterance


def wav_bytes(samples, rate=SAMPLE_RATE):
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.fixture
def recorder(household_dir):
    return Recorder(household_dir)


def test_info(recorder):
    info = recorder.info()
    assert info["household"] == "home"
    assert info["ui"]["who_are_you"] == "Who are you?"
    assert "far" in info["takes"]
    kid = next(s for s in info["speakers"] if s["id"] == "kid")
    assert [w["id"] for w in kid["words"]] == ["hey_tony", "robo"]
    assert kid["words"][0] | {"files": []} == {"id": "hey_tony", "wake_word": "Hey Tony", "done": 0,
                                               "target": 6, "files": []}


def test_polish_ui(household_dir):
    text = (household_dir / "household.yaml").read_text().replace("ui_language: en", "ui_language: pl")
    (household_dir / "household.yaml").write_text(text)
    assert Recorder(household_dir).info()["ui"]["who_are_you"] == "Kim jesteś?"


def test_upload_flow(recorder, household):
    nxt = recorder.next("robo", "kid")
    assert (nxt["variant"], nxt["number"], nxt["target"]) == ("near", 1, 6)
    result = recorder.upload("robo", "kid", "near", wav_bytes(utterance()))
    assert result["saved"] and result["issues"] == [] and result["done"] == 1
    assert result["file"] == "kid_000_near.wav"
    assert recorder.next("robo", "kid")["variant"] == "far"
    assert recorder.audio("robo", "kid", "kid_000_near.wav")[:4] == b"RIFF"
    silent = recorder.upload("robo", "kid", "far", wav_bytes(silence(1)))
    assert not silent["saved"] and silent["issues"] == ["no_speech"] and silent["done"] == 1
    assert recorder.delete("robo", "kid", "kid_000_near.wav")["done"] == 0


def test_upload_resamples_browser_rate(recorder, household):
    from wakeword.audio import read_wav, resample

    recorder.upload("robo", "kid", "near", wav_bytes(resample(utterance(), SAMPLE_RATE, 48000), 48000))
    _, rate = read_wav(household.real_dir("robo", "kid") / "kid_000_near.wav")
    assert rate == SAMPLE_RATE


@pytest.mark.parametrize(
    "call, status",
    [
        (lambda r: r.next("robo", "dad"), HTTPStatus.NOT_FOUND),
        (lambda r: r.next("robo", "nobody"), HTTPStatus.NOT_FOUND),
        (lambda r: r.upload("robo", "kid", "sideways", b""), HTTPStatus.BAD_REQUEST),
        (lambda r: r.upload("robo", "kid", "near", b"not a wav"), HTTPStatus.BAD_REQUEST),
        (lambda r: r.audio("robo", "kid", "../../household.yaml"), HTTPStatus.BAD_REQUEST),
        (lambda r: r.audio("robo", "kid", "dad_000_near.wav"), HTTPStatus.BAD_REQUEST),
        (lambda r: r.audio("robo", "kid", "kid_009_near.wav"), HTTPStatus.NOT_FOUND),
        (lambda r: r.delete("robo", "kid", "kid_009_near.wav"), HTTPStatus.NOT_FOUND),
    ],
)
def test_errors(recorder, call, status):
    with pytest.raises(RecorderError) as err:
        call(recorder)
    assert err.value.status == status


@pytest.fixture
def server(household_dir):
    server = make_server(household_dir, host="127.0.0.1", port=0, verbose=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def request(url, method="GET", data=None, context=None):
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, context=context) as response:
            return response.status, response.headers["Content-Type"], response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers["Content-Type"], err.read()


def test_http_pages(server):
    status, ctype, body = request(server + "/")
    assert status == 200 and ctype.startswith("text/html") and b"app.js" in body
    for name, kind in [("app.js", "text/javascript"), ("style.css", "text/css")]:
        status, ctype, _ = request(f"{server}/static/{name}")
        assert status == 200 and ctype.startswith(kind)
    assert request(server + "/static/../server.py")[0] == 404
    assert request(server + "/nope")[0] == 404


def test_http_api(server):
    status, _, body = request(server + "/api/info")
    assert status == 200 and json.loads(body)["household"] == "home"
    status, _, body = request(server + "/api/take?word=robo&speaker=kid&variant=near", "POST",
                              wav_bytes(utterance()))
    assert status == 200 and json.loads(body)["file"] == "kid_000_near.wav"
    status, ctype, body = request(server + "/api/take?word=robo&speaker=kid&file=kid_000_near.wav")
    assert status == 200 and ctype == "audio/wav" and body[:4] == b"RIFF"
    status, _, body = request(server + "/api/next?word=robo&speaker=kid")
    assert json.loads(body)["number"] == 2
    status, _, body = request(server + "/api/take?word=robo&speaker=kid&file=kid_000_near.wav", "DELETE")
    assert status == 200 and json.loads(body)["done"] == 0
    status, _, body = request(server + "/api/next?word=robo&speaker=dad")
    assert status == 404 and "does not record" in json.loads(body)["error"]
    assert request(server + "/api/take?word=robo&speaker=kid&variant=near", "POST", b"")[0] == 413


def test_make_server_rejects_broken_household(tmp_path):
    (tmp_path / "household.yaml").write_text("speakers: []\n")
    with pytest.raises(ValueError):
        make_server(tmp_path, port=0)


def test_subject_alt_names():
    san = certs.subject_alt_names(["10.0.0.5", "127.0.0.1", "10.0.0.5"], ["mac", "localhost"])
    assert san == "DNS:localhost,DNS:mac,IP:10.0.0.5,IP:127.0.0.1"
    assert "127.0.0.1" in certs.local_addresses()


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")
def test_https(household_dir, tmp_path):
    cert, key = certs.make_cert(tmp_path / "certs", ["127.0.0.1"])
    assert oct(key.stat().st_mode & 0o777) == "0o600"
    server = make_server(household_dir, host="127.0.0.1", port=0, cert=cert, key=key, verbose=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ssl.create_default_context(cafile=str(cert))
        context.check_hostname = False
        status, _, _ = request(f"https://127.0.0.1:{server.server_address[1]}/api/info", context=context)
        assert status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_make_cert_without_openssl(tmp_path, monkeypatch):
    monkeypatch.setattr(certs.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="openssl"):
        certs.make_cert(tmp_path)


def test_language_switch(recorder, server):
    assert recorder.info()["language"] == "en"
    polish = recorder.info("pl")
    assert polish["language"] == "pl" and polish["ui"]["who_are_you"] == "Kim jesteś?"
    assert polish["takes"]["far"].startswith("Odejdź") and polish["languages"] == ["en", "pl"]
    status, _, body = request(server + "/api/info?lang=pl")
    assert status == 200 and json.loads(body)["ui"]["start"] == "Nagrywaj"

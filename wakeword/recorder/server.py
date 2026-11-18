"""HTTP(S) server of the recorder (standard library only)."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import ssl
from urllib.parse import parse_qs, urlparse

from ..audio import AudioError, read_wav
from ..dataset import list_takes, next_take, parse_take, save_take
from ..household import Household, load_household
from ..languages import AVAILABLE, get_pack

STATIC = Path(__file__).parent / "static"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
MAX_UPLOAD = 5 * 1024 * 1024  # a take is a few seconds, ~100 kB


class RecorderError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


class Recorder:
    """The recorder's logic, separate from HTTP so it can be tested directly."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def household(self) -> Household:
        # Re-read on every request: household.yaml may be edited while the recorder runs.
        return load_household(self.root)

    def _check(self, household: Household, word: str, speaker: str) -> None:
        if speaker not in household.speakers:
            raise RecorderError(HTTPStatus.NOT_FOUND, f"unknown speaker '{speaker}'")
        if word not in household.words or speaker not in household.words[word].speakers:
            raise RecorderError(HTTPStatus.NOT_FOUND, f"'{speaker}' does not record '{word}'")

    def _progress(self, household: Household, word: str, speaker: str) -> dict:
        target = household.targets.for_group(household.speakers[speaker].group)
        takes = list_takes(household, word, speaker)
        return {"done": len(takes), "target": target, "files": [t.path.name for t in takes]}

    def info(self, language: str | None = None) -> dict:
        household = self.household
        # the page may switch the language; default: ui_language of household.yaml
        pack = get_pack(language or household.ui_language)
        return {
            "household": household.name,
            "ui": pack.UI,
            "language": pack.__name__.rsplit(".", 1)[-1],
            "languages": list(AVAILABLE),
            "takes": pack.TAKES,
            "speakers": [
                {
                    "id": s.id,
                    "group": s.group,
                    "words": [
                        {"id": w.id, "wake_word": w.wake_word, **self._progress(household, w.id, s.id)}
                        for w in household.words_for(s.id)
                    ],
                }
                for s in household.speakers.values()
            ],
        }

    def next(self, word: str, speaker: str) -> dict:
        household = self.household
        self._check(household, word, speaker)
        take = next_take(household, word, speaker)
        progress = self._progress(household, word, speaker)
        return {"variant": take.variant, "number": progress["done"] + 1, **progress}

    def upload(self, word: str, speaker: str, variant: str, body: bytes) -> dict:
        household = self.household
        self._check(household, word, speaker)
        if variant not in get_pack("en").TAKES:
            raise RecorderError(HTTPStatus.BAD_REQUEST, f"unknown variant '{variant}'")
        try:
            samples, rate = read_wav(io.BytesIO(body))
        except AudioError as err:
            raise RecorderError(HTTPStatus.BAD_REQUEST, f"not a WAV file: {err}") from err
        take, issues = save_take(household, word, speaker, samples, rate, variant)
        saved = take.path.exists()
        return {"saved": saved, "file": take.path.name if saved else None, "issues": issues,
                **self._progress(household, word, speaker)}

    def _take_path(self, word: str, speaker: str, name: str) -> Path:
        household = self.household
        self._check(household, word, speaker)
        take = parse_take(Path(name))
        if take is None or take.speaker != speaker or "/" in name or "\\" in name:
            raise RecorderError(HTTPStatus.BAD_REQUEST, "bad file name")
        path = household.real_dir(word, speaker) / name
        if not path.exists():
            raise RecorderError(HTTPStatus.NOT_FOUND, "no such take")
        return path

    def audio(self, word: str, speaker: str, name: str) -> bytes:
        return self._take_path(word, speaker, name).read_bytes()

    def delete(self, word: str, speaker: str, name: str) -> dict:
        self._take_path(word, speaker, name).unlink()
        return self._progress(self.household, word, speaker)


def _handler(recorder: Recorder):
    class Handler(BaseHTTPRequestHandler):
        server_version = "wakeword-recorder"

        def log_message(self, format, *args):  # noqa: A002 - signature from the base class
            if getattr(self.server, "verbose", True):
                super().log_message(format, *args)

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _params(self) -> dict[str, str]:
            return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        def _route(self, method: str) -> None:
            path = urlparse(self.path).path
            p = self._params()
            try:
                if method == "GET" and path in ("/", "/index.html"):
                    return self._static("index.html")
                if method == "GET" and path.startswith("/static/"):
                    return self._static(path.removeprefix("/static/"))
                if path == "/api/info" and method == "GET":
                    return self._json(recorder.info(p.get("lang")))
                if path == "/api/next" and method == "GET":
                    return self._json(recorder.next(p.get("word", ""), p.get("speaker", "")))
                if path == "/api/take" and method == "POST":
                    length = int(self.headers.get("Content-Length") or 0)
                    if length <= 0 or length > MAX_UPLOAD:
                        raise RecorderError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "bad upload size")
                    body = self.rfile.read(length)
                    return self._json(recorder.upload(p.get("word", ""), p.get("speaker", ""),
                                                      p.get("variant", ""), body))
                if path == "/api/take" and method == "GET":
                    data = recorder.audio(p.get("word", ""), p.get("speaker", ""), p.get("file", ""))
                    return self._send(HTTPStatus.OK, data, "audio/wav")
                if path == "/api/take" and method == "DELETE":
                    return self._json(recorder.delete(p.get("word", ""), p.get("speaker", ""), p.get("file", "")))
                raise RecorderError(HTTPStatus.NOT_FOUND, "not found")
            except RecorderError as err:
                self._json({"error": str(err)}, err.status)
            except Exception as err:  # noqa: BLE001 - report instead of dropping the connection
                self._json({"error": f"{type(err).__name__}: {err}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _static(self, name: str) -> None:
            file = (STATIC / name).resolve()
            if STATIC.resolve() not in file.parents or not file.is_file():
                raise RecorderError(HTTPStatus.NOT_FOUND, "not found")
            self._send(HTTPStatus.OK, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def do_DELETE(self):  # noqa: N802
            self._route("DELETE")

    return Handler


def make_server(root: Path, host: str = "0.0.0.0", port: int = 8443, cert: Path | None = None,
                key: Path | None = None, verbose: bool = True) -> ThreadingHTTPServer:
    load_household(root)  # fail early on a broken household.yaml
    server = ThreadingHTTPServer((host, port), _handler(Recorder(root)))
    server.verbose = verbose
    if cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key) if key else None)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def serve(root: Path, **kwargs) -> None:
    server = make_server(root, **kwargs)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

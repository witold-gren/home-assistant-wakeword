"""HTTP server of the wake word studio: the training panel as an editor, run on the GPU machine itself.

The training backend (``wakeword.trainer.server.Trainer``) trains on this machine (the Docker container);
the studio adds the login, the draft and history of household.yaml, switching the machine off after
training, and one endpoint ``POST /api/call {"type": …}`` that the editor
calls the way the Home Dashboard and Assist Router editors call Home Assistant (``hass.callWS``).
Audio is served by plain GETs (``/api/recording``, ``/api/elevenlabs/test``) so ``<audio>`` can play it.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__, ha_sync
from ..trainer.server import CONTENT_TYPES, REPO, Trainer, docs_path
from .auth import (
    COOKIE,
    ENV,
    TRUSTED_ENV,
    Auth,
    LoginRefused,
    parse_credentials,
    parse_networks,
)
from .drafts import Conflict, Drafts

WWW = Path(__file__).parent / "www"
POWER_OFF_DELAY = 120  # seconds between the end of a training and switching the machine off (can be cancelled)
MAX_BODY = 2_000_000
CONTENT_TYPES = {**CONTENT_TYPES, ".json": "application/json; charset=utf-8", ".woff2": "font/woff2",
                 ".md": "text/markdown; charset=utf-8"}


class Studio(Trainer):
    """The panel's state for the editor: training always here, in this machine's container."""

    def __init__(self, household: Path, repo: Path = REPO, clock: Callable[[], float] = time.time) -> None:
        Path(household).mkdir(parents=True, exist_ok=True)
        super().__init__(household, repo)
        self.drafts = Drafts(self.household)
        self.clock = clock
        self.power_off = {"after_training": False, "at": None}  # at: when the machine goes off (cancellable)
        self._was_busy = False
        self._stopped_by_hand = False  # "Stop" ends a training without switching the machine off

    # --- household.yaml: draft, save, history ------------------------------------------------------
    def household_view(self) -> dict:
        """The household for the editor: data, counts, devices, the file's text and hash, the draft."""
        return {**self.household_data(), **self.drafts.load(), "text": self.drafts.saved_text()}

    def save(self, data: dict, base: str, user: str, note: str = "", force: bool = False) -> str | None:
        """The draft becomes household.yaml (and goes to Home Assistant); returns why it was not sent there."""
        self.drafts.check_base(base, force)
        version = self.drafts.remember(user, note)
        try:
            warning = self.save_household(data)
        except ValueError:
            if version:  # nothing was saved: no new history entry either
                for suffix in (".yaml", ".json"):
                    (self.drafts.history_folder / f"{version}{suffix}").unlink(missing_ok=True)
            raise
        self.drafts.discard()
        return warning

    def restore(self, version: str) -> dict:
        """An old version back as the draft (saved only with "Save")."""
        data = self.drafts.version_data(version)
        self.drafts.save_draft(data, self.drafts.load()["hash"])
        return data

    # --- switching the machine off after training -------------------------------------------------
    def set_power_off(self, after_training: bool | None = None, cancel: bool = False) -> dict:
        if after_training is not None:
            self.power_off["after_training"] = bool(after_training)
            if not after_training:
                self.power_off["at"] = None
        if cancel:
            self.power_off = {"after_training": False, "at": None}
        return dict(self.power_off)

    def stop(self) -> None:
        self._stopped_by_hand = True
        super().stop()

    def busy(self) -> bool:
        """A training or a command (evaluation, export, preparing...) is running."""
        return bool(self.running) or (self.job is not None and self.job.running)

    def tick(self) -> None:
        """Called with every state (gpu-studio standard, section 6): when the work ends - well or with an error,
        not after Stop - the countdown starts; work started during the countdown pauses it until that ends too;
        when it runs out the machine goes off. The countdown lives in memory: a restart of the container drops
        it and nothing is switched off."""
        busy = self.busy()
        if busy:
            self.power_off["at"] = None  # paused: a training's evaluation, an export, a job started by hand
        elif self._was_busy:
            if self.power_off["after_training"] and not self._stopped_by_hand:
                self.power_off["at"] = self.clock() + POWER_OFF_DELAY
            self._stopped_by_hand = False
        self._was_busy = busy
        at = self.power_off["at"]
        if at is None or busy or self.clock() < at:
            return
        self.power_off = {"after_training": False, "at": None}  # used once
        try:
            self.switch_machine(False)
        except (ValueError, RuntimeError) as err:
            self.power_off_error = str(err)

    # --- one call of the editor ------------------------------------------------------------------
    def call(self, message: dict, user: str = "", trusted: bool = False) -> object:
        kind = message.get("type")
        arg = lambda name, default="": message.get(name, default)
        if kind == "state":
            self.tick()
            state = self.state(arg("language") or None)
            state["studio"] = {"user": user, "trusted": trusted, "version": __version__, "power_off": dict(self.power_off),
                               "power_off_delay": POWER_OFF_DELAY,
                               "power_off_error": getattr(self, "power_off_error", None)}
            return state
        if kind == "household/get":
            return self.household_view()
        if kind == "draft/save":
            self.drafts.save_draft(dict(arg("data", {})), str(arg("base")))
            return {"ok": True}
        if kind == "draft/discard":
            self.drafts.discard()
            return {"ok": True}
        if kind == "household/save":
            warning = self.save(dict(arg("data", {})), str(arg("base")), user, str(arg("note")), bool(arg("force", False)))
            return {"ok": True, "warning": warning, "hash": self.drafts.load()["hash"]}
        if kind == "history/list":
            return {"versions": self.drafts.versions()}
        if kind == "history/get":
            return {"text": self.drafts.version_text(str(arg("id")))}
        if kind == "history/restore":
            return {"data": self.restore(str(arg("id")))}
        if kind == "action":
            return {"ok": True, "warning": self.action(dict(message))}
        if kind == "power/off_after_training":
            return self.set_power_off(after_training=bool(arg("enabled", False)))
        if kind == "power/cancel":
            return self.set_power_off(cancel=True)
        if kind == "recordings":
            return self.recordings()
        if kind == "models":
            return self.models(str(arg("word")))
        if kind == "model_progress":
            return self.model_progress(str(arg("word")), str(arg("model")))
        if kind == "ha_entities":
            return self.ha_entities()
        if kind == "hf_voices":
            return {"voices": self.hf_voices(str(arg("repo")))}
        if kind == "elevenlabs/voices":
            return {"voices": self.elevenlabs_voices(str(arg("language")), bool(arg("sync", False)))}
        if kind == "training_log":
            return {"text": self.training_log()}
        raise ValueError(f"unknown call '{kind}'")


ERRORS = (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, ha_sync.HaError)


def _handler(studio: Studio, auth: Auth):
    class Handler(BaseHTTPRequestHandler):
        server_version = "wakeword-studio"

        def log_message(self, format, *args):
            if getattr(self.server, "verbose", True) and not self.path.startswith(("/api/call", "/api/health")):
                super().log_message(format, *args)

        def _send(self, status: HTTPStatus, body: bytes, content_type: str, headers: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):  # the page was reloaded or closed meanwhile
                self.close_connection = True

        def _json(self, data, status: HTTPStatus = HTTPStatus.OK, headers: dict | None = None) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                       headers)

        def _trusted(self) -> bool:
            return auth.trusted(self.client_address[0])  # the connection's address, never a header

        def _user(self) -> str | None:
            if self._trusted():
                return auth.user
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return auth.check(cookie[COOKIE].value if COOKIE in cookie else None)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                raise ValueError("request too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("bad request")
            return data

        def _static(self, name: str, folder: Path = WWW) -> None:
            file = (folder / name).resolve()
            if folder.resolve() not in file.parents or not file.is_file():
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            self._send(HTTPStatus.OK, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            arg = lambda name: query.get(name, [""])[0]
            if url.path == "/api/health":
                # which app answers: a demo image started by mistake also has /api/health
                mode = "demo" if getattr(self.server, "demo", None) is not None else "studio"
                return self._json({"ok": True, "app": "wakeword-studio", "mode": mode, "version": __version__})
            if url.path == "/login":
                if self._trusted():  # nothing to log in to from a trusted network
                    return self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {"Location": "/"})
                return self._static("login.html")
            if url.path in ("/favicon.svg", "/icon.png"):
                return self._static(url.path.lstrip("/"))
            user = self._user()
            if user is None:
                if url.path.startswith(("/api/", "/docs/")):
                    return self._json({"error": "log in first", "login": True}, HTTPStatus.UNAUTHORIZED)
                return self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {"Location": "/login"})
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path.removeprefix("/static/"))
            if url.path.startswith("/docs/"):
                folder, name = docs_path(url.path.removeprefix("/docs/"))
                if not (folder / "index.html").is_file():
                    return self._json({"error": "the documentation is not built here: make docs"}, HTTPStatus.NOT_FOUND)
                return self._static(name, folder)
            try:
                if url.path == "/api/recording":
                    return self._send(HTTPStatus.OK, studio.recording_audio(arg("path")), "audio/wav")
                if url.path == "/api/elevenlabs/test":
                    audio = studio.elevenlabs_test(arg("voice"), arg("word"), arg("language"), arg("model"))
                    return self._send(HTTPStatus.OK, audio, "audio/wav")
            except ERRORS as err:
                return self._json({"error": str(err)}, HTTPStatus.BAD_REQUEST)
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                data = self._body()
            except (ValueError, json.JSONDecodeError) as err:
                return self._json({"error": str(err) or "bad JSON"}, HTTPStatus.BAD_REQUEST)
            if path == "/api/login":
                try:
                    cookie = auth.login(self.client_address[0], str(data.get("user", "")), str(data.get("password", "")))
                except LoginRefused as err:
                    return self._json({"error": str(err), "retry_after": err.retry_after}, HTTPStatus.UNAUTHORIZED)
                secure = self.headers.get("X-Forwarded-Proto") == "https"
                return self._json({"ok": True}, headers={"Set-Cookie": auth.set_cookie(cookie, secure)})
            if path == "/api/logout":
                return self._json({"ok": True}, headers={"Set-Cookie": auth.clear_cookie()})
            user = self._user()
            if user is None:
                return self._json({"error": "log in first", "login": True}, HTTPStatus.UNAUTHORIZED)
            if path != "/api/call":
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            try:
                return self._json(studio.call(data, user, self._trusted()))
            except Conflict as err:
                return self._json({"error": str(err), "conflict": True}, HTTPStatus.CONFLICT)
            except ERRORS as err:
                return self._json({"error": str(err)}, HTTPStatus.BAD_REQUEST)

    return Handler


def make_server(household: Path, credentials: tuple[str, str], host: str = "127.0.0.1", port: int = 8765,
                verbose: bool = True, secret_folder: Path | None = None, trusted_networks: tuple = (),
                **studio_options) -> ThreadingHTTPServer:
    studio = Studio(household, **studio_options)
    auth = Auth(credentials, secret_folder or ha_sync.CONFIG_FILE.parent, trusted_networks=trusted_networks)
    server = ThreadingHTTPServer((host, port), _handler(studio, auth))
    server.verbose = verbose
    server.studio = studio
    server.auth = auth
    return server


def serve(household: Path, host: str, port: int) -> None:
    try:
        credentials = parse_credentials(os.environ.get(ENV))
        trusted = parse_networks(os.environ.get(TRUSTED_ENV))
    except ValueError as err:
        raise SystemExit(f"error: {err}") from None
    server = make_server(household, credentials, host, port, trusted_networks=trusted)
    without = f"; no login from {', '.join(map(str, trusted))}" if trusted else ""
    print(f"Wake word studio for '{Path(household).resolve().name}' on http://{host}:{port}/ "
          f"(user '{credentials[0]}', password in {ENV}{without})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

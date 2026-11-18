"""Recordings and household.yaml from Home Assistant through its API - no file share needed.

The household folder lives on the computer that trains (a Mac, the GPU machine). Home Assistant
keeps only what its Wake Word Recorder integration writes: the takes recorded through the
satellites (``data/real``), the background recordings (``data/background``) and household.yaml,
which it reads. ``pull`` brings new recordings here; ``push_household`` sends household.yaml back
after an edit, so the satellites ask for the right people and words.

Connection: ``~/.config/wakeword/home_assistant.json`` (mode 600: ``{"url", "token"}`` - a long-lived
token of a Home Assistant administrator) or ``WAKEWORD_HA_URL`` / ``WAKEWORD_HA_TOKEN``. Outside
the household folder on purpose: it is copied to other machines and into backups. The token is
never printed nor sent to the panel page.

``data/ha_sync.json`` remembers every file brought here (size and time on Home Assistant): a
recording deleted here (moved to data/backup) is not brought back by the next pull.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import re
import time
from typing import Callable
from urllib import error, parse, request

HOUSEHOLD_FILE = "household.yaml"
CONFIG_FILE = Path.home() / ".config" / "wakeword" / "home_assistant.json"
STATE_FILE = "ha_sync.json"  # in data/
LOG_FILE = "recordings.csv"  # data/real/recordings.csv: which satellite recorded which take
API = "/api/wake_word_recorder"
TIMEOUT = 60
DNS_CACHE_SECONDS = 300
URL_PATTERN = re.compile(r"^https?://[^\s/]+(:\d+)?/?$")


class HaError(RuntimeError):
    """Home Assistant refused or could not be reached - said in plain words."""


class TokenRejected(HaError):
    """Home Assistant answered 401: the token is wrong or expired.

    Every 401 counts as a failed login for Home Assistant's ip_ban, so after the first one nothing asks
    again (``token_rejected`` in the connection file) until the connection is saved anew.
    """


REJECTED_KEY = "token_rejected"
REJECTED_MESSAGE = ("Home Assistant rejected the token - not asked again until the connection is saved anew "
                    "(Settings → Home Assistant)")


@dataclass
class Connection:
    url: str
    token: str

    @property
    def ready(self) -> bool:
        return bool(self.url and self.token)


def load_connection() -> Connection:
    saved = {}
    if CONFIG_FILE.is_file():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except ValueError:
            saved = {}
    url = os.environ.get("WAKEWORD_HA_URL") or saved.get("url", "")
    token = os.environ.get("WAKEWORD_HA_TOKEN") or saved.get("token", "")
    return Connection(url.rstrip("/"), token)


def save_connection(url: str, token: str | None) -> None:
    """``token`` None keeps the saved one (the panel never shows it back); "" removes the connection."""
    url = url.strip().rstrip("/")
    if url and not URL_PATTERN.match(url + "/"):
        raise ValueError("Home Assistant address: e.g. http://homeassistant.local:8123")
    if token is not None and token.strip() and not re.match(r"^[A-Za-z0-9._-]{20,}$", token.strip()):
        raise ValueError("this does not look like a Home Assistant long-lived token")  # never echoed
    kept = load_connection().token if token is None else token.strip()
    if not url and not kept:
        CONFIG_FILE.unlink(missing_ok=True)
        return
    saved = {key: value for key, value in _read_config().items() if key != REJECTED_KEY}  # asked again
    _write_config({**saved, "url": url, "token": kept})  # other keys (e.g. "power") stay


def token_rejected() -> bool:
    """Home Assistant refused the saved token; nothing is asked until the connection is saved again."""
    return bool(_read_config().get(REJECTED_KEY))


def _mark_rejected() -> None:
    _write_config({**_read_config(), REJECTED_KEY: True})  # also for a token from WAKEWORD_HA_TOKEN


def check_connection() -> None:
    """One request to Home Assistant's API with the saved connection; HaError says why it failed."""
    with Client()._open("/", api="/api", timeout=10):
        pass


def _read_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.touch(mode=0o600, exist_ok=True)
    CONFIG_FILE.chmod(0o600)
    CONFIG_FILE.write_text(json.dumps(data) + "\n", encoding="utf-8")


_resolved: dict[tuple[str, int], tuple[float, str]] = {}  # (host, port) -> (time, IPv4 address)


def _direct_url(url: str) -> tuple[str, dict]:
    """``http://homeassistant.local:8123/...`` -> the same URL with the IPv4 address, plus its Host header.

    macOS asks mDNS for IPv4 and IPv6 at once and waits 5 s for an IPv6 answer that never comes - on
    every request. The address is asked for once (IPv4 first) and kept a few minutes. HTTPS keeps the
    name (the certificate is for it); an address or a failed lookup leaves the URL as it is.
    """
    import ipaddress
    import socket

    parts = parse.urlsplit(url)
    host, port = parts.hostname or "", parts.port or 80
    if parts.scheme != "http" or not host:
        return url, {}
    try:
        ipaddress.ip_address(host)
        return url, {}
    except ValueError:
        pass
    cached = _resolved.get((host, port))
    if cached and time.time() - cached[0] < DNS_CACHE_SECONDS:
        address = cached[1]
    else:
        try:
            address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        except OSError:
            return url, {}
        _resolved[(host, port)] = (time.time(), address)
    netloc = f"{address}:{parts.port}" if parts.port else address
    return parse.urlunsplit(parts._replace(netloc=netloc)), {"Host": parts.netloc}


class Client:
    def __init__(self, connection: Connection | None = None):
        self.saved = connection is None  # the saved connection: its rejected token is remembered
        self.connection = connection or load_connection()
        if not self.connection.ready:
            raise HaError("no Home Assistant connection - set the address and token in the panel (Settings)")
        if self.saved and token_rejected():
            raise TokenRejected(REJECTED_MESSAGE)

    def _open(self, path: str, query: dict | None = None, data: bytes | None = None, method: str = "GET",
              api: str = API, timeout: float = TIMEOUT):
        url, host = _direct_url(f"{self.connection.url}{api}{path}" + (f"?{parse.urlencode(query)}" if query else ""))
        headers = {"Authorization": f"Bearer {self.connection.token}", "Content-Type": "application/json", **host}
        try:
            return request.urlopen(request.Request(url, data=data, method=method, headers=headers), timeout=timeout)
        except error.HTTPError as err:
            if err.code == 401:  # a failed login for ip_ban - never asked again with this token
                if self.saved:
                    _mark_rejected()
                raise TokenRejected(explain(401, "")) from None
            raise HaError(explain(err.code, err.read().decode("utf-8", "replace"))) from None
        except (error.URLError, OSError) as err:
            reason = getattr(err, "reason", err)
            raise HaError(f"Home Assistant at {self.connection.url} cannot be reached: {reason}") from None

    def files(self) -> dict:
        with self._open("/files") as response:
            return json.load(response)

    def download(self, relative: str, target: Path) -> None:
        tmp = target.with_name(f".{target.name}.part")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._open("/file", {"path": relative}) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        tmp.replace(target)

    def household(self) -> str:
        with self._open("/household") as response:
            return response.read().decode("utf-8")

    def put_household(self, text: str) -> None:
        with self._open("/household", data=text.encode("utf-8"), method="PUT"):
            pass

    def esphome_devices(self) -> list[dict]:
        """Voice devices of Home Assistant's ESPHome folder: [{"name", "friendly_name", "file"}]."""
        with self._open("/esphome") as response:
            return json.load(response)["devices"]

    # --- Home Assistant itself: states and services (the machine's power, see wakeword/power.py) ---
    def entity_state(self, entity_id: str, timeout: float = 5) -> dict:
        """{"state", "attributes", ...} of an entity."""
        with self._open(f"/states/{parse.quote(entity_id)}", api="/api", timeout=timeout) as response:
            return json.load(response)

    def entities(self, timeout: float = 10) -> list[dict]:
        with self._open("/states", api="/api", timeout=timeout) as response:
            return json.load(response)

    def call_service(self, domain: str, service: str, entity_id: str, timeout: float = 10) -> None:
        body = json.dumps({"entity_id": entity_id}).encode()
        with self._open(f"/services/{domain}/{service}", data=body, method="POST", api="/api", timeout=timeout):
            pass

    def upload_wake_word(self, path: Path) -> str:
        """An exported model file into /config/esphome/wake_words/; returns where it went."""
        with self._open(f"/wake_words/{parse.quote(Path(path).name)}", data=Path(path).read_bytes(), method="PUT") as response:
            return json.load(response)["saved"]


def explain(status: int, body: str) -> str:
    try:
        message = json.loads(body).get("message", "")
    except ValueError:
        message = body.strip()[:200]
    if status == 401:
        return "Home Assistant 401: the token is wrong or expired - make a new long-lived token (profile → Security)"
    if status == 403:
        return "Home Assistant 403: the token belongs to a user who is not an administrator"
    if status == 404 and (not message or "not found" in message.lower()):  # the route, not a file
        return "Home Assistant 404: no recordings API - update the Wake Word Recorder integration and restart HA"
    if status == 503:
        return f"Home Assistant 503: {message or 'Wake Word Recorder is not set up'}"
    return f"Home Assistant {status}: {message or 'refused'}"


# --- what was brought here ------------------------------------------------------------------------


def _state_path(root: Path) -> Path:
    return root / "data" / STATE_FILE


def read_state(root: Path) -> dict:
    try:
        return json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}}


def _write_state(root: Path, state: dict) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def merge_log(local: Path, remote_text: str) -> int:
    """Add the rows of Home Assistant's takes log that this one lacks (same file); returns how many."""
    rows = list(csv.reader(io.StringIO(remote_text)))
    if not rows:
        return 0
    header, remote = rows[0], rows[1:]
    column = header.index("file") if "file" in header else 1
    known = set()
    if local.is_file():
        with local.open(newline="", encoding="utf-8") as handle:
            known = {row[column] for row in list(csv.reader(handle))[1:] if len(row) > column}
    new = [row for row in remote if len(row) > column and row[column] not in known]
    if new:
        fresh = not local.is_file()
        local.parent.mkdir(parents=True, exist_ok=True)
        with local.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if fresh:
                writer.writerow(header)
            writer.writerows(new)
    return len(new)


def pull(root: Path, client: Client | None = None, log: Callable[[str], None] = print) -> dict:
    """Bring the new recordings (and household.yaml when there is none here); returns the counts."""
    root = Path(root)
    client = client or Client()
    started = time.time()
    log(f"Home Assistant {client.connection.url}: listing the recordings")
    listing = client.files()
    if not (root / HOUSEHOLD_FILE).is_file():
        root.mkdir(parents=True, exist_ok=True)
        (root / HOUSEHOLD_FILE).write_text(client.household(), encoding="utf-8")
        log(f"{HOUSEHOLD_FILE}: brought from Home Assistant")
    state = read_state(root)
    seen = state.setdefault("files", {})
    counts = {"new": 0, "known": 0, "log_rows": 0, "bytes": 0}
    for file in listing["files"]:
        relative, stamp = file["path"], [file["size"], file["mtime"]]
        target = root / relative
        if Path(relative).name == LOG_FILE:
            buffer = root / "data" / f".{LOG_FILE}.ha"
            client.download(relative, buffer)
            counts["log_rows"] += merge_log(target, buffer.read_text(encoding="utf-8"))
            buffer.unlink()
            continue
        if seen.get(relative) == stamp:  # brought before - also when deleted here since
            counts["known"] += 1
            continue
        if target.is_file() and target.stat().st_size == file["size"]:  # already here (copied by hand)
            seen[relative] = stamp
            counts["known"] += 1
            continue
        client.download(relative, target)
        seen[relative] = stamp
        counts["new"] += 1
        counts["bytes"] += file["size"]
        if counts["new"] % 50 == 0:
            log(f"  {counts['new']} recordings brought")
            _write_state(root, state)  # an interrupted pull keeps what it brought
    state["last_pull"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["household"] = listing.get("household", "")
    _write_state(root, state)
    log(f"Home Assistant: {counts['new']} new recordings ({counts['bytes'] / 1e6:.1f} MB), "
        f"{counts['known']} already here, {counts['log_rows']} new rows in {LOG_FILE} "
        f"({time.time() - started:.0f} s)")
    return counts


def push_household(root: Path, client: Client | None = None) -> None:
    """Send household.yaml to Home Assistant (the integration reads it within seconds)."""
    client = client or Client()
    client.put_household((Path(root) / HOUSEHOLD_FILE).read_text(encoding="utf-8"))

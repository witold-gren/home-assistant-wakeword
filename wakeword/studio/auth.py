"""Login to the studio: one user and password from ``WAKEWORD_UI_AUTH=user:password``.

The install script writes it to ``config/env`` (mode 600) on the first install, like Piper Voice Cloner's
``PVC_UI_AUTH``. A login gives a signed cookie (HMAC, 30 days). The signing key comes from a random secret
kept next to the other secrets and from the password itself, so changing the password logs everybody out.
After ``MAX_FAILURES`` wrong passwords from one address that address waits ``PAUSE_SECONDS``.

``STUDIO_TRUSTED_NETWORKS`` (e.g. ``192.168.1.0/24``, comma-separated, empty by default) lets a home that runs the
machine only on its own network skip the login: a connection from such a network is logged in as the user.
Only the address of the connection itself counts, never a header a client could fake. A machine in the cloud
leaves it empty and keeps the login.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ENV = "WAKEWORD_UI_AUTH"
TRUSTED_ENV = "STUDIO_TRUSTED_NETWORKS"  # the same name in every studio of the GPU machine
COOKIE = "wakeword_studio"
SESSION_SECONDS = 30 * 24 * 3600
MAX_FAILURES = 5
PAUSE_SECONDS = 60
SECRET_FILE = "studio-secret"


class LoginRefused(Exception):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def parse_credentials(value: str | None) -> tuple[str, str]:
    """``user:password`` -> (user, password); the password may contain ":"."""
    user, sep, password = (value or "").partition(":")
    if not sep or not user.strip() or not password:
        raise ValueError(f"{ENV} must be user:password (written by docker/install-ubuntu.sh to config/env)")
    return user.strip(), password


def parse_networks(value: str | None) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """``192.168.1.0/24, 10.8.0.0/24`` -> networks; empty -> none (the login is needed from everywhere)."""
    networks = []
    for part in (value or "").replace(";", ",").replace(" ", ",").split(","):
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ValueError(f"{TRUSTED_ENV}: {part!r} is not a network like 192.168.1.0/24") from None
    return tuple(networks)


def _secret(folder: Path) -> bytes:
    """A random secret kept with the other secrets (made once, mode 600)."""
    file = folder / SECRET_FILE
    if not file.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        file.touch(mode=0o600)
        file.chmod(0o600)
        file.write_text(secrets.token_hex(32), encoding="utf-8")
    return file.read_text(encoding="utf-8").strip().encode()


@dataclass
class _Failures:
    count: int = 0
    until: float = 0.0  # paused until this time


class Auth:
    def __init__(self, credentials: tuple[str, str], secret_folder: Path,
                 clock: Callable[[], float] = time.time, trusted_networks: tuple = ()) -> None:
        self.user, self._password = credentials
        self.trusted_networks = tuple(trusted_networks)
        self._clock = clock
        self._key = hmac.new(_secret(secret_folder), f"{self.user}:{self._password}".encode(), hashlib.sha256).digest()
        self._failures: dict[str, _Failures] = {}
        self._lock = threading.Lock()

    def trusted(self, address: str) -> bool:
        """The connection comes from a network that needs no login (STUDIO_TRUSTED_NETWORKS)."""
        if not self.trusted_networks:
            return False
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:  # ::ffff:192.168.1.5 on a dual-stack socket
            ip = ip.ipv4_mapped
        return any(ip.version == net.version and ip in net for net in self.trusted_networks)

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def login(self, address: str, user: str, password: str) -> str:
        """The cookie value for a right user and password; LoginRefused otherwise."""
        now = self._clock()
        with self._lock:
            failures = self._failures.get(address)
            if failures and failures.until > now:
                raise LoginRefused("too many attempts", int(failures.until - now) + 1)
            right = hmac.compare_digest(user.strip().encode(), self.user.encode()) & hmac.compare_digest(
                password.encode(), self._password.encode())
            if right:
                self._failures.pop(address, None)
            else:
                failures = self._failures.setdefault(address, _Failures())
                failures.count += 1
                if failures.count >= MAX_FAILURES:
                    failures.count, failures.until = 0, now + PAUSE_SECONDS
                    raise LoginRefused("too many attempts", PAUSE_SECONDS)
                raise LoginRefused("wrong user or password")
        payload = f"{self.user}|{int(now) + SESSION_SECONDS}"
        return f"{payload}|{self._sign(payload)}"

    def check(self, cookie: str | None) -> str | None:
        """The logged-in user of a cookie value, None when missing, forged or expired."""
        user, _, rest = (cookie or "").partition("|")
        expires, _, signature = rest.partition("|")
        if not (user and expires.isdigit() and signature):
            return None
        if not hmac.compare_digest(signature, self._sign(f"{user}|{expires}")):
            return None
        return user if int(expires) > self._clock() else None

    @staticmethod
    def set_cookie(value: str, secure: bool = False) -> str:
        return (f"{COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"
                + ("; Secure" if secure else ""))

    @staticmethod
    def clear_cookie() -> str:
        return f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"

"""Login to the studio: one user and password from ``WAKEWORD_UI_AUTH=user:password``.

The install script writes it to ``config/env`` (mode 600) on the first install, like Piper Voice Cloner's
``PVC_UI_AUTH``. A login gives a signed cookie (HMAC, 30 days). The signing key comes from a random secret
kept next to the other secrets and from the password itself, so changing the password logs everybody out.
After ``MAX_FAILURES`` wrong passwords from one address that address waits ``PAUSE_SECONDS``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import secrets
import threading
import time
from typing import Callable

ENV = "WAKEWORD_UI_AUTH"
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
                 clock: Callable[[], float] = time.time) -> None:
        self.user, self._password = credentials
        self._clock = clock
        self._key = hmac.new(_secret(secret_folder), f"{self.user}:{self._password}".encode(), hashlib.sha256).digest()
        self._failures: dict[str, _Failures] = {}
        self._lock = threading.Lock()

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

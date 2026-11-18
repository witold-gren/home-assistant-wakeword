"""Login of the studio: user:password, signed cookie, a pause after too many wrong passwords."""

import pytest

from wakeword.studio.auth import (
    MAX_FAILURES,
    PAUSE_SECONDS,
    SESSION_SECONDS,
    Auth,
    LoginRefused,
    parse_credentials,
)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def auth(tmp_path, clock):
    return Auth(("admin", "s3cret:with-colon"), tmp_path / "config", clock)


def test_credentials_from_the_environment_value():
    assert parse_credentials("admin:a:b") == ("admin", "a:b")
    for wrong in (None, "", "admin", ":pass", "admin:"):
        with pytest.raises(ValueError, match="WAKEWORD_UI_AUTH"):
            parse_credentials(wrong)


def test_right_login_gives_a_cookie_that_names_the_user(auth):
    cookie = auth.login("10.0.0.5", "admin", "s3cret:with-colon")
    assert auth.check(cookie) == "admin"
    assert "HttpOnly" in Auth.set_cookie(cookie) and "SameSite=Strict" in Auth.set_cookie(cookie)
    assert "Secure" in Auth.set_cookie(cookie, secure=True)
    assert "Max-Age=0" in Auth.clear_cookie()


def test_wrong_password_and_forged_or_missing_cookie(auth):
    with pytest.raises(LoginRefused, match="wrong user or password"):
        auth.login("10.0.0.5", "admin", "nope")
    with pytest.raises(LoginRefused):
        auth.login("10.0.0.5", "root", "s3cret:with-colon")
    cookie = auth.login("10.0.0.5", "admin", "s3cret:with-colon")
    user, expires, signature = cookie.split("|")
    assert auth.check(f"root|{expires}|{signature}") is None
    assert auth.check(f"{user}|{int(expires) + 999}|{signature}") is None
    for broken in (None, "", "admin", "admin|x|y"):
        assert auth.check(broken) is None


def test_session_expires(auth, clock):
    cookie = auth.login("10.0.0.5", "admin", "s3cret:with-colon")
    clock.now += SESSION_SECONDS - 1
    assert auth.check(cookie) == "admin"
    clock.now += 2
    assert auth.check(cookie) is None


def test_pause_after_too_many_wrong_passwords_from_one_address(auth, clock):
    for _ in range(MAX_FAILURES - 1):
        with pytest.raises(LoginRefused):
            auth.login("10.0.0.5", "admin", "nope")
    with pytest.raises(LoginRefused) as refused:
        auth.login("10.0.0.5", "admin", "nope")
    assert refused.value.retry_after == PAUSE_SECONDS
    with pytest.raises(LoginRefused, match="too many"):  # even the right password waits
        auth.login("10.0.0.5", "admin", "s3cret:with-colon")
    assert auth.check(auth.login("10.0.0.6", "admin", "s3cret:with-colon")) == "admin"  # another address
    clock.now += PAUSE_SECONDS + 1
    assert auth.check(auth.login("10.0.0.5", "admin", "s3cret:with-colon")) == "admin"


def test_new_password_or_secret_logs_everybody_out(tmp_path, clock):
    folder = tmp_path / "config"
    cookie = Auth(("admin", "one"), folder, clock).login("a", "admin", "one")
    assert Auth(("admin", "one"), folder, clock).check(cookie) == "admin"  # a restart keeps the sessions
    assert Auth(("admin", "two"), folder, clock).check(cookie) is None
    assert (folder / "studio-secret").stat().st_mode & 0o777 == 0o600
    (folder / "studio-secret").unlink()
    assert Auth(("admin", "one"), folder, clock).check(cookie) is None


def test_trusted_networks_from_the_environment_value():
    from wakeword.studio.auth import parse_networks

    assert [str(n) for n in parse_networks("192.168.0.0/23, 172.16.5.0/24;fd00::/8")] == [
        "192.168.0.0/23", "172.16.5.0/24", "fd00::/8"]
    assert parse_networks("") == () and parse_networks(None) == ()
    with pytest.raises(ValueError, match="STUDIO_TRUSTED_NETWORKS: 'home' is not a network"):
        parse_networks("home")


def test_a_trusted_network_needs_no_login_and_nothing_else_does(tmp_path, clock):
    from wakeword.studio.auth import parse_networks

    auth = Auth(("admin", "pw"), tmp_path / "c", clock, trusted_networks=parse_networks("192.168.0.0/23"))
    assert auth.trusted("192.168.1.5") and auth.trusted("192.168.0.1")
    assert auth.trusted("::ffff:192.168.1.5")  # an IPv4 client on a dual-stack socket
    assert not auth.trusted("192.168.2.1") and not auth.trusted("10.0.0.5") and not auth.trusted("not an address")
    assert not Auth(("admin", "pw"), tmp_path / "c", clock).trusted("192.168.1.5")  # nothing set: the login always

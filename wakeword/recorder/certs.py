"""Self-signed certificate for the recorder, so phones allow the microphone (HTTPS only)."""

from __future__ import annotations

from pathlib import Path
import shutil
import socket
import subprocess


def local_addresses() -> list[str]:
    """This computer's LAN IPv4 addresses (best effort) plus localhost."""
    addresses = {"127.0.0.1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # no packet is sent; picks the outgoing interface
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    return sorted(addresses)


def subject_alt_names(addresses: list[str], hostnames: list[str]) -> str:
    entries = [f"DNS:{h}" for h in dict.fromkeys(["localhost", *hostnames])]
    entries += [f"IP:{a}" for a in dict.fromkeys(addresses)]
    return ",".join(entries)


def make_cert(folder: Path, addresses: list[str] | None = None, days: int = 825) -> tuple[Path, Path]:
    """Create `cert.pem` and `key.pem` in `folder` with openssl (valid for this computer's IPs)."""
    if not shutil.which("openssl"):
        raise RuntimeError("openssl not found")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / "cert.pem", folder / "key.pem"
    hostname = socket.gethostname()
    san = subject_alt_names(addresses or local_addresses(), [hostname, f"{hostname.split('.')[0]}.local"])
    cmd = ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", str(days),
           "-subj", "/CN=wakeword recorder", "-addext", f"subjectAltName={san}",
           "-keyout", str(key), "-out", str(cert)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"openssl failed: {result.stderr.strip()}")
    key.chmod(0o600)
    return cert, key

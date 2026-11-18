"""Web recorder: every person records their takes from a phone or computer browser.

The page asks "who are you?", lists that person's words with progress, tells them how to say each
take (near, far, quiet …) and uploads a 16 kHz mono WAV made in the browser. Phones only give the
microphone to HTTPS pages, so the server can run with a self-signed certificate (``make-cert``).
"""

from .server import make_server, serve

__all__ = ["make_server", "serve"]

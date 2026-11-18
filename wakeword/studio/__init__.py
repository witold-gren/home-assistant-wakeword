"""Wake word studio: the training panel as an editor (Docker on the GPU machine, see docker/)."""

from .server import make_server, serve

__all__ = ["make_server", "serve"]

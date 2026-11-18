"""Language packs: recorder instructions and messages shown to the people recording.

A pack is a module in this package with two dicts:

- ``TAKES``: delivery variant id -> instruction (the variant ids are shared by all languages and
  stored in file names, so a recording says how it was spoken),
- ``UI``: message id -> text (``{word}``, ``{done}``, ``{target}`` … are filled in).

Add a language by copying ``en.py`` to ``<code>.py`` and translating the values; the test suite
checks that every pack has exactly the same keys.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

# Delivery variants in recording order. Each person cycles through them until the target count of
# takes is reached, so a dozen takes already cover distance, loudness, speed and mood.
TAKE_ORDER = (
    "near",
    "far",
    "quiet",
    "loud",
    "fast",
    "slow",
    "question",
    "tired",
    "cheerful",
    "background",
    "other_side",
    "normal",
)

AVAILABLE = ("en", "pl")
DEFAULT = "en"


def get_pack(language: str) -> ModuleType:
    """The pack for `language` (`pl`, `pl-PL`, `pl_PL` …), English when there is none."""
    code = (language or DEFAULT).replace("_", "-").split("-")[0].lower()
    if code not in AVAILABLE:
        code = DEFAULT
    return import_module(f"{__name__}.{code}")


def take_variant(index: int) -> str:
    """Delivery variant of the `index`-th take (0-based) of a person for one word."""
    return TAKE_ORDER[index % len(TAKE_ORDER)]

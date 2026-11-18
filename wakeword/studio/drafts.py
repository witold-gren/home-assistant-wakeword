"""The editor's draft of household.yaml and the history of saved versions.

The draft is the household as data (the same dictionary the training panel edits), kept in
``data/studio/draft.json`` until "Save": nothing changes for training, the recorder or Home Assistant
before that. It remembers which household.yaml it started from, so a file changed meanwhile (``ha-pull``,
another browser) is a conflict instead of being overwritten. Before every save the old file goes to
``data/studio/history/`` (the last ``HISTORY_LIMIT`` versions), from where a version can come back as a draft.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

import yaml

from ..household import HOUSEHOLD_FILE

FOLDER = "data/studio"
HISTORY_LIMIT = 30
VERSION_PATTERN = re.compile(r"^\d{8}-\d{6}-\d{6}$")


class Conflict(Exception):
    """household.yaml changed since the draft started."""


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class Drafts:
    def __init__(self, household_root: Path) -> None:
        self.root = Path(household_root)
        self.folder = self.root / FOLDER
        self.history_folder = self.folder / "history"

    @property
    def _draft_file(self) -> Path:
        return self.folder / "draft.json"

    def saved_text(self) -> str:
        file = self.root / HOUSEHOLD_FILE
        return file.read_text(encoding="utf-8") if file.is_file() else ""

    def load(self) -> dict:
        """The saved file's hash and the draft, if any ({"data", "base", "changed"})."""
        saved = self.saved_text()
        draft = None
        if self._draft_file.is_file():
            stored = json.loads(self._draft_file.read_text(encoding="utf-8"))
            draft = {**stored, "outdated": stored.get("base") != file_hash(saved)}
        return {"hash": file_hash(saved), "draft": draft}

    def save_draft(self, data: dict, base: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        stored = {"data": data, "base": base, "changed": datetime.now().isoformat(timespec="seconds")}
        tmp = self._draft_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._draft_file)

    def discard(self) -> None:
        self._draft_file.unlink(missing_ok=True)

    def check_base(self, base: str, force: bool = False) -> None:
        if not force and base != file_hash(self.saved_text()):
            raise Conflict("household.yaml changed outside the editor since this draft started")

    def remember(self, user: str = "", note: str = "") -> str | None:
        """Keep the current household.yaml in the history (before it is overwritten); its version id."""
        text = self.saved_text()
        if not text:
            return None
        self.history_folder.mkdir(parents=True, exist_ok=True)
        version = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (self.history_folder / f"{version}.yaml").write_text(text, encoding="utf-8")
        (self.history_folder / f"{version}.json").write_text(
            json.dumps({"user": user, "note": note}, ensure_ascii=False), encoding="utf-8")
        for old in self.versions()[HISTORY_LIMIT:]:
            for suffix in (".yaml", ".json"):
                (self.history_folder / f"{old['id']}{suffix}").unlink(missing_ok=True)
        return version

    def versions(self) -> list[dict]:
        """Saved versions, newest first."""
        if not self.history_folder.is_dir():
            return []
        result = []
        for file in sorted(self.history_folder.glob("*.yaml"), reverse=True):
            meta_file = file.with_suffix(".json")
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
            when = datetime.strptime(file.stem, "%Y%m%d-%H%M%S-%f")
            result.append({"id": file.stem, "time": when.isoformat(timespec="seconds"), **meta})
        return result

    def version_text(self, version: str) -> str:
        if not VERSION_PATTERN.match(version) or not (self.history_folder / f"{version}.yaml").is_file():
            raise ValueError("no such version")
        return (self.history_folder / f"{version}.yaml").read_text(encoding="utf-8")

    def version_data(self, version: str) -> dict:
        data = yaml.safe_load(self.version_text(version)) or {}
        if not isinstance(data, dict):
            raise ValueError("this version is not a household")
        return data

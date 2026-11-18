"""The draft of household.yaml and the history of saved versions."""

import pytest

from wakeword.studio.drafts import HISTORY_LIMIT, Conflict, Drafts, file_hash


def test_draft_remembers_its_base_and_sees_an_outside_change(household_dir):
    drafts = Drafts(household_dir)
    loaded = drafts.load()
    assert loaded["draft"] is None and loaded["hash"] == file_hash(drafts.saved_text())
    drafts.save_draft({"speakers": []}, loaded["hash"])
    assert drafts.load()["draft"]["data"] == {"speakers": []} and not drafts.load()["draft"]["outdated"]
    drafts.check_base(loaded["hash"])
    (household_dir / "household.yaml").write_text("ui_language: pl\n", encoding="utf-8")
    assert drafts.load()["draft"]["outdated"]
    with pytest.raises(Conflict):
        drafts.check_base(loaded["hash"])
    drafts.check_base(loaded["hash"], force=True)
    drafts.discard()
    assert drafts.load()["draft"] is None


def test_history_keeps_the_last_versions_newest_first(household_dir):
    drafts = Drafts(household_dir)
    first = drafts.remember("admin", "first")
    assert drafts.versions()[0] == {"id": first, "time": drafts.versions()[0]["time"], "user": "admin", "note": "first"}
    assert drafts.version_text(first) == drafts.saved_text()
    assert drafts.version_data(first)["words"]["robo"]["wake_word"] == "Robo"
    for _ in range(HISTORY_LIMIT + 3):
        drafts.remember()
    versions = drafts.versions()
    assert len(versions) == HISTORY_LIMIT and first not in [v["id"] for v in versions]
    assert [v["id"] for v in versions] == sorted((v["id"] for v in versions), reverse=True)


def test_history_refuses_made_up_versions(household_dir):
    drafts = Drafts(household_dir)
    for wrong in ("../household", "20260101-000000-000000", ""):
        with pytest.raises(ValueError):
            drafts.version_text(wrong)


def test_nothing_to_remember_without_a_household(tmp_path):
    drafts = Drafts(tmp_path)
    assert drafts.remember() is None and drafts.versions() == [] and drafts.saved_text() == ""

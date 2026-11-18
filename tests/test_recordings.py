import pytest

from wakeword.recordings import delete_recordings, list_recordings, recording_path

from wakeword.audio import write_wav

from .conftest import record_takes, utterance


def test_list_recordings(household):
    record_takes(household, "robo", "kid", 2)
    (household.data_dir / "real" / "old_word" / "gone").mkdir(parents=True)
    (household.data_dir / "real" / "old_word" / "gone" / "gone_000_near.wav").write_bytes(b"not audio")
    (household.data_dir / "background").mkdir()
    record = record_takes(household, "robo", "dad", 1)[0]
    record.rename(household.data_dir / "background" / "salon_20261027_1800.wav")

    listing = list_recordings(household.root)

    groups = {(g["word"], g["speaker"]): g["files"] for g in listing["takes"]}
    assert list(groups) == [("old_word", "gone"), ("robo", "kid")]  # empty dad folder is skipped
    kid = groups[("robo", "kid")]
    assert [f["name"] for f in kid] == ["kid_000_normal.wav", "kid_001_normal.wav"]
    assert kid[0]["path"] == "real/robo/kid/kid_000_normal.wav" and kid[0]["variant"] == "normal"
    assert kid[0]["seconds"] > 0 and kid[0]["size"] > 0 and "T" in kid[0]["time"]
    assert groups[("old_word", "gone")][0]["seconds"] is None  # unreadable, still listed
    assert [b["path"] for b in listing["background"]] == ["background/salon_20261027_1800.wav"]


def test_list_recordings_empty(tmp_path):
    assert list_recordings(tmp_path) == {"takes": [], "background": [], "synthetic": [], "elevenlabs": []}


def test_delete_moves_to_backup(household):
    paths = record_takes(household, "robo", "kid", 3)
    backup = delete_recordings(household.root, ["real/robo/kid/kid_000_normal.wav", "real/robo/kid/kid_001_normal.wav"])
    assert backup.parent.name == "backup" and backup.name.startswith("deleted-")
    assert (backup / "real" / "robo" / "kid" / "kid_000_normal.wav").exists()
    assert not paths[0].exists() and paths[2].exists()
    # the last take of a person removes the emptied folders, never data/real itself
    delete_recordings(household.root, ["real/robo/kid/kid_002_normal.wav"])
    assert not (household.data_dir / "real" / "robo").exists() and (household.data_dir / "real").is_dir()


def test_delete_refuses_paths_outside_recordings(household):
    record_takes(household, "robo", "kid", 1)
    (household.root / "household.yaml").read_text()
    for bad in ["../household.yaml", "real/../../household.yaml", "build/x.wav", "real/robo/kid/missing.wav"]:
        with pytest.raises(ValueError):
            recording_path(household.root, bad)
    with pytest.raises(ValueError):  # one bad path - nothing is moved
        delete_recordings(household.root, ["real/robo/kid/kid_000_normal.wav", "../household.yaml"])
    assert (household.data_dir / "real" / "robo" / "kid" / "kid_000_normal.wav").exists()
    with pytest.raises(ValueError, match="nothing"):
        delete_recordings(household.root, [])


def test_synthetic_preview_listed_playable_not_deletable(tmp_path):
    import pytest

    from wakeword.recordings import delete_recordings, list_recordings, recording_path

    folder = tmp_path / "data" / "build" / "hej_jarvis" / "synthetic_preview" / "positive"
    folder.mkdir(parents=True)
    write_wav(folder / "pl_PL-gosia-medium_00_00000.wav", utterance())
    (tmp_path / "data" / "build" / "hej_jarvis" / "trained").mkdir()
    write_wav(tmp_path / "data" / "build" / "hej_jarvis" / "trained" / "other.wav", utterance())
    listed = list_recordings(tmp_path)["synthetic"]
    assert [(g["word"], g["kind"], len(g["files"])) for g in listed] == [("hej_jarvis", "positive", 1)]
    path = listed[0]["files"][0]["path"]
    assert recording_path(tmp_path, path).is_file()
    with pytest.raises(ValueError, match="listening only"):
        delete_recordings(tmp_path, [path])
    with pytest.raises(ValueError, match="not a recording"):  # only the preview folder of build/
        recording_path(tmp_path, "build/hej_jarvis/trained/other.wav")


def test_elevenlabs_takes_listed_by_size_without_opening(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    from wakeword import recordings

    group = tmp_path / "data" / "elevenlabs" / "hej_jarvis" / "bartosz-k9StxIPT_00"
    group.mkdir(parents=True)
    sf.write(group / "00000.wav", np.zeros(11680, dtype=np.float32), 16000, subtype="PCM_16")  # as generate()
    (group / ".00001.wav").write_bytes(b"half-written")
    real = sf.info(str(group / "00000.wav")).duration

    def no_opening(path):
        raise AssertionError(f"opened {path}")

    monkeypatch.setattr(recordings.sf, "info", no_opening)
    listed = list_recordings(tmp_path)["elevenlabs"]
    assert [(g["word"], g["group"], len(g["files"])) for g in listed] == [("hej_jarvis", "bartosz-k9StxIPT_00", 1)]
    assert listed[0]["files"][0]["seconds"] == round(real, 2) == 0.73
    with pytest.raises(ValueError, match="listening only"):
        delete_recordings(tmp_path, [listed[0]["files"][0]["path"]])

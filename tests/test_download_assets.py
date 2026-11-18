"""train/download_assets.py without the network: fake Hugging Face downloads, real zips and markers."""

import importlib.util
from pathlib import Path
import sys
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "download_assets", Path(__file__).parents[1] / "train" / "download_assets.py")
assets_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets_module)


def fake_hub(calls):
    """Stands in for hf_hub_download: makes a small zip with one folder named after the file."""

    def fetch(repo, filename, folder):
        calls.append((repo, filename))
        path = Path(folder) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{Path(filename).stem}/part.npy", b"x")
        return path

    return fetch


def test_negatives_download_extract_and_mark(tmp_path):
    calls = []
    assets_module.negatives(tmp_path, fetch=fake_hub(calls))
    out = tmp_path / "negative_datasets"
    assert [c[1] for c in calls] == assets_module.NEGATIVE_FILES
    assert all(c[0] == assets_module.NEGATIVE_REPO for c in calls)
    for name in ("speech", "dinner_party", "dinner_party_eval", "no_speech"):
        assert (out / name / "part.npy").exists() and (out / f".{name}.complete").exists()
    assert not list(out.glob("*.zip"))  # archives removed after extracting
    calls.clear()
    assets_module.negatives(tmp_path, fetch=fake_hub(calls))
    assert calls == []  # done once, skipped afterwards


def test_negatives_redo_only_what_was_not_finished(tmp_path):
    out = tmp_path / "negative_datasets"
    (out / "speech").mkdir(parents=True)  # extracted half-way, no marker: not trusted
    (out / ".no_speech.complete").touch()
    calls = []
    assets_module.negatives(tmp_path, fetch=fake_hub(calls))
    assert [c[1] for c in calls] == ["dinner_party.zip", "dinner_party_eval.zip", "speech.zip"]


def test_rirs_from_an_older_run_count_as_done(tmp_path):
    out = tmp_path / "mit_rirs"
    out.mkdir()
    for index in range(assets_module.RIRS_COUNT):
        (out / f"{index}.wav").write_bytes(b"")
    assets_module.rirs(tmp_path)  # would need `datasets` if it tried to download
    assert assets_module.is_done(out)


def test_finished_steps_do_not_touch_the_network(tmp_path, monkeypatch):
    for folder in ("mit_rirs", "audioset_16k", "fma_16k"):
        assets_module.mark_done(tmp_path / folder)
    monkeypatch.setitem(sys.modules, "datasets", None)  # importing it would fail
    fail = lambda *a: pytest.fail("downloaded although finished")  # noqa: E731
    assets_module.rirs(tmp_path, fetch=fail)
    assets_module.audioset(tmp_path, fetch=fail)
    assets_module.fma(tmp_path, fetch=fail)


def test_decode_16k_mono(tmp_path):
    pytest.importorskip("scipy")  # training machine only; the Mac toolkit is numpy-only
    import io

    import numpy as np
    import soundfile as sf

    stereo = np.stack([np.sin(np.linspace(0, 100, 44100)), np.zeros(44100)], axis=1) * 0.5
    buffer = io.BytesIO()
    sf.write(buffer, stereo, 44100, format="FLAC")
    samples = assets_module.decode_16k(buffer.getvalue())
    assert samples.ndim == 1 and abs(len(samples) - 16000) <= 1
    assert 0.2 < np.abs(samples).max() < 0.3  # the two channels averaged


def test_audioset_from_parquet_parts(tmp_path, monkeypatch):
    """The AudioSet step with its parquet reading replaced: clips land as 16 kHz WAVs, markers set."""
    pytest.importorskip("scipy")
    import io

    import numpy as np
    import soundfile as sf

    legacy = tmp_path / "audioset" / assets_module.LEGACY_AUDIOSET_TAR
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"")
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(32000), 32000, format="FLAC")
    clips = {"a": buffer.getvalue(), "broken": b"not audio"}
    parts = []
    monkeypatch.setattr(assets_module, "parquet_audio", lambda path: iter(clips.items()))
    monkeypatch.setitem(sys.modules, "tqdm", type(sys)("tqdm"))
    sys.modules["tqdm"].tqdm = lambda it, **k: it
    assets_module.audioset(tmp_path, fetch=lambda repo, name, folder: parts.append(name) or Path(folder) / name)
    out = tmp_path / "audioset_16k"
    assert parts == assets_module.AUDIOSET_PARTS and parts[0] == "data/bal_train/00.parquet"
    assert sf.info(str(out / "a.wav")).samplerate == 16000 and not (out / "broken.wav").exists()
    assert assets_module.is_done(out) and not legacy.exists()

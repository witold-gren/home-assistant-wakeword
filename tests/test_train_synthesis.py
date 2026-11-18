"""train/synth_piper.py and train/synth_preview.py without Piper: fake clips, real files and logs."""

import importlib.util
from pathlib import Path

import numpy as np
import soundfile as sf


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "train" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


synth = load("synth_piper")
preview = load("synth_preview")


def fake_clip(calls):
    def clip(index):
        calls.append(index)
        return np.full(1600, 0.1, dtype=np.float32), 16000

    return clip


def test_settings_cycle_like_the_old_script():
    lengths, noises = [0.8, 0.9, 1.0, 1.1, 1.25], [0.5, 0.667, 0.9]
    assert synth.settings(0, lengths, noises) == (0.8, 0.5)
    assert synth.settings(4, lengths, noises) == (1.25, 0.5)
    assert synth.settings(5, lengths, noises) == (0.8, 0.667)
    assert synth.settings(15, lengths, noises) == (0.8, 0.5)  # all 15 combinations, then again


def test_make_clips_logs_progress_and_marks_done(tmp_path, monkeypatch):
    monkeypatch.setattr(synth, "PROGRESS_EVERY", 4)
    lines, calls = [], []
    out = tmp_path / "pl_PL-gosia-medium_00"
    made = synth.make_clips(out, 10, fake_clip(calls), "[3/27]", "pl_PL-gosia-medium 'hej dżarwis'", lines.append)
    assert made == 10 and calls == list(range(10))
    assert lines[0] == f"[3/27] pl_PL-gosia-medium 'hej dżarwis': making 10 of 10 clips → {out}"
    assert [line.split(",")[0].strip() for line in lines[1:]] == ["[3/27]   4/10 clips", "[3/27]   8/10 clips",
                                                                  "[3/27]   10/10 clips"]
    info = sf.info(str(out / "00009.wav"))
    assert (info.samplerate, info.channels, info.subtype) == (16000, 1, "PCM_16")
    assert (out / ".complete").exists()
    lines.clear()
    assert synth.make_clips(out, 10, fake_clip(calls), "[3/27]", "x", lines.append) == 0
    assert lines == ["[3/27] skip, already complete: x"]


def test_make_clips_resumes_an_interrupted_group(tmp_path):
    out = tmp_path / "group"
    out.mkdir()
    for index in (0, 1, 2, 5):
        sf.write(out / f"{index:05d}.wav", np.zeros(160), 16000)
    (out / ".00006.wav").write_bytes(b"half")  # interrupted while writing
    (out / "raw.wav").write_bytes(b"old")  # left by the old one-process-per-clip script
    (out / "00007.wav").write_bytes(b"RIFF")  # cut short by an interrupted ffmpeg
    lines, calls = [], []
    synth.make_clips(out, 8, fake_clip(calls), "[1/2]", "voice 'text'", lines.append)
    assert calls == [3, 4, 6, 7]
    assert "making 4 of 8 clips (resuming: 4 already there)" in lines[0]
    assert not (out / ".00006.wav").exists() and not (out / "raw.wav").exists()
    assert sorted(p.name for p in out.glob("*.wav")) == [f"{i:05d}.wav" for i in range(8)]


def test_make_clips_marks_a_group_finished_by_the_old_script(tmp_path):
    out = tmp_path / "group"
    out.mkdir()
    for index in range(3):
        sf.write(out / f"{index:05d}.wav", np.zeros(160), 16000)
    lines, calls = [], []
    assert synth.make_clips(out, 3, fake_clip(calls), "[1/1]", "v 't'", lines.append) == 0
    assert calls == [] and lines == ["[1/1] v 't': all 3 clips already there"] and (out / ".complete").exists()


def test_voice_downloaded_only_when_missing(tmp_path, monkeypatch):
    lines = []
    (tmp_path / "pl_PL-gosia-medium.onnx").write_bytes(b"m")
    (tmp_path / "pl_PL-gosia-medium.onnx.json").write_text("{}")
    assert synth.ensure_voice("pl_PL-gosia-medium", tmp_path, lines.append) == tmp_path / "pl_PL-gosia-medium.onnx"
    assert lines == ["voice pl_PL-gosia-medium: already downloaded"]


def test_preview_picks_spread_clips_per_group(tmp_path):
    synthetic = tmp_path / "data" / "synthetic" / "hej_jarvis"
    for kind, group, count in (("positive", "pl_PL-gosia-medium_00", 300), ("negative", "pl_PL-gosia-medium_00", 2)):
        folder = synthetic / kind / group
        folder.mkdir(parents=True)
        for index in range(count):
            (folder / f"{index:05d}.wav").write_bytes(b"x")
        (folder / ".00999.wav").write_bytes(b"half")
    (tmp_path / "data" / "build" / "hej_jarvis").mkdir(parents=True)
    (synthetic.parent / "removed_word" / "positive" / "g").mkdir(parents=True)  # not prepared: ignored
    assert preview.make_preview(tmp_path, per_group=3) == {"hej_jarvis": 5}
    target = tmp_path / "data" / "build" / "hej_jarvis" / "synthetic_preview"
    assert sorted(p.name for p in (target / "positive").iterdir()) == [
        "pl_PL-gosia-medium_00_00000.wav", "pl_PL-gosia-medium_00_00100.wav", "pl_PL-gosia-medium_00_00200.wav"]
    assert len(list((target / "negative").iterdir())) == 2
    assert not (tmp_path / "data" / "build" / "removed_word").exists()


def test_group_made_again_when_its_text_changed(tmp_path):
    out = tmp_path / "group"
    lines, calls = [], []
    assert synth.make_clips(out, 2, fake_clip(calls), "[1/1]", "v 'hej dżarwis'", lines.append, "hej dżarwis") == 2
    assert (out / ".complete").read_text(encoding="utf-8") == "hej dżarwis"
    assert synth.make_clips(out, 2, fake_clip(calls), "[1/1]", "v", lines.append, "hej dżarwis") == 0
    assert synth.make_clips(out, 2, fake_clip(calls), "[1/1]", "v 'hej dżarwys'", lines.append, "hej dżarwys") == 2
    assert "[1/1] the text changed, making the group again: v 'hej dżarwys'" in lines
    assert (out / ".complete").read_text(encoding="utf-8") == "hej dżarwys" and calls == [0, 1, 0, 1]
    (out / ".complete").write_text("")  # from before the text was kept: trusted
    assert synth.is_complete(out, "anything")


def test_voice_from_a_hugging_face_repository(tmp_path, monkeypatch):
    import sys
    import types

    fetched = []

    def hf_hub_download(repo, filename, local_dir):
        fetched.append((repo, filename))
        (Path(local_dir) / filename).write_text("x")

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=hf_hub_download))
    lines = []
    voice = "WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium"
    model = synth.ensure_voice(voice, tmp_path / "voices", lines.append)
    assert model == tmp_path / "voices" / "pl_PL-meski_wg_glos-medium.onnx" and model.is_file()
    assert fetched == [("WitoldG/polish_piper_models", "pl_PL-meski_wg_glos-medium.onnx.json"),
                       ("WitoldG/polish_piper_models", "pl_PL-meski_wg_glos-medium.onnx")]
    assert lines == [f"voice pl_PL-meski_wg_glos-medium: downloading from huggingface.co/WitoldG/polish_piper_models "
                     f"to {tmp_path / 'voices'}"]
    assert synth.ensure_voice(voice, tmp_path / "voices", lines.append) == model and len(fetched) == 2

"""ElevenLabs takes of the word, with a pretend API (no key, no characters used)."""

import json
from types import SimpleNamespace as NS

import numpy as np
import pytest
import soundfile as sf

from wakeword import elevenlabs
from wakeword.household import HouseholdError, parse_household


@pytest.fixture(autouse=True)
def no_real_key(tmp_path, monkeypatch):
    monkeypatch.setattr(elevenlabs, "KEY_FILE", tmp_path / "config" / "elevenlabs.json")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


class FakeApi:
    """Two pages of library voices, one own voice, speech = a short tone per request."""

    def __init__(self):
        self.spoken = []
        self.voices = NS(get_shared=self.get_shared, search=self.search, share=self.share)
        self.text_to_speech = NS(convert=self.convert)

    def get_shared(self, language, page_size, page):
        # voice 0: an English voice verified in the language, voice 1: a native speaker
        voices = [NS(voice_id=f"lib{page}voice{i}xx", public_owner_id=f"owner{i}", name=f"Lib {page}-{i}",
                     gender="female", age="young", accent="standard", description="calm", descriptive="",
                     preview_url=f"https://x/{page}{i}.mp3", is_added_by_user=False, language=("en", language)[i],
                     verified_languages=[
                         NS(language=language, model_id="eleven_v3", preview_url=f"https://x/v3{language}{page}{i}.mp3"),
                         NS(language=language, model_id="eleven_multilingual_v2",
                            preview_url=f"https://x/{language}{page}{i}.mp3")])
                  for i in range(2)]
        return NS(voices=voices, has_more=page == 0)

    def search(self, page_size, next_page_token):
        return NS(voices=[NS(voice_id="ownvoice0001", name="Tomek clone", category="cloned",
                             labels={"gender": "male", "language": "en"},
                             description="my voice", preview_url=None, verified_languages=None)],
                  has_more=False, next_page_token=None)

    def share(self, owner, voice_id, new_name):
        self.shared = (owner, voice_id, new_name)
        return NS(voice_id=voice_id)

    def convert(self, voice_id, **kwargs):
        self.spoken.append((voice_id, kwargs))
        tone = (0.3 * np.sin(np.linspace(0, 200, 8000)) * 32767).astype("<i2").tobytes()
        return iter([tone[:5000], tone[5000:]])


def make_household(household_data, tmp_path, voices=None, count=3):
    household_data["words"]["robo"]["spellings"] = {"pl": ["hej robo", "hej robbo"]}
    household_data["elevenlabs"] = {"model": "eleven_multilingual_v2", "count": count, "voices": voices if voices
                                    is not None else [{"id": "ownvoice0001", "name": "Tomek clone", "language": "pl"}]}
    return parse_household(household_data, tmp_path)


def test_key_kept_outside_the_household_and_only_for_its_owner(tmp_path, monkeypatch):
    assert elevenlabs.load_key() == ""
    elevenlabs.save_key("sk_" + "a" * 40)
    assert elevenlabs.load_key() == "sk_" + "a" * 40
    assert elevenlabs.KEY_FILE.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="does not look like") as err:
        elevenlabs.save_key("short")
    assert "short" not in str(err.value)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_from_env_0123456789")
    assert elevenlabs.load_key() == "sk_from_env_0123456789"
    elevenlabs.save_key("")
    assert not elevenlabs.KEY_FILE.exists()


def test_sync_lists_own_voices_then_the_library_of_the_language(household_data, tmp_path):
    household = make_household(household_data, tmp_path)
    voices = elevenlabs.sync_voices(household, "pl", api=FakeApi())
    # native speakers first, then voices verified in Polish, then an own English voice that is not
    assert [v["id"] for v in voices] == ["lib0voice1xx", "lib1voice1xx", "lib0voice0xx", "lib1voice0xx", "ownvoice0001"]
    assert [(v["native"], v["speaks"]) for v in voices] == [("pl", True)] * 2 + [("en", True)] * 2 + [("en", False)]
    english = voices[2]
    assert english["source"] == "library" and english["owner"] == "owner0"
    assert english["preview"] == "https://x/pl00.mp3"  # the Polish preview, from multilingual v2
    assert voices[-1]["source"] == "own" and voices[-1]["preview"] is None
    assert elevenlabs.cached_voices(household, "pl") == voices
    with pytest.raises(ValueError, match="language"):
        elevenlabs.sync_voices(household, "polish", api=FakeApi())


def test_api_errors_are_explained_without_the_request():
    error = Exception("boom")
    error.status_code, error.body = 401, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}
    assert elevenlabs.explain(error) == "ElevenLabs 401: Invalid API key"


def test_speak_returns_16k_samples_with_the_variant(household_data, tmp_path):
    api = FakeApi()
    quiet = elevenlabs.speak(api, "v1abcdefgh", "hej robo", "eleven_multilingual_v2", elevenlabs.Variant(0.9, 0.3, 0.2, -10), 1)
    normal = elevenlabs.speak(api, "v1abcdefgh", "hej robo", "eleven_v3", elevenlabs.VARIANTS[0], 2, language="pl")
    assert quiet.size == normal.size == 8000 and np.max(np.abs(quiet)) < np.max(np.abs(normal)) / 2
    first, second = api.spoken[0][1], api.spoken[1][1]
    assert first["output_format"] == "pcm_16000" and "language_code" not in first  # refused by multilingual v2
    assert second["language_code"] == "pl" and first["voice_settings"].speed == 0.9


def test_generate_makes_takes_resumes_and_redoes_changed_texts(household_data, tmp_path):
    household = make_household(household_data, tmp_path)
    api, lines = FakeApi(), []
    assert elevenlabs.estimate(household, "robo") == {"groups": 2, "takes": 6, "characters": (8 + 9) * 3}
    assert elevenlabs.generate(household, "robo", api=api, log=lines.append) == 6
    group = household.data_dir / "elevenlabs" / "robo" / "tomek_clone-ownvoice_00"
    assert sorted(p.name for p in group.glob("*.wav")) == ["00000.wav", "00001.wav", "00002.wav"]
    assert sf.info(group / "00000.wav").samplerate == 16000
    assert (group / ".complete").read_text() == "eleven_multilingual_v2|3|hej robo"
    # every take of a group differs (speed of VARIANTS 0, 1, 2)
    assert {k["seed"]: k["voice_settings"].speed for _, k in api.spoken} == {1: 1.0, 2: 0.85, 3: 1.15}
    assert elevenlabs.generate(household, "robo", api=api, log=lines.append) == 0
    assert "(0 to make, 2 already complete)" in lines[-2]

    (group / "00001.wav").unlink()
    (group / ".complete").unlink()  # interrupted: only the missing take
    assert elevenlabs.generate(household, "robo", api=api, log=lines.append) == 1

    household_data["words"]["robo"]["spellings"] = {"pl": ["hej robot", "hej robbo"]}
    household = parse_household(household_data, tmp_path)
    assert elevenlabs.generate(household, "robo", api=api, log=lines.append) == 3  # the changed text only


def test_voices_no_longer_chosen_move_to_backup(household_data, tmp_path):
    household = make_household(household_data, tmp_path)
    elevenlabs.generate(household, "robo", api=FakeApi(), log=lambda line: None)
    household = make_household(household_data, tmp_path, voices=[
        {"id": "lib0voice0xx", "name": "Lib 0-0", "language": "pl", "owner": "owner0"}])
    lines = []
    elevenlabs.generate(household, "robo", api=FakeApi(), log=lines.append)
    assert any("no longer chosen" in line for line in lines)
    names = sorted(p.name for p in (household.data_dir / "elevenlabs" / "robo").iterdir() if p.is_dir())
    assert names == ["lib_0_0-lib0voic_00", "lib_0_0-lib0voic_01"]
    assert list((household.data_dir / "backup").glob("elevenlabs-*/robo/tomek_clone-ownvoice_00"))


def test_nothing_chosen_for_the_word_language(household_data, tmp_path):
    household = make_household(household_data, tmp_path, voices=[{"id": "enuservoice1", "name": "En", "language": "en"}])
    lines = []
    assert elevenlabs.generate(household, "robo", api=FakeApi(), log=lines.append) == 0
    assert "no ElevenLabs voices chosen" in lines[0]


def test_add_library_voice_to_the_account():
    api = FakeApi()
    elevenlabs.add_to_account({"id": "lib0voice0xx", "owner": "owner0", "name": "Lib 0-0"}, api=api)
    assert api.shared == ("owner0", "lib0voice0xx", "Lib 0-0")


def test_household_section_is_checked_and_saved_only_when_used(household_data, tmp_path):
    from wakeword.scaffold import read_raw, save_raw

    household_data["elevenlabs"] = {"voices": [{"id": "x", "language": "pl"}]}
    with pytest.raises(HouseholdError, match="voice id"):
        parse_household(household_data, tmp_path)
    household_data["elevenlabs"] = {"count": 99}
    with pytest.raises(HouseholdError, match="1-50"):
        parse_household(household_data, tmp_path)
    household_data["elevenlabs"] = {"model": "eleven_multilingual_v2", "count": 5, "voices": []}
    save_raw(tmp_path, household_data)
    assert "elevenlabs" not in (tmp_path / "household.yaml").read_text()  # the defaults are not written
    household_data["elevenlabs"]["voices"] = [{"id": "ownvoice0001", "name": "Tomek clone", "language": "pl"}]
    saved = save_raw(tmp_path, household_data)
    assert saved.elevenlabs["voices"][0]["id"] == "ownvoice0001"
    assert read_raw(tmp_path)["elevenlabs"]["voices"][0]["name"] == "Tomek clone"


def test_training_config_uses_the_takes(household_data, tmp_path):
    from wakeword.training_config import feature_sets

    household = make_household(household_data, tmp_path)
    for word in household.words:
        folder = household.data_dir / "elevenlabs" / word / "v-12345678_00"
        folder.mkdir(parents=True)
    split = household.data_dir / "splits"
    split.mkdir(parents=True)
    word = next(iter(household.words))
    take = household.real_dir(word, next(iter(household.speakers))) / "a.wav"
    take.parent.mkdir(parents=True)
    sf.write(take, np.zeros(1600), 16000)
    (split / f"{word}.csv").write_text(f"path,word,speaker,group,split\n{take.relative_to(household.root)},{word},x,adult,train\n")
    sets = {s.name: s for s in feature_sets(household, word)}
    assert sets["elevenlabs"].truth and sets["elevenlabs"].sources == [f"data/elevenlabs/{word}"]
    others = [w for w in household.words if w != word]
    assert all(f"data/elevenlabs/{other}" in sets["other_words"].sources for other in others)


def test_cached_voices_file_is_plain_data(household_data, tmp_path):
    household = make_household(household_data, tmp_path)
    elevenlabs.sync_voices(household, "pl", api=FakeApi())
    text = elevenlabs.voices_file(household, "pl").read_text()
    assert "sk_" not in text and json.loads(text)[-1]["name"] == "Tomek clone"


def test_the_plan_is_read_or_learnt_from_a_refusal(household_data, tmp_path):
    household = make_household(household_data, tmp_path)
    assert elevenlabs.account(household) == {}
    voices = elevenlabs.sync_voices(household, "pl", api=FakeApi())  # the key may not read the plan
    assert elevenlabs.account(household) == {}
    assert {v["category"] for v in voices} == {"library", "cloned"}

    refusal = RuntimeError("ElevenLabs 402: Free users cannot use library voices via the API. Please upgrade")
    elevenlabs.learn_from(household, RuntimeError("ElevenLabs 500: busy"))
    assert elevenlabs.account(household) == {}
    elevenlabs.learn_from(household, refusal)
    assert elevenlabs.account(household) == {"tier": "free"}

    api = FakeApi()
    api.user = NS(subscription=NS(get=lambda: NS(tier="starter", character_count=1200, character_limit=30000)))
    elevenlabs.sync_voices(household, "pl", api=api)
    assert elevenlabs.account(household) == {"tier": "starter", "used": 1200, "limit": 30000}


def test_generate_learns_the_free_plan(household_data, tmp_path):
    household = make_household(household_data, tmp_path)
    api = FakeApi()

    def refuse(voice_id, **kwargs):
        error = Exception("refused")
        error.status_code, error.body = 402, {"detail": {"message": "Free users cannot use library voices via the API."}}
        raise error

    api.text_to_speech = NS(convert=refuse)
    with pytest.raises(RuntimeError, match="Free users"):
        elevenlabs.generate(household, "robo", api=api, log=lambda line: None)
    assert elevenlabs.account(household)["tier"] == "free"


def test_busy_service_is_asked_again(monkeypatch):
    api, waits, calls = FakeApi(), [], []
    original = api.convert

    def busy_twice(voice_id, **kwargs):
        calls.append(voice_id)
        if len(calls) <= 2:
            error = Exception("busy")
            error.status_code, error.body = 429, {"detail": {"message": "too_many_concurrent_requests"}}
            raise error
        return original(voice_id, **kwargs)

    api.text_to_speech = NS(convert=busy_twice)
    monkeypatch.setattr(elevenlabs.time, "sleep", waits.append)
    samples = elevenlabs.speak(api, "v1abcdefgh", "hej robo", "eleven_multilingual_v2", elevenlabs.VARIANTS[0], 1)
    assert samples.size == 8000 and waits == [2, 5] and len(calls) == 3

    def refused(voice_id, **kwargs):  # not worth asking again
        error = Exception("no")
        error.status_code, error.body = 401, {"detail": {"message": "Invalid API key"}}
        raise error

    api.text_to_speech = NS(convert=refused)
    with pytest.raises(RuntimeError, match="401"):
        elevenlabs.speak(api, "v1abcdefgh", "hej robo", "eleven_multilingual_v2", elevenlabs.VARIANTS[0], 1)
    assert waits == [2, 5]


def test_many_takes_are_augmented_fewer_times(household_data, tmp_path):
    from wakeword.training_config import feature_sets

    household = make_household(household_data, tmp_path)
    word = "robo"
    split = household.data_dir / "splits"
    split.mkdir(parents=True)
    take = household.real_dir(word, next(iter(household.speakers))) / "a.wav"
    take.parent.mkdir(parents=True)
    sf.write(take, np.zeros(1600), 16000)
    (split / f"{word}.csv").write_text(f"path,word,speaker,group,split\n{take.relative_to(household.root)},{word},x,adult,train\n")

    def repeat_with(takes: int) -> int:
        folder = household.data_dir / "elevenlabs" / word / "v-12345678_00"
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.wav"):
            old.unlink()
        for i in range(takes):
            (folder / f"{i:05d}.wav").write_bytes(b"")
        return {s.name: s for s in feature_sets(household, word)}["elevenlabs"].repeat

    assert repeat_with(300) == 10 and repeat_with(4000) == 5 and repeat_with(15000) == 2


def test_voice_being_added_to_the_account_is_asked_again(monkeypatch):
    api, waits, calls = FakeApi(), [], []
    original = api.convert

    def adding_once(voice_id, **kwargs):
        calls.append(voice_id)
        if len(calls) == 1:
            error = Exception("conflict")
            error.status_code, error.body = 409, {"detail": {"message": "Multiple voice additions/deletions for the same voice were called at the same time. Please retry shortly."}}
            raise error
        return original(voice_id, **kwargs)

    api.text_to_speech = NS(convert=adding_once)
    monkeypatch.setattr(elevenlabs.time, "sleep", waits.append)
    samples = elevenlabs.speak(api, "lib0voice1xx", "hej robo", "eleven_multilingual_v2", elevenlabs.VARIANTS[0], 1)
    assert samples.size == 8000 and waits == [2] and len(calls) == 2


def test_takes_go_to_the_voices_in_turn():
    tasks = [({"id": voice}, take) for voice, takes in (("a", 3), ("b", 1), ("c", 2)) for take in range(takes)]
    assert [(t[0]["id"], t[1]) for t in elevenlabs.interleave(tasks)] == [
        ("a", 0), ("b", 0), ("c", 0), ("a", 1), ("c", 1), ("a", 2)]
    assert elevenlabs.interleave([]) == []


def test_generate_asks_different_voices_one_after_another(household_data, tmp_path, monkeypatch):
    voices = [{"id": f"lib0voice{i}xx", "name": f"Lib {i}", "language": "pl"} for i in range(3)]
    household = make_household(household_data, tmp_path, voices=voices, count=2)
    monkeypatch.setattr(elevenlabs, "CONCURRENCY", 1)  # the order of requests is the order of tasks
    api = FakeApi()
    assert elevenlabs.generate(household, "robo", api=api, log=lambda line: None) == 12
    first = [voice for voice, _ in api.spoken[:3]]
    assert sorted(first) == [v["id"] for v in voices]


def not_fine_tuned(api, bad_id):
    original = api.convert

    def convert(voice_id, **kwargs):
        if voice_id == bad_id:
            error = Exception("refused")
            error.status_code, error.body = 400, {"detail": {"message": f"Voice '{bad_id}' is not fine-tuned and cannot be used."}}
            raise error
        return original(voice_id, **kwargs)

    api.text_to_speech = NS(convert=convert)
    return api


def test_a_refused_voice_is_skipped_and_remembered(household_data, tmp_path):
    voices = [{"id": f"lib0voice{i}xx", "name": f"Lib {i}", "language": "pl"} for i in range(3)]
    household = make_household(household_data, tmp_path, voices=voices, count=2)
    lines = []
    api = not_fine_tuned(FakeApi(), "lib0voice1xx")
    assert elevenlabs.generate(household, "robo", api=api, log=lines.append) == 8  # 2 voices × 2 spellings × 2
    base = household.data_dir / "elevenlabs" / "robo"
    # the refused voice leaves no (empty) groups behind: nothing of it goes to training
    assert sorted(p.name for p in base.iterdir() if p.is_dir()) == ["lib_0-lib0voic_00", "lib_0-lib0voic_01",
                                                      "lib_2-lib0voic_00", "lib_2-lib0voic_01"]
    assert elevenlabs.broken_voices(household)["lib0voice1xx"]["name"] == "Lib 1"
    assert "not fine-tuned" in elevenlabs.broken_voices(household)["lib0voice1xx"]["reason"]
    assert any("voices with takes: 2 of 3 chosen, 1 skipped" in line for line in lines)
    assert any("1 voices skipped" in line for line in lines) and any("Lib 1: ElevenLabs 400" in line for line in lines)
    # the next run does not ask for it again and the estimate leaves it out
    api, lines = FakeApi(), []
    assert elevenlabs.generate(household, "robo", api=api, log=lines.append) == 0
    assert api.spoken == [] and any("refused this voice before: Lib 1" in line for line in lines)
    assert elevenlabs.estimate(household, "robo")["groups"] == 4
    # a voice that speaks again (e.g. fine-tuned since) is not broken any more
    elevenlabs.learn_paid(household, "lib0voice1xx", "pl")
    assert elevenlabs.broken_voices(household) == {}


def test_only_refusals_of_a_voice_skip_it():
    def refusal(status, message):
        return elevenlabs.ApiError(f"ElevenLabs {status}: {message}", status)

    assert elevenlabs.voice_refused(refusal(400, "Voice 'x' is not fine-tuned and cannot be used."))
    assert elevenlabs.voice_refused(refusal(404, "voice_not_found"))
    assert not elevenlabs.voice_refused(refusal(400, "text is too long"))
    assert not elevenlabs.voice_refused(refusal(401, "Invalid API key"))
    assert not elevenlabs.voice_refused(RuntimeError("Voice 'x' is not fine-tuned"))  # no status


def test_a_refusal_of_the_key_still_stops(household_data, tmp_path):
    voices = [{"id": f"lib0voice{i}xx", "name": f"Lib {i}", "language": "pl"} for i in range(2)]
    household = make_household(household_data, tmp_path, voices=voices, count=1)
    api = FakeApi()

    def refuse(voice_id, **kwargs):
        error = Exception("no")
        error.status_code, error.body = 401, {"detail": {"message": "Invalid API key"}}
        raise error

    api.text_to_speech = NS(convert=refuse)
    with pytest.raises(RuntimeError, match="401"):
        elevenlabs.generate(household, "robo", api=api, log=lambda line: None)
    assert elevenlabs.broken_voices(household) == {}


def test_generate_keeps_the_list_of_takes_for_the_panel(household_data, tmp_path, monkeypatch):
    from wakeword import recordings

    household = make_household(household_data, tmp_path, count=2)
    elevenlabs.generate(household, "robo", api=FakeApi(), log=lambda line: None)
    base = household.data_dir / "elevenlabs" / "robo"
    index = recordings.read_index(base)
    assert sorted(index) == sorted(p.name for p in base.iterdir() if p.is_dir())
    assert all(takes == {"00000.wav": 0.5, "00001.wav": 0.5} for takes in index.values())  # 8000 samples
    # the panel reads that one file, not every folder and take
    monkeypatch.setattr(recordings, "scan_group", lambda group: pytest.fail(f"scanned {group}"))
    listed = recordings.list_recordings(household.root)["elevenlabs"]
    assert [len(g["files"]) for g in listed] == [2, 2] and listed[0]["files"][0]["seconds"] == 0.5


def test_an_interrupted_run_lists_the_takes_made_so_far(household_data, tmp_path, monkeypatch):
    from wakeword import recordings

    household = make_household(household_data, tmp_path, count=4)
    api, calls = FakeApi(), []
    original = api.convert

    def key_dies(voice_id, **kwargs):
        calls.append(voice_id)
        if len(calls) > 3:
            error = Exception("no")
            error.status_code, error.body = 401, {"detail": {"message": "Invalid API key"}}
            raise error
        return original(voice_id, **kwargs)

    api.text_to_speech = NS(convert=key_dies)
    monkeypatch.setattr(elevenlabs, "CONCURRENCY", 1)  # exactly 3 takes before the refusal
    with pytest.raises(RuntimeError, match="401"):
        elevenlabs.generate(household, "robo", api=api, log=lambda line: None)
    index = recordings.read_index(household.data_dir / "elevenlabs" / "robo")
    assert sum(len(takes) for takes in index.values()) == 3


def test_takes_changed_by_hand_are_listed_again(household_data, tmp_path):
    import shutil

    from wakeword import recordings

    household = make_household(household_data, tmp_path, count=1)
    elevenlabs.generate(household, "robo", api=FakeApi(), log=lambda line: None)
    base = household.data_dir / "elevenlabs" / "robo"
    gone = sorted(p for p in base.iterdir() if p.is_dir())[0]
    shutil.rmtree(gone)  # e.g. removed in Finder
    listed = recordings.list_recordings(household.root)["elevenlabs"]
    assert gone.name not in [g["group"] for g in listed] and len(listed) == 1
    assert sorted(recordings.read_index(base)) == [g["group"] for g in listed]


def test_takes_of_a_removed_language_leave_training_without_the_api(household_data, tmp_path):
    """Prepare (cmd_config) runs drop_stale: no key needed, also when no voice is left for the word."""
    household = make_household(household_data, tmp_path)
    elevenlabs.generate(household, "robo", api=FakeApi(), log=lambda line: None)
    make_household(household_data, tmp_path)
    household_data["words"]["robo"]["spellings"] = {"en": ["hey robo"]}  # the Polish spelling removed
    household = parse_household(household_data, tmp_path)
    lines = []
    moved = elevenlabs.drop_stale(household, "robo", log=lines.append)
    assert [p.name for p in moved] == ["tomek_clone-ownvoice_00", "tomek_clone-ownvoice_01"]
    assert not [p for p in (household.data_dir / "elevenlabs" / "robo").iterdir() if p.is_dir()]
    assert "moved to data/backup" in lines[0]

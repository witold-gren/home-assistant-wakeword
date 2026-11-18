from importlib import import_module

import pytest

from wakeword import languages


@pytest.mark.parametrize("code", languages.AVAILABLE)
def test_packs_have_the_same_keys(code):
    pack = import_module(f"wakeword.languages.{code}")
    reference = import_module("wakeword.languages.en")
    assert set(pack.TAKES) == set(reference.TAKES) == set(languages.TAKE_ORDER)
    assert set(pack.UI) == set(reference.UI)
    assert set(pack.TRAINER) == set(reference.TRAINER)
    assert set(pack.TRAINER_HELP) == set(reference.TRAINER_HELP)
    assert all(text.strip() for text in [*pack.TAKES.values(), *pack.UI.values()])


@pytest.mark.parametrize("code", languages.AVAILABLE)
def test_placeholders_match(code):
    import string

    pack = import_module(f"wakeword.languages.{code}")
    reference = import_module("wakeword.languages.en")

    def fields(text):
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    for key, text in pack.UI.items():
        assert fields(text) == fields(reference.UI[key]), key
    for key, text in pack.TRAINER.items():
        assert fields(text) == fields(reference.TRAINER[key]), key


@pytest.mark.parametrize(
    "language, expected",
    [("pl", "pl"), ("pl-PL", "pl"), ("pl_PL", "pl"), ("EN", "en"), ("de", "en"), ("", "en"), (None, "en")],
)
def test_get_pack(language, expected):
    assert languages.get_pack(language).__name__.endswith(f".{expected}")


def test_take_variant_cycles():
    n = len(languages.TAKE_ORDER)
    assert languages.take_variant(0) == "near"
    assert languages.take_variant(n) == "near"
    assert languages.take_variant(n + 1) == languages.TAKE_ORDER[1]

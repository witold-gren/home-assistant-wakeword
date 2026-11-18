# 05. Dane syntetyczne {#synthetic-data}

[← Augmentacja i negatywy](04-augmentation-and-negatives.md) · [Spis treści](index.md) · [Dalej: trening →](06-training.md)

Nawet z rozmnożeniem macie kilka głosów. Model musi też rozpoznać gościa, babcię, kolegę syna —
dlatego dochodzą tysiące wypowiedzi z syntezatora mowy. Akcent i tak pochodzi z danych, więc
łączymy trzy źródła:

| Źródło | Narzędzie | Co daje |
|---|---|---|
| Angielskie pisownie (`spellings.en`) | **piper-sample-generator** z modelem LibriTTS-R (~900 mówców, mieszanie głosów) | ogromna różnorodność głosów |
| Pozostałe języki (`spellings.pl`, …) | zwykłe głosy **Piper** danego języka (np. `pl_PL-gosia-medium`, `pl_PL-darkman-medium`, `pl_PL-mc_speech-medium`) czytające zapis fonetyczny | **polski akcent** — tak mówi się to słowo w Waszym domu |
| `sound_alikes` | jw., w pierwszym języku słowa i po angielsku | trudne negatywy |

Każdy głos Piper jest uruchamiany wiele razy z różną szybkością (`length_scale` 0,8–1,25) i
losowością (`noise_scale` 0,5–0,9) — każde uruchomienie to inne ujęcie.

## Skrypt dla maszyny treningowej {#script-for-the-training-machine}

Na Macu nic nie jest generowane. `synthetic` pisze skrypt, który uruchomi `train/train.sh`:

```bash
wakeword -H households/dom synthetic --all
```

```
dzarwis: households/dom/data/build/dzarwis/synthetic.sh
 en generator negative    2000
 en generator positive   20000
 en piper     negative    1600
 en piper     positive    2400
 pl piper     negative    1200
 pl piper     positive    2700
```

Opcje:

| Opcja | Domyślnie | Znaczenie |
|---|---|---|
| `--positives` | 20000 | wypowiedzi z angielskiego generatora na słowo (dzielone między pisownie) |
| `--per-voice` | 300 | wypowiedzi na tekst i głos Piper |
| `--negatives` | 4000 | wypowiedzi `sound_alikes` łącznie |
| `--voice pl=pl_PL-…` | — | własne głosy dla języka (można powtarzać) |

Głosy dla języków są w `wakeword/synthetic.py` (`PIPER_VOICES`: en, pl, de, es, fr, it, nl, cs,
uk). Język, którego tam nie ma, podajesz przez `--voice`. Lista głosów:
<https://huggingface.co/rhasspy/piper-voices>.

## Słowo w obcym języku z polskim akcentem {#a-foreign-word-with-your-accent}

Dla „Optimus Prime” (`trained_languages: [en]`) najwięcej danych da angielski generator — ale to
głosy anglojęzyczne. Dlatego koniecznie dodaj `spellings.pl: [optimus prajm]`: polskie głosy
przeczytają to tak, jak mówi syn. Do tego nagrania domowników z najwyższą wagą — i model słyszy
słowo z Waszym akcentem, a nie tylko z amerykańskim.

## Słowo polskie {#a-word-in-your-own-language}

Dla „Dżarwis” czy „Wajana” główne źródło to polskie głosy, a angielski generator z pisownią
`jarvis`/`vaiana` dokłada różnorodność barwy. Polskich głosów Piper jest tylko kilka — to kolejny
powód, dla którego nagrania i rozmnożenie głosów domowników są tak ważne.

## Po zmianie pisowni lub `sound_alikes` {#after-changing-spellings-or-sound-alikes}

`synthetic.sh` pomija foldery, które już zawierają pliki (żeby przerwane generowanie dało się
wznowić). Jeśli zmienisz `spellings` lub `sound_alikes` słowa, usuń na maszynie treningowej
`data/synthetic/<słowo>/` przed ponownym uruchomieniem `train.sh`.

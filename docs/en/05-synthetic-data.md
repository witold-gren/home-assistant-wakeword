# 05. Synthetic data {#synthetic-data}

[← Augmentation and negatives](04-augmentation-and-negatives.md) · [Contents](index.md) · [Next: training →](06-training.md)

Even with expansion you only have a few voices. The model also has to recognise a guest, grandma,
the son's friend — so thousands of utterances from a speech synthesiser are added. The accent
still comes from the data, so we combine three sources:

| Source | Tool | What it gives |
|---|---|---|
| English spellings (`spellings.en`) | **piper-sample-generator** with the LibriTTS-R model (~900 speakers, voice mixing) | huge voice variety |
| Other languages (`spellings.pl`, …) | regular **Piper** voices of that language (e.g. `pl_PL-gosia-medium`, `pl_PL-darkman-medium`, `pl_PL-mc_speech-medium`) reading the phonetic spelling | **your accent** — the way the word is said in your home |
| `sound_alikes` | as above, in the word's first language and in English | hard negatives |

Each Piper voice is run many times with a different speed (`length_scale` 0.8–1.25) and
randomness (`noise_scale` 0.5–0.9) — every run is a different take.

## Script for the training machine {#script-for-the-training-machine}

Nothing is generated on the Mac. `synthetic` writes a script that `train/train.sh` will run:

```bash
wakeword -H households/home synthetic --all
```

```
dzarwis: households/home/data/build/dzarwis/synthetic.sh
 en generator negative    2000
 en generator positive   20000
 en piper     negative    1600
 en piper     positive    2400
 pl piper     negative    1200
 pl piper     positive    2700
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--positives` | 20000 | utterances from the English generator per word (shared between spellings) |
| `--per-voice` | 300 | utterances per text and Piper voice |
| `--negatives` | 4000 | `sound_alikes` utterances in total |
| `--voice pl=pl_PL-…` | — | your own voices for a language (can be repeated) |

The voices for each language are in `wakeword/synthetic.py` (`PIPER_VOICES`: en, pl, de, es, fr,
it, nl, cs, uk). A language that isn't listed there is given with `--voice`. Voice list:
<https://huggingface.co/rhasspy/piper-voices>.

## A foreign word with your accent {#a-foreign-word-with-your-accent}

The idea works for any language: native-language voices reading a phonetic spelling in that
language reproduce how a native speaker says the word. Polish is the worked example here.

For "Optimus Prime" (`trained_languages: [en]`) the English generator provides the most data — but
those are English-speaking voices. So be sure to add `spellings.pl: [optimus prajm]`: the Polish
voices will read it the way the son says it. Add the household recordings with the highest weight
— and the model hears the word with your accent, not only with an American one.

## A word in your own language {#a-word-in-your-own-language}

For "Dżarwis" or "Wajana" the main source is the Polish voices, and the English generator with the
spelling `jarvis`/`vaiana` adds variety of timbre. There are only a few Polish Piper voices (many
languages have just a handful) — one more reason why the household recordings and voice expansion
matter so much.

## After changing spellings or `sound_alikes` {#after-changing-spellings-or-sound-alikes}

`synthetic.sh` skips folders that already contain files (so an interrupted generation can be
resumed). If you change a word's `spellings` or `sound_alikes`, delete `data/synthetic/<word>/` on
the training machine before running `train.sh` again.

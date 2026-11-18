# 00. How it works {#how-it-works}

[← Contents](index.md) · [Next: what you need →](01-what-you-need.md)

## The wake word in Home Assistant Voice {#the-wake-word-in-home-assistant-voice}

The Home Assistant Voice Preview Edition (and other ESPHome devices with `micro_wake_word`) listens
to its microphone all the time, but **sends nothing** to Home Assistant until it hears the wake
word. It listens for it with a small neural network model (**microWakeWord**) running directly on
the ESP32-S3 chip:

1. every 10 ms, 40 features are computed from the audio (a mel-scale spectrum),
2. every 30 ms, the model returns the **probability** that the word was just spoken,
3. the device averages the last few results (the **window**, `sliding_window_size`, usually 5),
4. when the average exceeds the **cutoff** (`probability_cutoff`, e.g. 0.97), the device wakes up.

The model is a few dozen kilobytes and recognises **one specific word**. It does not understand
speech — that is why it runs on a microcontroller, and why it has to be trained separately for
every word.

## Why you can't "fine-tune" an existing model {#why-you-can-t-fine-tune-an-existing-model}

Ready-made models (`okay_nabu`, `hey_jarvis` …) are already **quantised** (8-bit numbers) and
converted to a **streaming** version. There is no way back from such a file to a version that can
be trained further. Every tool — this one included — trains the model **from scratch**:

- **household recordings** (the most valuable, because they are your voices and your accent),
- **expanded recordings** (the same voice shifted higher/lower, faster/slower),
- **synthetic data** (thousands of utterances of the word from a speech synthesiser),
- **negatives** — hours of speech, music and noise the model must **not** react to.

The good news: since we train from scratch anyway, you can choose **any word** — including
"Dżarwis" pronounced the Polish way, or something entirely new like "Wajana".

## A word for the whole family, not one person {#a-word-for-the-whole-family-not-one-person}

The tool is built around a **household** file (`household.yaml`):

- **speakers** — who will say the words (adult / child),
- **words** — each word has a list of the people who use it; a shared word ("Dżarwis") is recorded
  by everyone, a personal word ("Optimus Prime") only by the son,
- **devices** — which words work on which Voice PE (at most two, because the Voice PE has two
  assistant slots, each with one word).

Each word is trained separately, on recordings of **all of its users**. The household's other
words go into training as negatives — so "Wajana" will not wake the device that listens for
"Optimus Prime".

Recognising **who** is speaking is a separate topic (e.g. the Speaker ID integration) — the wake
word model only has to react correctly to all of its users.

## Key terms {#key-terms}

| Term | Meaning |
|---|---|
| **Take** | one recording of the word by one person, about 1 s |
| **Variant** | how the take was said: near, far, quiet, loud, fast, as a question … |
| **FRR** (false rejection rate) | share of real utterances the model **did not react to**; computed separately for every person |
| **False wakes / h** | how many times per hour the model reacts although nobody said the word (TV, conversation) |
| **Cutoff** (`probability_cutoff`) | higher = fewer false wakes, but more missed words |
| **Window** (`sliding_window_size`) | how many consecutive results are averaged; larger = more stable, but slower |
| **Augmentation** | overlaying background noise and room reverb on a recording, changing volume and timbre |
| **Voice expansion** | one take becomes several "new speakers" (pitch, formants, tempo) |
| **Negatives** | recordings the model must not react to: speech, music, silence, similar-sounding words |
| **Test set** | 2–3 takes per person set aside — the model never sees them in training; they are used for a fair evaluation |
| **Manifest** | a JSON file ESPHome reads to load the `.tflite` model |

## The whole process at a glance {#the-whole-process-at-a-glance}

```
Mac (this repository)                         Computer with NVIDIA GPU           Home Assistant
───────────────────────────────────────       ─────────────────────────          ──────────────
init / add-word / set-device  (plan)
record / import               (recordings)
check                         (speaker × word matrix)
preview                       (listen to augmentation)
prepare = split + expand + synthetic + config ──► train/train.sh  (a few hours)
                                              ◄── .tflite model
evaluate                      (per-person FRR, false/h, cutoff)
export                        (manifest + YAML) ──────────────────────────────────► ESPHome OTA
```

Nothing is trained on the Mac — only planning, recording, checking, data preparation, evaluation
and export. Training itself needs an NVIDIA GPU and runs on Linux.

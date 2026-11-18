# 10. Alternatives {#alternatives}

[← Iterating](09-iterating.md) · [Contents](index.md)

This tool was created because none of the ones below supported **words shared by several people**,
**the household's accent** and **assigning words to devices** all at once. Each of them has its
strengths, though.

| Tool | What it does | When it makes sense | Limitations |
|---|---|---|---|
| **microWakeWord notebook** (`notebooks/basic_training_notebook.ipynb`) | the official example: English synthesis → augmentation → training | a single English word, without household recordings | only synthetic English voices; no per-person evaluation |
| **wakesmith** | microWakeWord training wizard | a quick model for an English word | English Piper voices and English Common Voice; no accent control |
| **TaterTotterson trainer** (Docker) | microWakeWord training in a container, also on Apple Silicon, multilingual TTS engines | training without a separate Linux machine | no household recordings or per-person split; the accent depends on the TTS |
| **openWakeWord + custom verifier** | a second verification stage "is this the speaker" on the HA server (min. 3 recordings per person) | when a general model is good and you want to limit wakes to household members | runs in Home Assistant (Wyoming), not on the Voice PE itself; different models than microWakeWord |
| **SEED method** | 5–9 recordings expanded with the WORLD vocoder | inspiration for `expand` | requires pyworld (not easy to build on macOS) — replaced here by numpy-based expansion |

## When to choose something else {#when-to-choose-something-else}

- You only want an English "Hey Something" and don't care about the accent — the microWakeWord
  notebook or wakesmith will be faster.
- You have no NVIDIA machine at all and don't want to rent one in the cloud — the TaterTotterson
  trainer on a Mac.
- You want the device to react **only** to household members — a wake word model can't guarantee
  that; you need speaker verification (openWakeWord verifier, or speaker recognition after the
  wake, e.g. Speaker ID).

# 09. Iterating {#iterating}

[← Deployment](08-deployment.md) · [Contents](index.md) · [Next: alternatives →](10-alternatives.md)

The first model is rarely the last. A plan for the first week:

## A week of observation {#a-week-of-observation}

Write down (a note on the fridge is enough):

- **misses** — who, in which room, how they said it,
- **false wakes** — when, and what was playing or being said at the time.

In Home Assistant every wake is visible under **Settings → Voice assistants → (assistant) →
Debug**; with audio recording enabled you can listen to what the device heard.

## False wakes → new negatives {#false-wakes-new-negatives}

The most valuable negatives are exactly the sounds that woke the device. Save them (a recording
from the assistant debug view, a clip of the TV programme, a phone recording of the same scene) as
WAV to:

```
households/home/data/false_wakes/dzarwis/2026-11-03_advert.wav
```

On the next `config`/`prepare` a `false_wakes` dataset with a high weight will appear.

## Misses → more takes {#misses-more-takes}

If one person is often missed, record more takes for them — especially in the variant where it
fails (from far away? quietly? in a tired voice?). Children grow: after a few months, record a few
more takes for them.

## Retraining {#retraining}

```bash
wakeword -H households/home check
wakeword -H households/home prepare dzarwis     # new split, expand, synthetic, config
# on the GPU machine:
train/train.sh households/home dzarwis
```

The speech synthesis and downloaded data are already on the GPU machine, so a rerun is quicker.
Features are recomputed only for datasets whose files changed (e.g. `real` after adding takes,
`false_wakes` after adding recordings) — the rest is taken from `data/build/<word>/features/`.

## When to stop {#when-to-stop}

When, for a week, every household member usually wakes the device on the first try and a false
wake happens less than once every few days. Better a slightly higher cutoff and the occasional
repeated word than a device that speaks up on its own at night.

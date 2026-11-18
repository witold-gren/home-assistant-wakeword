# 04. Augmentation and negatives {#augmentation-and-negatives}

[← Recordings](03-recording.md) · [Contents](index.md) · [Next: synthetic data →](05-synthetic-data.md)

## What augmentation does {#what-augmentation-does}

A dozen or so takes are not enough to train a network — but every take can be "placed" in a
thousand situations. During training, microWakeWord transforms each take many times:

- **background** — music, noise, conversations (AudioSet, Free Music Archive, your background
  recordings) at various signal-to-noise ratios (from −5 to 10 dB),
- **reverb** — real room impulse responses (MIT RIR),
- **volume, equaliser (EQ), band-pass filters, slight distortion, pitch shift**,
- **time shift** — the word sometimes earlier, sometimes later in the window.

Household recordings are repeated most often in training (50 augmentation passes, the highest
weight), because they are the most valuable.

## Voice expansion (`expand`) {#voice-expansion-expand}

Augmentation changes the surroundings, but not the voice. `expand` turns every training take into
several "new people":

- **pitch + formants** together (as if a shorter or longer vocal tract — a bit like a child or a
  larger adult), in semitones,
- **tempo** (faster / slower, without changing pitch).

For adults the shifts go both ways, for children mostly downwards (their voices are already high).
By default 6 variants per take:

```bash
wakeword -H households/home expand --all --per-take 6
```

Files go to `data/expanded/<word>/<speaker>/dad_003_far__p-1.5_t0.92.wav` (here: −1.5 semitones,
tempo 0.92). **Only training takes** are expanded — the test set stays untouched, otherwise the
evaluation would measure the model on near-copies of what it learned from. That is why `expand`
requires `split` first (`prepare` does it for you).

## Listen before sending to training (`preview`) {#listen-before-sending-to-training-preview}

```bash
wakeword -H households/home preview dzarwis --count 8
```

This creates 8 files in `data/preview/dzarwis/`, e.g.
`03_mum_002_quiet_rt0.5_eq150-6000_snr10_g-6_tv_evening.wav`:

| Name part | Meaning |
|---|---|
| `rt0.5` | 0.5 s reverb (`dry` = no reverb) |
| `eq150-6000` | 150–6000 Hz band (small speaker, distant microphone) |
| `snr10` | background 10 dB quieter than speech (`clean` = no background) |
| `g-6` | everything 6 dB quieter |
| `tv_evening` | which background recording (`pink` = substitute noise when you have no recordings) |

Listen: does it still sound like someone saying the word in a real room? If your background
recordings are louder than the speech in every example, record them more quietly or from further
away. The preview is simplified — the real augmentation is done by microWakeWord during training.

## Negatives — what augmentation can't replace {#negatives-what-augmentation-can-t-replace}

The model learns from two kinds of examples: **"this is the word"** and **"this is not the word"**.
Augmenting takes only gives the former. Negatives come from:

| Dataset | Source | Purpose |
|---|---|---|
| `speech`, `dinner_party`, `no_speech` | pre-computed features from Hugging Face (`kahrendt/microwakeword`) | hundreds of hours of speech, parties, noise |
| `dinner_party_eval` | as above | only for measuring false wakes during training |
| `sound_alikes` | synthesis of your "sounds like" words (`darwin`, `jarmark` …) | hard negatives — the word's closest neighbours |
| `other_words` | **recordings and synthesis of the household's other words** | "Wajana" doesn't wake the "Optimus Prime" device |
| `background` | your background recordings (`data/background/`) | your TV and your kitchen |
| `false_wakes` | recordings of false wakes (`data/false_wakes/<word>/`) | added over time, see [09](09-iterating.md) |

`config` (and `prepare`) choose the weights automatically; you can review and change the
`training_parameters.yaml` file — each entry has a `sampling_weight` (how often it is sampled) and
a `penalty_weight` (how heavily an error is penalised).

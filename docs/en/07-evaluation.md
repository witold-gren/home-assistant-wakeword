# 07. Evaluation and choosing the cutoff {#evaluation-and-choosing-the-cutoff}

[← Training](06-training.md) · [Contents](index.md) · [Next: deployment →](08-deployment.md)

The training results (on synthetic data) tend to be too optimistic. What matters is whether the
model reacts to **every member of the household** and doesn't wake up from **your TV**.

## Running {#running}

```bash
make setup-eval                   # once: pymicro-features + ai-edge-litert
wakeword -H households/home evaluate dzarwis
```

The model is run the same way as in ESPHome (features every 10 ms, a result every 30 ms, window
average) on:

- every person's **held-out test takes** (the model has not seen them),
- **background recordings** from `data/background/` (or files given with `--background`).

```
word: dzarwis   takes: 15   background: 0.75 h   window: 5
FRR = share of held-out takes missed; fa_per_hour = false wakes per hour of background
cutoff         frr   frr_adult   frr_child        dad        mum        son  daughter1  daughter2  fa_per_hour
0.80          0.0%       0.0%       0.0%       0.0%       0.0%       0.0%       0.0%       0.0%        4.00
0.90          0.0%       0.0%       0.0%       0.0%       0.0%       0.0%       0.0%       0.0%        1.33
0.95          6.7%       0.0%      11.1%       0.0%       0.0%       0.0%      33.3%       0.0%        0.00
0.97         13.3%       0.0%      22.2%       0.0%       0.0%      33.3%      33.3%       0.0%        0.00
…
recommended cutoff: none meets FRR ≤ 5 % per person and ≤ 0.5 false wakes/h — more data needed
```

## How to read the table {#how-to-read-the-table}

- **`frr`** — share of test takes the model didn't recognise; separately for groups (`frr_adult`,
  `frr_child`) and **for every person**.
- **`fa_per_hour`** — false wakes per hour of background (with a 2 s pause after each wake, as on
  the device). `—` when there are no background recordings.
- The higher the cutoff, the fewer false wakes, but the more misses.

**Criteria:** FRR ≤ 5 % for every person and at most 0.5 false wakes per hour.
`recommended cutoff` is the lowest cutoff that meets them.

Note: with 3 test takes per person, a single miss is already 33 %. The table is a hint, not a
verdict — the final test is a week at home.

## What to do when the result is poor {#what-to-do-when-the-result-is-poor}

| Problem | What helps |
|---|---|
| One person (usually a child) has a high FRR | more takes from that person, in different variants; `expand --per-take 8` |
| Everyone has a high FRR at a low cutoff | too little positive data or too strong negatives — increase the `sampling_weight` of the `real` dataset, more steps (`STEPS=40000`) |
| Many false wakes | more background recordings, `sound_alikes`, then [false wakes](09-iterating.md); a higher cutoff |
| The model confuses the household's words | the words are too similar — consider a different word ([02](02-plan-your-household.md)) |

## Measuring at home: the wake log {#measuring-at-home-the-wake-log}

The *Wake Word Recorder* integration writes every wake of a satellite to
`/config/assist/wake_word_log.csv` (semicolons, opens in Excel). It works on its own, with no settings.
The file shows how often each word wakes each room in the real home, so it complements the `fa_per_hour`
measured on recordings.

| Column | Meaning |
| --- | --- |
| `timestamp` | time of the wake |
| `area`, `device` | room and device |
| `wake_word` | the word that woke the device, as the firmware names it |
| `pipeline` | the Assist pipeline that took the wake |
| `outcome` | the result, described below |
| `text` | what speech-to-text heard |
| `response` | how the agent reacted, e.g. `action_done` or `no_intent_match` |
| `seconds` | how long the whole run took |

Values of `outcome`:

- **`no_speech`** — the device woke and nobody said anything. This is the surest sign of a false wake.
- **`command`** — speech-to-text returned text. Check `response` too: `no_intent_match` with odd text is
  usually noise or conversation read as words.
- **`duplicate`** — another device took the same word within 2 s. Usually someone really said it and two
  rooms heard it.
- **`cancelled`** — the run ended before speech-to-text finished.
- any other value — a Home Assistant error code, e.g. `stt-stream-failed`.

Only runs started by a wake word are logged. The button on the device and later turns of a conversation
are not wakes. A wake is not seen while the device cannot reach Home Assistant, for example during its
restart.

## Without the extras on the Mac {#without-the-extras-on-the-mac}

If `pymicro-features` or `ai-edge-litert` won't install on your system, skip this step: choose a
cutoff of 0.97 (the `export` default) and evaluate at home — see [09](09-iterating.md).

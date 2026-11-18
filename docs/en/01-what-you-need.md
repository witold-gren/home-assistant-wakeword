# 01. What you need {#what-you-need}

[← How it works](00-how-it-works.md) · [Contents](index.md) · [Next: plan your household →](02-plan-your-household.md)

## Hardware {#hardware}

| For | What | Notes |
|---|---|---|
| Planning, recording, checking, evaluation, export | Mac, Linux or Windows (WSL) with Python 3.10+ | this repository; no GPU needed |
| Recording | household members' phones or a computer with a microphone | the recorder runs in the browser; ideally record where the device stands |
| Training | Ubuntu 24.04 with an **NVIDIA GeForce RTX 4090 (24 GB)** - the only tested and supported machine | disk: about **70 GB** free, RAM: **16 GB+**; time: a few hours per word |
| Deployment | Home Assistant with the ESPHome Device Builder add-on and Voice PE / ESPHome devices with `micro_wake_word` | — |

The scripts are prepared for exactly this setup: the studio runs in Docker right on Ubuntu with the RTX 4090. Other GPUs, cloud machines or Google Colab may work, but they are not
supported and the project will not be adapted to them - supporting your own hardware is up to you.

## Software on the recording computer {#software-on-the-recording-computer}

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv, once: it fetches Python 3.12 itself, no brew

git clone <repository URL> home-assistant-wakeword
cd home-assistant-wakeword
make setup                 # .venv through uv
source .venv/bin/activate
wakeword --version
```

- **ffmpeg** (`brew install ffmpeg`) — only needed to import Voice Memos files (`.m4a`) and formats other than WAV.
- Only trying the studio needs none of this — Docker Desktop and `make demo` ([Try it on a Mac](11-studio.md#try-on-a-mac)).
- **openssl** — for the recorder certificate (included in macOS and Linux).
- Optional, for evaluating the model on the Mac: `make setup-eval` (pymicro-features, ai-edge-litert).

## Time {#time}

| Step | How long it takes |
|---|---|
| Household plan | 15 minutes at the table with the family |
| Recording | **about 5–10 minutes per person per word** (12–18 guided takes) |
| Household background recording (optional) | 10–30 minutes — the phone lies on the table while the TV plays or dinner is on |
| Data preparation on the Mac | a few minutes |
| Training (GPU) | first run: ~20 GB download + installation; then 2–6 hours per word |
| Evaluation and deployment | 30 minutes |
| Observation at home | a week — see [09. Iterating](09-iterating.md) |

## Consent and privacy — especially for children {#consent-and-privacy-especially-for-children}

- Recordings stay **at home**: the `households/<name>/data/` folder is excluded from git
  (`.gitignore`) and nothing is sent to the internet. You copy the folder to the training machine yourself.
- Tell everyone what the recordings are for, and let them listen to and delete their takes
  (the recorder has **Listen** and **Delete** buttons).
- Record children at their own pace — short sessions; a game of "different voices" (cheerful,
  tired, like a robot) actually gives better, more varied data.
- The `.tflite` model contains no recordings, but it was trained on them — don't publish it if
  anyone in the household doesn't want you to.

## Training data licenses {#training-data-licenses}

The public datasets used in training (AudioSet, Free Music Archive, MIT RIR, the microWakeWord
negative datasets) have various licenses. As with the official microWakeWord notebook, assume the
trained models are **for private, non-commercial use**.

# 06. Training step by step {#training-step-by-step}

[← Synthetic data](05-synthetic-data.md) · [Contents](index.md) · [Next: evaluation →](07-evaluation.md)


> **Easier:** the wake word studio on the GPU machine does every step for you, with no copying between computers —
> [13. The studio step by step](13-studio-step-by-step.md). This chapter describes the command-line way.

## 1. Preparation on the Mac {#preparation-on-the-mac}

When `check` shows a complete set:

```bash
wakeword -H households/home prepare --all
```

`prepare` runs, in order:

| Step | Separate command | Result |
|---|---|---|
| set aside the test set | `split --all` | `data/splits/<word>.csv` — `train`/`test` for every take |
| voice expansion | `expand --all` | `data/expanded/<word>/…` |
| synthesis script | `synthetic --all` | `data/build/<word>/synthetic.sh` |
| training configuration | `config --all` | `data/build/<word>/training_parameters.yaml` and `features.json` |

Without a complete set of recordings `prepare` refuses; `--force` lets you start despite gaps
(e.g. to test the whole process).

## 2. Moving to the GPU machine {#moving-to-the-gpu-machine}

Copy the **repository** (for `train/`) and **the household folder including `data/`**:

```bash
rsync -a home-assistant-wakeword/ gpu-host:home-assistant-wakeword/
```

## 3. Running {#running}

On the Linux machine with an NVIDIA GPU (driver and CUDA installed, `nvidia-smi` works):

```bash
cd home-assistant-wakeword
sudo apt install -y python3.10-venv ffmpeg wget unzip git
train/train.sh households/home --all          # or: train/train.sh households/home dzarwis
```

What `train.sh` does:

1. **Environment** in `~/wakeword-work/venv`: TensorFlow with CUDA, piper-sample-generator, piper-tts, PyTorch, microWakeWord
   (from git, `MWW_REPO`/`MWW_REF`). Only the first time.
2. **Augmentation data and negatives** (`train/download_assets.py`, about 20 GB, only the first
   time): MIT impulse responses, part of AudioSet, Free Music Archive, pre-computed microWakeWord
   negative features. Plus the generator model `en_US-libritts_r-medium.pt`.
3. **Speech synthesis** — runs `synthetic.sh` for **all** words (because each word uses the others
   as negatives). Finished folders are skipped, so an interrupted run can be resumed.
4. For each word:
   - **features** (`train/make_features.py`): collects the files from `features.json`, augments
     them and computes spectrograms into `data/build/<word>/features/`,
   - **training** `microwakeword.model_train_eval` (MixedNet architecture, as in the official notebook),
   - **streaming, quantised model**:
     `data/build/<word>/trained/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite`.

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `WORK` | `~/wakeword-work` | environment, models, voices, downloaded data |
| `PYTHON` | `python3.10` | Python for the venv (3.10 or 3.11) |
| `MWW_REPO`, `MWW_REF` | microWakeWord repository, `main` | e.g. your own fork |
| `STEPS` | from the configuration (20000) | number of training steps |
| `TRAIN=0` | — | no training: only convert and test the best weights so far |
| `ALLOW_CPU=1` | — | train even when TensorFlow sees no GPU (very slow) |

## How long it takes and what you see {#how-long-it-takes-and-what-you-see}

- Synthesis: 20–60 minutes per word (the generator on the GPU is fast, Piper on the CPU slower).
- Features: 10–40 minutes per word.
- Training 20,000 steps: 1–3 hours on an RTX 3060/4090. Every 500 steps you see an evaluation on
  the validation set: `accuracy`, `recall`, `false positives per hour` (from `dinner_party_eval`).
  The best weights are kept (`average_viable_recall`).
- At the end: a test of the streaming model and the `.tflite` file.

Training can be interrupted and resumed (`--restore_checkpoint 1`) — however, it starts counting
the configured steps from the beginning.


## Following training (RTX 4090, i9-14900K, 128 GB RAM) {#following-training-rtx-4090-i9-14900k-128-gb-ram}

In the studio: Training → Live progress ([13.2 step 10](13-studio-step-by-step.md#step-live)).

- **Time (estimate):** first run for 3 words about 6–9 h (downloading ~20 GB, Polish synthesis about 45–60 min
  per word, features 20–40 min, training 40–90 min); retraining one word 1.5–3 h.
- **GPU:** `watch -n 5 nvidia-smi` — during training GPU 30–90 %, 2–8 GB GPU memory. GPU 0 % and CPU 100 % =
  training on the CPU (`train.sh` stops when TensorFlow sees no GPU).
- **Every 500 steps:** `average viable recall` (the main measure) > 0.90 good, > 0.95 very good;
  `estimated false positives per hour` < 1 (ideally < 0.5); `recall at no faph` > 80 % at a cutoff of 0.90–0.97.
  When "So far the best" is flat for ~5,000 steps you can stop and convert: `TRAIN=0 train/train.sh … <word>`.
- **Final result:** `trained/tflite_stream_state_internal_quant/tflite_streaming_roc.txt` — good when some cutoff
  has `frr` ≤ 0.05 and `faph` ≤ 0.5; `AUC` < ~0.05.
- Charts: `tensorboard --logdir data/build/<word>/trained/logs --bind_all` → port 6006.

## 4. Back to the Mac {#back-to-the-mac}

```bash
rsync -a gpu-host:home-assistant-wakeword/households/home/data/build/ households/home/data/build/
```

Next: [07. Evaluation and choosing the cutoff](07-evaluation.md).

## If something goes wrong {#if-something-goes-wrong}

| Symptom | Cause / solution |
|---|---|
| `data/build/<word>: run 'wakeword prepare'` | no configuration — run `prepare` on the Mac and copy again |
| `negative_datasets/… missing` | interrupted download — delete the incomplete folder in `~/wakeword-work/assets` and run again |
| `<dataset>: no audio found` | e.g. another word's synthesis is missing — check that all `synthetic.sh` scripts succeeded |
| very slow, `warning: nvidia-smi not found` | training runs on the CPU — check the NVIDIA driver and `tensorflow[and-cuda]` (train.sh stops when TensorFlow sees no GPU; `ALLOW_CPU=1` overrides) |
| out of GPU memory | reduce `batch_size` in `training_parameters.yaml` (e.g. 64) |

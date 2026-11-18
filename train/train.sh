#!/usr/bin/env bash
# Train wake words of a household on a Linux machine with an NVIDIA GPU.
#
#   train/train.sh <household folder> <word> [<word> …]
#   train/train.sh <household folder> --all
#
# Before: on the Mac run `wakeword prepare --all` and copy the household folder (with data/) here.
# Environment (optional):
#   WORK=~/wakeword-work      venv, microWakeWord, voices and downloaded data (~30 GB)
#   VENV=$WORK/venv           the training environment (the Docker image: /opt/venv, installed already)
#   PYTHON=python3.12         Python used for the venv (default: the first of 3.12, 3.11, 3.10
#                             that can create one - needs the python3.X-venv package)
#   MWW_REPO / MWW_REF        microWakeWord git repository and branch/tag
#   PSG_REF                   piper-sample-generator release for piper_train (default: the installed one)
#   STEPS                     override training steps from training_parameters.yaml
#                             (a second run continues from the saved state: STEPS more steps)
#   NEG_WEIGHT                override negative_class_weight (higher = fewer false wakes, more misses)
#   SET_WEIGHTS               e.g. real=6,synthetic=1 - sampling weight of sets (panel card 5: family / neutral)
#   LEARNING_RATES            e.g. 0.001,0.0003,0.0001 - one per phase, the steps split 50/30/20 (2 phases:
#                             50/50, 4: 40/30/20/10); default 0.001,0.0003,0.0001, continuing 0.0003,0.0001
#   TRAIN=0                   skip training, only convert and test the best weights so far
#   BASE=<model id>|new       no training: the next run starts from that kept model (panel card 6:
#                             Models → Choose) or from scratch (train/models.py, train/set_base.py)
#   ALLOW_CPU=1               train even when TensorFlow does not see a GPU (very slow)
set -euo pipefail

usage() { sed -n '2,15p' "$0"; exit 1; }
[ $# -ge 2 ] || usage

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOUSEHOLD="$(cd "$1" && pwd)"; shift
WORK="${WORK:-$HOME/wakeword-work}"
PYTHON="${PYTHON:-}"
MWW_REPO="${MWW_REPO:-https://github.com/kahrendt/microWakeWord}"
MWW_REF="${MWW_REF:-main}"
VENV="${VENV:-$WORK/venv}"  # the Docker image brings its own, ready (/opt/venv)
ASSETS="$WORK/assets"
# the model architecture: the same for training and for train/set_base.py
MODEL_ARGS=(mixednet --pointwise_filters "64,64,64,64" --repeat_in_block "1, 1, 1, 1"
  --mixconv_kernel_sizes '[5], [7,11], [9,15], [23]' --residual_connection "0,0,0,0"
  --first_conv_filters 32 --first_conv_kernel_size 5 --stride 3)

log() { printf '\n==> %s\n' "$*"; }

# The first Python that can create a venv (Ubuntu ships venv/ensurepip in a separate package).
pick_python() {
  local candidate
  for candidate in ${PYTHON:-python3.12 python3.11 python3.10}; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import ensurepip, venv" 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  local version
  version=$(${PYTHON:-python3} -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo 3.12)
  echo "error: no Python here can create a virtual environment (venv/ensurepip missing)." >&2
  echo "Install it once and run the training again:" >&2
  echo "  sudo apt install -y python$version-venv python$version-dev build-essential" >&2
  return 1
}

if [ "$1" = "--all" ]; then
  mapfile -t WORDS < <(ls "$HOUSEHOLD/data/build")
else
  WORDS=("$@")
fi
[ ${#WORDS[@]} -gt 0 ] || { echo "no words — run 'wakeword prepare --all' first"; exit 1; }

# 1. Environment ----------------------------------------------------------------------------------
mkdir -p "$WORK"
if [ -d "$VENV" ] && [ ! -f "$VENV/bin/activate" ]; then
  # left over by a failed creation (e.g. python3.X-venv missing): has bin/python but no pip
  log "removing the incomplete venv in $VENV"
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  PYTHON="$(pick_python)" || exit 1
  log "creating venv in $VENV with $PYTHON"
  "$PYTHON" -m venv "$VENV" || { rm -rf "$VENV"; exit 1; }
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
if [ ! -f "$VENV/.installed" ]; then
  log "installing training packages"
  pip install --upgrade pip wheel
  pip install -r "$HERE/requirements-train.txt"
  [ -d "$WORK/microWakeWord" ] || git clone --branch "$MWW_REF" "$MWW_REPO" "$WORK/microWakeWord"
  pip install -e "$WORK/microWakeWord"
  touch "$VENV/.installed"
fi
# piper-sample-generator pins audiomentations 0.33, microWakeWord's augmentation needs a newer one
# (AddColorNoise). The generator only uses it in its own augment.py, which is not used here.
if ! python -c "import audiomentations; audiomentations.AddColorNoise" 2>/dev/null; then
  log "updating audiomentations for microWakeWord (piper-sample-generator's pin to 0.33 does not matter here)"
  pip install -q -U "audiomentations>=0.36" 2>&1 | grep -v -e "dependency resolver" -e "audiomentations==0.33.0" || true
fi
# microWakeWord writes training statistics with tf.summary, which needs TensorBoard (TensorFlow 2.20+
# no longer brings it); without it training stops at the first validation (step 500)
if ! python -c "import tensorboard" 2>/dev/null; then
  log "installing tensorboard (training statistics)"
  pip install -q tensorboard
fi
nvidia-smi >/dev/null 2>&1 || echo "warning: nvidia-smi not found — is the NVIDIA driver installed?"
if ! python -c "import tensorflow as tf, sys; sys.exit(0 if tf.config.list_physical_devices('GPU') else 1)" 2>/dev/null; then
  echo "TensorFlow does not see a GPU - training would run on the CPU (many times slower)."
  echo "Check: nvidia-smi, and pip install 'tensorflow[and-cuda]' in $VENV (ALLOW_CPU=1 to continue anyway)."
  [ "${ALLOW_CPU:-0}" = "1" ] || exit 1
fi

# 2. Data for augmentation and negatives -------------------------------------------------------
log "downloading augmentation data and negative datasets (first run only)"
python "$HERE/download_assets.py" "$ASSETS"
ln -sfn "$ASSETS/negative_datasets" "$HOUSEHOLD/negative_datasets"

GENERATOR="$WORK/models/en_US-libritts_r-medium.pt"
if [ ! -f "$GENERATOR" ]; then
  mkdir -p "$WORK/models"
  wget -q --show-progress -O "$GENERATOR" \
    https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt
fi
# The PyPI package of piper-sample-generator leaves out piper_train (needed by the English generator)
# and the generator's config sits in the repository's models/ - take both from the same release.
# the sources of the installed version (PSG_REF=v… to choose another)
PSG_REF="${PSG_REF:-v$(python -c 'from importlib.metadata import version; print(version("piper-sample-generator"))')}"
PSG_SRC="$WORK/piper-sample-generator-$PSG_REF"
if [ ! -d "$PSG_SRC/piper_train" ]; then
  log "piper-sample-generator $PSG_REF sources (piper_train, generator config)"
  rm -rf "$PSG_SRC"
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$PSG_REF" \
    https://github.com/rhasspy/piper-sample-generator "$PSG_SRC"
fi
echo "$PSG_SRC" > "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/piper_train_src.pth"
[ -f "$GENERATOR.json" ] || cp "$PSG_SRC/models/$(basename "$GENERATOR").json" "$GENERATOR.json"
python -c "import piper_train.vits.commons" 2>/dev/null || {
  echo "error: the English generator cannot import piper_train (from $PSG_SRC) - remove that folder and run again"
  exit 1
}

cd "$HOUSEHOLD"

if [ -n "${BASE:-}" ]; then
  # card 6 of the panel, Models → Choose: no synthesis, no training
  for word in "${WORDS[@]}"; do
    log "$word: the next training starts from $BASE"
    python "$HERE/models.py" select "$HOUSEHOLD" "$word" "$BASE"
    if [ "$BASE" != new ]; then
      python "$HERE/set_base.py" "data/build/$word/training_parameters.yaml" \
        "data/build/$word/trained/best_weights.weights.h5" "${MODEL_ARGS[@]}"
    fi
  done
  log "base chosen - start the training in the panel (card 5)"
  exit 0
fi

# 3. Synthetic speech for every word (each word's training uses the others as negatives) ----------
for script in data/build/*/synthetic.sh; do
  log "synthetic speech: $script"
  PSG_MODEL="$GENERATOR" PIPER_VOICES_DIR="$WORK/voices" SYNTH_PIPER="$HERE/synth_piper.py" PYTHON=python \
    bash "$script"
done
# a few clips of every group to listen to on the Mac (card 4 of the panel: Fetch samples)
python "$HERE/synth_preview.py" "$HOUSEHOLD"

# 4. Features, training and the streaming model, word by word ------------------------------------
for word in "${WORDS[@]}"; do
  build="data/build/$word"
  [ -f "$build/training_parameters.yaml" ] || { echo "$build: run 'wakeword prepare $word'"; exit 1; }

  log "$word: features"
  # Features of each word are built separately (the sets depend on the word's split).
  rm -rf features
  mkdir -p "$build/features"
  ln -sfn "$build/features" features
  python "$HERE/make_features.py" "$build/features.json" --assets "$ASSETS"

  config="$build/training_parameters.yaml"
  # a run after a finished one continues from its weights (--restore_checkpoint): it starts at a lower
  # learning rate - 0.001 again shook the learnt model (AVR down to 0.07) before it settled
  CONTINUE=""
  if [ "${TRAIN:-1}" != 0 ] && [ -f "$build/trained/best_weights.weights.h5" ]; then CONTINUE=1; fi
  if [ -n "${STEPS:-}${NEG_WEIGHT:-}${CONTINUE}${LEARNING_RATES:-}${SET_WEIGHTS:-}" ]; then
    python - "$config" "${STEPS:-}" "${NEG_WEIGHT:-}" "$build/training_parameters.run.yaml" "$CONTINUE" \
      "${LEARNING_RATES:-}" "${SET_WEIGHTS:-}" <<'PY'
import sys, yaml
config = yaml.safe_load(open(sys.argv[1]))
phases = len(config["training_steps"])
continuing = len(sys.argv) > 5 and sys.argv[5]
rates = [float(r) for r in sys.argv[6].split(",") if r.strip()] if len(sys.argv) > 6 else []
if sys.argv[2] or continuing or rates:
    # the same falling learning rate as wakeword/training_config.py SCHEDULE (FINE_TUNE when continuing);
    # LEARNING_RATES from the panel: one rate per phase, the steps split as SHARES
    shares = {1: (1.0,), 2: (0.5, 0.5), 3: (0.5, 0.3, 0.2), 4: (0.4, 0.3, 0.2, 0.1)}
    if rates:
        schedule = tuple(zip(shares[len(rates)], rates))
    else:
        schedule = ((0.5, 0.0003), (0.5, 0.0001)) if continuing else ((0.5, 0.001), (0.3, 0.0003), (0.2, 0.0001))
    steps = int(sys.argv[2] or sum(int(s) for s in config["training_steps"]))
    parts = [int(steps * share) for share, _ in schedule[:-1]]
    config["training_steps"] = [*parts, steps - sum(parts)]
    config["learning_rates"] = [rate for _, rate in schedule]
    phases = len(schedule)
    for key in ("positive_class_weight", "negative_class_weight", "mix_up_augmentation_prob",
                "freq_mix_augmentation_prob", "time_mask_max_size", "time_mask_count", "freq_mask_max_size",
                "freq_mask_count"):
        if isinstance(config.get(key), list):
            config[key] = config[key][-1:] * phases
if sys.argv[3]:
    config["negative_class_weight"] = [float(sys.argv[3])] * phases
# SET_WEIGHTS from the panel: how often each set is sampled (features/<set> or negative_datasets/<set>)
weights = dict(pair.split("=", 1) for pair in sys.argv[7].split(",") if "=" in pair) if len(sys.argv) > 7 else {}
for feature in config.get("features", []):
    name = feature["features_dir"].rstrip("/").rsplit("/", 1)[-1]
    if name in weights:
        feature["sampling_weight"] = float(weights[name])
yaml.safe_dump(config, open(sys.argv[4], "w"), sort_keys=False)
PY
    config="$build/training_parameters.run.yaml"
  fi

  if [ "${TRAIN:-1}" != 0 ] && [ -f "$build/trained/best_weights.weights.h5" ]; then
    # microWakeWord restarts its "best so far" in every run, so the first score of this run
    # replaces the previous best weights - a model trained before models were kept goes to the list
    python "$HERE/models.py" archive "$HOUSEHOLD" "$word" >/dev/null
  fi
  started=$(date +%s)

  log "$word: training"
  if [ "${TRAIN:-1}" != 0 ]; then
    # read by the training panel: percent done, time left and the advice after the test
    python - "$config" <<'PY'
import sys, time, yaml
config = yaml.safe_load(open(sys.argv[1]))
phases = ",".join(f"{int(s)}:{r:g}" for s, r in zip(config["training_steps"], config["learning_rates"]))
weights = ",".join(f"{f['features_dir'].rsplit('/', 1)[-1]}:{f['sampling_weight']:g}"
                   for f in config.get("features", []) if f["sampling_weight"])
print(f"training plan: steps={sum(int(s) for s in config['training_steps'])} started={int(time.time())} "
      f"negative_weight={config['negative_class_weight'][-1]:g} phases={phases} weights={weights}")
PY
  fi
  python -m microwakeword.model_train_eval \
    --training_config="$config" \
    --train "${TRAIN:-1}" \
    --restore_checkpoint 1 \
    --test_tf_nonstreaming 0 \
    --test_tflite_nonstreaming 0 \
    --test_tflite_nonstreaming_quantized 0 \
    --test_tflite_streaming 0 \
    --test_tflite_streaming_quantized 1 \
    --use_weights "best_weights" \
    "${MODEL_ARGS[@]}"

  model="$build/trained/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite"
  [ -f "$model" ] && log "$word: model ready → $model" || { echo "$word: no model produced"; exit 1; }
  # every run on the list of card 6 (Models); after "convert only" its final test is refreshed
  python "$HERE/models.py" archive "$HOUSEHOLD" "$word" --config "$config" --started "$started" --log
  # the household test of the new model (and of older ones not measured on these takes yet): the
  # "Household" column of the Models card - held-out family takes, the test part of the home background
  log "$word: household test"
  PYTHONPATH="$HERE/.." python -m wakeword -H "$HOUSEHOLD" evaluate-models "$word" --missing \
    || echo "$word: household test failed - the Models card can run it again"
done

rm -f features
log "done - compare the models (studio: Training → Models; old panel: card 6; or wakeword evaluate / export)"

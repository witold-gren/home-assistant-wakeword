#!/usr/bin/env bash
# Install (or update) the wake word studio on an Ubuntu machine with an NVIDIA GPU.
#
#   docker/install-ubuntu.sh               check, write the login on the first run, build and start
#   docker/install-ubuntu.sh --show-login  print the login (user and password) from config/env
#   docker/install-ubuntu.sh --gpu-check   does TensorFlow in the running container compute on the GPU
#   docker/install-ubuntu.sh --stop        stop the studio; it stays off after a restart (starting it again: up)
#   docker/install-ubuntu.sh --uninstall [--yes]  remove containers, image, config and the code folder (data stays)
#   docker/install-ubuntu.sh --remove      stop and remove the container (data and config stay)
#
# Afterwards the studio starts with the machine: http://<machine>:8765/
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config"
ENV_FILE="$CONFIG/env"
COMPOSE=(docker compose -f "$HERE/compose.yaml")

# one line: the GPUs TensorFlow sees and a small product computed on the first one (exit 1 without a GPU)
TF_GPU_CHECK='import sys, tensorflow as tf
gpus = tf.config.list_physical_devices("GPU")
if not gpus: sys.exit("TensorFlow: no GPU - training would run on the CPU")
with tf.device("/GPU:0"): product = tf.matmul(tf.ones((256, 256)), tf.ones((256, 256)))
if float(product[0, 0]) != 256.0 or "GPU" not in product.device: sys.exit("TensorFlow: the product was not computed on the GPU")
print(f"TensorFlow {tf.__version__}: {len(gpus)} GPU, a matrix product on the GPU works")'
say() { printf '==> %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  --show-login)
    [ -f "$ENV_FILE" ] || fail "no $ENV_FILE yet - run docker/install-ubuntu.sh first"
    sed -n 's/^WAKEWORD_UI_AUTH=\([^:]*\):\(.*\)$/user: \1\npassword: \2/p' "$ENV_FILE"
    exit 0 ;;
  --gpu-check)
    "${COMPOSE[@]}" exec -T -e TF_CPP_MIN_LOG_LEVEL=3 studio python -c "$TF_GPU_CHECK"
    exit $? ;;
  --stop)
    "${COMPOSE[@]}" stop
    say "stopped - it stays off after a restart too; start it again: make deploy (or docker compose up -d)"
    exit 0 ;;
  --uninstall)
    ROOT="$(cd "$HERE/.." && pwd)"
    name=$(sed -n 's/^name *= *"\(.*\)"$/\1/p' "$ROOT/pyproject.toml" 2>/dev/null | head -1)
    [ "$name" = home-assistant-wakeword ] \
      || fail "$ROOT is not the wake word studio (pyproject.toml name: ${name:-none}) - nothing removed"
    [ "$ROOT" != / ] && [ "$ROOT" != "$(cd ~ && pwd)" ] || fail "refusing to remove $ROOT"
    data=("$HERE/data")
    if [ -f "$HERE/.env" ]; then
      while IFS='=' read -r key value; do
        case "$key" in STUDIO_HOUSEHOLD|STUDIO_WORK|STUDIO_HF) data+=("${value/#\~/$HOME}") ;; esac
      done < "$HERE/.env"
    fi
    keep_code=0
    for folder in "${data[@]}"; do
      case "$folder/" in "$ROOT"/*) [ -e "$folder" ] && keep_code=1 ;; esac
    done
    echo "This removes:"
    echo "  - the studio's containers and the image wakeword-studio:latest"
    echo "  - $CONFIG (login, Home Assistant, keys) and $HERE/.env"
    if [ "$keep_code" = 1 ]; then echo "  - (the code folder $ROOT stays: data lies inside it)"; else echo "  - the code folder $ROOT"; fi
    echo "It keeps the data:"
    for folder in "${data[@]}"; do [ -e "$folder" ] && echo "  - $folder"; done
    if [ "${2:-}" != --yes ]; then
      printf 'Type yes to remove: '
      read -r answer || answer=""
      [ "$answer" = yes ] || fail "nothing removed"
    fi
    "${COMPOSE[@]}" down --remove-orphans || true
    docker image rm wakeword-studio:latest >/dev/null 2>&1 || true
    rm -rf "$CONFIG" "$HERE/.env"
    if [ "$keep_code" = 0 ]; then
      cd /
      rm -rf "$ROOT"
      say "removed $ROOT; the data stays"
    else
      say "removed the studio; $ROOT stays (data inside)"
    fi
    exit 0 ;;
  --remove)
    "${COMPOSE[@]}" down
    say "removed; $HERE/data and $CONFIG are kept"
    exit 0 ;;
  "") ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac

say "checking the machine"
command -v docker >/dev/null || fail "Docker is missing: https://docs.docker.com/engine/install/ubuntu/"
docker compose version >/dev/null 2>&1 || fail "the Docker Compose plugin is missing: sudo apt install docker-compose-plugin"
docker info >/dev/null 2>&1 || fail "this user cannot use Docker: sudo usermod -aG docker $(id -un) (then log in again)"
command -v nvidia-smi >/dev/null || fail "the NVIDIA driver is missing (no nvidia-smi) - install it first: sudo ubuntu-drivers install"
nvidia-smi >/dev/null 2>&1 \
  || fail "the NVIDIA driver does not answer (nvidia-smi) - restart the machine after installing it, or reinstall: sudo ubuntu-drivers install"
# TensorFlow's CUDA 12 libraries in the image need at least this driver
MIN_DRIVER=525
driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
[ "${driver%%.*}" -ge "$MIN_DRIVER" ] 2>/dev/null \
  || fail "the NVIDIA driver ${driver:-?} is too old - the studio needs $MIN_DRIVER or newer: sudo ubuntu-drivers install"
docker info --format '{{json .Runtimes}}' | grep -q nvidia \
  || fail "the NVIDIA Container Toolkit is missing: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html (then: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker)"
free_gb=$(df -Pk "$HERE" | awk 'NR == 2 { print int($4 / 1048576) }')
[ "$free_gb" -ge 60 ] || say "warning: only ${free_gb} GB free here - training data, the image and the models need ~60 GB"

umask 077
# existing folders of the machine can be used instead of docker/data (kept in docker/.env):
#   STUDIO_HOUSEHOLD=~/wakeword-train/household STUDIO_WORK=~/wakeword-work docker/install-ubuntu.sh
STUDIO_HOUSEHOLD="${STUDIO_HOUSEHOLD:-$HERE/data/household}"
STUDIO_WORK="${STUDIO_WORK:-$HERE/data/work}"
STUDIO_HF="${STUDIO_HF:-$HERE/data/huggingface}"
mkdir -p "$CONFIG" "$STUDIO_HOUSEHOLD" "$STUDIO_WORK" "$STUDIO_HF"
chmod 700 "$CONFIG"
if [ ! -f "$ENV_FILE" ]; then
  password=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
  printf 'WAKEWORD_UI_AUTH=admin:%s\n' "$password" > "$ENV_FILE"
  say "login written to $ENV_FILE (show it: docker/install-ubuntu.sh --show-login)"
fi
# a home that uses the machine only on its own network may skip the login (e.g. 192.168.1.0/24; VPN clients count when
# the VPN translates them to a home address); empty = the login from everywhere (always on a machine in the cloud)
if [ -n "${STUDIO_TRUSTED_NETWORKS+set}" ]; then
  grep -v '^STUDIO_TRUSTED_NETWORKS=' "$ENV_FILE" > "$ENV_FILE.new" || true
  [ -z "$STUDIO_TRUSTED_NETWORKS" ] || printf 'STUDIO_TRUSTED_NETWORKS=%s\n' "$STUDIO_TRUSTED_NETWORKS" >> "$ENV_FILE.new"
  mv "$ENV_FILE.new" "$ENV_FILE"
  say "no login from: ${STUDIO_TRUSTED_NETWORKS:-nowhere (login always)}"
fi
chmod 600 "$ENV_FILE"
printf 'UID=%s\nGID=%s\nSTUDIO_HOUSEHOLD=%s\nSTUDIO_WORK=%s\nSTUDIO_HF=%s\n' "$(id -u)" "$(id -g)" \
  "$STUDIO_HOUSEHOLD" "$STUDIO_WORK" "$STUDIO_HF" > "$HERE/.env"

if ! systemctl is-enabled --quiet docker 2>/dev/null; then
  say "starting Docker with the machine (sudo)"
  sudo systemctl enable --now docker
fi

# an older panel of this app on the same port (a user service, or "make ui-remote" left running) is switched off
for unit in $(systemctl --user list-unit-files 'wakeword*' --no-legend 2>/dev/null | awk '{print $1}'); do
  say "switching off the old service $unit (the studio replaces it)"
  systemctl --user disable --now "$unit" || true
done
port="${STUDIO_PORT:-8765}"
if ! "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx studio \
   && ss -Hltn "sport = :$port" 2>/dev/null | grep -q .; then
  fail "port $port is taken by another program (an old training panel?) - stop it first: ss -ltnp 'sport = :$port'"
fi

say "building and starting (the first build downloads TensorFlow and CUDA, ~10 GB)"
"${COMPOSE[@]}" up -d --build
say "GPU in the container:"
"${COMPOSE[@]}" exec -T studio nvidia-smi --query-gpu=name,memory.total --format=csv,noheader \
  || say "warning: the container does not see the GPU - see the FAQ (no GPU in the container)"
# nvidia-smi alone is not enough: TensorFlow itself must find its CUDA libraries, or it trains on the CPU
"${COMPOSE[@]}" exec -T -e TF_CPP_MIN_LOG_LEVEL=3 studio python -c "$TF_GPU_CHECK" \
  || say "warning: TensorFlow in the container does not see the GPU - training would run on the CPU; see the FAQ"
say "ready: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${STUDIO_PORT:-8765}/  (user and password: --show-login)"

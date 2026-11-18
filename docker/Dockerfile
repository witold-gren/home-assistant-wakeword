# Wake word studio: the editor and everything training needs, for a Linux machine with an NVIDIA GPU.
#
#   docker compose -f docker/compose.yaml up -d --build      (docker/install-ubuntu.sh does it all)
#
# TRAINING=0 builds the editor only (no TensorFlow, CUDA, microWakeWord) - for trying the studio on a Mac.
# the documentation (the studio's "?" opens it at /docs/, also without the internet) - its own stage
FROM python:3.12-slim-bookworm AS docs
RUN pip install --no-cache-dir mkdocs==1.6.1 mkdocs-material==9.8.1 mkdocs-static-i18n==1.3.1
COPY mkdocs.yml CHANGELOG.md /src/
COPY docs /src/docs
RUN cd /src && NO_MKDOCS_2_WARNING=1 mkdocs build --strict --site-dir /site

# make docs-build: only the built site, written to ./site (docker build --target docs-site --output type=local,dest=site)
FROM scratch AS docs-site
COPY --from=docs /site /

# make demo on a Mac (gpu-studio standard, section 8b): the studio on a made-up household with a pretend GPU,
# login demo/demo, nothing to install but Docker. Only the toolkit's own dependencies (wheels for arm64 and amd64):
# no TensorFlow, CUDA, microWakeWord, compilers or evaluation extras - it builds in seconds.
#   docker build --target demo -f docker/Dockerfile -t wakeword-studio:demo .
FROM python:3.12-slim-bookworm AS demo
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd -m -u 1000 demo && mkdir /app && chown demo:demo /app
COPY --chown=demo:demo pyproject.toml README.md /app/
COPY --chown=demo:demo wakeword /app/wakeword
RUN pip install -e /app
COPY --chown=demo:demo docs /app/docs
COPY --chown=demo:demo train /app/train
COPY --from=docs --chown=demo:demo /site /app/site
USER demo
WORKDIR /app
RUN python -c "import sys; sys.path.insert(0, 'docs'); import studio_demo"   # import self-test of the demo
EXPOSE 8766
CMD ["python", "docs/studio_demo.py", "--host", "0.0.0.0", "--port", "8766"]

# the studio for the GPU machine (the last stage: what docker compose builds)
FROM python:3.12-slim-bookworm AS studio

ARG UID=1000
ARG GID=1000
ARG TRAINING=1
# microWakeWord at a known commit: training must not change under the household between two runs
ARG MWW_REPO=https://github.com/kahrendt/microWakeWord
ARG MWW_REF=4665173cd35f1cff9a61e06fc427f124766c488e

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/wakeword \
    VENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    WORK=/data/work \
    WAKEWORD_HOUSEHOLD=/data/household \
    WAKEWORD_IN_CONTAINER=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git wget unzip rsync ca-certificates build-essential libsndfile1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g "$GID" wakeword && useradd -m -u "$UID" -g "$GID" -s /bin/bash wakeword \
 && mkdir -p /opt/venv /app /data/household /data/work \
 && chown -R wakeword:wakeword /opt/venv /app /data

USER wakeword
RUN python -m venv /opt/venv && pip install --upgrade pip wheel

# the training environment first: it changes rarely, so code changes rebuild only the last layers
COPY --chown=wakeword:wakeword train/requirements-train.txt /tmp/requirements-train.txt
# torch (piper-sample-generator) from the CUDA 12 index first: torch from PyPI is built for CUDA 13 and brings
# a second set of CUDA libraries next to TensorFlow's. The build fails if any non-CUDA-12 package comes in.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu126
RUN if [ "$TRAINING" = "1" ]; then \
      pip install --index-url "$TORCH_INDEX" torch torchaudio \
      && pip install -r /tmp/requirements-train.txt \
      && git clone "$MWW_REPO" /opt/venv/microWakeWord \
      && git -C /opt/venv/microWakeWord checkout -q "$MWW_REF" \
      && pip install -e /opt/venv/microWakeWord \
      && pip install "audiomentations>=0.36" tensorboard \
      && python -c "import tensorflow, microwakeword, audiomentations" \
      && { ! pip list --format=freeze | grep -i '^nvidia-' | grep -vi -- '-cu12=='; } \
      && touch /opt/venv/.installed; \
    fi

# TensorFlow 2.21's libtensorflow_framework has no nvidia/cusolver/lib in its RUNPATH: without this it misses
# libcusolver.so.11 and runs on the CPU without a word (2026-11-18 on the RTX 4090); the build checks the file
ENV CUSOLVER_LIB=/opt/venv/lib/python3.12/site-packages/nvidia/cusolver/lib
ENV LD_LIBRARY_PATH=$CUSOLVER_LIB
RUN if [ "$TRAINING" = "1" ]; then test -f "$CUSOLVER_LIB/libcusolver.so.11"; fi

# the toolkit and the studio, installed in place: train/, docs/ and the panel are found next to the code
COPY --chown=wakeword:wakeword . /app
COPY --from=docs --chown=wakeword:wakeword /site /app/site
RUN pip install -e "/app[evaluate]" \
 && python -c "import wakeword.studio.server, wakeword.trainer.server"   # import self-test of the last layer

WORKDIR /app
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)"
CMD ["wakeword", "studio", "--host", "0.0.0.0", "--port", "8765"]

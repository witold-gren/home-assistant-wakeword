# Following the shared standard {#standard}

The wake word studio is one of five apps that since 16–17 November 2026 are used **the same way**: the wake word
studio, the Assist Router trainer studio and Piper Voice Cloner (GPU machine), and the Home Dashboard editor and the
Assist Router editor (panels in Home Assistant). The rules are in one file: `~/Home Assistant/standards/gpu-studio.md`
(English `gpu-studio.en.md`, also on the home documentation site as "Standard studia na maszynie GPU"). This page collects
everything changed in this repository to meet it.

## In short {#in-short}

| Area | Section of the standard | What changed |
|---|---|---|
| `make` commands | §2 | the same names as the other apps, three groups, the machine's address in one file, Python through uv |
| Trying it on a Mac | §8b | `make demo` — Docker Desktop is enough, a light demo image in 20 s |
| Docker | §3 | separate stages: documentation, demo, studio; self-tests; the installer switches old services on the same port off |
| Login | §4 | user and password like Piper Voice Cloner, a 30-day session, a pause after 5 mistakes |
| Look and help | §5 | one `?` to the documentation, help windows, folding columns |
| Switching the machine off | §6 | through Home Assistant, by itself after a training with a countdown |
| Performance | §9a | the studio never hangs: time limits, no polling in the background, long lists in pieces |
| Documentation | §8 | a MkDocs site in PL and EN, in the studio and on the home documentation site, built in Docker |
| Tests | §9 | a test for every change, separate tests of the Docker images |

## make commands {#make-commands}

`make help` (Polish or English, from `$LANG`) starts with three groups, the same in every app:

| Group | Commands | Needs |
|---|---|---|
| 1. Start | `help`, `demo`, `demo-clean`, `docs`, `docs-serve`, `doctor` | only Docker Desktop |
| 2. GPU machine | `install`, `deploy`, `login`, `logs`, `status`, `stop`, `uninstall`; on the machine `docker-up`, `docker-down`, `docker-logs`, `docker-shell` | `ssh` and `rsync` (macOS has them) and the machine's address |
| 3. Development | `setup`, `demo-local`, `test`, `test-browser`, `test-docker`, `test-all`, `lint`, `format`, `docs-build`, `screenshots`, `icons`, `clean` | uv (it fetches Python 3.12 itself), Chrome for the browser tests |

Then come the groups of this toolkit only: household and recordings on the Mac, training and results without the
studio. The old panel (`ui`, `ui-remote`) is gone since 1.0.0.

What changed along the way:

- **The machine's address in one place for every studio**: `~/.config/gpu-studio/host.mk` with
  `GPU_HOST = user@address`. This app's exceptions (data folders) are in `Makefile.local`, outside git. Without the
  address the commands say where to put it. No private addresses in the repository.
- **New commands**: `install` (the first install from the Mac), `login` (shows the user and password from the
  machine), `logs`, `status` (the studio's answer, the graphics card in the container), `doctor` (checks Docker, git,
  ssh, rsync, the machine, uv, Chrome, ffmpeg and the household folder — installs nothing).
- **The developer's environment through uv**: `make setup` creates `.venv` with `uv venv --python 3.12`, no
  `brew install python`. Without uv a message gives the command to install it.
- **Tests**: `make test` builds no images; `make test-docker` really builds the demo and documentation images (pytest
  marker `docker`); `make test-all` = `lint` + `test` + `test-browser` + `test-docker`; `make format` fixes and
  formats the code; `make lint` also checks the formatting.
- **One name for one thing**: removed `make studio` and `make studio-docker` (the same as `demo-local` and `demo`),
  `make docs-pages` (old HTML pages) and the file `docker/compose.cpu.yaml` (copies in `backup/`).
- `tests/test_makefile.py` checks: both descriptions of every command, the order of the groups and their commands, no
  `setup` in groups 1 and 2, uv, the meaning of `test`/`test-docker`/`test-all`, the ports, no aliases.

## Trying it on a Mac {#try-on-a-mac-summary}

- `make demo` builds the **light `demo` stage** of `docker/Dockerfile` (only the toolkit's dependencies, no
  TensorFlow, CUDA, compilers or `apt-get`) and runs it at `http://localhost:8766`, login `demo`/`demo`. A made-up
  household and a pretend GPU, nothing goes to Home Assistant or the machine.
- The first version built the demo from the GPU image without training: **23 minutes and 1.5 GB**. Its own stage:
  **18 seconds and 426 MB**, later builds in a few seconds.
- Ctrl+C stops and removes the container (checked: in under a second), `make demo-clean` removes the images, without
  Docker — the message "install and start Docker Desktop".
- `docs/studio_demo.py` got `--host` (`0.0.0.0` in the container); the demo without Docker is `make demo-local`.
- Every port is different across the apps (the table in the standard): studio 8765, demo 8766, documentation 9766.
- The [Try it on a Mac](11-studio.md#try-on-a-mac) section in the README (PL and EN) and in chapter 11.

## Docker on the GPU machine {#docker}

- `docker/Dockerfile` has the stages: `docs` (builds the documentation, `mkdocs build --strict`), `docs-site` (only
  the site, for `make docs-build`), `demo` (Mac) and the last one — the studio with TensorFlow and CUDA, which
  `docker compose` builds.
- An import self-test after every layer — a broken image is never made.
- `docker/install-ubuntu.sh` switches this app's old services off (`wakeword*` in the user's systemd) and names the
  program holding port 8765 instead of fighting it.
- `.dockerignore` leaves out `site`, `Makefile.local`, data and secrets.

## The first real run on Ubuntu {#first-run-on-ubuntu}

On 18 November 2026 three apps started on the RTX 4090 machine for the first time. The bugs that passed every test on
the Mac, and what changed in the studio:

- **TensorFlow did not see the card**, although `nvidia-smi` in the container showed it: TensorFlow 2.21's
  `libtensorflow_framework.so.2` has no `nvidia/cusolver/lib` in its paths and `libcusolver.so.11` was missing.
  Training would have run on the CPU. The image sets `LD_LIBRARY_PATH` to that folder and the build checks the file;
  also torch from the CUDA 12 index (one CUDA family in the image instead of 12 and 13).
- **The card check computes on the card**: the installer and `make status` multiply a matrix in TensorFlow
  (`docker/install-ubuntu.sh --gpu-check`), not just ask `nvidia-smi`.
- **Compose builds the stage by name** (`target: studio`), and `/api/health` says who answers (`app`, `mode`,
  `version`) — Piper's machine started the demo because compose took the last stage.
- **The real script in a test**: the runner starts the real `train/train.sh` the way the studio does (in a variant
  that ends before installing anything) — the log is not empty, the exit code is not 0.
- **Installer**: `$(id -un)` instead of `$USER`, the driver must answer and be at least 525, tests on a "pretend
  machine" for every missing piece; new `make stop` and `make uninstall`.
- **A copy before updating**: `docker/config` and `docker/.env` of the machine in `~/backup/` (mode 600).

## Login {#login}

Like Piper Voice Cloner: `WAKEWORD_UI_AUTH=user:password` in `docker/config/env` (made by the installer, mode 600),
a signed 30-day session, a 60 s pause after 5 wrong passwords from one address. `make login` shows them from the
machine. It replaced the old panel's access token.

## Look and help {#look-and-help}

- **One `?` in the top bar** opens the documentation (in the studio at `/docs/`, works without the internet).
- **The `?` of a card** opens a small window with that one function's description next to the button — closed by ✕,
  Esc, a click beside it, the same `?` or a change of view; it has "More in the guide" to the chapter's anchor.
  Before, every `?` jumped to the documentation site.
- Removed: the `?` next to the training fields (the fields have hints) and the old "How to train?" window.
- **Folding columns**: ‹ next to the search folds the left column, › at the top of the right one folds it; a 28 px
  strip with an unfold button stays. Shortcuts Ctrl/⌘+B (left) and Ctrl/⌘+Alt+B (right). The browser remembers it,
  and in a window narrower than 900 px the right column starts folded.

## Switching the machine off {#power-off}

- The "Switch the machine off" button and "switch off when it ends" — through the machine's switch in Home Assistant
  (`switch.turn_off`); Home Assistant always switches it on.
- After a training (successful or with an error, never after Stop) a 120 s countdown in the top bar with Cancel; an
  evaluation, export or command meanwhile pauses it; a container restart drops it; a power-off error shows in the bar.
  The power-off box is also next to "Start training".

## Performance {#performance}

After the HA dashboards hung, the standard requires that the app never hangs:

- the state is asked only after the previous answer and not from a tab in the background;
- every call has a time limit (state 20 s, others 150 s) and a clear message;
- long lists of recordings are drawn when their group opens, 200 at a time, and ticking a recording does not redraw
  the view;
- the draft goes to the machine one save at a time (a change during a slow save goes in one more save, a failed save
  says so and does not retry in a loop);
- Playwright tests: a slow server, a tab in the background, no answer, 1500 recordings with no task above 500 ms.

## Documentation {#documentation}

- The hand-written HTML pages became a **MkDocs Material site** (`mkdocs.yml`, `docs/pl`, `docs/en`): the same pages
  and the same `{#…}` anchors in both languages. The old pages are in `backup/docs-before-mkdocs/`.
- The same site is in the studio at `/docs/` (built into the image) and on the **home documentation site** (docs-hub, type
  `mkdocs`, no dead links).
- `make docs`, `docs-build` and `docs-serve` run **in Docker** — no Python. The live preview at
  `http://127.0.0.1:9766` rebuilds after a file changes.
- New and rewritten chapters: 11 "Wake word studio" (installing, login, the screen, draft and history, power-off,
  recordings from HA, trying it on a Mac), 12 "Training a good wake word" (how many takes, every parameter with its
  default and effect, reading the results, recipes), this page.
- FAQ (PL and EN) for every new message: no `GPU_HOST`, port 8765 taken, a call's time limit, a chapter missing on
  the home documentation site, Docker not running, no uv.
- Screenshots refreshed (`make screenshots`), with no Mac paths, addresses or household names.

## Tests {#tests}

Every change has a test. The main files:

| File | What it checks |
|---|---|
| `tests/test_makefile.py` | commands, groups, uv, no aliases, `doctor`, the message without a machine address |
| `tests/test_try_on_a_mac.py` | the "Try it on a Mac" section; marked `docker`: the real demo image (HTTP, login, no container after stopping) and the documentation built in Docker |
| `tests/studio/test_studio_server.py` | power-off (pause, Stop, restart), `/docs/` |
| `tests/studio/test_studio_docker.py` | the Dockerfile stages (light demo, studio last), self-tests, the installer |
| `tests/studio/test_studio_docs.py` | the same pages and anchors in PL and EN, navigation, links from the `?` windows, strict build |
| `tests/studio/test_studio_browser.py` | only one `?` opens the documentation, help windows, the power-off countdown, folding columns, performance |

Result on 17 November 2026: `make test` — 530 passed, 2 skipped; `make test-docker` — 2 passed. The tests never
reach the real Home Assistant.

## What is left {#what-is-left}

- ~~The first start on the GPU machine~~ — done on 18 Nov 2026: install, TensorFlow on the GPU, training, evaluation
  and export through the studio ([The first real run](#first-run-on-ubuntu)).
- ~~Stage E7~~ — done in 1.0.0: the old panel (`make ui`, `ui-remote`, `wakeword train-ui`), the SSH mode from the Mac,
  `guide.md` and its screenshots removed; the texts and the cards' help describe the studio.
- **Stage E8** — the false wakes log (API in Wake Word Recorder 0.3.0 and a view in the studio).
- **Tidying the code**: `make lint` reports old ruff findings in older files and unformatted code — `make format`
  and manual fixes are a separate step.

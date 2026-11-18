# home-assistant-wakeword - every step from recordings to a model on Home Assistant Voice.
#
#   make help                 the commands in groups (Polish or English, from $LANG; HELP_LANG=en|pl)
#   make <target> H=<folder>  household folder (default below)
#
# The shared commands of every app (~/Home Assistant/standards/gpu-studio.md, section 2):
#   1. Start        - need only Docker Desktop (demo, docs, doctor)
#   2. GPU machine  - need only ssh and rsync (macOS has them) and GPU_HOST
#   3. Development  - work on the code: the environment comes from uv (it fetches Python itself)
# The toolkit's own targets (household, recordings, training on this computer) follow; they create the
# environment first, so any target can be the first one.

# the household folder on this computer; Home Assistant keeps only what its integration records and
# the studio fetches it through the API
H ?= $(HOME)/home-assistant/wakeword
WORD ?=
WORDS ?= --all
CUTOFF ?= 0.97
PORT ?= 8443
UI_PORT ?= 8765
PYTHON_VERSION ?= 3.12
# the GPU machine with the studio in Docker (make install / deploy), shared by every studio
# (~/Home Assistant/standards/gpu-studio.md): ~/.config/gpu-studio/host.mk with GPU_HOST = user@192.168.1.21;
# this repository's exceptions go to Makefile.local (not in git)
-include $(HOME)/.config/gpu-studio/host.mk
-include Makefile.local
GPU_DIR ?= home-assistant-wakeword
DEMO_PORT ?= 8766
DOCS_PORT ?= 9766
DEMO_IMAGE ?= wakeword-studio:demo
DEMO_CONTAINER ?= wakeword-studio-demo
DOCS_IMAGE ?= wakeword-studio:docs
NEED_DOCKER = command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || { \
  echo "Docker is not running: install and start Docker Desktop (https://www.docker.com/products/docker-desktop/)"; \
  echo "Docker nie działa: zainstaluj i uruchom Docker Desktop"; exit 1; }
NEED_HOST = @test -n "$(GPU_HOST)" || { echo "put GPU_HOST = user@machine in ~/.config/gpu-studio/host.mk (or make <target> GPU_HOST=…)"; exit 1; }
# folders the studio uses on that machine (empty: docker/data/... next to the repository); an earlier training
# without Docker: STUDIO_HOUSEHOLD=~/wakeword-train/household STUDIO_WORK=~/wakeword-work STUDIO_HF=~/.cache/huggingface
STUDIO_HOUSEHOLD ?=
STUDIO_WORK ?=
STUDIO_HF ?=
RSYNC_CODE := rsync -az --delete --exclude .git --exclude '.venv*' --exclude __pycache__ --exclude .pytest_cache \
  --exclude backup --exclude data --exclude docker/data --exclude docker/config --exclude docker/.env --exclude Makefile.local
STUDIO_FOLDERS := $(if $(STUDIO_HOUSEHOLD),STUDIO_HOUSEHOLD=$(STUDIO_HOUSEHOLD) )$(if $(STUDIO_WORK),STUDIO_WORK=$(STUDIO_WORK) )$(if $(STUDIO_HF),STUDIO_HF=$(STUDIO_HF) )
COMPOSE := docker compose -f docker/compose.yaml
HA_CONFIG ?= /Volumes/config
# device YAMLs for the Devices tab, when the Home Assistant config share is mounted
export WAKEWORD_ESPHOME ?= $(HA_CONFIG)/esphome

VENV := .venv
PIP := uv pip install -q --python $(VENV)/bin/python
WAKEWORD := $(VENV)/bin/wakeword -H "$(H)"
HELP_LANG ?= $(if $(filter pl%,$(LANG)),pl,en)
DOCS_START := site/$(if $(filter pl,$(HELP_LANG)),pl/,)index.html

.DEFAULT_GOAL := help
.PHONY: help demo demo-clean docs docs-serve doctor \
        install deploy login logs status stop uninstall docker-up docker-down docker-logs docker-shell \
        setup demo-local test test-browser test-docker test-all lint format docs-build screenshots icons clean \
        setup-eval init household record record-phone import check preview prepare train evaluate export

##@ 1. Start - only Docker Desktop | 1. Start - wystarczy Docker Desktop

help: ## This list | Ta lista
	@awk -v lang=$(HELP_LANG) 'BEGIN { FS = ":.*## " } \
	  /^##@ / { split(substr($$0, 5), t, " \\| "); printf "\n\033[1m%s\033[0m\n", (lang == "pl" && t[2] != "") ? t[2] : t[1]; next } \
	  /^[a-zA-Z0-9_-]+:.*## / { split($$2, d, " \\| "); printf "  \033[36m%-14s\033[0m %s\n", $$1, (lang == "pl" && d[2] != "") ? d[2] : d[1] }' \
	  $(MAKEFILE_LIST)
	@echo
	@if [ "$(HELP_LANG)" = "pl" ]; then \
	  echo "Folder rodziny: H=$(H)   (zmień: make <cel> H=/inna/ścieżka)"; \
	else \
	  echo "Household folder: H=$(H)   (change: make <target> H=/other/path)"; \
	fi

demo: ## Try the studio: builds and runs the demo image (http://localhost:8766, demo/demo) | Wypróbuj studio: buduje i uruchamia obraz demo (http://localhost:8766, demo/demo)
	@$(NEED_DOCKER)
	docker build --target demo -f docker/Dockerfile -t $(DEMO_IMAGE) .
	@echo "==> http://localhost:$(DEMO_PORT)  (demo / demo)  -  Ctrl+C stops it | zatrzymuje"
	docker run --rm --init $$([ -t 0 ] && echo -it) --name $(DEMO_CONTAINER) -p 127.0.0.1:$(DEMO_PORT):$(DEMO_PORT) \
	  $(DEMO_IMAGE) python docs/studio_demo.py --host 0.0.0.0 --port $(DEMO_PORT)

demo-clean: ## Remove the demo container and images | Usuń kontener i obrazy demo
	-docker container stop $(DEMO_CONTAINER) 2>/dev/null
	-docker image rm $(DEMO_IMAGE) $(DOCS_IMAGE) 2>/dev/null

docs: docs-build ## Build the documentation in Docker and open it | Zbuduj dokumentację w Dockerze i ją otwórz
	@open $(DOCS_START) 2>/dev/null || xdg-open $(DOCS_START)

docs-serve: ## The documentation with a live preview, in Docker (http://127.0.0.1:9766) | Dokumentacja z podglądem na żywo, w Dockerze (http://127.0.0.1:9766)
	@$(NEED_DOCKER)
	docker build --target docs -f docker/Dockerfile -t $(DOCS_IMAGE) .
	@echo "==> http://127.0.0.1:$(DOCS_PORT)  -  Ctrl+C stops it | zatrzymuje"
	docker run --rm --init $$([ -t 0 ] && echo -it) -p 127.0.0.1:$(DOCS_PORT):8000 -w /src -e NO_MKDOCS_2_WARNING=1 -e SITE_URL=http://127.0.0.1:$(DOCS_PORT)/ \
	  -v "$(CURDIR)/docs:/src/docs" -v "$(CURDIR)/mkdocs.yml:/src/mkdocs.yml:ro" -v "$(CURDIR)/CHANGELOG.md:/src/CHANGELOG.md:ro" \
	  $(DOCS_IMAGE) mkdocs serve -a 0.0.0.0:8000

doctor: ## Check what this computer has (installs nothing) | Sprawdź, co ma ten komputer (niczego nie instaluje)
	@ok() { printf "ok       %s\n" "$$1"; }; miss() { printf "MISSING  %s - %s\n" "$$1" "$$2"; }; \
	if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then ok "Docker (make demo, make docs)"; \
	  else miss "Docker" "install and start Docker Desktop: https://www.docker.com/products/docker-desktop/"; fi; \
	for tool in git ssh rsync; do if command -v $$tool >/dev/null 2>&1; then ok "$$tool"; else miss "$$tool" "xcode-select --install"; fi; done; \
	if [ -n "$(GPU_HOST)" ]; then \
	  if ssh -o BatchMode=yes -o ConnectTimeout=3 $(GPU_HOST) true 2>/dev/null; then ok "GPU machine $(GPU_HOST) (ssh)"; \
	  else miss "GPU machine $(GPU_HOST)" "off or no SSH key (switch it on in Home Assistant; ssh-copy-id $(GPU_HOST))"; fi; \
	else miss "GPU_HOST" "put GPU_HOST = user@machine in ~/.config/gpu-studio/host.mk (make install, deploy)"; fi; \
	echo "-- for working on the code | do pracy nad kodem:"; \
	if command -v uv >/dev/null 2>&1; then ok "uv $$(uv --version | cut -d' ' -f2) (make setup)"; \
	  else miss "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh"; fi; \
	if [ -d "/Applications/Google Chrome.app" ] || command -v google-chrome >/dev/null 2>&1; then ok "Google Chrome (make test-browser, screenshots)"; \
	  else miss "Google Chrome" "https://www.google.com/chrome/ (make test-browser, screenshots)"; fi; \
	for tool in ffmpeg openssl; do if command -v $$tool >/dev/null 2>&1; then ok "$$tool (recorder, import)"; else miss "$$tool" "brew install $$tool (only the recorder and import)"; fi; done; \
	if [ -f "$(H)/household.yaml" ]; then ok "household: $(H)"; \
	  else miss "$(H)/household.yaml" "only for the toolkit on this computer: make init (or create it in HA: Wake Word Recorder)"; fi

##@ 2. GPU machine (GPU_HOST) | 2. Maszyna z GPU (GPU_HOST)

install: ## First install on GPU_HOST: code, login, autostart, build, start (STUDIO_HOUSEHOLD/WORK/HF = existing folders) | Pierwsza instalacja na GPU_HOST: kod, login, autostart, budowa, start (STUDIO_HOUSEHOLD/WORK/HF = istniejące foldery)
	$(NEED_HOST)
	$(RSYNC_CODE) ./ $(GPU_HOST):$(GPU_DIR)/
	ssh -t $(GPU_HOST) 'cd $(GPU_DIR) && $(STUDIO_FOLDERS)docker/install-ubuntu.sh'

deploy: ## Every update: send this repository to GPU_HOST and rebuild the studio there | Każda aktualizacja: wyślij repozytorium na GPU_HOST i przebuduj tam studio
	$(NEED_HOST)
	$(RSYNC_CODE) ./ $(GPU_HOST):$(GPU_DIR)/
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && { test -f docker/config/env || { echo "first time: make install"; exit 1; }; } && $(COMPOSE) up -d --build'

login: ## The studio's user and password (kept on GPU_HOST in docker/config/env) | Użytkownik i hasło studia (zapisane na GPU_HOST w docker/config/env)
	$(NEED_HOST)
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && docker/install-ubuntu.sh --show-login'

logs: ## The studio's log on GPU_HOST (Ctrl+C ends) | Log studia na GPU_HOST (Ctrl+C kończy)
	$(NEED_HOST)
	ssh -t $(GPU_HOST) 'cd $(GPU_DIR) && $(COMPOSE) logs -f --tail 200'

status: ## Does the right app answer (health: app, mode, version), the card, TensorFlow on the GPU | Czy odpowiada właściwa aplikacja (health: app, tryb, wersja), karta, TensorFlow na karcie
	$(NEED_HOST)
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && curl -fsS http://127.0.0.1:$(UI_PORT)/api/health; echo; $(COMPOSE) ps --format "{{.Service}} {{.State}} {{.Status}}"; $(COMPOSE) exec -T studio nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total,temperature.gpu --format=csv,noheader; docker/install-ubuntu.sh --gpu-check'

stop: ## Stop the studio on GPU_HOST: it stays off also after a restart (make deploy starts it) | Zatrzymaj studio na GPU_HOST: zostaje wyłączone także po restarcie (make deploy je uruchamia)
	$(NEED_HOST)
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && docker/install-ubuntu.sh --stop'

uninstall: ## Remove the studio from GPU_HOST: lists what goes and asks for yes (CONFIRM=yes skips it); the data stays | Usuń studio z GPU_HOST: wypisuje, co usunie, i pyta o yes (CONFIRM=yes bez pytania); dane zostają
	$(NEED_HOST)
	ssh -t $(GPU_HOST) 'cd $(GPU_DIR) && docker/install-ubuntu.sh --uninstall$(if $(filter yes,$(CONFIRM)), --yes)'

docker-up: ## On the machine: build and start the studio (first time: docker/install-ubuntu.sh) | Na maszynie: zbuduj i uruchom studio (za pierwszym razem: docker/install-ubuntu.sh)
	$(COMPOSE) up -d --build

docker-down: ## On the machine: stop the studio (a running training stops too; data stays) | Na maszynie: zatrzymaj studio (trwający trening też; dane zostają)
	$(COMPOSE) down

docker-logs: ## On the machine: the studio's log (Ctrl+C ends) | Na maszynie: log studia (Ctrl+C kończy)
	$(COMPOSE) logs -f --tail 200

docker-shell: ## On the machine: a shell in the studio's container | Na maszynie: powłoka w kontenerze studia
	$(COMPOSE) exec studio bash

##@ 3. Development - the environment through uv | 3. Rozwój - środowisko przez uv

$(VENV)/bin/wakeword: pyproject.toml
	@command -v uv >/dev/null 2>&1 || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh  (uv fetches Python $(PYTHON_VERSION) itself)"; \
	  echo "brak uv: curl -LsSf https://astral.sh/uv/install.sh | sh  (uv sam pobierze Pythona $(PYTHON_VERSION))"; exit 1; }
	@echo "==> Python environment in $(VENV) (Python $(PYTHON_VERSION) through uv)"
	@test -x $(VENV)/bin/python || uv venv -q --python $(PYTHON_VERSION) $(VENV)
	@$(PIP) -e '.[test]'
	@touch $@
	@echo "==> ready: $$($(VENV)/bin/wakeword --version)"

setup: $(VENV)/bin/wakeword ## The environment for tests, demo-local and the toolkit (.venv through uv) | Środowisko do testów, demo-local i narzędzia (.venv przez uv)

demo-local: setup ## The same demo from .venv, without Docker (for tests and screenshots) | To samo demo z .venv, bez Dockera (do testów i zrzutów)
	@$(PIP) -e '.[test,docs]'
	$(VENV)/bin/python docs/studio_demo.py --port $(DEMO_PORT)

test: setup ## Tests, without building images | Testy, bez budowania obrazów
	$(VENV)/bin/python -m pytest -q -m "not docker"

test-browser: setup ## The studio and the panel in Google Chrome (Playwright, demo household) | Studio i panel w Google Chrome (Playwright, przykładowa rodzina)
	@$(PIP) -e '.[test,docs]'
	$(VENV)/bin/python -m pytest -q -m "not docker" tests/studio/test_studio_browser.py tests/studio/test_studio_login_browser.py tests/test_trainer_browser.py

test-docker: setup ## The images for real: build the demo, run it, log in, stop it; build the docs (needs Docker) | Obrazy naprawdę: buduje demo, uruchamia, loguje się, zatrzymuje; buduje dokumentację (wymaga Dockera)
	@$(NEED_DOCKER)
	$(VENV)/bin/python -m pytest -q -m docker

test-all: lint test test-browser test-docker ## lint + test + test-browser + test-docker | lint + test + test-browser + test-docker

lint: setup ## Ruff: errors and formatting | Ruff: błędy i formatowanie
	@$(PIP) ruff
	$(VENV)/bin/ruff check wakeword tests docs train
	$(VENV)/bin/ruff format --check wakeword tests docs train

format: setup ## Ruff: fix what it can and format the code | Ruff: popraw, co się da, i sformatuj kod
	@$(PIP) ruff
	$(VENV)/bin/ruff check --fix wakeword tests docs train
	$(VENV)/bin/ruff format wakeword tests docs train

docs-build: ## Build the documentation site into site/ in Docker (the studio serves it at /docs/; docs-hub builds it) | Zbuduj stronę dokumentacji do site/ w Dockerze (studio podaje ją pod /docs/; buduje ją też docs-hub)
	@$(NEED_DOCKER)
	rm -rf site
	docker build --target docs-site -f docker/Dockerfile --output type=local,dest=site .
	chmod -R u+rwX,go+rX site
	@test -f site/index.html && test -f site/pl/index.html && echo "==> site/ ready | gotowe"

screenshots: setup ## Screenshots of the studio for the documentation (demo household, Google Chrome) | Zrzuty studia do dokumentacji (przykładowa rodzina, Google Chrome)
	@$(PIP) -e '.[test,docs]'
	$(VENV)/bin/python docs/studio_demo.py --shots

icons: setup ## Icons of the studio again, after adding an mdi: icon (MDI=path/to/@mdi/js/mdi.js) | Ikony studia od nowa po dodaniu ikony mdi: (MDI=ścieżka do @mdi/js/mdi.js)
	@test -n "$(MDI)" || { echo "usage: make icons MDI=path/to/mdi.js (npm @mdi/js 7.4.47)"; exit 1; }
	$(VENV)/bin/python -m wakeword.studio.make_icons "$(MDI)"

clean: ## Remove caches and the built site (keeps environments and recordings) | Usuń pliki tymczasowe i zbudowaną stronę (środowiska i nagrania zostają)
	find . -name __pycache__ -type d -prune -not -path "./.venv*" -exec rm -rf {} +
	rm -rf .pytest_cache build *.egg-info site

##@ 4. Household and recordings (the toolkit on this computer) | 4. Rodzina i nagrania (narzędzie na tym komputerze)

setup-eval: setup ## Add the extras for evaluating models on this computer | Doinstaluj dodatki do oceny modeli na tym komputerze
	@$(PIP) -e '.[test,evaluate]' && echo "==> evaluation extras installed"

init: setup ## Create household.yaml (SPEAKERS="dad mum kid:child") | Utwórz household.yaml (SPEAKERS="tata mama ola:child")
	@test -n "$(SPEAKERS)" || { echo 'usage: make init SPEAKERS="tomek ania ola:child"'; exit 1; }
	$(WAKEWORD) init --ui-language $(HELP_LANG) $(foreach s,$(SPEAKERS),--speaker $(s))

household: setup ## Show people, words and devices | Pokaż osoby, słowa i urządzenia
	@cat "$(H)/household.yaml"

record: setup ## Recorder on this computer (http://localhost:8443) | Rejestrator na tym komputerze (http://localhost:8443)
	$(WAKEWORD) record --http --port $(PORT)

record-phone: setup ## Recorder for phones (HTTPS, own certificate) | Rejestrator dla telefonów (HTTPS, własny certyfikat)
	$(WAKEWORD) record --port $(PORT)

import: setup ## Import audio files (WORD=… SPEAKER=… FILES="a.m4a b.m4a") | Importuj pliki audio (WORD=… SPEAKER=… FILES="…")
	@test -n "$(WORD)" -a -n "$(SPEAKER)" -a -n "$(FILES)" || { echo 'usage: make import WORD=dzarwis SPEAKER=tomek FILES="~/Downloads/*.m4a"'; exit 1; }
	$(WAKEWORD) import $(WORD) --speaker $(SPEAKER) $(FILES)

check: setup ## Recordings: person x word matrix and problems | Nagrania: macierz osoba x słowo i problemy
	-$(WAKEWORD) check

preview: setup ## Listen to augmented examples (WORD=…) | Posłuchaj przykładów augmentacji (WORD=…)
	@test -n "$(WORD)" || { echo "usage: make preview WORD=dzarwis"; exit 1; }
	$(WAKEWORD) preview $(WORD) && open "$(H)/data/preview/$(WORD)" 2>/dev/null || true

##@ 5. Training and results without the studio | 5. Trening i wyniki bez studia

prepare: setup ## Prepare words for training (WORDS="dzarwis wajana", default all) | Przygotuj słowa do treningu (WORDS="…", domyślnie wszystkie)
	$(WAKEWORD) prepare $(WORDS)

train: ## Train on this machine without the studio (Linux + NVIDIA; WORDS=… STEPS=…) | Trenuj na tym komputerze bez studia (Linux + NVIDIA; WORDS=… STEPS=…)
	$(if $(STEPS),STEPS=$(STEPS) )train/train.sh "$(H)" $(WORDS)

evaluate: setup-eval ## Misses per person and false wakes per hour (WORD=…) | Przegapienia na osobę i fałszywe wybudzenia/h (WORD=…)
	@test -n "$(WORD)" || { echo "usage: make evaluate WORD=dzarwis"; exit 1; }
	$(WAKEWORD) evaluate $(WORD)

export: setup ## Models and ESPHome snippets (CUTOFF=0.97) | Modele i fragmenty YAML dla ESPHome (CUTOFF=0.97)
	$(WAKEWORD) export $(WORDS) --cutoff $(CUTOFF)

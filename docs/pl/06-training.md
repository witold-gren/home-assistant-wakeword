# 06. Trening krok po kroku {#training-step-by-step}

[← Dane syntetyczne](05-synthetic-data.md) · [Spis treści](index.md) · [Dalej: ocena →](07-evaluation.md)


> **Wygodniej:** studio słów budzących na maszynie z GPU robi wszystkie kroki za Ciebie, bez kopiowania między
> komputerami — [13. Studio krok po kroku](13-studio-step-by-step.md). Ten rozdział opisuje drogę z wiersza poleceń.

## 1. Przygotowanie na Macu {#preparation-on-the-mac}

Gdy `check` pokazuje komplet:

```bash
wakeword -H households/dom prepare --all
```

`prepare` robi po kolei:

| Krok | Polecenie osobno | Wynik |
|---|---|---|
| odłożenie testu | `split --all` | `data/splits/<słowo>.csv` — `train`/`test` dla każdego ujęcia |
| rozmnożenie głosu | `expand --all` | `data/expanded/<słowo>/…` |
| skrypt syntezy | `synthetic --all` | `data/build/<słowo>/synthetic.sh` |
| konfiguracja treningu | `config --all` | `data/build/<słowo>/training_parameters.yaml` i `features.json` |

Bez kompletu nagrań `prepare` odmówi; `--force` pozwala zacząć mimo braków (np. żeby
przetestować cały proces).

## 2. Przeniesienie na maszynę z GPU {#moving-to-the-gpu-machine}

Skopiuj **repozytorium** (dla `train/`) i **folder rodziny razem z `data/`**:

```bash
rsync -a home-assistant-wakeword/ gpu-host:home-assistant-wakeword/
```

## 3. Uruchomienie {#running}

Na maszynie z Linuksem i kartą NVIDIA (sterownik i CUDA zainstalowane, `nvidia-smi` działa):

```bash
cd home-assistant-wakeword
sudo apt install -y python3.10-venv ffmpeg wget unzip git
train/train.sh households/dom --all          # albo: train/train.sh households/dom dzarwis
```

Co robi `train.sh`:

1. **Środowisko** w `~/wakeword-work/venv`: TensorFlow z CUDA, piper-sample-generator, piper-tts, PyTorch, microWakeWord
   (z gita, `MWW_REPO`/`MWW_REF`). Tylko za pierwszym razem.
2. **Dane do augmentacji i negatywy** (`train/download_assets.py`, ok. 20 GB, tylko za pierwszym
   razem): odpowiedzi impulsowe MIT, część AudioSet, Free Music Archive, gotowe cechy negatywów
   microWakeWord. Do tego model generatora `en_US-libritts_r-medium.pt`.
3. **Synteza mowy** — uruchamia `synthetic.sh` **wszystkich** słów (bo każde słowo używa pozostałych
   jako negatywów). Gotowe foldery są pomijane, więc przerwane uruchomienie można wznowić.
4. Dla każdego słowa:
   - **cechy** (`train/make_features.py`): zbiera pliki z `features.json`, augmentuje je i liczy
     spektrogramy do `data/build/<słowo>/features/`,
   - **trening** `microwakeword.model_train_eval` (architektura MixedNet, jak w oficjalnym notatniku),
   - **model strumieniowy, skwantyzowany**:
     `data/build/<słowo>/trained/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite`.

Zmienne środowiskowe:

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `WORK` | `~/wakeword-work` | środowisko, modele, głosy, pobrane dane |
| `PYTHON` | `python3.10` | Python do venv (3.10 lub 3.11) |
| `MWW_REPO`, `MWW_REF` | repozytorium microWakeWord, `main` | np. własny fork |
| `STEPS` | z konfiguracji (20000) | liczba kroków treningu |
| `TRAIN=0` | — | bez treningu: tylko przelicz i przetestuj model z najlepszych dotąd wag |
| `ALLOW_CPU=1` | — | trenuj mimo braku karty widocznej dla TensorFlow (bardzo wolno) |

## Ile to trwa i co widać {#how-long-it-takes-and-what-you-see}

- Synteza: 20–60 minut na słowo (generator na GPU jest szybki, Piper na CPU wolniejszy).
- Cechy: 10–40 minut na słowo.
- Trening 20 000 kroków: 1–3 godziny na RTX 3060/4090. Co 500 kroków pojawia się ocena na zbiorze
  walidacyjnym: `accuracy`, `recall`, `false positives per hour` (z `dinner_party_eval`).
  Zapamiętywane są najlepsze wagi (`average_viable_recall`).
- Na końcu: test modelu strumieniowego i plik `.tflite`.

Trening można przerwać i wznowić (`--restore_checkpoint 1`) — zacznie jednak od początku liczby
kroków z konfiguracji.


## Jak śledzić trening (RTX 4090, i9-14900K, 128 GB RAM) {#following-training-rtx-4090-i9-14900k-128-gb-ram}

W studiu: Trening → Postęp na żywo ([13.2 krok 10](13-studio-step-by-step.md#step-live)).

- **Czas (szacunek):** pierwsze uruchomienie dla 3 słów ok. 6–9 h (pobieranie ~20 GB, synteza polska ok. 45–60 min
  na słowo, cechy 20–40 min, trening 40–90 min); ponowny trening jednego słowa 1,5–3 h.
- **Karta:** `watch -n 5 nvidia-smi` — w treningu GPU 30–90 %, 2–8 GB pamięci GPU. GPU 0 % i 100 % CPU = trening
  na procesorze (`train.sh` przerywa, gdy TensorFlow nie widzi karty).
- **Co 500 kroków:** `average viable recall` (główna miara) > 0,90 dobrze, > 0,95 bardzo dobrze;
  `estimated false positives per hour` < 1 (najlepiej < 0,5); `recall at no faph` > 80 % przy progu 0,90–0,97.
  Gdy „So far the best” stoi ~5 000 kroków — można przerwać i przeliczyć: `TRAIN=0 train/train.sh … <słowo>`.
- **Wynik końcowy:** `trained/tflite_stream_state_internal_quant/tflite_streaming_roc.txt` — dobrze, gdy jest
  próg z `frr` ≤ 0,05 i `faph` ≤ 0,5; `AUC` < ~0,05.
- Wykresy: `tensorboard --logdir data/build/<słowo>/trained/logs --bind_all` → port 6006.

## 4. Z powrotem na Maca {#back-to-the-mac}

```bash
rsync -a gpu-host:home-assistant-wakeword/households/dom/data/build/ households/dom/data/build/
```

Dalej: [07. Ocena i wybór progu](07-evaluation.md).

## Jeśli coś pójdzie nie tak {#if-something-goes-wrong}

| Objaw | Przyczyna / rozwiązanie |
|---|---|
| `data/build/<słowo>: run 'wakeword prepare'` | brak konfiguracji — uruchom `prepare` na Macu i skopiuj ponownie |
| `negative_datasets/… missing` | przerwane pobieranie — usuń niepełny folder w `~/wakeword-work/assets` i uruchom ponownie |
| `<zbiór>: no audio found` | np. brak syntezy innego słowa — sprawdź, czy wszystkie `synthetic.sh` przeszły |
| bardzo wolno, `warning: nvidia-smi not found` | trening idzie na CPU — sprawdź sterownik NVIDIA i wersję TensorFlow z CUDA (`tensorflow[and-cuda]`) |
| brak pamięci GPU | zmniejsz `batch_size` w `training_parameters.yaml` (np. 64) |

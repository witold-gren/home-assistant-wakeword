# 01. Co przygotować {#what-you-need}

[← Jak to działa](00-how-it-works.md) · [Spis treści](index.md) · [Dalej: plan rodziny →](02-plan-your-household.md)

## Sprzęt {#hardware}

| Do czego | Co | Uwagi |
|---|---|---|
| Planowanie, nagrania, kontrola, ocena, eksport | Mac, Linux lub Windows (WSL) z Pythonem 3.10+ | to repozytorium; bez karty graficznej |
| Nagrywanie | telefony domowników albo komputer z mikrofonem | rejestrator działa w przeglądarce; najlepiej nagrywać w miejscu, gdzie stoi urządzenie |
| Trening | Ubuntu 24.04 z kartą **NVIDIA GeForce RTX 4090 (24 GB)** - jedyna sprawdzona i wspierana maszyna | dysk: ok. **70 GB** wolnego miejsca, RAM: **16 GB+**; czas: kilka godzin na słowo |
| Wdrożenie | Home Assistant z dodatkiem ESPHome Device Builder i urządzenia Voice PE / ESPHome z `micro_wake_word` | — |

Skrypty są przygotowane dokładnie pod ten zestaw: studio działa w Dockerze wprost na Ubuntu z RTX 4090. Inne karty, maszyny w chmurze czy Google Colab mogą działać, ale nie są wspierane
i projekt nie będzie do nich dostosowywany - wsparcie dla własnego sprzętu trzeba zapewnić samemu.

## Oprogramowanie na komputerze do nagrań {#software-on-the-recording-computer}

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv, raz: sam pobiera Pythona 3.12, bez brew

git clone <adres repozytorium> home-assistant-wakeword
cd home-assistant-wakeword
make setup                 # .venv przez uv
source .venv/bin/activate
wakeword --version
```

- **ffmpeg** (`brew install ffmpeg`) — potrzebny tylko do importu plików z Dyktafonu (`.m4a`) i innych formatów niż WAV.
- Samo wypróbowanie studia nie potrzebuje niczego z tego — Docker Desktop i `make demo` ([Wypróbuj na Macu](11-studio.md#try-on-a-mac)).
- **openssl** — do certyfikatu rejestratora (jest w macOS i Linuksie).
- Opcjonalnie do oceny modelu na Macu: `make setup-eval` (pymicro-features, ai-edge-litert).

## Czas {#time}

| Krok | Ile to trwa |
|---|---|
| Plan rodziny | 15 minut przy stole z rodziną |
| Nagrania | **ok. 5–10 minut na osobę na słowo** (12–18 ujęć z instrukcją) |
| Nagranie tła domu (opcjonalnie) | 10–30 minut — telefon leży na stole, gdy gra TV, trwa obiad |
| Przygotowanie danych na Macu | kilka minut |
| Trening (GPU) | pierwsze uruchomienie: pobranie ~20 GB danych + instalacja; potem 2–6 godzin na słowo |
| Ocena i wdrożenie | 30 minut |
| Obserwacja w domu | tydzień — zobacz [09. Kolejne iteracje](09-iterating.md) |

## Zgoda i prywatność — szczególnie dzieci {#consent-and-privacy-especially-for-children}

- Nagrania zostają **w domu**: folder `households/<nazwa>/data/` jest wykluczony z gita
  (`.gitignore`) i niczego nie wysyła się do internetu. Na maszynę treningową kopiujesz folder sam.
- Powiedz domownikom, do czego są nagrania, i pozwól im odsłuchać i usunąć swoje ujęcia
  (rejestrator ma przyciski **Odsłuchaj** i **Usuń**).
- Dzieci nagrywaj w ich tempie — krótkie sesje, zabawa w „różne głosy” (wesoło, zmęczonym głosem,
  jak robot) daje zresztą lepsze, bardziej zróżnicowane dane.
- Model `.tflite` nie zawiera nagrań, ale został na nich wytrenowany — nie publikuj go, jeśli
  ktoś z domowników sobie tego nie życzy.

## Licencje danych treningowych {#training-data-licenses}

Publiczne zbiory używane w treningu (AudioSet, Free Music Archive, MIT RIR, zbiory negatywów
microWakeWord) mają różne licencje. Tak jak w oficjalnym notatniku microWakeWord przyjmij, że
wytrenowane modele są **do użytku prywatnego, niekomercyjnego**.

# 07. Ocena i wybór progu {#evaluation-and-choosing-the-cutoff}

[← Trening](06-training.md) · [Spis treści](index.md) · [Dalej: wdrożenie →](08-deployment.md)

Wyniki z treningu (na danych syntetycznych) bywają zbyt optymistyczne. Liczy się, czy model
reaguje na **każdego z domowników** i czy nie budzi się od **Waszego telewizora**.

## Uruchomienie {#running}

```bash
make setup-eval                   # raz: pymicro-features + ai-edge-litert
wakeword -H households/dom evaluate dzarwis
```

Model jest uruchamiany tak jak w ESPHome (cechy co 10 ms, wynik co 30 ms, średnia z okna) na:

- **odłożonych ujęciach testowych** każdej osoby (model ich nie widział),
- **nagraniach tła** z `data/background/` (albo plikach podanych przez `--background`).

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

## Jak czytać tabelę {#how-to-read-the-table}

- **`frr`** — odsetek ujęć testowych, których model nie rozpoznał; osobno dla grup (`frr_adult`,
  `frr_child`) i **dla każdej osoby**.
- **`fa_per_hour`** — fałszywe wybudzenia na godzinę tła (po wybudzeniu 2 s przerwy, jak w
  urządzeniu). `—` gdy nie ma nagrań tła.
- Im wyższy próg, tym mniej fałszywych wybudzeń, ale więcej przegapień.

**Kryteria:** dla każdej osoby FRR ≤ 5 % i najwyżej 0,5 fałszywego wybudzenia na godzinę.
`recommended cutoff` to najniższy próg, który je spełnia.

Uwaga: przy 3 ujęciach testowych na osobę jedno przegapienie to od razu 33 %. Tabela jest
wskazówką, nie wyrokiem — ostateczny test to tydzień w domu.

## Co zrobić, gdy wynik jest słaby {#what-to-do-when-the-result-is-poor}

| Problem | Co pomaga |
|---|---|
| Jedna osoba (zwykle dziecko) ma wysoki FRR | więcej ujęć tej osoby, w różnych wariantach; `expand --per-take 8` |
| Wszyscy mają wysoki FRR przy niskim progu | za mało danych pozytywnych lub za mocne negatywy — zwiększ `sampling_weight` zbioru `real`, więcej kroków (`STEPS=40000`) |
| Dużo fałszywych wybudzeń | więcej nagrań tła, `sound_alikes`, a potem [fałszywe wybudzenia](09-iterating.md); wyższy próg |
| Model myli słowa domu | słowa są zbyt podobne — rozważ inne słowo ([02](02-plan-your-household.md)) |

## Pomiar w domu: dziennik wybudzeń {#measuring-at-home-the-wake-log}

Integracja *Wake Word Recorder* zapisuje każde wybudzenie satelity do pliku
`/config/assist/wake_word_log.csv` (średniki, otwiera się w Excelu). Działa sama, bez ustawień. Plik
pokazuje, jak często każde słowo wybudza każdy pokój w prawdziwym domu, więc uzupełnia `fa_per_hour`
liczone na nagraniach.

| Kolumna | Znaczenie |
| --- | --- |
| `timestamp` | czas wybudzenia |
| `area`, `device` | pokój i urządzenie |
| `wake_word` | słowo, które wybudziło urządzenie, tak jak podaje je firmware |
| `pipeline` | potok Assist, który przyjął wybudzenie |
| `outcome` | wynik, opisany niżej |
| `text` | co usłyszało rozpoznawanie mowy |
| `response` | jak zareagował agent, np. `action_done` albo `no_intent_match` |
| `seconds` | jak długo trwał cały przebieg |

Wartości `outcome`:

- **`no_speech`** — urządzenie się wybudziło, a nikt nic nie powiedział. To najpewniejszy znak
  fałszywego wybudzenia.
- **`command`** — rozpoznawanie mowy zwróciło tekst. Sprawdź też `response`: `no_intent_match` przy
  dziwnym tekście to zwykle hałas albo rozmowa odczytana jako słowa.
- **`duplicate`** — to samo słowo przyjęło już inne urządzenie w ciągu 2 s. Zwykle ktoś naprawdę je
  powiedział, tylko usłyszały je dwa pokoje.
- **`cancelled`** — przebieg zakończył się przed rozpoznaniem mowy.
- inna wartość — kod błędu Home Assistant, np. `stt-stream-failed`.

Do dziennika trafiają tylko przebiegi rozpoczęte słowem budzącym. Przycisk na urządzeniu i kolejne
tury rozmowy nie są wybudzeniami. Wybudzenia nie widać, gdy urządzenie nie połączyło się z Home
Assistant, na przykład w czasie jego restartu.

## Bez dodatków na Macu {#without-the-extras-on-the-mac}

Jeśli `pymicro-features` lub `ai-edge-litert` nie instalują się na Twoim systemie, pomiń ten krok:
wybierz próg 0,97 (domyślny `export`) i oceniaj w domu — patrz [09](09-iterating.md).

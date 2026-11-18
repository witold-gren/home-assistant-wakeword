# 04. Augmentacja i negatywy {#augmentation-and-negatives}

[← Nagrania](03-recording.md) · [Spis treści](index.md) · [Dalej: dane syntetyczne →](05-synthetic-data.md)

## Co robi augmentacja {#what-augmentation-does}

Kilkanaście ujęć to za mało, żeby nauczyć sieć — ale każde ujęcie można „postawić” w tysiącu
sytuacji. W czasie treningu microWakeWord każde ujęcie wielokrotnie przerabia:

- **tło** — muzyka, hałas, rozmowy (AudioSet, Free Music Archive, Wasze nagrania tła) przy różnym
  stosunku sygnału do szumu (od −5 do 10 dB),
- **pogłos** — prawdziwe odpowiedzi impulsowe pomieszczeń (MIT RIR),
- **głośność, korektor (EQ), filtry pasmowe, lekkie zniekształcenie, przesunięcie wysokości**,
- **przesunięcie w czasie** — słowo raz wcześniej, raz później w oknie.

Nagrania domowników są w treningu powtarzane najczęściej (50 przebiegów augmentacji, najwyższa waga),
bo to one są najcenniejsze.

## Rozmnożenie głosu (`expand`) {#voice-expansion-expand}

Augmentacja zmienia otoczenie, ale nie głos. `expand` robi z każdego ujęcia treningowego kilka
„nowych osób”:

- **wysokość + formanty** razem (jakby krótszy lub dłuższy tor głosowy — trochę jak dziecko albo
  większy dorosły), w półtonach,
- **tempo** (szybciej / wolniej, bez zmiany wysokości).

Dla dorosłych przesunięcia idą w obie strony, dla dzieci bardziej w dół (ich głosy są już wysokie).
Domyślnie 6 wariantów na ujęcie:

```bash
wakeword -H households/dom expand --all --per-take 6
```

Pliki trafiają do `data/expanded/<słowo>/<osoba>/dad_003_far__p-1.5_t0.92.wav` (tu: −1,5 półtonu,
tempo 0,92). Rozmnażane są **tylko ujęcia treningowe** — test zostaje nietknięty, inaczej ocena
mierzyłaby model na prawie-kopiach tego, czego się uczył. Dlatego `expand` wymaga wcześniejszego
`split` (zrobi to za Ciebie `prepare`).

## Posłuchaj, zanim wyślesz do treningu (`preview`) {#listen-before-sending-to-training-preview}

```bash
wakeword -H households/dom preview dzarwis --count 8
```

Powstaje 8 plików w `data/preview/dzarwis/`, np.
`03_mum_002_quiet_rt0.5_eq150-6000_snr10_g-6_tv_wieczor.wav`:

| Fragment nazwy | Znaczenie |
|---|---|
| `rt0.5` | pogłos 0,5 s (`dry` = bez pogłosu) |
| `eq150-6000` | pasmo 150–6000 Hz (głośniczek, daleki mikrofon) |
| `snr10` | tło 10 dB ciszej niż mowa (`clean` = bez tła) |
| `g-6` | całość 6 dB ciszej |
| `tv_wieczor` | które nagranie tła (`pink` = szum zastępczy, gdy nie ma Waszych nagrań) |

Posłuchaj: czy to dalej brzmi jak ktoś mówiący słowo w prawdziwym pokoju? Jeśli Wasze nagrania tła
są głośniejsze od mowy we wszystkich przykładach, nagraj je ciszej lub z dalszej odległości.
Podgląd jest uproszczony — prawdziwą augmentację robi microWakeWord w treningu.

## Negatywy — czego augmentacja nie zastąpi {#negatives-what-augmentation-can-t-replace}

Model uczy się na dwóch rodzajach przykładów: **„to jest słowo”** i **„to nie jest słowo”**.
Augmentacja ujęć daje tylko te pierwsze. Negatywy pochodzą z:

| Zbiór | Skąd | Po co |
|---|---|---|
| `speech`, `dinner_party`, `no_speech` | gotowe cechy z Hugging Face (`kahrendt/microwakeword`) | setki godzin mowy, przyjęć, hałasu |
| `dinner_party_eval` | jw. | tylko do pomiaru fałszywych wybudzeń w czasie treningu |
| `sound_alikes` | synteza Waszych „brzmi podobnie” (`darwin`, `jarmark` …) | trudne negatywy — najbliżsi sąsiedzi słowa |
| `other_words` | **nagrania i synteza pozostałych słów domu** | „Wajana” nie budzi urządzenia z „Optimus Prime” |
| `background` | Wasze nagrania tła (`data/background/`) | Wasz telewizor i Wasza kuchnia |
| `false_wakes` | nagrania fałszywych wybudzeń (`data/false_wakes/<słowo>/`) | dodawane z czasem, patrz [09](09-iterating.md) |

`config` (i `prepare`) dobiera wagi automatycznie; plik `training_parameters.yaml` możesz
przejrzeć i zmienić — każda pozycja ma `sampling_weight` (jak często losowana) i `penalty_weight`
(jak bardzo karany błąd).

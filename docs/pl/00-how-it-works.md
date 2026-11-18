# 00. Jak to działa {#how-it-works}

[← Spis treści](index.md) · [Dalej: co przygotować →](01-what-you-need.md)

## Słowo wybudzające w Home Assistant Voice {#the-wake-word-in-home-assistant-voice}

Home Assistant Voice Preview Edition (i inne urządzenia ESPHome z `micro_wake_word`) cały czas
słucha mikrofonu, ale **nic nie wysyła** do Home Assistanta, dopóki nie usłyszy słowa
wybudzającego. Słucha go mały model sieci neuronowej (**microWakeWord**) uruchomiony bezpośrednio
na układzie ESP32-S3:

1. co 10 ms z dźwięku liczonych jest 40 cech (widmo w skali melowej),
2. co 30 ms model zwraca **prawdopodobieństwo**, że przed chwilą padło słowo,
3. urządzenie uśrednia ostatnie kilka wyników (**okno**, `sliding_window_size`, zwykle 5),
4. gdy średnia przekroczy **próg** (`probability_cutoff`, np. 0,97), urządzenie się wybudza.

Model ma kilkadziesiąt kilobajtów i rozpoznaje **jedno konkretne słowo**. Nie rozumie mowy —
to dlatego działa na mikrokontrolerze i dlatego trzeba go wytrenować osobno dla każdego słowa.

## Dlaczego nie da się „dotrenować” gotowego modelu {#why-you-can-t-fine-tune-an-existing-model}

Gotowe modele (`okay_nabu`, `hey_jarvis` …) są już **skwantyzowane** (liczby 8-bitowe) i
przerobione na wersję **strumieniową**. Z takiego pliku nie da się wrócić do wersji, którą można
dalej uczyć. Każde narzędzie — także to — trenuje model **od zera**:

- **nagrania domowników** (najcenniejsze, bo to Wasze głosy i Wasz akcent),
- **rozmnożone nagrania** (ten sam głos przesunięty wyżej/niżej, szybciej/wolniej),
- **dane syntetyczne** (tysiące wypowiedzi słowa z syntezatora mowy),
- **negatywy** — godziny mowy, muzyki i hałasu, na które model ma **nie** reagować.

Dobra wiadomość: ponieważ i tak trenujemy od zera, można wybrać **dowolne słowo** — także
„Dżarwis” wymawiane po polsku albo zupełnie nowe, np. „Wajana”.

## Słowo dla całej rodziny, nie dla jednej osoby {#a-word-for-the-whole-family-not-one-person}

Narzędzie opiera się na pliku **rodziny** (`household.yaml`):

- **osoby** — kto będzie mówił słowa (dorosły / dziecko),
- **słowa** — każde słowo ma listę osób, które go używają; słowo wspólne („Dżarwis”) nagrywają
  wszyscy, słowo osobiste („Optimus Prime”) tylko syn,
- **urządzenia** — które słowa działają na którym Voice PE (maksymalnie dwa, bo Voice PE ma dwa
  miejsca na asystenta, każde z jednym słowem).

Każde słowo jest trenowane osobno, na nagraniach **wszystkich swoich użytkowników**. Pozostałe słowa
domu trafiają do treningu jako negatywy — dzięki temu „Wajana” nie wybudzi urządzenia, które
słucha na „Optimus Prime”.

Rozpoznawanie, **kto** mówi, to osobny temat (np. integracja Speaker ID) — model słowa
wybudzającego ma tylko poprawnie reagować na wszystkich swoich użytkowników.

## Najważniejsze pojęcia {#key-terms}

| Pojęcie | Znaczenie |
|---|---|
| **Ujęcie (take)** | jedno nagranie słowa przez jedną osobę, ok. 1 s |
| **Wariant wypowiedzenia** | jak ujęcie zostało powiedziane: blisko, daleko, cicho, głośno, szybko, pytająco … |
| **FRR** (false rejection rate) | odsetek prawdziwych wypowiedzi, na które model **nie zareagował**; liczymy go osobno dla każdej osoby |
| **Fałszywe wybudzenia / h** | ile razy na godzinę model reaguje, choć nikt nie powiedział słowa (TV, rozmowa) |
| **Próg** (`probability_cutoff`) | wyższy = mniej fałszywych wybudzeń, ale więcej przegapionych słów |
| **Okno** (`sliding_window_size`) | ile kolejnych wyników jest uśrednianych; większe = stabilniej, ale wolniej |
| **Augmentacja** | nakładanie na nagranie hałasu tła, pogłosu pomieszczenia, zmiana głośności i barwy |
| **Rozmnożenie głosu** | z jednego ujęcia powstaje kilka „nowych mówców” (wysokość, formanty, tempo) |
| **Negatywy** | nagrania, na które model ma nie reagować: mowa, muzyka, cisza, podobnie brzmiące słowa |
| **Zbiór testowy** | 2–3 ujęcia każdej osoby odłożone na bok — model nigdy ich nie widzi w treningu, służą do uczciwej oceny |
| **Manifest** | plik JSON, który ESPHome czyta, aby załadować model `.tflite` |

## Cały proces w skrócie {#the-whole-process-at-a-glance}

```
Mac (to repozytorium)                         Komputer z kartą NVIDIA            Home Assistant
───────────────────────────────────────       ─────────────────────────          ──────────────
init / add-word / set-device  (plan)
record / import               (nagrania)
check                         (macierz osoba × słowo)
preview                       (odsłuch augmentacji)
prepare = split + expand + synthetic + config ──► train/train.sh  (kilka godzin)
                                              ◄── model .tflite
evaluate                      (FRR na osobę, fałszywe/h, próg)
export                        (manifest + YAML) ──────────────────────────────────► ESPHome OTA
```

Na Macu nic nie jest trenowane — tylko planowanie, nagrania, kontrola, przygotowanie danych, ocena i
eksport. Sam trening wymaga karty graficznej NVIDIA i działa na Linuksie.

# 12. Jak dobrze wytrenować słowo budzące — parametry i ich wpływ {#training-well}

Ten rozdział zbiera w jednym miejscu: ile i jakich nagrań potrzeba, co robi każdy parametr treningu, jak czytać
wyniki i co zmienić, gdy model przegapia słowo albo budzi się sam. Liczby to wartości domyślne z kodu
(`wakeword/training_config.py`, `train/make_features.py`, `wakeword/synthetic.py`, `wakeword/export.py`).

## 12.1 Dwa błędy, jedna równowaga {#two-mistakes-one-balance}

Każdy model słowa budzącego myli się na dwa sposoby:

- **przegapienie** (FRR — odsetek wypowiedzeń, na które nie zareagował): domownik mówi słowo, nic się nie dzieje;
- **fałszywe wybudzenie** (FAPH — fałszywe na godzinę): urządzenie budzi się samo od telewizora, rozmowy, muzyki.

Prawie każdy parametr przesuwa model w jedną stronę: mniej fałszywych wybudzeń kosztem większej liczby przegapień
albo odwrotnie. Dobry trening to **więcej i lepszych danych**, które poprawiają oba błędy naraz; parametry tylko
wybierają punkt równowagi. Cele studia:

| Miara | Cel | Gdzie widać |
|---|---|---|
| AVR (średnia rozpoznawalność w walidacji) | ≥ 0,90 (≥ 0,95 bardzo dobrze) | Postęp na żywo, kafelek i wykres |
| FAPH w walidacji | ≤ 0,5 / h (≤ 1 akceptowalnie) | Postęp na żywo |
| Rozpoznawanie bez fałszywych wybudzeń | ≥ 80 % | Postęp na żywo |
| FRR każdej osoby (test domowy) | ≤ 5 % (1 na 20 wypowiedzeń) | Modele → kolumna Domownicy |
| Fałszywe wybudzenia w domu | ≤ 1 na dobę | Modele → Domownicy; Dom → Fałszywe wybudzenia |

## 12.2 Wybór słowa {#choosing-the-word}

- **2–4 sylaby, wyraźne spółgłoski** („Hej Jarvis”, „Hej Robo”). Jedna sylaba budzi się od wszystkiego.
- **Nie słowo z codziennej mowy** i nie początek częstego zwrotu („Hej, a może…”). Dodaj w słowie **podobne
  brzmienia** (`hej harwis`, `hej darwin`) — staną się negatywami, model nauczy się ich nie słuchać.
- **Jak brzmi** w każdym języku głosów syntetycznych: polski zapis (`hej dżarwis`) daje polski akcent, angielski
  (`hey jarvis`) — angielski. Pisownie to dane treningowe, nie tylko etykieta.
- Słowo dla dziecka — najlepiej jego własne, krótkie i łatwe do wymówienia; nagrania dziecka mają większą wagę
  (preset **Rodzina**).

## 12.3 Ile nagrań i jakich {#how-many-recordings-and-which}

Cele w Ustawieniach → Cele i język (domyślnie):

| Grupa | Nagrań na słowo | Odłożone do testu |
|---|---|---|
| Dorosły | **12** (dobrze 12–15) | 3 |
| Dziecko | **18** (dobrze 18–25) | 3 |

**Więcej różnych ujęć daje więcej niż więcej takich samych.** Rejestrator i satelity prowadzą przez warianty:
blisko i daleko od urządzenia, cicho i głośno, szybko i wolno, pytająco, zmęczonym głosem, wesoło, z tłem
(telewizor, rozmowa), z drugiej strony pokoju. Nagrywaj **tym urządzeniem, które ma słuchać** (Voice PE przez
Wake Word Recorder) — mikrofon i pogłos pokoju trafiają wtedy do danych. 3 ujęcia każdej osoby są odkładane do
testu i nie biorą udziału w treningu — dzięki nim test domowy mówi prawdę.

Z ok. 15 nagrań na osobę powstają tysiące przykładów: rozmnożenie głosu (`expand`: wysokość, barwa, tempo —
6 wariantów na ujęcie), augmentacja (tło, pogłos, EQ, głośność) i 50 przebiegów augmentacji na zbiór nagrań rodziny.

## 12.4 Tło domu i fałszywe wybudzenia {#home-background}

To, na co model **nie ma** reagować, pochodzi z publicznych zbiorów (mowa, przyjęcie, cisza i szum — ok. 20 GB,
pobierane przy pierwszym treningu) i z **Twojego domu**:

- **Tło domu** — 30 min na pokój przez satelitę („Nasłuchuj 30 min” w Wake Word Recorder): telewizor, obiad,
  dzieci. Trafia do treningu jako negatyw i do testu domowego (fałszywe wybudzenia na dobę).
- **Fałszywe wybudzenia** — nagrania sytuacji, w których model obudził się sam (rozdział 9), w zbiorze
  `false_wakes` z największą wagą wśród nagrań domu. To najskuteczniejszy sposób na „głupka, który włącza się za
  szybko”.

## 12.5 Dane syntetyczne {#synthetic-data}

| Źródło | Ile (domyślnie) | Po co |
|---|---|---|
| Generator angielski (libritts, setki głosów) | 20 000 wypowiedzeń | różnorodność głosów, słowo dla gości |
| Głosy Piper w językach pisowni | 300 na głos i zapis | akcent języka (polskie głosy czytają `hej dżarwis`) |
| Podobne brzmienia (negatywy) | 4 000 | uczą odrzucać słowa podobne |
| ElevenLabs (opcjonalnie) | 5 na głos i zapis (do 50), 10 wariantów mówienia | bardzo naturalne głosy, także polskie |

Tempo i wariant mowy Piper są losowane (`length_scale` 0,8–1,25, `noise_scale` 0,5–0,9). Odsłuchaj próbki
(Głosy syntetyczne → Próbki) przed treningiem — głos, który przekręca słowo, wyłącz (Piper) albo odznacz
(ElevenLabs).

## 12.6 Parametry treningu (Trening → Parametry i start) {#training-parameters}

### Kroki (`steps`, domyślnie 20 000, zakres 100–500 000) {#steps}

Ile partii po 128 przykładów model zobaczy. Mało kroków — model niedouczony (niski AVR, wykres jeszcze rośnie).
Za dużo — strata czasu (studio pokazuje pozostały czas w Postępie na żywo), czasem przeuczenie na syntetyce. Kolejny trening
**kontynuuje** od zapisanego stanu o podaną liczbę kroków; powyżej ~80 000 kroków łącznie więcej kroków rzadko
pomaga — pomagają dane. Porada po treningu proponuje +20 000, gdy wynik wciąż rósł.

### Waga negatywów (`negative_class_weight`, domyślnie 20, zakres 1–200) {#negative-weight}

Jak bardzo kara za fałszywe wybudzenie przeważa nad karą za przegapienie. **Więcej** (30–60): mniej fałszywych
wybudzeń, więcej przegapień, model „ostrożniejszy”. **Mniej** (5–15): czulszy, częściej budzi się sam.
Zmieniaj o 30–50 %, gdy porada tak podpowie; jeśli oba błędy są złe — potrzeba danych, nie wagi.

### Tempo nauki (`learning_rates`) {#learning-rates}

Domyślnie trzy fazy **0,001 → 0,0003 → 0,0001** (50/30/20 % kroków); dalszy trening od zapisanego stanu:
**0,0003 → 0,0001** (50/50). Własne: 1–4 wartości (2 → 50/50, 3 → 50/30/20, 4 → 40/30/20/10), zakres
0,000001–0,01. Za duże tempo: AVR skacze między walidacjami (porada „niestabilny”); za małe: wolna nauka.
Fazy widać jako pasy na wykresie postępu.

### Wagi zbiorów (`sampling_weight`) i presety {#set-weights}

Jak często trening sięga do każdego zbioru. **+** uczy, kiedy reagować; **−** — kiedy nie reagować (zakres 0–50,
puste = domyślne).

| Zbiór | Domyślnie | Rodzina | Neutralnie | Co daje więcej |
|---|---|---|---|---|
| + Nagrania rodziny (`real`) | 3 | **6** | 2 | lepsze rozpoznawanie domowników, także dzieci |
| + Rozmnożone nagrania (`expanded`) | 2 | **4** | 1 | odporność na zmianę głosu (katar, szept, pośpiech) |
| + ElevenLabs | 2,5 | 1,5 | **3** | naturalne obce głosy |
| + Synteza Piper (`synthetic`) | 2 | 1 | **3** | słowo dla każdego (goście), akcent języka |
| − Brzmi podobnie (`sound_alikes`) | 3 | 3 | 3 | mniej wybudzeń od podobnych słów |
| − Inne słowa domu (`other_words`) | 4 | 4 | 4 | słowa domu nie budzą się nawzajem |
| − Tło domu (`background`) | 3 | **8** | 3 | mniej wybudzeń od Waszego TV i rozmów |
| − Fałszywe wybudzenia (`false_wakes`) | 5 | **8** | 5 | koniec z konkretnymi samoczynnymi wybudzeniami |
| − Obca mowa (`speech`) | 10 | 10 | 10 | odporność na rozmowę |
| − Gwar, impreza (`dinner_party`) | 10 | 10 | 10 | odporność na hałas wielu głosów |
| − Hałas bez mowy (`no_speech`) | 5 | 5 | 5 | odporność na muzykę i szum |

Preset **Rodzina** ustawia też wagę negatywów 30: model bardzo dobrze reaguje na domowników i prawie nie budzi
się sam w domu (gorzej na gości). **Neutralnie** (waga 20): słowo dla każdego, mniej dopasowane do rodziny.
Dla domu z dziećmi i telewizorem zacznij od **Rodziny**.

### Augmentacja (stała, `train/make_features.py`) {#augmentation}

Każde nagranie trafia do treningu jako 3,2-sekundowy klip, z prawdopodobieństwem: tło 0,75 (SNR −5…10 dB),
pogłos pomieszczenia (RIR) 0,5, zmiana głośności zawsze, EQ / zniekształcenie / zmiana wysokości / filtr / szum
kolorowy po 0,1. Długie negatywy (tło domu) są cięte na kawałki po 3 s. Powtórzenia zbioru w augmentacji:
nagrania rodziny 50×, rozmnożone 5×, synteza 2×, podobne brzmienia 2×, inne słowa 3×, fałszywe wybudzenia 3×.

### Tylko przelicz (bez treningu) {#convert-only-no-training}

Konwertuje najlepsze dotąd wagi do modelu `.tflite` i robi test końcowy — gdy trening przerwano albo trzeba
odtworzyć model.

## 12.7 Parametry wdrożenia (Trening → Ocena i eksport) {#deployment-parameters}

| Parametr | Domyślnie | Wpływ |
|---|---|---|
| `probability_cutoff` (próg) | 0,97 (studio podpowiada próg z testu końcowego) | wyżej = mniej fałszywych wybudzeń, więcej przegapień; zmiana o 0,01–0,02 to już dużo |
| `sliding_window_size` (okno) | 5 | ile kolejnych ocen modelu jest uśrednianych przed porównaniem z progiem; większe = mniej krótkich „pików” od pojedynczych dźwięków, minimalnie wolniejsza reakcja |
| `feature_step_size` | 10 ms | krok cech audio (jak w treningu — nie zmieniaj) |
| `tensor_arena_size` | 30 000 | pamięć modelu na urządzeniu |

Próg wybieraj z tabeli testu końcowego (Postęp na żywo) i z testu domowego (Modele → Domownicy): najniższy próg,
przy którym każda osoba ma FRR ≤ 5 %, a fałszywych wybudzeń jest ≤ 1 na dobę. Studio wysyła model i manifest
prosto do `/config/esphome/wake_words/` przez Home Assistant.

## 12.8 Czytanie wyników {#reading-the-results}

- **Wykres** (AVR i FAPH co 500 kroków): AVR powinien rosnąć i wypłaszczać się powyżej 0,90; FAPH spadać.
  AVR wciąż rośnie na końcu → więcej kroków. AVR skacze → mniejsze tempo nauki.
- **Test końcowy** (tabela próg / przegapione / fałszywe na godzinę, AUC): zielony wiersz to rekomendowany próg.
- **Modele**: każdy trening zostaje jako osobny model. Ranking **Domownicy** (nagrania odłożone + tło domu) jest
  ważniejszy niż **Neutralnie** (głosy syntetyczne). „Cel osiągnięty” albo „×2,3 od celu” mówi, jak daleko.
  **Wybierz** ustawia model, od którego zacznie następny trening; **Od zera** — trening bez starego stanu.
- **Porada** po teście końcowym mówi, co zmienić; **Zastosuj** wpisuje kroki i wagę do formularza.

## 12.9 Przepisy na typowe problemy {#recipes-for-common-problems}

| Objaw | Przyczyna | Co zrobić (po kolei) |
|---|---|---|
| Budzi się sam od telewizora / YouTube | za mało negatywów z tego domu | nagraj tło 30 min w tym pokoju (TV włączony) → dodaj fałszywe wybudzenia → preset Rodzina → waga negatywów +30–50 % → próg +0,01 |
| Budzi się przy rozmowie, „łapie” podobne słowa | podobne brzmienia nie są w danych | dopisz je w słowie (Brzmi podobnie) → przygotuj ponownie |
| Dziecko musi powtarzać 2–3 razy | za mało nagrań dziecka, za mała waga | 18–25 nagrań dziecka w różnych wariantach → preset Rodzina (`real` 6) → próg −0,01 |
| Jedna osoba ma FRR 15 %, reszta 0 % | jej ujęcia są jednolite albo z innego mikrofonu | dograj jej warianty przez satelitę, z którego korzysta |
| AVR < 0,75 po całym treningu | problem z danymi, nie z parametrami | odsłuchaj nagrania (przester, cisza, inne słowo), próbki syntetyczne (głosy przekręcające słowo) |
| AVR skacze ±0,4 między walidacjami | za duże tempo nauki | tempo 0,0003, 0,0001 → kontynuuj |
| Dobry test końcowy, w domu słabo | test na syntetyce nie odpowiada domowi | ranking Domownicy, tło domu do testu, model ze studia zamiast pierwszego |

### Przykład z życia: pokój dziecka, listopad 2026 {#real-example}

Model „Hej Jarvis” wytrenowany wcześnie (bez tła domu i bez fałszywych wybudzeń, próg 0,97, okno 5) w ciągu
6 dni obudził się sam **39 razy** (≈ 6,5 na dobę, cel ≤ 1), głównie od YouTube („Dziękuję za oglądanie”, muzyka)
i krótkich dźwięków bez mowy; prawdziwych wywołań było 4. Gotowe modele „Okay Nabu” i „Hey Jarvis” w innych
pokojach miały 1–3 fałszywe wybudzenia w tym czasie. Kolejność naprawy: 30 min tła w tym pokoju z YouTube →
nagrania fałszywych wybudzeń jako `false_wakes` → preset Rodzina → nowy model z najlepszym wynikiem w rankingu
Domownicy → próg z testu domowego (zwykle 0,98–0,99).

## 12.10 Kolejność pracy {#the-order-of-work}

1. Rodzina: osoby, słowo (pisownie, podobne brzmienia), urządzenia → **Zapisz**.
2. Nagrania: 12 (dorośli) / 18 (dzieci) ujęć przez satelitę w pokoju, w którym słowo ma działać; 30 min tła.
3. Głosy: odsłuchaj Piper, opcjonalnie ElevenLabs.
4. **Przygotuj** → **Rozpocznij trening** (preset Rodzina, 20 000 kroków).
5. Test końcowy i porada → ewentualnie **Zastosuj** i kontynuuj.
6. **Test domowy** (Modele) → wybierz najlepszy model w rankingu Domownicy → **Eksport** z progiem z testu.
7. Tydzień obserwacji fałszywych wybudzeń → nagrania jako `false_wakes` → kolejny trening od najlepszego modelu.

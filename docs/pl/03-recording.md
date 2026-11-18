# 03. Nagrania domowników {#household-recordings}

[← Plan rodziny](02-plan-your-household.md) · [Spis treści](index.md) · [Dalej: augmentacja i negatywy →](04-augmentation-and-negatives.md)

## Ile nagrań {#how-many-recordings}

Nie trzeba nagrywać pół godziny. Wystarczy **kilkanaście ujęć na osobę na słowo**, ale **różnie
powiedzianych** — resztę zrobią rozmnożenie głosu i augmentacja (tysiące wariantów).

| Kto | Ujęć na słowo (`targets`) | Dlaczego |
|---|---|---|
| Dorosły | 12 | głos stabilny |
| Dziecko | 18 | głos zmienia się z dnia na dzień, mówi mniej równo |

Z tych ujęć **3 na osobę** (`held_out`) narzędzie odłoży do testu — model ich nie zobaczy, a potem
sprawdzimy na nich, czy rozpoznaje każdą osobę.

W rodzinie z przykładu to razem: „Dżarwis” 5 osób (2×12 + 3×18 = 78 ujęć), „Optimus Prime” 2 osoby
(30), „Wajana” 3 osoby (48). Jedna osoba nagrywa wszystkie swoje słowa w 10–20 minut.

## Warianty wypowiedzenia {#variants}

Rejestrator prowadzi każdą osobę przez kolejne warianty — każde ujęcie jest powiedziane inaczej:

| Wariant | Instrukcja |
|---|---|
| `near` | pół metra od telefonu, normalnie |
| `far` | z drugiego końca pokoju (3–4 m) |
| `quiet` | cicho, jakby ktoś obok spał |
| `loud` | głośno, jak z innego pokoju |
| `fast` | szybko, w biegu |
| `slow` | powoli i wyraźnie |
| `question` | pytająco, niepewnie |
| `tired` | zmęczonym głosem |
| `cheerful` | wesoło, z uśmiechem |
| `background` | przy włączonym TV lub muzyce |
| `other_side` | bokiem lub tyłem do telefonu |
| `normal` | tak jak na co dzień |

Po 12 ujęciach kolejność zaczyna się od nowa. Wariant zapisuje się w nazwie pliku
(`son_004_fast.wav`), a `check` podpowiada, których wariantów jeszcze brakuje.

## Gdzie nagrywać {#where-to-record}

- **Najlepiej tam, gdzie stoi urządzenie**: w pokoju syna dla „Optimus Prime”, w salonie dla słowa
  wspólnego. Akustyka pokoju to część danych.
- Telefon połóż mniej więcej tam, gdzie stoi Voice PE (półka, komoda), a nie trzymaj przy ustach.
- Nie wyłączaj w domu wszystkiego na siłę — trochę zwykłego tła jest dobre. Przesterowania i
  krzyku do mikrofonu nie.

## Rejestrator w przeglądarce {#browser-recorder}

```bash
wakeword -H households/dom record
```

```
Recorder for 'dom' — open on a phone or computer in the same network:
  https://192.168.1.20:8443/
The browser warns about the certificate (it is your own) — accept it once.
```

1. Otwórz adres na telefonie (ta sama sieć Wi-Fi). Przeglądarka ostrzeże o certyfikacie —
   to Twój własny certyfikat, wygenerowany przy pierwszym uruchomieniu; zaakceptuj go
   (Safari: *Pokaż szczegóły → odwiedź tę stronę*; Chrome: *Zaawansowane → Przejdź do …*).
   Telefony udostępniają mikrofon tylko stronom HTTPS — dlatego certyfikat.
2. **Kim jesteś?** — wybierz siebie.
3. **Twoje słowa** — lista Twoich słów z postępem (np. `Nagrane: 4 z 18`).
4. Wybierz słowo. Na ekranie: **Powiedz: „Dżarwis”** i instrukcja wariantu (np. *Odejdź na drugi
   koniec pokoju…*).
5. **Nagrywaj** → powiedz słowo → **Stop** (albo samo zatrzyma się po 6 s).
6. **Odsłuchaj** → **Zapisz** albo **Nagraj ponownie**.
7. Po zapisaniu rejestrator od razu ocenia nagranie: *Za cicho*, *Za głośno (przester)*, *Nic nie
   słychać*. Złe ujęcie usuń z listy pod spodem i nagraj jeszcze raz.

Rejestrator zapisuje pliki jako WAV 16 kHz mono, przycięte z ciszy (z marginesem 0,25 s) i
znormalizowane, do `data/real/<słowo>/<osoba>/`.

Bez telefonu: `wakeword record --http` i otwórz `http://localhost:8443/` na tym samym komputerze
(mikrofon przez HTTP działa tylko na `localhost`).

## Nagrywanie przez Voice PE (integracja Wake Word Recorder) — najlepsze dane {#recording-through-voice-pe-wake-word-recorder-in}

Najlepiej, gdy nagrania pochodzą z **tych samych mikrofonów**, które potem będą słuchać słowa:
Voice PE ma dwa mikrofony i procesor dźwięku (tłumienie echa i szumu), telefon brzmi inaczej.
Integracja **Wake Word Recorder** ([osobne repozytorium](https://github.com/witold-gren/home-assistant-wake-word-recorder)) nagrywa ujęcia przez
satelity Home Assistant:

1. Zainstaluj integrację (HACS — repozytorium niestandardowe, opis w jej README) i zrestartuj
   Home Assistant.
2. Utwórz plik rodziny (`household.yaml`) w folderze konfiguracji HA, np. `/config/wakeword` (na Macu z udziałem Samba:
   `wakeword -H /Volumes/config/wakeword init …`).
3. **Ustawienia → Urządzenia i usługi → Dodaj integrację → Wake Word Recorder**, folder z
   household.yaml: `/config/wakeword`.
   Jeśli pliku jeszcze nie ma, integracja zaproponuje jego utworzenie z osobami z HA (encje
   `person`); zaznaczasz tylko dzieci, a słowa dodajesz potem `wakeword add-word`.
4. Na urządzeniu „Wake Word Recorder” wybierz **Osobę**, **Słowo wybudzające** i **Satelitę**,
   naciśnij **Rozpocznij nagrywanie** (albo akcja `wake_word_recorder.start_session`).

Co się dzieje:

- satelita zostaje przełączony na potok **„Wake word recording”** (integracja tworzy go sama, z głosem
  Twojego domyślnego asystenta); po sesji wraca poprzedni potok — także po restarcie HA w trakcie,
- urządzenie mówi np. *„Nagranie 4 z 18. Odejdź na drugi koniec pokoju. Powiedz: Dżarwis.”* i
  słucha **bez słowa wybudzającego**,
- nagranie jest sprawdzane (cisza, za cicho, przester, za krótko/długo); dobre trafia do
  `data/real/<słowo>/<osoba>/` z nazwą jak w rejestratorze, złe trzeba powtórzyć
  (*„Za cicho. Jeszcze raz…”*),
- sesja kończy się po osiągnięciu celu osoby (albo `count` nagrań), po 3 razach ciszy, po 6 złych
  nagraniach z rzędu lub po **Zakończ nagrywanie**,
- `data/real/recordings.csv` zapisuje, które urządzenie nagrało które ujęcie,
- czujnik `sensor.wake_word_recorder_status` pokazuje postęp (osoba, słowo, `done`/`target`, ostatni
  plik, problemy).

Nagrania widzisz od razu na Macu: `wakeword -H /Volumes/config/wakeword check`. Oba sposoby
nagrywania można łączyć — Voice PE daje realizm, telefon dodatkową różnorodność.

Uwaga techniczna: w firmware Voice PE wykrywanie słowa słucha kanału 1 mikrofonów (wzmocnienie ×4),
a do Home Assistanta trafia strumień asystenta. Wzmocnienie nie ma znaczenia (nagrania są
normalizowane), a dźwięk przechodzi przez ten sam procesor XMOS — to wciąż znacznie bliżej
rzeczywistości niż telefon.

## Import nagrań z Dyktafonu lub starych plików {#importing-recordings-from-voice-memos-or-old-fil}

Każda osoba może też nagrać ujęcia Dyktafonem w iPhonie (jedno słowo = jedno nagranie) i przesłać
pliki. Import przyjmie `.m4a`, `.mp3`, `.wav`, `.flac` … (potrzebny `ffmpeg`):

```bash
wakeword -H households/dom import dzarwis --speaker dad ~/Downloads/dzarwis_*.m4a
```

```
/Users/…/dzarwis_1.m4a → dad_000_imported.wav
/Users/…/dzarwis_2.m4a → dad_001_imported.wav
```

Importowane ujęcia mają wariant `imported`. Zadbaj sam o to, by były różnie powiedziane.

## Kontrola: macierz osoba × słowo {#checking-the-speaker-word-matrix}

```bash
wakeword -H households/dom check
```

```
           dzarwis        optimus_prime  wajana
dad        13/12 ✓        0/12           —
mum        0/12           —              0/12
son        0/18           0/18           —
daughter1  1/18           —              0/18
daughter2  0/18           —              0/18

mum / dzarwis: 12 more take(s) — e.g. near, far, quiet, loud …
…
problem: son_003_loud.wav (optimus_prime): clipped
```

- `13/12 ✓` — osoba ma komplet dobrych ujęć,
- `—` — ta osoba nie używa tego słowa,
- `problem:` — ujęcie do poprawy: `no_speech` (cisza), `too_short` (ucięte), `too_long` (zdanie
  zamiast słowa), `too_quiet`, `clipped` (przester), `unreadable`,
- `not a take` — plik w folderze nagrań, który nie pasuje do nazewnictwa (usuń lub zmień nazwę).

`check` kończy się kodem 0 dopiero, gdy wszystko jest kompletne — `prepare` bez `--force` nie
ruszy wcześniej.

## Nagrania tła domu (opcjonalne, ale warte 10 minut) {#household-background-recordings-optional-but-wor}

**Najlepiej przez Voice PE:** w integracji Wake Word Recorder wybierz **Satelitę do nagrania dźwięków
domu** i naciśnij **Nasłuchuj 30 min** (albo akcja `wake_word_recorder.start_background` z `minutes`). Urządzenie po cichu nagrywa przez
30 minut do `data/background/<satelita>_<data>.wav` — dokładnie to, co słyszy jego mikrofon.

Telefonem:

Połóż telefon tam, gdzie stoi urządzenie, i nagraj 10–30 minut zwykłego życia: TV, obiad, rozmowa,
zmywarka. **Nikt nie mówi w tym czasie słowa wybudzającego.** Pliki (dowolny format, przekonwertuj
`ffmpeg -i nagranie.m4a -ac 1 -ar 16000 tv.wav`) wrzuć do:

```
households/dom/data/background/tv_wieczor.wav
households/dom/data/background/obiad.wav
```

Służą do trzech rzeczy: jako prawdziwe tło w podglądzie augmentacji, jako negatywy w treningu i do
pomiaru fałszywych wybudzeń na godzinę w ocenie.

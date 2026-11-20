# Dostosowanie do wspólnego standardu {#standard}

Studio słów budzących jest jedną z pięciu aplikacji, które od 16–17 listopada 2026 obsługuje się **tak samo**:
studio słów budzących, studio trenera Assist Routera i Piper Voice Cloner (maszyna z GPU) oraz Edytor Home Dashboard
i Edytor Assist Router (panele w Home Assistant). Zasady są w jednym pliku: `~/Home Assistant/standards/gpu-studio.md`
(wersja angielska `gpu-studio.en.md`, także na domowej stronie dokumentacji jako „Standard studia na maszynie GPU”). Ta strona
zbiera wszystko, co w tym repozytorium zmieniono, żeby je spełnić.

## W skrócie {#in-short}

| Obszar | Rozdział standardu | Co się zmieniło |
|---|---|---|
| Polecenia `make` | §2 | te same nazwy co w innych aplikacjach, trzy grupy, adres maszyny w jednym pliku, Python przez uv |
| Wypróbowanie na Macu | §8b | `make demo` — wystarczy Docker Desktop, lekki obraz demo w 20 s |
| Docker | §3 | osobne etapy: dokumentacja, demo, studio; samotesty; instalator wyłącza stare usługi na tym samym porcie |
| Logowanie | §4 | login i hasło jak w Piper Voice Cloner, sesja 30 dni, przerwa po 5 błędach |
| Wygląd i pomoc | §5 | jeden `?` do dokumentacji, okienka pomocy, zwijanie kolumn |
| Przewodnik i samouczki | §5a | przewodnik po studiu przy pierwszym otwarciu, 26 samouczków z ⚙, „Pokaż krok po kroku” w `?` |
| Wyłączanie maszyny | §6 | przez Home Assistant, samo po treningu z odliczaniem |
| Wydajność | §9a | studio się nie zawiesza: limity czasu, brak odpytywania w tle, długie listy po kawałku |
| Dokumentacja | §8 | strona MkDocs w PL i EN, w studiu i na domowej stronie dokumentacji, budowana w Dockerze |
| Testy | §9 | testy każdej zmiany, osobno testy obrazów Dockera |

## Polecenia make {#make-commands}

`make help` (po polsku albo angielsku, wg `$LANG`) zaczyna się od trzech grup, takich samych w każdej aplikacji:

| Grupa | Polecenia | Czego wymaga |
|---|---|---|
| 1. Start | `help`, `demo`, `demo-clean`, `docs`, `docs-serve`, `doctor` | tylko Docker Desktop |
| 2. Maszyna z GPU | `install`, `deploy`, `login`, `logs`, `status`, `stop`, `uninstall`; na maszynie `docker-up`, `docker-down`, `docker-logs`, `docker-shell` | `ssh` i `rsync` (są w macOS) i adres maszyny |
| 3. Rozwój | `setup`, `demo-local`, `test`, `test-browser`, `test-docker`, `test-all`, `lint`, `format`, `docs-build`, `screenshots`, `icons`, `clean` | uv (sam pobiera Pythona 3.12), Chrome do testów w przeglądarce |

Potem są grupy tylko tego narzędzia: rodzina i nagrania na Macu oraz trening i wyniki bez studia. Stary panel
(`ui`, `ui-remote`) zniknął w 1.0.0.

Co zmieniono po drodze:

- **Adres maszyny w jednym miejscu dla wszystkich studiów**: `~/.config/gpu-studio/host.mk` z
  `GPU_HOST = użytkownik@adres`. Wyjątki tej aplikacji (foldery danych) są w `Makefile.local`, poza gitem. Bez
  adresu polecenia mówią, gdzie go wpisać. W repozytorium nie ma prywatnych adresów.
- **Nowe polecenia**: `install` (pierwsza instalacja z Maca), `login` (pokazuje login i hasło z maszyny), `logs`,
  `status` (odpowiedź studia, karta graficzna w kontenerze), `doctor` (sprawdza Dockera, git, ssh, rsync, maszynę,
  uv, Chrome, ffmpeg i folder rodziny — niczego nie instaluje).
- **Środowisko programisty przez uv**: `make setup` tworzy `.venv` przez `uv venv --python 3.12`, bez
  `brew install python`. Bez uv pojawia się komunikat z poleceniem instalacji.
- **Testy**: `make test` nie buduje obrazów; `make test-docker` buduje obraz demo i dokumentacji naprawdę (pytest z
  markerem `docker`); `make test-all` = `lint` + `test` + `test-browser` + `test-docker`; `make format` poprawia i
  formatuje kod; `make lint` sprawdza także formatowanie.
- **Jedna nazwa na jedną rzecz**: usunięte `make studio` i `make studio-docker` (dublowały `demo-local` i `demo`),
  `make docs-pages` (stare strony HTML) i plik `docker/compose.cpu.yaml` (kopie w `backup/`).
- Test `tests/test_makefile.py` pilnuje: oba opisy każdego polecenia, kolejność grup i ich polecenia, brak `setup` w
  grupach 1 i 2, uv, znaczenie `test`/`test-docker`/`test-all`, porty, brak aliasów.

## Wypróbowanie na Macu {#try-on-a-mac-summary}

- `make demo` buduje **lekki etap `demo`** z `docker/Dockerfile` (tylko zależności narzędzia, bez TensorFlow,
  CUDA, kompilatorów i `apt-get`) i uruchamia go na `http://localhost:8766`, login `demo`/`demo`. Wymyślona
  rodzina i udawane GPU, nic nie trafia do Home Assistanta ani na maszynę.
- Pierwsza wersja budowała demo z obrazu GPU bez treningu: **23 minuty i 1,5 GB**. Osobny etap: **18 sekund i
  426 MB**, następne budowy w kilka sekund.
- Ctrl+C zatrzymuje i usuwa kontener (sprawdzone: w mniej niż sekundę), `make demo-clean` usuwa obrazy, bez
  Dockera — komunikat „zainstaluj i uruchom Docker Desktop”.
- `docs/studio_demo.py` dostał `--host` (w kontenerze `0.0.0.0`); demo bez Dockera to `make demo-local`.
- Każdy port jest inny we wszystkich aplikacjach (tabela w standardzie): studio 8765, demo 8766, dokumentacja 9766.
- Sekcja [Wypróbuj na Macu](11-studio.md#try-on-a-mac) w README (PL i EN) i w rozdziale 11.

## Docker na maszynie z GPU {#docker}

- `docker/Dockerfile` ma etapy: `docs` (buduje dokumentację `mkdocs build --strict`), `docs-site` (sama strona do
  `make docs-build`), `demo` (Mac) i ostatni — studio z TensorFlow i CUDA, który buduje `docker compose`.
- Samotest importów po każdej warstwie — zepsuty obraz nie powstaje.
- `docker/install-ubuntu.sh` wyłącza stare usługi tej aplikacji (`wakeword*` w systemd użytkownika) i nazywa
  program, który zajmuje port 8765, zamiast z nim walczyć.
- `.dockerignore` pomija `site`, `Makefile.local`, dane i sekrety.

## Pierwsze prawdziwe uruchomienie na Ubuntu {#first-run-on-ubuntu}

18 listopada 2026 trzy aplikacje pierwszy raz wystartowały na maszynie z RTX 4090. Błędy, które przeszły
wszystkie testy na Macu, i co się zmieniło w studiu:

- **TensorFlow nie widział karty**, choć `nvidia-smi` w kontenerze ją pokazywał: `libtensorflow_framework.so.2`
  z TensorFlow 2.21 nie ma folderu `nvidia/cusolver/lib` w swoich ścieżkach i zabrakło `libcusolver.so.11`.
  Trening szedłby na procesorze. Obraz ustawia `LD_LIBRARY_PATH` na ten folder, a budowa sprawdza plik. Do tego
  torch z indeksu CUDA 12 (jedna rodzina CUDA w obrazie zamiast 12 i 13).
- **Sprawdzenie karty liczy na karcie**: instalator i `make status` mnożą macierz w TensorFlow
  (`docker/install-ubuntu.sh --gpu-check`), nie tylko pytają `nvidia-smi`.
- **Compose buduje etap z nazwy** (`target: studio`), a `/api/health` mówi, kto odpowiada (`app`, `mode`, `version`)
  — u Pipera na maszynie wystartowało demo, bo compose wziął ostatni etap.
- **Prawdziwy skrypt w teście**: runner uruchamia prawdziwe `train/train.sh` tą samą drogą co studio
  (w wariancie, który kończy się przed instalacją) — log nie jest pusty, kod wyjścia nie jest 0.
- **Instalator**: `$(id -un)` zamiast `$USER`, sterownik musi odpowiadać i mieć co najmniej 525, testy na
  „udawanej maszynie” dla każdego brakującego elementu; nowe `make stop` i `make uninstall`.
- **Kopia przed aktualizacją**: `docker/config` i `docker/.env` z maszyny w `~/backup/` (prawa 600).

## Logowanie {#login}

Jak w Piper Voice Cloner: `WAKEWORD_UI_AUTH=użytkownik:hasło` w `docker/config/env` (tworzy go instalator,
prawa 600), podpisana sesja na 30 dni, po 5 błędnych hasłach z jednego adresu 60 s przerwy. `make login` pokazuje
dane z maszyny. Zastąpiło token dostępu starego panelu.

## Wygląd i pomoc {#look-and-help}

- **Jeden `?` w pasku górnym** otwiera dokumentację (w studiu pod `/docs/`, działa bez internetu).
- **`?` przy karcie** otwiera małe okienko z opisem tej jednej funkcji obok przycisku — zamyka je ✕, Esc, klik
  obok, ten sam `?` albo zmiana widoku; ma link „Więcej w przewodniku” do kotwicy rozdziału. Wcześniej każdy `?`
  przerzucał na stronę dokumentacji.
- Usunięte: `?` przy polach treningu (pola mają podpowiedzi) i stare okno „Jak trenować?”.
- **Zwijanie kolumn**: ‹ obok wyszukiwarki zwija lewą kolumnę, › u góry prawej — prawą; zostaje pasek 28 px z
  przyciskiem rozwinięcia. Skróty Ctrl/⌘+B (lewa) i Ctrl/⌘+Alt+B (prawa). Przeglądarka pamięta stan, a w oknie
  węższym niż 900 px prawa kolumna startuje zwinięta.

## Wyłączanie maszyny {#power-off}

- Przycisk „Wyłącz maszynę” i opcja „wyłącz po zakończeniu” — przez przełącznik maszyny w Home Assistant
  (`switch.turn_off`); włącza ją zawsze Home Assistant.
- Po treningu (udanym albo z błędem, nigdy po „Zatrzymaj”) 120 s odliczania w pasku górnym z „Anuluj”; ocena,
  eksport albo polecenie w trakcie wstrzymują odliczanie; restart kontenera je kasuje; błąd wyłączenia widać w
  pasku. Pole wyłączania jest też przy „Rozpocznij trening”.

## Przewodnik i samouczki {#tour-and-lessons}

Od 1.2.0 (§5a standardu): **przewodnik po studiu** (9 części ekranu w ramce, startuje sam przy pierwszym otwarciu,
potem ⚙ → Przewodnik po studiu) i **samouczki** (⚙ → Samouczki, 26 w trzech grupach — każde zadanie rozdziału 13, także
„Model dla domu, nie dla świata” i „Fałszywe wybudzenia”). Samouczek czeka na kliknięcie tylko tam, gdzie zmiana trafia do
szkicu; przyciski, które uruchamiają pracę maszyny, tylko pokazuje. Testy: `tests/studio/test_studio_tour.py` (każdy krok
znajduje element w demo, PL i EN, kliknięcie obok ramki nic nie robi). Kontener ma strefę czasową maszyny (§3,
`/etc/localtime`). Opis: [11.7](11-studio.md#tour-and-lessons).

## Wydajność {#performance}

Po problemach z zawieszaniem się dashboardów HA standard wymaga, żeby aplikacja nigdy się nie zawieszała:

- stan jest pobierany dopiero po poprzedniej odpowiedzi i nie z karty w tle;
- każde wywołanie ma limit czasu (stan 20 s, inne 150 s) i czytelny komunikat;
- długie listy nagrań rysują się po rozwinięciu grupy, po 200, a zaznaczenie nagrania nie przerysowuje widoku;
- szkic idzie na maszynę jednym zapisem naraz (zmiana w trakcie wolnego zapisu idzie w jednym kolejnym, nieudany
  zapis mówi o tym i nie ponawia się w pętli);
- testy Playwright: wolny serwer, karta w tle, brak odpowiedzi, 1500 nagrań bez zadania dłuższego niż 500 ms.

## Dokumentacja {#documentation}

- Ręcznie pisane strony HTML zamieniono na **stronę MkDocs Material** (`mkdocs.yml`, `docs/pl`, `docs/en`): te same
  strony i te same kotwice `{#…}` w obu językach. Stare strony są w `backup/docs-before-mkdocs/`.
- Ta sama strona jest w studiu pod `/docs/` (wbudowana w obraz) i na **domowej stronie dokumentacji** (docs-hub, typ
  `mkdocs`, bez martwych linków).
- `make docs`, `docs-build` i `docs-serve` działają **w Dockerze** — bez Pythona. Podgląd na żywo na
  `http://127.0.0.1:9766` przebudowuje się po zmianie pliku.
- Nowe i przepisane rozdziały: 11 „Studio słów budzących” (instalacja, logowanie, ekran, szkic i historia,
  wyłączanie, nagrania z HA, wypróbowanie na Macu), 12 „Jak wytrenować dobre słowo” (ile nagrań, każdy parametr z
  wartością domyślną i wpływem, czytanie wyników, przepisy), ta strona.
- FAQ (PL i EN) dla każdego nowego komunikatu: brak `GPU_HOST`, zajęty port 8765, limit czasu wywołania, brak
  rozdziału na domowej stronie dokumentacji, Docker nie działa, brak uv.
- Zrzuty ekranu odświeżone (`make screenshots`), bez ścieżek z Maca, adresów i imion domowników.

## Testy {#tests}

Każda zmiana ma test. Najważniejsze pliki:

| Plik | Co sprawdza |
|---|---|
| `tests/test_makefile.py` | polecenia, grupy, uv, brak aliasów, `doctor`, komunikat bez adresu maszyny |
| `tests/test_try_on_a_mac.py` | sekcja „Wypróbuj na Macu”; z markerem `docker`: prawdziwy obraz demo (HTTP, login, brak kontenera po zatrzymaniu) i budowa dokumentacji w Dockerze |
| `tests/studio/test_studio_server.py` | wyłączanie (pauza, Stop, restart), `/docs/` |
| `tests/studio/test_studio_docker.py` | etapy Dockerfile (lekkie demo, studio ostatnie), samotesty, instalator |
| `tests/studio/test_studio_docs.py` | te same strony i kotwice w PL i EN, nawigacja, linki z okienek `?`, budowa strict |
| `tests/studio/test_studio_browser.py` | tylko jeden `?` otwiera dokumentację, okienka pomocy, odliczanie wyłączenia, zwijanie kolumn, wydajność |

Wynik na 17 listopada 2026: `make test` — 530 przeszło, 2 pominięte; `make test-docker` — 2 przeszły. Testy nigdy
nie łączą się z prawdziwym Home Assistantem.

## Co jeszcze zostało {#what-is-left}

- ~~Pierwsze uruchomienie na maszynie z GPU~~ — zrobione 18.11.2026: instalacja, TensorFlow na karcie, trening,
  ocena i eksport przez studio ([Pierwsze prawdziwe uruchomienie](#first-run-on-ubuntu)).
- ~~Etap E7~~ — zrobione w 1.0.0: stary panel (`make ui`, `ui-remote`, `wakeword train-ui`), tryb SSH z Maca,
  `guide.md` i jego zrzuty usunięte; teksty i pomoc kart opisują studio.
- ~~Etap E8~~ — zrobione w 1.2.0: dziennik fałszywych wybudzeń (API w Wake Word Recorder 0.3.0 i widok Dom → Fałszywe wybudzenia).
- **Porządek w kodzie**: `make lint` zgłasza dawne uwagi ruff w starszych plikach i niesformatowany kod —
  `make format` i ręczne poprawki to osobny krok.

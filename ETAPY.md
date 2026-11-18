# Studio słów budzących — etapy

Panel treningowy jako edytor w stylu Edytora Home Dashboard i Edytora Assist Router, uruchamiany w Dockerze na
maszynie z GPU (Ubuntu + RTX 4090). Stary panel (`wakeword/trainer/static`, `make ui`) działa do końca i znika
dopiero w E7, po teście na Ubuntu.

| Etap | Zakres | Stan |
|---|---|---|
| E1 | Docker, backend `/api/call`, logowanie, szkic i historia `household.yaml` | gotowe |
| E2 | Szkielet edytora: pasek górny, drzewo, kolumny, motyw, szkic, cofnij/ponów, historia, YAML | gotowe |
| E3 | Rodzina i nagrania, ustawienia, ElevenLabs | gotowe |
| E4 | Trening: dane, parametry, na żywo, zasilanie | gotowe |
| E5 | Modele, ocena, eksport do HA | gotowe |
| E6 | Dokumentacja PL+EN: instalacja, przewodnik po edytorze, jak trenować, parametry, FAQ | gotowe |
| E7 | Przełączenie: usunięcie starego panelu i trybu SSH, wersja 1.0.0 | gotowe |
| E8 | Fałszywe wybudzenia: API w Wake Word Recorder 0.3.0 + widok w studiu | — |
| E9 | Wspólny standard aplikacji na maszynie z GPU (`~/Home Assistant/standards/gpu-studio.md`) | gotowe |

## E1 — Docker, backend, logowanie (gotowe)

- `wakeword/studio/server.py` — klasa `Studio` dziedziczy po `Trainer` z panelu (cała logika bez kopii), trening
  zawsze lokalnie; jeden punkt `POST /api/call {type}`: `state`, `household/get`, `draft/save`, `draft/discard`,
  `household/save` (konflikt → 409), `history/list|get|restore`, `action` (akcje panelu; SSH-owe odrzucane),
  `power/off_after_training`, `power/cancel`, `recordings`, `models`, `model_progress`, `ha_entities`, `hf_voices`,
  `elevenlabs/voices`, `training_log`. Audio przez `GET /api/recording` i `/api/elevenlabs/test`.
  `GET /api/health` bez logowania (healthcheck Dockera).
- `wakeword/studio/auth.py` — `WAKEWORD_UI_AUTH=user:hasło`, podpisane ciasteczko (30 dni, HMAC z losowego sekretu
  `~/.config/wakeword/studio-secret` i hasła — zmiana hasła wylogowuje), 5 błędnych prób z adresu → 60 s przerwy.
- `wakeword/studio/drafts.py` — szkic w `data/studio/draft.json` z hashem pliku bazowego, historia 30 wersji
  w `data/studio/history/`.
- `wakeword/studio/www/login.html` — strona logowania (tokeny edytorów, jasny/ciemny, PL/EN).
- Wyłączanie po treningu: koniec treningu → 120 s odliczania (do anulowania) → przełącznik maszyny w HA; czeka na
  trwające zadanie (np. eksport), błąd pokazuje w stanie.
- `docker/Dockerfile` (python 3.12, TensorFlow z CUDA, microWakeWord przypięty do commita, `/opt/venv`;
  `TRAINING=0` = sam edytor), `docker/compose.yaml` (GPU, `restart: unless-stopped`, wolumeny danych i sekretów),
  `docker/compose.cpu.yaml` (Mac), `docker/install-ubuntu.sh` (kontrole, login, autostart, `--show-login`,
  `--remove`), `.dockerignore`.
- `train/train.sh` i ocena modeli przyjmują `VENV` (obraz ma gotowe środowisko).
- Makefile: `studio`, `studio-docker`, `docker-up`, `docker-logs`, `docker-down`, `deploy`; CLI `wakeword studio`.
- Testy: `tests/studio/` — logowanie, szkic/historia, wywołania i HTTP, wyłączanie po treningu, pliki Dockera,
  strona logowania w Chrome. Obraz CPU zbudowany i uruchomiony na Macu (healthcheck `healthy`).

## E2–E5 — edytor (gotowe)

- `wakeword/studio/www/`: `app.js` (powłoka Lit w light DOM: pasek górny, drzewo, kolumny z dzielnikami, motyw,
  szkic z opóźnionym zapisem na serwer i `sendBeacon` przy zamknięciu, cofnij/ponów z łączeniem pisania, okna zapisu
  z listą zmian i diffem, historii, wyglądu i języka, przewodnika; YAML zaznaczenia i całego pliku; prawa kolumna
  na żywo, wyłączanie po treningu), `outline.js` (drzewo z licznikami i ostrzeżeniami), `changes.js` (zmiany i diff),
  `i18n.js` (teksty studia PL/EN; teksty widoków z pakietów panelu), `main.js` (`ha-icon` w shadow DOM z
  `vendor/mdi.js` — 51 ikon, bez CDN), `studio.css` (tokeny edytorów + klasy kart panelu).
- `views/`: `family.js`, `recordings.js`, `voices.js`, `settings.js`, `training.js`, `models.js`, `overview.js` —
  przeniesione karty panelu 1:1 (`state`, `household`, `draft` jako powiązania modułu).
- Nowe: Pulpit (kroki, następny krok), widok osoby i słowa z ich nagraniami, „Sprawdź maszynę” w Ustawieniach.
- Lista zgodności `docs/design/parity.md` + `tests/studio/test_studio_parity.py`; testy tekstów i ikon
  (`test_studio_assets.py`); Playwright (`test_studio_browser.py`): drzewo i wszystkie widoki, szkic → cofnij →
  ponów → przeładowanie → zapis z notatką → historia → przywrócenie, YAML zaznaczenia i całego pliku, konflikt i
  „Zapisz mimo to”, motyw, język, menu, trening z presetem i postęp na żywo, przewodnik na sekcji.
- `docs/studio_demo.py`: studio na wymyślonej rodzinie z udawanym GPU i fałszywym `train.sh`, sekrety w folderze
  tymczasowym (`make demo`, `--shots`).

## E6 — dokumentacja (gotowe)

- `docs/{pl,en}/11-studio.md` (instalacja, dane, aktualizacja, logowanie, ekran, szkic i historia, wyłączanie,
  pobieranie z HA), `docs/{pl,en}/12-training-well.md` (dwa błędy i cele, wybór słowa, ile nagrań, tło i fałszywe
  wybudzenia, synteza, wszystkie parametry z wartościami z kodu i wpływem, wdrożenie, czytanie wyników, przepisy,
  przykład z pokoju dziecka, kolejność pracy), FAQ „studio (Docker)” w `docs/{pl,en}/index.html`, README, zrzuty.
- `tests/studio/test_studio_docs.py`: zrzuty, linki, tabela wag = `training_config.py`.

## E7 — przełączenie (gotowe, 1.0.0)

Po pierwszym prawdziwym uruchomieniu na Ubuntu (18.11.2026: instalacja, TensorFlow na karcie, trening, ocena i
eksport przez studio):

- usunięte: `wakeword train-ui`, `make ui`/`ui-remote`, `wakeword/trainer/static`, token dostępu panelu, `SshRunner`,
  rsync, `wakeword/trainer/config.py`, akcje `sync`, `fetch`, `fetch_samples`, `panel_access`, `machine_on`;
  `wakeword/trainer` to teraz tylko zaplecze studia (`Trainer`, `LocalRunner`, postęp, modele);
- teksty pakietów językowych i pomoc kart opisują studio (nazwy węzłów zamiast numerów kart), 46 nieużywanych
  tekstów usuniętych; test pilnuje, żeby żaden tekst nie wspominał starego panelu;
- dokumentacja: `guide.md` i jego zrzuty usunięte, FAQ panelu → FAQ studia, rozdziały 01, 06, ściąga i README
  kierują do studia; `docs/screenshots.py` → `docs/demo_household.py`;
- testy starego panelu (przeglądarka, HTTP, SSH) usunięte, testy logiki zostały; test zerwanego połączenia przeniesiony
  do serwera studia.

## E9 — wspólny standard aplikacji na maszynie z GPU (gotowe)

Standard uzgodniony z sesjami trenera Assist Routera i Piper Voice Cloner: `~/Home Assistant/standards/gpu-studio.md`
(PL) i `gpu-studio.en.md` (EN), także na domowej stronie dokumentacji. Zmiany w tym repozytorium:

- **Makefile**: `install`, `deploy`, `login`, `logs`, `status` (z Maca), `docker-up|down|logs|shell` (na maszynie),
  `demo` (port 8766), `icons`, `test-browser`, `lint`, `docs`, `docs-build`, `docs-serve`, `screenshots`; adres
  maszyny w `~/.config/gpu-studio/host.mk` (wspólny), czytelny błąd bez niego; `tests/test_makefile.py` pilnuje listy.
- **Wyłączanie po zakończeniu**: po udanym albo błędnym końcu, nigdy po „Zatrzymaj”; ocena, eksport albo
  polecenie w trakcie wstrzymują odliczanie; restart kontenera je kasuje; odliczanie z „Anuluj” i błąd w pasku
  górnym; pole także przy „Rozpocznij trening”.
- **Dokumentacja MkDocs Material** (`mkdocs.yml`, `docs/{en,pl}`, `docs/site_hooks.py`, `docs/stylesheets/extra.css`):
  strona startowa, studio, rozdziały, „Jak robić to dobrze”, FAQ, ściąga, stary panel, lista zmian; te same strony i
  kotwice w PL i EN; `/docs/` w studiu i w panelu podaje `site/`; `?` w pasku → dokumentacja, `?` kart i pól →
  kotwica rozdziału (`DOCS_LINKS` w `views/common.js`); docs-hub typ `mkdocs`. Stare strony HTML w
  `backup/docs-before-mkdocs/`.
- **Docker**: etap budowy dokumentacji (`mkdocs build --strict`), samotest importów, instalator wyłącza stary panel
  na tym samym porcie. Obraz CPU zbudowany na Macu (strona i importy w środku).
- Testy: makefile, wyłączanie (pauza, Stop, restart), serwowanie `/docs/`, strona (te same kotwice, nawigacja,
  linki `?`, ścieżki obrazków, budowa strict), Docker, Playwright (odliczanie w pasku i Anuluj, pole przy Start).
- **Pomoc i wydajność** (standard §5 „Pomoc”, §9a, 2026-11-16): `?` karty = okienko przy przycisku (`showHelp`,
  `views/common.js`), `?` przy polach i okno „Jak trenować?” usunięte; odpytywanie `setTimeout` po odpowiedzi, bez
  odpytywania w tle, limit czasu każdego wywołania; nagrania rysowane po rozwinięciu grupy, po 200; testy Playwright
  okienka i wydajności (wolny serwer, karta w tle, brak odpowiedzi, 1500 nagrań bez longtask > 500 ms).

# 08. Wdrożenie w ESPHome {#deploying-to-esphome}

[← Ocena](07-evaluation.md) · [Spis treści](index.md) · [Dalej: kolejne iteracje →](09-iterating.md)

## 1. Eksport {#export}

```bash
wakeword -H households/dom export --all --cutoff 0.97 --window 5 --author "Rodzina"
```

Powstaje:

```
data/export/wake_words/dzarwis.tflite
data/export/wake_words/dzarwis.json          # manifest
…
data/export/devices/living-room-voice.yaml   # fragment YAML dla każdego urządzenia
data/export/devices/daughters-room-voice.yaml
…
```

Manifest (format v2 ESPHome):

```json
{
  "type": "micro",
  "wake_word": "Dżarwis",
  "author": "Rodzina",
  "model": "dzarwis.tflite",
  "trained_languages": ["pl"],
  "version": 2,
  "micro": {
    "probability_cutoff": 0.97,
    "sliding_window_size": 5,
    "feature_step_size": 10,
    "tensor_arena_size": 30000,
    "minimum_esphome_version": "2024.7.0"
  }
}
```

## 2. Pliki do Home Assistanta {#files-for-home-assistant}

Skopiuj zawartość `data/export/wake_words/` do folderu konfiguracji ESPHome:
**`/config/esphome/wake_words/`** (np. przez Samba, dodatek File editor albo `scp`).

Zamiast tego możesz trzymać modele na dowolnym serwerze WWW i wyeksportować z
`--url https://…/wake_words` — fragmenty YAML wskażą wtedy adresy URL.

## 3. YAML urządzenia {#device-yaml}

Fragment dla pokoju córek (`data/export/devices/daughters-room-voice.yaml`):

```yaml
micro_wake_word:
  models:
    - model: wake_words/dzarwis.json
      id: dzarwis
    - model: wake_words/wajana.json
      id: wajana

# After flashing, in Home Assistant set:
#   assistant slot 1 wake word: Dżarwis
#   assistant slot 2 wake word: Wajana
```

W ESPHome Device Builder otwórz YAML urządzenia i wklej fragment **pod** istniejącym blokiem
`packages:` (pakietu Voice PE nie zmieniaj). Przykład:

```yaml
substitutions:
  name: daughters-room-voice
  friendly_name: Pokój dziewczyn Voice
packages:
  Nabu Casa.Home Assistant Voice PE: github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml
esphome:
  name: ${name}
  name_add_mac_suffix: false
  friendly_name: ${friendly_name}
api:
  encryption:
    key: !secret …

micro_wake_word:
  models:
    - model: wake_words/dzarwis.json
      id: dzarwis
    - model: wake_words/wajana.json
      id: wajana
```

ESPHome dołącza nowe modele do tych z pakietu (`okay_nabu`, `hey_jarvis`, `hey_mycroft` zostają).
Kliknij **Validate** — jeśli walidacja przejdzie, **Install → Wirelessly** (OTA). Kompilacja trwa
kilka minut.

Urządzenia ESPHome z własnym blokiem `micro_wake_word` (np. Onju Voice) — dopisz modele do jego
listy `models:` w ten sam sposób.

## 4. Ustawienie słów w Home Assistant {#setting-the-words-in-home-assistant}

Po aktualizacji w **Ustawienia → Urządzenia → (urządzenie)**:

- **Słowo aktywujące** (miejsce 1) → *Dżarwis*,
- **Słowo aktywujące 2** (miejsce 2) → *Wajana*,

a w ustawieniach asystenta głosowego wybierz, który asystent odpowiada na które miejsce.

## 5. Test w domu {#testing-at-home}

- Powiedzcie słowo **każdy po kolei**, z różnych miejsc pokoju, różnym głosem.
- Zostawcie włączony telewizor na wieczór i sprawdźcie, czy urządzenie się samo nie budzi.
- Gotowe słowo (np. `okay_nabu`) może zostać na drugim miejscu jako zapas.

Próg można zmienić bez ponownego treningu: `export --cutoff 0.95`, skopiuj JSON i wgraj
firmware ponownie. ESPHome pozwala też nadpisać próg dla jednego modelu w YAML
(`probability_cutoff:` przy modelu na liście `models`).

# 08. Deploying to ESPHome {#deploying-to-esphome}

[← Evaluation](07-evaluation.md) · [Contents](index.md) · [Next: iterating →](09-iterating.md)

## 1. Export {#export}

```bash
wakeword -H households/home export --all --cutoff 0.97 --window 5 --author "Family"
```

This creates:

```
data/export/wake_words/dzarwis.tflite
data/export/wake_words/dzarwis.json          # manifest
…
data/export/devices/living-room-voice.yaml   # YAML snippet for each device
data/export/devices/daughters-room-voice.yaml
…
```

Manifest (ESPHome v2 format):

```json
{
  "type": "micro",
  "wake_word": "Dżarwis",
  "author": "Family",
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

## 2. Files for Home Assistant {#files-for-home-assistant}

Copy the contents of `data/export/wake_words/` to the ESPHome configuration folder:
**`/config/esphome/wake_words/`** (e.g. via Samba, the File editor add-on or `scp`).

Alternatively, you can host the models on any web server and export with
`--url https://…/wake_words` — the YAML snippets will then point to the URLs.

## 3. Device YAML {#device-yaml}

The snippet for the daughters' room (`data/export/devices/daughters-room-voice.yaml`):

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

In ESPHome Device Builder, open the device YAML and paste the snippet **below** the existing
`packages:` block (don't modify the Voice PE package). Example:

```yaml
substitutions:
  name: daughters-room-voice
  friendly_name: Daughters Room Voice
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

ESPHome adds the new models to those from the package (`okay_nabu`, `hey_jarvis`, `hey_mycroft`
stay). Click **Validate** — if validation passes, **Install → Wirelessly** (OTA). Compilation takes
a few minutes.

ESPHome devices with their own `micro_wake_word` block (e.g. Onju Voice) — add the models to its
`models:` list in the same way.

## 4. Setting the words in Home Assistant {#setting-the-words-in-home-assistant}

After the update, in **Settings → Devices & services → (device)**:

- **Wake word** (slot 1) → *Dżarwis*,
- **Wake word 2** (slot 2) → *Wajana*,

and in the voice assistant settings choose which assistant answers which slot.

## 5. Testing at home {#testing-at-home}

- Say the word **one after another**, from different places in the room, in different voices.
- Leave the TV on for an evening and check that the device doesn't wake up by itself.
- A ready-made word (e.g. `okay_nabu`) can stay in the second slot as a backup.

The cutoff can be changed without retraining: `export --cutoff 0.95`, copy the JSON and flash the
firmware again. ESPHome also lets you override the cutoff for a single model in YAML
(`probability_cutoff:` on the model in the `models` list).

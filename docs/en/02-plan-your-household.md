# 02. Plan your household and choose words {#plan-your-household-and-choose-words}

[← What you need](01-what-you-need.md) · [Contents](index.md) · [Next: recordings →](03-recording.md)

Before anyone records anything, agree together on **who**, **which words** and **on which devices**.

## Example: a family with three children {#example-a-family-with-three-children}

This is a Polish family's example — the wake words and their spellings are Polish on purpose,
because training on the household's own pronunciation is the point.

- **"Dżarwis"** — the whole family's shared word, works everywhere,
- **"Optimus Prime"** — the son's word in his room (dad records it too, because he is often in the son's room),
- **"Wajana"** — the daughters' word in their room (mum too),
- in the living room and bedroom, the second slot keeps the ready-made **"Okay Nabu"**.

```yaml
ui_language: pl

speakers:
  - id: dad
    group: adult
  - id: mum
    group: adult
  - id: son
    group: child
  - id: daughter1
    group: child
  - id: daughter2
    group: child

words:
  dzarwis:
    wake_word: Dżarwis
    trained_languages: [pl]
    speakers: all
    spellings:
      pl: [dżarwis, dżarwys, dżar wis]
      en: [jarvis, jar vis]
    sound_alikes: [harwis, dżem wiśniowy, jarmark, darwin]
  optimus_prime:
    wake_word: Optimus Prime
    trained_languages: [en]
    speakers: [son, dad]
    spellings:
      en: [optimus prime, optimus]
      pl: [optimus prajm, optimus prime]
    sound_alikes: [optimum price, optymista, oprime]
  wajana:
    wake_word: Wajana
    trained_languages: [pl]
    speakers: [daughter1, daughter2, mum]
    spellings:
      pl: [wajana, wajaana]
      en: [vaiana, vy ana]
    sound_alikes: [banana, tajana, wanna, jana]

targets:
  adult: 12
  child: 18
  held_out: 3

devices:
  living-room-voice: [dzarwis, okay_nabu]
  bedroom-voice: [dzarwis, okay_nabu]
  son-room-voice: [dzarwis, optimus_prime]
  daughters-room-voice: [dzarwis, wajana]
```

This file is in `households/examples/family/household.yaml`; a second example — one person, one
word — is in `households/examples/single/`.

## File fields {#file-fields}

| Field | Meaning |
|---|---|
| `ui_language` | recorder language (`pl`, `en`) |
| `speakers[].id` | person identifier: lowercase letters, digits, `_` (can be a first name, e.g. `ola`) |
| `speakers[].group` | `adult` or `child` — children need more takes and are reported separately in evaluation |
| `words.<id>` | word identifier: lowercase letters, digits, `_`; becomes the model file name |
| `wake_word` | how the word is shown in Home Assistant |
| `trained_languages` | language(s) written into the model manifest |
| `speakers` | `all` (everyone, including people added later) or a list of people |
| `spellings` | texts for the speech synthesiser, separately for each voice language — see below |
| `sound_alikes` | similar-sounding words and phrases that must **not** wake the device (negatives) |
| `targets` | how many takes per person per word (`adult`, `child`) and how many of them to set aside for testing (`held_out`) |
| `devices` | ESPHome device name → at most **2** words; you can use the ready-made ones: `okay_nabu`, `hey_jarvis`, `hey_mycroft`, `alexa` |

## Phonetic spellings — where the accent comes from {#phonetic-spellings-where-the-accent-comes-from}

A synthesiser reads text the way **its** language reads it. A Polish Piper voice reads "dżarwis"
the way a Pole says it; an English voice reads "jarvis" the English way. Therefore:

- in the spellings for your own language (here `spellings.pl`), write **how you say the word at
  home**, using that language's spelling (`dżarwis`, `optimus prajm`),
- in `spellings.en` (and other languages), write that language's spelling — for voice variety,
- several spelling variants (`dżarwis`, `dżarwys`, `dżar wis`) give several pronunciation variants.

## How to choose a good word {#how-to-choose-a-good-word}

1. **2–4 syllables.** "Dżarwis" (2), "Wajana" (3), "Optimus Prime" (4). One syllable carries too
   little information, a sentence is too long (the model listens to at most about 1.5 s).
2. **Clear, varied sounds**, ideally with plosives (p, t, k, b, d, g) and distinctive sounds such
   as "sh"/"j" (in Polish: ż, dż, sz).
3. **Not a word from everyday speech.** "Mum", "okay", "listen" — you will get false wakes.
   A household member's name is out too.
4. **Words in one home must differ from each other.** "Wajana" and "Jana" on two devices is asking
   for mix-ups. The tool adds the household's other words as negatives anyway, but it cannot remove
   similarity of sound.
5. **The "sounds like" test.** Say the word a few times and write down what it reminds you of
   (e.g. "Dżarwis" → "darwin", "harwis", "jarmark") — those are your `sound_alikes`.
6. **Children must be able to say it.** If a younger child says "Optimus Plajm", add that to the
   spellings too — and record it exactly the way they say it.

## Devices and the two Voice PE slots {#devices-and-the-two-voice-pe-slots}

The Voice PE has **two assistant slots** ("Wake word" and "Wake word 2" in Home Assistant). Each has
one word and can lead to a different assistant (e.g. a different language or agent). That is why
`devices` accepts at most two words per device. The device name is the ESPHome name (`name:` in the
device YAML), e.g. `daughters-room-voice`.

## Commands {#commands}

Instead of writing YAML by hand:

```bash
wakeword -H households/home init --ui-language pl \
  --speaker dad --speaker mum --speaker son:child --speaker daughter1:child --speaker daughter2:child

wakeword -H households/home add-word dzarwis "Dżarwis" --language pl \
  --spelling "pl=dżarwis,dżarwys,dżar wis" --spelling "en=jarvis,jar vis" \
  --sound-alike harwis --sound-alike darwin

wakeword -H households/home add-word wajana "Wajana" --language pl \
  --speaker daughter1 --speaker daughter2 --speaker mum \
  --spelling "pl=wajana,wajaana" --spelling "en=vaiana" --sound-alike banana

wakeword -H households/home set-device daughters-room-voice dzarwis wajana

# a new person later (also added to the word wajana):
wakeword -H households/home add-speaker ela --group child --word wajana
```

Every change is validated (unknown people, more than 2 words on a device …), and the previous
version of the file is kept in `household.yaml.bak`. Instead of `-H …` you can set
`export WAKEWORD_HOUSEHOLD=households/home` or change into the household folder.

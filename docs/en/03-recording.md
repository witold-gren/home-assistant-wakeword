# 03. Household recordings {#household-recordings}

[← Plan your household](02-plan-your-household.md) · [Contents](index.md) · [Next: augmentation and negatives →](04-augmentation-and-negatives.md)

## How many recordings {#how-many-recordings}

You don't need to record for half an hour. **A dozen or so takes per person per word** is enough,
as long as they are **said differently** — voice expansion and augmentation do the rest (thousands
of variants).

| Who | Takes per word (`targets`) | Why |
|---|---|---|
| Adult | 12 | stable voice |
| Child | 18 | the voice changes from day to day, speech is less even |

Of these takes, the tool sets aside **3 per person** (`held_out`) for testing — the model never
sees them, and later we use them to check whether it recognises every person.

For the example family that adds up to: "Dżarwis" 5 people (2×12 + 3×18 = 78 takes), "Optimus
Prime" 2 people (30), "Wajana" 3 people (48). One person records all of their words in 10–20 minutes.

## Variants {#variants}

The recorder guides each person through a series of variants — each take is said differently:

| Variant | Instruction |
|---|---|
| `near` | half a metre from the phone, normally |
| `far` | from the other side of the room (3–4 m) |
| `quiet` | quietly, as if someone is sleeping nearby |
| `loud` | loudly, as if from another room |
| `fast` | quickly, in passing |
| `slow` | slowly and clearly |
| `question` | like a question, unsure |
| `tired` | in a tired voice |
| `cheerful` | cheerfully, with a smile |
| `background` | with the TV or music on |
| `other_side` | sideways or facing away from the phone |
| `normal` | the way you say it every day |

After 12 takes the sequence starts again. The variant is saved in the file name
(`son_004_fast.wav`), and `check` tells you which variants are still missing.

## Where to record {#where-to-record}

- **Ideally where the device stands**: in the son's room for "Optimus Prime", in the living room
  for the shared word. The room acoustics are part of the data.
- Put the phone roughly where the Voice PE stands (a shelf, a dresser) rather than holding it to your mouth.
- Don't force everything in the house off — a bit of normal background is good. Clipping and
  shouting into the microphone are not.

## Browser recorder {#browser-recorder}

```bash
wakeword -H households/home record
```

```
Recorder for 'home' — open on a phone or computer in the same network:
  https://192.168.1.20:8443/
The browser warns about the certificate (it is your own) — accept it once.
```

The recorder's language follows `ui_language` in `household.yaml`; the screens below are from the
English UI (`ui_language: en`).

1. Open the address on a phone (same Wi-Fi network). The browser warns about the certificate —
   it is your own certificate, generated on the first run; accept it
   (Safari: *Show Details → visit this website*; Chrome: *Advanced → Proceed to …*).
   Phones only allow the microphone on HTTPS pages — hence the certificate.
2. **Who are you?** — pick yourself.
3. **Your words** — a list of your words with progress (e.g. `4 of 18 recorded`).
4. Pick a word. The screen shows **Say: “Dżarwis”** and the variant instruction (e.g. *Step back
   to the other side of the room…*).
5. **Start recording** → say the word → **Stop** (or it stops by itself after 6 s).
6. **Listen** → **Keep** or **Record again**.
7. Right after saving, the recorder rates the recording: *Too quiet*, *Too loud (distorted)*,
   *Nothing was heard*. Delete a bad take from the list below and record it again.

The recorder saves files as 16 kHz mono WAV, trimmed of silence (with a 0.25 s margin) and
normalised, to `data/real/<word>/<speaker>/`.

Without a phone: `wakeword record --http` and open `http://localhost:8443/` on the same computer
(the microphone over HTTP only works on `localhost`).

## Recording through Voice PE (Wake Word Recorder integration) — the best data {#recording-through-voice-pe-wake-word-recorder-in}

Takes are best when they come from **the same microphones** that will later listen for the word:
Voice PE has two microphones and an audio processor (echo and noise suppression); a phone sounds
different. The **Wake Word Recorder** integration ([its own repository](https://github.com/witold-gren/home-assistant-wake-word-recorder)) records takes
through Home Assistant voice satellites:

1. Install the integration (HACS custom repository, see its README) and
   restart Home Assistant.
2. Create the household in the HA config folder, e.g. `/config/wakeword` (from a computer with the
   Samba share mounted: `wakeword -H /Volumes/config/wakeword init …`).
3. **Settings → Devices & services → Add integration → Wake Word Recorder**, household folder:
   `/config/wakeword`.
   If there is no household.yaml yet, the integration offers to create it with the people of HA
   (person entities); you only mark the children and add the words later with `wakeword add-word`.
4. On the "Wake Word Recorder" device choose the **Person**, the **Wake word** and the
   **Satellite**, press **Start recording** (or the action `wake_word_recorder.start_session`).

What happens:

- the satellite is switched to the **"Wake word recording"** pipeline (created by the integration,
  with the voice of your preferred assistant); afterwards its previous pipeline is restored — also
  after a restart of HA during a session,
- the device says e.g. *"Take 4 of 18. Step back to the other side of the room. Say: Jarvis."* and
  listens **without a wake word**,
- the take is checked (silence, too quiet, clipped, too short/long); a good one goes to
  `data/real/<word>/<person>/` with the recorder's naming, a bad one is asked again
  (*"Too quiet. Once more…"*),
- the session ends at the person's target (or after `count` takes), after 3 silent turns, after
  6 rejected takes in a row, or with **Stop recording**,
- `data/real/recordings.csv` notes which device recorded which take,
- `sensor.wake_word_recorder_status` shows the progress (person, word, `done`/`target`, last file,
  problems).

The takes are visible on your computer right away: `wakeword -H /Volumes/config/wakeword check`.
Both ways of recording can be combined — Voice PE gives realism, phones add variety.

Technical note: in the Voice PE firmware wake word detection listens to microphone channel 1
(gain ×4), while Home Assistant receives the assistant stream. The gain does not matter (takes are
normalised) and the audio passes through the same XMOS processor — still much closer to real use
than a phone.

## Importing recordings from Voice Memos or old files {#importing-recordings-from-voice-memos-or-old-fil}

Each person can also record takes with Voice Memos on an iPhone (one word = one recording) and send
the files. Import accepts `.m4a`, `.mp3`, `.wav`, `.flac` … (requires `ffmpeg`):

```bash
wakeword -H households/home import dzarwis --speaker dad ~/Downloads/dzarwis_*.m4a
```

```
/Users/…/dzarwis_1.m4a → dad_000_imported.wav
/Users/…/dzarwis_2.m4a → dad_001_imported.wav
```

Imported takes get the variant `imported`. Make sure yourself that they are said differently.

## Checking: the speaker × word matrix {#checking-the-speaker-word-matrix}

```bash
wakeword -H households/home check
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

- `13/12 ✓` — the person has a full set of good takes,
- `—` — this person doesn't use this word,
- `problem:` — a take to fix: `no_speech` (silence), `too_short` (cut off), `too_long` (a sentence
  instead of a word), `too_quiet`, `clipped` (distortion), `unreadable`,
- `not a take` — a file in the recordings folder that doesn't match the naming (delete or rename it).

`check` exits with code 0 only when everything is complete — `prepare` without `--force` won't
start before that.

## Household background recordings (optional, but worth 10 minutes) {#household-background-recordings-optional-but-wor}

**Best through Voice PE:** in the Wake Word Recorder integration choose the **Background satellite** and press
**Listen 30 min** (or the action `wake_word_recorder.start_background` with `minutes`). The device silently records
for 30 minutes to `data/background/<satellite>_<date>.wav` — exactly what its microphone hears.

With a phone:

Put the phone where the device stands and record 10–30 minutes of ordinary life: TV, dinner,
conversation, the dishwasher. **Nobody says the wake word during that time.** Put the files (any
format; convert with `ffmpeg -i recording.m4a -ac 1 -ar 16000 tv.wav`) in:

```
households/home/data/background/tv_evening.wav
households/home/data/background/dinner.wav
```

They serve three purposes: as real background in the augmentation preview, as negatives in
training, and to measure false wakes per hour in evaluation.

# 12. Training a good wake word — the parameters and what they do {#training-well}

This chapter gathers in one place: how many and which recordings are needed, what each training parameter does, how
to read the results and what to change when the model misses the word or wakes by itself. The numbers are the
defaults in the code (`wakeword/training_config.py`, `train/make_features.py`, `wakeword/synthetic.py`,
`wakeword/export.py`).

## 12.1 Two mistakes, one balance {#two-mistakes-one-balance}

Every wake word model makes two kinds of mistakes:

- **a miss** (FRR — the share of utterances it did not react to): someone says the word, nothing happens;
- **a false wake** (FAPH — false wakes per hour): the device wakes by itself from the TV, a conversation, music.

Almost every parameter moves the model one way: fewer false wakes at the cost of more misses, or the other way round.
Good training is **more and better data**, which improves both at once; the parameters only choose the balance.
The studio's goals:

| Measure | Goal | Where |
|---|---|---|
| AVR (average viable recall in validation) | ≥ 0.90 (≥ 0.95 very good) | Live progress, tile and chart |
| FAPH in validation | ≤ 0.5 / h (≤ 1 acceptable) | Live progress |
| Recall at no false wakes | ≥ 80 % | Live progress |
| FRR of every person (household test) | ≤ 5 % (1 in 20 utterances) | Models → Household column |
| False wakes at home | ≤ 1 a day | Models → Household; Home → False wakes |

## 12.2 Choosing the word {#choosing-the-word}

- **2–4 syllables, clear consonants** (“Hey Jarvis”, “Hey Robo”). One syllable wakes from everything.
- **Not an everyday word** and not the start of a frequent phrase. Add **sound-alikes** to the word
  (`hey harvest`, `hey darwin`) — they become negatives, the model learns not to listen to them.
- **How it is read** in every language of the synthetic voices: a Polish spelling (`hej dżarwis`) gives a Polish
  accent, an English one (`hey jarvis`) an English accent. Spellings are training data, not only a label.
- A child's word — best their own, short and easy to say; the child's recordings weigh more (preset **Family**).

## 12.3 How many recordings, and which {#how-many-recordings-and-which}

Targets in Settings → Targets and language (defaults):

| Group | Takes per word | Held out for the test |
|---|---|---|
| Adult | **12** (good: 12–15) | 3 |
| Child | **18** (good: 18–25) | 3 |

**Different takes give more than more of the same.** The recorder and the satellites guide through the variants:
near and far from the device, quiet and loud, fast and slow, as a question, tired, cheerful, with background (TV,
talking), from the other side of the room. Record **with the device that will listen** (Voice PE through Wake Word
Recorder) — its microphone and the room's echo go into the data. 3 takes of every person are held out for the test
and never trained on — this is why the household test tells the truth.

About 15 takes per person become thousands of examples: voice expansion (`expand`: pitch, timbre, tempo — 6 variants
per take), augmentation (background, echo, EQ, gain) and 50 augmentation passes over the household's recordings.

## 12.4 The home's background and false wakes {#home-background}

What the model must **not** react to comes from public datasets (speech, a dinner party, silence and noise — about
20 GB, downloaded by the first training) and from **your home**:

- **Home background** — 30 min per room through a satellite (“Listen 30 min” in Wake Word Recorder): TV, dinner,
  children. It is trained on as a negative and used by the household test (false wakes a day).
- **False wakes** — recordings of moments the model woke by itself (chapter 9), in the `false_wakes` set with the
  highest weight of the home's recordings. The most effective cure for a model that “wakes too eagerly”.

## 12.5 Synthetic data {#synthetic-data}

| Source | How many (default) | Why |
|---|---|---|
| English generator (libritts, hundreds of voices) | 20,000 utterances | many voices, the word for guests |
| Piper voices in the spellings' languages | 300 per voice and spelling | the language's accent (Polish voices read `hej dżarwis`) |
| Sound-alikes (negatives) | 4,000 | teach it to refuse similar words |
| ElevenLabs (optional) | 5 per voice and spelling (up to 50), 10 ways of speaking | very natural voices, Polish too |

Piper's tempo and variation are randomised (`length_scale` 0.8–1.25, `noise_scale` 0.5–0.9). Listen to the samples
(Synthetic voices → Samples) before training — a voice that mangles the word should be switched off (Piper) or
unticked (ElevenLabs).

## 12.6 Training parameters (Training → Parameters and start) {#training-parameters}

### Steps (`steps`, default 20,000, range 100–500,000) {#steps}

How many batches of 128 examples the model sees. Too few — undertrained (low AVR, the chart still rising). Too many —
time lost (the studio shows the time left in Live progress), sometimes overfitting on the synthetic data. A next
training **continues** from the saved state for the given number of steps; beyond ~80,000 steps in total more steps
rarely help — more data does. The advice after a training proposes +20,000 when the result was still rising.

### Negative weight (`negative_class_weight`, default 20, range 1–200) {#negative-weight}

How much a false wake costs compared to a miss. **More** (30–60): fewer false wakes, more misses, a “more careful”
model. **Less** (5–15): more sensitive, wakes by itself more often. Change it by 30–50 % when the advice says so; when
both mistakes are bad, data is needed, not a weight.

### Learning rates (`learning_rates`) {#learning-rates}

Default three phases **0.001 → 0.0003 → 0.0001** (50/30/20 % of the steps); a training continuing from a saved state:
**0.0003 → 0.0001** (50/50). Own: 1–4 values (2 → 50/50, 3 → 50/30/20, 4 → 40/30/20/10), range 0.000001–0.01.
Too high: AVR jumps between validations (advice “unstable”); too low: slow learning. The phases show as bands on the
progress chart.

### Set weights (`sampling_weight`) and presets {#set-weights}

How often the training takes from each set. **+** teaches when to react; **−** when not to (range 0–50, empty =
default).

| Set | Default | Family | Neutral | More of it gives |
|---|---|---|---|---|
| + Household recordings (`real`) | 3 | **6** | 2 | better recognition of the household, children too |
| + Expanded recordings (`expanded`) | 2 | **4** | 1 | robustness to a changed voice (a cold, whispering, hurry) |
| + ElevenLabs | 2.5 | 1.5 | **3** | natural strangers' voices |
| + Piper synthesis (`synthetic`) | 2 | 1 | **3** | the word for anyone (guests), the language's accent |
| − Sound-alikes (`sound_alikes`) | 3 | 3 | 3 | fewer wakes from similar words |
| − Other words of the home (`other_words`) | 4 | 4 | 4 | the home's words do not wake each other |
| − Home background (`background`) | 3 | **8** | 3 | fewer wakes from your TV and conversations |
| − False wakes (`false_wakes`) | 5 | **8** | 5 | an end to particular false wakes |
| − Strangers' speech (`speech`) | 10 | 10 | 10 | robustness to conversation |
| − Dinner party (`dinner_party`) | 10 | 10 | 10 | robustness to the noise of many voices |
| − Noise without speech (`no_speech`) | 5 | 5 | 5 | robustness to music and noise |

The **Family** preset also sets the negative weight to 30: the model reacts very well to the household and almost
never wakes by itself at home (worse for guests). **Neutral** (weight 20): the word for anyone, less fitted to the
family. For a home with children and a TV, start with **Family**. The lesson **⚙ → Lessons → A model for the home, not for the world** goes through every place where a home model differs from a general one (the preset, the weight of the negatives, the ranking of the models, the threshold of the export).

### Augmentation (fixed, `train/make_features.py`) {#augmentation}

Every recording goes into training as a 3.2-second clip, with probability: background 0.75 (SNR −5…10 dB), room echo
(RIR) 0.5, a gain change always, EQ / distortion / pitch shift / band-stop / colour noise 0.1 each. Long negatives (the
home background) are cut into 3 s pieces. Repeats of a set in augmentation: household recordings 50×, expanded 5×,
synthesis 2×, sound-alikes 2×, other words 3×, false wakes 3×.

### Convert only (no training) {#convert-only-no-training}

Converts the best weights so far to a `.tflite` model and runs the final test — when a training was stopped or a model
must be made again.

## 12.7 Deployment parameters (Training → Evaluation and export) {#deployment-parameters}

| Parameter | Default | Effect |
|---|---|---|
| `probability_cutoff` (cutoff) | 0.97 (the studio suggests the final test's cutoff) | higher = fewer false wakes, more misses; a change of 0.01–0.02 is already a lot |
| `sliding_window_size` (window) | 5 | how many of the model's last scores are averaged before the cutoff; larger = fewer short “spikes” from single sounds, a slightly slower reaction |
| `feature_step_size` | 10 ms | the audio features' step (as in training — do not change) |
| `tensor_arena_size` | 30,000 | the model's memory on the device |

Choose the cutoff from the final test's table (Live progress) and the household test (Models → Household): the lowest
cutoff at which every person's FRR is ≤ 5 % and there is ≤ 1 false wake a day. The studio sends the model and its
manifest straight to `/config/esphome/wake_words/` through Home Assistant.

## 12.8 Reading the results {#reading-the-results}

- **Chart** (AVR and FAPH every 500 steps): AVR should rise and level off above 0.90; FAPH fall. AVR still rising at
  the end → more steps. AVR jumping → a lower learning rate.
- **Final test** (cutoff / missed / false per hour, AUC): the green row is the recommended cutoff.
- **Models**: every training stays as a model of its own. The **Household** ranking (held-out takes + home background)
  matters more than **Neutral** (synthetic voices). “Goal met” or “×2.3 the goal” says how far. **Choose** sets the
  model the next training starts from; **From scratch** — a training without the old state.
- **Advice** after the final test says what to change; **Apply** fills the steps and weight in the form.

## 12.9 Recipes for common problems {#recipes-for-common-problems}

| Symptom | Cause | What to do (in order) |
|---|---|---|
| Wakes by itself from the TV / YouTube | too few negatives from this home | record 30 min of background in this room (TV on) → add the false wakes → Family preset → negative weight +30–50 % → cutoff +0.01 |
| Wakes during conversation, “catches” similar words | the sound-alikes are not in the data | add them to the word (Sound-alikes) → prepare again |
| A child must repeat it 2–3 times | too few takes of the child, too small a weight | 18–25 takes of the child in different variants → Family preset (`real` 6) → cutoff −0.01 |
| One person has FRR 15 %, the others 0 % | their takes are alike or from another microphone | record their variants through the satellite they use |
| AVR < 0.75 after a whole training | a data problem, not a parameter one | listen to the recordings (clipping, silence, another word), the synthetic samples (voices mangling the word) |
| AVR jumps ±0.4 between validations | too high a learning rate | rates 0.0003, 0.0001 → continue |
| A good final test, poor at home | the test on synthetic voices is not the home | Household ranking, home background for the test, the studio's model instead of the first one |

### A real example: a child's room, November 2026 {#real-example}

A “Hey Jarvis” model trained early (no home background and no false wakes, cutoff 0.97, window 5) woke by itself
**39 times** in 6 days (≈ 6.5 a day, goal ≤ 1), mostly from YouTube (“thanks for watching”, music) and short sounds
without speech; there were 4 real calls. The stock “Okay Nabu” and “Hey Jarvis” models in other rooms had 1–3 false
wakes in the same time. The order of the fix: 30 min of background in that room with YouTube → the false wakes'
recordings as `false_wakes` → Family preset → a new model with the best Household ranking → the cutoff from the
household test (usually 0.98–0.99).

## 12.10 The order of work {#the-order-of-work}

1. Household: people, the word (spellings, sound-alikes), devices → **Save**.
2. Recordings: 12 (adults) / 18 (children) takes through the satellite in the room where the word must work;
   30 min of background.
3. Voices: listen to Piper, optionally ElevenLabs.
4. **Prepare** → **Start training** (Family preset, 20,000 steps).
5. Final test and advice → **Apply** and continue if needed.
6. **Household test** (Models) → choose the best model in the Household ranking → **Export** with the test's cutoff.
7. A week of watching the false wakes → their recordings as `false_wakes` → the next training from the best model.

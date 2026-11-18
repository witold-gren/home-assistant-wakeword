# Training panel → wake word studio: nothing left behind

Every feature of the training panel (`wakeword/trainer/static`, cards 1–6 and the right column) and where it is in
the studio (`wakeword/studio/www`). The last column names what in the studio's code does it;
`tests/studio/test_studio_parity.py` fails when one of them disappears. Rows with “—” in that column are left out
on purpose, with the reason.

| Feature | Training panel | Studio | Code |
|---|---|---|---|
| People: add, adult/child, remove, takes per word | card 1 → People | Household → People, a person | `data-add-person` `data-remove-person` `data-group` |
| People and words in order by drag and drop (keys too) | card 1 | Household → People, Words | `sortable(` `dragHandle(` |
| Words: name, language, who uses it, spellings, sound-alikes, add, remove | card 1 → Words | Household → Words, a word | `data-add-word` `data-remove-word` `data-everyone` `data-spelling` `data-sound-alikes` |
| A word's id changed with its recordings | card 1 → Words → change | a word → change | `data-rename` `rename_word` |
| Devices: found in ESPHome / Home Assistant, typed, two slots | card 1 → Devices | Household → Devices | `data-add-device` `device_pick` `slot1` |
| Targets of takes and the recorder's language | card 1 → Settings | Settings → Targets and language | `data-target` `recorder_language` |
| Draft, Save, Discard | card 1 (unsaved badge) | top bar: pill, Save, Discard; kept on the server, undo/redo, history | `data-save` `data-discard` `data-undo` `data-redo` `data-history` `draft/save` |
| Save sends household.yaml to Home Assistant | card 1 → Save | Save (warning when not sent) | `household/save` `saved_not_sent` |
| Recordings: per word and person, listen, select, delete (to data/backup), background, synthetic | card 1 → Recordings | Recordings → all, a word, home background | `data-play` `data-pick` `data-delete-picked` `delete_recordings` `renderBackground` |
| Piper voices per language, reset, from a Hugging Face repository | card 1 → Settings | Synthetic voices → Piper voices | `data-voice` `data-hf-load` `hf_voices` |
| Home Assistant address and token, rejected token said | card 1 → Settings | Settings → Home Assistant | `data-ha-save` `ha_token_rejected` `ha_connection` |
| Machine power: switch, power sensor, threshold, entity lists | card 1 → Settings | Settings → Machine power | `data-power-save` `ha_entities` `data-off-watts` |
| Machine power button and state in the header | header | top bar (switching off; the studio runs on the machine) | `data-power-off` `machineLabel` `machine_off` |
| Switch the machine off after training | — (new) | side column of the training views | `data-power-after` `power/off_after_training` `power/cancel` |
| ElevenLabs: key, language, word, model, count, sync, search, gender and language filters, free plan | card 1 → ElevenLabs | Synthetic voices → ElevenLabs | `data-el-key` `data-el-sync` `el_speaks_filter` `el_usable_filter` |
| ElevenLabs: preview, paid test take, add a library voice, choose shown, unselect all | card 1 → ElevenLabs | same | `elPreview` `/api/elevenlabs/test` `elevenlabs_add` `el_select_shown` `el_unselect_all` |
| ElevenLabs: generate takes, made count, refused voices and restore | card 1 → ElevenLabs | same | `data-el-generate` `el_made_count` `elevenlabs_restore` |
| Check the machine (GPU, Python, disk, tools, HF token) | card 2 → Check | Settings → Machine and HF token | `data-check` `action("check"` |
| Hugging Face token on the machine, set / remove, only whether it is set | card 2 | Settings → Machine and HF token | `data-hf-save` `hf_token` |
| Words to train, notes (missing takes, not prepared, trained), kept per browser | card 3 | Training → Data, Parameters, Samples | `data-train-word` `wakeword-words` |
| Fetch recordings from Home Assistant, last fetch said | card 4 | Training → Data and preparing | `ha-pull` `ha_pull_hint` |
| Prepare (all complete words, force, refused when incomplete) | card 4 | Training → Data and preparing | `prepare_incomplete` `prepare_skipped` `id: "force"` |
| Synthetic samples per voice, waiting voices, negatives, ElevenLabs review (search, pages, listen one after another, switch a voice off) | card 4 | Training → Data, Synthetic voices → Samples | `renderSamples` `data-play-all` `el_voice_disable` |
| Steps, negative weight, learning rates (checked), set weights with presets, convert only, start, stop | card 5 | Training → Parameters and start | `"steps"` `"negative_weight"` `learning-rates` `data-set` `data-preset` `convert-only` `id: "start"` `id: "stop"` |
| Evaluate a trained word, the exported model said, cutoff (from the recommendation), export to Home Assistant | card 6 | Training → Evaluation and export | `data-evaluate` `id: "cutoff"` `id: "export"` `form.recommended` |
| Command output with copy, toasts when a job ends, lists read again | right column | Overview → Command output, side column | `data-copy-job` `_afterState` `DISK_JOBS` |
| Training log, opened while training, copy of the whole log | right column | Overview → Command output | `data-copy-log` `training_log` |
| Live: stage, time, GPU name and rings (load, memory, temperature, power) | right column | Training → Live progress, side column | `liveCard` `utilization` `temperature` |
| Progress per word: timeline, steps and time left, tiles, chart with phases, final test, recommended cutoff | right column | Training → Live progress | `drawChart` `final_title` `recommended` `phase_label` |
| Advice after the final test with “Apply” | right column | Training → Live progress | `data-apply-advice` `advice_apply` |
| Models: both rankings, why, base, view a model's chart, choose, from scratch, household test, folded words | right column → Models | Training → Models, a word | `data-rank` `data-view-model` `data-choose-model` `data-from-scratch` `data-household-test` `models_why_household` |
| “How to train?” guide and “?” next to fields | header, fields | top bar “?” = documentation; a “?” per card = help window with “More in the guide” (gpu-studio standard) | `data-docs` `showHelp` `docs_more` |
| “?” help of each card | cards | each view's card | `help-btn` `data-help` |
| Language of the panel (Polish, English) | header | ⚙ Look and language | `data-language` `wakeword-studio-lang` |
| The step-by-step guide (docs) | header | menu → Guide | `/docs/` |
| The road 1–6 (stepper) | header | Overview → Dashboard | `data-steps` `next_` |
| Folding cards, kept per browser | cards | the tree (fold, fold all, search) and folded model blocks | `data-fold-all` `data-search` `saveCollapsed` |
| Questions in the panel's own window | everywhere | everywhere | `ask(` |
| Where training runs: SSH machine or this computer | card 2 | — | — the studio runs on the training machine itself (Docker); training is always local |
| Send to machine (rsync) | card 4 | — | — nothing to send: recordings and the household are on the machine |
| Fetch samples / Fetch models | cards 4, 6 | — | — they are made on the same machine |
| Machine switch on | header | — | — the studio is off while the machine is off; switch it on in Home Assistant (switch.maszyna_gpu) |
| A newer model chosen on the machine than the one fetched | card 6 | — | — one folder: the models are the machine's |
| Access token of the panel (data/panel.json, link with ?token=) | card 1 → Settings | Settings → Login | — replaced by the login (WAKEWORD_UI_AUTH, docker/install-ubuntu.sh) |

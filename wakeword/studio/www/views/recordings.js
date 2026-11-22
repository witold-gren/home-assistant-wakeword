// Recordings on disk (takes, home background), synthetic samples and the review of ElevenLabs takes.
// Taken over from the training panel (renderRecordings, renderSamples, elReviewBlock).

import {
  action, ask, call, card, draft, el, fmt, household, recordingUrl, redraw, renderFamily, selectedWords, state, t, toast,
} from "./common.js";

let recordings = null; // the "recordings" call, loaded when a view needs it
let loading = null;
const picked = new Set();
let player = null;
let playingPath = null;

export function forgetRecordings() {
  recordings = null;
}

export function recordingsLoaded() {
  return recordings;
}

export function loadRecordings() {
  loading ??= call("recordings").then((answer) => {
    recordings = answer;
    const present = new Set([...recordings.takes.flatMap((g) => g.files), ...recordings.background,
      ...(recordings.synthetic || []).flatMap((g) => g.files)].map((f) => f.path));
    for (const path of [...picked]) if (!present.has(path)) picked.delete(path);
  }).catch((err) => toast(err.message, "error")).finally(() => {
    loading = null;
    redraw();
  });
  return loading;
}

function play(path, button) {
  if (elQueue) elStopQueue(); // a take picked by hand ends "listen one after another"
  // the same button again stops it
  const again = player && playingPath === path;
  if (player) { player.pause(); document.querySelectorAll(".play-btn.on").forEach((b) => b.classList.remove("on")); }
  player = null;
  playingPath = null;
  if (again) return;
  player = new Audio(recordingUrl(path));
  playingPath = path;
  button.classList.add("on");
  player.addEventListener("ended", () => { button.classList.remove("on"); player = null; playingPath = null; });
  player.play().catch((err) => toast(err.message, "error"));
}

async function deleteRecordings(paths) {
  if (!paths.length) return;
  if (!(await ask(t("confirm_delete_recordings", { count: paths.length }), { ok: t("delete_recordings_ok"), danger: true }))) return;
  const answer = await action("delete_recordings", { paths });
  if (answer) {
    for (const path of paths) picked.delete(path);
    toast(t("recordings_deleted", { count: paths.length }), "ok");
    // the counts change; the draft (unsaved edits) stays as it is
    household.counts = (await call("household/get")).counts;
  }
  recordings = null;
  await loadRecordings();
}

// a long list is drawn when its group is opened, ROWS_AT_ONCE rows at a time (gpu-studio standard, section 9a):
// thousands of recordings never become thousands of elements in one step
export const ROWS_AT_ONCE = 200;

/** The "Delete selected" button follows the choice without drawing the view again. */
function showPicked() {
  const button = document.querySelector("[data-delete-picked]");
  if (!button) return;
  button.disabled = picked.size === 0;
  button.textContent = t("delete_selected", { count: picked.size });
}

function recordingRow(file, listenOnly) {
  const box = el(listenOnly ? "span" : "input", listenOnly ? {} : { type: "checkbox", "data-pick": file.path });
  if (!listenOnly) {
    box.checked = picked.has(file.path);
    box.addEventListener("change", () => {
      if (box.checked) picked.add(file.path);
      else picked.delete(file.path);
      showPicked();
    });
  }
  const button = el("button", { type: "button", class: "icon-btn play-btn", title: t("listen"), "data-play": file.path }, "▶");
  button.addEventListener("click", (e) => { e.preventDefault(); play(file.path, button); });
  const seconds = file.seconds === null ? t("unreadable") : `${fmt(file.seconds, 1)} s`;
  return el("label", { class: "rec-row" }, box, button,
    el("span", { class: "rec-name" }, file.name),
    el("span", { class: "rec-meta" }, seconds),
    el("span", { class: "rec-meta" }, file.time.replace("T", " ").slice(0, 16)));
}

/** The rows of a group: drawn on the first opening, then ROWS_AT_ONCE more with "Show more". */
function lazyRows(node, files, listenOnly = false) {
  const list = el("div", { class: "rec-list" });
  let shown = 0;
  const more = el("button", { type: "button", class: "btn small", "data-more-rows": "" });
  const next = () => {
    const part = files.slice(shown, shown + ROWS_AT_ONCE).map((file) => recordingRow(file, listenOnly));
    shown += part.length;
    more.remove();
    list.append(...part);
    if (shown < files.length) {
      more.textContent = t("show_more", { count: Math.min(ROWS_AT_ONCE, files.length - shown), left: files.length - shown });
      list.append(more);
    }
  };
  more.addEventListener("click", (e) => { e.preventDefault(); next(); });
  const first = () => { if (node.open && shown === 0 && files.length) next(); };
  node.addEventListener("toggle", first);
  queueMicrotask(first); // a group drawn open
  return list;
}

// synthetic clips: listen only (they are made again by every training)
function syntheticGroup(title, files, note = "") {
  const node = el("details", { class: "rec-group" },
    el("summary", {}, el("span", { class: "rec-icon" }, "🔊"), el("strong", {}, title),
      note ? el("span", { class: "badge" }, note) : null,
      el("span", { class: "rec-meta" }, t("recordings_count", { count: files.length }))));
  node.append(lazyRows(node, files, true));
  return node;
}

function recordingGroup(title, note, files, open = false) {
  const paths = files.map((f) => f.path);
  const all = el("input", { type: "checkbox", title: t("select_all") });
  all.checked = paths.length > 0 && paths.every((p) => picked.has(p));
  const node = el("details", { class: "rec-group" },
    el("summary", {}, all, el("strong", {}, title), note ? el("span", { class: "badge ok" }, note) : null,
      el("span", { class: "rec-meta" }, t("recordings_count", { count: files.length })),
      el("button", { type: "button", class: "btn small danger", onclick: (e) => { e.preventDefault(); deleteRecordings(paths); } },
        t("delete_all"))));
  all.addEventListener("change", () => {
    for (const path of paths) {
      if (all.checked) picked.add(path);
      else picked.delete(path);
    }
    for (const box of node.querySelectorAll("[data-pick]")) box.checked = all.checked; // only the drawn rows
    showPicked();
  });
  node.open = open;
  node.append(lazyRows(node, files));
  return node;
}

/** Recordings of one word (or all): takes per person, the home background, synthetic clips. */
export function renderRecordings(word = null, { background = true } = {}) {
  if (!recordings) {
    loadRecordings();
    return card(t("tab_recordings"), null, el("p", { class: "hint" }, t("loading")));
  }
  const speakers = new Set(draft.speakers.map((s) => s.id));
  const groups = recordings.takes.filter((g) => !word || g.word === word).map((g) => {
    const known = draft.words[g.word];
    const title = `${known ? known.wake_word : g.word} · ${g.speaker}`;
    const note = !known ? t("word_gone") : !speakers.has(g.speaker) ? t("person_gone") : "";
    return recordingGroup(title, note, g.files, Boolean(word));
  });
  const backgroundGroup = background && recordings.background.length
    ? recordingGroup(t("background_recordings"), "", recordings.background, word === null && !groups.length) : null;
  const synthetic = (recordings.synthetic || []).filter((g) => !word || g.word === word).map((g) => syntheticGroup(
    `${t("synthetic_title")} · ${draft.words[g.word]?.wake_word || g.word} · ${t("synthetic_" + g.kind)}`, g.files));
  const chosen = [...picked];
  return card(word ? `${t("tab_recordings")} · ${draft.words[word]?.wake_word || word}` : t("tab_recordings"), null,
    el("p", { class: "hint" }, t("recordings_intro")),
    el("div", { class: "rec-toolbar" },
      el("button", { type: "button", class: "btn", "data-refresh-recordings": "", onclick: () => { recordings = null; redraw(); } }, t("refresh")),
      el("button", { type: "button", class: "btn danger", disabled: !chosen.length, "data-delete-picked": "",
        onclick: () => deleteRecordings([...picked]) }, t("delete_selected", { count: chosen.length }))),
    groups.length || backgroundGroup ? el("div", { class: "rec-groups" }, groups, backgroundGroup)
      : el("p", { class: "hint" }, t("no_recordings")),
    background ? el("h4", { class: "rec-heading" }, t("synthetic_title")) : null,
    background ? el("p", { class: "hint" }, t("synthetic_hint")) : null,
    background ? (synthetic.length ? el("div", { class: "rec-groups" }, synthetic) : el("p", { class: "hint" }, t("synthetic_none"))) : null);
}

/** Only the home background recordings. */
export function renderBackground() {
  if (!recordings) {
    loadRecordings();
    return card(t("background_recordings"), null, el("p", { class: "hint" }, t("loading")));
  }
  const chosen = [...picked].filter((p) => recordings.background.some((f) => f.path === p));
  return card(t("background_recordings"), null,
    el("div", { class: "rec-toolbar" },
      el("button", { type: "button", class: "btn", onclick: () => { recordings = null; redraw(); } }, t("refresh")),
      el("button", { type: "button", class: "btn danger", disabled: !chosen.length,
        onclick: () => deleteRecordings(chosen) }, t("delete_selected", { count: chosen.length }))),
    recordings.background.length ? el("div", { class: "rec-groups" }, recordingGroup(t("background_recordings"), "", recordings.background, true))
      : el("p", { class: "hint" }, t("no_recordings")));
}

// --- synthetic samples of the chosen words, one group per voice, to check before training ---------

// voice names saved in household.yaml (or the defaults); null until the household is loaded
function activeVoiceNames() {
  if (!household) return null;
  const saved = household.data.voices || {};
  const all = { ...(household.default_voices || {}), ...saved };
  return new Set(Object.values(all).flat().map((v) => v.split("/").pop()));
}

const sampleVoice = (name) => name.replace(/_\d+_\d+\.wav$/, "");
// "pl_PL-gosia-medium", "WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium" -> "pl"
export const voiceLanguage = (voice) => voice.split("/").pop().split(/[_-]/)[0].toLowerCase();
let samplesOpen = new Set();

export function renderSamples() {
  const box = el("div", { class: "samples", id: "samples" });
  if (!recordings) {
    loadRecordings();
    box.append(el("p", { class: "hint" }, t("loading")));
    return box;
  }
  const chosen = state.words.filter((w) => selectedWords.has(w.id)).map((w) => w.id);
  const groups = (recordings.synthetic || []).filter((g) => !chosen.length || chosen.includes(g.word));
  const active = activeVoiceNames();
  const eleven = (recordings.elevenlabs || []).filter((g) => !chosen.length || chosen.includes(g.word));
  if (!groups.length && !eleven.length) {
    box.append(el("p", { class: "hint" }, t("synthetic_none")));
    return box;
  }
  const sections = [];
  for (const word of [...new Set([...groups, ...eleven].map((g) => g.word))]) {
    const name = state.words.find((w) => w.id === word)?.wake_word || word;
    const positive = groups.find((g) => g.word === word && g.kind === "positive")?.files || [];
    const negative = groups.find((g) => g.word === word && g.kind === "negative")?.files || [];
    const voices = new Map();
    for (const file of positive) {
      const voice = sampleVoice(file.name);
      voices.set(voice, [...(voices.get(voice) || []), file]);
    }
    const details = [...voices].map(([voice, files]) => {
      const off = active && voice !== "en_generator" && !active.has(voice);
      const node = syntheticGroup(voice, files, off ? t("sample_voice_off") : "");
      node.dataset.key = `${word}:${voice}`;
      node.classList.toggle("off", Boolean(off));
      return node;
    });
    // chosen in the voices but not made yet: the synthesis runs at "Start training"
    const languages = Object.keys(household?.data.words[word]?.spellings || {});
    for (const voice of active || []) {
      if (voices.has(voice) || !languages.includes(voiceLanguage(voice))) continue;
      details.push(el("div", { class: "rec-group waiting" },
        el("div", { class: "rec-summary" }, el("span", { class: "rec-icon" }, "⏳"), el("strong", {}, voice),
          el("span", { class: "badge" }, t("sample_voice_waiting")))));
    }
    if (negative.length) {
      const node = syntheticGroup(t("synthetic_negative"), negative);
      node.dataset.key = `${word}:negative`;
      details.push(node);
    }
    // ElevenLabs takes: one block for all voices, each voice with all its spellings
    const byVoice = new Map();
    for (const g of eleven.filter((x) => x.word === word)) {
      const voice = g.group.replace(/_\d+$/, "");
      byVoice.set(voice, [...(byVoice.get(voice) || []), ...g.files]);
    }
    if (byVoice.size) details.push(elReviewBlock(word, byVoice));
    for (const node of details) {
      if (node.tagName === "DETAILS") {
        node.open = samplesOpen.has(node.dataset.key);
        node.addEventListener("toggle", () => {
          if (node.open) samplesOpen.add(node.dataset.key);
          else samplesOpen.delete(node.dataset.key);
        });
      }
    }
    sections.push(el("h4", { class: "rec-heading" }, `${name} · ${t("samples_voices", { count: voices.size })}`),
      el("div", { class: "rec-groups" }, details));
  }
  box.append(el("p", { class: "hint" }, t("samples_hint")), ...sections);
  return box;
}

// --- ElevenLabs takes: search, a page at a time, listen one after another, switch a voice off ----------
const EL_SAMPLES_PAGE = 20;
const elReview = {}; // word → { query, limit }
const elReviewFill = {}; // word → redraws the list of its block
let elQueue = null; // { word, voices, index } while "listen one after another" plays

const elVoiceId8 = (key) => key.match(/-([A-Za-z0-9]{8})$/)?.[1] || "";

function elVoiceState(key) {
  const id8 = elVoiceId8(key);
  const match = (v) => v.id.slice(0, 8) === id8;
  const saved = (household?.data.elevenlabs?.voices || []).filter(match);
  const chosen = (draft?.elevenlabs?.voices || []).filter(match);
  const name = (chosen[0] || saved[0])?.name || key.replace(/-[A-Za-z0-9]{8}$/, "").replaceAll("_", " ");
  return { name, on: chosen.length > 0, restorable: !chosen.length && saved.length > 0, saved, match };
}

function elSetVoice(key, on) {
  const { saved, match } = elVoiceState(key);
  draft.elevenlabs ||= { model: household.elevenlabs_models[0], count: 5, voices: [] };
  const settings = draft.elevenlabs;
  settings.voices = settings.voices.filter((v) => !match(v));
  if (on) settings.voices.push(...saved);
  renderFamily();
}

function elSampleRow(word, key, files) {
  const voice = elVoiceState(key);
  const listen = el("button", { type: "button", class: "icon-btn play-btn", title: t("listen") }, "▶");
  listen.addEventListener("click", (e) => { e.preventDefault(); play(files[0].path, listen); });
  const toggle = household && (voice.on || voice.restorable)
    ? el("button", { type: "button", class: `btn small${voice.on ? " danger" : ""}`,
      onclick: (e) => { e.preventDefault(); elSetVoice(key, !voice.on); } },
    t(voice.on ? "el_voice_disable" : "el_voice_enable"))
    : null;
  const node = el("details", { class: `rec-group el-sample${voice.on || !household ? "" : " off"}` },
    el("summary", {}, listen, el("strong", { title: voice.name }, voice.name),
      voice.on || !household ? null : el("span", { class: "badge" }, t("el_voice_off")),
      el("span", { class: "rec-meta" }, t("recordings_count", { count: files.length })), toggle));
  // the takes are drawn when the voice is opened: hundreds of voices × all takes would be thousands of rows
  node.append(lazyRows(node, files, true));
  node.dataset.key = `${word}:el:${key}`;
  node.dataset.voice = key;
  node.dataset.word = word;
  node.open = samplesOpen.has(node.dataset.key);
  return node;
}

function elReviewBlock(word, byVoice) {
  const review = (elReview[word] ||= { query: "", limit: EL_SAMPLES_PAGE });
  const voices = [...byVoice];
  const takes = voices.reduce((sum, [, files]) => sum + files.length, 0);
  const off = household ? voices.filter(([key]) => !elVoiceState(key).on).length : 0;
  const list = el("div", { class: "rec-groups" });
  const more = el("button", { type: "button", class: "btn small" });
  const search = el("input", { type: "search", placeholder: t("el_review_search") });
  search.value = review.query;
  const playAll = el("button", { type: "button", class: "btn small", "data-play-all": word });
  const matching = () => {
    const query = review.query.trim().toLowerCase();
    return voices.filter(([key]) => !query || elVoiceState(key).name.toLowerCase().includes(query));
  };
  function fill() {
    const shown = matching();
    const rows = shown.slice(0, review.limit).map(([key, files]) => elSampleRow(word, key, files));
    list.replaceChildren(...(rows.length ? rows : [el("p", { class: "hint" }, t("el_review_none"))]));
    const left = shown.length - review.limit;
    more.hidden = left <= 0;
    more.textContent = t("el_review_more", { count: Math.min(EL_SAMPLES_PAGE, left), left });
    playAll.textContent = elQueue?.word === word ? t("el_review_stop") : t("el_review_play_all", { count: shown.length });
    playAll.disabled = !shown.length;
    elMarkPlaying();
  }
  elReviewFill[word] = fill;
  search.addEventListener("input", () => { review.query = search.value; review.limit = EL_SAMPLES_PAGE; fill(); });
  more.addEventListener("click", () => { review.limit += EL_SAMPLES_PAGE; fill(); });
  playAll.addEventListener("click", () => (elQueue?.word === word ? elStopQueue() : elPlayQueue(word, matching())));
  fill();
  const node = el("details", { class: "rec-group el-review" },
    el("summary", {}, el("span", { class: "rec-icon" }, "🎙"), el("strong", {}, "ElevenLabs"),
      el("span", { class: "rec-meta" }, t("el_review_count", { voices: voices.length, takes })),
      off ? el("span", { class: "badge" }, t("el_review_off", { count: off })) : null),
    el("div", { class: "el-review-body" },
      el("p", { class: "hint" }, t("el_review_hint")),
      el("div", { class: "el-review-tools" }, search, playAll),
      list, more));
  node.dataset.key = `${word}:elevenlabs`;
  return node;
}

// "listen one after another": the first take of every voice shown, the list follows the voice playing
function elPlayQueue(word, voices) {
  if (elQueue) elStopQueue();
  if (player) player.pause();
  elQueue = { word, voices, index: 0 };
  elPlayNext();
}

function elPlayNext() {
  const queue = elQueue;
  if (!queue) return;
  if (queue.index >= queue.voices.length) { elStopQueue(); return; }
  const review = elReview[queue.word];
  if (queue.index >= review.limit) review.limit = (Math.floor(queue.index / EL_SAMPLES_PAGE) + 1) * EL_SAMPLES_PAGE;
  const path = queue.voices[queue.index][1][0].path;
  player = new Audio(recordingUrl(path));
  playingPath = path;
  const next = () => { if (elQueue === queue) { queue.index += 1; elPlayNext(); } };
  player.addEventListener("ended", next);
  player.addEventListener("error", next); // an unreadable take does not stop the round
  player.play().catch(() => {});
  elReviewFill[queue.word]?.();
  elMarkPlaying(true);
}

function elStopQueue() {
  const queue = elQueue;
  elQueue = null;
  if (player) player.pause();
  player = null;
  playingPath = null;
  if (queue) elReviewFill[queue.word]?.();
}

function elMarkPlaying(scroll = false) {
  const voice = elQueue?.voices[elQueue.index]?.[0];
  for (const node of document.querySelectorAll("#samples .el-sample")) {
    const playing = Boolean(voice) && node.dataset.word === elQueue.word && node.dataset.voice === voice;
    node.classList.toggle("playing", playing);
    if (playing && scroll) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

/** Plays a test take (a blob) - the ElevenLabs view uses the same player. */
export function playUrl(url) {
  if (player) player.pause();
  player = new Audio(url);
  return player.play();
}

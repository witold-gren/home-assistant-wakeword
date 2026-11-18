// Wake word recorder: records in the browser, converts to 16 kHz mono 16-bit WAV and uploads.
"use strict";

const TARGET_RATE = 16000;
const MAX_SECONDS = 6;

const state = { info: null, speaker: null, word: null, next: null, stream: null, ctx: null,
  chunks: [], recording: false, wav: null, timer: null };

const $ = (id) => document.getElementById(id);
const LANG_KEY = "wakeword-lang";
let chosenLanguage = null;
try { chosenLanguage = localStorage.getItem(LANG_KEY); } catch (e) { chosenLanguage = null; }
const langQuery = () => (chosenLanguage ? `lang=${encodeURIComponent(chosenLanguage)}` : "");
const t = (key, values = {}) =>
  (state.info?.ui[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function show(section) {
  for (const id of ["who", "words", "record"]) $(id).hidden = id !== section;
  $("back").hidden = section === "who";
  $("back").textContent = "← " + t("back");
  $("back").onclick = section === "record" ? () => openSpeaker(state.speaker) : () => showWho();
}

function setStatus(text, kind = "") {
  $("status").textContent = text;
  $("status").className = "status " + kind;
}

async function load() {
  state.info = await api("/api/info?" + langQuery());
  document.documentElement.lang = state.info.language;
  $("lang-switch").replaceChildren(...state.info.languages.map((code) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = code;
    button.className = code === state.info.language ? "on" : "";
    button.onclick = () => {
      try { localStorage.setItem(LANG_KEY, code); } catch (e) { /* private mode */ }
      location.reload();
    };
    return button;
  }));
  document.title = t("title");
  $("title").textContent = t("title");
  for (const el of document.querySelectorAll("[data-ui]")) el.textContent = t(el.dataset.ui);
  if (!window.isSecureContext) {
    $("warning").textContent = t("https_needed");
    $("warning").hidden = false;
  }
}

function showWho() {
  const box = $("speakers");
  box.replaceChildren();
  for (const speaker of state.info.speakers) {
    const button = document.createElement("button");
    button.textContent = speaker.id;
    button.onclick = () => openSpeaker(speaker.id);
    box.append(button);
  }
  show("who");
}

async function openSpeaker(id) {
  state.info = await api("/api/info?" + langQuery());
  state.speaker = id;
  const speaker = state.info.speakers.find((s) => s.id === id);
  const list = $("word-list");
  list.replaceChildren();
  for (const word of speaker.words) {
    const button = document.createElement("button");
    const name = document.createElement("strong");
    name.textContent = word.wake_word;
    const progress = document.createElement("span");
    const complete = word.done >= word.target;
    progress.className = complete ? "done" : "muted";
    progress.textContent = complete ? "✓ " + t("progress", word) : t("progress", word);
    button.append(name, progress);
    button.onclick = () => openWord(word.id);
    list.append(button);
  }
  show("words");
}

async function openWord(id) {
  state.word = id;
  state.wav = null;
  const word = state.info.speakers.find((s) => s.id === state.speaker).words.find((w) => w.id === id);
  $("say").textContent = t("say", { word: word.wake_word });
  $("review").hidden = true;
  setStatus("");
  await refreshNext();
  show("record");
}

async function refreshNext() {
  const q = new URLSearchParams({ word: state.word, speaker: state.speaker });
  state.next = await api("/api/next?" + q);
  const n = state.next;
  $("progress-text").textContent = n.done >= n.target ? t("all_done") : t("progress", n);
  $("progress-bar").style.width = Math.min(100, (100 * n.done) / n.target) + "%";
  $("instruction").textContent = t("next_take", { number: n.number, target: Math.max(n.target, n.number),
    instruction: state.info.takes[n.variant] });
  renderFiles(n.files);
}

function renderFiles(files) {
  $("files-summary").textContent = t("progress", { done: files.length, target: state.next.target });
  const list = $("files");
  list.replaceChildren();
  for (const name of files.slice().reverse()) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = name;
    const listen = document.createElement("button");
    listen.textContent = t("listen");
    const q = new URLSearchParams({ word: state.word, speaker: state.speaker, file: name });
    listen.onclick = () => new Audio("/api/take?" + q).play();
    const remove = document.createElement("button");
    remove.textContent = t("delete");
    remove.onclick = async () => {
      await api("/api/take?" + q, { method: "DELETE" });
      await refreshNext();
    };
    item.append(label, listen, remove);
    list.append(item);
  }
}

async function ensureMicrophone() {
  if (state.stream) return;
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
  } catch (err) {
    $("warning").textContent = t("mic_denied");
    $("warning").hidden = false;
    throw err;
  }
}

async function start() {
  await ensureMicrophone();
  state.ctx = state.ctx || new (window.AudioContext || window.webkitAudioContext)();
  await state.ctx.resume();
  const source = state.ctx.createMediaStreamSource(state.stream);
  // ScriptProcessor is deprecated but works everywhere (including iOS Safari) without extra files.
  const processor = state.ctx.createScriptProcessor(4096, 1, 1);
  state.chunks = [];
  processor.onaudioprocess = (event) => {
    if (!state.recording) return;
    const data = event.inputBuffer.getChannelData(0);
    state.chunks.push(new Float32Array(data));
    let sum = 0;
    for (const v of data) sum += v * v;
    const db = 20 * Math.log10(Math.sqrt(sum / data.length) || 1e-8);
    $("level").style.width = Math.max(0, Math.min(100, (db + 60) * (100 / 60))) + "%";
  };
  source.connect(processor);
  processor.connect(state.ctx.destination);
  state.node = { source, processor };
  state.recording = true;
  $("start").hidden = true;
  $("stop").hidden = false;
  $("review").hidden = true;
  setStatus("");
  state.timer = setTimeout(stop, MAX_SECONDS * 1000);
}

function stop() {
  if (!state.recording) return;
  clearTimeout(state.timer);
  state.recording = false;
  state.node.source.disconnect();
  state.node.processor.disconnect();
  $("level").style.width = "0";
  $("start").hidden = false;
  $("stop").hidden = true;
  const samples = concat(state.chunks);
  state.wav = encodeWav(downsample(samples, state.ctx.sampleRate, TARGET_RATE), TARGET_RATE);
  $("review").hidden = false;
}

function concat(chunks) {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let offset = 0;
  for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.length; }
  return out;
}

// Average over each output sample's span (a simple low-pass) and pick — fine for speech.
function downsample(samples, rate, target) {
  if (rate === target) return samples;
  const ratio = rate / target;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function keep() {
  const q = new URLSearchParams({ word: state.word, speaker: state.speaker, variant: state.next.variant });
  $("keep").disabled = true;
  try {
    const result = await api("/api/take?" + q, { method: "POST", body: state.wav,
      headers: { "Content-Type": "audio/wav" } });
    const problems = result.issues.filter((i) => ["too_quiet", "clipped", "no_speech"].includes(i));
    if (!result.saved) setStatus(t("no_speech"), "bad");
    else if (problems.length) setStatus(problems.map((i) => t(i)).join(" "), "bad");
    else setStatus(t("saved"), "good");
    state.wav = null;
    $("review").hidden = true;
    await refreshNext();
  } catch (err) {
    setStatus(err.message, "bad");
  } finally {
    $("keep").disabled = false;
  }
}

$("start").onclick = () => start().catch((err) => setStatus(err.message, "bad"));
$("stop").onclick = stop;
$("listen").onclick = () => state.wav && new Audio(URL.createObjectURL(state.wav)).play();
$("redo").onclick = () => { state.wav = null; $("review").hidden = true; setStatus(""); };
$("keep").onclick = keep;

load().then(showWho).catch((err) => { $("warning").textContent = err.message; $("warning").hidden = false; });

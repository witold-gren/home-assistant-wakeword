// What every view of the studio shares: the state of the training machine, the household and its draft (live
// bindings the frame sets), the texts, small DOM helpers and the calls.

import { STUDIO_STRINGS } from "../i18n.js";

export let state = null; // the "state" call: training, words, Home Assistant, machine …
export let household = null; // the "household/get" call: saved data, counts, languages, ESPHome devices
export let draft = null; // the household being edited (the draft of household.yaml)

let hooks = {};

/** The frame gives the views its state, household and draft (and gives them again after every change). */
export function bind(next) {
  if ("state" in next) state = next.state;
  if ("household" in next) household = next.household;
  if ("draft" in next) draft = next.draft;
}

/** What the views ask of the frame: redraw, mark the draft changed, toasts, questions, selecting a node. */
export function setHooks(next) {
  hooks = next;
}

// The training panel's texts first (the views were its cards), then the studio's own.
export const t = (key, values = {}) => {
  const language = state?.language === "pl" ? "pl" : "en";
  // the studio's own words first (like app.js): some texts of the old panel name its cards and buttons
  const text = STUDIO_STRINGS[language][key] ?? state?.ui?.[key] ?? STUDIO_STRINGS.en[key] ?? key;
  return String(text).replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
};

export const fmt = (value, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : Number(value).toLocaleString(state?.language || "en", { minimumFractionDigits: digits, maximumFractionDigits: digits });

// "uk — ukraiński": a bare code is easy to mistake (uk is Ukrainian, not UK English)
export function langLabel(code) {
  try {
    const name = new Intl.DisplayNames([state?.language || "en"], { type: "language" }).of(code);
    return name && name !== code ? `${code} — ${name}` : code;
  } catch {
    return code;
  }
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child);
  return node;
}

export const icon = (name) => el("ha-icon", { icon: name });

// --- the draft ----------------------------------------------------------------------------------

/** The draft changed in place; the view stays as it is (typing). `key` merges quick typing into one undo step. */
export const markDirty = (key = null) => hooks.changed?.({ key, redraw: false });
/** The draft changed (or a list must be drawn again): the view is drawn again. */
export const renderFamily = () => hooks.changed?.({ key: null, redraw: true });
/** Draw the view again without touching the draft (e.g. a list fetched from the machine). */
export const redraw = () => hooks.redraw?.();
export const refresh = () => hooks.refresh?.();
export const select = (key) => hooks.select?.(key);
export const isDirty = () => hooks.isDirty?.() ?? false;

// --- talking to the studio ----------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(message, status, body = {}) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

// no request may hang the page: every call ends after this (a slow Home Assistant or machine says so instead)
export const CALL_TIMEOUT_MS = 150000; // above the server's own limits (Home Assistant: 60 s)

export async function call(type, data = {}, { timeout = CALL_TIMEOUT_MS } = {}) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeout);
  let response;
  try {
    response = await fetch("/api/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, type }),
      signal: abort.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw new ApiError(t("call_timeout", { seconds: Math.round(timeout / 1000) }), 0, {});
    throw err;
  } finally {
    clearTimeout(timer);
  }
  const body = await response.json().catch(() => ({}));
  if (response.status === 401 && body.login) {
    location.assign("/login");
    throw new ApiError(body.error, 401, body);
  }
  if (!response.ok) throw new ApiError(body.error || response.statusText, response.status, body);
  return body;
}

export const recordingUrl = (path) => `/api/recording?path=${encodeURIComponent(path)}`;

// actions whose output goes to "Command output"
export const JOB_ACTIONS = new Set(["check", "prepare", "evaluate", "export", "elevenlabs_generate", "ha_pull",
  "evaluate_models"]);

export async function action(name, extra = {}, button = null) {
  if (button) button.classList.add("busy");
  try {
    const answer = await call("action", { action: name, ...extra });
    if (answer.warning) toast(t("ha_push_failed", { error: answer.warning }), "error");
    await refresh();
    if (JOB_ACTIONS.has(name)) hooks.jobStarted?.(name);
    return answer;
  } catch (err) {
    toast(err.message, "error");
    return null;
  } finally {
    if (button) button.classList.remove("busy");
  }
}

// --- toasts, questions, help ----------------------------------------------------------------------

export function toast(text, kind = "") {
  let box = document.getElementById("toasts");
  if (!box) {
    box = el("div", { id: "toasts", class: "toasts", "aria-live": "polite" });
    document.body.append(box);
  }
  const node = el("div", { class: `toast ${kind}` }, text);
  box.append(node);
  // long messages stay long enough to be read
  setTimeout(() => node.remove(), Math.max(kind === "error" ? 7000 : 3500, String(text).length * 70));
}

// a question in the studio's own window; resolves true for OK, false for Cancel, Esc or a click outside
export function ask(message, { danger = false } = {}) {
  const ok = el("button", { type: "button", class: `btn ${danger ? "danger" : "primary"}`, "data-ask-ok": "" }, "OK");
  const cancel = el("button", { type: "button", class: "btn", "data-ask-cancel": "" }, t("cancel"));
  const dialog = el("dialog", { class: "ask" }, el("p", {}, message), el("div", { class: "actions" }, cancel, ok));
  document.body.append(dialog);
  return new Promise((resolve) => {
    const finish = (answer) => {
      if (dialog.open) dialog.close();
      dialog.remove();
      resolve(answer);
    };
    dialog.addEventListener("close", () => finish(false));
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    dialog.onclick = (e) => { if (e.target === dialog) finish(false); };
    dialog.showModal();
    ok.focus();
  });
}

// --- help: "?" opens a small window with the text of this one thing (gpu-studio standard, section 5) ---------------

let openHelp = null; // { button, close }

/** Close the open help window (Esc, a click beside it, the same "?" again, another view). */
export function closeHelp() {
  const open = openHelp;
  openHelp = null;
  open?.close();
}

function paragraphs(text) {
  return text.split("\n\n").map((part) => {
    const lines = part.split("\n");
    return lines.every((l) => l.startsWith("• "))
      ? el("ul", {}, ...lines.map((l) => el("li", {}, l.slice(2))))
      : el("p", {}, part);
  });
}

/** Open (or close, when it is open for this button) the help window next to `button`. */
export function showHelp(button, { title, html = null, text = null, docsKey = null }) {
  if (openHelp?.button === button) return closeHelp();
  closeHelp();
  const body = el("div", { class: "help-pop-body" });
  if (html) body.innerHTML = html; // the panel's own texts (language packs)
  else if (text) body.append(...paragraphs(text));
  const more = docsLink(docsKey);
  const pop = el("div", { class: "help-pop", role: "dialog", "aria-label": title, "data-help-pop": docsKey || "" },
    el("div", { class: "help-pop-head" }, el("strong", {}, title),
      el("button", { type: "button", class: "help-pop-close", "aria-label": t("close"), title: t("close"),
        onclick: () => closeHelp() }, "✕")),
    body, more ? el("p", { class: "help-pop-more" }, more) : null, lessonButton());
  document.body.append(pop);
  // next to the button, inside the screen
  const r = button.getBoundingClientRect();
  const width = Math.min(380, window.innerWidth - 16);
  pop.style.width = `${width}px`;
  pop.style.left = `${Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8))}px`;
  let top = r.bottom + 6;
  if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 6);
  pop.style.top = `${top}px`;
  const onKey = (e) => { if (e.key === "Escape") closeHelp(); };
  const onDown = (e) => { if (!pop.contains(e.target) && !button.contains(e.target)) closeHelp(); };
  document.addEventListener("keydown", onKey);
  document.addEventListener("pointerdown", onDown, true);
  button.setAttribute("aria-expanded", "true");
  openHelp = {
    button,
    close() {
      pop.remove();
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown, true);
    },
  };
  return undefined;
}

// the lesson of the chosen node under a help text (gpu-studio standard, section 5a): "Show me step by step"
function lessonButton() {
  const lesson = hooks?.lessonFor?.();
  if (!lesson) return null;
  return el("p", { class: "help-pop-more" }, el("button", { type: "button", class: "btn small", "data-help-lesson": lesson,
    onclick: () => { closeHelp(); hooks.startLesson(lesson); } }, t("help_lesson")));
}

/** A "?" button for a card: opens its help window. */
export function helpButton(title, help, docsKey = null) {
  return el("button", { type: "button", class: "help-btn", title: t("help"), "aria-label": t("help"),
    "aria-expanded": "false", "data-help": docsKey || "",
    onclick: (e) => showHelp(e.currentTarget, { title, html: help, docsKey }) }, "?");
}

/** "How to read" as a small text button (not another "?") that opens the explanation in the help window. */
export function helpBox(key) {
  return el("button", { type: "button", class: "link-btn how-to-read", "data-how-to-read": key,
    onclick: (e) => showHelp(e.currentTarget, { title: t("how_to_read"), text: t(key) }) }, t("how_to_read"));
}

/** A card of a view: its title, a "?" with the training panel's help for it, the content. */
// where each "?" leads in the documentation (gpu-studio standard, section 5): page#anchor of docs/<lang>/;
// tests/studio/test_studio_docs.py checks every page and anchor exists in both languages
export const DOCS_LINKS = {
  household: "02-plan-your-household.html#file-fields",
  words: "02-plan-your-household.html#how-to-choose-a-good-word",
  machine: "11-studio.html#switching-the-machine-off",
  data: "12-training-well.html#how-many-recordings-and-which",
  training: "12-training-well.html#training-parameters",
  progress: "12-training-well.html#reading-the-results",
  log: "06-training.html#how-long-it-takes-and-what-you-see",
  results: "07-evaluation.html#how-to-read-the-table",
  models: "12-training-well.html#reading-the-results",
};

/** The documentation built into the studio (/docs/), in the page's language; `page` = "file.html#anchor". */
export function docsUrl(page = "") {
  return `/docs/${state?.language === "pl" ? "pl" : "en"}/${page}`;
}

/** "More in the documentation" under a help text, when the key has a chapter. */
export function docsLink(key) {
  const page = DOCS_LINKS[key];
  return page ? el("a", { class: "docs-link", href: docsUrl(page), target: "_blank", rel: "noopener",
    "data-docs-link": key }, t("docs_more")) : null;
}

export function card(title, helpKey, ...children) {
  const help = helpKey && state?.help?.[helpKey];
  const button = help ? helpButton(title, help, helpKey) : null;
  return el("section", { class: "card view-card" }, el("div", { class: "card-head" }, el("h2", {}, title), button),
    ...children);
}

// --- fields -------------------------------------------------------------------------------------------

export function field(label, input, hint) {
  return el("label", { class: "field" }, el("span", {}, label), input, hint ? el("p", { class: "hint" }, hint) : null);
}

export function input(value, oninput, attrs = {}) {
  const node = el("input", { value: value ?? "", ...attrs });
  node.value = value ?? "";
  node.addEventListener("input", () => { oninput(node.value, node); markDirty(node); });
  return node;
}

export function choice(options, value, onchange) {
  const node = el("select", {}, ...options.map(([v, label]) => el("option", { value: v }, label)));
  node.value = value ?? "";
  node.addEventListener("change", () => { onchange(node.value); markDirty(); });
  return node;
}

export const ID_RE = /^[a-z0-9][a-z0-9_]*$/;
const POLISH = { ą: "a", ć: "c", ę: "e", ł: "l", ń: "n", ó: "o", ś: "s", ź: "z", ż: "z" };
export const slug = (text) =>
  text.toLowerCase().replace(/[ąćęłńóśźż]/g, (c) => POLISH[c]).normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "word";
export const splitList = (text) => text.split(",").map((x) => x.trim()).filter(Boolean);

// --- clipboard ----------------------------------------------------------------------------------------

// the API needs a secure page (https or localhost); over a plain http:// address fall back to execCommand
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = el("textarea", { readonly: true, style: "position:fixed;top:-1000px;opacity:0" });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export async function copyButton(button, getText) {
  const label = button.querySelector("span");
  try {
    const text = await getText();
    if (!text) return toast(t("copy_empty"));
    if (!(await copyText(text))) throw new Error("copy");
    button.classList.add("done");
    label.textContent = t("copied");
    setTimeout(() => { button.classList.remove("done"); label.textContent = t("copy"); }, 1600);
  } catch {
    toast(t("copy_failed"), "error");
  }
  return undefined;
}

// --- drag and drop: the order of the cards is the order in household.yaml ------------------------------

let dragFrom = null;

export function moveItem(list, from, to) {
  // `to` is an insertion point in the original list (0..length)
  const [item] = list.splice(from, 1);
  list.splice(to > from ? to - 1 : to, 0, item);
  return list;
}

export function dragHandle() {
  return el("button", { type: "button", class: "drag-handle", title: t("drag_hint"), "aria-label": t("drag_hint") }, "⠿");
}

export function sortable(cards, onMove) {
  const clear = () => document.querySelectorAll(".drop-before, .drop-after")
    .forEach((n) => n.classList.remove("drop-before", "drop-after"));
  const after = (card, e) => { const r = card.getBoundingClientRect(); return e.clientX > r.left + r.width / 2; };
  const move = (from, to) => { if (to !== from && to !== from + 1) { onMove(from, to); renderFamily(); } };
  cards.forEach((card, index) => {
    const handle = card.querySelector(".drag-handle");
    card.classList.add("sortable");
    // only the handle starts a drag, so text in the inputs can still be selected
    handle.addEventListener("mousedown", () => { card.draggable = true; });
    handle.addEventListener("mouseup", () => { card.draggable = false; });
    handle.addEventListener("keydown", (e) => {
      const step = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 2, ArrowDown: 2 }[e.key];
      if (step === undefined) return;
      e.preventDefault();
      const to = Math.max(0, Math.min(cards.length, index + step));
      move(index, to);
      document.querySelectorAll(".view .sortable .drag-handle")[Math.max(0, Math.min(cards.length - 1, to > index ? to - 1 : to))]?.focus();
    });
    card.addEventListener("dragstart", (e) => {
      dragFrom = index;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(index));
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => { card.draggable = false; card.classList.remove("dragging"); dragFrom = null; clear(); });
    card.addEventListener("dragover", (e) => {
      if (dragFrom === null) return;
      e.preventDefault();
      clear();
      card.classList.add(after(card, e) ? "drop-after" : "drop-before");
    });
    card.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragFrom === null) return;
      const from = dragFrom;
      dragFrom = null;
      clear();
      move(from, index + (after(card, e) ? 1 : 0));
    });
  });
  return cards;
}

// --- the words chosen for preparing, training and the models (kept per browser) ------------------------

const WORDS_KEY = "wakeword-words";
export const selectedWords = new Set();
let wordsInitialised = false;

export function saveSelectedWords() {
  try { localStorage.setItem(WORDS_KEY, JSON.stringify([...selectedWords])); } catch { /* private mode */ }
}

export function initSelectedWords() {
  if (wordsInitialised || !state) return;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(WORDS_KEY) || "null"); } catch { saved = null; }
  const known = new Set(state.words.map((w) => w.id));
  if (Array.isArray(saved) && saved.some((id) => known.has(id))) saved.filter((id) => known.has(id)).forEach((id) => selectedWords.add(id));
  else state.words.filter((w) => w.prepared).forEach((w) => selectedWords.add(w.id)); // first visit: the prepared ones
  wordsInitialised = true;
}

export const wordName = (word) => state?.words.find((w) => w.id === word)?.wake_word || word;

export function duration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h} h ${m} min` : `${m} min ${String(s).padStart(2, "0")} s`;
}

// --- folding kept per browser (blocks of a view, e.g. one word's models) ---------------------------------

const COLLAPSE_KEY = "wakeword-studio-blocks";
export let collapsed = {};
try { collapsed = JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "{}"); } catch { collapsed = {}; }
export function saveCollapsed() {
  try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsed)); } catch { /* private mode */ }
}

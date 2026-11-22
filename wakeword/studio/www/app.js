// The wake word studio: the training panel as an editor, laid out like the Home Dashboard and Assist Router editors.
// Three columns: the tree (household, recordings, voices, training, settings), the view of what is chosen (or the
// whole household.yaml) and on the side the YAML of the choice or the live training. Every change of the household
// goes to a draft kept on the training machine, which changes nothing until "Save"; undo and redo work over it.

import { LitElement, html, nothing } from "./vendor/lit-all.min.js";
import { parse, stringify } from "./vendor/yaml.js";
import { LANGUAGES, translate } from "./i18n.js";
import { buildOutline, filterOutline, findNode, flattenOutline } from "./outline.js";
import { describeChanges, diffHunks, diffLines } from "./changes.js";
import * as common from "./views/common.js";
import { renderDevices, renderPeople, renderTargets, renderWords } from "./views/family.js";
import { forgetRecordings, renderBackground, renderRecordings, renderSamples } from "./views/recordings.js";
import { renderElevenLabs, renderVoices } from "./views/voices.js";
import { machineLabel, renderAccount, renderHfToken, renderHomeAssistant, renderPower, switchMachineOff } from "./views/settings.js";
import {
  liveCard, renderData, renderExport, renderJobs, renderLive, renderRun, renderWordsToTrain, updateJobs, updateLive,
} from "./views/training.js";
import { forgetModels, renderModels, watchModels } from "./views/models.js";
import { renderOverview } from "./views/overview.js";
import { renderFalseWakes } from "./views/false_wakes.js";
import { tourSeen } from "./tour.js";
import { findLesson, lessonForNode } from "./lessons.js";

const APP_TAG = "wakeword-studio";
export const POLL_MS = 2000;
// lines of the running job in the right column (it fills the column to its foot)
const SIDE_JOB_LINES = 400;
export const STATE_TIMEOUT_MS = 20000; // a state that does not come in 20 s is said, not waited for
// A draft is kept this long after the last change, so typing does not send every letter.
export const DRAFT_SAVE_MS = 800;
// Steps that can be undone; typing in one place within this time is one step, not one per letter.
export const UNDO_LIMIT = 200;
const COALESCE_MS = 1500;
const THEME_KEY = "wakeword-studio-theme";
const LANG_KEY = "wakeword-studio-lang";
const WIDTHS_KEY = "wakeword-studio-widths";
const FOLDED_KEY = "wakeword-studio-folded";
export const FOLDED_WIDTH = 28; // a folded column stays as a strip with its unfold button
const COLLAPSED_KEY = "wakeword-studio-collapsed";
const NODE_KEY = "wakeword-studio-node";
export const THEMES = ["auto", "light", "dark"];
const LANGUAGE_NAMES = { pl: "Polski", en: "English" };
const THEME_ICONS = { auto: "mdi:theme-light-dark", light: "mdi:weather-sunny", dark: "mdi:weather-night" };
// The side columns: their width when nothing was chosen, and how narrow and wide a drag can make them.
export const COLUMNS = { left: { start: 290, min: 220, max: 520 }, right: { start: 380, min: 300, max: 680 } };
// jobs that change what is on disk: the recordings and the counts are read again when they end
const DISK_JOBS = new Set(["ha_pull", "prepare", "elevenlabs", "elevenlabs_generate"]);

export function columnWidth(side, width) {
  const { min, max } = COLUMNS[side];
  return Math.round(Math.min(max, Math.max(min, Number(width) || COLUMNS[side].start)));
}

const readJson = (key, fallback) => {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "null") ?? fallback;
  } catch {
    return fallback;
  }
};
const store = (key, value) => {
  try { localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value)); } catch { /* private mode */ }
};

/** The ElevenLabs part with its defaults: nothing chosen yet is not an unsaved change. */
function normalize(data, household) {
  data.elevenlabs = { model: household?.elevenlabs_models?.[0] || "eleven_multilingual_v2", count: 5, voices: [], ...(data.elevenlabs || {}) };
  data.speakers ||= [];
  data.words ||= {};
  data.devices ||= {};
  data.targets ||= { adult: 12, child: 18, held_out: 3 };
  return data;
}

const dump = (value) => stringify(value, { lineWidth: 0 });

// The YAML of a part of the household shown on the side, and how an edit of it goes back into the draft.
const SIDE_YAML = {
  people: { get: (d) => ({ speakers: d.speakers }), set: (d, v) => { d.speakers = list(v.speakers); } },
  person: {
    get: (d, id) => d.speakers.find((s) => s.id === id),
    set: (d, v, id) => {
      if (!v || typeof v.id !== "string") throw new Error("id: …");
      const index = d.speakers.findIndex((s) => s.id === id);
      d.speakers[index] = v;
    },
  },
  words: { get: (d) => ({ words: d.words }), set: (d, v) => { d.words = map(v.words); } },
  word: {
    get: (d, id) => ({ [id]: d.words[id] }),
    set: (d, v, id) => {
      const keys = Object.keys(map(v));
      if (keys.length !== 1 || keys[0] !== id) throw new Error(`${id}: …`);
      d.words[id] = map(v[id]);
    },
  },
  devices: { get: (d) => ({ devices: d.devices }), set: (d, v) => { d.devices = map(v.devices); } },
  targets: {
    get: (d) => ({ ui_language: d.ui_language, targets: d.targets }),
    set: (d, v) => { d.ui_language = v.ui_language; d.targets = map(v.targets); },
  },
  piper: { get: (d) => ({ voices: d.voices || {} }), set: (d, v) => { d.voices = map(v.voices); } },
  elevenlabs: { get: (d) => ({ elevenlabs: d.elevenlabs }), set: (d, v) => { d.elevenlabs = map(v.elevenlabs); } },
};
function list(value) {
  if (!Array.isArray(value)) throw new Error("a list is needed");
  return value;
}
function map(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("a mapping (key: value) is needed");
  return value;
}

class WakewordStudio extends LitElement {
  static properties = {
    _state: { state: true },
    _household: { state: true },
    _selected: { state: true },
    _search: { state: true },
    _collapsed: { state: true },
    _widths: { state: true },
    _folded: { state: true },
    _theme: { state: true },
    _dialog: { state: true },
    _notice: { state: true },
    _saving: { state: true },
    _past: { state: true },
    _future: { state: true },
    _yamlAll: { state: true },
    _menu: { state: true },
    _gear: { state: true },
    _error: { state: true },
    // the tour ({ lesson: null }) or a lesson ({ lesson }) on the screen, null for none (gpu-studio standard, 5a)
    _tour: { state: true },
  };

  // light DOM: the views are plain DOM taken over from the training panel and share studio.css
  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this._state = null;
    this._household = null;
    this._draft = null;
    this._current = "";
    this._savedJson = "";
    this._past = [];
    this._future = [];
    this._search = "";
    this._viewVersion = 0;
    const widths = readJson(WIDTHS_KEY, {});
    this._widths = { left: columnWidth("left", widths.left), right: columnWidth("right", widths.right) };
    this._collapsed = new Set(readJson(COLLAPSED_KEY, []));
    // folded side columns (gpu-studio standard, section 5): remembered; a narrow window starts with the right one folded
    const folded = readJson(FOLDED_KEY, null);
    this._folded = folded ? { left: Boolean(folded.left), right: Boolean(folded.right) }
      : { left: false, right: window.innerWidth < 900 };
    let theme = null;
    try { theme = localStorage.getItem(THEME_KEY); } catch { theme = null; }
    this._theme = THEMES.includes(theme) ? theme : "auto";
    try { this._language = localStorage.getItem(LANG_KEY); } catch { this._language = null; }
    this._selected = decodeURIComponent(location.hash.replace(/^#\/?/, "")) || readJson(NODE_KEY, null) || "overview";
    this._jobsSeen = new Set();
    this._jobsKnown = false;
    this._onKey = this._onKey.bind(this);
    this._onOutside = this._onOutside.bind(this);
    this._onHash = this._onHash.bind(this);
    this._onUnload = this._onUnload.bind(this);
    this._applyTheme();
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("keydown", this._onKey);
    window.addEventListener("click", this._onOutside);
    window.addEventListener("hashchange", this._onHash);
    window.addEventListener("pagehide", this._onUnload);
    this._onVisible = this._onVisible.bind(this);
    document.addEventListener("visibilitychange", this._onVisible);
    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => this._applyTheme());
    common.setHooks({
      changed: ({ key, redraw }) => this._changed(key, redraw),
      redraw: () => this._redraw(),
      refresh: (options) => this._refresh(options),
      select: (key) => this._select(key),
      isDirty: () => this._dirty,
      lessonFor: () => lessonForNode(this._selected)?.key ?? null,
      startLesson: (key) => this._startLesson(key),
      jobStarted: () => {},
    });
    this._load();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("keydown", this._onKey);
    window.removeEventListener("click", this._onOutside);
    window.removeEventListener("hashchange", this._onHash);
    window.removeEventListener("pagehide", this._onUnload);
    document.removeEventListener("visibilitychange", this._onVisible);
    clearTimeout(this._poller);
    clearTimeout(this._countdownTimer);
    common.closeHelp();
  }

  _t(key, values) {
    return translate(this._state?.language, key, values, this._state?.ui);
  }

  // --- the look -------------------------------------------------------------------------------------

  _applyTheme() {
    const dark = this._theme === "dark" || (this._theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }

  _setTheme(theme) {
    this._theme = theme;
    store(THEME_KEY, theme);
    this._applyTheme();
  }

  _nextTheme() {
    this._setTheme(THEMES[(THEMES.indexOf(this._theme) + 1) % THEMES.length]);
  }

  async _setLanguage(language) {
    this._language = language;
    store(LANG_KEY, language);
    await this._refresh();
    this._redraw();
  }

  // --- loading, the state, the household -----------------------------------------------------------

  async _load() {
    try {
      const [state, household] = await Promise.all([this._callState(), common.call("household/get")]);
      this._setState(state);
      this._applyHousehold(household);
      this._error = null;
    } catch (err) {
      this._error = err.message;
    }
    this._schedulePoll();
  }

  /** The next state only after the answer to the previous one (gpu-studio standard, section 9a): a slow server
   * means slower polling, never a queue of requests; a tab in the background does not poll at all. */
  _schedulePoll(delay = POLL_MS) {
    clearTimeout(this._poller);
    this._poller = setTimeout(() => this._poll(), delay);
  }

  async _poll() {
    if (document.hidden) return; // _onVisible polls again when the tab comes back
    if (!this._polling) {
      this._polling = true;
      try {
        await this._refresh();
      } finally {
        this._polling = false;
      }
    }
    if (this.isConnected) this._schedulePoll();
  }

  _onVisible() {
    if (!document.hidden && this.isConnected) this._schedulePoll(0);
  }

  _callState() {
    return common.call("state", { language: this._language || null }, { timeout: STATE_TIMEOUT_MS });
  }

  _setState(state) {
    this._state = state;
    common.bind({ state });
    document.documentElement.lang = state.language;
    document.title = `${this._t("title")} · ${state.household.name}`;
  }

  async _refresh({ household = false } = {}) {
    try {
      this._setState(await this._callState());
      this._error = null;
    } catch (err) {
      this._error = err.message;
      return;
    }
    if (household) await this._reloadHousehold();
    this._afterState();
  }

  /** The household again (counts, devices); the draft stays unless nothing was changed in it. */
  async _reloadHousehold() {
    const household = await common.call("household/get");
    if (this._dirty) {
      normalize(household.data, household);
      this._household = household;
      this._hash = household.hash;
      this._savedJson = JSON.stringify(household.data);
      common.bind({ household });
    } else {
      this._applyHousehold(household);
    }
    this._redraw();
  }

  _applyHousehold(household) {
    normalize(household.data, household);
    this._household = household;
    this._hash = household.hash;
    this._savedJson = JSON.stringify(household.data);
    if (household.draft) {
      this._draft = normalize(household.draft.data, household);
      this._base = household.draft.base;
      this._draftOnServer = true;
      this._draftAt = household.draft.changed;
    } else {
      this._draft = JSON.parse(this._savedJson);
      this._base = household.hash;
      this._draftOnServer = false;
      this._draftAt = null;
    }
    this._current = JSON.stringify(this._draft);
    this._sideYamlText = null;
    this._allYamlText = null;
    common.bind({ household, draft: this._draft });
    this._redraw();
  }

  /** After every state: jobs that ended, models to list again. */
  _afterState() {
    const job = this._state.job;
    if (job && !job.running) {
      const key = `${job.name}:${job.started}`;
      if (!this._jobsSeen.has(key)) {
        this._jobsSeen.add(key);
        if (this._jobsKnown) {
          common.toast(`${job.name}: ${job.code === 0 ? this._t("job_ok") : this._t("job_failed", { code: job.code })}`,
            job.code === 0 ? "ok" : "error");
        }
        if (DISK_JOBS.has(job.name)) {
          forgetRecordings();
          this._reloadHousehold();
        }
        if (job.name === "evaluate_models" && job.code === 0) forgetModels();
        this._redraw();
      }
    }
    this._jobsKnown = true;
    if (watchModels()) this._redraw();
  }

  // --- the draft, undo and redo ----------------------------------------------------------------------

  get _dirty() {
    return this._current !== this._savedJson;
  }

  get _conflict() {
    return this._draftOnServer && this._base !== this._hash;
  }

  /** The draft changed in place (a view, the YAML); one undo step unless quick typing in the same place. */
  _changed(key = null, redraw = false, { keepSideText = false, keepAllText = false } = {}) {
    const json = JSON.stringify(this._draft);
    if (json !== this._current) {
      const now = Date.now();
      const merge = key && this._lastEdit?.key === key && now - this._lastEdit.at < COALESCE_MS;
      if (!merge) this._past = [...this._past, this._current].slice(-UNDO_LIMIT);
      this._lastEdit = key ? { key, at: now } : null;
      this._future = [];
      this._current = json;
      if (!keepSideText) this._sideYamlText = null;
      if (!keepAllText) this._allYamlText = null;
      this._scheduleDraft();
    }
    if (redraw) this._viewVersion += 1;
    this.requestUpdate();
  }

  _redraw() {
    this._viewVersion += 1;
    this.requestUpdate();
  }

  _scheduleDraft() {
    this._pending = true;
    this._draftFailed = false; // a new change: the next save may try again
    clearTimeout(this._draftTimer);
    this._draftTimer = setTimeout(() => this._saveDraft(), DRAFT_SAVE_MS);
  }

  /** The draft to the machine - one save at a time (gpu-studio standard, section 9a): a change made while a save is
   * on its way goes in one more save after its answer, so answers never come back out of order. After a failure it
   * tries again only with the next change (`force` = Save asks for it now), never in a loop. */
  async _saveDraft({ force = false } = {}) {
    clearTimeout(this._draftTimer);
    while (this._draftRun) await this._draftRun;
    if (!this._pending || (this._draftFailed && !force)) return;
    this._draftRun = this._sendDraft();
    try {
      await this._draftRun;
    } finally {
      this._draftRun = null;
    }
  }

  async _sendDraft() {
    this._pending = false;
    this._saving = true;
    try {
      if (!this._dirty) {
        // back to the file as it is: no draft is needed
        if (this._draftOnServer) await common.call("draft/discard");
        this._draftOnServer = false;
        this._base = this._hash;
        this._draftAt = null;
      } else {
        await common.call("draft/save", { data: this._draft, base: this._base });
        this._draftOnServer = true;
        this._draftAt = new Date().toISOString();
      }
      this._draftFailed = false;
    } catch (err) {
      this._pending = true;
      this._draftFailed = true;
      this._notice = { kind: "error", text: this._t("error", { message: err.message }) };
    } finally {
      this._saving = false;
      this.requestUpdate();
    }
  }

  // the page closes with a change not sent yet: send it on the way out
  _onUnload() {
    if (!this._pending) return;
    const body = this._dirty ? { type: "draft/save", data: this._draft, base: this._base } : { type: "draft/discard" };
    navigator.sendBeacon?.("/api/call", JSON.stringify(body));
  }

  _restoreJson(json) {
    this._draft = JSON.parse(json);
    this._current = json;
    this._lastEdit = null;
    this._sideYamlText = null;
    this._allYamlText = null;
    common.bind({ draft: this._draft });
    this._scheduleDraft();
    this._redraw();
  }

  _undo() {
    if (!this._past.length) return;
    this._future = [this._current, ...this._future];
    const previous = this._past.at(-1);
    this._past = this._past.slice(0, -1);
    this._restoreJson(previous);
  }

  _redo() {
    if (!this._future.length) return;
    this._past = [...this._past, this._current];
    const next = this._future[0];
    this._future = this._future.slice(1);
    this._restoreJson(next);
  }

  async _discard() {
    if (!(await common.ask(this._t("discard_confirm"), { ok: this._t("discard"), danger: true }))) return;
    clearTimeout(this._draftTimer);
    this._pending = false;
    try {
      await common.call("draft/discard");
    } catch (err) {
      this._notice = { kind: "error", text: this._t("error", { message: err.message }) };
    }
    this._past = [];
    this._future = [];
    this._applyHousehold(await common.call("household/get"));
  }

  /** A click outside ☰ and ⚙ (and their pop-ups) closes them. */
  _onOutside(event) {
    if (!this._menu && !this._gear) return;
    // a click in the tour (Next of a lesson that opened ⚙) does not close what the lesson shows
    if (event.composedPath().some((node) => node.classList?.contains("menu-wrap") || node.localName === "wakeword-studio-tour")) return;
    this._menu = false;
    this._gear = false;
  }

  _onKey(event) {
    if (event.key === "Escape" && (this._menu || this._gear)) {
      this._menu = false;
      this._gear = false;
      return;
    }
    const mod = event.ctrlKey || event.metaKey;
    if (!mod || this._dialog || document.querySelector("dialog.ask[open]")) return;
    const key = event.key.toLowerCase();
    if (event.code === "KeyB") { // Ctrl/⌘+B the left column, Ctrl/⌘+Alt+B the right one (Alt changes event.key on a Mac)
      event.preventDefault();
      this._foldColumn(event.altKey ? "right" : "left");
      return;
    }
    if (key === "s") {
      event.preventDefault();
      this._openSave();
      return;
    }
    // in a text field its own undo works; elsewhere the editor's
    const typing = ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement?.tagName);
    if (typing) return;
    if (key === "z" || key === "y") {
      event.preventDefault();
      if (key === "y" || event.shiftKey) this._redo();
      else this._undo();
    }
  }

  // --- the tree ---------------------------------------------------------------------------------------

  _outline() {
    return buildOutline({ draft: this._draft, state: this._state, household: this._household, t: (k, v) => this._t(k, v) });
  }

  _select(key) {
    this._selected = key;
    this._yamlAll = false;
    this._sideYamlText = null;
    store(NODE_KEY, key);
    if (decodeURIComponent(location.hash.slice(2)) !== key) history.replaceState(null, "", `#/${encodeURIComponent(key)}`);
    this._unfoldTo(key);
    this.querySelector(".middle")?.scrollTo?.(0, 0);
  }

  _onHash() {
    const key = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    if (key && key !== this._selected) this._select(key);
  }

  _unfoldTo(key) {
    const groups = this._outline();
    const next = new Set(this._collapsed);
    for (const group of groups) {
      for (const item of group.children) {
        const inside = flattenOutline(item.children || []).some((child) => child.key === key);
        if (item.key === key || inside) next.delete(group.key);
        if (inside) next.delete(item.key);
      }
    }
    if (next.size !== this._collapsed.size) {
      this._collapsed = next;
      store(COLLAPSED_KEY, [...next]);
    }
  }

  _toggle(key) {
    const next = new Set(this._collapsed);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this._collapsed = next;
    store(COLLAPSED_KEY, [...next]);
  }

  _foldAll(fold) {
    const keys = flattenOutline(this._outline().flatMap((group) => group.children)).filter((item) => item.children?.length)
      .map((item) => item.key);
    this._collapsed = new Set(fold ? keys : []);
    store(COLLAPSED_KEY, [...this._collapsed]);
  }

  /** Fold or unfold a side column; the width from before folding stays for unfolding. */
  _foldColumn(side, folded = !this._folded[side]) {
    this._folded = { ...this._folded, [side]: folded };
    store(FOLDED_KEY, this._folded);
  }

  _foldButton(side) {
    const folded = this._folded[side];
    const arrow = (side === "left") === folded ? "›" : "‹";
    const key = side === "left" ? "Ctrl/⌘+B" : "Ctrl/⌘+Alt+B";
    const label = this._t(folded ? `unfold_${side}` : `fold_${side}`);
    return html`<button class="ghost fold-column" data-fold-column=${side} aria-expanded=${String(!folded)}
      aria-label=${label} title=${`${label} (${key})`} @click=${() => this._foldColumn(side)}>${arrow}</button>`;
  }

  /** A folded column: a narrow strip with its unfold button - it never disappears without a trace. */
  _renderStrip(side) {
    return html`<div class="column-strip ${side}" data-column-strip=${side}>${this._foldButton(side)}</div>`;
  }

  _renderSplitter(side) {
    const move = (event) => {
      const box = this.getBoundingClientRect();
      const width = side === "left" ? event.clientX - box.left : box.right - event.clientX;
      this._widths = { ...this._widths, [side]: columnWidth(side, width) };
    };
    const start = (event) => {
      event.preventDefault();
      const bar = event.currentTarget;
      bar.setPointerCapture?.(event.pointerId);
      bar.classList.add("dragging");
      const stop = () => {
        bar.classList.remove("dragging");
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", stop);
        bar.removeEventListener("pointercancel", stop);
        store(WIDTHS_KEY, this._widths);
      };
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", stop);
      bar.addEventListener("pointercancel", stop);
    };
    const reset = () => {
      this._widths = { ...this._widths, [side]: COLUMNS[side].start };
      store(WIDTHS_KEY, this._widths);
    };
    if (this._folded[side]) return html`<div class="splitter off" data-splitter=${side}></div>`; // nothing to drag
    return html`<div class="splitter" role="separator" aria-orientation="vertical" title=${this._t("resize")}
      data-splitter=${side} @pointerdown=${start} @dblclick=${reset}></div>`;
  }

  // --- the views ---------------------------------------------------------------------------------------

  /** What a node shows: its view, how it follows the state, and the YAML it has on the side. */
  _spec(key = this._selected) {
    const [kind, id] = key.includes("/") ? [key.slice(0, key.indexOf("/")), key.slice(key.indexOf("/") + 1)] : [key, null];
    const stack = (...parts) => common.el("div", { class: "stack" }, ...parts);
    const live = { side: "live" };
    switch (kind) {
      case "overview": return { ...live, render: renderOverview };
      case "jobs": return { ...live, render: renderJobs, update: updateJobs };
      case "people": return { render: () => renderPeople(), yaml: "people" };
      case "person": return this._draft.speakers.some((s) => s.id === id)
        ? { render: () => stack(renderPeople(id), ...Object.keys(this._draft.words).filter((w) => this._personUses(id, w))
          .map((w) => renderRecordings(w, { background: false }))), yaml: "person", id } : null;
      case "words": return { render: () => renderWords(), yaml: "words" };
      case "word": return id in this._draft.words
        ? { render: () => stack(renderWords(id), renderRecordings(id, { background: false })), yaml: "word", id } : null;
      case "devices": return { render: renderDevices, yaml: "devices" };
      case "recordings": return { render: () => renderRecordings() };
      case "rec": return { render: () => renderRecordings(id, { background: false }) };
      case "background": return { render: renderBackground };
      case "piper": return { render: renderVoices, yaml: "piper" };
      case "elevenlabs": return { render: renderElevenLabs, yaml: "elevenlabs" };
      case "samples": return { ...live, render: () => stack(renderWordsToTrain(), common.card(this._t("n_samples"), "data", renderSamples())) };
      case "train-data": return { ...live, render: renderData };
      case "train-run": return { ...live, render: renderRun };
      case "train-live": return { side: "jobs", render: renderLive, update: updateLive };
      case "models": return { ...live, render: () => renderModels(id) };
      case "export": return { ...live, render: renderExport };
      case "false-wakes": return { ...live, render: renderFalseWakes };
      case "targets": return { render: renderTargets, yaml: "targets" };
      case "ha": return { ...live, render: renderHomeAssistant };
      case "power": return { ...live, render: renderPower };
      case "hf": return { ...live, render: renderHfToken };
      case "account": return { ...live, render: renderAccount };
      case "look": return { render: () => this._renderLook() };
      default: return null;
    }
  }

  _personUses(person, word) {
    const speakers = this._draft.words[word]?.speakers;
    return speakers === "all" || (speakers || []).includes(person);
  }

  /** What in the state a view shows: when it changes, the view is drawn again (not while typing in it). */
  _signature() {
    const s = this._state;
    return JSON.stringify([s.words, s.home_assistant, s.machine, s.training.running, s.training.hf_token, s.elevenlabs_key,
      s.elevenlabs_account, s.job && [s.job.name, s.job.running, s.job.code], s.studio?.power_off, s.training.progress.stage]);
  }

  _buildView(spec) {
    try {
      return spec.render();
    } catch (err) {
      console.error(err); // eslint-disable-line no-console
      return common.card(this._t("error", { message: err.message }), null, common.el("pre", { class: "terminal" }, err.stack || ""));
    }
  }

  _mountView() {
    const host = this.querySelector(".view-host");
    if (!host || !this._state || !this._draft) return;
    let spec = this._spec();
    if (!spec) {
      this._select("overview");
      spec = this._spec();
    }
    const key = `${this._selected}|${this._viewVersion}|${this._state.language}`;
    if (key !== this._mountedKey) {
      this._mountedKey = key;
      common.closeHelp(); // the help window belongs to the view that is going away
      this._signatureShown = this._signature();
      host.replaceChildren(this._buildView(spec));
      return;
    }
    if (spec.update) {
      spec.update(host.firstElementChild);
      return;
    }
    const signature = this._signature();
    const typing = host.contains(document.activeElement) && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if (signature !== this._signatureShown && !typing) {
      this._signatureShown = signature;
      host.replaceChildren(this._buildView(spec));
    }
  }

  updated() {
    const dialog = this.querySelector("dialog.frame-dialog");
    if (dialog && !dialog.open) dialog.showModal();
    this._mountView();
    const slot = this.querySelector("[data-side-live]");
    if (slot && this._state) slot.replaceChildren(liveCard());
    const job = this.querySelector("[data-side-job]");
    if (job) {
      // the log opens at its end and follows it while you stay there; scrolled up, it stays where you read
      const atBottom = job.scrollTop + job.clientHeight >= job.scrollHeight - 20;
      if (atBottom || !job.dataset.seen) job.scrollTop = job.scrollHeight;
      job.dataset.seen = "1";
    }
    // the tour starts by itself the first time the studio opens in this browser, never over an open window
    if (!this._tourChecked) {
      this._tourChecked = true;
      if (!tourSeen() && !this._dialog) this._startTour();
    }
  }

  // --- the tour and the lessons (gpu-studio standard, section 5a) -----------------------------------

  _startTour() {
    common.closeHelp();
    this._dialog = null;
    this._gear = false;
    this._menu = false;
    this._tour = { lesson: null };
  }

  _startLesson(key) {
    const lesson = findLesson(key);
    if (!lesson) return;
    common.closeHelp();
    this._dialog = null;
    this._gear = false;
    this._menu = false;
    this._tour = { lesson };
  }

  // what a lesson opened (the ⚙ pop-up) closes with it
  _closeTour() {
    if (this._tour?.lesson) this._gear = false;
    this._tour = null;
  }

  _renderTour() {
    if (!this._tour) return nothing;
    return html`<wakeword-studio-tour .root=${this} .host=${this} .lesson=${this._tour.lesson}
      .t=${(key, values) => this._t(key, values)} @tour-close=${() => this._closeTour()}></wakeword-studio-tour>`;
  }

  // --- saving and the history ---------------------------------------------------------------------

  async _openSave() {
    if (!this._dirty || !this._draft) return;
    await this._saveDraft({ force: true });
    this._saveState = { note: "", error: null, conflict: false, busy: false };
    this._dialog = "save";
  }

  async _save(force = false) {
    this._saveState = { ...this._saveState, busy: true, error: null };
    this.requestUpdate();
    try {
      await this._saveDraft({ force: true });
      const answer = await common.call("household/save", { data: this._draft, base: this._base, note: this._saveState.note, force });
      this._dialog = null;
      this._past = [];
      this._future = [];
      this._applyHousehold(await common.call("household/get"));
      this._notice = answer.warning ? { kind: "error", text: this._t("saved_not_sent", { error: answer.warning }) }
        : { kind: "ok", text: this._t("saved") };
      await this._refresh();
    } catch (err) {
      this._saveState = { ...this._saveState, busy: false, conflict: Boolean(err.body?.conflict), error: err.message };
      this.requestUpdate();
    }
  }

  async _openHistory() {
    this._historyState = { versions: null, pick: null, text: null };
    this._dialog = "history";
    try {
      this._historyState = { ...this._historyState, versions: (await common.call("history/list")).versions };
    } catch (err) {
      this._historyState = { ...this._historyState, versions: [], error: err.message };
    }
    this.requestUpdate();
  }

  async _pickVersion(id) {
    this._historyState = { ...this._historyState, pick: id, text: null };
    this.requestUpdate();
    const { text } = await common.call("history/get", { id });
    this._historyState = { ...this._historyState, text };
    this.requestUpdate();
  }

  async _restoreVersion(id) {
    if (this._dirty && !(await common.ask(this._t("history_restore_confirm"), { ok: this._t("history_restore") }))) return;
    clearTimeout(this._draftTimer);
    this._pending = false;
    const before = this._current;
    await common.call("history/restore", { id });
    this._dialog = null;
    this._applyHousehold(await common.call("household/get"));
    if (before !== this._current) {
      this._past = [...this._past, before];
      this._future = [];
    }
    this._notice = { kind: "ok", text: this._t("restored") };
  }

  // --- the YAML of the choice and of the whole file ---------------------------------------------------

  _sideYaml(spec) {
    const part = SIDE_YAML[spec?.yaml];
    return part ? dump(part.get(this._draft, spec.id)) : null;
  }

  _onSideYaml(spec, text) {
    this._sideYamlText = text;
    try {
      const value = parse(text);
      SIDE_YAML[spec.yaml].set(this._draft, value, spec.id);
      normalize(this._draft, this._household);
      this._sideYamlError = null;
      this._changed("side-yaml", true, { keepSideText: true });
    } catch (err) {
      this._sideYamlError = this._t("yaml_error", { error: err.message });
      this.requestUpdate();
    }
  }

  _onAllYaml(text) {
    this._allYamlText = text;
    try {
      const value = parse(text);
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(this._t("yaml_not_map"));
      this._draft = normalize(value, this._household);
      common.bind({ draft: this._draft });
      this._allYamlError = null;
      this._changed("all-yaml", false, { keepAllText: true });
    } catch (err) {
      this._allYamlError = this._t("yaml_error", { error: err.message });
      this.requestUpdate();
    }
  }

  // --- rendering --------------------------------------------------------------------------------------

  render() {
    if (!this._state || !this._draft) {
      return html`<p class="loading">${this._error ? this._t("error", { message: this._error }) : this._t("loading")}</p>`;
    }
    const spec = this._spec() || this._spec("overview");
    return html`
      ${this._renderTop()} ${this._renderNotices()}
      <div class="cols ${this._folded.left ? "left-folded" : ""} ${this._folded.right ? "right-folded" : ""}"
        style="--left: ${this._folded.left ? FOLDED_WIDTH : this._widths.left}px; --right: ${this._folded.right ? FOLDED_WIDTH : this._widths.right}px">
        ${this._folded.left ? this._renderStrip("left") : this._renderTree()} ${this._renderSplitter("left")}
        <main class="middle" data-middle>
          ${this._yamlAll ? this._renderAllYaml() : html`<div class="view view-host" data-view=${this._selected}></div>`}
        </main>
        ${this._renderSplitter("right")} ${this._folded.right ? this._renderStrip("right") : this._renderSide(spec)}
      </div>
      ${this._renderDialog()} ${this._renderTour()}
    `;
  }

  _renderTop() {
    const state = this._saving ? this._t("state_saving") : this._dirty ? this._t("state_draft") : this._t("state_clean");
    const training = this._state.training;
    const machine = this._state.machine;
    return html`<header class="top">
      <span class="menu-wrap">
      <button class="ghost menu" data-menu aria-label=${this._t("menu")} title=${this._t("menu")} aria-expanded=${this._menu ? "true" : "false"}
        @click=${() => { this._menu = !this._menu; this._gear = false; }}>
        <ha-icon icon="mdi:menu"></ha-icon>
      </button>
      ${this._menu ? html`<div class="menu-pop" data-menu-pop @click=${() => { this._menu = false; }}>
        <span class="who" data-who>${this._state.studio?.trusted ? this._t("trusted_login")
          : this._t("logged_in", { user: this._state.studio?.user || "?" })}</span>
        <a href=${common.docsUrl()} target="_blank" rel="noopener">
          <ha-icon icon="mdi:book-open-variant"></ha-icon>${this._t("docs")}</a>
        <button @click=${() => this._select("account")}><ha-icon icon="mdi:account-key-outline"></ha-icon>${this._t("n_account")}</button>
        ${this._state.studio?.trusted ? nothing : html`<button data-logout @click=${async () => {
          await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          location.assign("/login");
        }}><ha-icon icon="mdi:logout"></ha-icon>${this._t("logout")}</button>`}
      </div>` : nothing}
      </span>
      <h1>${this._t("title")}</h1>
      <span class="board" title=${this._state.household.path}>${this._state.household.name}</span>
      <span class="grow"></span>
      ${training.running || training.error ? html`<span class="pill ${training.error ? "bad" : "running"}" data-training-pill
        @click=${() => this._select("train-live")}>
        <ha-icon icon=${training.error ? "mdi:alert-circle-outline" : "mdi:chart-line"}></ha-icon>
        ${training.error ? this._t("connection_error") : this._t("running")}</span>` : nothing}
      ${machine ? html`<span class="pill ${machine.machine === "rejected" ? "bad" : ""}" data-machine title=${machine.error || ""}>
          <ha-icon icon="mdi:power"></ha-icon>${machineLabel()}</span>
        <button class="ghost danger" data-power-off title=${this._t("power_off")}
          ?disabled=${["off", "stopping", "unknown", "checking", "rejected"].includes(machine.machine)}
          @click=${(event) => switchMachineOff(event.currentTarget)}><ha-icon icon="mdi:power"></ha-icon></button>` : nothing}
      ${this._renderPowerCountdown()}
      <span class="pill ${this._dirty ? "draft" : ""}" data-draft-state=${this._dirty ? "draft" : "clean"}>
        <ha-icon icon=${this._dirty ? "mdi:pencil" : "mdi:check"}></ha-icon>${state}
      </span>
      <button class="ghost" data-undo title=${this._t("undo")} ?disabled=${!this._past.length} @click=${this._undo}>
        <ha-icon icon="mdi:undo"></ha-icon></button>
      <button class="ghost" data-redo title=${this._t("redo")} ?disabled=${!this._future.length} @click=${this._redo}>
        <ha-icon icon="mdi:redo"></ha-icon></button>
      ${this._dirty || this._draftOnServer ? html`<button class="ghost" data-discard @click=${this._discard}>${this._t("discard")}</button>` : nothing}
      <button class="ghost" data-theme-button=${this._theme} title=${this._t(`theme_${this._theme}`)} @click=${this._nextTheme}>
        <ha-icon icon=${THEME_ICONS[this._theme]}></ha-icon></button>
      <button class="ghost ${this._yamlAll ? "on" : ""}" data-yaml title=${this._t("yaml_hint")} @click=${() => { this._yamlAll = !this._yamlAll; }}>
        <ha-icon icon="mdi:code-braces"></ha-icon>${this._t("yaml")}</button>
      <a class="ghost button" data-docs href=${common.docsUrl()} target="_blank" rel="noopener" title=${this._t("docs_hint")}
        aria-label=${this._t("docs")}><ha-icon icon="mdi:help-circle-outline"></ha-icon></a>
      ${this._renderGear()}
      <button class="ghost" data-history @click=${this._openHistory}><ha-icon icon="mdi:history"></ha-icon>${this._t("history")}</button>
      <button class="primary" data-save ?disabled=${!this._dirty} @click=${this._openSave}>
        <ha-icon icon="mdi:content-save"></ha-icon>${this._t("save")}</button>
    </header>`;
  }

  _renderNotices() {
    return html`
      ${this._error ? html`<div class="notice error" data-error-notice><span>${this._t("error", { message: this._error })}</span></div>` : nothing}
      ${this._conflict ? html`<div class="notice error" data-conflict-notice><span>${this._t("conflict")}</span></div>` : nothing}
      ${this._notice ? html`<div class="notice ${this._notice.kind}" data-notice=${this._notice.kind}>
        <span>${this._notice.text}</span>
        <button class="ghost" aria-label=${this._t("close")} @click=${() => { this._notice = null; }}><ha-icon icon="mdi:close"></ha-icon></button>
      </div>` : nothing}
    `;
  }

  _renderTree() {
    const groups = filterOutline(this._outline(), this._search);
    const searching = Boolean(this._search.trim());
    const node = (item, depth) => {
      const open = searching || !this._collapsed.has(item.key);
      return html`
        <div class="node ${this._selected === item.key ? "sel" : ""} ${item.warn ? "warn" : ""} ${item.busy ? "busy" : ""}"
          style="padding-left: ${8 + depth * 16}px" data-node=${item.key} title=${item.warn ?? item.hint ?? ""}
          @click=${() => this._select(item.key)}>
          ${item.children.length
            ? html`<button class="fold" aria-label=${this._t("fold")} data-fold=${item.key}
                @click=${(event) => { event.stopPropagation(); this._toggle(item.key); }}>
                <ha-icon icon=${open ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon></button>`
            : html`<span class="fold"></span>`}
          <ha-icon class="icon" icon=${item.warn ? "mdi:alert-outline" : item.icon}></ha-icon>
          <span class="label">${item.label}</span>
          ${item.count !== undefined ? html`<span class="count">${item.count}</span>` : nothing}
        </div>
        ${open ? item.children.map((child) => node(child, depth + 1)) : nothing}
      `;
    };
    return html`<nav class="tree" data-tree>
      <div class="tree-head">
        <label class="search">
          <ha-icon icon="mdi:magnify"></ha-icon>
          <input data-search placeholder=${this._t("search")} .value=${this._search} @input=${(event) => { this._search = event.target.value; }} />
        </label>
        ${this._foldButton("left")}
      </div>
      <div class="tree-tools">
        <button class="ghost" data-fold-all @click=${() => this._foldAll(true)}><ha-icon icon="mdi:unfold-less-horizontal"></ha-icon>${this._t("fold_all")}</button>
        <button class="ghost" data-unfold-all @click=${() => this._foldAll(false)}><ha-icon icon="mdi:unfold-more-horizontal"></ha-icon>${this._t("unfold_all")}</button>
      </div>
      ${groups.map((group) => {
        const groupOpen = searching || !this._collapsed.has(group.key);
        return html`
          <div class="group" data-group=${group.key}>
            <button class="fold" aria-label=${this._t("fold")} aria-expanded=${groupOpen} data-group-fold=${group.key}
              @click=${() => this._toggle(group.key)}>
              <ha-icon icon=${groupOpen ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon></button>
            <span class="group-name" @click=${() => this._toggle(group.key)}>${group.label}</span>
            ${group.key === "g:family" ? html`<button class="ghost add" data-add-person-tree title=${this._t("add_person")}
              @click=${() => this._select("people")}><ha-icon icon="mdi:plus"></ha-icon></button>` : nothing}
          </div>
          ${groupOpen ? group.children.map((item) => node(item, 0)) : nothing}
        `;
      })}
    </nav>`;
  }

  _renderAllYaml() {
    const text = this._allYamlText ?? dump(this._draft);
    return html`<section class="card" data-yaml-all>
      <div class="card-head"><h2>household.yaml</h2><span class="hint">${this._t("yaml_hint")}</span></div>
      ${this._allYamlError ? html`<p class="field-error" data-yaml-error>${this._allYamlError}</p>` : nothing}
      <textarea class="code" spellcheck="false" .value=${text} @input=${(event) => this._onAllYaml(event.target.value)}></textarea>
    </section>`;
  }

  /** The countdown before the machine goes off, in the top bar (gpu-studio standard, section 5) - with Cancel. */
  _renderPowerCountdown() {
    const power = this._state.studio?.power_off || {};
    const error = this._state.studio?.power_off_error;
    if (power.at) {
      const left = Math.max(0, Math.round(power.at - Date.now() / 1000));
      clearTimeout(this._countdownTimer);
      this._countdownTimer = setTimeout(() => this.requestUpdate(), 1000);
      const time = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      return html`<span class="pill bad" data-power-countdown-top>
        <ha-icon icon="mdi:power"></ha-icon>${this._t("power_off_in", { time })}
        <button class="link-btn" data-power-cancel-top @click=${async () => { await common.call("power/cancel"); await this._refresh(); }}>
          ${this._t("side_power_off_cancel")}</button></span>`;
    }
    return error ? html`<span class="pill bad" data-power-error-top title=${error}>
      <ha-icon icon="mdi:alert-circle-outline"></ha-icon>${this._t("power_off_failed")}</span>` : nothing;
  }

  _renderSide(spec) {
    const yaml = this._sideYaml(spec);
    const power = this._state.studio?.power_off || {};
    const seconds = power.at ? Math.max(0, Math.round(power.at - Date.now() / 1000)) : null;
    const ha = this._state.home_assistant || {};
    const powerReady = Boolean(ha.power?.switch && ha.url);
    return html`<aside class="side" data-side>
      <div class="side-head">${this._foldButton("right")}</div>
      ${yaml !== null ? html`<section class="card" data-side-yaml>
          <h3>${this._t("side_yaml")}</h3>
          <p class="hint">${this._t("side_yaml_hint")}</p>
          ${this._sideYamlError && this._sideYamlText !== null ? html`<p class="field-error">${this._sideYamlError}</p>` : nothing}
          <textarea class="code" spellcheck="false" data-side-yaml-text .value=${this._sideYamlText ?? yaml}
            @input=${(event) => this._onSideYaml(spec, event.target.value)}></textarea>
        </section>
        <section class="card" data-draft-card>
          <h3>${this._t("side_draft")}</h3>
          ${this._household.exists ? nothing : html`<p class="hint">${this._t("side_file_missing")}</p>`}
          ${this._dirty && this._draftAt ? html`<p>${this._t("side_draft_at", { time: new Date(this._draftAt).toLocaleString(this._state.language) })}</p>` : nothing}
          ${this._conflict ? html`<p class="hint warn">${this._t("draft_outdated")}</p>` : nothing}
          <p class="hint">${this._t("side_draft_note")}</p>
        </section>`
        : html`${spec?.side === "jobs" ? nothing : html`<div data-side-live></div>`}
          ${powerReady ? html`<section class="card" data-power-card>
            <label class="check"><input type="checkbox" data-power-after .checked=${Boolean(power.after_training) || seconds !== null}
              @change=${async (event) => {
                await common.call("power/off_after_training", { enabled: event.target.checked });
                await this._refresh();
              }} /><span>${this._t("side_power_off")}</span></label>
            <p class="hint">${this._t("side_power_off_hint", { seconds: this._state.studio?.power_off_delay ?? 120 })}</p>
            ${seconds !== null ? html`<p class="hint warn" data-power-countdown>${this._t("side_power_off_countdown", { seconds })}
              <button class="btn small" @click=${async () => { await common.call("power/cancel"); await this._refresh(); }}>
              ${this._t("side_power_off_cancel")}</button></p>` : nothing}
            ${this._state.studio?.power_off_error ? html`<p class="hint warn">${this._t("side_power_off_error", { error: this._state.studio.power_off_error })}</p>` : nothing}
          </section>` : nothing}
          ${spec?.side === "jobs" || this._state.job ? html`<section class="card" data-side-job-card>
            <h3>${this._t("side_job")}${this._state.job ? ` · ${this._state.job.name}` : ""}</h3>
            <pre class="terminal" data-side-job>${(this._state.job?.lines || []).slice(-SIDE_JOB_LINES).join("\n") || "—"}</pre>
          </section>` : nothing}`}
    </aside>`;
  }

  _renderDialog() {
    if (this._dialog === "save") return this._renderSave();
    if (this._dialog === "history") return this._renderHistory();
    if (this._dialog === "lessons") {
      return this._dialogShell("lessons", this._t("lessons_title"), html`<wakeword-studio-lessons .host=${this}
        .t=${(key, values) => this._t(key, values)} @lesson-start=${(event) => this._startLesson(event.detail.key)}>
        </wakeword-studio-lessons>`);
    }
    return nothing;
  }

  _dialogShell(name, title, body, foot = nothing, narrow = false) {
    const close = () => { this._dialog = null; };
    return html`<dialog class="frame-dialog ${narrow ? "narrow" : ""}" data-dialog=${name}
      @close=${() => { if (this._dialog === name) close(); }}
      @click=${(event) => { if (event.target === event.currentTarget) close(); }}>
      <div class="dialog-head"><h2>${title}</h2>
        <button class="ghost" data-close aria-label=${this._t("close")} @click=${close}><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="dialog-body">${body}</div>
      ${foot === nothing ? nothing : html`<div class="dialog-foot">${foot}</div>`}
    </dialog>`;
  }

  _renderDiff(before, after) {
    return html`<div class="diff" data-diff>${diffHunks(diffLines(before, after)).map((line) => line.kind === "skip"
      ? html`<div class="skip">${this._t("save_lines_skipped", { count: line.count })}</div>`
      : html`<div class=${line.kind}>${line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}${line.text}</div>`)}</div>`;
  }

  _renderSave() {
    const saved = JSON.parse(this._savedJson);
    const changes = describeChanges(saved, this._draft);
    const s = this._saveState;
    const chips = (kind, keys) => keys.map((key) => html`<span class="change ${kind}">${key}</span>`);
    const body = html`
      <p class="hint">${this._t("save_intro")}</p>
      <div class="changes" data-changes>
        ${chips("added", changes.added)} ${chips("removed", changes.removed)} ${chips("changed", changes.changed)}
      </div>
      ${this._renderDiff(dump(saved), dump(this._draft))}
      <label class="field">${this._t("save_note")}
        <input data-save-note placeholder=${this._t("save_note_placeholder")} .value=${s.note}
          @input=${(event) => { s.note = event.target.value; }} /></label>
      ${s.conflict ? html`<p class="hint warn" data-save-conflict>${this._t("save_conflict")}</p>` : nothing}
      ${s.error && !s.conflict ? html`<p class="field-error" data-save-error>${s.error}</p>` : nothing}`;
    const foot = html`
      <button class="ghost" @click=${() => { this._dialog = null; }}>${this._t("cancel")}</button>
      ${s.conflict ? html`<button class="btn danger" data-save-force ?disabled=${s.busy} @click=${() => this._save(true)}>${this._t("save_force")}</button>` : nothing}
      <button class="primary ${s.busy ? "busy" : ""}" data-save-confirm ?disabled=${s.busy} @click=${() => this._save(false)}>
        <ha-icon icon="mdi:content-save"></ha-icon>${this._t("save_button")}</button>`;
    return this._dialogShell("save", this._t("save_title"), body, foot);
  }

  _renderHistory() {
    const h = this._historyState || {};
    const versions = h.versions;
    const body = html`
      <p class="hint">${this._t("history_intro")}</p>
      ${versions === null ? html`<p class="hint">${this._t("loading")}</p>` : !versions.length
        ? html`<p class="hint" data-history-empty>${this._t("history_empty")}</p>`
        : html`<div class="history">
          <div class="history-list">${versions.map((v) => html`<button class=${h.pick === v.id ? "on" : ""} data-version=${v.id}
            @click=${() => this._pickVersion(v.id)}>
            <span>${new Date(v.time).toLocaleString(this._state.language)}</span>
            <small>${[v.user ? this._t("history_by", { user: v.user }) : "", v.note].filter(Boolean).join(" · ")}</small>
          </button>`)}</div>
          <div>${h.pick ? (h.text === null ? html`<p class="hint">${this._t("loading")}</p>` : html`
              <p class="hint">${this._t("history_against")}</p>
              ${this._renderDiff(h.text, this._household.text || "")}
              <div class="actions"><button class="primary" data-restore=${h.pick} @click=${() => this._restoreVersion(h.pick)}>
                <ha-icon icon="mdi:backup-restore"></ha-icon>${this._t("history_restore")}</button></div>`)
            : html`<p class="hint">${this._t("history_pick")}</p>`}</div>
        </div>`}`;
    return this._dialogShell("history", this._t("history_title"), body);
  }

  /** ⚙: a pop-up under the button with the quick settings (look and language); the full view is in the tree. */
  _renderGear() {
    return html`<span class="menu-wrap gear-wrap">
      <button class="ghost ${this._gear ? "on" : ""}" data-settings title=${this._t("settings")} aria-label=${this._t("settings")}
        aria-expanded=${this._gear ? "true" : "false"} @click=${() => { this._gear = !this._gear; this._menu = false; }}>
        <ha-icon icon="mdi:cog-outline"></ha-icon></button>
      ${this._gear ? html`<div class="menu-pop gear-pop" data-gear-pop>
        <strong class="pop-title">${this._t("settings")}</strong>
        <span class="pop-label">${this._t("theme")}</span>
        <div class="seg" data-theme-seg>${THEMES.map((theme) => html`<button class=${theme === this._theme ? "on" : ""}
          data-theme-choice=${theme} aria-pressed=${theme === this._theme ? "true" : "false"}
          @click=${() => this._setTheme(theme)}>${this._t(`theme_choice_${theme}`)}</button>`)}</div>
        <span class="pop-label">${this._t("language")}</span>
        <div class="seg" data-language-seg>${LANGUAGES.map((code) => html`<button class=${code === this._state.language ? "on" : ""}
          data-language-choice=${code} aria-pressed=${code === this._state.language ? "true" : "false"}
          @click=${() => this._setLanguage(code)}>${LANGUAGE_NAMES[code] || code.toUpperCase()}</button>`)}</div>
        <button class="pop-link" data-gear-all @click=${() => { this._gear = false; this._select("look"); }}>
          <ha-icon icon="mdi:palette-outline"></ha-icon>${this._t("gear_all")}</button>
        <button class="pop-link" data-tour-start @click=${() => this._startTour()}>
          <ha-icon icon="mdi:arrow-right"></ha-icon>${this._t("gear_tour")}</button>
        <button class="pop-link" data-lessons-open @click=${() => { this._gear = false; this._dialog = "lessons"; }}>
          <ha-icon icon="mdi:book-open-variant"></ha-icon>${this._t("gear_lessons")}</button>
      </div>` : nothing}
    </span>`;
  }

  /** The tree's node „Look and language”: everything of the ⚙ pop-up, and who is logged in. */
  _renderLook() {
    const { el, card } = common;
    const language = el("select", { "data-language": "", onchange: (event) => this._setLanguage(event.target.value) },
      ...LANGUAGES.map((code) => el("option", { value: code, ...(code === this._state.language ? { selected: "" } : {}) },
        LANGUAGE_NAMES[code] || code.toUpperCase())));
    const theme = el("select", { "data-theme-select": "", onchange: (event) => this._setTheme(event.target.value) },
      ...THEMES.map((value) => el("option", { value, ...(value === this._theme ? { selected: "" } : {}) },
        this._t(`theme_choice_${value}`))));
    return card(this._t("n_look"), null,
      el("p", { class: "hint" }, this._t("look_intro")),
      el("label", { class: "field" }, this._t("language"), language),
      el("label", { class: "field" }, this._t("theme"), theme),
      el("p", { class: "hint" }, `${this._t("logged_in", { user: this._state.studio?.user || "?" })} · ${this._state.studio?.version || ""}`));
  }


}

if (!customElements.get(APP_TAG)) customElements.define(APP_TAG, WakewordStudio);

// the tree's helpers for the tests of the page
export { buildOutline, findNode };

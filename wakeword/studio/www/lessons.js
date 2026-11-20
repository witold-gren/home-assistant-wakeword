// The lessons of the studio: every task of the step-by-step chapter of the documentation (13), each a short tour
// (tour.js) that goes where the task is done and frames one part at a time. A step can choose a node of the tree or
// open the ⚙ pop-up first (`prepare`) and wait for the framed button to be clicked (`advance: "click"`) - only for
// what the draft can undo (adding a person, a word). Buttons that start work on the machine (download, prepare, train,
// export, switch off) are framed and explained, never waited for: the person decides to press them (`note: "heavy"`).
// The list (⚙ → Lessons) marks the ones gone through; a lesson that needs something the studio has not got says what.

import { LitElement, html, nothing } from "./vendor/lit-all.min.js";
import { lessonsDone } from "./tour.js";

const choose = (key) => (app) => app?._select?.(key);
const view = (key) => [`[data-view='${key}']`];
const firstWord = (app) => Object.keys(app?._draft?.words ?? {})[0];
const openGear = (app) => {
  if (app) app._gear = true;
};
const closeGear = (app) => {
  if (app) app._gear = false;
};

// steps several lessons share (texts lesson_<shared>_title/_text once)
const SAVE = { key: "save", targets: ["[data-save]"], side: "below-end", shared: "save" };

/** What a lesson needs in the studio, and whether it has it. */
export const NEEDS = {
  words: (app) => Object.keys(app?._draft?.words ?? {}).length > 0,
  trained: (app) => (app?._state?.words ?? []).some((word) => word.trained),
  prepared: (app) => (app?._state?.words ?? []).some((word) => word.prepared),
};

// group: start (the first word from nothing), next (more words, more training), once (set up once)
export const LESSONS = [
  {
    key: "connect_ha", group: "start", icon: "mdi:home-assistant", nodes: ["ha"],
    steps: [
      { key: "node", targets: ["[data-node='ha']"], side: "right", prepare: choose("ha") },
      { key: "url", targets: ["[data-ha-url]"], side: "left", fallback: view("ha") },
      { key: "token", targets: ["[data-ha-token]"], side: "left", fallback: view("ha") },
      { key: "save", targets: ["[data-ha-save]"], side: "left", fallback: view("ha") },
    ],
  },
  {
    key: "add_person", group: "start", icon: "mdi:account-group", nodes: ["people", "person"],
    steps: [
      { key: "name", targets: ["[data-new-person]"], side: "left", prepare: choose("people"), fallback: view("people") },
      { key: "add", targets: ["[data-add-person]"], side: "left", advance: "click", fallback: view("people") },
      { key: "tree", targets: ["[data-node='people']"], side: "right" },
      SAVE,
    ],
  },
  {
    key: "add_word", group: "start", icon: "mdi:text-recognition", nodes: ["words", "word"],
    steps: [
      { key: "name", targets: ["[data-new-word]"], side: "left", prepare: choose("words"), fallback: view("words") },
      { key: "add", targets: ["[data-add-word]"], side: "left", advance: "click", fallback: view("words") },
      { key: "spellings", targets: ["[data-spelling]"], side: "left", fallback: view("words") },
      { key: "alikes", targets: ["[data-sound-alikes]"], side: "left", fallback: view("words") },
      { key: "who", targets: ["[data-everyone]"], side: "left", fallback: view("words") },
      SAVE,
    ],
  },
  {
    key: "devices", group: "start", icon: "mdi:speaker-wireless", nodes: ["devices"],
    steps: [
      { key: "list", targets: ["[data-device]"], side: "left", prepare: choose("devices"), fallback: view("devices") },
      { key: "add", targets: [".device-add"], side: "left", fallback: view("devices") },
      SAVE,
    ],
  },
  {
    key: "targets", group: "start", icon: "mdi:target", nodes: ["targets"],
    steps: [
      { key: "fields", targets: ["[data-target]"], side: "left", prepare: choose("targets"), fallback: view("targets") },
      SAVE,
    ],
  },
  {
    key: "record", group: "start", icon: "mdi:waveform", nodes: ["recordings", "rec"], needs: "words",
    steps: [
      { key: "satellite", targets: [] },
      { key: "pull", targets: ["#ha-pull"], side: "left", prepare: choose("train-data"), fallback: view("train-data"), note: "heavy" },
      { key: "listen", targets: ["[data-play]"], side: "left", prepare: choose("recordings"), fallback: [".rec-groups"] },
      { key: "remove", targets: ["[data-delete-picked]"], side: "left", fallback: view("recordings") },
    ],
  },
  {
    key: "prepare", group: "start", icon: "mdi:database-cog-outline", nodes: ["train-data"], needs: "words",
    steps: [
      { key: "words", targets: ["[data-train-word]"], side: "left", prepare: choose("train-data"), fallback: view("train-data") },
      { key: "force", targets: ["#force"], side: "left", fallback: view("train-data") },
      { key: "start", targets: ["#prepare"], side: "left", fallback: view("train-data"), note: "heavy" },
      { key: "job", targets: ["[data-side]"], side: "left" },
    ],
  },
  {
    key: "train", group: "start", icon: "mdi:tune-variant", nodes: ["train-run"], needs: "prepared",
    steps: [
      { key: "words", targets: ["[data-train-word]"], side: "left", prepare: choose("train-run"), fallback: view("train-run") },
      { key: "steps", targets: ["#steps"], side: "left", fallback: view("train-run") },
      { key: "presets", targets: ["#weight-presets"], side: "left", fallback: view("train-run") },
      { key: "sets", targets: ["#set-weights"], side: "left", fallback: view("train-run") },
      { key: "negative", targets: ["#negative-weight"], side: "left", fallback: view("train-run") },
      { key: "rates", targets: ["#learning-rates"], side: "left", fallback: view("train-run") },
      { key: "convert", targets: ["#convert-only"], side: "left", fallback: view("train-run") },
      { key: "start", targets: ["#start"], side: "left", fallback: view("train-run"), note: "heavy" },
      { key: "stop", targets: ["#stop"], side: "left", fallback: view("train-run"), note: "heavy" },
    ],
  },
  {
    key: "home_model", group: "start", icon: "mdi:home-assistant", nodes: [], needs: "prepared",
    steps: [
      { key: "why", targets: [] },
      { key: "preset", targets: ["[data-preset='family']"], side: "left", prepare: choose("train-run"), fallback: view("train-run") },
      { key: "sets", targets: ["[data-set='background']", "[data-set='false_wakes']", "[data-set='real']"], side: "left",
        fallback: ["#set-weights"] },
      { key: "negative", targets: ["#negative-weight"], side: "left", fallback: view("train-run") },
      { key: "rank", targets: ["[data-rank='household']"], side: "below", prepare: choose("models"), fallback: view("models") },
      { key: "household", targets: ["[data-household-test]"], side: "left", fallback: view("models"), note: "heavy" },
      { key: "cutoff", targets: ["#cutoff"], side: "left", prepare: choose("export"), fallback: view("export") },
      { key: "watch", targets: ["[data-node='false-wakes']"], side: "right" },
    ],
  },
  {
    key: "live", group: "start", icon: "mdi:chart-line", nodes: ["train-live"],
    steps: [
      { key: "progress", targets: ["#progress"], side: "inside", prepare: choose("train-live"), fallback: view("train-live") },
      { key: "log", targets: ["[data-side]"], side: "left" },
      { key: "advice", targets: ["[data-apply-advice]"], side: "left", fallback: view("train-live") },
    ],
  },
  {
    key: "evaluate", group: "start", icon: "mdi:brain", nodes: ["models"], needs: "trained",
    steps: [
      { key: "load", targets: ["#load-models"], side: "left", prepare: choose("models"), fallback: view("models") },
      { key: "models", targets: ["[data-view='models'] table", "[data-models-word]"], side: "inside", fallback: view("models") },
      { key: "chart", targets: ["[data-view-model]"], side: "left", fallback: view("models") },
      { key: "rank", targets: ["[data-rank]"], side: "below", fallback: view("models") },
      { key: "household", targets: ["[data-household-test]"], side: "left", fallback: view("models"), note: "heavy" },
      { key: "evaluate", targets: ["[data-evaluate]"], side: "left", prepare: choose("export"), fallback: view("export"), note: "heavy" },
    ],
  },
  {
    key: "export", group: "start", icon: "mdi:export-variant", nodes: ["export"], needs: "trained",
    steps: [
      { key: "cutoff", targets: ["#cutoff"], side: "left", prepare: choose("export"), fallback: view("export") },
      { key: "send", targets: ["#export"], side: "left", fallback: view("export"), note: "heavy" },
      { key: "voice_pe", targets: [] },
    ],
  },
  {
    key: "another_word", group: "next", icon: "mdi:microphone-message", nodes: [],
    steps: [
      { key: "add", targets: ["[data-add-word]"], side: "left", prepare: choose("words"), fallback: view("words") },
      { key: "record", targets: ["#ha-pull"], side: "left", prepare: choose("train-data"), fallback: view("train-data") },
      { key: "only", targets: ["[data-train-word]"], side: "left", fallback: view("train-data") },
      { key: "start", targets: ["#start"], side: "left", prepare: choose("train-run"), fallback: view("train-run"), note: "heavy" },
    ],
  },
  {
    key: "train_again", group: "next", icon: "mdi:cube-outline", nodes: [], needs: "trained",
    steps: [
      { key: "base", targets: ["[data-choose-model]"], side: "left", prepare: choose("models"), fallback: view("models") },
      { key: "scratch", targets: ["[data-from-scratch]"], side: "left", fallback: view("models") },
      { key: "start", targets: ["#start"], side: "left", prepare: choose("train-run"), fallback: view("train-run"), note: "heavy" },
    ],
  },
  {
    key: "recordings", group: "next", icon: "mdi:folder-music-outline", nodes: [], needs: "words",
    steps: [
      { key: "word", targets: (app) => [`[data-node='rec/${firstWord(app)}']`], side: "right",
        prepare: (app) => app?._select?.(`rec/${firstWord(app)}`), fallback: ["[data-node='recordings']"] },
      { key: "listen", targets: ["[data-play]"], side: "left", fallback: ["[data-middle]"] },
      { key: "pick", targets: ["[data-pick]"], side: "left", fallback: ["[data-middle]"] },
      { key: "delete", targets: ["[data-delete-picked]"], side: "left", fallback: ["[data-middle]"] },
    ],
  },
  {
    key: "false_wakes", group: "next", icon: "mdi:bell-alert-outline", nodes: ["false-wakes"],
    steps: [
      { key: "node", targets: ["[data-node='false-wakes']"], side: "right", prepare: choose("false-wakes") },
      { key: "period", targets: ["[data-fw-since]"], side: "left", fallback: view("false-wakes") },
      { key: "summary", targets: ["[data-fw-summary]"], side: "left", fallback: view("false-wakes") },
      { key: "words", targets: ["[data-fw-words]"], side: "left", fallback: view("false-wakes") },
      { key: "deployed", targets: ["[data-fw-deployed]"], side: "left", fallback: ["[data-fw-words]", ...view("false-wakes")] },
      { key: "days", targets: ["[data-fw-days]"], side: "left", fallback: view("false-wakes") },
      { key: "devices", targets: ["[data-fw-devices]"], side: "left", fallback: view("false-wakes") },
      { key: "recent", targets: ["[data-fw-recent]"], side: "left", fallback: view("false-wakes") },
      { key: "advice", targets: ["[data-fw-advice]"], side: "left", fallback: view("false-wakes") },
    ],
  },
  {
    key: "edit_family", group: "next", icon: "mdi:pencil", nodes: [], needs: "words",
    steps: [
      { key: "group", targets: ["[data-group]"], side: "left", prepare: choose("people"), fallback: view("people") },
      { key: "order", targets: [".drag-handle"], side: "left", fallback: view("people") },
      { key: "rename", targets: ["[data-rename]"], side: "left", prepare: choose("words"), fallback: view("words") },
      { key: "remove", targets: ["[data-remove-word]"], side: "left", fallback: view("words") },
      SAVE,
    ],
  },
  {
    key: "samples", group: "next", icon: "mdi:playlist-play", nodes: ["samples"], needs: "prepared",
    steps: [
      { key: "words", targets: ["[data-train-word]"], side: "left", prepare: choose("samples"), fallback: view("samples") },
      { key: "list", targets: ["#samples"], side: "left", fallback: view("samples") },
    ],
  },
  {
    key: "background", group: "next", icon: "mdi:home-sound-in-outline", nodes: ["background"],
    steps: [
      { key: "view", targets: view("background"), side: "inside", prepare: choose("background") },
    ],
  },
  {
    key: "drafts", group: "next", icon: "mdi:history", nodes: [],
    steps: [
      { key: "state", targets: ["[data-draft-state]"], side: "below", prepare: choose("overview") },
      { key: "undo", targets: ["[data-undo]", "[data-redo]"], side: "below" },
      { key: "side_yaml", targets: ["[data-side-yaml]"], side: "left", prepare: (app) => app?._select?.(`word/${firstWord(app)}`),
        fallback: ["[data-side]"] },
      { key: "yaml", targets: ["[data-yaml]"], side: "below" },
      { key: "discard", targets: ["[data-discard]"], side: "below", fallback: ["[data-draft-state]"] },
      SAVE,
      { key: "history", targets: ["[data-history]"], side: "below-end" },
    ],
  },
  {
    key: "jobs", group: "next", icon: "mdi:console", nodes: ["jobs", "overview"],
    steps: [
      { key: "overview", targets: view("overview"), side: "inside", prepare: choose("overview") },
      { key: "jobs", targets: view("jobs"), side: "inside", prepare: choose("jobs") },
      { key: "copy", targets: ["[data-copy-job]"], side: "left", fallback: view("jobs") },
    ],
  },
  {
    key: "power", group: "once", icon: "mdi:power", nodes: ["power"],
    steps: [
      { key: "view", targets: view("power"), side: "inside", prepare: choose("power") },
      { key: "watts", targets: ["[data-off-watts]"], side: "left", fallback: view("power") },
      { key: "save", targets: ["[data-power-save]"], side: "left", fallback: view("power") },
      { key: "after", targets: ["[data-power-after]"], side: "left", prepare: choose("train-data"), fallback: ["[data-side]"] },
      { key: "top", targets: ["[data-power-off]", "[data-machine]"], side: "below", fallback: ["header.top"] },
    ],
  },
  {
    key: "piper", group: "once", icon: "mdi:account-voice", nodes: ["piper"],
    steps: [
      { key: "voices", targets: ["[data-voice]"], side: "left", prepare: choose("piper"), fallback: view("piper") },
      { key: "repo", targets: ["[data-hf-repo]"], side: "left", fallback: view("piper") },
      { key: "load", targets: ["[data-hf-load]"], side: "left", fallback: view("piper") },
    ],
  },
  {
    key: "elevenlabs", group: "once", icon: "mdi:playlist-play", nodes: ["elevenlabs"],
    steps: [
      { key: "key", targets: ["[data-el-key]"], side: "left", prepare: choose("elevenlabs"), fallback: view("elevenlabs") },
      { key: "sync", targets: ["[data-el-sync]"], side: "left", fallback: view("elevenlabs") },
      { key: "voices", targets: ["[data-el-voice]"], side: "left", fallback: view("elevenlabs") },
      { key: "generate", targets: ["[data-el-generate]"], side: "left", fallback: view("elevenlabs"), note: "heavy" },
    ],
  },
  {
    key: "machine", group: "once", icon: "mdi:key-outline", nodes: ["hf", "account"],
    steps: [
      { key: "token", targets: ["[data-hf-token]"], side: "left", prepare: choose("hf"), fallback: view("hf") },
      { key: "check", targets: ["[data-check]"], side: "left", fallback: view("hf") },
      { key: "account", targets: view("account"), side: "inside", prepare: choose("account") },
    ],
  },
  {
    key: "look", group: "once", icon: "mdi:palette-outline", nodes: ["look"],
    steps: [
      { key: "gear", targets: ["[data-settings]"], side: "below-end", prepare: closeGear, advance: "click" },
      { key: "theme", targets: ["[data-theme-seg]"], side: "left", prepare: openGear, fallback: ["[data-settings]"] },
      { key: "language", targets: ["[data-language-seg]"], side: "left", prepare: openGear, fallback: ["[data-settings]"] },
      { key: "tour", targets: ["[data-tour-start]", "[data-lessons-open]"], side: "left", prepare: openGear,
        fallback: ["[data-settings]"] },
    ],
  },
];

export const LESSON_GROUPS = ["start", "next", "once"];

/** The lesson of a node of the tree („?” of a view offers it), or null. */
export function lessonForNode(key) {
  const kind = key?.includes("/") ? key.slice(0, key.indexOf("/")) : key;
  return LESSONS.find((lesson) => lesson.nodes.includes(kind)) ?? null;
}

/** The lesson with this key, or null. */
export function findLesson(key) {
  return LESSONS.find((lesson) => lesson.key === key) ?? null;
}

/** Whether the studio has what the lesson needs (a lesson on models needs a trained word). */
export function lessonReady(lesson, app) {
  return !lesson.needs || NEEDS[lesson.needs](app);
}

/** The list of the lessons in groups, each marked done or what it needs; a click starts it. */
export class WakewordStudioLessons extends LitElement {
  static properties = {
    host: { attribute: false },
    t: { attribute: false },
  };

  // light DOM: the list sits in a window of the studio and takes its styles
  createRenderRoot() {
    return this;
  }

  _start(lesson) {
    this.dispatchEvent(new CustomEvent("lesson-start", { bubbles: true, composed: true, detail: { key: lesson.key } }));
  }

  render() {
    const t = this.t ?? ((key) => key);
    const done = new Set(lessonsDone());
    return html`<p class="hint">${t("lessons_intro")}</p>
      ${LESSON_GROUPS.map((group) => html`<h3 class="lessons-group">${t(`lessons_group_${group}`)}</h3>
        <div class="lessons-list">${LESSONS.filter((lesson) => lesson.group === group).map((lesson) => {
          const ready = lessonReady(lesson, this.host);
          return html`<button class="lesson ${done.has(lesson.key) ? "done" : ""}" data-lesson=${lesson.key}
            ?disabled=${!ready} @click=${() => this._start(lesson)}>
            <ha-icon icon=${lesson.icon}></ha-icon>
            <span class="lesson-text"><strong>${t(`lesson_${lesson.key}_name`)}</strong>
              <span class="hint">${ready ? t(`lesson_${lesson.key}_about`) : t(`lessons_needs_${lesson.needs}`)}</span></span>
            ${done.has(lesson.key) ? html`<ha-icon class="lesson-done" icon="mdi:check" data-lesson-done></ha-icon>` : nothing}
          </button>`;
        })}</div>`)}`;
  }
}

if (!customElements.get("wakeword-studio-lessons")) customElements.define("wakeword-studio-lessons", WakewordStudioLessons);

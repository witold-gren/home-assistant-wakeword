// The tour of the studio: one part of the screen at a time framed, the rest dimmed, and a bubble that says what it is
// and where its settings are. It starts by itself the first time the studio opens in a browser, and from ⚙ whenever
// asked. A step whose part is not on the screen (a folded column, no training running) is left out.
// The lessons (lessons.js) are tours of one task each: their steps first go where the task is (a node of the tree, the
// ⚙ pop-up opened) and may wait for the framed button to be clicked, so the task is done while learnt.
// Taken over from the Home Dashboard editor (gpu-studio standard, section 5a), with the studio's colours.

import { LitElement, css, html, nothing } from "./vendor/lit-all.min.js";

export const TOUR_KEY = "wakeword-studio-tour";
export const LESSONS_KEY = "wakeword-studio-lessons";
const BUBBLE_WIDTH = 360;
const GAP = 16;
const PAD = 8;
const CLICK_SETTLE_MS = 400;

// Each step: its key (the texts are tour_<key>_title, _text and, with `where`, _where), the parts it frames (one
// frame round all of them) and the side of the bubble.
export const TOUR_STEPS = [
  { key: "welcome", targets: [] },
  { key: "tree", targets: ["[data-tree]"], side: "right", where: true },
  { key: "middle", targets: ["[data-middle]"], side: "inside" },
  { key: "side", targets: ["[data-side]"], side: "left", where: true },
  { key: "draft", targets: ["[data-draft-state]", "[data-undo]", "[data-redo]", "[data-history]"], side: "below", where: true },
  { key: "save", targets: ["[data-save]"], side: "below-end" },
  { key: "machine", targets: ["[data-machine]", "[data-power-off]", "[data-training-pill]"], side: "below", where: true },
  { key: "help", targets: ["[data-docs]", "[data-settings]"], side: "below-end", where: true },
  { key: "menu", targets: ["[data-menu]"], side: "below" },
];

function readStored(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return undefined; // no storage of the browser (private browsing)
  }
}

function writeStored(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private browsing: nothing kept */
  }
}

/** The keys of the lessons gone through in this browser. */
export function lessonsDone() {
  try {
    return JSON.parse(readStored(LESSONS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function markLessonDone(key) {
  const done = lessonsDone();
  if (!done.includes(key)) writeStored(LESSONS_KEY, JSON.stringify([...done, key]));
}

/**
 * Whether the tour has been seen (or skipped) in this browser. Without the storage of the browser it could not
 * remember being skipped and would come back every time, so it counts as seen; ⚙ still opens it.
 */
export function tourSeen() {
  const value = readStored(TOUR_KEY);
  return value === undefined || value === "done";
}

// The first element for a selector in a root or any shadow root under it.
function deepFind(root, selector) {
  const found = root.querySelector?.(selector);
  if (found) return found;
  for (const element of root.querySelectorAll?.("*") ?? []) {
    if (!element.shadowRoot) continue;
    const inner = deepFind(element.shadowRoot, selector);
    if (inner) return inner;
  }
  return null;
}

/**
 * The element a target names: a selector, or selectors joined by ">>>" for one inside another (each looked for in the
 * last one found and the shadow roots under it).
 */
export function findTarget(root, target) {
  let scope = root;
  for (const selector of target.split(">>>").map((part) => part.trim())) {
    if (!scope) return null;
    scope = deepFind(scope.shadowRoot ?? scope, selector) ?? (scope.shadowRoot ? deepFind(scope, selector) : null);
  }
  return scope && scope !== root ? scope : null;
}

// A part counts as on the screen when it is drawn (a folded column or a hidden pill has no size).
function shown(root, target) {
  const box = findTarget(root, target)?.getBoundingClientRect();
  return Boolean(box && box.width && box.height);
}

/** The steps there is something on the screen for. */
export function shownSteps(root, steps = TOUR_STEPS) {
  return steps.filter((step) => !step.targets.length || step.targets.some((target) => shown(root, target)));
}

/** One rectangle round the parts of a step that are on the screen, a little larger; null for none. */
export function frameOf(root, targets, width = window.innerWidth, height = window.innerHeight) {
  const boxes = targets
    .map((target) => (root ? findTarget(root, target) : null)?.getBoundingClientRect())
    .filter((box) => box && box.width && box.height);
  if (!boxes.length) return null;
  const left = Math.max(4, Math.min(...boxes.map((box) => box.left)) - PAD);
  const top = Math.max(4, Math.min(...boxes.map((box) => box.top)) - PAD);
  const right = Math.min(width - 4, Math.max(...boxes.map((box) => box.right)) + PAD);
  const bottom = Math.min(height - 4, Math.max(...boxes.map((box) => box.bottom)) + PAD);
  return { left, top, width: right - left, height: bottom - top };
}

/**
 * Where the bubble stands: on the chosen side of the frame, kept inside the window. When that side has no room and the
 * bubble would cover the framed part, the other sides are tried (a button low in the window gets it above).
 */
export function bubbleAt(frame, side, size, width = window.innerWidth, height = window.innerHeight) {
  const bubble = { width: Math.min(BUBBLE_WIDTH, width - 2 * GAP), height: size?.height ?? 220 };
  const clampX = (x) => Math.max(GAP, Math.min(width - bubble.width - GAP, x));
  const clampY = (y) => Math.max(GAP, Math.min(height - bubble.height - GAP, y));
  if (!frame) return { left: clampX((width - bubble.width) / 2), top: clampY(height * 0.28), width: bubble.width };
  const below = frame.top + frame.height + GAP;
  const places = {
    right: { left: frame.left + frame.width + GAP, top: frame.top + 40 },
    left: { left: frame.left - bubble.width - GAP, top: frame.top + 40 },
    below: { left: frame.left, top: below },
    "below-end": { left: frame.left + frame.width - bubble.width, top: below },
    above: { left: frame.left, top: frame.top - bubble.height - GAP },
    inside: { left: frame.left + 24, top: frame.top + frame.height - bubble.height - 24 },
  };
  const at = (name) => ({ left: clampX(places[name].left), top: clampY(places[name].top), width: bubble.width });
  const covers = (box) => box.left < frame.left + frame.width && box.left + bubble.width > frame.left
    && box.top < frame.top + frame.height && box.top + bubble.height > frame.top;
  const chosen = at(places[side] ? side : "below");
  if (side === "inside" || !covers(chosen)) return chosen;
  return ["right", "left", "below", "above"].map(at).find((box) => !covers(box)) ?? chosen;
}

export class WakewordStudioTour extends LitElement {
  static properties = {
    root: { attribute: false },
    t: { attribute: false },
    // A lesson instead of the tour: { key, steps } and the studio its steps prepare (select a node, open ⚙).
    lesson: { attribute: false },
    host: { attribute: false },
    _index: { state: true },
    _steps: { state: true },
  };

  constructor() {
    super();
    this._index = 0;
    this._onResize = () => this.requestUpdate();
    // A click on the framed part of a step that waits for it moves on, once what it opens is there.
    this._onClick = (event) => {
      const step = this._steps?.[this._index];
      if (step?.advance !== "click" || !this._frame) return;
      const { left, top, width, height } = this._frame;
      if (event.clientX < left || event.clientX > left + width || event.clientY < top || event.clientY > top + height) return;
      const at = this._index;
      setTimeout(() => this._index === at && this._go(1), CLICK_SETTLE_MS);
    };
    // in the capture phase: Esc ends the tour, not the pop-up or the window of the studio under it
    this._onKey = (event) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(event.composedPath?.()[0]?.tagName);
      if (event.key === "Escape") this._finish();
      else if (typing) return; // a lesson can ask to type a name: Enter and the arrows stay the field's
      else if (event.key === "ArrowRight" || event.key === "Enter") this._go(1);
      else if (event.key === "ArrowLeft") this._go(-1);
      else return;
      event.preventDefault();
      event.stopPropagation();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("resize", this._onResize);
    window.addEventListener("keydown", this._onKey, true);
    window.addEventListener("click", this._onClick, true);
    // What a step frames can move or appear (a pop-up opening, a view drawn): the frame follows it.
    this._follow = setInterval(() => this.requestUpdate(), 400);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("resize", this._onResize);
    window.removeEventListener("keydown", this._onKey, true);
    window.removeEventListener("click", this._onClick, true);
    clearInterval(this._follow);
  }

  get _prefix() {
    return this.lesson ? `lesson_${this.lesson.key}` : "tour";
  }

  willUpdate(changed) {
    // The tour leaves out what is not on the screen; a lesson goes where its steps are, so all of them stay.
    if (changed.has("root") || changed.has("lesson") || !this._steps) {
      this._steps = this.lesson
        ? this.lesson.steps.filter((step) => !step.when || step.when(this.host))
        : shownSteps(this.root);
      this._prepared = null;
    }
    const step = this._steps?.[this._index];
    if (step && this._prepared !== this._index) {
      this._prepared = this._index;
      this._scrolled = null;
      step.prepare?.(this.host);
    }
  }

  // The bubble's own height is known once it is drawn: it is placed again with it.
  updated() {
    const height = this.renderRoot.querySelector("[data-tour-bubble]")?.offsetHeight;
    if (height && height !== this._height) {
      this._height = height;
      this.requestUpdate();
    }
  }

  _go(by) {
    const next = this._index + by;
    if (next < 0) return;
    if (next >= this._steps.length) return this._finish(true);
    this._index = next;
  }

  _finish(completed = false) {
    if (this.lesson) {
      // A lesson counts as done only once it was gone through to its end (Esc in the middle does not).
      if (completed) markLessonDone(this.lesson.key);
    } else writeStored(TOUR_KEY, "done");
    this.dispatchEvent(new CustomEvent("tour-close", { bubbles: true, composed: true, detail: { completed } }));
  }

  render() {
    const t = this.t ?? ((key) => key);
    const steps = this._steps ?? [];
    const step = steps[this._index];
    if (!step) return nothing;
    const targets = typeof step.targets === "function" ? step.targets(this.host) : step.targets;
    // What comes only after an earlier click is framed by the part it belongs to until then.
    const frame = frameOf(this.root, targets) ?? (step.fallback ? frameOf(this.root, step.fallback) : null);
    this._frame = frame;
    // The framed part is brought into view once a step: to the middle when it is out of the window (the frame is cut
    // to the window, so the part's own box tells), else "nearest" - a part cut by its scrolled column (the middle, the
    // tree) is inside the window but partly hidden. A part taller than the window stays where it is.
    if (frame && this._scrolled !== this._index) {
      const part = [...targets, ...(step.fallback ?? [])].map((target) => findTarget(this.root, target)).find(Boolean);
      const box = part?.getBoundingClientRect();
      if (box && box.height < window.innerHeight - 2 * GAP) {
        this._scrolled = this._index;
        const out = box.bottom > window.innerHeight - GAP || box.top < 0;
        part.scrollIntoView({ block: out ? "center" : "nearest" });
        requestAnimationFrame(() => this.requestUpdate());
      }
    }
    const at = bubbleAt(frame, step.side, { height: this._height });
    const last = this._index === steps.length - 1;
    // Steps several lessons share have their texts once: lesson_<shared>_….
    const base = step.shared ? `lesson_${step.shared}` : `${this._prefix}_${step.key}`;
    const waits = step.advance === "click" && frame;
    return html`
      ${waits ? this._renderBlockers(frame) : html`<div class="block" data-tour-block></div>`}
      ${frame
        ? html`<div class="frame" data-tour-frame=${step.key}
            style="left:${frame.left}px;top:${frame.top}px;width:${frame.width}px;height:${frame.height}px"></div>`
        : html`<div class="dim"></div>`}
      <section class="bubble" role="dialog" aria-label=${t(`${base}_title`)} data-tour-bubble=${step.key}
        style="left:${at.left}px;top:${at.top}px;width:${at.width}px">
        <div class="top">
          <span data-tour-count>${this.lesson
            ? t("lesson_step", { name: t(`lesson_${this.lesson.key}_name`), step: this._index + 1, count: steps.length })
            : t("tour_step", { step: this._index + 1, count: steps.length })}</span>
          <button class="close" data-tour-close aria-label=${t("close")} @click=${() => this._finish()}>×</button>
        </div>
        <h3>${t(`${base}_title`)}</h3>
        <p>${t(`${base}_text`)}</p>
        ${step.where ? html`<div class="where"><strong>${t("tour_where")}</strong> ${t(`${base}_where`)}</div>` : nothing}
        ${step.note ? html`<p class="note" data-tour-note>${t(`lesson_note_${step.note}`)}</p>` : nothing}
        ${waits ? html`<p class="try" data-tour-try>${t("lesson_try")}</p>` : nothing}
        <div class="bottom">
          <div class="dots" aria-hidden="true">
            ${steps.map((_, index) => html`<i class=${index === this._index ? "on" : ""}></i>`)}
          </div>
          ${this._index
            ? html`<button class="ghost" data-tour-back @click=${() => this._go(-1)}>${t("tour_back")}</button>`
            : html`<button class="link" data-tour-skip @click=${() => this._finish()}>${t("tour_skip")}</button>`}
          <button class="primary" data-tour-next @click=${() => this._go(1)}>
            ${last ? t("tour_done") : t("tour_next")}
          </button>
        </div>
      </section>
    `;
  }

  // Around a frame that waits for a click: the rest is blocked, the framed part takes the click.
  _renderBlockers(frame) {
    const right = frame.left + frame.width;
    const bottom = frame.top + frame.height;
    const box = (left, top, width, height) =>
      html`<div class="blocker" style="left:${left}px;top:${top}px;width:${Math.max(0, width)}px;height:${Math.max(0, height)}px"></div>`;
    return html`<div data-tour-block="open">
      ${box(0, 0, window.innerWidth, frame.top)} ${box(0, bottom, window.innerWidth, window.innerHeight - bottom)}
      ${box(0, frame.top, frame.left, frame.height)} ${box(right, frame.top, window.innerWidth - right, frame.height)}
    </div>`;
  }

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      z-index: 60;
      pointer-events: none;
      font: 14px/1.45 -apple-system, "SF Pro Text", Roboto, system-ui, sans-serif;
    }
    .block {
      position: absolute;
      inset: 0;
    }
    .blocker {
      position: absolute;
    }
    .block,
    .blocker,
    .bubble {
      pointer-events: auto;
    }
    .dim {
      position: absolute;
      inset: 0;
      background: rgba(4, 8, 14, 0.66);
    }
    .frame {
      position: absolute;
      border-radius: var(--radius, 12px);
      pointer-events: none;
      box-shadow:
        0 0 0 3px var(--panel, #fff),
        0 0 0 6px var(--accent, #4f8cff),
        0 0 0 9999px rgba(4, 8, 14, 0.66);
      transition: left 0.25s, top 0.25s, width 0.25s, height 0.25s;
    }
    .bubble {
      position: absolute;
      box-sizing: border-box;
      padding: 16px;
      border: 1px solid var(--line, #2f343c);
      border-radius: 14px;
      color: var(--text, #e8eaed);
      background: var(--panel, #1b1e24);
      box-shadow: var(--shadow, 0 8px 24px rgba(0, 0, 0, 0.6));
      transition: left 0.25s, top 0.25s;
    }
    .top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--muted, #9aa0a6);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    h3 {
      margin: 6px 0;
      font-size: 17px;
    }
    p {
      margin: 0 0 10px;
    }
    .where {
      padding: 8px 10px;
      border-radius: 10px;
      color: var(--text, #e8eaed);
      background: var(--accent-soft, rgba(79, 140, 255, 0.16));
      font-size: 13px;
    }
    .note {
      margin: 10px 0 0;
      padding: 8px 10px;
      border-radius: 10px;
      background: var(--warn-soft, rgba(255, 179, 64, 0.15));
      font-size: 13px;
    }
    .try {
      margin: 10px 0 0;
      color: var(--accent, #4f8cff);
      font-weight: 600;
      font-size: 13px;
    }
    .bottom {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 14px;
    }
    .dots {
      display: flex;
      flex: 1;
      flex-wrap: wrap;
      gap: 4px;
    }
    .dots i {
      width: 6px;
      height: 6px;
      border-radius: 3px;
      background: var(--line, #2f343c);
    }
    .dots i.on {
      width: 18px;
      background: var(--accent, #4f8cff);
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    .close {
      border: 0;
      background: none;
      color: inherit;
      font-size: 20px;
      line-height: 1;
    }
    .ghost {
      padding: 7px 14px;
      border: 1px solid var(--line, #2f343c);
      border-radius: 10px;
      color: var(--text, #e8eaed);
      background: var(--panel2, #23272e);
    }
    .link {
      border: 0;
      background: none;
      color: var(--muted, #9aa0a6);
    }
    .primary {
      padding: 7px 16px;
      border: 0;
      border-radius: 10px;
      color: #fff;
      background: var(--accent, #4f8cff);
      font-weight: 600;
    }
  `;
}

if (!customElements.get("wakeword-studio-tour")) customElements.define("wakeword-studio-tour", WakewordStudioTour);

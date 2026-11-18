// Training: words to train, data (fetch from Home Assistant, prepare, samples), parameters and start, live progress
// (GPU, chart, final test, advice), command output and log, evaluation and export.
// Taken over from the training panel's cards 3-6 and its right column.

import {
  action, ask, call, card, copyButton, duration, el, field, fmt, helpBox, initSelectedWords, redraw, refresh, select,
  selectedWords, saveSelectedWords, state, t, toast, wordName,
} from "./common.js";
import { renderSamples } from "./recordings.js";

// --- the form of the training, kept per browser (the panel kept the weights; the studio keeps all of it) ---

const FORM_KEY = "wakeword-studio-train";
const WEIGHTS_KEY = "wakeword-weights"; // the panel's key: weights typed there come along
export const WEIGHT_SETS = ["real", "expanded", "elevenlabs", "synthetic", "sound_alikes", "other_words", "background",
  "false_wakes", "speech", "dinner_party", "no_speech"];
const POSITIVE_SETS = new Set(["real", "expanded", "elevenlabs", "synthetic"]);

const read = (key, fallback) => {
  try { return JSON.parse(localStorage.getItem(key) || "null") ?? fallback; } catch { return fallback; }
};
export const form = { steps: "", negative_weight: "", learning_rates: "", convert_only: false, force: false,
  cutoff: null, ...read(FORM_KEY, {}), weights: read(WEIGHTS_KEY, {}) };

function saveForm() {
  const { weights, ...rest } = form;
  try {
    localStorage.setItem(FORM_KEY, JSON.stringify(rest));
    localStorage.setItem(WEIGHTS_KEY, JSON.stringify(weights));
  } catch { /* private mode */ }
}

// --- words to train (card 3) ----------------------------------------------------------------------------

function wordChips() {
  initSelectedWords();
  return el("div", { class: "chips", id: "words" }, ...state.words.map((w) => {
    const box = el("input", { type: "checkbox", "data-train-word": w.id });
    box.checked = selectedWords.has(w.id);
    box.addEventListener("change", () => {
      if (box.checked) selectedWords.add(w.id);
      else selectedWords.delete(w.id);
      saveSelectedWords();
      redraw();
    });
    const note = !w.complete ? t("takes_missing") : !w.prepared ? t("not_prepared") : w.trained ? `✓ ${t("trained")}` : w.speakers.join(", ");
    return el("label", { class: "chip" }, box, el("span", {}, w.wake_word, el("small", {}, note)));
  }));
}

export function renderWordsToTrain() {
  return card(t("words_title"), "words", el("p", { class: "hint" }, t("words_hint")), wordChips());
}

// --- data (card 4) --------------------------------------------------------------------------------------

function haPullHint() {
  const ha = state.home_assistant || {};
  const ready = Boolean(ha.url && ha.token);
  return !ready ? t("ha_pull_off")
    : ha.last_pull ? t("ha_pull_hint", { url: ha.url, when: ha.last_pull.replace("T", " ").slice(0, 16), count: ha.recordings })
      : t("ha_pull_never", { url: ha.url });
}

function prepare(button) {
  const force = form.force;
  const missing = (w) => Object.entries(w.takes).filter(([, [done, target]]) => done < target)
    .map(([sid, [done, target]]) => `${sid} ${done}/${target}`).join(", ");
  let words = state.words.filter((w) => selectedWords.has(w.id));
  if (!words.length) {
    // nothing chosen: every word whose recordings are complete
    const skipped = state.words.filter((w) => !w.complete && !force);
    words = state.words.filter((w) => w.complete || force);
    if (!words.length) return toast(t("prepare_none_ready"), "error");
    if (skipped.length) toast(t("prepare_skipped", { words: skipped.map((w) => `${w.wake_word} (${missing(w)})`).join("; ") }));
  } else if (!force) {
    const incomplete = words.filter((w) => !w.complete);
    if (incomplete.length) {
      return toast(t("prepare_incomplete", { words: incomplete.map((w) => `${w.wake_word}: ${missing(w)}`).join("; ") }), "error");
    }
  }
  action("prepare", { words: words.map((w) => w.id), force }, button);
  return undefined;
}

export function renderData() {
  const ha = state.home_assistant || {};
  const force = el("input", { type: "checkbox", id: "force" });
  force.checked = form.force;
  force.addEventListener("change", () => { form.force = force.checked; saveForm(); });
  return el("div", { class: "stack" },
    renderWordsToTrain(),
    card(t("data_title"), "data",
      el("div", { class: "row-action" },
        el("div", {}, el("strong", {}, t("ha_pull")), el("p", { class: "hint", id: "ha-pull-hint" }, haPullHint())),
        el("button", { class: "btn", id: "ha-pull", disabled: !(ha.url && ha.token), onclick: (e) => action("ha_pull", {}, e.currentTarget) },
          t("ha_pull"))),
      el("div", { class: "row-action" },
        el("div", {}, el("strong", {}, t("prepare")), el("p", { class: "hint" }, t("prepare_hint")),
          el("div", { class: "check-row" }, el("label", { class: "check" }, force, el("span", {}, t("force"))),
            el("span", { class: "info-tip", tabindex: "0", role: "note" }, el("span", { "aria-hidden": "true" }, "i"),
              el("span", { class: "tip" }, t("force_hint"))))),
        el("button", { class: "btn primary", id: "prepare", onclick: (e) => prepare(e.currentTarget) }, t("prepare"))),
      renderSamples()));
}

// --- parameters and start (card 5) ------------------------------------------------------------------------

function weightsPreset(weights) {
  const same = (a, b) => WEIGHT_SETS.every((name) => (a[name] ?? null) === (b[name] ?? null));
  if (!Object.keys(weights).length) return "";
  return Object.entries(state.set_weights.presets).find(([, p]) => same(weights, p.weights))?.[0] ?? "custom";
}

// "family", "neutral" or "own" for the weights a model was trained with
export function weightsLabel(weights) {
  const presets = state.set_weights?.presets || {};
  const name = Object.entries(presets).find(([, p]) => WEIGHT_SETS.every((s) => (p.weights[s] ?? null) === (weights[s] ?? null)))?.[0];
  return t(name ? `preset_${name}` : "models_weights_own");
}

function start(button) {
  // only prepared words can be trained
  const words = [...selectedWords].filter((id) => state.words.find((w) => w.id === id)?.prepared);
  if (!words.length) return toast(t("nothing_prepared"), "error");
  // "0.001, 0.0003, 0.0001": one rate per phase (empty: automatic); numbers with a dot, separated by commas,
  // semicolons or spaces ("0,0001" would be two numbers)
  const rates = String(form.learning_rates).split(/[\s,;]+/).filter(Boolean).map(Number);
  if (rates.some((r) => !(r > 0))) return toast(t("learning_rates_bad"), "error");
  action("start", { words, steps: form.steps ? Number(form.steps) : null,
    negative_weight: form.negative_weight ? Number(form.negative_weight) : null,
    learning_rates: rates, convert_only: form.convert_only, weights: { ...form.weights } }, button)
    .then((answer) => { if (answer) select("train-live"); });
  return undefined;
}

export function renderRun() {
  const number = (key, attrs) => {
    const node = el("input", { type: "number", ...attrs, id: key.replace("_", "-") });
    node.value = form[key];
    node.addEventListener("input", () => { form[key] = node.value; saveForm(); });
    return node;
  };
  const steps = number("steps", { min: 100, step: 1000, placeholder: state.words.find((w) => w.steps)?.steps ?? 20000 });
  const weight = number("negative_weight", { min: 1, max: 200, step: 1,
    placeholder: state.words.find((w) => w.negative_weight)?.negative_weight ?? 20 });
  const rates = el("input", { type: "text", inputmode: "decimal", id: "learning-rates", placeholder: "0.001, 0.0003, 0.0001" });
  rates.value = form.learning_rates;
  rates.addEventListener("input", () => { form.learning_rates = rates.value; saveForm(); });

  const defaults = state.set_weights.defaults;
  const hint = el("p", { class: "hint", id: "set-weights-hint" });
  const presets = el("div", { class: "preset-buttons", id: "weight-presets" });
  const inputs = WEIGHT_SETS.map((name) => {
    const node = el("input", { type: "number", min: 0, max: 50, step: 0.5, placeholder: fmt(defaults[name], 1), "data-set": name });
    node.value = form.weights[name] ?? "";
    node.addEventListener("input", () => {
      if (node.value === "") delete form.weights[name];
      else form.weights[name] = Number(node.value);
      saveForm();
      markPreset();
    });
    return node;
  });
  function markPreset() {
    const current = weightsPreset(form.weights);
    for (const button of presets.querySelectorAll("button")) button.classList.toggle("primary", button.dataset.preset === current);
    hint.textContent = t(current === "" ? "set_weights_default" : current === "custom" ? "set_weights_custom" : `set_weights_${current}`);
  }
  presets.append(...[["family", "preset_family"], ["neutral", "preset_neutral"], ["", "preset_default"]].map(([preset, key]) =>
    el("button", { type: "button", class: "btn small", "data-preset": preset, onclick: () => {
      const chosen = preset ? state.set_weights.presets[preset] : null;
      form.weights = chosen ? { ...chosen.weights } : {};
      form.negative_weight = chosen ? String(chosen.negative_weight) : "";
      inputs.forEach((node) => { node.value = form.weights[node.dataset.set] ?? ""; });
      weight.value = form.negative_weight;
      saveForm();
      markPreset();
      if (chosen) toast(t("preset_applied", { preset: t(`preset_${preset}`) }), "ok");
    } }, t(key))));
  markPreset();
  const convert = el("input", { type: "checkbox", id: "convert-only" });
  convert.checked = form.convert_only;
  convert.addEventListener("change", () => { form.convert_only = convert.checked; saveForm(); });
  const running = state.training.running;
  return el("div", { class: "stack" },
    renderWordsToTrain(),
    card(t("training_title"), "training",
      el("label", { class: "field" }, el("span", {}, t("steps")), steps),
      el("p", { class: "hint" }, t("steps_hint")),
      el("label", { class: "field" }, el("span", {}, t("negative_weight")), weight),
      el("p", { class: "hint" }, t("negative_weight_hint")),
      el("label", { class: "field" }, el("span", {}, t("learning_rates")), rates),
      el("p", { class: "hint" }, t("learning_rates_hint")),
      el("div", { class: "set-weights" },
        el("div", { class: "set-weights-head" },
          el("span", { class: "label" }, t("set_weights")), presets),
        hint,
        el("div", { class: "set-weights-grid", id: "set-weights" }, ...WEIGHT_SETS.map((name, i) =>
          el("label", { class: `field set-weight ${POSITIVE_SETS.has(name) ? "positive" : "negative"}` },
            el("span", {}, t(`set_${name}`)), inputs[i])))),
      el("label", { class: "check" }, convert, el("span", {}, t("convert_only"))),
      powerOffBox(),
      el("div", { class: "actions" },
        el("button", { class: "btn primary big", id: "start", disabled: running, onclick: (e) => start(e.currentTarget) }, t("start")),
        el("button", { class: "btn danger", id: "stop", disabled: !running, onclick: async (e) => {
          const button = e.currentTarget;
          if (await ask(t("confirm_stop"), { danger: true })) action("stop", {}, button);
        } }, t("stop")))));
}

/** "Switch the machine off when it ends" next to Start (the same setting as in the right column). */
function powerOffBox() {
  const ha = state.home_assistant || {};
  if (!(ha.power?.switch && ha.url)) return null;
  const power = state.studio?.power_off || {};
  const box = el("input", { type: "checkbox", id: "power-after-start", checked: Boolean(power.after_training || power.at),
    onchange: async (e) => {
      const enabled = e.currentTarget.checked;
      await call("power/off_after_training", { enabled });
      refresh();
    } });
  return el("label", { class: "check", title: t("side_power_off_hint", { seconds: state.studio?.power_off_delay ?? 120 }) },
    box, el("span", {}, t("side_power_off")));
}

// --- live: stage, GPU, progress per word, the chart, the final test and the advice -----------------------

export let viewedModel = null; // { word, id, label, data } - a kept model's run shown instead of the current one

export async function viewModel(word, id, label, button) {
  button.classList.add("busy");
  try {
    const data = await call("model_progress", { word, model: id });
    viewedModel = { word, id, label, data };
    select("train-live");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    button.classList.remove("busy");
  }
}

// the last line of train.sh speaks to the command line: here, what to do next
function finishedStage(stage) {
  if (stage.startsWith("done")) return t("stage_finished");
  if (stage.startsWith("base chosen")) return t("stage_base_chosen");
  return stage;
}

function ring(value, max, text, warnAt, label) {
  const percent = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (100 * value) / max));
  const color = warnAt && percent >= warnAt ? "var(--warn)" : "var(--accent)";
  return el("div", { class: "meter" },
    el("div", { class: "ring", style: `--value: ${percent}; --color: ${color}` }, el("span", {}, value === null || value === undefined ? "—" : text)),
    el("span", {}, label));
}

/** The stage, the time and the GPU's rings (the right column of the training views and the live view). */
export function liveCard() {
  const training = state.training;
  const progress = training.progress;
  const current = progress.current_word && progress.words[progress.current_word];
  const stage = progress.stage
    ? (current && training.running ? `${wordName(current.word)} · ${t("stage_" + current.stage)}` : finishedStage(progress.stage))
    : "—";
  const gpu = training.gpu;
  return el("section", { class: "card live-card", "data-live": "" },
    el("div", { class: "live-head" },
      el("div", {}, el("div", { class: "label" }, t("stage")), el("div", { class: "stage", id: "stage" }, stage)),
      el("div", { class: "elapsed" }, el("div", { class: "label" }, t("elapsed")),
        el("div", { id: "elapsed" }, training.running && training.started_at ? duration(Date.now() / 1000 - training.started_at) : "—"))),
    el("div", { class: "gpu" },
      el("div", { class: "gpu-name" }, el("span", {}, t("gpu")), " ", el("strong", { id: "gpu-name" }, gpu ? gpu.name : t("no_gpu"))),
      el("div", { class: "meters" },
        ring(gpu?.utilization, 100, `${Math.round(gpu?.utilization ?? 0)}%`, null, t("utilization")),
        ring(gpu?.memory_used, gpu?.memory_total || 1, `${((gpu?.memory_used ?? 0) / 1024).toFixed(1)}G`, 90, t("memory")),
        ring(gpu?.temperature, 95, `${Math.round(gpu?.temperature ?? 0)}°`, 85, t("temperature")),
        ring(gpu?.power, 480, `${Math.round(gpu?.power ?? 0)}W`, null, t("power")))));
}

function verdictClass(value, good, ok, lowerIsBetter = false) {
  if (value === null || value === undefined) return "";
  if (lowerIsBetter) return value <= good ? "good" : value <= ok ? "ok" : "bad";
  return value >= good ? "good" : value >= ok ? "ok" : "bad";
}

function tile(name, value, text, hint, cls) {
  return el("div", { class: `tile ${cls}` }, el("div", { class: "name" }, name),
    el("div", { class: "value" }, text ?? fmt(value)), el("p", { class: "hint" }, hint));
}

// a round top for the right axis whose quarters are round too: 2, 4, 10, 20, 40, 100… (303.2 → 400)
function niceMax(value) {
  const power = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 4, 10].map((m) => m * power).find((m) => m >= value);
}

// steps under the x axis: about one per 110 px, round numbers
function stepTicks(minX, maxX, width) {
  const raw = (maxX - minX) / Math.max(1, Math.floor(width / 110));
  const power = 10 ** Math.floor(Math.log10(Math.max(1, raw)));
  const every = [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= raw);
  const ticks = [];
  for (let s = Math.ceil(minX / every) * every; s <= maxX; s += every) ticks.push(s);
  return ticks;
}

// drawn at the real size of the card, again when the card changes width
function chart(points, phases = []) {
  if (points.length < 2) return null;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const box = el("div", { class: "chart" }, el("div", { class: "label" }, t("chart_title")), svg,
    el("div", { class: "legend" },
      el("span", {}, el("i", { style: "background: var(--accent)" }), t("metric_avr")),
      el("span", {}, el("i", { style: "background: var(--warn)" }), t("metric_faph"))),
    helpBox("chart_help"));
  let drawn = 0;
  new ResizeObserver(() => {
    const width = Math.round(svg.clientWidth);
    if (width && width !== drawn) { drawn = width; drawChart(svg, points, width, phases); }
  }).observe(svg);
  return box;
}

function drawChart(svg, points, W, phases = []) {
  const H = 240, L = 40, R = 44, B = 26;
  const T = phases.length > 1 ? 28 : 12; // room for the phase labels
  const steps = points.map((p) => p.step);
  const minX = Math.min(...steps), maxX = Math.max(...steps);
  const maxF = niceMax(Math.max(2, ...points.map((p) => p.faph)));
  const x = (s) => L + ((s - minX) / Math.max(1, maxX - minX)) * (W - L - R);
  const yA = (v) => T + (1 - v) * (H - T - B);
  const yF = (v) => T + (1 - v / maxF) * (H - T - B);
  const ns = "http://www.w3.org/2000/svg";
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("height", H);
  const add = (tag, attrs, text) => {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    svg.append(node);
    return node;
  };
  const defs = add("defs", {});
  const gradient = document.createElementNS(ns, "linearGradient");
  gradient.setAttribute("id", "avr-fill"); gradient.setAttribute("x1", "0"); gradient.setAttribute("y1", "0");
  gradient.setAttribute("x2", "0"); gradient.setAttribute("y2", "1");
  for (const [offset, opacity] of [["0", ".28"], ["1", "0"]]) {
    const stop = document.createElementNS(ns, "stop");
    stop.setAttribute("offset", offset); stop.setAttribute("stop-color", "var(--accent)"); stop.setAttribute("stop-opacity", opacity);
    gradient.append(stop);
  }
  defs.append(gradient);
  const faphText = (v) => fmt(v, Number.isInteger(maxF / 4) ? 0 : 1);
  // learning rate phases: a band each, the rate and its share of the steps on top, a line where it changes
  if (phases.length > 1) {
    const total = phases.reduce((sum, [n]) => sum + n, 0);
    let from0 = 0;
    phases.forEach(([n, rate], i) => {
      const from = Math.max(from0, minX), to = Math.min(from0 + n, maxX);
      from0 += n;
      if (to <= from) return;
      add("rect", { class: `phase phase-${i % 2}`, x: x(from), y: T, width: x(to) - x(from), height: H - T - B });
      if (i > 0) add("line", { class: "phase-edge", x1: x(from), x2: x(from), y1: T - 4, y2: H - B });
      add("text", { class: "axis phase-label", x: (x(from) + x(to)) / 2, y: T - 8, "text-anchor": "middle" },
        t("phase_label", { rate: String(rate), share: Math.round((n / total) * 100) }));
    });
  }
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    add("line", { class: "grid", x1: L, x2: W - R, y1: yA(v), y2: yA(v) });
    add("text", { class: "axis", x: L - 8, y: yA(v) + 4, "text-anchor": "end" }, fmt(v));
    add("text", { class: "axis faph-axis", x: W - R + 8, y: yA(v) + 4 }, faphText(maxF * v));
  }
  for (const s of stepTicks(minX, maxX, W - L - R)) {
    add("line", { class: "grid tick", x1: x(s), x2: x(s), y1: H - B, y2: H - B + 4 });
    add("text", { class: "axis", x: x(s), y: H - 6, "text-anchor": "middle" }, s.toLocaleString(state?.language || "en"));
  }
  add("line", { class: "target", x1: L, x2: W - R, y1: yA(state.good.avr), y2: yA(state.good.avr) });
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.step).toFixed(1)},${yA(p.avr).toFixed(1)}`).join(" ");
  add("path", { d: `${line} L${x(maxX)},${H - B} L${x(minX)},${H - B} Z`, fill: "url(#avr-fill)" });
  add("path", { class: "faph", d: points.map((p, i) => `${i ? "L" : "M"}${x(p.step).toFixed(1)},${yF(p.faph).toFixed(1)}`).join(" ") });
  add("path", { class: "avr", d: line });
  // a dot and the values on hover, per validation
  for (const p of points) {
    const dot = add("circle", { class: "dot", cx: x(p.step), cy: yA(p.avr), r: 3.2 });
    add("title", {}, `${t("step_label", { step: p.step })} · ${t("metric_avr")} ${fmt(p.avr)} · ${t("metric_faph")} ${fmt(p.faph, 2)}`);
    dot.append(svg.lastChild);
  }
}

// After the final test: deploy, or which parameter to change for the next run and why
function adviceBox(w) {
  const { kind, change, facts } = w.advice;
  const text = t("advice_" + kind, {
    cutoff: fmt(facts.cutoff), steps: change.steps, weight: fmt(facts.negative_weight, 0),
    new_weight: change.negative_weight, faph: fmt(facts.faph_at_good_frr, 1),
    frr: fmt((facts.frr_at_good_faph ?? 0) * 100, 0), avr: fmt(facts.best_avr),
    low: fmt(facts.avr_low), high: fmt(facts.avr_high),
    b_cutoff: fmt(facts.balance_cutoff), b_frr: fmt((facts.balance_frr ?? 0) * 100, 1), b_faph: fmt(facts.balance_faph, 2),
  });
  const rerun = Object.keys(change).length > 0;
  const box = el("div", { class: `callout advice ${kind === "ready" ? "good" : rerun ? "" : "bad"}` },
    el("strong", {}, t("advice_title")), el("p", {}, text));
  if (rerun) {
    box.append(el("p", { class: "hint" }, t("advice_backup")));
    box.append(el("button", { class: "btn small", type: "button", "data-apply-advice": w.word, onclick: () => {
      form.steps = change.steps ? String(change.steps) : "";
      form.negative_weight = change.negative_weight ? String(change.negative_weight) : "";
      form.convert_only = false;
      saveForm();
      selectedWords.clear();
      selectedWords.add(w.word);
      saveSelectedWords();
      toast(t("advice_applied", { word: wordName(w.word) }));
      select("train-run");
    } }, t("advice_apply")));
  }
  return box;
}

function progressWords() {
  const words = viewedModel ? [viewedModel.data] : Object.values(state.training.progress.words);
  if (!words.length) return [el("div", { class: "empty" }, t("no_progress"))];
  const good = state.good;
  const banner = viewedModel ? el("div", { class: "callout viewing" },
    el("span", {}, t("models_viewing", { model: viewedModel.label })),
    el("button", { type: "button", class: "btn small", "data-leave-model": "", onclick: () => { viewedModel = null; redraw(); } },
      t("models_viewing_back"))) : null;
  return [...(banner ? [banner] : []), ...words.map((w) => {
    const info = state.words.find((x) => x.id === w.word);
    const total = w.total_steps || (info && info.steps) || Number(form.steps) || null;
    const last = w.points[w.points.length - 1];
    const order = ["features", "training", "testing", "done"];
    const index = order.indexOf(w.stage);
    const timeline = el("div", { class: "timeline" }, ...order.map((s, i) =>
      el("span", { class: i < index || w.stage === "done" ? "done" : i === index ? "now" : "" }, t("stage_" + s))));
    const step = w.step;
    const percent = total && step ? Math.min(100, (100 * step) / total) : null;
    const counted = [t("step_of", { step, total }), `${Math.floor(percent)}%`];
    if (w.remaining_seconds != null) counted.push(t("time_left", { time: duration(w.remaining_seconds) }));
    const children = [
      el("div", { class: "word-head" },
        el("div", {}, el("h3", {}, info ? info.wake_word : w.word),
          el("span", { class: "sub" }, percent != null ? counted.join(" · ") : t("stage_" + w.stage))),
        el("span", { class: `badge ${w.verdict === "unknown" ? "" : w.verdict}` }, t("verdict_" + w.verdict))),
      timeline,
    ];
    if (percent != null) children.push(el("div", { class: "bar" }, el("div", { style: `width:${percent}%` })));
    if (last) {
      children.push(el("div", { class: "tiles" },
        tile(t("metric_avr"), last.avr, null, `${t("metric_avr_hint")} · ${t("best")} ${fmt(w.best_avr)}`, verdictClass(last.avr, good.avr, 0.75)),
        tile(t("metric_faph"), last.faph, null, t("metric_faph_hint"), verdictClass(last.faph, good.faph, good.faph_ok, true)),
        tile(t("metric_recall_no_faph"), last.recall_no_faph, `${fmt(last.recall_no_faph, 1)}%`,
          t("metric_recall_no_faph_hint", { cutoff: fmt(last.cutoff_no_faph) }), verdictClass(last.recall_no_faph, good.recall_no_faph, 60)),
        tile(t("metric_accuracy"), w.train_accuracy, `${fmt(w.train_accuracy, 1)}%`, t("metric_accuracy_hint"),
          verdictClass(w.train_accuracy, 97, 90))));
      const graph = chart(w.points, w.phases || []);
      if (graph) children.push(graph);
    }
    if (w.roc.length) {
      const pick = w.recommended_cutoff;
      children.push(el("div", { class: "roc" }, el("div", { class: "label" }, `${t("final_title")} · AUC ${fmt(w.auc, 4)}`),
        el("table", {}, el("tr", {}, el("th", {}, t("cutoff")), el("th", {}, t("frr")), el("th", {}, t("faph"))),
          ...w.roc.map((p) => el("tr", { class: p.cutoff === pick ? "pick" : "" },
            el("td", {}, fmt(p.cutoff)), el("td", {}, `${fmt(p.frr * 100, 1)}%`), el("td", {}, fmt(p.faph, 3))))),
        el("div", { class: `callout ${pick !== null ? "good" : "bad"}` },
          pick !== null ? t("recommended", { cutoff: fmt(pick) }) : t("no_recommended"))));
      if (pick !== null && !viewedModel) form.recommended = pick; // "Evaluation and export" starts from it
    }
    if (w.advice) children.push(adviceBox(w));
    return el("div", { class: "word" }, ...children);
  })];
}

const live = { progress: null, shownProgress: "" };

export function renderLive() {
  live.progress = el("div", { id: "progress" });
  live.shownProgress = "";
  const view = el("div", { class: "stack" },
    el("div", { "data-live-slot": "" }, liveCard()),
    card(t("progress_title"), "progress", live.progress));
  updateLive(view);
  return view;
}

/** Called with every state: the rings and time again, the progress only when it changed. */
export function updateLive(view) {
  const slot = view.querySelector("[data-live-slot]");
  if (slot) slot.replaceChildren(liveCard());
  const shown = JSON.stringify([state.language, state.training.progress, viewedModel?.id]);
  if (live.progress && shown !== live.shownProgress) {
    live.shownProgress = shown;
    live.progress.replaceChildren(...progressWords());
  }
}

// --- command output and the training log ----------------------------------------------------------

export function jobCard() {
  const job = state.job;
  if (!job) return el("section", { class: "card job-card" }, el("h2", {}, t("job_title")), el("p", { class: "hint" }, "—"));
  const badge = el("span", { class: `badge ${job.running ? "ok" : job.code === 0 ? "good" : "bad"}`, id: "job-status" },
    `${job.name} · ${job.running ? t("job_running") : job.code === 0 ? t("job_ok") : t("job_failed", { code: job.code })}`);
  const out = el("pre", { class: "terminal", id: "job-output" }, job.lines.join("\n"));
  const copy = el("button", { class: "copy-btn", type: "button", "data-copy-job": "" }, el("span", {}, t("copy")));
  copy.addEventListener("click", () => copyButton(copy, () => (state.job?.lines || []).join("\n")));
  requestAnimationFrame(() => { out.scrollTop = out.scrollHeight; });
  return el("section", { class: "card job-card", id: "job-card" },
    el("div", { class: "card-head" }, el("h2", {}, t("job_title")), badge),
    el("div", { class: "terminal-wrap" }, copy, out));
}

export function logCard() {
  const log = el("pre", { class: "terminal tall", id: "log" }, state.training.log || "—");
  const copy = el("button", { class: "copy-btn", type: "button", "data-copy-log": "" }, el("span", {}, t("copy")));
  // the page shows only the end of the log - copy all of it
  copy.addEventListener("click", () => copyButton(copy, async () => (await call("training_log")).text.trim()));
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  return card(t("log_title"), "log", el("div", { class: "terminal-wrap" }, copy, log));
}

export function renderJobs() {
  const view = el("div", { class: "stack" }, el("div", { "data-job-slot": "" }, jobCard()), el("div", { "data-log-slot": "" }, logCard()));
  return view;
}

/** A terminal keeps its scroll: at the bottom it follows new lines, scrolled up it stays where it is. */
function refill(pre, text) {
  if (!pre || pre.textContent === text) return;
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = text;
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

export function updateJobs(view) {
  const job = state.job;
  const jobSlot = view.querySelector("[data-job-slot]");
  if (jobSlot && (!job || !jobSlot.querySelector("#job-output"))) jobSlot.replaceChildren(jobCard());
  else if (jobSlot) {
    refill(jobSlot.querySelector("#job-output"), job.lines.join("\n"));
    const badge = jobSlot.querySelector("#job-status");
    badge.className = `badge ${job.running ? "ok" : job.code === 0 ? "good" : "bad"}`;
    badge.textContent = `${job.name} · ${job.running ? t("job_running") : job.code === 0 ? t("job_ok") : t("job_failed", { code: job.code })}`;
  }
  refill(view.querySelector("#log"), state.training.log || "—");
}

// --- evaluation and export (card 6) ---------------------------------------------------------------------

// which model "Evaluate" and "Export" take - the one in the household's build folder
function exportedModel(word) {
  const model = word.model;
  const text = model ? t("export_model", { model: `#${model.number} ${model.name} (${modelDate(model.id)})` }) : t("export_model_unknown");
  return el("span", { class: "export-model-box" }, el("div", { class: "export-model" }, text));
}

export const modelDate = (id) => `${id.slice(6, 8)}.${id.slice(4, 6)} ${id.slice(9, 11)}:${id.slice(11, 13)}`;

export function renderExport() {
  const cutoff = el("input", { id: "cutoff", type: "number", min: 0.5, max: 0.999, step: 0.01 });
  cutoff.value = form.cutoff ?? form.recommended ?? 0.97;
  cutoff.addEventListener("input", () => { form.cutoff = cutoff.value; saveForm(); });
  const trained = state.words.filter((w) => w.trained);
  return card(t("results_title"), "results",
    el("div", { class: "list", id: "evaluate-list" }, ...(trained.length ? trained.map((w) =>
      el("div", { class: "item" }, el("span", {}, el("strong", {}, w.wake_word), " ",
        el("span", { class: "badge good" }, t("trained")), exportedModel(w)),
      el("button", { class: "btn", "data-evaluate": w.id, onclick: (e) => action("evaluate", { word: w.id }, e.target) }, t("evaluate"))))
      : [el("p", { class: "hint" }, t("models_none"))])),
    el("div", { class: "row-action" },
      el("label", { class: "field small" }, el("span", {}, t("cutoff")), cutoff),
      el("button", { class: "btn primary", id: "export", disabled: !trained.length,
        onclick: (e) => action("export", { cutoff: Number(cutoff.value) }, e.target) }, t("export"))),
    form.recommended ? el("p", { class: "hint" }, t("recommended", { cutoff: fmt(form.recommended) })) : null);
}

export { refresh };

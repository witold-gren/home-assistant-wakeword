// Home → False wakes: the wake log of Home Assistant (Wake Word Recorder 0.3.0, /api/wake_word_recorder/wake_log)
// sorted out by the studio (wakeword/false_wakes.py): per day, per satellite, per wake word and, for a word trained
// here, before and after its model went to the satellites. The goal: at most one false wake a day (chapter 12).

import { call, card, el, fmt, helpButton, redraw, select, t } from "./common.js";

const DAYS_KEY = "wakeword-studio-false-wakes-days";
const PERIODS = [7, 14, 30, 90];
const FALSE_KINDS = new Set(["no_speech", "hallucination", "short"]);

let data = null; // the "false_wakes" answer
let error = null;
let loading = null;
let asked = null; // the period and dates the data is for
const deployed = {}; // word id -> "YYYY-MM-DD" set by hand

function periodDays() {
  try {
    const days = Number(localStorage.getItem(DAYS_KEY));
    return PERIODS.includes(days) ? days : 30;
  } catch {
    return 30;
  }
}

function sinceFor(days) {
  const day = new Date(Date.now() - days * 86400000);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

export function forgetFalseWakes() {
  data = null;
  error = null;
}

function load() {
  const request = JSON.stringify([periodDays(), deployed]);
  if (loading || asked === request) return;
  asked = request;
  loading = call("false_wakes", { since: sinceFor(periodDays()), deployed: { ...deployed } }, { timeout: 40000 })
    .then((answer) => { data = answer; error = null; })
    .catch((err) => { error = err.message; })
    .finally(() => { loading = null; redraw(); });
}

function refresh() {
  asked = null;
  data = null;
  load();
  redraw();
}

const rateClass = (perDay, goal) => (perDay <= goal ? "good" : perDay <= 2 * goal ? "ok" : "bad");

function tile(name, value, hint, cls = "") {
  return el("div", { class: `tile ${cls}` }, el("div", { class: "name" }, name), el("div", { class: "value" }, value),
    el("p", { class: "hint" }, hint));
}

function table(attr, head, rows) {
  return el("div", { class: "table-wrap" }, el("table", { class: "overview-words fw-table", [attr]: "" },
    el("tr", {}, ...head.map((name) => el("th", {}, name))), ...rows));
}

function compare(word) {
  if (!word.before || !word.after) return [el("td", {}, "—"), el("td", {}, "—")];
  // less than a day after the model says nothing yet
  const verdict = word.after.days < 1 ? "" : word.after.per_day < word.before.per_day ? "fw-better" : "fw-worse";
  return [
    el("td", {}, t("fw_rate", { rate: fmt(word.before.per_day), days: fmt(word.before.days, 1) })),
    el("td", { class: verdict, title: verdict ? "" : t("fw_too_early") },
      t("fw_rate", { rate: fmt(word.after.per_day), days: fmt(word.after.days, 1) })),
  ];
}

function dateInput(word) {
  const input = el("input", { type: "date", "data-fw-deployed": word.word, title: t("fw_deployed_hint") });
  input.value = deployed[word.word] ?? (word.deployed || "").slice(0, 10);
  input.addEventListener("change", () => {
    if (input.value) deployed[word.word] = input.value;
    else delete deployed[word.word];
    asked = null;
    load();
  });
  return input;
}

function chart(days) {
  const top = Math.max(1, ...days.map((d) => d.wakes));
  return el("div", { class: "fw-days", "data-fw-days": "" }, ...days.map((d) => el("div", {
    class: "fw-day", title: t("fw_day_title", { day: d.day, wakes: d.wakes, false: d.false }) },
  el("div", { class: "fw-bar all", style: `height:${(100 * d.wakes) / top}%` }),
  el("div", { class: "fw-bar false", style: `height:${(100 * d.false) / top}%` }))));
}

function advice(result) {
  const worst = result.devices.find((d) => d.false > 0);
  if (result.per_day <= result.goal_per_day) return el("div", { class: "callout good", "data-fw-advice": "ok" }, t("fw_advice_ok"));
  return el("div", { class: "callout bad", "data-fw-advice": "high" },
    t("fw_advice_high", { device: worst ? worst.area || worst.device : "—" }),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn small", onclick: () => select("background") }, t("n_background")),
      el("button", { type: "button", class: "btn small", onclick: () => select("words") }, t("n_words")),
      el("button", { type: "button", class: "btn small", onclick: () => select("export") }, t("n_export"))));
}

export function renderFalseWakes() {
  const period = el("select", { "data-fw-since": "" }, ...PERIODS.map((days) =>
    el("option", { value: String(days), ...(days === periodDays() ? { selected: "" } : {}) }, t("fw_period", { days }))));
  period.addEventListener("change", () => {
    try { localStorage.setItem(DAYS_KEY, period.value); } catch { /* private mode */ }
    refresh();
  });
  const head = el("div", { class: "fw-controls" }, el("label", { class: "field small" }, el("span", {}, t("fw_since")), period),
    el("button", { type: "button", class: "btn", "data-fw-refresh": "", onclick: refresh }, t("refresh")));
  const title = card(t("n_false_wakes"), null, el("p", { class: "hint" }, t("fw_intro")), head);
  title.querySelector(".card-head").append(helpButton(t("n_false_wakes"), t("fw_help")));
  load();
  if (error) return el("div", { class: "stack" }, title, card(t("fw_error_title"), null,
    el("p", { class: "field-error", "data-fw-error": "" }, error), el("p", { class: "hint" }, t("fw_error_hint"))));
  if (!data) return el("div", { class: "stack" }, title, card("", null, el("p", { class: "hint" }, t("loading"))));
  const result = data;
  const kinds = result.kinds;
  const summary = el("div", { class: "tiles", "data-fw-summary": "" },
    tile(t("fw_wakes"), String(result.wakes), t("fw_wakes_hint", { days: fmt(result.days, 1) })),
    tile(t("fw_false"), String(result.false), t("fw_false_hint", { no_speech: kinds.no_speech, hallucination: kinds.hallucination,
      short: kinds.short })),
    tile(t("fw_per_day"), fmt(result.per_day), t("fw_per_day_hint", { goal: fmt(result.goal_per_day, 0) }),
      rateClass(result.per_day, result.goal_per_day)),
    tile(t("fw_unclear"), String(kinds.cancelled), t("fw_unclear_hint")),
    tile(t("fw_left_out"), String(kinds.duplicate + kinds.recorder), t("fw_left_out_hint", { duplicate: kinds.duplicate,
      recorder: kinds.recorder })));
  const words = table("data-fw-words", [t("col_word"), t("fw_wakes"), t("fw_false"), t("fw_per_day"), t("fw_deployed"),
    t("fw_before"), t("fw_after")], result.words.map((word) => el("tr", { "data-fw-word": word.wake_word },
    el("td", {}, word.wake_word), el("td", {}, String(word.wakes)), el("td", {}, String(word.false)),
    el("td", { class: `fw-rate ${rateClass(word.per_day, result.goal_per_day)}` }, fmt(word.per_day)),
    el("td", {}, word.word ? dateInput(word) : el("span", { class: "hint" }, t("fw_not_ours"))), ...compare(word))));
  const devices = table("data-fw-devices", [t("fw_device"), t("fw_wakes"), t("fw_false"), t("fw_per_day")],
    result.devices.map((device) => el("tr", {}, el("td", {}, device.area || device.device, el("div", { class: "hint" }, device.device)),
      el("td", {}, String(device.wakes)), el("td", {}, String(device.false)),
      el("td", { class: `fw-rate ${rateClass(device.per_day, result.goal_per_day)}` }, fmt(device.per_day)))));
  const recent = result.recent.length ? table("data-fw-recent", [t("fw_when"), t("fw_device"), t("col_word"), t("fw_kind"), t("fw_text")],
    result.recent.map((row) => el("tr", {}, el("td", {}, row.timestamp.slice(5, 16)), el("td", {}, row.area || row.device),
      el("td", {}, row.wake_word),
      el("td", {}, el("span", { class: `badge ${FALSE_KINDS.has(row.kind) ? "bad" : ""}` }, t(`fw_kind_${row.kind}`))),
      el("td", {}, row.text || "—"))))
    : el("p", { class: "hint", "data-fw-recent": "" }, t("fw_recent_none"));
  return el("div", { class: "stack" }, title,
    card(t("fw_summary"), null, summary, advice(result)),
    card(t("fw_words"), null, el("p", { class: "hint" }, t("fw_words_hint")), words),
    card(t("fw_by_day"), null, el("p", { class: "hint" }, t("fw_by_day_hint")), chart(result.by_day)),
    card(t("fw_devices"), null, devices),
    card(t("fw_recent"), null, el("p", { class: "hint" }, t("fw_recent_hint")), recent));
}

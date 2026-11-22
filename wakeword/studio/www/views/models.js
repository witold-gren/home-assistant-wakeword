// The kept models of each word: both rankings (household, neutral), why the best one is best, the base of the next
// run, a model's chart, choosing a model or training from scratch. Taken over from the training panel (card Models).

import {
  action, ask, call, card, collapsed, el, fmt, helpBox, redraw, saveCollapsed, state, t, wordName,
} from "./common.js";
import { modelDate, viewModel, weightsLabel } from "./training.js";

let modelLists = {}; // word → listing of the "models" call, or {error}
let loadingWords = null;
// which test ranks the models: "household" (family takes, home background) or "neutral" (synthetic voices)
const RANK_KEY = "wakeword-rank";
let rankChoice = null;
try { rankChoice = localStorage.getItem(RANK_KEY); } catch { rankChoice = null; }
let lastStage = null; // a run that ends lists the models again
let reloadAfterChoice = false;

function rankMode() {
  if (rankChoice === "household" || rankChoice === "neutral") return rankChoice;
  return Object.values(modelLists).some((l) => l.best_household) ? "household" : "neutral"; // measured: household
}

// the best model of a word by the chosen test (household not measured yet: the neutral one)
function bestOf(listing) {
  return rankMode() === "household" && listing.best_household ? listing.best_household : listing.best;
}

const percent = (value) => `${fmt(value * 100, 1)}%`;
// "#3 wolny_wiatr" - the number in the order the models were made, and the name kept with the model
function modelNumber(listing, id) {
  return listing.models.map((m) => m.id).sort().indexOf(id) + 1; // ids are times: the order they were made
}
function modelLabel(listing, id) {
  const model = listing.models.find((m) => m.id === id);
  if (!model) return modelDate(id);
  return `#${modelNumber(listing, id)} ${model.run?.name || ""} (${modelDate(id)})`.replace("  ", " ");
}

export async function loadModels(words, button = null) {
  const key = words.join(",");
  if (loadingWords === key && !button) return;
  loadingWords = key;
  if (button) button.classList.add("busy");
  const fresh = {}; // put in place at once: the tables do not vanish while the machine answers
  for (const word of words) {
    try {
      fresh[word] = await call("models", { word });
    } catch (err) {
      fresh[word] = { error: err.message };
    }
  }
  modelLists = { ...modelLists, ...fresh };
  loadingWords = null;
  if (button) button.classList.remove("busy");
  redraw();
}

async function chooseModel(word, model, button, label = "") {
  const question = model === "new" ? t("models_new_confirm", { word: wordName(word) })
    : t("models_choose_confirm", { model: label || modelDate(model), word: wordName(word) });
  if (!(await ask(question, { ok: t(model === "new" ? "models_new_ok" : "models_choose_ok") }))) return;
  reloadAfterChoice = true;
  action("choose_model", { word, model }, button);
}

function rankSwitch() {
  const mode = rankMode();
  const button = (value) => el("button", { type: "button", class: `btn small ${mode === value ? "primary" : ""}`, "data-rank": value,
    onclick: () => {
      rankChoice = value;
      try { localStorage.setItem(RANK_KEY, value); } catch { /* private mode */ }
      redraw();
    } }, t(`models_rank_${value}`));
  return el("div", { class: "rank-switch" }, el("span", { class: "label" }, t("models_rank")), button("household"),
    button("neutral"), el("span", { class: "hint" }, t(`models_rank_${mode}_hint`)));
}

// one word's block, folded by its heading (remembered per browser)
function modelsWord(word, note, ...body) {
  const key = `models:${word}`;
  const summary = el("summary", {}, el("h4", { class: "rec-heading" }, wordName(word)),
    note ? el("span", { class: "models-word-note" }, note) : null);
  const box = el("details", { class: "models-word", "data-models-word": word }, summary, ...body);
  box.open = !collapsed[key];
  summary.addEventListener("click", () => {
    collapsed[key] = box.open; // still the state before the click: open now = folded after it
    saveCollapsed();
  });
  return box;
}

// the two tests of a model: the household one (family takes, home background) and the neutral one
function householdCell(m) {
  const score = m.household_score;
  if (!score) {
    return el("td", {}, el("div", { class: "model-goal muted" }, "—"),
      el("div", { class: "rec-meta" }, t(m.household ? "models_household_none" : "models_household_missing")));
  }
  const people = Object.entries(score.missed).map(([p, k]) => `${p} ${k}/${m.household.takes[p]}`).join(", ");
  return el("td", {}, el("div", { class: "model-goal" }, score.ready ? t("models_goal_met") : t("models_goal_times", { times: fmt(score.times, 1) })),
    el("div", { class: "rec-meta" }, t("models_household_cutoff", { cutoff: fmt(score.cutoff) })),
    el("div", { class: "rec-meta" }, t("models_household_missed", { frr: percent(score.frr_worst), people })),
    el("div", { class: "rec-meta" }, t("models_household_wakes", { wakes: score.false_wakes, hours: fmt(m.household.hours, 1) })));
}

function neutralCell(m) {
  const score = m.score;
  if (!score) return el("td", {}, el("div", { class: "model-goal muted" }, "—"), el("div", { class: "rec-meta" }, t("models_no_test")));
  return el("td", {}, el("div", { class: "model-goal" }, score.ready ? t("models_goal_met") : t("models_goal_times", { times: fmt(score.times, 1) })),
    el("div", { class: "rec-meta" }, t("models_household_cutoff", { cutoff: fmt(score.cutoff) })),
    el("div", { class: "rec-meta" }, t("models_neutral_missed", { frr: percent(score.frr) })),
    el("div", { class: "rec-meta" }, t("models_neutral_wakes", { faph: fmt(score.faph, 2) })));
}

// the household ranking in plain words: the best, the runner-up, and how sure the background test is
function modelsWhyHousehold(listing) {
  const sorted = listing.models.filter((m) => m.household_score).sort((a, b) => a.household_score.times - b.household_score.times);
  if (!sorted.length) return el("p", { class: "hint" }, t("models_why_household_none"));
  const values = (m) => ({ model: modelLabel(listing, m.id), cutoff: fmt(m.household_score.cutoff),
    frr: percent(m.household_score.frr_worst), wakes: m.household_score.false_wakes, hours: fmt(m.household.hours, 1),
    times: fmt(m.household_score.times, 1) });
  const best = sorted.find((m) => m.id === listing.best_household) || sorted[0];
  const text = [t(best.household_score.ready ? "models_why_household_ready" : "models_why_household", values(best))];
  const next = sorted.find((m) => m.id !== best.id);
  if (next) text.push(t("models_why_household_next", values(next)));
  const hours = best.household.hours;
  if (hours > 0) text.push(t("models_household_hours", { hours: fmt(hours, 1), per_day: fmt(24 / hours, 0) }));
  return el("div", { class: "callout good models-why" }, ...text.map((line) => el("p", {}, line)));
}

// why the best one is best, in plain words, next to the runner-up
function modelsWhy(listing) {
  const sorted = listing.models.filter((m) => m.score).sort((a, b) => a.score.times - b.score.times);
  if (!sorted.length) return el("p", { class: "hint" }, t("models_why_none"));
  const best = sorted[0];
  const text = [t(best.score.ready ? "models_why_ready" : "models_why", { model: modelLabel(listing, best.id),
    cutoff: fmt(best.score.cutoff), frr: percent(best.score.frr), faph: fmt(best.score.faph, 2), times: fmt(best.score.times, 1) })];
  const next = sorted[1];
  if (next) {
    text.push(t("models_why_next", { model: modelLabel(listing, next.id), cutoff: fmt(next.score.cutoff), frr: percent(next.score.frr),
      faph: fmt(next.score.faph, 2), times: fmt(next.score.times, 1) }));
  }
  return el("div", { class: "callout good models-why" }, ...text.map((line) => el("p", {}, line)));
}

function modelsBase(listing) {
  if (listing.base === "new") return el("p", { class: "hint" }, t("models_base_new"));
  if (!listing.base) return null;
  return el("p", { class: "hint" }, t("models_base_is", { model: modelLabel(listing, listing.base) }));
}

function modelsTable(word, listing) {
  if (listing.error) return modelsWord(word, "", el("div", { class: "callout bad" }, listing.error));
  if (!listing.models.length) return modelsWord(word, "", el("p", { class: "hint" }, t("models_none")));
  const busy = state.training.running;
  const best = bestOf(listing);
  const rows = [...listing.models].reverse().map((m) => {
    const run = m.run || {};
    // which model this run continued from (its number and name), or from scratch
    const parent = listing.models.find((p) => p.id === run.base);
    const from = run.base === "new" ? t("models_from_scratch_short")
      : parent ? el("span", {}, el("strong", {}, `#${modelNumber(listing, parent.id)}`), ` ${parent.run?.name || modelDate(parent.id)}`)
        : run.base ? modelDate(run.base) : "—";
    const training = run.steps
      ? el("div", {}, t("models_run", { steps: run.steps, weight: fmt(run.negative_weight, 0), rates: (run.learning_rates || []).join(" → ") }),
        run.weights ? el("div", { class: "rec-meta" }, t("models_weights", { preset: weightsLabel(run.weights) })) : null,
        run.reconstructed ? el("span", { class: "badge", title: t("models_reconstructed_hint") }, t("models_reconstructed")) : null)
      : t("models_run_unknown");
    const badges = [
      m.id === best ? el("span", { class: "badge ok" }, t("models_best")) : null,
      m.id === listing.base ? el("span", { class: "badge" }, t("models_base")) : null,
      m.current ? el("span", { class: "badge", title: t("models_current_hint") }, t("models_current")) : null,
    ];
    const actions = el("div", { class: "model-actions" },
      el("button", { type: "button", class: "btn small", disabled: !m.chart, title: m.chart ? t("models_view_hint") : t("models_no_chart"),
        "data-view-model": m.id, onclick: (e) => viewModel(word, m.id, modelLabel(listing, m.id), e.currentTarget) }, t("models_view")),
      el("button", { type: "button", class: "btn small", disabled: busy || m.id === listing.base, "data-choose-model": m.id,
        onclick: (e) => chooseModel(word, m.id, e.currentTarget, modelLabel(listing, m.id)) }, t("models_choose")));
    return el("tr", { class: m.id === best ? "pick" : "" },
      el("td", { class: "model-nr" }, `#${modelNumber(listing, m.id)}`),
      el("td", {}, el("strong", {}, run.name || modelDate(m.id)), el("div", { class: "rec-meta" }, modelDate(m.id)),
        el("div", { class: "badges" }, ...badges)),
      el("td", {}, from), el("td", {}, training), householdCell(m), neutralCell(m),
      el("td", {}, m.auc === null ? "—" : fmt(m.auc, 3)), el("td", {}, actions));
  });
  const table = el("table", { class: "models-table" },
    el("tr", {}, ...[["models_col_nr"], ["models_col_model"], ["models_col_from"], ["models_col_training", "steps"],
      ["models_col_household", "household"], ["models_col_neutral", "goal"], ["AUC", "auc"], [""]]
      .map(([k]) => el("th", {}, k.startsWith("models_") ? t(k) : k))),
    ...rows);
  const note = t("models_word_note", { count: listing.models.length, best: listing.best ? modelLabel(listing, listing.best) : "—" });
  return modelsWord(word, note, el("div", { class: "table-wrap" }, table),
    rankMode() === "household" ? modelsWhyHousehold(listing) : modelsWhy(listing), modelsBase(listing),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn small", disabled: busy || listing.base === "new", "data-from-scratch": word,
        onclick: (e) => chooseModel(word, "new", e.currentTarget) }, t("models_from_scratch", { word: wordName(word) })),
      el("button", { type: "button", class: "btn small", disabled: busy, title: t("models_evaluate_hint"), "data-household-test": word,
        onclick: (e) => action("evaluate_models", { word }, e.currentTarget) }, t("models_evaluate"))),
    helpBox("models_help"));
}

/** The models of one word, or of every prepared word. */
export function renderModels(only = null) {
  const words = state.words.filter((w) => (!only || w.id === only));
  const prepared = words.filter((w) => w.prepared).map((w) => w.id);
  const missing = prepared.filter((w) => !(w in modelLists));
  if (missing.length) loadModels(missing);
  const tables = prepared.filter((w) => w in modelLists).map((w) => modelsTable(w, modelLists[w]));
  const waiting = words.filter((w) => !w.prepared).map((w) => modelsWord(w.id, "", el("p", { class: "hint" }, t("models_not_prepared"))));
  const load = el("button", { class: "btn", id: "load-models", onclick: (e) => loadModels(prepared, e.currentTarget) }, t("models_load"));
  return card(only ? `${t("models_title")} · ${wordName(only)}` : t("models_title"), "models",
    el("div", { class: "row-action" }, el("p", { class: "hint" }, t("models_hint")), load),
    el("div", { id: "models", class: "models" },
      ...(tables.length ? [rankSwitch()] : []), ...tables,
      ...(missing.length ? [el("p", { class: "hint" }, t("loading"))] : []), ...waiting));
}

/** With every state: a run that ended (or a chosen base) lists the models again. */
export function watchModels() {
  const stage = state.training.progress.stage || "";
  const ended = lastStage !== null && stage !== lastStage && stage.startsWith("done");
  const chosen = reloadAfterChoice && !state.training.running && stage.startsWith("base chosen");
  lastStage = stage;
  if (ended || chosen) {
    reloadAfterChoice = false;
    modelLists = {};
    return true;
  }
  return false;
}

/** The household test was done: the Household column is filled. */
export function forgetModels() {
  modelLists = {};
}

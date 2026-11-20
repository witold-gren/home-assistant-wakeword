// The dashboard: the road from recordings to a model in Home Assistant (the panel's stepper), what to do next,
// what runs now and every word at a glance.

import { card, el, household, icon, select, selectedWords, state, t } from "./common.js";

/** Which steps are done, and the first one that is not. */
export function steps() {
  const words = state.words;
  const exists = state.household.exists && words.length > 0 && (household?.data.speakers || []).length > 0;
  const prepared = words.filter((w) => w.prepared);
  const trained = words.some((w) => w.trained);
  const done = {
    family: exists,
    recordings: exists && words.every((w) => w.complete),
    data: prepared.length > 0 && words.filter((w) => w.complete).every((w) => w.prepared),
    training: trained || Boolean(state.training.progress.finished),
    results: trained && words.every((w) => !w.prepared || w.trained),
  };
  const order = ["family", "recordings", "data", "training", "results"];
  return { done, order, next: order.find((s) => !done[s]) || null };
}

const NEXT_NODE = { family: "people", recordings: "train-data", data: "train-data", training: "train-run", results: "export" };

export function renderOverview() {
  const { done, order, next } = steps();
  const stepper = el("ol", { class: "steps", "data-steps": "" }, ...order.map((step, i) =>
    el("li", { class: done[step] ? "done" : step === next ? "active" : "", "data-step": step },
      el("span", { class: "num" }, done[step] ? "✓" : String(i + 1)), el("span", {}, t(`step_${step === "family" ? "family" : step}`)))));
  const training = state.training;
  const status = training.checking ? t("status_checking") : training.error ? `${t("connection_error")}: ${training.error}`
    : training.running ? t("running") : training.progress.finished ? t("finished") : t("idle");
  const ha = state.home_assistant || {};
  const words = state.words.map((w) => {
    const takes = Object.entries(w.takes).map(([sid, [count, goal]]) =>
      el("span", { class: `count ${count >= goal ? "done" : count ? "part" : ""}` }, `${sid} ${count}/${goal}`));
    return el("tr", { "data-word-row": w.id },
      el("td", {}, el("button", { type: "button", class: "link-btn", onclick: () => select(`word/${w.id}`) }, w.wake_word),
        selectedWords.has(w.id) ? el("span", { class: "badge" }, t("words_title")) : null),
      el("td", {}, el("div", { class: "counts" }, ...takes)),
      el("td", {}, w.prepared ? "✓" : "—"),
      el("td", {}, w.trained ? `✓ ${w.model ? `#${w.model.number} ${w.model.name}` : ""}` : "—"));
  });
  return el("div", { class: "stack" },
    card(t("n_overview"), null, stepper,
      el("div", { class: "callout next", "data-next": next || "done" },
        el("strong", {}, t("overview_next")),
        el("p", {}, t(next ? `next_${next}` : "next_done")),
        next ? el("button", { type: "button", class: "btn primary", onclick: () => select(NEXT_NODE[next]) },
          icon("mdi:arrow-right"), t("open")) : null)),
    card(t("overview_status"), null,
      el("p", { class: `status-line ${training.error ? "bad" : training.running ? "running" : ""}`, "data-status": "" }, status),
      state.job ? el("p", { class: "hint" }, `${state.job.name} · ${state.job.running ? t("job_running")
        : state.job.code === 0 ? t("job_ok") : t("job_failed", { code: state.job.code })}`) : null,
      ha.rejected ? el("div", { class: "callout bad ha-rejected" }, t("ha_token_rejected")) : null,
      !ha.url ? el("p", { class: "hint warn" }, t("ha_pull_off")) : null),
    state.words.length ? card(t("n_words"), null, el("div", { class: "table-wrap" }, el("table", { class: "overview-words" },
      el("tr", {}, el("th", {}, t("col_word")), el("th", {}, t("col_takes")), el("th", {}, t("col_prepared")),
        el("th", {}, t("col_trained"))),
      ...words))) : null);
}

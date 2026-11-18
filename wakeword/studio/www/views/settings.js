// Settings saved at once (not in household.yaml): Home Assistant, the machine's power, the Hugging Face token,
// the login. Taken over from the training panel (renderHomeAssistant, renderPowerSettings, the HF token).

import { action, ask, call, card, el, field, fmt, redraw, refresh, select, state, t, toast } from "./common.js";

// --- Home Assistant: the satellites' recordings through its API ----------------------------------------

export function renderHomeAssistant() {
  const ha = state.home_assistant || {};
  const url = el("input", { value: ha.url || "", placeholder: "http://homeassistant.local:8123", "data-ha-url": "" });
  const token = el("input", { type: "password", autocomplete: "off", "data-ha-token": "",
    placeholder: ha.token ? t("ha_token_saved") : t("ha_token_placeholder") });
  const save = el("button", { type: "button", class: "btn primary", "data-ha-save": "", onclick: async (e) => {
    const extra = { url: url.value };
    if (token.value.trim()) extra.token = token.value.trim(); // empty: the saved token stays
    const button = e.currentTarget;
    button.classList.add("busy");
    try { // saving asks Home Assistant once - also after it rejected the token
      await call("action", { action: "ha_connection", ...extra });
      if (extra.url) toast(t("ha_connection_ok"));
    } catch (err) {
      toast(err.message, "error");
    } finally {
      button.classList.remove("busy");
    }
    await refresh();
    token.value = "";
    redraw();
  } }, t("ha_save"));
  const remove = ha.url || ha.token ? el("button", { type: "button", class: "btn danger", onclick: async (e) => {
    const button = e.currentTarget;
    if (!(await ask(t("ha_remove_confirm"), { danger: true }))) return;
    await action("ha_connection", { url: "", token: "" }, button);
    redraw();
  } }, t("ha_remove")) : null;
  return card(t("ha_title"), null,
    el("p", { class: "hint" }, t("ha_hint")),
    ha.rejected ? el("div", { class: "callout bad ha-rejected" }, t("ha_token_rejected")) : null,
    field(t("ha_url"), url),
    field(t("ha_token"), token, t("ha_token_hint")),
    el("div", { class: "voice-repo-row" }, save, remove));
}

// --- the machine's power through its switch in Home Assistant ---------------------------------------------

let haEntities = null; // the switches and power sensors of Home Assistant, read once
let haEntitiesLoading = null;

function loadHaEntities(again = false) {
  if (again) { haEntities = null; haEntitiesLoading = null; }
  haEntitiesLoading ??= call("ha_entities").then((answer) => { haEntities = answer; return answer; })
    .catch(() => { haEntitiesLoading = null; return null; }); // no connection: the ids are typed by hand
  return haEntitiesLoading;
}

// a list of Home Assistant entities, "name (entity id)"; while Home Assistant is asked it says so, and when it
// gives no list the id is typed by hand
function entityPicker(kind, value, placeholder) {
  const choose = el("select", { disabled: true, "data-entity": kind }, el("option", { value: value || "" }, t("ha_entities_loading")));
  const typed = el("input", { value: value || "", placeholder, autocomplete: "off", hidden: true, "data-entity-typed": kind });
  const box = el("div", { class: "entity-picker" }, choose, typed);
  box.fill = (entities) => {
    if (!entities) { choose.hidden = true; typed.hidden = false; return; }
    const current = box.value;
    const list = [...(entities[kind] || [])].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
    const known = new Set(list.map((e) => e.id));
    choose.replaceChildren(el("option", { value: "" }, t("ha_entity_choose")),
      ...(current && !known.has(current) ? [el("option", { value: current }, current)] : []),
      ...list.map((e) => el("option", { value: e.id }, e.name ? `${e.name} (${e.id})` : e.id)));
    choose.value = current;
    choose.disabled = false;
    choose.hidden = false;
    typed.hidden = true;
  };
  Object.defineProperty(box, "value", { get: () => (choose.hidden ? typed.value : choose.value).trim() });
  return box;
}

/** The header's button and Settings: the machine can only be switched off from here (it runs the studio). */
export async function switchMachineOff(button) {
  const kind = state.machine?.machine;
  if (kind === "rejected") return toast(t("ha_token_rejected"), "error");
  if (state.training.running) return toast(t("power_off_running"), "error");
  if (!(await ask(t("power_off_confirm"), { danger: true }))) return undefined;
  await action("machine_off", {}, button);
  return undefined;
}

export function machineLabel() {
  const machine = state.machine;
  if (!machine) return "";
  const kind = machine.machine || "unknown";
  const watts = machine.watts === null || machine.watts === undefined || kind === "off" ? "" : ` · ${fmt(machine.watts, 0)} W`;
  return t(`machine_${kind}`) + watts;
}

export function renderPower() {
  const ha = state.home_assistant || {};
  if (!(ha.url && ha.token)) {
    return card(t("power_title"), null, el("p", { class: "hint" }, t("power_hint")), el("p", { class: "hint warn" }, t("ha_pull_off")));
  }
  const settings = ha.power || {};
  const plug = entityPicker("switches", settings.switch, "switch.…");
  const sensor = entityPicker("sensors", settings.sensor, "sensor.…");
  const watts = el("input", { type: "number", min: 1, max: 100, step: 1, value: settings.off_watts ?? 5, "data-off-watts": "" });
  const fill = async (again) => {
    const entities = await loadHaEntities(again);
    plug.fill(entities);
    sensor.fill(entities);
  };
  fill(false);
  const suggest = el("button", { type: "button", class: "btn", onclick: async (e) => {
    const button = e.currentTarget;
    button.classList.add("busy");
    await fill(true);
    button.classList.remove("busy");
    if (!haEntities) toast(t("ha_entities_failed"), "error");
  } }, t("ha_entities_refresh"));
  const save = el("button", { type: "button", class: "btn primary", "data-power-save": "", onclick: (e) => action("power_settings",
    { switch: plug.value, sensor: sensor.value, off_watts: Number(watts.value) || 5 }, e.currentTarget) }, t("power_save"));
  const kind = state.machine?.machine;
  const off = el("button", { type: "button", class: "btn danger", "data-power-off": "",
    disabled: !state.machine || ["stopping", "unknown", "checking", "rejected", "off"].includes(kind),
    onclick: (e) => switchMachineOff(e.currentTarget) }, t("power_off"));
  return card(t("power_title"), null,
    el("p", { class: "hint" }, t("power_hint")),
    state.machine ? el("p", { class: "machine-now" }, machineLabel()) : null,
    el("div", { class: "form-grid" }, field(t("power_switch"), plug, t("power_switch_hint")), field(t("power_sensor"), sensor),
      field(t("power_watts"), watts, t("power_watts_hint"))),
    el("div", { class: "voice-repo-row" }, suggest, save, off),
    el("p", { class: "hint" }, t("side_power_off_hint", { seconds: state.studio?.power_off_delay ?? 120 })));
}

// --- the Hugging Face token: on this machine (~/.cache/huggingface/token), only whether it is set comes back ---

export function renderHfToken() {
  const saved = state.training.hf_token;
  const value = el("input", { type: "password", autocomplete: "off", placeholder: saved ? t("hf_token_replace") : "hf_…",
    "data-hf-token": "" });
  const send = async (token, button) => {
    button.classList.add("busy");
    try {
      await call("action", { action: "hf_token", token });
      value.value = "";
      toast(t(token ? "hf_token_saved" : "hf_token_removed"));
      await refresh();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      button.classList.remove("busy");
    }
    redraw();
  };
  return card(t("n_hf"), "machine",
    el("div", { class: "row-action" },
      el("div", {}, el("strong", {}, t("machine_check")), el("p", { class: "hint" }, t("machine_check_hint"))),
      el("button", { type: "button", class: "btn", "data-check": "", onclick: (e) => action("check", {}, e.currentTarget)
        .then((answer) => { if (answer) select("jobs"); }) }, t("check"))),
    el("h4", { class: "rec-heading" }, t("hf_token")),
    el("p", { class: "hint" }, t("hf_token_hint")),
    saved === null || saved === undefined ? null
      : el("p", { class: `hf-status ${saved ? "ok" : ""}` }, saved ? `✓ ${t("hf_token_set")}` : t("hf_token_not_set")),
    el("div", { class: "voice-repo-row" }, value,
      el("button", { type: "button", class: "btn primary", "data-hf-save": "", onclick: (e) => {
        const token = value.value.trim();
        if (!token) return toast(t("hf_token_empty"), "error");
        send(token, e.currentTarget);
        return undefined;
      } }, t("hf_token_save")),
      saved ? el("button", { type: "button", class: "btn danger", onclick: async (e) => {
        const button = e.currentTarget;
        if (await ask(t("hf_token_confirm_remove"), { danger: true })) send("", button);
      } }, t("hf_token_remove")) : null));
}

// --- the login (docker/config/env) -------------------------------------------------------------------------

export function renderAccount() {
  return card(t("n_account"), null,
    el("p", {}, t("logged_in", { user: state.studio?.user || "?" })),
    el("p", { class: "hint" }, t("account_intro")),
    el("p", { class: "hint" }, t("account_change")),
    el("p", { class: "hint" }, el("code", {}, t("account_show"))),
    el("div", { class: "voice-repo-row" }, el("button", { type: "button", class: "btn", "data-logout": "", onclick: async () => {
      await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      location.assign("/login");
    } }, t("logout"))));
}

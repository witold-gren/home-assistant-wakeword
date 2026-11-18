// The tree on the left: groups of nodes built from the draft and the state, with counts and warnings. Pure functions.

/** Node keys that are not parts of household.yaml but views of the studio. */
export const VIEWS = ["overview", "jobs", "people", "words", "devices", "recordings", "background", "piper", "elevenlabs",
  "samples", "train-data", "train-run", "train-live", "models", "export", "false-wakes", "targets", "ha", "power", "hf",
  "account"];

const PERSON_ICON = { adult: "mdi:account", child: "mdi:human-child" };

/** The words of a person that still miss takes ("ola 3/18"). */
function missingTakes(person, draft, household) {
  const goal = person.group === "child" ? draft.targets?.child : draft.targets?.adult;
  return Object.entries(draft.words || {})
    .filter(([, w]) => w.speakers === "all" || (w.speakers || []).includes(person.id))
    .map(([wid, w]) => [w.wake_word || wid, household?.counts?.[wid]?.[person.id] ?? 0, goal])
    .filter(([, done, target]) => done < target)
    .map(([name, done, target]) => `${name} ${done}/${target}`);
}

export function buildOutline({ draft, state, household, t }) {
  if (!draft || !state) return [];
  const people = draft.speakers || [];
  const words = Object.entries(draft.words || {});
  const devices = Object.entries(draft.devices || {});
  const esphome = new Set((household?.esphome || []).map((d) => d.name));
  const takes = (wid) => Object.values(household?.counts?.[wid] || {}).reduce((sum, n) => sum + n, 0);
  const prepared = state.words.filter((w) => w.prepared);
  const node = (key, icon, label, extra = {}) => ({ key, icon, label, children: [], ...extra });
  return [
    { key: "g:overview", label: t("g_overview"), children: [
      node("overview", "mdi:view-dashboard-outline", t("n_overview")),
      node("jobs", "mdi:console", t("n_jobs"), { busy: Boolean(state.job?.running) }),
    ] },
    { key: "g:family", label: t("g_family"), children: [
      node("people", "mdi:account-group", t("n_people"), { count: people.length,
        children: people.map((p) => {
          const missing = missingTakes(p, draft, household);
          return node(`person/${p.id}`, PERSON_ICON[p.group] || PERSON_ICON.adult, p.id,
            { warn: missing.length ? t("warn_takes", { words: missing.join(", ") }) : null });
        }) }),
      node("words", "mdi:text-recognition", t("n_words"), { count: words.length,
        children: words.map(([wid, w]) => {
          const noSpelling = !Object.values(w.spellings || {}).some((list) => list.length);
          const nobody = Array.isArray(w.speakers) && !w.speakers.length;
          return node(`word/${wid}`, "mdi:microphone-message", w.wake_word || wid, {
            hint: wid, warn: noSpelling ? t("warn_spellings") : nobody ? t("warn_no_people") : null });
        }) }),
      node("devices", "mdi:speaker-wireless", t("n_devices"), { count: devices.length,
        warn: esphome.size && devices.some(([name]) => !esphome.has(name)) ? t("warn_device") : null }),
    ] },
    { key: "g:recordings", label: t("g_recordings"), children: [
      node("recordings", "mdi:waveform", t("n_recordings"), { count: words.reduce((sum, [wid]) => sum + takes(wid), 0),
        children: words.map(([wid, w]) => node(`rec/${wid}`, "mdi:folder-music-outline", w.wake_word || wid, { count: takes(wid) })) }),
      node("background", "mdi:home-sound-in-outline", t("n_background")),
    ] },
    { key: "g:voices", label: t("g_voices"), children: [
      node("piper", "mdi:account-voice", t("n_piper")),
      node("elevenlabs", "mdi:waveform", t("n_elevenlabs"), { count: (draft.elevenlabs?.voices || []).length }),
      node("samples", "mdi:playlist-play", t("n_samples")),
    ] },
    { key: "g:training", label: t("g_training"), children: [
      node("train-data", "mdi:database-cog-outline", t("n_train_data")),
      node("train-run", "mdi:tune-variant", t("n_train_run")),
      node("train-live", "mdi:chart-line", t("n_train_live"), { busy: Boolean(state.training.running) }),
      node("models", "mdi:brain", t("n_models"), { count: state.words.filter((w) => w.trained).length,
        children: prepared.map((w) => node(`models/${w.id}`, "mdi:cube-outline", w.wake_word)) }),
      node("export", "mdi:export-variant", t("n_export")),
    ] },
    { key: "g:home", label: t("g_home"), children: [
      node("false-wakes", "mdi:bell-alert-outline", t("n_false_wakes")),
    ] },
    { key: "g:settings", label: t("g_settings"), children: [
      node("targets", "mdi:target", t("n_targets")),
      node("ha", "mdi:home-assistant", t("n_ha"), { warn: state.home_assistant?.rejected ? t("ha_token_rejected") : null }),
      node("power", "mdi:power", t("n_power")),
      node("hf", "mdi:key-outline", t("n_hf")),
      node("account", "mdi:account-key-outline", t("n_account")),
      node("look", "mdi:palette-outline", t("n_look")),
    ] },
  ];
}

/** Every node of a list (and their children), in order. */
export function flattenOutline(items) {
  return items.flatMap((item) => [item, ...flattenOutline(item.children || [])]);
}

/** Only the nodes whose label (or a child's) has the text; groups without any are left out. */
export function filterOutline(groups, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return groups;
  const keep = (item) => {
    const children = (item.children || []).map(keep).filter(Boolean);
    const own = `${item.label} ${item.hint || ""}`.toLowerCase().includes(needle);
    return own || children.length ? { ...item, children: own ? item.children : children } : null;
  };
  return groups.map((group) => ({ ...group, children: group.children.map(keep).filter(Boolean) }))
    .filter((group) => group.children.length);
}

/** The node a key names, or null. */
export function findNode(groups, key) {
  return flattenOutline(groups.flatMap((group) => group.children)).find((item) => item.key === key) ?? null;
}

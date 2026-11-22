// Synthetic voices: Piper voices per language (household.yaml `voices`) and ElevenLabs (household.yaml
// `elevenlabs`, the key in ~/.config/wakeword). Taken over from the training panel (renderVoices, renderElevenLabs).

import {
  action, ask, call, card, choice, draft, el, field, household, input, isDirty, langLabel, redraw, refresh, renderFamily,
  selectedWords, state, t, toast,
} from "./common.js";
import { loadRecordings, playUrl, recordingsLoaded, voiceLanguage } from "./recordings.js";

// --- Piper voices --------------------------------------------------------------------------------------

let hfRepo = "";
const loadedVoices = new Set(); // read from Hugging Face repositories in this session

function chosenVoices(lang) {
  const voices = draft.voices || {};
  return lang in voices ? voices[lang] : [...(household.default_voices?.[lang] || [])];
}

export function renderVoices() {
  const defaults = household.default_voices || {};
  const languages = [...new Set([...Object.values(draft.words).flatMap((w) => Object.keys(w.spellings || {})),
    ...Object.keys(draft.voices || {})])].sort();
  const rows = languages.map((lang) => {
    const chosen = chosenVoices(lang);
    const candidates = [...new Set([...chosen, ...(defaults[lang] || []),
      ...[...loadedVoices].filter((v) => voiceLanguage(v) === lang)])];
    const chips = candidates.map((voice) => {
      const box = el("input", { type: "checkbox", "data-voice": voice });
      box.checked = chosen.includes(voice);
      box.addEventListener("change", () => {
        const now = new Set(chosenVoices(lang));
        if (box.checked) now.add(voice);
        else now.delete(voice);
        draft.voices = { ...(draft.voices || {}), [lang]: candidates.filter((v) => now.has(v)) };
        renderFamily();
      });
      const repo = voice.includes("/") ? voice.split("/").slice(0, 2).join("/") : "";
      return el("label", { class: "chip" }, box,
        el("span", {}, voice.split("/").pop(), el("small", {}, repo || t("voice_default"))));
    });
    const custom = lang in (draft.voices || {});
    return el("div", { class: "voice-lang", "data-voice-lang": lang },
      el("div", { class: "voice-lang-head" }, el("strong", {}, langLabel(lang)),
        el("span", { class: "rec-meta" }, t("voices_chosen", { count: chosen.length })),
        custom ? el("button", { type: "button", class: "link-btn", onclick: () => {
          const { [lang]: _, ...rest } = draft.voices;
          draft.voices = rest;
          renderFamily();
        } }, t("voices_reset")) : null),
      el("div", { class: "chips" }, chips),
      chosen.length ? null : el("p", { class: "hint warn" }, t(lang === "en" ? "voices_none_en" : "voices_none")));
  });
  const repo = el("input", { value: hfRepo, placeholder: "WitoldG/polish_piper_models", "data-hf-repo": "" });
  repo.addEventListener("input", () => { hfRepo = repo.value; }); // not part of household.yaml
  const load = el("button", { type: "button", class: "btn", "data-hf-load": "", onclick: async (e) => {
    e.target.classList.add("busy");
    try {
      const { voices } = await call("hf_voices", { repo: repo.value });
      const next = { ...(draft.voices || {}) };
      for (const voice of voices) {
        loadedVoices.add(voice);
        const lang = voiceLanguage(voice);
        const current = lang in next ? [...next[lang]] : [...(defaults[lang] || [])];
        if (!current.includes(voice)) current.push(voice);
        next[lang] = current;
      }
      draft.voices = next;
      toast(t("voices_loaded", { count: voices.length }), "ok");
      renderFamily();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      e.target.classList.remove("busy");
    }
  } }, t("voices_load"));
  return card(t("voices_title"), null,
    el("p", { class: "hint" }, t("voices_hint")),
    ...rows,
    el("div", { class: "field voice-repo" }, el("span", {}, t("voices_repo")),
      el("div", { class: "voice-repo-row" }, repo, load), el("p", { class: "hint" }, t("voices_repo_hint"))));
}

// --- ElevenLabs: voices of a language, a test take, the chosen voices ---------------------------------

const EL_PAGE = 60;
const eleven = { language: null, word: null, voices: null, loading: false, search: "", gender: "", shown: EL_PAGE,
  error: "", speaks: "speaks", usable: true, cardErrors: {} };

// the free plan speaks only with the account's premade, cloned and generated voices
const elFree = () => state.elevenlabs_account?.tier === "free";
const elNeedsPaid = (voice) => elFree() && voice.category !== undefined
  && !(state.elevenlabs_free || []).includes(voice.category);
// refused by ElevenLabs while generating or testing: out of the list, shown apart
const elBrokenAll = () => state.elevenlabs_account?.broken || {};
const elBroken = (voice) => elBrokenAll()[voice.id]?.reason;

function elFits(voice) {
  if (elBroken(voice)) return false;
  if (eleven.usable && elNeedsPaid(voice)) return false;
  if (eleven.speaks === "native") return voice.native === eleven.language;
  if (eleven.speaks === "speaks") return voice.speaks !== false;
  return true;
}

function elLanguageBadge(voice) {
  const lang = eleven.language.toUpperCase();
  if (!voice.native) return null; // listed before the language was kept: sync again
  if (voice.native === eleven.language) return el("span", { class: "badge good" }, t("el_native", { lang }));
  if (voice.speaks) {
    return el("span", { class: "badge", title: t("el_verified_hint", { lang }) }, `${voice.native.toUpperCase()} → ${lang}`);
  }
  return el("span", { class: "badge bad", title: t("el_not_verified_hint", { lang }) },
    t("el_not_verified", { native: voice.native.toUpperCase(), lang }));
}

const elSettings = () => draft.elevenlabs; // filled with the defaults when the household is loaded

function elLanguages() {
  return [...new Set(Object.values(draft.words).flatMap((w) => Object.keys(w.spellings || {})))].sort();
}

async function elLoadVoices(sync, button) {
  eleven.loading = true;
  button?.classList.add("busy");
  try {
    const answer = await call("elevenlabs/voices", { language: eleven.language, sync });
    eleven.voices = answer.voices;
    eleven.shown = EL_PAGE;
    eleven.error = "";
    if (sync) toast(t("el_synced", { count: answer.voices.length }), "ok");
  } catch (err) {
    // stays in the view (a toast is easy to miss); a missing permission says which one to tick
    eleven.error = err.message;
    toast(err.message, "error");
    eleven.voices = eleven.voices || [];
  } finally {
    eleven.loading = false;
    button?.classList.remove("busy");
  }
  redraw();
}

async function elTest(voice, button) {
  // the first spelling of the word in this voice, generated now (costs a few characters)
  button.classList.add("busy");
  try {
    const query = new URLSearchParams({ voice: voice.id, word: eleven.word, language: eleven.language, model: elSettings().model });
    const response = await fetch(`/api/elevenlabs/test?${query}`);
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || response.statusText);
    playUrl(URL.createObjectURL(await response.blob()));
    delete eleven.cardErrors[voice.id];
  } catch (err) {
    // stays on the card; a 402 teaches the studio the plan (state.elevenlabs_account)
    eleven.cardErrors[voice.id] = err.message;
    toast(err.message, "error");
    await refresh();
  } finally {
    button.classList.remove("busy");
  }
  redraw();
}

function elPreview(voice, button) {
  if (!voice.preview) return toast(t("el_no_preview"));
  playUrl(voice.preview).catch((err) => toast(err.message, "error"));
  button.blur();
  return undefined;
}

function elVoiceCard(voice, chosen) {
  const settings = elSettings();
  const box = el("input", { type: "checkbox", "data-el-voice": voice.id });
  box.checked = chosen;
  box.addEventListener("change", () => {
    const others = settings.voices.filter((v) => !(v.id === voice.id && v.language === eleven.language));
    settings.voices = box.checked
      ? [...others, { id: voice.id, name: voice.name, language: eleven.language, owner: voice.owner || "" }]
      : others;
    renderFamily();
  });
  const meta = [voice.gender, voice.age, voice.accent].filter(Boolean).join(" · ");
  return el("div", { class: `el-voice${chosen ? " on" : ""}` },
    el("label", { class: "el-use" }, box, el("strong", {}, voice.name)),
    el("div", { class: "el-badges" }, elLanguageBadge(voice),
      el("span", { class: "badge" }, t(voice.source === "own" ? "el_own" : "el_library")),
      elNeedsPaid(voice) ? el("span", { class: "badge bad", title: t("el_paid_hint") }, t("el_paid")) : null),
    meta ? el("span", { class: "rec-meta" }, meta) : null,
    voice.description ? el("p", { class: "hint" }, voice.description) : null,
    el("div", { class: "el-actions" },
      el("button", { type: "button", class: "btn small", onclick: (e) => elPreview(voice, e.currentTarget) }, `▶ ${t("el_preview")}`),
      el("button", { type: "button", class: "btn small primary", disabled: !eleven.word || !state.elevenlabs_key,
        title: t("el_test_hint"), onclick: (e) => elTest(voice, e.currentTarget) }, `🗣 ${t("el_test")}`),
      voice.source === "library" && !voice.added ? el("button", { type: "button", class: "link-btn", onclick: async (e) => {
        if (!(await ask(t("el_add_confirm", { name: voice.name }), { ok: t("el_add_ok") }))) return;
        const done = await action("elevenlabs_add", { voice: voice.id, language: eleven.language }, e.target);
        if (done) elLoadVoices(true);
      } }, t("el_add")) : null),
    eleven.cardErrors[voice.id] ? el("p", { class: "hint warn" }, eleven.cardErrors[voice.id]) : null);
}

// how many chosen voices really have takes (refused ones are skipped), from the takes on disk
function elMadeCount(words, settings) {
  const recordings = recordingsLoaded();
  if (!recordings) {
    loadRecordings();
    return null;
  }
  const groups = (recordings.elevenlabs || []).filter((g) => words.includes(g.word));
  const made = new Set(groups.map((g) => g.group.replace(/_\d+$/, "").match(/-([A-Za-z0-9]{8})$/)?.[1]));
  const chosen = settings.voices.filter((v) => !elBroken(v));
  const withTakes = chosen.filter((v) => made.has(v.id.slice(0, 8))).length;
  const takes = groups.reduce((sum, g) => sum + g.files.length, 0);
  return el("p", { class: "el-made" }, t("el_made_count", { made: withTakes, chosen: chosen.length,
    skipped: settings.voices.length - chosen.length, takes }));
}

// voices ElevenLabs refused: kept apart so they do not get in the way when choosing voices again
function elUnavailable() {
  const broken = Object.entries(elBrokenAll());
  if (!broken.length) return null;
  return el("details", { class: "rec-group el-unavailable" },
    el("summary", {}, el("strong", {}, t("el_unavailable_title", { count: broken.length }))),
    el("div", { class: "el-review-body" },
      el("p", { class: "hint" }, t("el_unavailable_hint")),
      ...broken.map(([id, info]) => el("div", { class: "el-unavailable-row" },
        el("strong", {}, info.name || id),
        el("span", { class: "rec-meta" }, info.reason),
        el("button", { type: "button", class: "btn small", onclick: async (e) => {
          await action("elevenlabs_restore", { voice: id }, e.currentTarget);
          redraw();
        } }, t("el_restore"))))));
}

export function renderElevenLabs() {
  const settings = elSettings();
  const languages = elLanguages();
  if (!languages.includes(eleven.language)) eleven.language = languages.includes("pl") ? "pl" : languages[0] || "pl";
  const words = Object.entries(draft.words).filter(([, w]) => (w.spellings?.[eleven.language] || []).length);
  if (!words.some(([id]) => id === eleven.word)) {
    eleven.word = (words.find(([id]) => selectedWords.has(id)) || words[0] || [null])[0];
  }
  if (eleven.voices === null && !eleven.loading) elLoadVoices(false);

  // the key: straight to ~/.config/wakeword on the training machine, never shown again
  const key = el("input", { type: "password", placeholder: state.elevenlabs_key ? t("el_key_replace") : "sk_…",
    autocomplete: "off", spellcheck: "false", "data-el-key": "" });
  const keyBlock = el("div", { class: "field" }, el("span", {}, t("el_key")),
    el("div", { class: "voice-repo-row" }, key,
      el("button", { type: "button", class: "btn", onclick: async (e) => {
        if (!key.value.trim()) return toast(t("el_key_empty"), "error");
        await action("elevenlabs_key", { key: key.value }, e.target);
        key.value = "";
        redraw();
        return undefined;
      } }, t("el_key_save")),
      state.elevenlabs_key ? el("button", { type: "button", class: "link-btn", onclick: async (e) => {
        if (await ask(t("el_key_remove_confirm"), { ok: t("remove"), danger: true })) {
          await action("elevenlabs_key", { key: "" }, e.target);
          redraw();
        }
      } }, t("el_key_remove")) : null),
    el("p", { class: state.elevenlabs_key ? "hf-status" : "hint" }, t(state.elevenlabs_key ? "el_key_set" : "el_key_hint")));

  const languageSelect = choice(languages.map((l) => [l, l.toUpperCase()]), eleven.language, (v) => {
    eleven.language = v;
    eleven.voices = null;
    redraw();
  });
  const wordSelect = choice(words.map(([id, w]) => [id, w.wake_word]), eleven.word, (v) => { eleven.word = v; redraw(); });
  const model = choice(household.elevenlabs_models.map((m) => [m, m]), settings.model, (v) => { settings.model = v; });
  const count = input(settings.count, (v) => { settings.count = Math.max(1, Math.min(50, Number(v) || 1)); },
    { type: "number", min: 1, max: 50 });
  const spellings = draft.words[eleven.word]?.spellings?.[eleven.language] || [];

  const chosenIds = new Set(settings.voices.filter((v) => v.language === eleven.language).map((v) => v.id));
  const all = eleven.voices || [];
  const matches = () => {
    const needle = eleven.search.toLowerCase();
    return all.filter((v) => elFits(v) && (!eleven.gender || v.gender === eleven.gender)
      && (!needle || `${v.name} ${v.description} ${v.accent}`.toLowerCase().includes(needle)))
      // the chosen ones first, then the list as ElevenLabs sorts it
      .sort((a, b) => Number(chosenIds.has(b.id)) - Number(chosenIds.has(a.id)));
  };
  const filtered = matches();
  const search = el("input", { value: eleven.search, placeholder: t("el_search") });
  const gender = choice([["", t("el_any_gender")], ["female", t("el_female")], ["male", t("el_male")], ["neutral", t("el_neutral")]],
    eleven.gender, (v) => { eleven.gender = v; eleven.shown = EL_PAGE; redraw(); });

  // what "Generate" makes for the words chosen for training (or all words)
  const targets = Object.keys(draft.words).filter((id) => selectedWords.has(id));
  const generateWords = targets.length ? targets : Object.keys(draft.words);
  let takes = 0;
  let characters = 0;
  for (const id of generateWords) {
    for (const voice of settings.voices.filter((v) => !elBroken(v))) { // skipped by "Generate takes"
      for (const text of draft.words[id].spellings?.[voice.language] || []) {
        takes += settings.count;
        characters += text.length * settings.count;
      }
    }
  }
  const known = new Map(all.map((v) => [v.id, v]));
  const blocked = settings.voices.filter((v) => known.has(v.id) && elNeedsPaid(known.get(v.id)));
  const broken = settings.voices.filter(elBroken);
  const generate = el("button", { type: "button", class: "btn primary", "data-el-generate": "",
    disabled: !settings.voices.length || !state.elevenlabs_key || blocked.length > 0,
    onclick: async (e) => {
      if (isDirty()) return toast(t("save_first"), "error");
      if (!(await ask(t("el_generate_confirm", { takes, characters }), { ok: t("el_generate") }))) return undefined;
      action("elevenlabs_generate", { words: generateWords }, e.target);
      return undefined;
    } }, t("el_generate"));

  const list = el("div", { class: "el-voices", id: "el-voices" });
  function renderList() {
    const rows = matches();
    const more = rows.length > eleven.shown ? [el("button", { type: "button", class: "btn", onclick: () => {
      eleven.shown += EL_PAGE;
      renderList();
    } }, t("el_more", { count: rows.length - eleven.shown }))] : [];
    list.replaceChildren(...rows.slice(0, eleven.shown).map((v) => elVoiceCard(v, chosenIds.has(v.id))), ...more);
  }
  search.addEventListener("input", () => { eleven.search = search.value; eleven.shown = EL_PAGE; renderList(); });
  renderList();

  return card("ElevenLabs", null,
    el("p", { class: "hint" }, t("el_intro")),
    keyBlock,
    el("div", { class: "settings-grid" },
      field(t("el_language"), languageSelect, t("el_language_hint")),
      field(t("el_word"), wordSelect, spellings.length ? `${t("el_reads")}: ${spellings.join(" · ")}` : t("el_no_spelling")),
      field(t("el_model"), model, t("el_model_hint")),
      field(t("el_count"), count, t("el_count_hint", { variants: household.elevenlabs_variants }))),
    el("div", { class: "el-toolbar" },
      el("button", { type: "button", class: "btn primary", disabled: !state.elevenlabs_key, "data-el-sync": "",
        onclick: (e) => elLoadVoices(true, e.currentTarget) }, t("el_sync")),
      search, gender,
      choice([["speaks", t("el_speaks_filter", { lang: eleven.language.toUpperCase() })],
        ["native", t("el_native_filter", { lang: eleven.language.toUpperCase() })], ["all", t("el_all_filter")]],
      eleven.speaks, (v) => { eleven.speaks = v; eleven.shown = EL_PAGE; redraw(); }),
      elFree() ? (() => {
        const usable = el("input", { type: "checkbox" });
        usable.checked = eleven.usable;
        usable.addEventListener("change", () => { eleven.usable = usable.checked; eleven.shown = EL_PAGE; redraw(); });
        return el("label", { class: "check" }, usable, el("span", {}, t("el_usable_filter")));
      })() : null,
      el("span", { class: "rec-meta" }, eleven.loading ? t("loading")
        : t("el_voices_count", { count: filtered.length, all: all.length, chosen: chosenIds.size })),
      // many voices at once: everything the filters show (e.g. all native speakers usable on the plan)
      el("button", { type: "button", class: "btn small", disabled: !filtered.length, onclick: () => {
        const others = settings.voices.filter((v) => v.language !== eleven.language);
        const kept = settings.voices.filter((v) => v.language === eleven.language);
        const ids = new Set(kept.map((v) => v.id));
        const added = filtered.filter((v) => !ids.has(v.id))
          .map((v) => ({ id: v.id, name: v.name, language: eleven.language, owner: v.owner || "" }));
        settings.voices = [...others, ...kept, ...added];
        toast(t("el_selected", { count: added.length }), "ok");
        renderFamily();
      } }, t("el_select_shown", { count: filtered.length })),
      el("button", { type: "button", class: "btn small", disabled: !chosenIds.size, onclick: () => {
        settings.voices = settings.voices.filter((v) => v.language !== eleven.language);
        renderFamily();
      } }, t("el_unselect_all"))),
    elFree() ? el("div", { class: "callout" }, el("strong", {}, t("el_free_title")), el("p", {}, t("el_free_hint", {
      count: all.filter((v) => !elNeedsPaid(v)).length }))) : null,
    eleven.error ? el("div", { class: "callout bad" }, el("strong", {}, eleven.error),
      /permission/i.test(eleven.error) ? el("p", {}, t("el_permission_hint")) : null) : null,
    all.length ? list : el("p", { class: "hint" }, t(state.elevenlabs_key ? "el_none" : "el_key_first")),
    el("div", { class: "el-generate" },
      el("div", {}, el("strong", {}, t("el_generate")),
        el("p", { class: "hint" }, t("el_generate_hint", { voices: settings.voices.length, takes, characters,
          words: generateWords.map((id) => draft.words[id].wake_word).join(", ") })),
        blocked.length ? el("p", { class: "hint warn" }, t("el_blocked", { names: blocked.map((v) => v.name).join(", ") })) : null,
        elMadeCount(generateWords, settings),
        broken.length ? el("p", { class: "hint warn el-broken" }, t("el_broken_chosen", { count: broken.length,
          names: broken.map((v) => v.name).join(", ") }), " ",
        el("button", { type: "button", class: "link-btn", onclick: () => {
          settings.voices = settings.voices.filter((v) => !elBroken(v));
          renderFamily();
        } }, t("el_untick_broken"))) : null),
      generate),
    elUnavailable());
}

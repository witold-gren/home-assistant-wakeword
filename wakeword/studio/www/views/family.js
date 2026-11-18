// Household: people, words, devices and the targets of recordings - the draft of household.yaml.
// Taken over from the training panel's card 1 (renderPeople, renderWord, renderDevices, renderSettings).

import {
  ID_RE, action, ask, call, card, choice, draft, dragHandle, el, field, household, input, isDirty, langLabel, markDirty,
  moveItem, refresh, renderFamily, select, selectedWords, saveSelectedWords, slug, sortable, splitList, t, toast,
} from "./common.js";

function speakerWords(id) {
  return Object.entries(draft.words).filter(([, w]) => w.speakers === "all" || w.speakers.includes(id));
}

const target = (group) => (group === "child" ? draft.targets.child : draft.targets.adult);

function personCard(person, index) {
  const seg = el("div", { class: "mini-seg" }, ...["adult", "child"].map((group) =>
    el("button", { type: "button", class: person.group === group ? "on" : "", "data-group": group,
      onclick: () => { person.group = group; renderFamily(); } }, t(group))));
  const words = speakerWords(person.id);
  const counts = words.length ? words.map(([wid, w]) => {
    const done = household.counts?.[wid]?.[person.id] ?? 0;
    const goal = target(person.group);
    return el("span", { class: `count ${done >= goal ? "done" : done ? "part" : ""}` }, `${w.wake_word} ${done}/${goal}`);
  }) : [el("span", { class: "count" }, t("no_words_yet"))];
  return el("div", { class: "person", "data-person": person.id },
    el("div", { class: "person-head" }, dragHandle(),
      el("div", { class: `avatar ${person.group}` }, person.id.slice(0, 1)),
      el("strong", { class: "person-name", onclick: () => select(`person/${person.id}`) }, person.id),
      el("button", { type: "button", class: "icon-btn", title: t("remove"), "data-remove-person": person.id, onclick: async () => {
        if (!(await ask(t("confirm_remove_person", { name: person.id }), { danger: true }))) return;
        draft.speakers.splice(index, 1);
        for (const w of Object.values(draft.words)) if (w.speakers !== "all") w.speakers = w.speakers.filter((s) => s !== person.id);
        renderFamily();
      } }, "✕")),
    seg, el("div", { class: "counts" }, ...counts));
}

export function renderPeople(only = null) {
  const people = draft.speakers.map((person, index) => [person, index]).filter(([p]) => !only || p.id === only);
  const cards = people.map(([person, index]) => personCard(person, index));
  if (!only) {
    sortable(cards, (from, to) => {
      moveItem(draft.speakers, from, to);
      // each word lists its people in the same order as the household
      const order = draft.speakers.map((s) => s.id);
      for (const w of Object.values(draft.words)) {
        if (w.speakers !== "all") w.speakers = order.filter((id) => w.speakers.includes(id));
      }
    });
    const name = el("input", { placeholder: "ola", autocomplete: "off", "data-new-person": "" });
    let group = "adult";
    const seg = el("div", { class: "mini-seg" }, ...["adult", "child"].map((g) =>
      el("button", { type: "button", class: g === group ? "on" : "", onclick: (e) => {
        group = g;
        for (const b of seg.children) b.classList.toggle("on", b === e.target);
      } }, t(g))));
    const add = () => {
      const id = name.value.trim().toLowerCase();
      if (!ID_RE.test(id)) return toast(t("invalid_id"), "error");
      if (draft.speakers.some((s) => s.id === id)) return toast(t("duplicate_id"), "error");
      draft.speakers.push({ id, group });
      renderFamily();
      return undefined;
    };
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    cards.push(el("div", { class: "add-card" }, field(t("person_id"), name, t("person_hint")), seg,
      el("button", { type: "button", class: "btn primary", "data-add-person": "", onclick: add }, t("add_person"))));
  }
  return card(t("tab_people"), "household", el("div", { class: "people" }, ...cards));
}

function renderWord(wid, word) {
  const langs = household.languages;
  const everyone = el("input", { type: "checkbox", "data-everyone": "" });
  everyone.checked = word.speakers === "all";
  everyone.addEventListener("change", () => {
    word.speakers = everyone.checked ? "all" : draft.speakers.map((s) => s.id);
    renderFamily();
  });
  const pick = el("div", { class: "people-pick" }, ...draft.speakers.map((person) => {
    const box = el("input", { type: "checkbox", disabled: word.speakers === "all" });
    box.checked = word.speakers === "all" || word.speakers.includes(person.id);
    box.addEventListener("change", () => {
      const set = new Set(word.speakers === "all" ? [] : word.speakers);
      if (box.checked) set.add(person.id);
      else set.delete(person.id);
      word.speakers = draft.speakers.map((s) => s.id).filter((id) => set.has(id));
      markDirty();
    });
    return el("label", { class: "chip" }, box, el("span", {}, person.id));
  }));
  const rows = Object.entries(word.spellings).map(([lang, texts]) => {
    const area = el("textarea", { rows: 1, "data-spelling": lang });
    area.value = texts.join(", ");
    area.addEventListener("input", () => { word.spellings[lang] = splitList(area.value); markDirty(area); });
    return el("div", { class: "spelling-row" }, el("span", { class: "lang-tag", title: langLabel(lang) }, lang), area,
      el("button", { type: "button", class: "icon-btn", title: t("remove"),
        onclick: async () => {
          // its synthetic speech and ElevenLabs takes are trained on until the word is prepared again
          if (!(await ask(t("spelling_remove_confirm", { lang: langLabel(lang), word: word.wake_word }), { danger: true }))) return;
          delete word.spellings[lang];
          renderFamily();
        } }, "✕"));
  });
  const missing = langs.filter((l) => !(l in word.spellings));
  const addLang = choice([["", t("add_language")], ...missing.map((l) => [l, langLabel(l)])], "", (lang) => {
    if (lang) { word.spellings[lang] = []; renderFamily(); }
  });
  const alikes = el("textarea", { rows: 1, placeholder: t("sound_alikes_hint"), "data-sound-alikes": "" });
  alikes.value = (word.sound_alikes || []).join(", ");
  alikes.addEventListener("input", () => { word.sound_alikes = splitList(alikes.value); markDirty(alikes); });
  return el("div", { class: "word-card", "data-word": wid },
    el("div", { class: "word-title" }, dragHandle(),
      input(word.wake_word, (v) => { word.wake_word = v; }, { title: t("word_name_hint"), "aria-label": t("word_name"), "data-wake-word": "" }),
      el("button", { type: "button", class: "icon-btn", title: t("remove"), "data-remove-word": wid, onclick: async () => {
        if (!(await ask(t("confirm_remove_word", { name: word.wake_word }), { danger: true }))) return;
        delete draft.words[wid];
        for (const [device, slots] of Object.entries(draft.devices)) draft.devices[device] = slots.filter((w) => w !== wid);
        renderFamily();
      } }, "✕")),
    el("span", { class: "id" }, t("word_id", { id: wid }), " ",
      el("button", { type: "button", class: "link-btn", "data-rename": wid, onclick: () => renameWord(wid, word) }, t("rename_id"))),
    field(t("language"), choice(langs.map((l) => [l, l]), (word.trained_languages || [])[0] || langs[0],
      (v) => { word.trained_languages = [v]; })),
    el("div", {}, el("div", { class: "label" }, t("who_uses")),
      el("label", { class: "check" }, everyone, el("span", {}, t("everyone"))), pick),
    el("div", {}, el("div", { class: "label" }, t("spellings")), el("p", { class: "hint" }, t("spellings_hint")),
      ...rows, el("div", { class: "inline" }, addLang)),
    field(t("sound_alikes"), alikes));
}

export function renderWords(only = null) {
  const entries = Object.entries(draft.words).filter(([wid]) => !only || wid === only);
  const cards = entries.map(([wid, word]) => renderWord(wid, word));
  if (!only) {
    sortable(cards, (from, to) => {
      draft.words = Object.fromEntries(moveItem(Object.entries(draft.words), from, to));
    });
    const name = el("input", { placeholder: "Dżarwis", autocomplete: "off", "data-new-word": "" });
    const preview = el("span", { class: "id" }, "");
    name.addEventListener("input", () => { preview.textContent = name.value.trim() ? t("word_id", { id: slug(name.value) }) : ""; });
    const languages = household.languages;
    const language = choice(languages.map((l) => [l, l]), languages.includes(draft.ui_language) ? draft.ui_language : languages[0], () => {});
    const add = () => {
      const text = name.value.trim();
      if (!text) return undefined;
      const id = slug(text);
      if (draft.words[id] || household.stock_words.includes(id)) return toast(t("duplicate_id"), "error");
      draft.words[id] = { wake_word: text, trained_languages: [language.value], speakers: "all",
        spellings: { [language.value]: [text.toLowerCase()] }, sound_alikes: [] };
      renderFamily();
      return undefined;
    };
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    cards.push(el("div", { class: "add-card" }, field(t("word_name"), name, t("new_word_hint")), preview,
      field(t("language"), language), el("button", { type: "button", class: "btn primary", "data-add-word": "", onclick: add }, t("add_word"))));
  }
  return card(t("tab_words"), "household", el("div", { class: "words-grid" }, ...cards));
}

export function renderDevices() {
  const options = [["", "—"], ...Object.entries(draft.words).map(([wid, w]) => [wid, w.wake_word]),
    ...household.stock_words.map((w) => [w, w])];
  const rows = Object.entries(draft.devices).map(([device, slots]) => {
    let name = device;
    const nameInput = input(device, (v) => {
      const value = v.trim();
      if (!value || (value !== name && draft.devices[value])) return;
      const entries = Object.entries(draft.devices).map(([k, val]) => [k === name ? value : k, val]);
      draft.devices = Object.fromEntries(entries);
      name = value;
    });
    const slot = (i) => choice(options, slots[i] || "", (v) => {
      const current = draft.devices[name];
      current[i] = v;
      draft.devices[name] = current.filter((x, j) => x || j < 2).slice(0, 2);
    });
    const known = (household.esphome || []).find((d) => d.name === device);
    const where = known ? `${known.friendly_name} · ${known.file}` : t("device_not_found");
    return el("div", { class: "device-row", "data-device": device }, field(t("device_name"), nameInput, where),
      field(t("slot1"), slot(0)), field(t("slot2"), slot(1)),
      // an empty label: the button stands level with the fields
      field(" ", el("button", { type: "button", class: "icon-btn", title: t("remove"),
        onclick: () => { delete draft.devices[name]; renderFamily(); } }, "✕")));
  });
  const name = el("input", { placeholder: "salon-ha-voice", autocomplete: "off" });
  const add = (picked) => {
    const value = (picked || name.value).trim();
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(value)) return toast(t("device_hint"), "error");
    if (draft.devices[value]) return toast(t("duplicate_id"), "error");
    draft.devices[value] = [];
    renderFamily();
    return undefined;
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
  // voice devices found through Home Assistant (or the ESPHome folder), not added yet
  const found = (household.esphome || []).filter((d) => !draft.devices[d.name]);
  const picker = found.length ? field(t("device_pick"), choice([["", t("device_pick_placeholder")],
    ...found.map((d) => [d.name, `${d.friendly_name} (${d.name})`])], "", (v) => { if (v) add(v); }),
  t("device_pick_hint")) : null;
  return card(t("tab_devices"), "household", el("p", { class: "hint" }, t("devices_intro")),
    rows.length ? el("div", {}, ...rows) : el("p", { class: "hint" }, t("no_devices")),
    el("div", { class: "device-add" }, picker || el("span"),
      field(t(found.length ? "device_manual" : "device_name"), name, t("device_hint")),
      field(" ", el("button", { type: "button", class: "btn primary", "data-add-device": "", onclick: () => add() }, t("add_device")))));
}

async function renameWord(wid, word) {
  if (isDirty()) return toast(t("save_first"), "error");
  const answer = prompt(t("rename_prompt", { id: wid }), slug(word.wake_word));
  const value = (answer || "").trim();
  if (!value || value === wid) return undefined;
  if (!ID_RE.test(value)) return toast(t("invalid_id"), "error");
  const reply = await action("rename_word", { word: wid, new_id: value });
  if (!reply) return undefined;
  if (selectedWords.delete(wid)) { selectedWords.add(value); saveSelectedWords(); }
  toast(t("renamed", { id: value }), "ok");
  await refresh({ household: true });
  select(`word/${value}`);
  return undefined;
}

export function renderTargets() {
  const number = (key) => input(draft.targets[key], (v) => { draft.targets[key] = Number(v) || 0; },
    { type: "number", min: key === "held_out" ? 1 : 2, max: 100, "data-target": key });
  return card(t("n_targets"), "household",
    el("div", { class: "settings-grid" },
      field(t("target_adult"), number("adult"), t("target_hint")), field(t("target_child"), number("child"), t("target_hint")),
      field(t("target_held"), number("held_out"), t("target_held_hint")),
      field(t("recorder_language"), choice(household.ui_languages.map((l) => [l, l]), draft.ui_language,
        (v) => { draft.ui_language = v; }))));
}

export { call };

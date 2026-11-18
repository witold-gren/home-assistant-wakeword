# Cheat sheet: commands and household.yaml {#cheatsheet}

<div class="table"><table>
<tr><th>Command</th><th>What it does</th></tr>
<tr><td><code>init</code>, <code>add-speaker</code>, <code>add-word</code>, <code>set-device</code></td><td>create and change <code>household.yaml</code> (the previous version is kept as <code>.bak</code>)</td></tr>
<tr><td><code>record [--http]</code>, <code>make-cert</code></td><td>browser recorder</td></tr>
<tr><td><code>import &lt;word&gt; --speaker &lt;person&gt; files…</code></td><td>import audio files as takes</td></tr>
<tr><td><code>check</code></td><td>person × word matrix and issues</td></tr>
<tr><td><code>preview &lt;word&gt;</code></td><td>augmentation samples to listen to</td></tr>
<tr><td><code>split</code>, <code>expand</code>, <code>synthetic</code>, <code>config</code></td><td>preparation steps (individually)</td></tr>
<tr><td><code>prepare --all</code></td><td>all preparation steps at once</td></tr>
<tr><td><code>evaluate &lt;word&gt;</code></td><td>FRR per person, false wakes/h, cutoff</td></tr>
<tr><td><code>export --all</code></td><td>manifests and YAML snippets for devices</td></tr>
</table></div>
<p><code>wakeword &lt;command&gt; --help</code> shows all options.</p>

<pre><code>ui_language: pl
speakers:
  - id: tomek
    group: adult
  - id: kuba
    group: child
words:
  dzarwis:
    wake_word: Dżarwis
    trained_languages: [pl]
    speakers: all
    spellings:
      pl: [dżarwis, dżarwys]
      en: [jarvis]
    sound_alikes: [harwis, darwin]
targets:
  adult: 12
  child: 18
  held_out: 3
devices:
  salon-ha-voice: [dzarwis, okay_nabu]
# optional: synthesis voices (language missing = defaults, [] = no Piper voices)
voices:
  pl:
  - pl_PL-darkman-medium
  - WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium   # from Hugging Face: owner/repo/voice
  en: [en_US-lessac-medium]
# optional: ElevenLabs voices (studio: Synthetic voices → ElevenLabs; the API key only in ~/.config/wakeword)
elevenlabs:
  model: eleven_multilingual_v2
  count: 5                      # takes per spelling and voice
  voices:
  - {id: 21m00Tcm4TlvDq8ikWAM, name: Rachel, language: en, owner: ""}</code></pre>

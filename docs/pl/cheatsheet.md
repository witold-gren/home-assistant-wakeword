# Ściąga: polecenia i household.yaml {#cheatsheet}

<div class="table"><table>
<tr><th>Polecenie</th><th>Co robi</th></tr>
<tr><td><code>init</code>, <code>add-speaker</code>, <code>add-word</code>, <code>set-device</code></td><td>tworzą i zmieniają <code>household.yaml</code> (poprzednia wersja zostaje jako <code>.bak</code>)</td></tr>
<tr><td><code>record [--http]</code>, <code>make-cert</code></td><td>rejestrator w przeglądarce</td></tr>
<tr><td><code>import &lt;słowo&gt; --speaker &lt;osoba&gt; pliki…</code></td><td>import plików audio jako ujęć</td></tr>
<tr><td><code>check</code></td><td>macierz osoba × słowo i problemy</td></tr>
<tr><td><code>preview &lt;słowo&gt;</code></td><td>przykłady augmentacji do odsłuchu</td></tr>
<tr><td><code>split</code>, <code>expand</code>, <code>synthetic</code>, <code>config</code></td><td>kroki przygotowania (osobno)</td></tr>
<tr><td><code>prepare --all</code></td><td>wszystkie kroki przygotowania naraz</td></tr>
<tr><td><code>evaluate &lt;słowo&gt;</code></td><td>FRR na osobę, fałszywe wybudzenia/h, próg</td></tr>
<tr><td><code>export --all</code></td><td>manifesty i fragmenty YAML dla urządzeń</td></tr>
</table></div>
<p><code>wakeword &lt;polecenie&gt; --help</code> pokazuje wszystkie opcje.</p>

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
# opcjonalnie: głosy syntezy (brak języka = domyślne, [] = bez głosów Pipera)
voices:
  pl:
  - pl_PL-darkman-medium
  - WitoldG/polish_piper_models/pl_PL-meski_wg_glos-medium   # z Hugging Face: właściciel/repozytorium/głos
  en: [en_US-lessac-medium]
# opcjonalnie: głosy ElevenLabs (studio: Głosy syntetyczne → ElevenLabs; klucz API tylko w ~/.config/wakeword)
elevenlabs:
  model: eleven_multilingual_v2
  count: 5                      # nagrań na zapis i głos
  voices:
  - {id: 21m00Tcm4TlvDq8ikWAM, name: Rachel, language: pl, owner: ""}</code></pre>

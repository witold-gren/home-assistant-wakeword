# 10. Alternatywy {#alternatives}

[← Kolejne iteracje](09-iterating.md) · [Spis treści](index.md)

To narzędzie powstało, bo żadne z poniższych nie obsługiwało naraz **słów wspólnych dla kilku osób**,
**akcentu domowników** i **przypisania słów do urządzeń**. Każde ma jednak swoje zalety.

| Narzędzie | Co robi | Kiedy warto | Ograniczenia |
|---|---|---|---|
| **Notatnik microWakeWord** (`notebooks/basic_training_notebook.ipynb`) | oficjalny przykład: synteza angielska → augmentacja → trening | jedno angielskie słowo, bez nagrań domowników | tylko syntetyczne angielskie głosy; brak oceny na osobach |
| **wakesmith** | kreator treningu microWakeWord | szybki model angielskiego słowa | angielskie głosy Piper i angielskie Common Voice; brak kontroli akcentu |
| **Trener TaterTotterson** (Docker) | trening microWakeWord w kontenerze, także na Apple Silicon, wielojęzyczne silniki TTS | trening bez osobnej maszyny z Linuksem | brak nagrań domowników i podziału na osoby; akcent zależy od TTS |
| **openWakeWord + custom verifier** | drugi etap weryfikacji „czy to ten mówca” na serwerze HA (min. 3 nagrania na osobę) | gdy model ogólny jest dobry, a chcesz ograniczyć wybudzenia do domowników | działa w Home Assistant (Wyoming), nie w samym Voice PE; inne modele niż microWakeWord |
| **Metoda SEED** | 5–9 nagrań rozmnożonych vocoderem WORLD | inspiracja dla `expand` | wymaga pyworld (nie buduje się łatwo na macOS) — tu zastąpione rozmnożeniem w numpy |

## Kiedy wybrać co innego {#when-to-choose-something-else}

- Chcesz tylko angielskiego „Hey Something” i nie zależy Ci na akcencie — notatnik microWakeWord lub
  wakesmith będą szybsze.
- Nie masz żadnej maszyny z NVIDIA i nie chcesz wynajmować chmury — trener TaterTotterson na Macu.
- Chcesz, by urządzenie reagowało **tylko** na domowników — model słowa wybudzającego tego nie
  zapewni; potrzebna jest weryfikacja mówcy (openWakeWord verifier albo rozpoznawanie mówcy po
  wybudzeniu, np. Speaker ID).

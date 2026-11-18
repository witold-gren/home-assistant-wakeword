# 02. Plan rodziny i wybór słów {#plan-your-household-and-choose-words}

[← Co przygotować](01-what-you-need.md) · [Spis treści](index.md) · [Dalej: nagrania →](03-recording.md)

Zanim ktokolwiek coś nagra, ustalcie razem **kto**, **jakie słowa** i **na których urządzeniach**.

## Przykład: rodzina z trojgiem dzieci {#example-a-family-with-three-children}

- **„Dżarwis”** — wspólne słowo całej rodziny, działa wszędzie,
- **„Optimus Prime”** — słowo syna w jego pokoju (tata też go nagrywa, bo bywa w pokoju syna),
- **„Wajana”** — słowo córek w ich pokoju (mama też),
- w salonie i sypialni zostaje drugie, gotowe słowo **„Okay Nabu”**.

```yaml
ui_language: pl

speakers:
  - id: dad
    group: adult
  - id: mum
    group: adult
  - id: son
    group: child
  - id: daughter1
    group: child
  - id: daughter2
    group: child

words:
  dzarwis:
    wake_word: Dżarwis
    trained_languages: [pl]
    speakers: all
    spellings:
      pl: [dżarwis, dżarwys, dżar wis]
      en: [jarvis, jar vis]
    sound_alikes: [harwis, dżem wiśniowy, jarmark, darwin]
  optimus_prime:
    wake_word: Optimus Prime
    trained_languages: [en]
    speakers: [son, dad]
    spellings:
      en: [optimus prime, optimus]
      pl: [optimus prajm, optimus prime]
    sound_alikes: [optimum price, optymista, oprime]
  wajana:
    wake_word: Wajana
    trained_languages: [pl]
    speakers: [daughter1, daughter2, mum]
    spellings:
      pl: [wajana, wajaana]
      en: [vaiana, vy ana]
    sound_alikes: [banana, tajana, wanna, jana]

targets:
  adult: 12
  child: 18
  held_out: 3

devices:
  living-room-voice: [dzarwis, okay_nabu]
  bedroom-voice: [dzarwis, okay_nabu]
  son-room-voice: [dzarwis, optimus_prime]
  daughters-room-voice: [dzarwis, wajana]
```

Ten plik jest w `households/examples/family/household.yaml`; drugi przykład — jedna osoba, jedno
słowo — w `households/examples/single/`.

## Pola pliku {#file-fields}

| Pole | Znaczenie |
|---|---|
| `ui_language` | język rejestratora (`pl`, `en`) |
| `speakers[].id` | identyfikator osoby: małe litery, cyfry, `_` (może być imię, np. `ola`) |
| `speakers[].group` | `adult` albo `child` — dzieci potrzebują więcej ujęć, a w ocenie liczymy je osobno |
| `words.<id>` | identyfikator słowa: małe litery, cyfry, `_`; staje się nazwą pliku modelu |
| `wake_word` | jak słowo wyświetla się w Home Assistant |
| `trained_languages` | język(i) wpisany do manifestu modelu |
| `speakers` | `all` (wszyscy, także osoby dodane później) albo lista osób |
| `spellings` | teksty dla syntezatora mowy, osobno dla każdego języka głosów — patrz niżej |
| `sound_alikes` | podobnie brzmiące słowa i frazy, które **nie** mają wybudzać (negatywy) |
| `targets` | ile ujęć na osobę na słowo (`adult`, `child`) i ile z nich odłożyć do testu (`held_out`) |
| `devices` | nazwa urządzenia ESPHome → maksymalnie **2** słowa; można używać gotowych: `okay_nabu`, `hey_jarvis`, `hey_mycroft`, `alexa` |

## Zapisy fonetyczne — skąd bierze się akcent {#phonetic-spellings-where-the-accent-comes-from}

Syntezator czyta tekst tak, jak czyta go **jego** język. Polski głos Pipera przeczyta „dżarwis”
tak, jak mówi Polak; angielski głos przeczyta „jarvis” po angielsku. Dlatego:

- w `spellings.pl` wpisz, **jak to słowo mówicie w domu**, polską pisownią (`dżarwis`, `optimus prajm`),
- w `spellings.en` (i innych językach) wpisz pisownię tego języka — dla różnorodności głosów,
- kilka wariantów pisowni (`dżarwis`, `dżarwys`, `dżar wis`) daje kilka wariantów wymowy.

## Jak wybrać dobre słowo {#how-to-choose-a-good-word}

1. **2–4 sylaby.** „Dżarwis” (2), „Wajana” (3), „Optimus Prime” (4). Jedna sylaba to za mało
   informacji, zdanie — za długo (model słucha maksymalnie ok. 1,5 s).
2. **Wyraźne, różne głoski**, najlepiej z spółgłoskami zwartymi (p, t, k, b, d, g) i „ż/dż/sz”.
3. **Nie słowo z codziennej mowy.** „Mama”, „okej”, „słuchaj” — będą fałszywe wybudzenia.
   Imię domownika też odpada.
4. **Słowa w jednym domu muszą się od siebie różnić.** „Wajana” i „Jana” na dwóch urządzeniach
   to proszenie się o pomyłki. Narzędzie i tak dodaje pozostałe słowa domu jako negatywy, ale
   podobieństwa brzmienia nie usunie.
5. **Test „brzmi podobnie”.** Powiedzcie słowo kilka razy i zapiszcie, z czym się kojarzy
   (np. „Dżarwis” → „darwin”, „harwis”, „jarmark”) — to są `sound_alikes`.
6. **Dzieci muszą umieć je wymówić.** Jeśli młodsze dziecko mówi „Optimus Plajm”, wpiszcie to też
   do `spellings.pl` — i nagrywajcie dokładnie tak, jak mówi.

## Urządzenia i dwa miejsca Voice PE {#devices-and-the-two-voice-pe-slots}

Voice PE ma **dwa miejsca na asystenta** („Wake word” i „Wake word 2” w Home Assistant). Każde ma
jedno słowo i może prowadzić do innego asystenta (np. inny język lub inny agent). Dlatego
`devices` przyjmuje maksymalnie dwa słowa na urządzenie. Nazwa urządzenia to nazwa ESPHome
(`name:` w YAML urządzenia), np. `pokoj-dziewczyn-voice`.

## Polecenia {#commands}

Zamiast pisać YAML ręcznie:

```bash
wakeword -H households/dom init --ui-language pl \
  --speaker dad --speaker mum --speaker son:child --speaker daughter1:child --speaker daughter2:child

wakeword -H households/dom add-word dzarwis "Dżarwis" --language pl \
  --spelling "pl=dżarwis,dżarwys,dżar wis" --spelling "en=jarvis,jar vis" \
  --sound-alike harwis --sound-alike darwin

wakeword -H households/dom add-word wajana "Wajana" --language pl \
  --speaker daughter1 --speaker daughter2 --speaker mum \
  --spelling "pl=wajana,wajaana" --spelling "en=vaiana" --sound-alike banana

wakeword -H households/dom set-device daughters-room-voice dzarwis wajana

# nowa osoba później (dopisana też do słowa wajana):
wakeword -H households/dom add-speaker ela --group child --word wajana
```

Każda zmiana jest sprawdzana (nieznane osoby, więcej niż 2 słowa na urządzeniu …), a poprzednia
wersja pliku zostaje w `household.yaml.bak`. Zamiast `-H …` możesz ustawić zmienną
`export WAKEWORD_HOUSEHOLD=households/dom` albo wejść do folderu rodziny.

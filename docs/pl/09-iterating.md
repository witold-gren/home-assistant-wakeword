# 09. Kolejne iteracje {#iterating}

[← Wdrożenie](08-deployment.md) · [Spis treści](index.md) · [Dalej: alternatywy →](10-alternatives.md)

Pierwszy model rzadko jest ostatnim. Plan na pierwszy tydzień:

## Tydzień obserwacji {#a-week-of-observation}

Zapisujcie (kartka na lodówce wystarczy):

- **przegapienia** — kto, w którym pokoju, jak powiedział,
- **fałszywe wybudzenia** — kiedy i co wtedy grało lub było mówione.

W Home Assistant każde wybudzenie widać w **Ustawienia → Asystenci głosowi → (asystent) →
Debugowanie**; przy włączonym zapisie audio można odsłuchać, co usłyszało urządzenie.

## Fałszywe wybudzenia → nowe negatywy {#false-wakes-new-negatives}

Ile ich jest, w którym pokoju i o której — pokazuje studio: **Dom → Fałszywe wybudzenia**
([11.8](11-studio.md#false-wakes)), także przed i po nowym modelu.

Najcenniejsze negatywy to dokładnie te dźwięki, które wybudziły urządzenie. Zapisz je (nagranie z
debugowania asystenta, fragment programu TV, nagranie telefonem tej samej sceny) jako WAV do:

```
households/dom/data/false_wakes/dzarwis/2026-11-03_reklama.wav
```

Przy następnym `config`/`prepare` pojawi się zbiór `false_wakes` z wysoką wagą.

## Przegapienia → więcej ujęć {#misses-more-takes}

Jeśli jedna osoba jest często przegapiana, dograj jej ujęcia — szczególnie w wariancie, w którym
zawodzi (z daleka? cicho? zmęczonym głosem?). Dzieci rosną: po kilku miesiącach dograjcie im
kilka ujęć.

## Ponowny trening {#retraining}

```bash
wakeword -H households/dom check
wakeword -H households/dom prepare dzarwis     # nowy split, expand, synthetic, config
# na maszynie GPU:
train/train.sh households/dom dzarwis
```

Synteza mowy i pobrane dane są już na maszynie GPU, więc powtórka trwa krócej. Cechy są
przeliczane tylko dla zbiorów, których pliki się zmieniły (np. `real` po dograniu ujęć,
`false_wakes` po dodaniu nagrań) — reszta jest brana z `data/build/<słowo>/features/`.

## Kiedy przestać {#when-to-stop}

Gdy przez tydzień: każdy domownik zwykle budzi urządzenie za pierwszym razem, a fałszywe wybudzenie
zdarza się rzadziej niż raz na kilka dni. Lepiej mieć trochę wyższy próg i czasem powtórzyć słowo
niż urządzenie, które samo się odzywa w nocy.

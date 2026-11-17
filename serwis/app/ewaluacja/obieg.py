"""Test pełnego obiegu: anonimizacja -> deanonimizacja na zestawie wzorcowym.

Uruchomienie w kontenerze:  python -m app.ewaluacja.obieg [--pokaz 03]

Sprawdza: (1) wycieki, czyli encje wzorcowe obecne dosłownie w tekście zanonimizowanym,
(2) czy tekst po deanonimizacji jest identyczny z oryginałem, (3) ile miejsc oznaczono jako niepewne."""
import argparse
import collections
import difflib
import time

import regex as re

from ..anonimizacja import silnik
from ..anonimizacja.sesja import Sesja
from ..detekcja import llm
from . import pamiec as pamiec_plik
from .scalanie import wykryj_z_cache
from .uruchom import WYNIKI
from .wzorce import wczytaj, wczytaj_zostaw


def _roznice(a: str, b: str) -> list[str]:
    out = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            # rozszerzenie do całych słów, żeby różnica była czytelna
            while i1 > 0 and a[i1 - 1].isalnum():
                i1 -= 1
                j1 -= 1
            while i2 < len(a) and a[i2].isalnum():
                i2 += 1
                j2 += 1
            out.append(f"„{a[i1:i2]}” -> „{b[max(j1, 0):j2]}”  (…{a[max(0, i1 - 25):i1].replace(chr(10), ' ')}…)")
    return list(dict.fromkeys(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=llm.LLM_MODEL)
    ap.add_argument("--klasyfikator", default=llm.LLM_MODEL_KLASYFIKACJA, help="model Ollamy do klasyfikacji kategorii")
    ap.add_argument("--pokaz", default="", help="przedrostek nazwy dokumentu, którego tekst zanonimizowany wypisać")
    # 200 sesji obejmuje przypadki kolizji surogatów znalezione 2026-11-17 (sesje 9 i 129), ok. 1 min na ciepłej pamięci
    ap.add_argument("--sesje", type=int, default=200,
                    help="ile sesji o ustalonych id (wzorzec-0, wzorzec-1, …) na dokument; surogaty zależą od id sesji")
    args = ap.parse_args()

    dokumenty = wczytaj()
    wykryte = wykryj_z_cache(dokumenty, args.llm)
    zostaw = wczytaj_zostaw()
    p_pamiec = pamiec_plik.sciezka(WYNIKI, "cache_klasyfikacja_", args.klasyfikator)
    pamiec = pamiec_plik.wczytaj(p_pamiec)
    zapisz_pamiec = pamiec_plik.zapisywacz(p_pamiec, args.klasyfikator)
    czasy_klasyfikacji = collections.Counter()
    t_start = time.time()

    def ile(fragment: str, gdzie: str) -> int:
        return len(re.findall(r"(?<![\p{L}\d])" + re.escape(fragment) + r"(?![\p{L}\d])", gdzie))

    linie = ["# Etap 2: pełny obieg\n",
             "| dokument | podmiany | wycieki | zepsute | różnice po obiegu | niepewne | wycieki złapane przez kontrolę "
             "| fałszywe alarmy kontroli | sesje z błędem |",
             "|---|---|---|---|---|---|---|---|---|"]
    szczegoly, suma = [], [0] * 8
    for dok, (tekst, wzorce) in dokumenty.items():
        licz = [0] * 8
        bledy: dict[str, list[int]] = {}   # opis błędu -> numery sesji, w których wystąpił
        for nr in range(args.sesje):
            sesja = Sesja(sciezka=":memory:", nowe_id=f"wzorzec-{nr}")
            czasy: dict = {}
            wynik = silnik.anonimizuj(sesja, tekst, wykryte[dok], pamiec=pamiec, model_klasyfikacji=args.klasyfikator,
                                      zapisz_pamiec=zapisz_pamiec, czasy=czasy)
            for k, v in czasy.items():
                if k.startswith("klasyfikacja_"):
                    czasy_klasyfikacji[k.removeprefix("klasyfikacja_")] += v["s"]
            anon = wynik["tekst"]
            wycieki = sorted({w.tekst for w in wzorce if len(w.tekst) >= 4 and ile(w.tekst, anon)})
            powrot = silnik.deanonimizuj(sesja, anon)
            roznice = _roznice(tekst, powrot["tekst"])
            # „Zepsute”: fragment, który miał zostać, występuje w tekście zanonimizowanym rzadziej niż w oryginale
            zepsute = sorted({z.tekst for z in zostaw[dok] if ile(z.tekst, anon) < ile(z.tekst, tekst)})
            # Kontrola wycieku: które wycieki złapała i ile alarmów nie dotyczy żadnej encji wzorcowej
            trafienia = wynik["kontrola"]["trafienia"]
            miejsca_wzorcow = [(m.start(), m.end()) for w in wzorce if len(w.tekst) >= 3
                               for m in re.finditer(r"(?<![\p{L}\d])" + re.escape(w.tekst) + r"(?![\p{L}\d])", anon)]

            def zachodzi(a: int, b: int, miejsca) -> bool:
                return any(a < y and b > x for x, y in miejsca)

            pozycje_trafien = [(t["start"], t["end"]) for t in trafienia]
            zlapane = [w for w in wycieki if any(zachodzi(m.start(), m.end(), pozycje_trafien)
                                                 for m in re.finditer(r"(?<![\p{L}\d])" + re.escape(w) + r"(?![\p{L}\d])", anon))]
            falszywe = [t for t in trafienia if not zachodzi(t["start"], t["end"], miejsca_wzorcow)]
            for i, v in enumerate((len(wynik["podmiany"]), len(wycieki), len(zepsute), len(roznice), len(powrot["niepewne"]),
                                   len(zlapane), len(falszywe))):
                licz[i] += v
            licz[7] += bool(wycieki or zepsute or roznice)
            for opis in ([f"WYCIEK: „{w}”{' (złapany przez kontrolę)' if w in zlapane else ''}" for w in wycieki]
                         + [f"ZEPSUTE: „{z}”" for z in zepsute] + [f"RÓŻNICA: {r}" for r in roznice]
                         + [f"FAŁSZYWY ALARM KONTROLI: {t['rodzaj']} {t['kat']} „{t['tekst']}”" for t in falszywe]):
                bledy.setdefault(opis, []).append(nr)
            if nr == 0:
                # Szczegóły, które nie są błędami, z pierwszej sesji
                pierwsza = [f"1. NIEPEWNE: „{n['surogat']}” -> „{n['oryginal']}” (…{n['kontekst']}…)" for n in powrot["niepewne"]]
                pierwsza += [f"1. BEZ PODMIANY: {p['typ']} „{p['tekst']}”" for p in wynik["pominiete"]]
                if args.pokaz and dok.startswith(args.pokaz):
                    pierwsza.append("\n```\n" + anon + "\n```")
        licz[0] = round(licz[0] / args.sesje)
        linie.append(f"| {dok} | " + " | ".join(map(str, licz)) + " |")
        for i, v in enumerate(licz):
            suma[i] += v
        szczegoly.append(f"\n## {dok}\n")
        szczegoly += [f"1. {opis} (sesje: {', '.join(map(str, nry[:5]))}{', …' if len(nry) > 5 else ''})" for opis, nry in bledy.items()]
        szczegoly += pierwsza
    linie.append("| **razem** | " + " | ".join(map(str, suma)) + " |")
    zapisz_pamiec(pamiec)
    czasy_txt = ", ".join(f"{w} {s:.0f} s" for w, s in czasy_klasyfikacji.items())
    linie.insert(1, f"Klasyfikator kategorii: {args.klasyfikator}. Sesje na dokument: {args.sesje} (id wzorzec-0 …). "
                    f"Podmiany: średnio na sesję, pozostałe liczniki: suma ze wszystkich sesji. "
                    f"Czas przebiegu: {time.time() - t_start:.0f} s (klasyfikacja: {czasy_txt}).\n")
    tresc = "\n".join(linie + szczegoly) + "\n"
    (WYNIKI / "etap2_obieg.md").write_text(tresc, encoding="utf-8")
    print(tresc)


if __name__ == "__main__":
    main()

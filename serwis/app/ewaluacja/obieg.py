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
    args = ap.parse_args()

    dokumenty = wczytaj()
    wykryte = wykryj_z_cache(dokumenty, args.llm)
    zostaw = wczytaj_zostaw()
    p_pamiec = pamiec_plik.sciezka(WYNIKI, "cache_klasyfikacja_", args.klasyfikator)
    pamiec = pamiec_plik.wczytaj(p_pamiec)
    zapisz_pamiec = pamiec_plik.zapisywacz(p_pamiec, args.klasyfikator)
    czasy_klasyfikacji = collections.Counter()
    t_start = time.time()
    linie = ["# Etap 2: pełny obieg\n", "| dokument | podmiany | wycieki | zepsute | różnice po obiegu | niepewne |", "|---|---|---|---|---|---|"]
    szczegoly, suma = [], [0, 0, 0, 0, 0]
    for dok, (tekst, wzorce) in dokumenty.items():
        sesja = Sesja(sciezka=":memory:")
        czasy: dict = {}
        wynik = silnik.anonimizuj(sesja, tekst, wykryte[dok], pamiec=pamiec, model_klasyfikacji=args.klasyfikator,
                                  zapisz_pamiec=zapisz_pamiec, czasy=czasy)
        for k, v in czasy.items():
            if k.startswith("klasyfikacja_"):
                czasy_klasyfikacji[k.removeprefix("klasyfikacja_")] += v["s"]
        anon = wynik["tekst"]
        wycieki = sorted({w.tekst for w in wzorce if len(w.tekst) >= 4 and re.search(r"(?<![\p{L}\d])" + re.escape(w.tekst) + r"(?![\p{L}\d])", anon)})
        powrot = silnik.deanonimizuj(sesja, anon)
        roznice = _roznice(tekst, powrot["tekst"])
        # „Zepsute”: fragment, który miał zostać, występuje w tekście zanonimizowanym rzadziej niż w oryginale
        def ile(fragment: str, gdzie: str) -> int:
            return len(re.findall(r"(?<![\p{L}\d])" + re.escape(fragment) + r"(?![\p{L}\d])", gdzie))

        zepsute = sorted({z.tekst for z in zostaw[dok] if ile(z.tekst, anon) < ile(z.tekst, tekst)})
        linie.append(f"| {dok} | {len(wynik['podmiany'])} | {len(wycieki)} | {len(zepsute)} | {len(roznice)} | {len(powrot['niepewne'])} |")
        for i, v in enumerate((len(wynik["podmiany"]), len(wycieki), len(zepsute), len(roznice), len(powrot["niepewne"]))):
            suma[i] += v
        szczegoly.append(f"\n## {dok}\n")
        szczegoly += [f"1. WYCIEK: „{w}”" for w in wycieki]
        szczegoly += [f"1. ZEPSUTE: „{z}”" for z in zepsute]
        szczegoly += [f"1. RÓŻNICA: {r}" for r in roznice]
        szczegoly += [f"1. NIEPEWNE: „{n['surogat']}” -> „{n['oryginal']}” (…{n['kontekst']}…)" for n in powrot["niepewne"]]
        szczegoly += [f"1. BEZ PODMIANY: {p['typ']} „{p['tekst']}”" for p in wynik["pominiete"]]
        if args.pokaz and dok.startswith(args.pokaz):
            szczegoly.append("\n```\n" + anon + "\n```")
    linie.append(f"| **razem** | {suma[0]} | {suma[1]} | {suma[2]} | {suma[3]} | {suma[4]} |")
    zapisz_pamiec(pamiec)
    czasy_txt = ", ".join(f"{w} {s:.0f} s" for w, s in czasy_klasyfikacji.items())
    linie.insert(1, f"Klasyfikator kategorii: {args.klasyfikator}. Czas przebiegu: {time.time() - t_start:.0f} s"
                    f" (klasyfikacja: {czasy_txt}).\n")
    tresc = "\n".join(linie + szczegoly) + "\n"
    (WYNIKI / "etap2_obieg.md").write_text(tresc, encoding="utf-8")
    print(tresc)


if __name__ == "__main__":
    main()

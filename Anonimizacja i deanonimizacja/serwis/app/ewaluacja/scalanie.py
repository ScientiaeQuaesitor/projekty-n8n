"""Pomiar wpływu scalania zakresów: pokrycie i nadmiar przed i po.

Uruchomienie w kontenerze:  python -m app.ewaluacja.scalanie [--llm gemma4:e4b] [--odswiez]

Wyniki detektorów są zapamiętywane w testy/wyniki/cache_detekcja.json, żeby kolejne przebiegi
nie czekały na LLM. Flaga --odswiez wymusza ponowną detekcję."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from ..detekcja import llm, ner, regexy
from ..detekcja.scal import scal
from ..detekcja.typy import Encja
from .uruchom import WYNIKI, ocen
from .wzorce import wczytaj

CACHE = WYNIKI / "cache_detekcja.json"


def wykryj_z_cache(dokumenty: dict, model: str, odswiez: bool = False) -> dict[str, list[Encja]]:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() and not odswiez else {}
    detektory = {"regex": regexy.wykryj, "spacy": ner.wykryj_spacy, "hf": ner.wykryj_hf, f"llm:{model}": lambda t: llm.wykryj(t, model)}
    out = {}
    for dok, (tekst, _) in dokumenty.items():
        encje = []
        for nazwa, fn in detektory.items():
            klucz = hashlib.sha256(f"{nazwa}|{tekst}".encode()).hexdigest()
            if nazwa == "regex" or klucz not in cache:  # regexy liczone zawsze, bo są szybkie i często zmieniane
                cache[klucz] = [e.jako_dict() for e in fn(tekst)]
            encje.extend(Encja(**e) for e in cache[klucz])
        out[dok] = encje
    WYNIKI.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=llm.LLM_MODEL)
    ap.add_argument("--odswiez", action="store_true")
    args = ap.parse_args()

    dokumenty = wczytaj()
    wykryte = wykryj_z_cache(dokumenty, args.llm, args.odswiez)
    linie = ["# Etap 2: scalanie zakresów\n", "| wariant | detektory | pełne | częściowe | brak | nadmiar |", "|---|---|---|---|---|---|"]
    szczegoly = []
    for etykieta, filtr in (("bez LLM", lambda e: not e.zrodlo.startswith("llm")), ("z LLM", lambda e: True)):
        for wariant in ("surowe", "scalone"):
            suma = defaultdict(int)
            pominiete, nadmiar = [], []
            for dok, (tekst, wzorce) in dokumenty.items():
                encje = [e for e in wykryte[dok] if filtr(e)]
                zakresy = scal(tekst, encje) if wariant == "scalone" else encje
                o = ocen(tekst, wzorce, zakresy)
                for s in o["per_typ"].values():
                    for k, v in s.items():
                        suma[k] += v
                pominiete += [(dok, p) for p in o["pominiete"]]
                nadmiar += o["nadmiar"]
            linie.append(f"| {wariant} | {etykieta} | {suma['pelne']}/{suma['n']} ({suma['pelne'] / suma['n']:.1%}) | {suma['czesciowe']} | {suma['brak']} | {len(nadmiar)} |")
            if wariant == "scalone":
                szczegoly.append(f"\n## Scalone, {etykieta}: pominięte\n")
                szczegoly += [f"1. `{d}` {p['typ']} „{p['tekst']}” ({p['pokryte']}): …{p['kontekst']}…" for d, p in pominiete] or ["Brak."]
                szczegoly.append(f"\n## Scalone, {etykieta}: nadmiar\n")
                szczegoly.append(", ".join(f"„{x}”" for x in sorted(set(nadmiar))) or "Brak.")
    tresc = "\n".join(linie + szczegoly) + "\n"
    (WYNIKI / "etap2_scalanie.md").write_text(tresc, encoding="utf-8")
    print(tresc)


if __name__ == "__main__":
    main()

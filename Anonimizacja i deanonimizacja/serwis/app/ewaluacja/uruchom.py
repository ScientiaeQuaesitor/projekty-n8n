"""Pomiar detekcji na zestawie wzorcowym.

Uruchomienie w kontenerze:  python -m app.ewaluacja.uruchom --llm gemma4:e4b [--llm inny:model]

Miara główna: encja wzorcowa jest „pokryta”, gdy każdy jej znak (poza spacjami) leży w zakresie
wykrytym przez dowolny detektor z konfiguracji, niezależnie od przypisanego typu. To odpowiada
pytaniu „czy ten fragment zostałby podmieniony”. Nadmiar to wykryte zakresy bez żadnej części wspólnej
z encjami wzorcowymi."""
import argparse
import itertools
import json
import time
from collections import defaultdict
from pathlib import Path

from ..detekcja import llm, ner, regexy
from ..detekcja.typy import TYPY
from .wzorce import wczytaj

WYNIKI = Path(__file__).resolve().parents[2] / "testy" / "wyniki"


def _maska(dlugosc: int, encje) -> bytearray:
    m = bytearray(dlugosc)
    for e in encje:
        m[e.start:e.end] = b"\x01" * (e.end - e.start)
    return m


def _zakresy(maska: bytearray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(maska):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(maska)))
    return out


def ocen(tekst: str, wzorce, wykryte) -> dict:
    maska = _maska(len(tekst), wykryte)
    maska_wz = _maska(len(tekst), wzorce)
    per_typ = defaultdict(lambda: {"n": 0, "pelne": 0, "czesciowe": 0, "brak": 0})
    pominiete = []
    for w in wzorce:
        znaki = [i for i in range(w.start, w.end) if not tekst[i].isspace()]
        pokryte = sum(maska[i] for i in znaki)
        s = per_typ[w.typ]
        s["n"] += 1
        if pokryte == len(znaki):
            s["pelne"] += 1
        else:
            s["czesciowe" if pokryte else "brak"] += 1
            pominiete.append({"typ": w.typ, "tekst": w.tekst, "pokryte": f"{pokryte}/{len(znaki)}",
                              "kontekst": tekst[max(0, w.start - 30):w.end + 20].replace("\n", " ")})
    nadmiar = [tekst[a:b] for a, b in _zakresy(maska) if not any(maska_wz[a:b])]
    return {"per_typ": dict(per_typ), "pominiete": pominiete, "nadmiar": nadmiar}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="append", default=[], help="model Ollamy, można podać kilka razy")
    ap.add_argument("--bez-ner", action="store_true")
    args = ap.parse_args()

    dokumenty = wczytaj()
    bazowe = {"regex": regexy.wykryj}
    if not args.bez_ner:
        bazowe["spacy"] = ner.wykryj_spacy
        bazowe["hf"] = ner.wykryj_hf
    for model in args.llm:
        bazowe[f"llm:{model}"] = lambda t, m=model: llm.wykryj(t, m)

    # Każdy detektor uruchamiany raz na dokument, kombinacje liczone z zapamiętanych wyników
    wykryte, czasy = defaultdict(dict), defaultdict(float)
    for nazwa, fn in bazowe.items():
        if nazwa in ("spacy", "hf"):
            fn("Rozgrzewka modelu.")  # ładowanie modelu poza pomiarem czasu
        for dok, (tekst, _) in dokumenty.items():
            t0 = time.perf_counter()
            wykryte[nazwa][dok] = fn(tekst)
            czasy[nazwa] += time.perf_counter() - t0
        print(f"[{nazwa}] {czasy[nazwa]:.1f} s", flush=True)

    konfiguracje = [list(k) for r in range(1, len(bazowe) + 1) for k in itertools.combinations(bazowe, r)]
    konfiguracje = [k for k in konfiguracje if sum(n.startswith("llm:") for n in k) <= 1]

    raport = []
    for konf in konfiguracje:
        suma = defaultdict(lambda: {"n": 0, "pelne": 0, "czesciowe": 0, "brak": 0})
        pominiete, nadmiar = {}, []
        for dok, (tekst, wzorce) in dokumenty.items():
            o = ocen(tekst, wzorce, [e for n in konf for e in wykryte[n][dok]])
            for typ, s in o["per_typ"].items():
                for k, v in s.items():
                    suma[typ][k] += v
            pominiete[dok] = o["pominiete"]
            nadmiar.extend(o["nadmiar"])
        n = sum(s["n"] for s in suma.values())
        pelne = sum(s["pelne"] for s in suma.values())
        raport.append({
            "konfiguracja": "+".join(konf), "n": n, "pelne": pelne,
            "czesciowe": sum(s["czesciowe"] for s in suma.values()),
            "brak": sum(s["brak"] for s in suma.values()),
            "recall": round(pelne / n, 4), "nadmiar": len(nadmiar),
            "czas_s": round(sum(czasy[x] for x in konf), 1),
            "per_typ": {t: suma[t] for t in TYPY if t in suma},
            "pominiete": pominiete, "nadmiar_lista": sorted(set(nadmiar)),
        })
    raport.sort(key=lambda r: (-r["recall"], r["nadmiar"]))

    typy = [t for t in TYPY if any(t in r["per_typ"] for r in raport)]
    znaki = sum(len(t) for t, _ in dokumenty.values())
    linie = [f"# Etap 1: pomiar detekcji\n",
             f"Dokumenty: {len(dokumenty)}, znaków: {znaki}, encji wzorcowych: {raport[0]['n']}.\n",
             "Wartości w kolumnach typów: w pełni pokryte / wszystkie.\n",
             "| konfiguracja | recall | częściowe | brak | nadmiar | czas [s] | " + " | ".join(typy) + " |",
             "|---|---|---|---|---|---|" + "---|" * len(typy)]
    for r in raport:
        kom = [f"{r['per_typ'][t]['pelne']}/{r['per_typ'][t]['n']}" if t in r["per_typ"] else "" for t in typy]
        linie.append(f"| {r['konfiguracja']} | {r['recall']:.1%} | {r['czesciowe']} | {r['brak']} | {r['nadmiar']} | {r['czas_s']} | " + " | ".join(kom) + " |")
    najlepsza = raport[0]
    linie.append(f"\n## Pominięte w najlepszej konfiguracji ({najlepsza['konfiguracja']})\n")
    for dok, lista in najlepsza["pominiete"].items():
        for p in lista:
            linie.append(f"1. `{dok}` {p['typ']} „{p['tekst']}” ({p['pokryte']}): …{p['kontekst']}…")
    linie.append(f"\n## Nadmiar w najlepszej konfiguracji ({len(najlepsza['nadmiar_lista'])} unikalnych)\n")
    linie.append(", ".join(f"„{x}”" for x in najlepsza["nadmiar_lista"]))

    WYNIKI.mkdir(parents=True, exist_ok=True)
    (WYNIKI / "etap1.json").write_text(json.dumps(raport, ensure_ascii=False, indent=1), encoding="utf-8")
    (WYNIKI / "etap1.md").write_text("\n".join(linie) + "\n", encoding="utf-8")
    print("\n".join(linie[:5 + len(raport)]))


if __name__ == "__main__":
    main()

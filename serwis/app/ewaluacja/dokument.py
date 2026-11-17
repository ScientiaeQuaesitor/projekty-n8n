"""Pełny przebieg na prawdziwym pliku PDF: ekstrakcja, detekcja, anonimizacja, obieg, raport HTML.

Uruchomienie w kontenerze:  python -m app.ewaluacja.dokument /srv/testy/prawdziwe/plik.pdf [--od-nowa] [--klasyfikator model]

Wypisuje wyłącznie liczniki, czasy faz i tekst zanonimizowany. Oryginał, raport porównawczy i pamięć ocen
klasyfikacji (plik.klasyfikacja_<model>.json) zostają w plikach obok PDF."""
import argparse
import collections
import json
import pathlib
import time

from .. import detekcja, ekstrakcja, raport
from ..anonimizacja import silnik
from ..anonimizacja.sesja import Sesja
from ..detekcja import llm, regexy
from ..detekcja.typy import Encja
from . import pamiec as pamiec_plik
from .obieg import _roznice
from .ocr import miary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--od-nowa", action="store_true", help="powtórz ekstrakcję i detekcję zamiast brać je z plików pośrednich")
    ap.add_argument("--pokaz", type=int, default=3000, help="ile znaków tekstu zanonimizowanego wypisać")
    ap.add_argument("--klasyfikator", default=llm.LLM_MODEL_KLASYFIKACJA, help="model Ollamy do klasyfikacji kategorii")
    args = ap.parse_args()
    pdf = pathlib.Path(args.pdf)
    baza = pdf.with_suffix("")
    p_tekst, p_encje = baza.with_suffix(".tekst.md"), baza.with_suffix(".encje.json")
    czasy: dict = {}

    if args.od_nowa or not p_tekst.exists():
        t0 = time.time()
        tekst, info = ekstrakcja.tekst_z_pdf(pdf)
        czasy["ekstrakcja"] = round(time.time() - t0, 1)
        p_tekst.write_text(tekst, encoding="utf-8")
        p_encje.unlink(missing_ok=True)
        print("ekstrakcja:", info)
    tekst = p_tekst.read_text(encoding="utf-8")
    print("jakość tekstu:", miary(tekst))

    if p_encje.exists():
        encje = [Encja(**e) for e in json.loads(p_encje.read_text(encoding="utf-8")) if e["zrodlo"] != "regex"] + regexy.wykryj(tekst)
    else:
        t0 = time.time()
        encje = detekcja.wykryj(tekst, ["regex", "spacy", "hf", "llm"])
        czasy["detekcja"] = round(time.time() - t0, 1)
        p_encje.write_text(json.dumps([e.jako_dict() for e in encje], ensure_ascii=False), encoding="utf-8")

    # Oceny klasyfikacji zapisywane po każdej paczce obok PDF: przerwany pomiar wznawia się bez powtórnych pytań
    p_pamiec = pamiec_plik.sciezka(pdf.parent, baza.name + ".klasyfikacja_", args.klasyfikator)
    pamiec = pamiec_plik.wczytaj(p_pamiec)
    zapisz_pamiec = pamiec_plik.zapisywacz(p_pamiec, args.klasyfikator)

    sesja = Sesja(sciezka=":memory:")
    wynik = silnik.anonimizuj(sesja, tekst, encje, pamiec=pamiec, model_klasyfikacji=args.klasyfikator,
                              zapisz_pamiec=zapisz_pamiec, czasy=czasy)
    zapisz_pamiec(pamiec)
    t0 = time.time()
    powrot = silnik.deanonimizuj(sesja, wynik["tekst"])
    czasy["deanonimizacja"] = round(time.time() - t0, 1)
    roznice = _roznice(tekst, powrot["tekst"])
    baza.with_suffix(".anon.md").write_text(wynik["tekst"], encoding="utf-8")
    baza.with_suffix(".raport.html").write_text(raport.zbuduj(f"{pdf.name}: raport porównawczy", tekst, wynik), encoding="utf-8")
    baza.with_suffix(".raport.json").write_text(json.dumps({**wynik, "roznice": roznice, "niepewne": powrot["niepewne"], "czasy": czasy},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    print("czasy faz [s]:")
    for faza, v in czasy.items():
        print(f"  {faza}: {v['s']} (zapytane {v['zapytane']}, z pamięci {v['z_pamieci']})" if isinstance(v, dict) else f"  {faza}: {v}")
    print("podmian", len(wynik["podmiany"]), dict(collections.Counter(p["typ"] for p in wynik["podmiany"])))
    # Bez treści trafień: to oryginały. Pozycje i treść są w raport.json (pole kontrola) obok PDF.
    k = wynik["kontrola"]
    print("kontrola wycieku:", k["status"], dict(collections.Counter(f"{t['rodzaj']}/{t['kat']}" for t in k["trafienia"])))
    print("różnic po obiegu:", len(roznice), "; niepewnych:", len(powrot["niepewne"]))
    print("odrzucone jako ogólne (ocena LLM):", wynik["odrzucone_jako_ogolne"])
    print("=" * 30)
    print(wynik["tekst"][:args.pokaz])


if __name__ == "__main__":
    main()

"""Pełny przebieg na prawdziwym pliku PDF: ekstrakcja, detekcja, anonimizacja, obieg, raport HTML.

Uruchomienie w kontenerze:  python -m app.ewaluacja.dokument /srv/testy/prawdziwe/plik.pdf [--od-nowa]

Wypisuje wyłącznie liczniki i tekst zanonimizowany. Oryginał i raport porównawczy zostają w plikach obok PDF."""
import argparse
import collections
import json
import pathlib
import time

from .. import detekcja, ekstrakcja, raport
from ..anonimizacja import silnik
from ..anonimizacja.sesja import Sesja
from ..detekcja import regexy
from ..detekcja.typy import Encja
from .obieg import _roznice
from .ocr import miary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--od-nowa", action="store_true", help="powtórz ekstrakcję i detekcję zamiast brać je z plików pośrednich")
    ap.add_argument("--pokaz", type=int, default=3000, help="ile znaków tekstu zanonimizowanego wypisać")
    args = ap.parse_args()
    pdf = pathlib.Path(args.pdf)
    baza = pdf.with_suffix("")
    p_tekst, p_encje = baza.with_suffix(".tekst.md"), baza.with_suffix(".encje.json")

    if args.od_nowa or not p_tekst.exists():
        tekst, info = ekstrakcja.tekst_z_pdf(pdf)
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
        p_encje.write_text(json.dumps([e.jako_dict() for e in encje], ensure_ascii=False), encoding="utf-8")
        print("detekcja:", round(time.time() - t0), "s")

    sesja = Sesja(sciezka=":memory:")
    t0 = time.time()
    wynik = silnik.anonimizuj(sesja, tekst, encje)
    powrot = silnik.deanonimizuj(sesja, wynik["tekst"])
    roznice = _roznice(tekst, powrot["tekst"])
    baza.with_suffix(".anon.md").write_text(wynik["tekst"], encoding="utf-8")
    baza.with_suffix(".raport.html").write_text(raport.zbuduj(f"{pdf.name}: raport porównawczy", tekst, wynik), encoding="utf-8")
    baza.with_suffix(".raport.json").write_text(json.dumps({**wynik, "roznice": roznice, "niepewne": powrot["niepewne"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("anonimizacja:", round(time.time() - t0), "s; podmian", len(wynik["podmiany"]), dict(collections.Counter(p["typ"] for p in wynik["podmiany"])))
    print("różnic po obiegu:", len(roznice), "; niepewnych:", len(powrot["niepewne"]))
    print("odrzucone jako ogólne (ocena LLM):", wynik["odrzucone_jako_ogolne"])
    print("=" * 30)
    print(wynik["tekst"][:args.pokaz])


if __name__ == "__main__":
    main()

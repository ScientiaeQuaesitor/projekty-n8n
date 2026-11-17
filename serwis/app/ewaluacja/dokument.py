"""Pełny przebieg na prawdziwym pliku PDF: ekstrakcja, detekcja, anonimizacja, obieg, raport HTML.

Oryginały do testów wrzuca użytkownik do jednego folderu: serwis/testy/prawdziwe/oryginaly/ (w kontenerze
/srv/testy/prawdziwe/oryginaly/). Tylko stamtąd brane są pliki. Wyniki trafiają do
serwis/testy/prawdziwe/wyniki/<nazwa pliku>/ (tekst z OCR, encje, pamięć ocen, tekst zanonimizowany, raport HTML i JSON).

Uruchomienie w kontenerze:
  python -m app.ewaluacja.dokument                  wszystkie pliki z folderu oryginałów
  python -m app.ewaluacja.dokument nazwa.pdf        jeden plik z folderu oryginałów
Opcje: [--od-nowa] [--klasyfikator model] [--pokaz liczba_znaków]

Wypisuje wyłącznie liczniki, czasy faz i początek tekstu zanonimizowanego, nigdy oryginału."""
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


PRAWDZIWE = pathlib.Path("/srv/testy/prawdziwe")
ORYGINALY = PRAWDZIWE / "oryginaly"
WYNIKI_PRAWDZIWE = PRAWDZIWE / "wyniki"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?", help="nazwa pliku w folderze oryginałów; bez niej wszystkie pliki PDF z folderu")
    ap.add_argument("--od-nowa", action="store_true", help="powtórz ekstrakcję i detekcję zamiast brać je z plików pośrednich")
    ap.add_argument("--pokaz", type=int, default=0, help="ile znaków tekstu zanonimizowanego wypisać")
    ap.add_argument("--klasyfikator", default=llm.LLM_MODEL_KLASYFIKACJA, help="model Ollamy do klasyfikacji kategorii")
    args = ap.parse_args()
    pliki = [ORYGINALY / pathlib.Path(args.pdf).name] if args.pdf else sorted(ORYGINALY.glob("*.pdf"))
    if not pliki or not all(p.exists() for p in pliki):
        raise SystemExit(f"Brak plików PDF w {ORYGINALY} (albo podanego pliku). Oryginały wrzuca się do "
                         f"serwis/testy/prawdziwe/oryginaly/.")
    for pdf in pliki:
        print(f"=== {pdf.name}")
        przetworz(pdf, args)


def przetworz(pdf: pathlib.Path, args) -> None:
    katalog = WYNIKI_PRAWDZIWE / pdf.stem
    katalog.mkdir(parents=True, exist_ok=True)
    baza = katalog / pdf.stem
    p_tekst, p_encje = baza.with_suffix(".tekst.md"), baza.with_suffix(".encje.json")
    czasy: dict = {}

    # Raport ekstrakcji (strony, jakość OCR, bez treści) zapisywany obok PDF, bo trafia do raportu HTML
    p_info = baza.with_suffix(".ekstrakcja.json")
    if args.od_nowa or not p_tekst.exists() or not p_info.exists():
        t0 = time.time()
        tekst_nowy, info = ekstrakcja.tekst_z_pdf(pdf)
        czasy["ekstrakcja"] = round(time.time() - t0, 1)
        p_info.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        if args.od_nowa or not p_tekst.exists() or p_tekst.read_text(encoding="utf-8") != tekst_nowy:
            p_tekst.write_text(tekst_nowy, encoding="utf-8")
            p_encje.unlink(missing_ok=True)
            print("ekstrakcja: nowy tekst, detekcja od nowa")
        else:
            print("ekstrakcja: tekst bez zmian, detekcja z pliku")
    info = json.loads(p_info.read_text(encoding="utf-8"))
    tekst = p_tekst.read_text(encoding="utf-8")
    print("jakość tekstu:", miary(tekst))

    if p_encje.exists():
        encje = [Encja(**e) for e in json.loads(p_encje.read_text(encoding="utf-8")) if e["zrodlo"] != "regex"] + regexy.wykryj(tekst)
    else:
        t0 = time.time()
        encje = detekcja.wykryj(tekst, ["regex", "spacy", "hf", "llm"])
        czasy["detekcja"] = round(time.time() - t0, 1)
        p_encje.write_text(json.dumps([e.jako_dict() for e in encje], ensure_ascii=False), encoding="utf-8")

    # Oceny klasyfikacji zapisywane po każdej paczce w katalogu wyników: przerwany pomiar wznawia się bez powtórnych pytań
    p_pamiec = pamiec_plik.sciezka(katalog, baza.name + ".klasyfikacja_", args.klasyfikator)
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
    baza.with_suffix(".raport.html").write_text(raport.zbuduj(f"{pdf.name}: raport porównawczy", tekst, wynik, info.get("ocr"),
                                                                 raport.obrazy_stron(pdf) if info.get("skan") else None), encoding="utf-8")
    baza.with_suffix(".raport.json").write_text(json.dumps({**wynik, "roznice": roznice, "niepewne": powrot["niepewne"], "czasy": czasy},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    print("czasy faz [s]:")
    for faza, v in czasy.items():
        print(f"  {faza}: {v['s']} (zapytane {v['zapytane']}, z pamięci {v['z_pamieci']}, niepotrzebne {v.get('pominiete', 0)})"
              if isinstance(v, dict) else f"  {faza}: {v}")
    print("podmian", len(wynik["podmiany"]), dict(collections.Counter(p["typ"] for p in wynik["podmiany"])))
    # Bez treści trafień: to oryginały. Pozycje i treść są w raport.json (pole kontrola) obok PDF.
    k = wynik["kontrola"]
    print("kontrola wycieku:", k["status"], dict(collections.Counter(f"{t['rodzaj']}/{t['kat']}" for t in k["trafienia"])))
    print("różnic po obiegu:", len(roznice), "; niepewnych:", len(powrot["niepewne"]))
    # Same liczniki: na liście zostawionych mogłaby się znaleźć źle oceniona nazwa własna
    print("zostawione (kategoria):", dict(collections.Counter(wynik["zostawione"].values())))
    print("raport:", f"serwis/testy/prawdziwe/wyniki/{pdf.stem}/{pdf.stem}.raport.html")
    if args.pokaz:
        print("=" * 30)
        print(wynik["tekst"][:args.pokaz])


if __name__ == "__main__":
    main()

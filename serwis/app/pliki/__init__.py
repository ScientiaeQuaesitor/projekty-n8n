"""Anonimizacja plików DOCX i PDF cyfrowych (etap 3) z kontrolą wycieku na pliku wynikowym (PLAN 4.5).

Kontrola pliku, bez modelu:
1. Tekst odczytany ponownie z pliku wynikowego musi się zgadzać z tekstem zanonimizowanym, który dał silnik. DOCX:
   tekst ciągły identyczny. PDF: każdy wiersz (strona i linia bazowa) z tymi samymi znakami poza odstępami. Różnica
   znaczy, że podmiana nie trafiła w plik albo w pliku został tekst, którego model nie widział.
2. Bezpiecznik wycieku (silnik.kontrola_wycieku: oryginały z mapy sesji, ponowne regexy numerów) na całym tekście
   pliku: także metadanych, XMP, relacjach, częściach, których model nie czyta.
3. W pliku nie może zostać obraz, załącznik ani część binarna.
Ponowny przebieg NER nie jest potrzebny: przy zgodności z punktu 1 dałby to samo co detekcja na tekście
zanonimizowanym, a tę ocenia już kontrola tekstu i raport."""
import difflib
from pathlib import Path

import regex as re

from ..anonimizacja import silnik
from ..anonimizacja.sesja import Sesja
from . import docx as fdocx
from . import pdf as fpdf

OBSLUGIWANE = {".docx": "docx", ".pdf": "pdf"}


class BladPliku(ValueError):
    pass


def rodzaj(nazwa: str, dane: bytes) -> str:
    typ = OBSLUGIWANE.get(Path(nazwa).suffix.lower())
    if typ is None:
        raise BladPliku(f"Nieobsługiwany typ pliku: {Path(nazwa).suffix or 'brak rozszerzenia'}")
    if typ == "pdf" and fpdf.strony_bez_tekstu(dane):
        return "pdf_skan"
    return typ


def otworz(typ: str, dane: bytes):
    if typ == "docx":
        return fdocx.Docx(dane)
    if typ == "pdf":
        return fpdf.Pdf(dane)
    raise BladPliku(f"Typ {typ} nie ma jeszcze podmiany w pliku (skany: faza E)")


def _bez_odstepow(s: str) -> str:
    return re.sub(r"\s+", "", s)


TOLERANCJA_BAZY = 1.5   # pt: znaki o liniach bazowych bliższych niż ta wartość należą do jednego wiersza


def _grupuj(elementy: list[tuple[int, float, float, str]]) -> list[tuple[int, float, str]]:
    """(strona, linia bazowa, x, tekst) -> wiersze (strona, linia bazowa, tekst bez odstępów w kolejności x)."""
    out: list[list] = []
    for nr, y, x, t in sorted(elementy):
        if out and out[-1][0] == nr and y - out[-1][1] < TOLERANCJA_BAZY:
            out[-1][2].append((x, t))
        else:
            out.append([nr, y, [(x, t)]])
    return [(nr, y, _bez_odstepow("".join(t for _, t in sorted(cz)))) for nr, y, cz in out]


def _wiersze_pdf(p: "fpdf.Pdf", edycje: dict) -> list[tuple[int, float, str]]:
    """Wiersze oczekiwane po podmianie, z modelu pliku wejściowego i edycji kawałków."""
    from .model import zastosuj
    el = []
    for k, (nr, znaki) in enumerate(p.model.kawalki):
        tekst = zastosuj("".join(z["c"] for z in znaki), edycje.get(k, []))
        el.append((nr, znaki[0]["origin"][1], znaki[0]["origin"][0], tekst))
    return [w for w in _grupuj(el) if w[2]]


def _wiersze_pdf_odczyt(dane: bytes) -> list[tuple[int, float, str]]:
    import fitz
    d = fitz.open(stream=dane, filetype="pdf")
    el = [(nr, z["origin"][1], z["origin"][0], z["c"]) for nr, s in enumerate(d) for b in s.get_text("rawdict")["blocks"]
          for l in b.get("lines", []) for sp in l["spans"] for z in sp["chars"] if z["c"].strip()]
    return [w for w in _grupuj(el) if w[2]]


def _porownaj(oczekiwane: list, odczytane: list) -> list[str]:
    out, wolne = [], list(odczytane)
    for nr, y, tekst in oczekiwane:
        para = next((w for w in wolne if w[0] == nr and abs(w[1] - y) < TOLERANCJA_BAZY), None)
        if para is None:
            out.append(f"strona {nr + 1}, wiersz y={y:.0f}: brak w pliku („{tekst[:80]}”)")
            continue
        wolne.remove(para)
        if para[2] != tekst:
            out.append(f"strona {nr + 1}, wiersz y={y:.0f}: oczekiwano „{tekst[:80]}”, w pliku „{para[2][:80]}”")
    out += [f"strona {nr + 1}, wiersz y={y:.0f}: nadmiarowy tekst w pliku „{t[:80]}”" for nr, y, t in wolne]
    return out


def kontrola_pliku(sesja: Sesja, typ: str, wynik_plik: bytes, tekst_anon: str, oczekiwane_wiersze: list | None = None) -> dict:
    roznice: list[str] = []
    if typ == "docx":
        odczyt = fdocx.Docx(wynik_plik).model.tekst
        if odczyt != tekst_anon:
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, tekst_anon, odczyt, autojunk=False).get_opcodes():
                if op != "equal":
                    roznice.append(f"oczekiwano „{tekst_anon[max(0, i1 - 20):i2 + 20]}”, w pliku „{odczyt[max(0, j1 - 20):j2 + 20]}”")
        surowy = fdocx.tekst_surowy(wynik_plik)
    else:
        roznice = _porownaj(oczekiwane_wiersze or [], _wiersze_pdf_odczyt(wynik_plik))
        surowy = fpdf.tekst_surowy(wynik_plik)
    wyciek = silnik.kontrola_wycieku(sesja, surowy)
    pozostalosci = sorted(set(re.findall(r"\[(?:część binarna|obraz|załącznik)[^\]]*\]", surowy)))
    ok = not roznice and wyciek["status"] == "ok" and not pozostalosci
    return {"status": "ok" if ok else "do_przegladu", "roznice_tekstu": roznice[:50], "liczba_roznic": len(roznice),
            "wyciek": [{k: v for k, v in t.items() if k != "start" and k != "end"} for t in wyciek["trafienia"]],
            "pozostalosci": pozostalosci}


def anonimizuj_plik(sesja: Sesja, nazwa: str, dane: bytes, encje=None, **opcje) -> tuple[bytes, dict]:
    """Zwraca (plik zanonimizowany, wynik). Wynik to wynik silnika (tekst, podmiany, kontrola tekstu, …) z polami
    typ, czyszczenie (co usunięto z pliku) i kontrola_pliku. Plik ze statusem kontroli innym niż ok nie powinien być
    wydawany."""
    typ = rodzaj(nazwa, dane)
    plik = otworz(typ, dane)
    wynik = silnik.anonimizuj(sesja, plik.model.tekst, encje, **opcje)
    oczekiwane = None
    if typ == "pdf":
        oczekiwane = _wiersze_pdf(plik, plik.model.edycje(wynik["podmiany"]))
    plik.podmien(wynik["podmiany"])
    wyjscie = plik.zapisz()
    wynik.update(typ=typ, czyszczenie=plik.czyszczenie, tekst_oryginalu=plik.model.tekst,
                 kontrola_pliku=kontrola_pliku(sesja, typ, wyjscie, wynik["tekst"], oczekiwane))
    return wyjscie, wynik

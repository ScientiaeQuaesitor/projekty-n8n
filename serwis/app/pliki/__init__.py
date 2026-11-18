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
from . import xlsx as fxlsx
from . import xml as fxml

OBSLUGIWANE = {".docx": "docx", ".pdf": "pdf", ".xlsx": "xlsx", ".xml": "xml"}
MODULY = {"docx": fdocx, "xlsx": fxlsx, "xml": fxml}   # formaty z kontrolą przez porównanie tekstu ciągłego


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
    if typ == "xlsx":
        return fxlsx.Xlsx(dane)
    if typ == "xml":
        return fxml.Xml(dane)
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
        if k not in edycje:
            # Kawałek bez podmiany zostaje w pliku znak w znak: porównanie znak po znaku, jak przy odczycie. Kawałek
            # ze znakami na dwóch liniach bazowych (komórka tabeli z „a)” obniżonym względem tekstu) inaczej trafiał
            # w całości do wiersza pierwszego znaku i dawał różnicę, choć plik się nie zmienił.
            el.extend((nr, z["origin"][1], z["origin"][0], z["c"]) for z in znaki if z["c"].strip())
            continue
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
    if typ in MODULY:
        odczyt = otworz(typ, wynik_plik).model.tekst
        if odczyt != tekst_anon:
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, tekst_anon, odczyt, autojunk=False).get_opcodes():
                if op != "equal":
                    roznice.append(f"oczekiwano „{tekst_anon[max(0, i1 - 20):i2 + 20]}”, w pliku „{odczyt[max(0, j1 - 20):j2 + 20]}”")
        surowy = MODULY[typ].tekst_surowy(wynik_plik)
    else:
        roznice = _porownaj(oczekiwane_wiersze or [], _wiersze_pdf_odczyt(wynik_plik))
        surowy = fpdf.tekst_surowy(wynik_plik)
    wyciek = silnik.kontrola_wycieku(sesja, surowy)
    pozostalosci = sorted(set(re.findall(r"\[(?:część binarna|obraz|załącznik)[^\]]*\]", surowy)))
    ok = not roznice and wyciek["status"] == "ok" and not pozostalosci
    return {"status": "ok" if ok else "do_przegladu", "roznice_tekstu": roznice[:50], "liczba_roznic": len(roznice),
            "wyciek": [{k: v for k, v in t.items() if k != "start" and k != "end"} for t in wyciek["trafienia"]],
            "pozostalosci": pozostalosci}


RX_ZNAKI_SPOZA_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def docx_z_tekstu(tekst: str) -> tuple[bytes, str]:
    """Dokument odtworzony ze skanu (PLAN 6.1, specyfikacja 2.10.3): każdy wiersz tekstu to akapit DOCX, bez obrazu
    strony i bez metadanych. Zwraca (plik, tekst w postaci, jaką ma plik), bo znaki niedozwolone w XML (sterujące z
    OCR) są usuwane, a kontrola pliku porównuje z tekstem po tym samym oczyszczeniu."""
    from docx import Document
    czysty = RX_ZNAKI_SPOZA_XML.sub("", tekst)
    d = Document()
    for k in ("author", "last_modified_by", "title", "subject", "keywords", "comments", "category"):
        setattr(d.core_properties, k, "")
    for linia in czysty.split("\n"):
        d.add_paragraph(linia)
    import io
    b = io.BytesIO()
    d.save(b)
    # Szablon python-docx ma miniaturę i metadane: plik przechodzi to samo czyszczenie co każdy DOCX
    return fdocx.Docx(b.getvalue()).zapisz(), czysty


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
    if typ == "xml":
        _zalaczniki_xml(sesja, plik, wynik, opcje)
    wyjscie = plik.zapisz()
    wynik.update(typ=typ, czyszczenie=plik.czyszczenie, tekst_oryginalu=plik.model.tekst,
                 kontrola_pliku=kontrola_pliku(sesja, typ, wyjscie, wynik["tekst"], oczekiwane))
    # Załącznik XML: wyciek w nim widzi już bezpiecznik na surowym tekście pliku (załącznik zdekodowany), ale różnice
    # tekstu pliku załącznika (wiersz PDF, który po podmianie nie zgadza się z oczekiwanym) trzeba dołączyć tutaj,
    # inaczej dokument byłby wydany jako gotowy mimo niezgodnego załącznika
    kp = wynik["kontrola_pliku"]
    for i, z in enumerate(wynik.get("zalaczniki") or [], 1):
        kz = (z.get("wynik") or {}).get("kontrola_pliku") or {}
        if kz.get("liczba_roznic"):
            kp["roznice_tekstu"] = (kp["roznice_tekstu"] + [f"załącznik {i}: {r}" for r in kz["roznice_tekstu"]])[:50]
            kp["liczba_roznic"] += kz["liczba_roznic"]
            kp["status"] = "do_przegladu"
    return wyjscie, wynik


def _zalaczniki_xml(sesja: Sesja, plik, wynik: dict, opcje: dict) -> None:
    """Załącznik XML (DOCX, PDF cyfrowy w base64) anonimizowany w tej samej sesji, więc ta sama osoba ma ten sam surogat
    w XML i w załączniku. Skan albo plik, którego nie da się otworzyć, jest usuwany. Wynik załącznika (podmiany,
    kontrole) trafia do wynik["zalaczniki"]; status jego kontroli liczy się do statusu dokumentu w kontrola_pliku,
    bo bezpiecznik czyta też zdekodowane załączniki."""
    wynik["zalaczniki"] = []
    for el, dane, rodzaj_zal in plik.zalaczniki:
        nazwa = f"załącznik.{rodzaj_zal}"
        try:
            if rodzaj(nazwa, dane) == "pdf_skan":
                raise BladPliku("skan")
            # pamięć klasyfikacji dokumentu jest wspólna, zapis po każdej paczce też
            wy, w = anonimizuj_plik(sesja, nazwa, dane, **opcje)
        except Exception as e:
            el.text = ""
            plik._licz("załączniki usunięte (skan albo nieczytelne)")
            wynik["zalaczniki"].append({"element": el.tag, "rodzaj": rodzaj_zal, "usuniety": True, "powod": type(e).__name__})
            continue
        plik.osadz(el, wy)
        wynik["zalaczniki"].append({"element": el.tag, "rodzaj": rodzaj_zal, "usuniety": False, "wynik": w})

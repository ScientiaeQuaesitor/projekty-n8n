"""Zestaw wzorcowy plikowy (PLAN 4.6) i pomiar anonimizacji plików (PLAN 4.8).

Uruchomienie w kontenerze:  python -m app.ewaluacja.pliki [--sesje 3] [--typ docx|pdf]

Z każdego dokumentu wzorcowego (dane fikcyjne) powstają DOCX i PDF z trudnymi miejscami:
DOCX: każdy akapit pocięty na przebiegi co kilka znaków (nazwy rozbite na runy), jeden akapit w tabeli, przedostatni
wiersz w nagłówku, ostatni w stopce, obraz w akapicie, zmiana śledzona z usuniętym nazwiskiem (w:delText), relacja
z adresem e-mail, metadane z nazwiskiem autora i nazwą firmy.
PDF: wąska kolumna, więc nazwy przechodzą przez koniec wiersza, przeniesienia długich wyrazów pisanych małą literą,
obraz, adnotacja z nazwiskiem, łącze mailto, metadane z nazwiskiem.

Miary na pliku wynikowym: wycieki (encje wzorcowe w całym tekście pliku, także metadanych i XML), zepsute (fragmenty
ZOSTAW rzadziej niż w oryginale), status kontroli pliku, różnice tekstu pliku wobec tekstu zanonimizowanego, czy plik
się otwiera. Pliki wejściowe i wynikowe zapisywane w testy/wyniki/pliki/ do obejrzenia."""
import argparse
import io
import time

import fitz
import regex as re
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from lxml import etree
from PIL import Image

from .. import pliki
from ..anonimizacja.sesja import Sesja
from ..detekcja import llm
from . import pamiec as pamiec_plik
from .scalanie import wykryj_z_cache
from .uruchom import WYNIKI
from .wzorce import wczytaj, wczytaj_zostaw

KATALOG = WYNIKI / "pliki"
CZCIONKA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(b, "PNG")
    return b.getvalue()


def _pierwszy(wzorce, typ: str, domyslny: str = "") -> str:
    return next((w.tekst for w in wzorce if w.typ == typ), domyslny)


def docx_z_wzorca(tekst: str, wzorce) -> bytes:
    linie = tekst.split("\n")
    d = Document()
    d.core_properties.author = _pierwszy(wzorce, "OSOBA", "Autor")
    d.core_properties.last_modified_by = _pierwszy(wzorce, "OSOBA", "Autor")
    d.core_properties.title = _pierwszy(wzorce, "FIRMA", "Tytuł")
    d.core_properties.comments = _pierwszy(wzorce, "ADRES", "Uwagi")
    tresc, naglowek, stopka = linie[:-2], linie[-2], linie[-1]
    srodek = len(tresc) // 2
    for i, linia in enumerate(tresc):
        if i == srodek:
            p = d.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
        else:
            p = d.add_paragraph()
        for j in range(0, len(linia), 5):
            r = p.add_run(linia[j:j + 5])
            r.bold = (j // 5) % 2 == 1
        if i == 1:
            p.add_run().add_picture(io.BytesIO(_png()), width=Pt(30))
        if i == 2:
            # Zmiana śledzona: usunięte nazwisko zostaje w pliku jako w:delText, Word go nie pokazuje
            usun = etree.SubElement(p._p, qn("w:del"), {qn("w:id"): "901", qn("w:author"): _pierwszy(wzorce, "OSOBA", "x")})
            r = etree.SubElement(usun, qn("w:r"))
            etree.SubElement(r, qn("w:delText")).text = " " + _pierwszy(wzorce, "OSOBA", "x")
    sekcja = d.sections[0]
    sekcja.header.paragraphs[0].text = naglowek
    sekcja.footer.paragraphs[0].text = stopka
    email = _pierwszy(wzorce, "EMAIL")
    if email:
        d.part.relate_to(f"mailto:{email}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                         is_external=True)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def pdf_z_wzorca(tekst: str, wzorce) -> bytes:
    d = fitz.open()
    font = fitz.Font(fontfile=CZCIONKA)
    rozmiar, szer, x0, y_min, y_max = 10, 250, 72, 72, 770
    strona, y = None, y_max

    def wiersz(t: str) -> None:
        nonlocal strona, y
        if strona is None or y > y_max:
            strona, y = d.new_page(), y_min
        if t:
            strona.insert_text((x0, y), t, fontsize=rozmiar, fontfile=CZCIONKA, fontname="F0")
        y += rozmiar * 1.25

    for akapit in tekst.split("\n"):
        biezacy = ""
        for slowo in akapit.split(" "):
            prop = (biezacy + " " + slowo) if biezacy else slowo
            if font.text_length(prop, fontsize=rozmiar) <= szer:
                biezacy = prop
                continue
            # Przeniesienie długiego wyrazu pisanego małą literą, jeśli zmieści się co najmniej 4 litery
            if slowo.isalpha() and slowo.islower() and len(slowo) >= 10:
                for n in range(len(slowo) - 3, 3, -1):
                    if font.text_length(biezacy + " " + slowo[:n] + "-", fontsize=rozmiar) <= szer:
                        wiersz(biezacy + " " + slowo[:n] + "-")
                        biezacy = slowo[n:]
                        break
                else:
                    wiersz(biezacy)
                    biezacy = slowo
                continue
            wiersz(biezacy)
            biezacy = slowo
        wiersz(biezacy)
        y += rozmiar * 0.8   # odstęp między akapitami
    pierwsza = d[0]
    pierwsza.insert_image(fitz.Rect(400, 72, 440, 92), stream=_png())
    osoba = _pierwszy(wzorce, "OSOBA", "Autor")
    pierwsza.add_text_annot((450, 80), f"Uwaga od {osoba}")
    email = _pierwszy(wzorce, "EMAIL")
    if email:
        pierwsza.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(400, 100, 440, 110), "uri": f"mailto:{email}"})
    d.set_metadata({"author": osoba, "title": _pierwszy(wzorce, "FIRMA", "Tytuł"), "subject": _pierwszy(wzorce, "ADRES", "")})
    return d.tobytes()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def _ile(fragment: str, gdzie: str) -> int:
    return len(re.findall(r"(?<![\p{L}\d])" + re.escape(_norm(fragment)) + r"(?![\p{L}\d])", gdzie))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sesje", type=int, default=3)
    ap.add_argument("--typ", default="docx,pdf")
    ap.add_argument("--llm", default=llm.LLM_MODEL)
    ap.add_argument("--klasyfikator", default=llm.LLM_MODEL_KLASYFIKACJA)
    args = ap.parse_args()
    t_start = time.time()
    KATALOG.mkdir(parents=True, exist_ok=True)
    dokumenty, zostaw = wczytaj(), wczytaj_zostaw()
    p_pamiec = pamiec_plik.sciezka(WYNIKI, "cache_klasyfikacja_", args.klasyfikator)
    pamiec = pamiec_plik.wczytaj(p_pamiec)
    zapisz_pamiec = pamiec_plik.zapisywacz(p_pamiec, args.klasyfikator)

    linie = ["# Etap 3: pliki\n", "", "| plik | tekst = wzorzec | podmiany | wycieki | zepsute | kontrola pliku do przeglądu "
             "| różnice tekstu pliku | otwiera się | usunięte z pliku |", "|---|---|---|---|---|---|---|---|---|"]
    szczegoly, suma = [], [0] * 5
    for typ in args.typ.split(","):
        for dok, (tekst, wzorce) in dokumenty.items():
            dane = docx_z_wzorca(tekst, wzorce) if typ == "docx" else pdf_z_wzorca(tekst, wzorce)
            nazwa = f"{dok}.{typ}"
            (KATALOG / nazwa).write_bytes(dane)
            model_tekst = pliki.otworz(typ, dane).model.tekst
            wykryte = wykryj_z_cache({nazwa: (model_tekst, [])}, args.llm)[nazwa]
            licz, bledy, otwiera = [0] * 5, {}, True
            for nr in range(args.sesje):
                sesja = Sesja(sciezka=":memory:", nowe_id=f"plik-{nr}")
                wyjscie, wynik = pliki.anonimizuj_plik(sesja, nazwa, dane, wykryte, pamiec=pamiec,
                                                       model_klasyfikacji=args.klasyfikator, zapisz_pamiec=zapisz_pamiec)
                if nr == 0:
                    (KATALOG / f"{dok}.anon.{typ}").write_bytes(wyjscie)
                surowy = _norm(pliki.fdocx.tekst_surowy(wyjscie) if typ == "docx" else pliki.fpdf.tekst_surowy(wyjscie))
                odczyt = _norm(pliki.otworz(typ, wyjscie).model.tekst)
                wycieki = sorted({w.tekst for w in wzorce if len(w.tekst) >= 4 and _ile(w.tekst, surowy)})
                zepsute = sorted({z.tekst for z in zostaw[dok] if _ile(z.tekst, odczyt) < _ile(z.tekst, _norm(model_tekst))})
                kp = wynik["kontrola_pliku"]
                try:
                    Document(io.BytesIO(wyjscie)) if typ == "docx" else fitz.open(stream=wyjscie, filetype="pdf").page_count
                except Exception as e:   # plik, którego biblioteka nie otwiera, jest błędem pomiaru
                    otwiera = False
                    bledy.setdefault(f"NIE OTWIERA SIĘ: {type(e).__name__}: {e}", []).append(nr)
                for i, v in enumerate((len(wynik["podmiany"]), len(wycieki), len(zepsute), kp["status"] != "ok", kp["liczba_roznic"])):
                    licz[i] += v
                for opis in ([f"WYCIEK: „{w}”" for w in wycieki] + [f"ZEPSUTE: „{z}”" for z in zepsute]
                             + [f"RÓŻNICA TEKSTU PLIKU: {r}" for r in kp["roznice_tekstu"][:5]]
                             + [f"KONTROLA PLIKU, wyciek: {t['rodzaj']} {t['kat']} „{t['tekst']}”" for t in kp["wyciek"]]
                             + [f"KONTROLA PLIKU, pozostałość: {p}" for p in kp["pozostalosci"]]):
                    bledy.setdefault(opis, []).append(nr)
            licz[0] = round(licz[0] / args.sesje)
            czyszczenie = ", ".join(f"{k} {v}" for k, v in wynik["czyszczenie"].items())
            linie.append(f"| {nazwa} | {'tak' if model_tekst == tekst else 'nie'} | " + " | ".join(map(str, licz))
                         + f" | {'tak' if otwiera else 'NIE'} | {czyszczenie} |")
            for i, v in enumerate(licz):
                suma[i] += v
            if bledy:
                szczegoly.append(f"\n## {nazwa}\n")
                szczegoly += [f"1. {o} (sesje: {', '.join(map(str, n))})" for o, n in bledy.items()]
    linie.append("| **razem** | | " + " | ".join(map(str, suma)) + " | | |")
    linie[1] = (f"Sesje na plik: {args.sesje} (id plik-0 …). Podmiany: średnio na sesję, pozostałe liczniki: suma ze wszystkich "
                f"sesji. Czas: {time.time() - t_start:.0f} s. Pliki: testy/wyniki/pliki/.\n")
    zapisz_pamiec(pamiec)
    tresc = "\n".join(linie + szczegoly) + "\n"
    (WYNIKI / "etap3_pliki.md").write_text(tresc, encoding="utf-8")
    print(tresc)


if __name__ == "__main__":
    main()

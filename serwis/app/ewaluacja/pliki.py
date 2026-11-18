"""Zestaw wzorcowy plikowy (PLAN 4.6) i pomiar anonimizacji plików (PLAN 4.8).

Uruchomienie w kontenerze:  python -m app.ewaluacja.pliki [--sesje 3] [--typ docx,pdf,xml,xlsx]

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


def pdf_z_wzorca(tekst: str, wzorce, szer: int = 250, rozmiar: int = 10) -> bytes:
    d = fitz.open()
    font = fitz.Font(fontfile=CZCIONKA)
    x0, y_min, y_max = 72, 72, 770
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


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def xml_z_wzorca(tekst: str, wzorce) -> bytes:
    """Koperta w stylu e-sprawozdania: akapity jako elementy, osoba i firma w elementach z nazwą pola, adres w atrybucie,
    komentarz z nazwiskiem, załącznik PDF (ten sam dokument) w base64 i podpis XAdES z „certyfikatem” osoby."""
    import base64
    osoba = _pierwszy(wzorce, "OSOBA", "Jan Testowy")
    imie, _, nazwisko = osoba.partition(" ")
    pesel = _pierwszy(wzorce, "PESEL")
    akapity = "".join(f"<Akapit nr=\"{i + 1}\">{_esc(l)}</Akapit>" for i, l in enumerate(tekst.split("\n")) if l.strip())
    zal = base64.b64encode(pdf_z_wzorca(tekst, wzorce)).decode()
    zal = "\n".join(zal[i:i + 76] for i in range(0, len(zal), 76))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Dokument xmlns="http://example.test/wzor/1" xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
            f'<!-- przygotował {_esc(osoba)} -->'
            f'<Naglowek><NazwaFirmy>{_esc(_pierwszy(wzorce, "FIRMA", "Firma Testowa sp. z o.o."))}</NazwaFirmy>'
            f'<Adres opis="{_esc(_pierwszy(wzorce, "ADRES", "ul. Testowa 1"))}"/></Naglowek>'
            f'<OsobaSporzadzajaca><Imie>{_esc(imie)}</Imie><Nazwisko>{_esc(nazwisko)}</Nazwisko>'
            f'<PESEL>{_esc(pesel)}</PESEL></OsobaSporzadzajaca>'
            f'<Tresc>{akapity}</Tresc>'
            f'<Zalacznik><Nazwa>informacja.pdf</Nazwa><Zawartosc>{zal}</Zawartosc></Zalacznik>'
            f'<ds:Signature><ds:SignatureValue>QUJD</ds:SignatureValue><ds:KeyInfo><ds:X509Data>'
            f'<ds:X509SubjectName>CN={_esc(osoba)}, SERIALNUMBER=PNOPL-{_esc(pesel)}</ds:X509SubjectName>'
            f'</ds:X509Data></ds:KeyInfo></ds:Signature></Dokument>').encode()


# Kwoty w komórkach liczbowych o kształcie identyfikatora: NIP z poprawną sumą kontrolną, dziesięć i dziewięć cyfr
KWOTY_JAK_NIP = ("5846254620", "1234563218", "123456785")


def xlsx_z_wzorca(tekst: str, wzorce) -> bytes:
    """Skoroszyt z dwoma arkuszami: treść dokumentu wiersz po wierszu (teksty wspólne, jeden użyty dwa razy) i lista
    osób z nagłówkiem, PESEL zapisanym jako tekst, kwotą, dziesięciocyfrową kwotą o kształcie NIP (komórka liczbowa,
    musi zostać bez zmian) i formułą z zapisaną wartością tekstową. Komentarz z nazwiskiem, metadane z autorem."""
    linie = [l for l in tekst.split("\n") if l.strip()]
    osoby = [w.tekst for w in wzorce if w.typ == "OSOBA"][:4] or ["Jan Testowy"]
    pesele = [w.tekst for w in wzorce if w.typ == "PESEL"]
    firma = re.sub(r"\s*,.*", "", _pierwszy(wzorce, "FIRMA", "Firma Testowa"))
    wspolne = linie + ["Imię i nazwisko", "PESEL", "Kwota"] + osoby
    idx = {t: i for i, t in reversed(list(enumerate(wspolne)))}
    sst = "".join(f"<si><t xml:space=\"preserve\">{_esc(t)}</t></si>" for t in wspolne)
    w1 = "".join(f'<row r="{i + 1}"><c r="A{i + 1}" t="s"><v>{idx[l]}</v></c></row>' for i, l in enumerate(linie + linie[:1]))
    w2 = ['<row r="1"><c r="A1" t="s"><v>{}</v></c><c r="B1" t="s"><v>{}</v></c><c r="C1" t="s"><v>{}</v></c></row>'.format(
        idx["Imię i nazwisko"], idx["PESEL"], idx["Kwota"])]
    for j, o in enumerate(osoby):
        r = j + 2
        pesel = re.sub(r"\D", "", pesele[j % len(pesele)]) if pesele else ""
        w2.append(f'<row r="{r}"><c r="A{r}" t="s"><v>{idx[o]}</v></c>'
                  + (f'<c r="B{r}" t="inlineStr"><is><t>{pesel}</t></is></c>' if pesel else "")
                  + f'<c r="C{r}"><v>{1250.5 * r}</v></c><c r="H{r}"><v>{KWOTY_JAK_NIP[j % len(KWOTY_JAK_NIP)]}</v></c><c r="D{r}" t="str"><f>A{r}</f><v>{_esc(o)}</v></c>'
                  + f'<c r="E{r}"><f>C{r}-C{r + 1}</f><v>-1250.5</v></c>'
                  + f'<c r="F{r}" t="str"><f>"kontakt: "&amp;A{r}&amp;" ({_esc(firma).replace(chr(34), chr(34) * 2)})"</f>'
                  + f'<v>kontakt: {_esc(o)} ({_esc(firma)})</v></c></row>')
    # Lista rozwijana (walidacja danych) z nazwą firmy: Excel trzyma ją w formule, poza komórkami
    walidacja = (f'<dataValidations count="1"><dataValidation type="list" sqref="G2:G9"><formula1>"{_esc(firma).replace(chr(34), chr(34) * 2)},inna"'
                 f'</formula1></dataValidation></dataValidations>')
    arkusz = lambda wiersze, extra="": (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{pliki.fxlsx.M}" '
                                        f'xmlns:r="{pliki.fxlsx.R}"><sheetData>{wiersze}</sheetData>{extra}</worksheet>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
          '<Override PartName="/xl/comments1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    czesci = {
        "[Content_Types].xml": ct,
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/>'
                       f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
        "docProps/core.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                             f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>{_esc(osoby[0])}</dc:creator></cp:coreProperties>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{pliki.fxlsx.M}" xmlns:r="{rel}"><sheets>'
                           f'<sheet name="Treść" sheetId="1" r:id="rId1"/><sheet name="Lista" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
                                      f'<Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/>'
                                      f'<Relationship Id="rId3" Type="{rel}/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{pliki.fxlsx.M}">{sst}</sst>',
        "xl/worksheets/sheet1.xml": arkusz(w1),
        "xl/worksheets/sheet2.xml": arkusz("".join(w2), walidacja),
        "xl/worksheets/_rels/sheet2.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                               f'<Relationship Id="rId1" Type="{rel}/comments" Target="../comments1.xml"/></Relationships>',
        "xl/comments1.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><comments xmlns="{pliki.fxlsx.M}"><authors><author>{_esc(osoby[0])}</author></authors>'
                            f'<commentList><comment ref="A2" authorId="0"><text><t>Sprawdzić u {_esc(osoby[-1])}</t></text></comment></commentList></comments>',
    }
    b = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, t in czesci.items():
            z.writestr(n, t)
    return b.getvalue()


def _liczby_xlsx(dane: bytes) -> dict:
    """(arkusz, adres) -> wartość każdej komórki liczbowej."""
    import zipfile
    from lxml import etree
    out = {}
    with zipfile.ZipFile(io.BytesIO(dane)) as z:
        for n in z.namelist():
            if pliki.fxlsx.RX_ARKUSZ.fullmatch(n):
                for c in etree.fromstring(z.read(n)).iter(f"{{{pliki.fxlsx.M}}}c"):
                    v = c.find(f"{{{pliki.fxlsx.M}}}v")
                    if c.get("t", "n") == "n" and v is not None:
                        out[(n, c.get("r"))] = v.text
    return out


GENERATORY = {"docx": docx_z_wzorca, "pdf": pdf_z_wzorca, "xml": xml_z_wzorca, "xlsx": xlsx_z_wzorca}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sesje", type=int, default=3)
    ap.add_argument("--typ", default="docx,pdf,xml,xlsx")
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
            dane = GENERATORY[typ](tekst, wzorce)
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
                surowy = _norm((pliki.MODULY.get(typ) or pliki.fpdf).tekst_surowy(wyjscie))
                odczyt = _norm(pliki.otworz(typ, wyjscie).model.tekst)
                wycieki = sorted({w.tekst for w in wzorce if len(w.tekst) >= 4 and _ile(w.tekst, surowy)})
                if typ == "pdf":
                    # PDF: tekst czytany w kolejności geometrycznej (sort=True). Kolejność strumienia pliku wynikowego
                    # rozdziela wiersz, w którym wstawiono surogat („Z Lokalem” i „Mieszkalnym”), choć na stronie tekst
                    # stoi w miejscu
                    geo = lambda b: _norm(" ".join(s.get_text("text", sort=True) for s in fitz.open(stream=b, filetype="pdf")))
                    geo_wy, geo_we = geo(wyjscie), geo(dane)
                    zepsute = sorted({z.tekst for z in zostaw[dok] if _ile(z.tekst, geo_wy) < _ile(z.tekst, geo_we)})
                else:
                    zepsute = sorted({z.tekst for z in zostaw[dok] if _ile(z.tekst, odczyt) < _ile(z.tekst, _norm(model_tekst))})
                if typ == "xlsx":
                    # Komórki liczbowe muszą zostać znak w znak (kwota o kształcie NIP też)
                    przed, po = _liczby_xlsx(dane), _liczby_xlsx(wyjscie)
                    zepsute += sorted(f"liczba {k}: {v}" for k, v in przed.items() if po.get(k) != v)
                kp = wynik["kontrola_pliku"]
                try:
                    Document(io.BytesIO(wyjscie)) if typ == "docx" else fitz.open(stream=wyjscie, filetype="pdf").page_count if typ == "pdf" else pliki.otworz(typ, wyjscie)
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

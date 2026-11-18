"""XLSX (PLAN 4.9.1): tekst komórek arkuszy, podmiana w miejscu na poziomie XML (lxml), formatowanie bez zmian.

Kawałek to tekst komórki (element t w is, z przebiegami tekstu sformatowanego), wartość tekstowa wyniku formuły
(t="str", wartość zapisana w pliku) i tekst nagłówka lub stopki wydruku. Komórki liczbowe (kwoty, daty, każda liczba
zapisana jako liczba) nie trafiają do tekstu ciągłego ani do kontroli wycieku i nigdy nie są zmieniane: liczby są
danymi do analizy, a dziesięciocyfrowa kwota ma kształt NIP (decyzja użytkownika, PRZEKAZANIE 2.00.17). Identyfikator
zapisany jako tekst (PESEL z zerem na początku, NIP z kreskami) jest anonimizowany jak w każdym dokumencie.

Tekst ciągły: arkusz po arkuszu, wiersz po wierszu, komórki wiersza rozdzielone „ | ”. Nagłówki kolumn stoją w wierszu
nad danymi, więc detekcja i klasyfikacja mają kontekst kolumny („Nazwisko | PESEL” nad „Kowalski | 85…”).

Czyszczenie przed odczytem:
1. Teksty wspólne (sharedStrings) są przenoszone do komórek (t="inlineStr"), a lista wspólna jest opróżniana: jeden
   tekst wspólny bywa użyty w wielu komórkach, a podmiana ma dotyczyć konkretnej komórki, i w pliku nie może zostać
   lista oryginałów.
2. Komentarze i notatki, osoby z wątków komentarzy, rysunki i obrazy, połączenia zewnętrzne, dane własne
   i niestandardowe XML, ustawienia drukarki, metadane (jak w DOCX) są usuwane.
3. Pamięć podręczna tabel przestawnych (kopia danych źródłowych) jest usuwana; tabela odświeży się przy otwarciu.
4. Skoroszyt dostaje fullCalcOnLoad: formuły przeliczą się po otwarciu na danych po podmianie.
Nazwy arkuszy i nazwy zdefiniowane nie są zmieniane (odwołują się do nich formuły). Kontrola pliku czyta je razem
z całą resztą, więc nazwisko w nazwie arkusza daje status do przeglądu."""
import io
import zipfile

import regex as re
from lxml import etree

from . import docx as fdocx
from .model import Model, zastosuj

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = fdocx.R
NS = {"m": M}

USUWANE = ("xl/comments", "xl/threadedComments/", "xl/persons/", "xl/drawings/", "xl/media/", "xl/externalLinks/",
           "xl/pivotCache/pivotCacheRecords", "xl/printerSettings/", "xl/embeddings/", "xl/ctrlProps/",
           "customXml/", "docProps/custom.xml", "docProps/thumbnail", "xl/sharedStrings.xml")
TYPY_RELACJI_USUWANE = ("/comments", "/threadedComment", "/person", "/drawing", "/vmlDrawing", "/image", "/externalLink",
                        "/pivotCacheRecords", "/printerSettings", "/oleObject", "/package", "/customXml",
                        "/custom-properties", "/thumbnail", "/sharedStrings", "/ctrlProp", "/hyperlink")
RX_ARKUSZ = re.compile(r"xl/worksheets/sheet\d+\.xml")
# Tekst w cudzysłowie wewnątrz formuły („="Kowalski"”) i lista wartości walidacji („"Firma A,Firma B"”): jedyne miejsca
# formuły, w których mogą stać dane; odwołania do komórek („B12-C12”) nie są ani danymi, ani numerami
RX_LITERAL = re.compile(r'"((?:[^"]|"")*)"')
FORMULY = ("f", "formula", "formula1", "formula2")


def _m(tag: str) -> str:
    return f"{{{M}}}{tag}"


class Xlsx:
    def __init__(self, dane: bytes):
        with zipfile.ZipFile(io.BytesIO(dane)) as z:
            self.pliki = {n: z.read(n) for n in z.namelist()}
        self.xml: dict[str, etree._Element] = {}
        self.czyszczenie: dict[str, int] = {}
        self._wyczysc()
        self.model = self._model()

    _licz = fdocx.Docx._licz

    def _arkusze(self) -> list[str]:
        """Arkusze w kolejności skoroszytu (workbook.xml i jego relacje), nie w kolejności nazw części."""
        wb = etree.fromstring(self.pliki["xl/workbook.xml"])
        rel = etree.fromstring(self.pliki["xl/_rels/workbook.xml.rels"])
        cele = {r.get("Id"): r.get("Target") for r in rel}
        out = []
        for s in wb.iterfind(".//m:sheet", NS):
            cel = cele.get(s.get(f"{{{R}}}id"), "")
            n = cel.lstrip("/") if cel.startswith("/") else "xl/" + cel
            if RX_ARKUSZ.fullmatch(n) and n in self.pliki:
                out.append(n)
        return out

    def _wyczysc(self) -> None:
        wspolne = []
        if "xl/sharedStrings.xml" in self.pliki:
            wspolne = etree.fromstring(self.pliki["xl/sharedStrings.xml"]).findall("m:si", NS)
        for n in self._arkusze():
            x = etree.fromstring(self.pliki[n])
            for c in x.iter(_m("c")):
                if c.get("t") == "s":
                    v = c.find("m:v", NS)
                    si = wspolne[int(v.text)] if v is not None and v.text and int(v.text) < len(wspolne) else None
                    c.remove(v) if v is not None else None
                    c.set("t", "inlineStr")
                    is_ = etree.SubElement(c, _m("is"))
                    for dz in (si if si is not None else []):
                        if etree.QName(dz).localname in ("t", "r"):
                            is_.append(etree.fromstring(etree.tostring(dz)))
                    self._licz("teksty wspólne przeniesione do komórek")
                # Wymowa fonetyczna (rPh) bywa kopią tekstu
                for el in list(c.iter(_m("rPh"), _m("phoneticPr"))):
                    el.getparent().remove(el)
            for el in list(x.iter(_m("legacyDrawing"), _m("legacyDrawingHF"), _m("drawing"), _m("picture"))):
                el.getparent().remove(el)
                self._licz("rysunki i obrazy")
            self.xml[n] = x
        for n in list(self.pliki):
            if n.startswith(USUWANE):
                del self.pliki[n]
                if n != "xl/sharedStrings.xml":
                    self._licz("usunięte części")
        for n in [n for n in self.pliki if n.endswith(".rels")]:
            x = etree.fromstring(self.pliki[n])
            usuniete = set()
            for rel in list(x):
                if rel.get("Type", "").endswith(TYPY_RELACJI_USUWANE) or rel.get("TargetMode") == "External":
                    usuniete.add(rel.get("Id"))
                    x.remove(rel)
            self.pliki[n] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)
            czesc = n.replace("_rels/", "").removesuffix(".rels")
            if usuniete and czesc in self.xml:
                for el in list(self.xml[czesc].iter(_m("hyperlink"))):
                    if el.get(f"{{{R}}}id") in usuniete:
                        el.getparent().remove(el)
                        self._licz("hiperłącza")
        # Typy zawartości usuniętych części
        x = etree.fromstring(self.pliki["[Content_Types].xml"])
        for el in list(x):
            if el.get("PartName", "").lstrip("/").startswith(USUWANE):
                x.remove(el)
        self.pliki["[Content_Types].xml"] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)
        # Skoroszyt: przeliczenie formuł przy otwarciu, bez odwołań do usuniętej pamięci tabel przestawnych
        wb = etree.fromstring(self.pliki["xl/workbook.xml"])
        calc = wb.find("m:calcPr", NS)
        if calc is None:
            calc = etree.SubElement(wb, _m("calcPr"))
        calc.set("fullCalcOnLoad", "1")
        for el in list(wb.iter(_m("fileSharing"))):   # nazwa użytkownika z ochrony przed zapisem
            el.getparent().remove(el)
        self.xml["xl/workbook.xml"] = wb
        fdocx.Docx._metadane(self)

    def _model(self) -> Model:
        m = Model()
        for nr, n in enumerate(self._arkusze()):
            if nr:
                m.separator("\n\n")
            pierwszy_wiersz = True
            for row in self.xml[n].iter(_m("row")):
                komorki = []
                for c in row.iterfind("m:c", NS):
                    t = c.get("t", "n")
                    if t == "inlineStr":
                        el = [e for e in c.iter(_m("t")) if e.text]
                        if el:
                            komorki.append(el)
                    elif t == "str":
                        v = c.find("m:v", NS)
                        if v is not None and v.text:
                            komorki.append([v])
                if not komorki:
                    continue
                if not pierwszy_wiersz:
                    m.separator("\n")
                pierwszy_wiersz = False
                for i, el in enumerate(komorki):
                    if i:
                        m.separator(" | ")
                    for e in el:
                        m.dodaj(e.text, (n, e))
            # Teksty w formułach i listach wyboru (walidacja danych), z odwołaniem do zakresu w elemencie
            # Lista wyboru „"A,B"” to osobne wartości rozdzielone przecinkiem: każda jest osobnym kawałkiem
            literaly = []
            for el in self.xml[n].iter(*(_m(f) for f in FORMULY)):
                for mm in RX_LITERAL.finditer(el.text or ""):
                    if etree.QName(el).localname == "f":
                        czesci = [(mm.start(1), mm.end(1))]
                    else:
                        czesci = [(mm.start(1) + x.start(), mm.start(1) + x.end()) for x in re.finditer(r"[^,]+", mm.group(1))]
                    literaly += [(el, a, b) for a, b in czesci if re.search(r"\p{L}", el.text[a:b])]
            for i, (el, a, b) in enumerate(literaly):
                m.separator("\n" if i == 0 else " | ")
                m.dodaj(el.text[a:b], (n, el, a, b))
            # Nagłówek i stopka wydruku (kody formatowania &L, &C, &R zostają w tekście kawałka)
            for el in self.xml[n].iter(_m("oddHeader"), _m("oddFooter"), _m("evenHeader"), _m("evenFooter"),
                                       _m("firstHeader"), _m("firstFooter")):
                if el.text and el.text.strip():
                    m.separator("\n")
                    m.dodaj(el.text, (n, el))
        return m.zamknij()

    def podmien(self, podmiany: list[dict]) -> None:
        # Kawałki będące częścią tekstu elementu (tekst w cudzysłowie w formule) od prawej, żeby pozycje
        # wcześniejszych kawałków tego samego elementu się nie przesunęły
        zmiany = sorted(self.model.edycje(podmiany).items(), key=lambda ke: -(self.model.kawalki[ke[0]][2] if len(self.model.kawalki[ke[0]]) > 2 else 0))
        for k, edycje in zmiany:
            n, el, *zakres = self.model.kawalki[k]
            if zakres:
                a, b = zakres
                el.text = el.text[:a] + zastosuj(el.text[a:b], edycje) + el.text[b:]
                continue
            el.text = zastosuj(el.text, edycje)
            if etree.QName(el).localname == "t":
                el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def zapisz(self) -> bytes:
        for n, x in self.xml.items():
            self.pliki[n] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in sorted(self.pliki, key=lambda n: n != "[Content_Types].xml"):
                z.writestr(n, self.pliki[n])
        return buf.getvalue()


def tekst_surowy(dane: bytes) -> str:
    """Jak w DOCX: wszystkie części XML (komórki, nazwy arkuszy i zdefiniowane, metadane), część binarna zgłaszana.
    Z formuł tylko teksty w cudzysłowie. Wartości komórek innych niż tekstowe (liczby, daty, wartości logiczne, błędy)
    są pomijane: nie są zmieniane, więc kontrola nie może ich zgłaszać jako numer bez podmiany."""
    with zipfile.ZipFile(io.BytesIO(dane)) as z:
        pliki = {}
        for n in z.namelist():
            tresc = z.read(n)
            if n.endswith(".xml"):
                x = etree.fromstring(tresc)
                for el in x.iter(*(_m(f) for f in FORMULY)):
                    if el.text:
                        el.text = " ¦ ".join(mm.group(1) for mm in RX_LITERAL.finditer(el.text))
                if RX_ARKUSZ.fullmatch(n):
                    for c in x.iter(_m("c")):
                        if c.get("t", "n") in ("n", "d", "b", "e"):
                            for v in c.iterfind("m:v", NS):
                                v.text = None
                tresc = etree.tostring(x)
            pliki[n] = tresc
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in pliki.items():
            z.writestr(n, t)
    return fdocx.tekst_surowy(buf.getvalue())

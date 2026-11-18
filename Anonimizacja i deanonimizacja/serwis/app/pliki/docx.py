"""DOCX: tekst ciągły z wszystkich części z treścią i podmiana w miejscu (PLAN 4.3).

Praca na XML (lxml), bo python-docx nie daje dostępu do przypisów, pól tekstowych ani kodów pól. Kawałek to element
w:t (tekst przebiegu) albo w:instrText (kod pola, np. adres e-mail w HYPERLINK). Kolejność części: treść główna (tabele
na swoich miejscach, pola tekstowe tam, gdzie są zakotwiczone), przypisy dolne i końcowe, nagłówki, stopki.

Przed odczytem tekstu dokument jest czyszczony: zmiany śledzone przyjęte (usunięty tekst w:delText znika), komentarze,
obrazy, osadzone obiekty, hiperłącza zewnętrzne i metadane usunięte. Dzięki temu do tekstu ciągłego, a więc do
detekcji i kontroli, trafia dokładnie to, co zostanie w pliku."""
import io
import re
import zipfile
from pathlib import Path

from lxml import etree

from .model import Model, zastosuj

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"w": W, "r": R}


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


# Części z treścią, w kolejności czytania
CZESCI_TRESCI = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
PREFIKSY_TRESCI = ("word/header", "word/footer")
# Części usuwane w całości: komentarze, metadane własne, dane niestandardowe, osadzone obiekty i obrazy, miniatura
USUWANE = ("word/comments", "word/commentsExtended", "word/commentsIds", "word/commentsExtensible", "word/people.xml",
           "docProps/custom.xml", "customXml/", "word/media/", "word/embeddings/", "docProps/thumbnail", "word/glossary/")
TYPY_RELACJI_USUWANE = ("/comments", "/commentsExtended", "/commentsIds", "/commentsExtensible", "/people", "/custom-properties",
                        "/customXml", "/image", "/oleObject", "/package", "/thumbnail", "/glossaryDocument", "/hyperlink",
                        "/attachedTemplate")


class Docx:
    def __init__(self, dane: bytes):
        self.pliki: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(dane)) as z:
            for n in z.namelist():
                self.pliki[n] = z.read(n)
        self.xml: dict[str, etree._Element] = {}
        self.czyszczenie: dict[str, int] = {}
        self._wyczysc()
        self.model = self._model()

    # ---------- czyszczenie ----------

    def _licz(self, co: str, n: int = 1) -> None:
        if n:
            self.czyszczenie[co] = self.czyszczenie.get(co, 0) + n

    def _czesci_tresci(self) -> list[str]:
        ini = [n for n in CZESCI_TRESCI if n in self.pliki]
        nf = [n for n in self.pliki if n.startswith(PREFIKSY_TRESCI) and n.endswith(".xml")]
        # nagłówki przed stopkami, w obrębie rodzaju według numeru części
        return ini + sorted(nf, key=lambda n: (n.startswith("word/footer"), len(n), n))

    def _wyczysc(self) -> None:
        for n in list(self.pliki):
            if n.startswith(USUWANE):
                del self.pliki[n]
                self._licz("usunięte części")
        for n in self._czesci_tresci():
            x = etree.fromstring(self.pliki[n])
            # Zmiany śledzone: wstawienia zostają, usunięcia znikają, zapis zmian formatowania znika. Wstawka z innego
            # pliku (altChunk) znika razem z relacją.
            usun = [el for el in x.iter(_w("del"), _w("moveFrom"), _w("rPrChange"), _w("pPrChange"), _w("sectPrChange"),
                                        _w("tblPrChange"), _w("trPrChange"), _w("tcPrChange"), _w("numberingChange"),
                                        _w("moveFromRangeStart"), _w("moveFromRangeEnd"), _w("moveToRangeStart"), _w("moveToRangeEnd"),
                                        _w("commentRangeStart"), _w("commentRangeEnd"), _w("commentReference"), _w("altChunk"))]
            self._licz("zmiany śledzone i komentarze", len(usun))
            for el in usun:
                el.getparent().remove(el)
            for el in list(x.iter(_w("ins"), _w("moveTo"))):
                self._rozpakuj(el)
            # Obrazy i obiekty: rysunek bez pola tekstowego znika, z polem tekstowym zostaje bez obrazów
            for el in list(x.iter(_w("drawing"), _w("pict"), _w("object"))):
                if el.getparent() is None:
                    continue
                if not list(el.iter(_w("txbxContent"))):
                    el.getparent().remove(el)
                    self._licz("obrazy i obiekty")
            for el in list(x.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip",
                                  "{urn:schemas-microsoft-com:vml}imagedata")):
                el.getparent().remove(el)
                self._licz("obrazy i obiekty")
            # Hiperłącza: przebiegi zostają, adres (relacja zewnętrzna) znika
            for el in list(x.iter(_w("hyperlink"))):
                self._rozpakuj(el)
                self._licz("hiperłącza")
            self.xml[n] = x
        # Relacje do usuniętych części i adresów zewnętrznych. Odwołania r:id do usuniętych relacji znikają z XML części,
        # żeby Word nie zgłaszał uszkodzonej zawartości.
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
                for el in self.xml[czesc].iter():
                    for atr in [a for a in el.attrib if a.startswith(f"{{{R}}}") and el.get(a) in usuniete]:
                        del el.attrib[atr]
        if "[Content_Types].xml" in self.pliki:
            x = etree.fromstring(self.pliki["[Content_Types].xml"])
            for el in list(x):
                if el.get("PartName", "").lstrip("/").startswith(USUWANE):
                    x.remove(el)
            self.pliki["[Content_Types].xml"] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)
        self._metadane()
        # Ustawienia: identyfikatory sesji edycji (rsid) i przypięty szablon
        if "word/settings.xml" in self.pliki:
            x = etree.fromstring(self.pliki["word/settings.xml"])
            for el in list(x.iter(_w("rsids"), _w("attachedTemplate"), _w("docVars"))):   # zmienne dokumentu bywają danymi
                el.getparent().remove(el)
            self.pliki["word/settings.xml"] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)

    @staticmethod
    def _rozpakuj(el) -> None:
        rodzic, i = el.getparent(), el.getparent().index(el)
        for dz in list(el):
            rodzic.insert(i, dz)
            i += 1
        rodzic.remove(el)

    def _metadane(self) -> None:
        """Właściwości dokumentu: wszystkie pola tekstowe opróżnione (autor, ostatnio zmieniał, tytuł, temat, firma,
        menedżer, słowa kluczowe, komentarze), daty zostają jako ogólne."""
        for n in ("docProps/core.xml", "docProps/app.xml"):
            if n not in self.pliki:
                continue
            x = etree.fromstring(self.pliki[n])
            for el in x.iter():
                if el is x or len(el):
                    continue
                lokalna = etree.QName(el).localname
                if lokalna in ("created", "modified", "Application", "AppVersion", "DocSecurity", "Template", "TotalTime",
                               "Pages", "Words", "Characters", "CharactersWithSpaces", "Lines", "Paragraphs", "ScaleCrop",
                               "LinksUpToDate", "SharedDoc", "HyperlinksChanged"):
                    if lokalna == "Template":
                        el.text = "Normal.dotm"
                    continue
                if el.text:
                    el.text = ""
                    self._licz("pola metadanych")
            # Lista tytułów części (app.xml) bywa kopią nagłówków: usuwana
            for el in list(x):
                if etree.QName(el).localname in ("TitlesOfParts", "HeadingPairs"):
                    x.remove(el)
            self.pliki[n] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)

    # ---------- model ----------

    def _model(self) -> Model:
        m = Model()
        pierwszy = True
        for n in self._czesci_tresci():
            for p in self.xml[n].iter(_w("p")):
                if not pierwszy:
                    m.separator("\n")
                pierwszy = False
                for el in p.iter(_w("t"), _w("tab"), _w("br"), _w("cr"), _w("instrText")):
                    if self._akapit(el) is not p:
                        continue   # akapit zagnieżdżony (pole tekstowe zakotwiczone w akapicie) ma własny wpis w iteracji
                    if el.tag == _w("t"):
                        if el.text:
                            m.dodaj(el.text, (n, el))
                    elif el.tag == _w("instrText"):
                        # Kod pola (HYPERLINK "mailto:…", MERGEFIELD) jest w pliku, choć Word go nie pokazuje: do detekcji
                        # trafia oddzielony spacjami, żeby nie sklejał się ze słowami akapitu
                        if el.text and el.text.strip():
                            m.separator(" ")
                            m.dodaj(el.text, (n, el))
                            m.separator(" ")
                    elif el.tag == _w("tab"):
                        m.separator("\t")
                    else:
                        m.separator("\n")
        return m.zamknij()

    @staticmethod
    def _akapit(el):
        while el is not None and el.tag != _w("p"):
            el = el.getparent()
        return el

    # ---------- podmiana i zapis ----------

    def podmien(self, podmiany: list[dict]) -> None:
        for k, edycje in self.model.edycje(podmiany).items():
            _, el = self.model.kawalki[k]
            el.text = zastosuj(el.text, edycje)
            # Spacje na brzegach są w Wordzie zachowane tylko z xml:space="preserve"
            el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def zapisz(self) -> bytes:
        for n, x in self.xml.items():
            self.pliki[n] = etree.tostring(x, xml_declaration=True, encoding="UTF-8", standalone=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            # [Content_Types].xml pierwszy, jak w plikach Worda
            for n in sorted(self.pliki, key=lambda n: n != "[Content_Types].xml"):
                z.writestr(n, self.pliki[n])
        return buf.getvalue()


# Atrybuty, w których Word zapisuje dane użytkownika: cel relacji (adres e-mail, ścieżka), autor i inicjały zmian
# i komentarzy, opis i tytuł obrazu lub kształtu (tekst alternatywny), nazwa zmiennej dokumentu. Pozostałe atrybuty to
# formatowanie, wymiary i identyfikatory: regexy numerów dawały na nich fałszywe alarmy („script="Hans"” w motywie).
ATRYBUTY_DANYCH = {"Target", "author", "initials", "descr", "title", "name", "userId", "providerId"}
SEPARATOR = " ¦ "   # rozdziela wartości tak, żeby regexy numerów nie łączyły sąsiednich liczb w jeden numer


def tekst_surowy(dane: bytes) -> str:
    """Tekst ze wszystkich części XML pliku (węzły tekstowe i atrybuty z danymi), do kontroli wycieku na pliku:
    obejmuje też metadane, relacje i części, których model nie czyta. Część binarna jest zgłaszana z nazwy."""
    out = []
    with zipfile.ZipFile(io.BytesIO(dane)) as z:
        for n in z.namelist():
            if not (n.endswith(".xml") or n.endswith(".rels")):
                out.append(f"[część binarna {n}]")
                continue
            x = etree.fromstring(z.read(n))
            ostatni_akapit = None
            for el in x.iter():
                if not isinstance(el.tag, str):
                    continue
                lokalna = etree.QName(el).localname
                if lokalna in ("t", "delText", "instrText") and el.text:
                    # Przebiegi jednego akapitu sklejone bez separatora, jak w tekście ciągłym: numer rozcięty na
                    # przebiegi („UI/20” + „25/04”) inaczej wyglądałby dla regexów jak inny, niepodmieniony numer
                    akapit = Docx._akapit(el)
                    if akapit is not None and akapit is ostatni_akapit and out:
                        out[-1] += el.text
                    else:
                        out.append(el.text)
                    ostatni_akapit = akapit
                elif el.text and el.text.strip():
                    out.append(el.text)
                    ostatni_akapit = None
                atrybuty = [v for a, v in el.attrib.items() if etree.QName(a).localname in ATRYBUTY_DANYCH and v.strip()
                            and not (a == "Target" and not re.search(r"[:@\\]|^/", v))]
                if atrybuty:
                    out.extend(atrybuty)
                    ostatni_akapit = None
    return SEPARATOR.join(out)


def otworz(sciezka: Path) -> Docx:
    return Docx(Path(sciezka).read_bytes())

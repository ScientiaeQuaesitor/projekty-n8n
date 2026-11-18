"""XML (PLAN 4.9.2): tekst elementów i wartości atrybutów, podmiana w miejscu, przestrzenie nazw i kolejność bez zmian.

Kawałek to tekst elementu, tekst po elemencie (treść mieszana) albo wartość atrybutu. W tekście ciągłym każdy kawałek
stoi w osobnym wierszu poprzedzonym nazwą elementu („Nazwisko: …”, „Nazwa firmy: …”) jako separatorem: pojedyncza
wartość nie ma zdania wokół siebie, a nazwa elementu daje detekcji i klasyfikacji kontekst. Separator nie istnieje
w pliku, więc podmiana go nie dotyka.

Czyszczenie przed odczytem:
1. Podpis elektroniczny (ds:Signature, XAdES) jest usuwany: po zmianie treści i tak traci ważność, a certyfikat
   zawiera dane podpisującego (imię, nazwisko, często PESEL).
2. Komentarze i instrukcje przetwarzania (poza xml-stylesheet) są usuwane: bywają notatkami z danymi.
3. Załącznik zakodowany w base64 (e-sprawozdanie: dodatkowe informacje w PDF): DOCX i PDF cyfrowy są anonimizowane
   w tej samej sesji i osadzane z powrotem (robi to pliki.anonimizuj_plik), każdy inny jest usuwany.
Encje zewnętrzne nie są rozwijane ani pobierane (resolve_entities=False, no_network)."""
import base64
import io

import regex as re
from lxml import etree

from .model import Model, zastosuj

DS = "http://www.w3.org/2000/09/xmldsig#"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
MIN_BASE64 = 200   # znaków: krótsze ciągi z samych liter i cyfr to zwykłe wartości, nie załączniki
RX_BASE64 = re.compile(r"[A-Za-z0-9+/=\s]+")


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, remove_blank_text=False)


def nazwa_elementu(el) -> str:
    """„NazwaFirmy” -> „Nazwa firmy”, „P_6A” -> „P 6A”: nazwa czytelna dla detekcji."""
    n = etree.QName(el).localname.replace("_", " ")
    n = re.sub(r"(?<=\p{Ll})(?=\p{Lu})", " ", n)
    return n[:1] + n[1:].lower() if not n.isupper() else n


def _zalacznik(tekst: str | None) -> bytes | None:
    if not tekst or len(tekst) < MIN_BASE64 or not RX_BASE64.fullmatch(tekst):
        return None
    try:
        return base64.b64decode(re.sub(r"\s+", "", tekst), validate=True)
    except ValueError:
        return None


def rodzaj_zalacznika(dane: bytes) -> str:
    if dane[:5] == b"%PDF-":
        return "pdf"
    if dane[:2] == b"PK" and b"word/" in dane[:4000]:
        return "docx"
    return "inny"


def zakoduj(dane: bytes, wzor: str) -> str:
    """base64 w układzie wierszy oryginału (długość wiersza i znak końca wiersza), żeby plik wyglądał jak wcześniej."""
    t = base64.b64encode(dane).decode()
    wiersze = wzor.strip().splitlines()
    if len(wiersze) > 1:
        n = len(wiersze[0])
        nl = "\r\n" if "\r\n" in wzor else "\n"
        t = nl.join(t[i:i + n] for i in range(0, len(t), n))
    return t


class Xml:
    def __init__(self, dane: bytes):
        self.drzewo = etree.parse(io.BytesIO(dane), _parser())
        self.czyszczenie: dict[str, int] = {}
        # załączniki do anonimizacji: (element, bajty, rodzaj); element trzyma base64 do czasu osadzenia wyniku
        self.zalaczniki: list[tuple] = []
        self._wyczysc()
        self.model = self._model()

    def _licz(self, co: str, n: int = 1) -> None:
        if n:
            self.czyszczenie[co] = self.czyszczenie.get(co, 0) + n

    def _wyczysc(self) -> None:
        r = self.drzewo.getroot()
        for el in [e for e in r.iter(f"{{{DS}}}Signature")]:
            el.getparent().remove(el)
            self._licz("podpisy elektroniczne (usunięte, tracą ważność)")
        for el in [e for e in r.iter() if isinstance(e, etree._Comment)]:
            self._usun_z_ogonem(el)
            self._licz("komentarze")
        for el in [e for e in r.iter() if isinstance(e, etree._ProcessingInstruction)]:
            self._usun_z_ogonem(el)
            self._licz("instrukcje przetwarzania")
        # Komentarze i instrukcje poza korzeniem (przed nim i po nim)
        for el in list(r.itersiblings(preceding=True)) + list(r.itersiblings()):
            if isinstance(el, etree._Comment) or (isinstance(el, etree._ProcessingInstruction) and el.target != "xml-stylesheet"):
                self._usun_z_ogonem(el)
                self._licz("komentarze" if isinstance(el, etree._Comment) else "instrukcje przetwarzania")
        for el in r.iter():
            if not isinstance(el.tag, str):
                continue
            dane = _zalacznik(el.text)
            if dane is None:
                continue
            rodzaj = rodzaj_zalacznika(dane)
            if rodzaj in ("pdf", "docx"):
                self.zalaczniki.append((el, dane, rodzaj))
            else:
                el.text = ""
                self._licz("załączniki usunięte (format bez anonimizacji)")

    @staticmethod
    def _usun_z_ogonem(el) -> None:
        """Usuwa węzeł, zostawiając jego ogon (tekst po węźle) na miejscu."""
        rodzic = el.getparent()
        if rodzic is None:
            return
        if el.tail:
            poprz = el.getprevious()
            if poprz is not None:
                poprz.tail = (poprz.tail or "") + el.tail
            else:
                rodzic.text = (rodzic.text or "") + el.tail
        rodzic.remove(el)

    def _model(self) -> Model:
        m = Model()
        zalaczniki = {id(el) for el, _, _ in self.zalaczniki}
        pierwszy = True

        def wpis(etykieta: str, tekst: str, adres) -> None:
            nonlocal pierwszy
            m.separator(("" if pierwszy else "\n") + etykieta + ": ")
            pierwszy = False
            m.dodaj(tekst, adres)

        for el in self.drzewo.getroot().iter():
            if not isinstance(el.tag, str):
                continue
            nazwa = nazwa_elementu(el)
            for a, v in el.attrib.items():
                q = etree.QName(a)
                # Atrybuty techniczne: przestrzeń xsi (schemaLocation, type), adresy URI
                if q.namespace == XSI or "://" in v or not re.search(r"[\p{L}\d]", v):
                    continue
                wpis(f"{nazwa} {q.localname}", v, ("atrybut", el, a))
            if el.text and el.text.strip() and id(el) not in zalaczniki:
                wpis(nazwa, el.text, ("tekst", el))
            if el.tail and el.tail.strip() and el.getparent() is not None:
                wpis(nazwa_elementu(el.getparent()), el.tail, ("ogon", el))
        return m.zamknij()

    def podmien(self, podmiany: list[dict]) -> None:
        for k, edycje in self.model.edycje(podmiany).items():
            rodzaj, el, *reszta = self.model.kawalki[k]
            if rodzaj == "tekst":
                el.text = zastosuj(el.text, edycje)
            elif rodzaj == "ogon":
                el.tail = zastosuj(el.tail, edycje)
            else:
                el.set(reszta[0], zastosuj(el.get(reszta[0]), edycje))

    def osadz(self, el, dane: bytes) -> None:
        el.text = zakoduj(dane, el.text or "")

    def zapisz(self) -> bytes:
        di = self.drzewo.docinfo
        return etree.tostring(self.drzewo, xml_declaration=True, encoding=di.encoding or "UTF-8",
                              standalone=di.standalone)


SEPARATOR = " ¦ "


def tekst_surowy(dane: bytes) -> str:
    """Cały tekst pliku do kontroli wycieku: elementy, ogony, atrybuty, komentarze, instrukcje przetwarzania, a załącznik
    w base64 zdekodowany i odczytany (DOCX, PDF) albo zgłoszony jako pozostałość. Podpis elektroniczny też jest
    pozostałością (powinien zostać usunięty)."""
    from . import docx as fdocx, pdf as fpdf
    d = etree.parse(io.BytesIO(dane), _parser())
    out = []
    for el in d.getroot().iter():
        if isinstance(el, (etree._Comment, etree._ProcessingInstruction)):
            out.append(el.text or "")
        elif isinstance(el.tag, str) and el.tag == f"{{{DS}}}Signature":
            out.append("[część binarna: podpis elektroniczny]")
        elif isinstance(el.tag, str):
            zal = _zalacznik(el.text)
            if zal is not None:
                r = rodzaj_zalacznika(zal)
                out.append(fdocx.tekst_surowy(zal) if r == "docx" else fpdf.tekst_surowy(zal) if r == "pdf"
                           else f"[załącznik {etree.QName(el).localname}]")
            elif el.text and el.text.strip():
                out.append(el.text)
            out.extend(v for v in el.attrib.values() if v.strip())
        if el.tail and el.tail.strip():
            out.append(el.tail)
    return SEPARATOR.join(out)

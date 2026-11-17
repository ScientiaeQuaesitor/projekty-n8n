"""PDF cyfrowy: tekst ciągły z warstwy tekstowej i podmiana w miejscu (PLAN 4.4).

Kawałek to wiersz tekstu (lista znaków z prostokątami). Wiersze jednego bloku łączy spacja, a przeniesienie wyrazu
(„przenie-” na końcu wiersza, mała litera na początku następnego) jest rozwijane: dywiz staje się znakiem ukrytym.
Bloki rozdziela koniec wiersza.

Podmiana: zakres jest redagowany (add_redact_annot, apply_redactions) w wąskim pasie wokół linii bazowej, żeby nie
naruszyć sąsiednich wierszy, a surogat jest wpisywany od początku zakresu czcionką zastępczą z polskimi znakami, w
rozmiarze i kolorze oryginału; dłuższy surogat jest ściskany w poziomie do szerokości zakresu. Czyszczenie: obrazy,
adnotacje i łącza, pola formularzy, załączniki, zakładki, metadane i XMP. Zapis z garbage=4 i clean, żeby usunięty
tekst nie został w strumieniach."""
from pathlib import Path

import fitz

from .model import Model

CZCIONKA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CZCIONKA_POGRUBIONA = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MIN_SCISKANIE = 0.6    # surogat dłuższy niż miejsce jest ściskany w poziomie najwyżej do tej skali, potem maleje czcionka


class Pdf:
    def __init__(self, dane: bytes):
        self.doc = fitz.open(stream=dane, filetype="pdf")
        self.czyszczenie: dict[str, int] = {}
        self._wyczysc()
        self.model = self._model()

    def _licz(self, co: str, n: int = 1) -> None:
        if n:
            self.czyszczenie[co] = self.czyszczenie.get(co, 0) + n

    def _wyczysc(self) -> None:
        d = self.doc
        if d.is_encrypted:
            raise ValueError("PDF zaszyfrowany")
        meta = {k: v for k, v in (d.metadata or {}).items() if v and k not in ("format", "encryption")}
        self._licz("pola metadanych", len(meta))
        d.set_metadata({})
        d.del_xml_metadata()
        for nazwa in list(d.embfile_names()):
            d.embfile_del(nazwa)
            self._licz("załączniki")
        if d.get_toc():
            self._licz("zakładki", len(d.get_toc()))
            d.set_toc([])
        for strona in d:
            for w in list(strona.widgets() or []):
                strona.delete_widget(w)
                self._licz("pola formularza")
            for a in list(strona.annots() or []):
                strona.delete_annot(a)
                self._licz("adnotacje")
            for l in strona.get_links():
                strona.delete_link(l)
                self._licz("łącza")
            obrazy = strona.get_images(full=True)
            if obrazy:
                # Obrazy (logo, pieczątki, podpisy) usuwane redakcją całej strony bez ruszania tekstu i grafiki
                strona.add_redact_annot(strona.rect)
                strona.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                        text=fitz.PDF_REDACT_TEXT_NONE)
                self._licz("obrazy", len(obrazy))

    def _model(self) -> Model:
        return model_z(self.doc)

    def podmien(self, podmiany: list[dict]) -> None:
        wpisy: dict[int, list] = {}
        for k, edycje in self.model.edycje(podmiany).items():
            nr, znaki = self.model.kawalki[k]
            strona = self.doc[nr]
            for a, b, nowy in edycje:
                zakres = znaki[a:b]
                pierwszy = zakres[0]
                rozmiar = pierwszy["rozmiar"]
                baza = pierwszy["origin"][1]
                x0, x1 = min(z["bbox"][0] for z in zakres), max(z["bbox"][2] for z in zakres)
                # Wąski pas wokół wysokości małych liter: prostokąty znaków sąsiednich wierszy go nie przecinają
                strona.add_redact_annot(fitz.Rect(x0, baza - 0.5 * rozmiar, x1, baza - 0.1 * rozmiar), fill=None)
                if nowy:
                    # Miejsce na surogat sięga do następnego widocznego znaku wiersza, który zostaje (albo do końca
                    # wiersza), z odstępem 0,15 rozmiaru czcionki
                    nast = next((z for z in znaki[b:] if z["c"].strip()), None)
                    granica = (nast["bbox"][0] - 0.15 * rozmiar) if nast else x1 + 0.15 * rozmiar
                    wpisy.setdefault(nr, []).append((x0, max(x1, granica), baza, rozmiar, pierwszy["kolor"], pierwszy["flagi"], nowy))
        for nr in {self.model.kawalki[k][0] for k in self.model.edycje(podmiany)}:
            self.doc[nr].apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        for nr, lista in wpisy.items():
            strona = self.doc[nr]
            for x0, x1, baza, rozmiar, kolor, flagi, nowy in lista:
                gruby = bool(flagi & 16)
                plik = CZCIONKA_POGRUBIONA if gruby else CZCIONKA
                szer = fitz.Font(fontfile=plik).text_length(nowy, fontsize=rozmiar)
                potrzebna = (x1 - x0) / szer if szer else 1.0
                # Surogat mieści się zawsze: najpierw ściskanie w poziomie do MIN_SCISKANIE, dalej mniejsza czcionka.
                # Wyjście poza miejsce nakładałoby litery na sąsiedni tekst (kontrola pliku to wykrywa).
                skala = min(1.0, max(MIN_SCISKANIE, potrzebna))
                if potrzebna < MIN_SCISKANIE:
                    rozmiar *= potrzebna / MIN_SCISKANIE
                rgb = ((kolor >> 16) & 255, (kolor >> 8) & 255, kolor & 255)
                strona.insert_text((x0, baza), nowy, fontsize=rozmiar, fontfile=plik, fontname="ZastB" if gruby else "Zast",
                                   color=tuple(c / 255 for c in rgb),
                                   morph=(fitz.Point(x0, baza), fitz.Matrix(skala, 1)) if skala < 1 else None)

    def zapisz(self) -> bytes:
        # Czcionka zastępcza osadzona tylko w podzbiorze użytych znaków (cała DejaVu to ok. 700 KB na plik)
        self.doc.subset_fonts()
        return self.doc.tobytes(garbage=4, deflate=True, clean=True, no_new_id=True)


def model_z(doc) -> Model:
    """Tekst ciągły warstwy tekstowej z mapą znaków (kawałek = wiersz). Wspólne dla podmiany i kontroli pliku."""
    m = Model()
    pierwszy = True
    for nr, strona in enumerate(doc):
        raw = strona.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
        for blok in raw["blocks"]:
            if blok.get("type") != 0:
                continue
            wiersze = []
            for linia in blok["lines"]:
                znaki = [dict(z, rozmiar=s["size"], kolor=s["color"], czcionka=s["font"], flagi=s["flags"])
                         for s in linia["spans"] for z in s["chars"]]
                while znaki and not znaki[-1]["c"].strip():
                    znaki.pop()
                while znaki and not znaki[0]["c"].strip():
                    znaki.pop(0)
                if znaki:
                    wiersze.append(znaki)
            if not wiersze:
                continue
            if not pierwszy:
                m.separator("\n")
            pierwszy = False
            for i, znaki in enumerate(wiersze):
                tekst = "".join(z["c"] for z in znaki)
                nast = wiersze[i + 1][0]["c"] if i + 1 < len(wiersze) else ""
                przeniesienie = (len(tekst) >= 2 and tekst[-1] in "-­" and tekst[-2].isalpha() and nast.islower())
                if przeniesienie:
                    k = m.dodaj(tekst[:-1], (nr, znaki))
                    m.ukryj(k, len(tekst) - 1)
                else:
                    m.dodaj(tekst, (nr, znaki))
                    if i + 1 < len(wiersze) and not tekst.endswith("-"):
                        m.separator(" ")
    return m.zamknij()


def _wiersze_geometryczne(d, tolerancja: float = 1.5) -> list[str]:
    out = []
    for s in d:
        znaki = sorted((z["origin"][1], z["origin"][0], z["bbox"][2], sp["size"], z["c"])
                       for b in s.get_text("rawdict")["blocks"] for l in b.get("lines", []) for sp in l["spans"] for z in sp["chars"])
        wiersze: list[list] = []
        for z in znaki:
            if wiersze and z[0] - wiersze[-1][0][0] < tolerancja:
                wiersze[-1].append(z)
            else:
                wiersze.append([z])
        for w in wiersze:
            tekst, prawy = "", None
            for _, x, x1, rozmiar, c in sorted(w, key=lambda z: z[1]):
                if prawy is not None and x - prawy > 0.2 * rozmiar and not tekst.endswith(" ") and c != " ":
                    tekst += " "
                tekst += c
                prawy = x1
            if tekst.strip():
                out.append(tekst)
    return out


def tekst_surowy(dane: bytes) -> str:
    """Wszystko, co da się z pliku odczytać jako tekst: warstwa tekstowa, metadane, XMP, załączniki, adnotacje,
    zakładki. Do kontroli wycieku na pliku."""
    d = fitz.open(stream=dane, filetype="pdf")
    out = [v for v in (d.metadata or {}).values() if v]
    out.append(d.get_xml_metadata() or "")
    out += [f"[załącznik {n}]" for n in d.embfile_names()]
    out += [str(t) for t in d.get_toc()]
    # Warstwa tekstowa wierszami w porządku geometrycznym (linia bazowa, potem x): surogaty wpisane przy podmianie są
    # w strumieniu strony osobnymi obiektami na końcu, a w wierszu stoją na miejscu oryginału. Wiersze rozdziela
    # separator, przez który regexy numerów nie przechodzą; numer przełamany między wierszami sprawdza porównanie
    # wierszy z tekstem zanonimizowanym w kontroli pliku.
    out += _wiersze_geometryczne(d)
    for s in d:
        out += [a.info.get("content", "") + " " + a.info.get("title", "") for a in (s.annots() or [])]
        out += [l.get("uri", "") for l in s.get_links()]
        out += [f"[obraz {x[0]}]" for x in s.get_images(full=True)]
    return " ¦ ".join(x for x in out if x)   # separator, którego regexy numerów nie przeskakują


def strony_bez_tekstu(dane: bytes, prog: int = 200) -> bool:
    d = fitz.open(stream=dane, filetype="pdf")
    return sum(len(s.get_text().strip()) for s in d) < prog * max(1, len(d))


def otworz(sciezka: Path) -> Pdf:
    return Pdf(Path(sciezka).read_bytes())

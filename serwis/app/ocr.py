"""OCR skanów dwoma silnikami z wyborem na poziomie wiersza.

Zasada: żaden silnik nie jest najlepszy wszędzie, więc każdy wiersz jest oceniany miarą niezależną od silnika
(udział słów znanych słownikowi, poprawne sumy kontrolne numerów, brak śmieci). Tesseract czyta całą stronę
i wyznacza układ. Na stronach, gdzie ma słabe wiersze, stronę czyta też EasyOCR i w każdym wierszu wygrywa
lepszy odczyt. Wiersze, które po tym nadal są słabe, trafiają do raportu jakości zamiast udawać dobry tekst."""
import csv
import io
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import regex as re

from . import morf
from .detekcja import regexy

SZEROKOSC_PX = 2480          # A4 w 300 dpi; strony o niższej rozdzielczości są powiększane
PROG_SLABY = 0.75            # poniżej tej oceny wiersz jest czytany drugim silnikiem
PROG_ZLY = 0.6               # poniżej tej oceny po wyborze wiersz jest zgłaszany jako niepewny
RX_WYPELNIACZ = re.compile(r"^[-=_.—–~*·]{2,}$")   # kreski i kropki dopełniające wiersz w aktach i formularzach
RX_LICZBOWY = re.compile(r"^[(\[„\"]?\d[\d./:,\-–]*\p{L}{0,2}[)\]”\".,;:]*$")
BRZEGI = " \t„”\"'()[].,;:!?-–"


@dataclass
class Wiersz:
    strona: int
    blok: int
    akapit: int
    x0: int
    y0: int
    x1: int
    y1: int
    tekst: str
    pewnosc: float
    ocena: float = 0.0
    zrodlo: str = "tesseract"
    inne: dict = field(default_factory=dict)


def _znane(slowo: str) -> bool:
    return any(i.klasa != "ign" for i in morf.analizuj(slowo))


def _numery(tekst: str) -> int:
    return sum(1 for e in regexy.wykryj(tekst) if e.typ in ("PESEL", "NIP", "REGON", "IBAN") and e.pewna)


def punkty(tekst: str) -> float:
    """Przybliżona liczba poprawnie odczytanych słów w wierszu (ocena razy liczba słów)."""
    ocena, n = ocen(tekst)
    return ocena * n


def ocen(tekst: str) -> tuple[float, int]:
    """Ocena wiersza 0..1 i liczba ocenianych słów. Nie zależy od silnika, który wiersz odczytał."""
    punkty, n = 0.0, 0
    for token in tekst.split():
        if RX_WYPELNIACZ.match(token):
            continue
        n += 1
        rdzen = token.strip(BRZEGI)
        if RX_LICZBOWY.match(token) or (rdzen and sum(c.isdigit() for c in rdzen) >= len(rdzen) / 2):
            punkty += 1
        elif rdzen and re.fullmatch(r"\p{L}+(?:[-'’]\p{L}+)*", rdzen):
            if all(_znane(cz) for cz in re.split(r"[-'’]", rdzen)):
                punkty += 1
            elif len(rdzen) >= 3 and rdzen[0].isupper() and rdzen[1:].islower():
                punkty += 0.6   # możliwa nazwa własna spoza słownika
            elif len(rdzen) <= 2:
                punkty += 0.2
    if n == 0:
        return 1.0, 0
    premia = 0.15 * sum(1 for e in regexy.wykryj(tekst) if e.typ in ("PESEL", "NIP", "REGON", "IBAN") and e.pewna)
    return min(1.0, punkty / n + premia), n


def oczysc(tekst: str) -> str:
    """Usuwa wypełniacze wiersza i śmieci za nimi („-------nn nnn a a”)."""
    tokeny = tekst.split()
    wynik = []
    for i, t in enumerate(tokeny):
        if RX_WYPELNIACZ.match(t):
            continue
        t = re.sub(r"[-=_—–]{3,}.*$", "", t)   # „Kowalski,-------nn” -> „Kowalski,”, sam wypełniacz z ogonem znika
        if not t:
            continue
        # resztki po kreskach odczytane jako litery: „nnn”, „mmm”, „mamma”, „aaa”
        if re.fullmatch(r"\p{Ll}+", t) and len(set(t)) <= 2 and not _znane(t):
            continue
        wynik.append(t)
    bez_resztek, i = [], 0
    while i < len(wynik):
        j = i
        while j < len(wynik) and re.fullmatch(r"[mnua]{1,6}", wynik[j]):
            j += 1
        if j - i >= 2:
            i = j   # co najmniej dwa takie „słowa” pod rząd: to nie tekst
            continue
        bez_resztek.append(wynik[i])
        i += 1
    wynik = bez_resztek
    while wynik:
        rdzen = wynik[-1].strip(BRZEGI)
        smiec = (not rdzen) or (len(rdzen) <= 4 and not rdzen.isdigit() and not _znane(rdzen) and not RX_LICZBOWY.match(wynik[-1]))
        if not smiec:
            break
        wynik.pop()
    return " ".join(wynik)


def strony_png(pdf: Path, katalog: Path) -> list[Path]:
    subprocess.run(["pdftoppm", "-png", "-scale-to-x", str(SZEROKOSC_PX), "-scale-to-y", "-1", str(pdf), str(katalog / "s")],
                   check=True, capture_output=True)
    return sorted(katalog.glob("s*.png"))


def tesseract(png: Path, strona: int, jezyk: str = "pol") -> list[Wiersz]:
    p = subprocess.run(["tesseract", str(png), "stdout", "-l", jezyk, "--psm", "3", "tsv"], capture_output=True, text=True, check=True)
    grupy: dict[tuple, list] = {}
    for w in csv.DictReader(io.StringIO(p.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        if w["level"] != "5" or not (w["text"] or "").strip():
            continue
        grupy.setdefault((int(w["block_num"]), int(w["par_num"]), int(w["line_num"])), []).append(w)
    wiersze = []
    for (blok, akapit, _), slowa in sorted(grupy.items()):
        x0 = min(int(s["left"]) for s in slowa)
        y0 = min(int(s["top"]) for s in slowa)
        x1 = max(int(s["left"]) + int(s["width"]) for s in slowa)
        y1 = max(int(s["top"]) + int(s["height"]) for s in slowa)
        pewnosc = sum(float(s["conf"]) for s in slowa) / len(slowa)
        wiersze.append(Wiersz(strona, blok, akapit, x0, y0, x1, y1, " ".join(s["text"] for s in slowa), pewnosc))
    return wiersze


@lru_cache(maxsize=1)
def _easyocr():
    import easyocr
    return easyocr.Reader(["pl"], gpu=False, verbose=False)


def easyocr_strona(png: Path) -> list[tuple[int, int, int, int, str]]:
    wynik = []
    for ramka, tekst, _ in _easyocr().readtext(str(png), detail=1, paragraph=False):
        xs, ys = [p[0] for p in ramka], [p[1] for p in ramka]
        wynik.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), tekst))
    return wynik


def _polacz(wiersze: list[Wiersz], obce: list[tuple[int, int, int, int, str]], strona: int) -> int:
    """Dla każdego wiersza Tesseracta składa odczyt drugiego silnika z ramek leżących na tej samej wysokości
    i wybiera lepszy. Ramki, których Tesseract w ogóle nie odczytał, dochodzą jako nowe wiersze. Zwraca liczbę zamian."""
    przypisane: dict[int, list] = {}
    sieroty = []
    for x0, y0, x1, y1, tekst in obce:
        srodek, najlepszy = (y0 + y1) / 2, None
        for i, w in enumerate(wiersze):
            if w.y0 <= srodek <= w.y1 and x1 > w.x0 - 40 and x0 < w.x1 + 40:
                najlepszy = i
                break
        (przypisane.setdefault(najlepszy, []) if najlepszy is not None else sieroty).append((x0, y0, x1, y1, tekst))
    zamiany = 0
    for i, ramki in przypisane.items():
        w = wiersze[i]
        kandydat = " ".join(t for _, _, _, _, t in sorted(ramki))
        ocena, n = ocen(kandydat)
        w.inne["easyocr"] = round(ocena, 2)
        # Drugi odczyt wygrywa, gdy jest wyraźnie lepszy i nie zgubił treści: ma co najmniej 80% poprawnych słów pierwszego.
        # Porównanie liczby wszystkich słów byłoby błędne, bo zły odczyt składa się głównie ze śmieci.
        # Numer z poprawną sumą kontrolną (PESEL, NIP, REGON, rachunek) jest twardym dowodem dobrego odczytu:
        # jeśli drugi silnik go ma, a pierwszy nie, wygrywa bez dalszych warunków.
        if n and (_numery(kandydat) > _numery(w.tekst) or (ocena > w.ocena + 0.05 and ocena * n >= 0.6 * punkty(w.tekst))):
            w.tekst, w.ocena, w.zrodlo = kandydat, ocena, "easyocr"
            zamiany += 1
    for x0, y0, x1, y1, tekst in sieroty:
        ocena, n = ocen(tekst)
        if n >= 2 and ocena >= PROG_ZLY:
            # wstawiany za wierszem leżącym bezpośrednio wyżej, w jego bloku
            wyzej = max((w for w in wiersze if w.y0 <= y0), key=lambda w: w.y0, default=None)
            nowy = Wiersz(strona, wyzej.blok if wyzej else 0, wyzej.akapit if wyzej else 0, x0, y0, x1, y1, tekst, 0.0, ocena, "easyocr")
            wiersze.insert(wiersze.index(wyzej) + 1 if wyzej else 0, nowy)
    return zamiany


def _akapity(wiersze: list[Wiersz]) -> list[str]:
    akapity, biezacy, klucz = [], "", None
    for w in wiersze:
        tekst = oczysc(w.tekst)
        if not tekst:
            continue
        if (w.strona, w.blok, w.akapit) != klucz and biezacy:
            akapity.append(biezacy)
            biezacy = ""
        klucz = (w.strona, w.blok, w.akapit)
        if not biezacy:
            biezacy = tekst
        elif biezacy.endswith("-") and tekst[:1].islower():
            biezacy = biezacy[:-1] + tekst          # przeniesienie wyrazu
        elif biezacy.endswith("-") and tekst[:1].isupper():
            biezacy += tekst                        # nazwisko dwuczłonowe przełamane między wierszami
        else:
            biezacy += " " + tekst
    if biezacy:
        akapity.append(biezacy)
    return akapity


def czytaj(pdf: Path, drugi_silnik: bool = True) -> tuple[str, dict]:
    """Zwraca (tekst, raport jakości). Raport nie zawiera treści dokumentu."""
    t0 = time.time()
    wszystkie: list[Wiersz] = []
    raport = {"strony": [], "silniki": ["tesseract"] + (["easyocr"] if drugi_silnik else [])}
    with tempfile.TemporaryDirectory() as tmp:
        for nr, png in enumerate(strony_png(pdf, Path(tmp)), 1):
            wiersze = tesseract(png, nr)
            for w in wiersze:
                w.ocena, _ = ocen(w.tekst)
            slabe = [w for w in wiersze if ocen(w.tekst)[1] >= 2 and (w.ocena < PROG_SLABY or w.pewnosc < 60)]
            zamiany = 0
            if drugi_silnik and slabe:
                zamiany = _polacz(wiersze, easyocr_strona(png), nr)
            zle = [i + 1 for i, w in enumerate(wiersze) if ocen(w.tekst)[1] >= 3 and w.ocena < PROG_ZLY]
            raport["strony"].append({"strona": nr, "wierszy": len(wiersze), "slabych_przed": len(slabe), "zamienionych": zamiany,
                                     "niepewnych_po": len(zle), "niepewne_wiersze": zle})
            wszystkie += wiersze
    rozmiar = subprocess.run(["pdfimages", "-list", str(pdf)], capture_output=True, text=True).stdout.splitlines()[2:3]
    szer_px = int(rozmiar[0].split()[3]) if rozmiar and rozmiar[0].split()[3].isdigit() else None
    wierszy = sum(s["wierszy"] for s in raport["strony"]) or 1
    niepewnych = sum(s["niepewnych_po"] for s in raport["strony"])
    raport.update({
        "szacowane_dpi": round(szer_px / 8.27) if szer_px else None,   # przy założeniu strony A4
        "wierszy": wierszy, "zamienionych": sum(s["zamienionych"] for s in raport["strony"]), "niepewnych": niepewnych,
        "udzial_niepewnych": round(niepewnych / wierszy, 3),
        "jakosc": "dobra" if niepewnych / wierszy < 0.03 else ("średnia" if niepewnych / wierszy < 0.10 else "słaba"),
        "czas_s": round(time.time() - t0),
    })
    return "\n\n".join(_akapity(wszystkie)), raport

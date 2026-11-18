"""Model pośredni dokumentu (PLAN 4.2): tekst ciągły z mapą każdego znaku do miejsca w pliku.

Detekcja i silnik pracują na tekście ciągłym, a podmiany wracają pod adresy w pliku. Format pliku (DOCX, PDF) dostarcza
kawałki: najmniejsze jednostki tekstu, które umie zmienić (element w:t w DOCX, wiersz w PDF). Między kawałkami stoją
separatory (koniec akapitu, spacja w miejscu złamania wiersza), które w pliku nie istnieją jako znaki.

Znak ukryty to znak pliku, którego nie ma w tekście ciągłym: dywiz przeniesienia wyrazu w PDF („przenie-” / „sienie”).
Podmiana zakresu, który obejmuje takie miejsce, usuwa też ukryty znak."""
import difflib
from dataclasses import dataclass, field

import regex as re


# Podmiany nazw, w których część słów zostaje (nazwa ogólna z podmienioną miejscowością, firma z formą prawną):
# tylko one są dzielone na różnice słowo po słowie. Numery, adresy i osoby zmieniają się w całości.
TYPY_CZASTKOWE = {"INSTYTUCJA", "AKT_PRAWNY", "DOKUMENT", "POJECIE", "OGOLNA", "OPISOWA", "FIRMA", "NAZWA"}


@dataclass
class Model:
    tekst: str = ""
    # dla każdego znaku tekstu ciągłego: (numer kawałka, pozycja w kawałku) albo None dla separatora
    zrodlo: list = field(default_factory=list)
    # znaki ukryte: pozycja w tekście ciągłym, przed którą stoją -> lista (kawałek, pozycja w kawałku)
    ukryte: dict = field(default_factory=dict)
    kawalki: list = field(default_factory=list)   # adresy kawałków, znaczenie zależy od formatu
    _czesci: list = field(default_factory=list)

    def dodaj(self, tekst: str, adres) -> int:
        """Dodaje kawałek tekstu z pliku. Zwraca jego numer."""
        k = len(self.kawalki)
        self.kawalki.append(adres)
        self._czesci.append(tekst)
        self.zrodlo.extend((k, i) for i in range(len(tekst)))
        return k

    def separator(self, tekst: str) -> None:
        self._czesci.append(tekst)
        self.zrodlo.extend([None] * len(tekst))

    def ukryj(self, k: int, poz: int) -> None:
        """Znak kawałka k na pozycji poz istnieje w pliku, ale nie w tekście ciągłym."""
        self.ukryte.setdefault(len(self.zrodlo), []).append((k, poz))

    def zamknij(self) -> "Model":
        self.tekst = "".join(self._czesci)
        assert len(self.tekst) == len(self.zrodlo)
        return self

    def edycje(self, podmiany: list[dict]) -> dict[int, list[tuple[int, int, str]]]:
        """Podmiany silnika (start, end, surogat w tekście ciągłym) jako edycje kawałków: numer kawałka -> lista
        (początek, koniec, nowy tekst) w pozycjach kawałka. Surogat trafia do pierwszego kawałka zakresu, pozostałe
        części zakresu (w kolejnych kawałkach) są usuwane. Zakres bez żadnego znaku z pliku jest błędem."""
        out: dict[int, list[tuple[int, int, str]]] = {}
        for p in (c for p in podmiany for c in self._czastkowe(p)):
            pozycje = [self.zrodlo[i] for i in range(p["start"], p["end"]) if self.zrodlo[i] is not None]
            pozycje += [u for i in range(p["start"] + 1, p["end"]) for u in self.ukryte.get(i, [])]
            if not pozycje:
                raise ValueError(f"Podmiana bez znaków w pliku: {p['start']}-{p['end']}")
            grupy: dict[int, list[int]] = {}
            for k, i in pozycje:
                grupy.setdefault(k, []).append(i)
            pierwszy = min(grupy, key=lambda k: (k != pozycje[0][0], k))
            for k, poz in grupy.items():
                a, b = min(poz), max(poz) + 1
                out.setdefault(k, []).append((a, b, p["surogat"] if k == pierwszy else ""))
        for k in out:
            out[k].sort()
        return out

    def _czastkowe(self, p: dict) -> list[dict]:
        """Podmiana podzielona na różnice słowo po słowie. Silnik zwraca całą nazwę („Sąd Rejonowy w Gliwicach” ->
        „Sąd Rejonowy w Legnicy”), a w pliku zmienia się tylko to, co inne: słowa bez zmian zostają na miejscu ze swoim
        formatowaniem, a w PDF surogat nie musi się mieścić w miejscu całej nazwy."""
        if p.get("typ") not in TYPY_CZASTKOWE:
            return [p]
        a0, org, sur = p["start"], self.tekst[p["start"]:p["end"]], p["surogat"]
        # Słowo to ciąg bez odstępu: identyfikator („UI/2025/04/017”) albo słowo z przecinkiem zmienia się w całości
        to, ts = re.findall(r"\S+|\s+", org), re.findall(r"\S+|\s+", sur)
        poz = [0]
        for t in to:
            poz.append(poz[-1] + len(t))
        out: list[list] = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, to, ts, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            nowy = "".join(ts[j1:j2])
            if i1 == i2:
                # Samo wstawienie nie ma znaków w pliku: dokleja się do sąsiedniego słowa oryginału
                if i1 > 0:
                    i1, nowy = i1 - 1, to[i1 - 1] + nowy
                else:
                    i2, nowy = i2 + 1, nowy + to[i2]
            if out and out[-1][1] > a0 + poz[i1]:
                return [p]   # edycje zachodzą na siebie (wstawienie tuż po zamianie): podmiana w całości
            out.append([a0 + poz[i1], a0 + poz[i2], nowy])
        return [{"start": a, "end": b, "surogat": s} for a, b, s in out]


def zastosuj(tekst: str, edycje: list[tuple[int, int, str]]) -> str:
    """Edycje jednego kawałka (posortowane, rozłączne) zastosowane do jego tekstu."""
    for a, b, nowy in sorted(edycje, reverse=True):
        tekst = tekst[:a] + nowy + tekst[b:]
    return tekst

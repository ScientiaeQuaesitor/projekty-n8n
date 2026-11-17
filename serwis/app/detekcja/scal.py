"""Scalanie wyników detektorów w rozłączne zakresy do podmiany.

Kolejność: przycięcie zakresów modeli (tytuły, cudzysłowy, interpunkcja) -> filtr określeń ogólnych
-> pierwszeństwo regexów -> suma nakładających się zakresów -> sklejanie sąsiadów -> forma prawna firmy."""
from dataclasses import dataclass, field

import regex as re

from .. import morf
from .typy import Encja

TYTULY = r"(?:pan|pani|pana|panu|panem|panią|panie|państwo|państwa|państwu|dr|inż|mgr|prof|mec|mecenas|mecenasa|hab|lek|radca|radcy)"
RX_TYTUL = re.compile(rf"^(?:(?:{TYTULY}|spółk\p{{L}}*|firm\p{{L}}*)\.?\s+)+(?=\p{{Lu}}|„)", re.I)
RX_OGON = re.compile(r"\s+(?:z|ze|w|we|i|a|na|do|od|o|u|oraz|przy|dla)$")
RX_BRZEG_L = re.compile(r"^[\s„”\"'«»(\[<,;:.–-]+")
RX_BRZEG_P = re.compile(r"[\s„”\"'«»)\]>,;:.–-]+$")

FORMA_PRAWNA = (r"(?:[Ss]p\.\s?z\s?o\.\s?o\.(?:\s?[Ss]p\.\s?k\.)?|S\.K\.A\.|S\.A\.|[Ss]p\.\s?k\.|[Ss]p\.\s?j\.|s\.c\.|P\.S\.A\."
                r"|[Ss]półk[aiąęo]\s[Aa]kcyjn(?:a|ej|ą)|[Ss]półk[aiąęo]\sz\sograniczoną\sodpowiedzialnością"
                r"|[Ss]półk[aiąęo]\s(?:komandytow|jawn|cywiln|partnersk)(?:a|ej|ą))")
RX_FORMA_PO = re.compile(r"^[”\"]?\s+" + FORMA_PRAWNA)

# Słowa, które same nie identyfikują nikogo. Zakres złożony wyłącznie z nich jest odrzucany.
STOP_DOKLADNE = {"krs", "nip", "pesel", "regon", "vat", "wz", "iban", "sp", "z", "o", "s", "a", "i", "w", "we", "nr", "ul", "tel", "kom", "fax", "faks", "mail",
                 "rep", "repertorium", "dnia", "dzień", "dniu", "ad", "poz", "art", "ust", "pkt"}
# Celowo nie ma tu listy pojęć („spółka”, „sąd”, „ustawa”). O tym, czy nazwa jest określeniem ogólnym, decyduje
# klasyfikacja kategorii w silniku (LLM z kontekstem), a nie słownik wyrazów.

# Typ wyniku przy sumowaniu: wygrywa najdłuższy zakres, przy remisie kolejność źródeł
PRIORYTET_ZRODLA = {"regex": 0, "hf": 1, "spacy": 2, "llm": 3}
SKLEJANE = {"OSOBA", "FIRMA", "NAZWA", "MIEJSCE", "ADRES"}


@dataclass
class Zakres:
    start: int
    end: int
    typ: str
    zrodla: set[str] = field(default_factory=set)
    tekst: str = ""

    def jako_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "typ": self.typ, "zrodla": sorted(self.zrodla), "tekst": self.tekst}


def _ogolny(fragment: str) -> bool:
    slowa = re.findall(r"[\p{L}\d]+", fragment)
    if not slowa:
        return True
    if len(slowa) == 1 and morf.tylko_funkcyjne(slowa[0]):  # „Dla”, „Na”, „Potwierdzam” z początku zdania
        return True
    return all(s.lower() in STOP_DOKLADNE for s in slowa)


def _pospolite(tekst: str, a: int, b: int, typ: str) -> bool:
    """Pojedyncze słowo pospolite wzięte przez model za nazwę: „Nieobecni” jako osoba, etykieta „Data:” na początku wiersza."""
    slowo = tekst[a:b]
    if not re.fullmatch(r"\p{L}+", slowo):
        return False
    inter = morf.analizuj(slowo)
    po_ocr = any(i.klasa == "ign" for i in inter)
    if po_ocr:
        # Słowo spoza słownika może być zwykłym wyrazem po OCR bez ogonków („legitymujacy”, „Stawajacych”, „trescia”)
        inter = [i for w in morf.z_ogonkami(slowo) for i in morf.analizuj(w)]
    if not inter:
        return False
    wlasne = any(set(i.nazwy) & {"imię", "nazwisko", "nazwa_geograficzna"} for i in inter)
    if po_ocr and not wlasne:
        return True  # niezależnie od typu: to nie nazwa, tylko zniekształcony wyraz pospolity
    if typ == "OSOBA" and not wlasne:
        return True
    etykieta = (a == 0 or tekst[a - 1] == "\n") and tekst[b:b + 1] == ":"
    return etykieta and typ != "OSOBA" and any("nazwa_pospolita" in i.nazwy for i in inter)


def _lematy(slowo: str) -> frozenset:
    """Możliwe formy podstawowe słowa, do porównywania wystąpień tej samej nazwy w różnych przypadkach."""
    s = slowo.lower()
    out = {s} | {i.lemat.lower() for i in morf.analizuj(slowo) if i.klasa != "ign"} | {i.lemat.lower() for i in morf.analizuj(slowo.capitalize())if i.klasa != "ign"}
    if len(out) == 1:  # słowo spoza słownika: możliwe rdzenie po odcięciu końcówki
        out |= {s[:-len(k)] for k in ("owi", "iem", "em", "ie", "u", "a", "y", "i", "ę", "ą") if s.endswith(k) and len(s) - len(k) >= 4}
    return frozenset(out)


def _ujednolic(tekst: str, zakresy: list["Zakres"]) -> None:
    """Ta sama nazwa dostaje jeden typ we wszystkich wystąpieniach. Modele często oznaczają tę samą firmę raz jako
    firmę, raz jako osobę albo miejsce, a wtedy dostałaby kilka różnych surogatów."""
    nazwane = [z for z in zakresy if z.typ in ("OSOBA", "FIRMA", "NAZWA", "MIEJSCE")]
    sygn = [[_lematy(w) for w in re.findall(r"[\p{L}\d]+", tekst[z.start:z.end])] for z in nazwane]
    rodzic = list(range(len(nazwane)))

    def korzen(i: int) -> int:
        while rodzic[i] != i:
            rodzic[i] = rodzic[rodzic[i]]
            i = rodzic[i]
        return i

    for i in range(len(nazwane)):
        for j in range(i + 1, len(nazwane)):
            a, b = (sygn[i], sygn[j]) if len(sygn[i]) <= len(sygn[j]) else (sygn[j], sygn[i])
            # to samo albo krótsza nazwa jest początkiem dłuższej (wielowyrazowej firmy), słowo w słowo
            if a and all(x & y for x, y in zip(a, b)) and (len(a) == len(b) or "OSOBA" not in (nazwane[i].typ, nazwane[j].typ)):
                rodzic[korzen(i)] = korzen(j)
    grupy: dict[int, list[Zakres]] = {}
    for i, z in enumerate(nazwane):
        grupy.setdefault(korzen(i), []).append(z)
    kolejnosc = ["FIRMA", "NAZWA", "OSOBA", "MIEJSCE"]
    for g in grupy.values():
        if len({z.typ for z in g}) == 1:
            continue
        glosy = {t: 0 for t in kolejnosc}
        for z in g:
            glosy[z.typ] += 1
            if RX_FORMA_PO.match(tekst[z.end:z.end + 60]):
                glosy["FIRMA"] += 100
        typ = max(kolejnosc, key=lambda t: glosy[t])
        for z in g:
            z.typ = typ


def _przytnij(tekst: str, a: int, b: int) -> tuple[int, int]:
    zmiana = True
    while zmiana and a < b:
        zmiana = False
        for rx in (RX_BRZEG_L, RX_TYTUL):
            m = rx.match(tekst[a:b])
            if m and m.end():
                a += m.end()
                zmiana = True
    zmiana = True
    while zmiana and a < b:
        zmiana = False
        for rx in (RX_BRZEG_P, RX_OGON):  # interpunkcja i doklejony przyimek: „Spółka Akcyjna z”
            m = rx.search(tekst[a:b])
            if m and m.start() > 0:
                b = a + m.start()
                zmiana = True
    return _domknij(tekst, a, b)


def _domknij(tekst: str, a: int, b: int) -> tuple[int, int]:
    """Przywraca znaki należące do nazwy: kropkę skrótu (o.o., S.A., inicjał) i zamykający cudzysłów."""
    if b < len(tekst) and tekst[b] == "." and re.search(r"(?:^|[\s.])\p{L}{1,2}$", tekst[a:b]):
        b += 1
    if b < len(tekst) and tekst[b] in "”\"" and tekst[a:b].count("„") + tekst[a:b].count('"') % 2 > tekst[a:b].count("”"):
        b += 1
    return a, b


def _wystapienia(tekst: str, wartosc: str):
    return re.finditer(r"(?<![\p{L}\d])" + re.escape(wartosc) + r"(?![\p{L}\d])", tekst)


def _odejmij(a: int, b: int, zajete: list[tuple[int, int]]) -> list[tuple[int, int]]:
    czesci = [(a, b)]
    for x, y in zajete:
        nowe = []
        for s, e in czesci:
            if y <= s or x >= e:
                nowe.append((s, e))
                continue
            if s < x:
                nowe.append((s, x))
            if y < e:
                nowe.append((y, e))
        czesci = nowe
    return czesci


# Fragmenty, których nie wolno podmieniać: odwołania do przepisów, publikatory, akty UE, kwoty
RX_CHRONIONE = re.compile(
    r"art\.\s?\d+\p{L}*(?:\s?(?:ust|pkt|lit|§)\.?\s?[\d\p{L}-]+)*"
    r"|(?:ust|pkt|poz)\.\s?\d+(?:\s?-\s?\d+)?"
    r"|§\s?\d+\p{L}?"
    r"|Dz\.\s?U\.[^()\n]{0,60}?poz\.\s?\d+"
    r"|(?:\(?(?:UE|WE|EWG)\)?\s)?\d{2,4}/\d{2,4}(?:/(?:WE|UE|EWG))"
    r"|\(UE\)\s?\d{4}/\d+"
    r"|\d{1,3}(?:[ . ]\d{3})*(?:,\d{2})?\s?(?:zł|PLN|EUR|USD|euro|złot\p{L}+)(?![\p{L}])"
    r"|\d{1,3}(?:[. ]\d{3})+,\d{2}"
    r"|\d+,\d+\s?(?:m²|m2|ha|%)"
    # daty: podmiana cyfr dałaby „93 grudnia 2086”
    r"|\d{1,2}\s(?:stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|wrzesnia|października|pazdziernika|listopada|grudnia)\s\d{4}(?:\s?(?:r\.|roku))?"
    r"|(?<![\d/])\d{1,2}[.-]\d{1,2}[.-]\d{4}(?:\s?r\.)?(?![\d/])|(?<![\d/])\d{4}-\d{2}-\d{2}(?![\d/])|(?<![\d/.,-])(?:19|20)\d{2}\s?(?:r\.|roku)")
RX_DEFINICJA = re.compile(r"(?:dalej|zwan\p{L}+)(?:\s+(?:dalej|także|również|jako|łącznie|w\sskrócie)){0,3}\s*:?\s+[„\"]?(\p{Lu}[^\"”„\n,;()]{1,60}?)[\"”]")


def terminy_zdefiniowane(tekst: str) -> list[list[frozenset]]:
    """Terminy wprowadzone w dokumencie zwrotem „zwany dalej …” („Kupujący”, „Lokal Mieszkalny”). To pojęcia umowne, nie nazwy własne."""
    return [[_lematy(w) for w in re.findall(r"[\p{L}\d]+", m.group(1))] for m in RX_DEFINICJA.finditer(tekst)]


def _to_termin(fragment: str, terminy: list[list[frozenset]]) -> bool:
    syg = [_lematy(w) for w in re.findall(r"[\p{L}\d]+", fragment)]
    return any(len(t) == len(syg) and all(x & y for x, y in zip(t, syg)) for t in terminy)


def _liczba_zwykla(fragment: str) -> bool:
    """Sama liczba albo kwota bez liter: numer lokalu, liczba udziałów, cena. Podmiana rozjechałaby się z zapisem słownym."""
    return bool(re.fullmatch(r"\d{1,4}|\d{1,3}(?:[ . ]\d{3})*(?:,\d+)?", fragment.strip()))


def _malo_cyfr(fragment: str) -> bool:
    """„numer 2”, „załącznik 3”: odwołanie wewnątrz dokumentu, nie identyfikator. Podmiana zepsułaby spójność tekstu."""
    return len(re.findall(r"\d", fragment)) < 5 and "/" not in fragment and not re.search(r"\d-\d", fragment)


def scal(tekst: str, encje: list[Encja]) -> list[Zakres]:
    chronione = [(m.start(), m.end()) for m in RX_CHRONIONE.finditer(tekst)]
    terminy = terminy_zdefiniowane(tekst)

    def chroniony(a: int, b: int) -> bool:
        return any(a < y and b > x for x, y in chronione)

    stale = [e for e in encje if e.zrodlo == "regex" and not (e.typ == "SYGNATURA" and chroniony(e.start, e.end))]
    zajete = [(e.start, e.end) for e in stale]
    wynik = [Zakres(e.start, e.end, e.typ, {"regex"}) for e in stale]

    # 1. Zakresy modeli: przycięcie, filtr, ustąpienie regexom
    kandydaci: list[tuple[int, int, str, str]] = []  # start, end, typ, źródło

    def dodaj(start: int, end: int, typ: str, zrodlo: str) -> None:
        for a, b in _odejmij(start, end, zajete):
            # Zakres modelu nie przechodzi przez pusty wiersz (granica akapitu)
            pos = a
            # Zakres modelu nie przechodzi przez koniec wiersza ani etykietę: „Polski)\nNieobecni: Ola Wiśniewska”
            # Osoby dodatkowo rozdzielane na spójniku: „Teresy i Henryka Borkowskich” to dwie osoby
            podzial = r"(\s*\n\s*|[:;]\s|,\s|\s+(?:i|oraz|lub|albo)\s+)" if typ == "OSOBA" else r"(\s*\n\s*|[:;]\s)"
            for czesc in re.split(podzial, tekst[a:b]):
                if czesc.strip():
                    x, y = _przytnij(tekst, pos, pos + len(czesc))
                    pos += len(czesc)
                    if len(re.findall(r"[\p{L}\d]", tekst[x:y])) < 3 or _ogolny(tekst[x:y]) or _pospolite(tekst, x, y, typ):
                        continue
                    if chroniony(x, y) or _to_termin(tekst[x:y], terminy) or (typ == "INNE" and (_liczba_zwykla(tekst[x:y]) or _malo_cyfr(tekst[x:y]))):
                        continue
                    kandydaci.append((x, y, typ, zrodlo))
                else:
                    pos += len(czesc)

    for e in encje:
        if e.zrodlo != "regex":
            dodaj(e.start, e.end, e.typ, e.zrodlo)

    # 1a. Propagacja: nazwa wykryta w jednym miejscu jest oznaczana we wszystkich dokładnych wystąpieniach
    for wartosc, typ, od_llm in {(tekst[a:b], typ, zr == "llm") for a, b, typ, zr in kandydaci if typ in ("OSOBA", "FIRMA", "NAZWA") and b - a >= 4}:
        for m in _wystapienia(tekst, wartosc):
            dodaj(m.start(), m.end(), typ, "propagacja-llm" if od_llm else "propagacja")

    # 2. Suma nakładających się zakresów
    kandydaci.sort(key=lambda k: (k[0], -k[1]))
    grupy: list[list[tuple[int, int, str, str]]] = []
    for k in kandydaci:
        if grupy and k[0] < max(x[1] for x in grupy[-1]):
            grupy[-1].append(k)
        else:
            grupy.append([k])
    for g in grupy:
        a, b = min(x[0] for x in g), max(x[1] for x in g)
        # Typ: LLM widzi kontekst i myli typy rzadziej niż NER (pomiar na zestawie wzorcowym), potem najdłuższy zakres
        z_llm = [x for x in g if x[3] == "llm" and x[2] != "INNE"]
        najlepszy = min(z_llm or g, key=lambda x: (-(x[1] - x[0]), PRIORYTET_ZRODLA.get(x[3], 9)))
        wynik.append(Zakres(a, b, najlepszy[2], {x[3] for x in g}))
    wynik.sort(key=lambda z: z.start)
    _ujednolic(tekst, wynik)

    # 3. Forma prawna za nazwą: zakres staje się firmą niezależnie od typu nadanego przez model
    for i, z in enumerate(wynik):
        if z.typ not in SKLEJANE:
            continue
        nastepny = wynik[i + 1].start if i + 1 < len(wynik) else len(tekst)
        m = RX_FORMA_PO.match(tekst[z.end:z.end + 60])
        if m and z.end + m.end() <= nastepny:
            z.end += m.end()
            z.typ = "FIRMA"
        elif z.typ == "NAZWA":  # numer wersji produktu: „TermoLak 2”
            m = re.match(r"\s\d{1,4}(?![\d.,/-])", tekst[z.end:z.end + 6])
            if m and z.end + m.end() <= nastepny:
                z.end += m.end()

    # 4. Sklejanie sąsiadów
    sklejone: list[Zakres] = []
    for z in wynik:
        p = sklejone[-1] if sklejone else None
        if p and p.typ in SKLEJANE and z.typ in SKLEJANE:
            odstep = tekst[p.end:z.start]
            ten_sam = (p.typ == z.typ and p.typ != "ADRES") or (z.typ == "FIRMA" and p.typ != "ADRES")
            sklej = (
                (ten_sam and re.fullmatch(r"[ \t]+|[ \t]*[-–][ \t]*", odstep))
                or (p.typ == "ADRES" and z.typ in ("MIEJSCE", "ADRES") and re.fullmatch(r",?[ \t]+(?:we?[ \t]+)?", odstep))
            )
            if sklej:
                p.end = z.end
                p.zrodla |= z.zrodla
                if z.typ == "FIRMA":
                    p.typ = "FIRMA"
                continue
        sklejone.append(z)
    _ujednolic(tekst, sklejone)  # drugi raz: sklejone nazwy wielowyrazowe porównywane w całości

    for z in sklejone:
        z.tekst = tekst[z.start:z.end]
    return sklejone

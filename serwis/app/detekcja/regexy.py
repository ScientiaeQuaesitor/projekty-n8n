"""Encje o stałym formacie. Zasada: priorytet ma recall, więc numer o poprawnym formacie
i błędnej sumie kontrolnej też jest zwracany (pewna=False), bo w dokumentach zdarzają się literówki."""
import regex as re  # pakiet regex zamiast re: obsługuje \p{L}, \p{Lu}

from .typy import Encja


def cyfry(s: str) -> str:
    return re.sub(r"\D", "", s)


def pesel_ok(s: str) -> bool:
    d = [int(c) for c in cyfry(s)]
    if len(d) != 11:
        return False
    wagi = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    return (10 - sum(a * b for a, b in zip(d, wagi)) % 10) % 10 == d[10]


def nip_ok(s: str) -> bool:
    d = [int(c) for c in cyfry(s)]
    if len(d) != 10:
        return False
    wagi = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    return sum(a * b for a, b in zip(d, wagi)) % 11 == d[9]


def regon_ok(s: str) -> bool:
    d = [int(c) for c in cyfry(s)]
    if len(d) == 9:
        wagi = [8, 9, 2, 3, 4, 5, 6, 7]
    elif len(d) == 14:
        wagi = [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]
    else:
        return False
    return sum(a * b for a, b in zip(d, wagi)) % 11 % 10 == d[-1]


def iban_ok(s: str) -> bool:
    d = cyfry(s)
    if len(d) != 26:
        return False
    return int(d[2:] + "2521" + d[:2]) % 97 == 1  # PL -> 25 21


def dowod_ok(s: str) -> bool:
    z = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{3}\d{6}", z):
        return False
    w = [ord(c) - 55 for c in z[:3]] + [int(c) for c in z[3:]]
    wagi = [7, 3, 1, 9, 7, 3, 1, 7, 3]
    return sum(a * b for a, b in zip(w, wagi)) % 10 == 0


def _kontekst(tekst: str, start: int, ile: int = 25) -> str:
    return tekst[max(0, start - ile):start].lower()


RX_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RX_IBAN = re.compile(r"(?<![\w])(?:PL\s?)?\d{2}(?:[  ]?\d{4}){6}(?!\d)")
RX_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
RX_PESEL_ROZBITY = re.compile(r"PESEL[:\s]{1,3}(\d(?:[ ]?\d){10})(?!\d)")
RX_10 = re.compile(r"(?<![\d-])(?:PL\s?)?(?:\d{10}|\d{3}-\d{3}-\d{2}-\d{2}|\d{3}-\d{2}-\d{2}-\d{3})(?![\d-])")
RX_14 = re.compile(r"(?<!\d)\d{14}(?!\d)")
RX_TEL = re.compile(
    r"(?<![\w+/-])(?:(?:\+48|0048)[\s-]?|\(\+48\)\s?)?"
    r"(?:\d{3}[\s-]\d{3}[\s-]\d{3}|\d{2}[\s-]\d{3}[\s-]\d{2}[\s-]\d{2}|\(\d{2}\)\s?\d{3}[\s-]?\d{2}[\s-]?\d{2}|\d{9})"
    r"(?![\d/-])"
)
RX_DOWOD = re.compile(r"(?<![A-Za-z])[A-Z]{3}\s?\d{6}(?!\d)")
RX_SYGN_SAD = re.compile(r"(?<![\w/])[IVXLC]{1,6}\s[A-Z][A-Za-z]{0,3}\s\d+/\d{2,4}(?![\w/])")
# Numer z ukośnikami lub myślnikami, z cyframi i literami: FV/2024/11/0452, ZL-2025-00871, ZG1E/00045871/3
RX_SYGN_NR = re.compile(r"(?<![\w/-])(?=[\w/-]*[A-Za-z])(?=[\w/-]*\d{2})[A-Za-z0-9]+(?:[/-][A-Za-z0-9]+){1,5}(?![\w/-])")
RX_NR_UKOSNIK = re.compile(r"(?<![\d/.,\p{L}])\d{1,5}/\d{1,5}(?:/\d{1,5})?(?![\d/\p{L}])")
RX_NR_KONTEKST = re.compile(r"dzia[łl]k\p{L}*|numer\p{L}*|\bnr\b|Rep\p{L}*\.?\s?A", re.I)
RX_ADRES_ULICA = re.compile(
    r"(?<!\p{L})(?:ul\.|ulic[aąęy]|al\.|alei|aleja|aleję|pl\.|placu?|os\.|osiedl[eu])\s+[\p{L}\d .'’-]{2,50}?\s\d+[A-Za-z]?"
    r"(?:\s?/\s?\d+[A-Za-z]?)?(?:[ ]+(?:m\.|lok\.)[ ]?\d+)?(?:,?\s+\d{2}-\d{3}[ ]+\p{Lu}[\p{L}-]+(?:[ ]\p{Lu}\p{Ll}[\p{L}-]*)?)?"
)
# Drugi człon nazwy miejscowości tylko w tym samym wierszu i pisany jak nazwa („Zielona Góra”, nie „Zabrze\nNIP”)
RX_KOD_MIASTO = re.compile(r"(?<!\d)\d{2}-\d{3}[ ]+\p{Lu}[\p{L}-]+(?:[ ]\p{Lu}\p{Ll}[\p{L}-]*)?")


def wykryj(tekst: str) -> list[Encja]:
    wynik: list[Encja] = []
    zajete: list[tuple[int, int]] = []

    def wolne(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in zajete)

    def dodaj(m_start: int, m_end: int, typ: str, pewna: bool = True) -> None:
        if not wolne(m_start, m_end):
            return
        zajete.append((m_start, m_end))
        wynik.append(Encja(m_start, m_end, typ, "regex", tekst[m_start:m_end], pewna))

    for m in RX_EMAIL.finditer(tekst):
        dodaj(m.start(), m.end(), "EMAIL")
    for m in RX_IBAN.finditer(tekst):
        dodaj(m.start(), m.end(), "IBAN", iban_ok(m.group()))
    for m in RX_14.finditer(tekst):
        dodaj(m.start(), m.end(), "REGON", regon_ok(m.group()))
    for m in RX_PESEL.finditer(tekst):
        dodaj(m.start(), m.end(), "PESEL", pesel_ok(m.group()))
    # PESEL rozbity spacjami przez OCR („PESEL 850 10112345”): rozpoznawany po słowie PESEL przed numerem
    for m in RX_PESEL_ROZBITY.finditer(tekst):
        dodaj(m.start(1), m.end(1), "PESEL", pesel_ok(m.group(1)))
    for m in RX_10.finditer(tekst):
        k = _kontekst(tekst, m.start())
        if "krs" in k:
            dodaj(m.start(), m.end(), "KRS")
        elif "nip" in k or nip_ok(m.group()):
            dodaj(m.start(), m.end(), "NIP", nip_ok(m.group()))
        elif cyfry(m.group()).startswith("0000"):
            dodaj(m.start(), m.end(), "KRS", False)
        else:
            dodaj(m.start(), m.end(), "NIP", False)
    for m in RX_ADRES_ULICA.finditer(tekst):
        dodaj(m.start(), m.end(), "ADRES")
    for m in RX_KOD_MIASTO.finditer(tekst):
        dodaj(m.start(), m.end(), "ADRES")
    for m in RX_TEL.finditer(tekst):
        if "regon" in _kontekst(tekst, m.start()) and len(cyfry(m.group())) == 9:
            dodaj(m.start(), m.end(), "REGON", regon_ok(m.group()))
        else:
            dodaj(m.start(), m.end(), "TELEFON")
    for m in RX_DOWOD.finditer(tekst):
        dodaj(m.start(), m.end(), "DOWOD", dowod_ok(m.group()))
    for rx in (RX_SYGN_SAD, RX_SYGN_NR):
        for m in rx.finditer(tekst):
            dodaj(m.start(), m.end(), "SYGNATURA")
    # Numer z ukośnikiem bez liter (repertorium, działka ewidencyjna): tylko gdy wcześniej w zdaniu stoi słowo
    # wskazujące na numer, a nie na ułamek („udział 95/10000”)
    for m in RX_NR_UKOSNIK.finditer(tekst):
        przed = tekst[max(0, m.start() - 110):m.start()]
        zdanie = re.split(r"[.;]\s|\n", przed)[-1]
        if RX_NR_KONTEKST.search(zdanie) and not re.search(r"udzia[łl]\p{L}*[^,]{0,25}$", zdanie):
            dodaj(m.start(), m.end(), "SYGNATURA")
    return sorted(wynik, key=lambda e: e.start)

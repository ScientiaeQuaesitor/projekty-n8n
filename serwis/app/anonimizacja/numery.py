"""Identyfikatory o stałym formacie: fałszywka w tym samym układzie znaków, z celowo błędną sumą kontrolną."""
import regex as re

from ..detekcja import regexy
from .sesja import Sesja

CYFROWE = {"PESEL", "NIP", "REGON", "KRS", "IBAN", "TELEFON", "KOD"}
KONTROLA = {"PESEL": regexy.pesel_ok, "NIP": regexy.nip_ok, "REGON": regexy.regon_ok, "IBAN": regexy.iban_ok}


def _klucz(typ: str, pow: str) -> str:
    if typ == "EMAIL":
        return pow.lower()
    if typ in CYFROWE:
        return regexy.cyfry(pow)
    return re.sub(r"[^\p{L}\d]", "", pow).upper()


def zajety(sesja: Sesja, ctx, surogat: str) -> bool:
    """Surogat numeru nie może wystąpić jako osobny ciąg w tekście oryginału ani powtórzyć surogatu wydanego już
    w sesji (także numeru domu). Deanonimizacja szuka surogatów dosłownie, więc kolizja oddałaby zły oryginał."""
    if ctx is not None and re.search(r"(?<![\p{L}\d])" + re.escape(surogat.lower()) + r"(?![\p{L}\d])", ctx.tekst_l):
        return True
    return surogat in sesja.uzyte("NRDOM") or ("ODWR", surogat, "") in sesja.formy or ("ODWR_N", surogat, "") in sesja.formy


def _falszywka(sesja: Sesja, typ: str, klucz: str, zakazane=lambda f: False) -> str | None:
    if typ == "EMAIL":
        n = sum(1 for k, _, _ in sesja.wpisy("NUMER") if k.startswith("EMAIL|")) + 1
        return f"adres{n}@poczta{n}.example"
    if not any(c.isdigit() for c in klucz):
        return None
    for proba in range(50):
        rng = sesja.losowe("NUMER", typ, klucz, proba)
        out = []
        for i, c in enumerate(klucz):
            if c.isdigit():
                stale = (typ == "KRS" and i < 4) or (typ == "TELEFON" and len(klucz) == 11 and i < 2)
                out.append(c if stale else str(rng.randint(1 if i == 0 else 0, 9)))
            else:
                out.append(chr(rng.randint(65, 90)) if typ == "DOWOD" else c)
        wynik = "".join(out)
        if wynik != klucz and not (typ in KONTROLA and KONTROLA[typ](wynik)) and not zakazane(wynik):
            return wynik
    return None


def _na_maske(pow: str, znaki: str, tylko_cyfry: bool) -> str:
    it = iter(znaki)
    out = []
    for c in pow:
        if c.isdigit() or (not tylko_cyfry and c.isalpha()):
            n = next(it, c)
            out.append(n.lower() if c.islower() else n)
        else:
            out.append(c)
    return "".join(out)


def podmien(sesja: Sesja, typ: str, pow: str, ctx=None) -> str | None:
    klucz = _klucz(typ, pow)
    wpis = sesja.wez("NUMER", f"{typ}|{klucz}")
    if wpis:
        falsz = wpis[0]
    else:
        tylko_cyfry = typ in CYFROWE

        def zakazane(f: str) -> bool:
            return zajety(sesja, ctx, f) or (typ != "EMAIL" and zajety(sesja, ctx, _na_maske(pow, f, tylko_cyfry)))

        falsz = _falszywka(sesja, typ, klucz, zakazane)
        if falsz is None:
            return None
        sesja.ustaw("NUMER", f"{typ}|{klucz}", falsz, {"typ": typ})
        sesja.zapamietaj_forme("ODWR_N", falsz, "", pow)
    wynik = falsz if typ == "EMAIL" else _na_maske(pow, falsz, typ in CYFROWE)
    sesja.zapamietaj_forme("ODWR", wynik, "", pow)
    return wynik


def znajdz(sesja: Sesja, tekst: str) -> list[tuple[int, int, str, bool]]:
    """Trafienia do deanonimizacji: (start, end, oryginał, niepewne)."""
    out = []
    for (kat, falsz, _), oryg in sesja.formy.items():
        if kat == "ODWR":
            for m in re.finditer(r"(?<![\p{L}\d])" + re.escape(falsz) + r"(?![\p{L}\d])", tekst, re.I if "@" in falsz else 0):
                out.append((m.start(), m.end(), oryg, False))
    # Ten sam numer w innym zapisie (np. bez spacji): dopasowanie po znormalizowanej postaci
    for e in regexy.wykryj(tekst):
        if any(a <= e.start and e.end <= b for a, b, _, _ in out):
            continue
        for typ in {e.typ, "TELEFON", "NIP", "KRS", "REGON", "PESEL", "IBAN", "SYGNATURA"}:
            oryg = sesja.forma("ODWR_N", _klucz(typ, e.tekst), "")
            if oryg:
                out.append((e.start, e.end, oryg, True))
                break
    return out

"""Wczytywanie dokumentów wzorcowych. Format: zwykły tekst ze znacznikami {{TYP|wartość}}.
Wartość zaczynająca się od @ to numer generowany z poprawną sumą kontrolną, np. {{PESEL|@1}},
{{NIP|@2:d}} (z myślnikami), {{IBAN|@1:pl}} (z prefiksem PL), {{IBAN|@1:c}} (bez spacji), {{DOWOD|@1:c}}."""
from dataclasses import dataclass
from pathlib import Path

import regex as re

from ..detekcja.typy import TYPY

KATALOG = Path(__file__).resolve().parents[2] / "testy" / "wzorce"
RX = re.compile(r"\{\{([A-Z_]+)\|(.*?)\}\}", re.S)


@dataclass(frozen=True)
class Wzorzec:
    start: int
    end: int
    typ: str
    tekst: str


def _pesel(n: int) -> str:
    d = f"{60 + n * 7 % 35:02d}{1 + n * 5 % 12:02d}{1 + n * 11 % 28:02d}{(1234 + n * 977) % 10000:04d}"
    wagi = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    return d + str((10 - sum(int(a) * b for a, b in zip(d, wagi)) % 10) % 10)


def _nip(n: int) -> str:
    baza = 521000000 + n * 1234567
    wagi = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    while True:
        d = f"{baza:09d}"
        k = sum(int(a) * b for a, b in zip(d, wagi)) % 11
        if k != 10:
            return d + str(k)
        baza += 1


def _regon(n: int) -> str:
    d = f"{14000000 + n * 345671:08d}"
    wagi = [8, 9, 2, 3, 4, 5, 6, 7]
    return d + str(sum(int(a) * b for a, b in zip(d, wagi)) % 11 % 10)


def _krs(n: int) -> str:
    return f"0000{(123456 + n * 98765) % 1000000:06d}"


def _iban(n: int) -> str:
    bban = f"{10201000 + n * 1111:08d}{(1234567890123456 + n * 1111111111) % 10**16:016d}"
    return f"{98 - int(bban + '252100') % 97:02d}{bban}"


def _dowod(n: int) -> str:
    litery = "A" + chr(65 + (n * 7) % 26) + chr(65 + (n * 11) % 26)
    reszta = f"{(48213 + n * 7919) % 100000:05d}"
    suma = sum((ord(c) - 55) * w for c, w in zip(litery, [7, 3, 1])) + sum(int(c) * w for c, w in zip(reszta, [7, 3, 1, 7, 3]))
    return litery + str(suma % 10) + reszta


def _generuj(typ: str, spec: str) -> str:
    numer, _, wariant = spec[1:].partition(":")
    n = int(numer)
    if typ == "PESEL":
        return _pesel(n)
    if typ == "NIP":
        v = _nip(n)
        return f"{v[:3]}-{v[3:6]}-{v[6:8]}-{v[8:]}" if wariant == "d" else v
    if typ == "REGON":
        return _regon(n)
    if typ == "KRS":
        return _krs(n)
    if typ == "IBAN":
        v = _iban(n)
        if wariant == "c":
            return v
        spacje = v[:2] + " " + " ".join(v[i:i + 4] for i in range(2, 26, 4))
        return "PL" + spacje if wariant == "pl" else spacje
    if typ == "DOWOD":
        v = _dowod(n)
        return v if wariant == "c" else v[:3] + " " + v[3:]
    raise ValueError(f"Brak generatora dla typu {typ}")


def parsuj(zrodlo: str) -> tuple[str, list[Wzorzec]]:
    tekst, wzorce, pos = [], [], 0
    dlugosc = 0
    for m in RX.finditer(zrodlo):
        przed = zrodlo[pos:m.start()]
        tekst.append(przed)
        dlugosc += len(przed)
        typ, wartosc = m.group(1), m.group(2)
        if typ not in TYPY and typ != "ZOSTAW":
            raise ValueError(f"Nieznany typ w znaczniku: {m.group(0)}")
        if wartosc.startswith("@"):
            wartosc = _generuj(typ, wartosc)
        wzorce.append(Wzorzec(dlugosc, dlugosc + len(wartosc), typ, wartosc))
        tekst.append(wartosc)
        dlugosc += len(wartosc)
        pos = m.end()
    tekst.append(zrodlo[pos:])
    calosc = "".join(tekst)
    if "{{" in calosc or "}}" in calosc:
        raise ValueError("Niedomknięty lub błędny znacznik w dokumencie wzorcowym")
    return calosc, wzorce


def wczytaj() -> dict[str, tuple[str, list[Wzorzec]]]:
    """Dokumenty z encjami do podmiany (bez fragmentów ZOSTAW)."""
    out = {}
    for p in sorted(KATALOG.glob("*.txt")):
        tekst, wzorce = parsuj(p.read_text(encoding="utf-8"))
        out[p.stem] = (tekst, [w for w in wzorce if w.typ != "ZOSTAW"])
    return out


def wczytaj_zostaw() -> dict[str, list[Wzorzec]]:
    """Fragmenty, które anonimizacja musi zostawić bez zmian: pojęcia prawne, nazwy ustaw, daty, kwoty, numery wewnętrzne."""
    return {p.stem: [w for w in parsuj(p.read_text(encoding="utf-8"))[1] if w.typ == "ZOSTAW"] for p in sorted(KATALOG.glob("*.txt"))}

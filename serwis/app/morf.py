"""Cienka warstwa nad Morfeusz2 (słownik SGJP): analiza i generowanie form."""
from dataclasses import dataclass
from functools import lru_cache

import morfeusz2

PRZYPADKI = ("nom", "gen", "dat", "acc", "inst", "loc", "voc")
KLASY_FUNKCYJNE = {"prep", "conj", "comp", "qub", "adv", "fin", "praet", "impt", "inf", "pcon", "pant", "pred", "interj",
                   "bedzie", "aglt", "imps", "winien", "ppron12", "ppron3", "siebie", "num", "part"}


@dataclass(frozen=True)
class Interpretacja:
    forma: str
    lemat: str
    klasa: str          # subst, adj, depr, ign, prep...
    liczba: str         # sg, pl albo ""
    przypadki: tuple    # np. ("gen", "acc")
    rodzaj: str         # m1, m2, m3, f, n albo ""
    nazwy: tuple        # ("imię", "nazwisko", "nazwa_geograficzna", "nazwa_pospolita")
    rodzaje: tuple = () # wszystkie rodzaje z tagu (przymiotnik ma ich kilka)

    def trojki(self) -> set:
        """Zbiór (liczba, przypadek, rodzaj) do sprawdzania zgody rzeczownika z przymiotnikiem."""
        return {(self.liczba, p, r) for p in self.przypadki for r in self.rodzaje}


@lru_cache(maxsize=1)
def _m():
    return morfeusz2.Morfeusz(expand_tags=False)


def _rozbij(forma: str, lemat: str, tag: str, nazwy) -> Interpretacja:
    czesci = tag.split(":")
    klasa = czesci[0]
    liczba = next((c for c in czesci[1:] if c in ("sg", "pl")), "")
    przypadki = tuple(p for c in czesci[1:] for p in c.split(".") if p in PRZYPADKI)
    rodzaje = tuple(r for c in czesci[1:] for r in c.split(".") if r in ("m1", "m2", "m3", "f", "n"))
    return Interpretacja(forma, lemat.split(":")[0], klasa, liczba, przypadki, rodzaje[0] if rodzaje else "", tuple(nazwy), rodzaje)


@lru_cache(maxsize=50000)
def analizuj(slowo: str) -> tuple[Interpretacja, ...]:
    """Interpretacje pojedynczego słowa. Dla słów spoza słownika jedna interpretacja klasy ign."""
    return tuple(_rozbij(orth, lemat, tag, nazwy) for _, _, (orth, lemat, tag, nazwy, _) in _m().analyse(slowo))


@lru_cache(maxsize=20000)
def generuj(lemat: str) -> tuple[Interpretacja, ...]:
    """Wszystkie formy lematu znane słownikowi."""
    return tuple(_rozbij(forma, lem, tag, nazwy) for forma, lem, tag, nazwy, _ in _m().generate(lemat))


_OGONKI = {"a": "ą", "c": "ć", "e": "ę", "l": "ł", "n": "ń", "o": "ó", "s": "ś", "z": "żź"}


@lru_cache(maxsize=50000)
def z_ogonkami(slowo: str) -> tuple[str, ...]:
    """Warianty słowa spoza słownika z przywróconymi znakami diakrytycznymi (do dwóch zamian), które słownik zna.
    OCR często gubi ogonki: „legitymujacy”, „Stawajacych”."""
    if any(i.klasa != "ign" for i in analizuj(slowo)):
        return ()
    pozycje = [i for i, c in enumerate(slowo.lower()) if c in _OGONKI]
    warianty = set()

    def zamien(baza: str, i: int):
        for znak in _OGONKI[baza[i].lower()]:
            yield baza[:i] + (znak.upper() if baza[i].isupper() else znak) + baza[i + 1:]

    for i in pozycje:
        for w1 in zamien(slowo, i):
            warianty.add(w1)
            for j in pozycje:
                if j > i:
                    warianty.update(zamien(w1, j))
    return tuple(sorted(w for w in warianty if any(i.klasa != "ign" for i in analizuj(w))))


def analizuj_ocr(slowo: str) -> tuple[Interpretacja, ...]:
    """Jak analizuj, ale dla słowa spoza słownika zwraca interpretacje jego wariantów z ogonkami („Wroclawiu” -> Wrocław)."""
    inter = analizuj(slowo)
    if any(i.klasa != "ign" for i in inter):
        return inter
    warianty = tuple(i for w in z_ogonkami(slowo) for i in analizuj(w))
    return warianty or inter


def rodzaj_slowa(slowo: str) -> str:
    """pospolite: istnieje w słowniku jako zwykły wyraz; wlasne: tylko jako imię, nazwisko lub nazwa geograficzna;
    ign: spoza słownika, także po przywróceniu ogonków."""
    w = slowo.capitalize() if len(slowo) > 1 and slowo.isupper() else slowo
    inter = [i for i in analizuj_ocr(w) if i.klasa != "ign"]
    if any(i.lemat[:1].islower() for i in inter):
        return "pospolite"
    return "wlasne" if inter else "ign"


def tylko_funkcyjne(slowo: str) -> bool:
    """Prawda, gdy słowo ma wyłącznie interpretacje funkcyjne (przyimek, spójnik, czasownik, przysłówek)."""
    inter = analizuj(slowo)
    return bool(inter) and all(i.klasa in KLASY_FUNKCYJNE for i in inter)

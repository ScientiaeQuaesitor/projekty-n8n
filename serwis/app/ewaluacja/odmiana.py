"""Test odmiany nazw firm spoza słownika (PLAN 3.6). Dane fikcyjne z testy/wzorce/odmiana_nazw.tsv.

Uruchomienie w kontenerze:  python -m app.ewaluacja.odmiana

Sprawdza: (1) regułę nazwy.formy_ign na każdym przypadku, (2) deanonimizację formy surogatu w przypadku, którego
w oryginale nie było (model zewnętrzny napisał „w Tarvonie”, a oryginał miał tylko „Stalmet”), (3) czy forma oryginału
z wymianą spółgłoski („w Stalmecie”) dostaje ten sam surogat co mianownik."""
import regex as re

from ..anonimizacja import nazwy, pule, silnik
from ..anonimizacja.sesja import Sesja
from ..detekcja.typy import Encja
from .uruchom import WYNIKI
from .wzorce import KATALOG

PRZYPADKI = ("gen", "dat", "acc", "inst", "loc")
ZDANIE = {"gen": "Zarząd {} przyjął plan.", "dat": "Przekazano dokumenty {} w terminie.", "acc": "Reprezentuje {} pełnomocnik.",
          "inst": "Umowę zawarto z {} w marcu.", "loc": "Pracował w {} przez rok."}


def _encje(tekst: str, fragmenty: list[str]) -> list[Encja]:
    out = []
    for f in fragmenty:
        for m in re.finditer(r"(?<!\p{L})" + re.escape(f) + r"(?!\p{L})", tekst):
            out.append(Encja(m.start(), m.end(), "FIRMA", "regex", f))
    return out


def main() -> None:
    wiersze = [l.split("\t") for l in (KATALOG / "odmiana_nazw.tsv").read_text(encoding="utf-8").splitlines()
               if l.strip() and not l.startswith("#")]
    bledy_reguly, bledy_powrotu, bledy_spojnosci = [], [], []
    for w in wiersze:
        lemat, oczek = w[0], dict(zip(PRZYPADKI, w[1:]))
        formy = nazwy.formy_ign(lemat)
        bledy_reguly += [f"{lemat} {p}: {formy[p]} zamiast {f}" for p, f in oczek.items() if formy[p] != f]

        # (2) Oryginał zawiera tylko mianownik; tekst „od modelu” ma surogat w każdym przypadku
        tekst = f"Spółka {lemat} z siedzibą w mieście zawarła umowę."
        sesja = Sesja(sciezka=":memory:", nowe_id="odmiana")
        wynik = silnik.anonimizuj(sesja, tekst, _encje(tekst, [lemat]), weryfikuj=False)
        sur = next((p["surogat"] for p in wynik["podmiany"] if p["oryginal"] == lemat), None)
        if not sur:
            bledy_powrotu.append(f"{lemat}: brak podmiany")
            continue
        for p, f in oczek.items():
            odp = ZDANIE[p].format(pule.formy_nazwy(sur)[p])
            powrot = silnik.deanonimizuj(sesja, odp)["tekst"]
            if powrot != ZDANIE[p].format(f):
                bledy_powrotu.append(f"{lemat} {p}: „{powrot}” zamiast „{ZDANIE[p].format(f)}”")

        # (3) Mianownik i miejscownik w jednym dokumencie: jeden surogat
        tekst = f"Spółka {lemat} zatrudnia 40 osób. Pracował w {oczek['loc']} przez rok."
        sesja = Sesja(sciezka=":memory:", nowe_id="odmiana")
        wynik = silnik.anonimizuj(sesja, tekst, _encje(tekst, [lemat, oczek["loc"]]), weryfikuj=False)
        sur = {p["oryginal"]: p["surogat"] for p in wynik["podmiany"]}
        if len(sur) != 2 or sur[lemat][:4] != sur[oczek["loc"]][:4]:
            bledy_spojnosci.append(f"{lemat}: {sur}")
        powrot = silnik.deanonimizuj(sesja, wynik["tekst"])["tekst"]
        if powrot != tekst:
            bledy_spojnosci.append(f"{lemat}: po obiegu „{powrot}”")

    linie = ["# Odmiana nazw spoza słownika (PLAN 3.6)\n",
             f"Nazw: {len(wiersze)}, przypadków: {len(wiersze) * len(PRZYPADKI)}.\n",
             f"1. Reguła odmiany, błędy: {len(bledy_reguly)}",
             f"2. Deanonimizacja przypadku niewidzianego w oryginale, błędy: {len(bledy_powrotu)}",
             f"3. Forma z wymianą w oryginale, niespójny surogat lub różnica po obiegu: {len(bledy_spojnosci)}\n"]
    linie += [f"1. {b}" for b in bledy_reguly + bledy_powrotu + bledy_spojnosci]
    tresc = "\n".join(linie) + "\n"
    (WYNIKI / "odmiana_nazw.md").write_text(tresc, encoding="utf-8")
    print(tresc)


if __name__ == "__main__":
    main()

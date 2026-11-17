"""Anonimizacja i deanonimizacja tekstu w ramach sesji."""
import time

import regex as re

from .. import detekcja, morf
from ..detekcja.scal import Zakres, _lematy, scal
from ..detekcja.typy import Encja
from . import adresy, nazwy, numery, osoby
from .sesja import Sesja

DOMYSLNE_DETEKTORY = ["regex", "spacy", "hf", "llm"]
NUMEROWE = {"PESEL", "NIP", "REGON", "KRS", "IBAN", "TELEFON", "EMAIL", "DOWOD", "SYGNATURA", "INNE"}


class Kontekst:
    """Dane jednego dokumentu potrzebne modułom: słowa tekstu (kolizje surogatów), lematy nazw spoza słownika, aliasy firm."""

    def __init__(self, sesja: Sesja, tekst: str, zakresy: list[Zakres]):
        self.tekst_l = tekst.lower()
        self.slowa = set(re.findall(r"\p{L}+", self.tekst_l))
        self.analizy: dict[tuple[str, str], tuple[dict, str]] = {}
        self.aliasy: dict[tuple[str, str], str] = {}
        self.dlugie: set[tuple[str, str]] = set()
        self._pamiec: dict[tuple[str, str], dict | None] = {}
        # Słowa spoza słownika otwierające nazwy firm i produktów: najkrótsza forma służy za lemat pozostałych
        self.ign: set[str] = set()
        rdzenie = []
        for z in zakresy:
            if z.typ in ("FIRMA", "NAZWA"):
                rdzen = nazwy.RX_FORMA_KONIEC.sub("", z.tekst) if z.typ == "FIRMA" else z.tekst
                m = nazwy.RX_W.search(rdzen)
                if m and not any(i.klasa in nazwy.ODMIENNE for i in nazwy._an(m.group())[1]):
                    self.ign.add(m.group())
                rdzenie.append((z.typ, rdzen))
        for kat in ("FIRMA", "NAZWA"):
            for _, _, d in sesja.wpisy(kat):
                self.ign.update(g["lemat"] for g in d.get("grupa", []) if g["klasa"] == "ign")
        # Aliasy: nazwa skrócona jest przedrostkiem (po słowach) dokładnie jednej dłuższej nazwy
        klucze: dict[str, set[str]] = {"FIRMA": {k for k, _, _ in sesja.wpisy("FIRMA")}, "NAZWA": {k for k, _, _ in sesja.wpisy("NAZWA")}}
        for kat, rdzen in rdzenie:
            an = self.analizy_zakresu(kat, rdzen)
            if an:
                klucze[kat].add(an["klucz"])
                self.analizy.setdefault((kat, an["klucz"]), (an, next((p for p in ("nom", "gen", "acc", "inst", "loc", "dat") if p in an["kand"]), "nom")))
        for kat, zbior in klucze.items():
            for k in zbior:
                kt = k.split(" ")
                dluzsze = {k2 for k2 in zbior if len(k2.split(" ")) > len(kt) and k2.split(" ")[:len(kt)] == kt}
                if len(dluzsze) == 1 and (kat, next(iter(dluzsze))) in self.analizy | {(kat, x): None for x, _, _ in sesja.wpisy(kat)}:
                    dlugi = next(iter(dluzsze))
                    if (kat, dlugi) in self.analizy or sesja.wez(kat, dlugi):
                        self.aliasy[(kat, k)] = dlugi
                        self.dlugie.add((kat, dlugi))

    def lemat_ign(self, w: str) -> str:
        kand = [s for s in self.ign if w.lower().startswith(s.lower()) and w[len(s):].lower() in nazwy.KONCOWKI_IGN]
        return min(kand, key=len) if kand else w

    def analizy_zakresu(self, kat: str, rdzen: str) -> dict | None:
        if (kat, rdzen) not in self._pamiec:
            self._pamiec[(kat, rdzen)] = nazwy.analizuj_nazwe(rdzen, self)
        return self._pamiec[(kat, rdzen)]


def _same_pospolite(fragment: str) -> bool:
    """Prawda, gdy każde słowo fragmentu istnieje w słowniku jako zwykły wyraz (pisane małą literą)."""
    slowa = re.findall(r"\p{L}+", fragment)
    if len(fragment) < 4 or not slowa:
        return False
    for w in slowa:
        # Imię, nazwisko albo miejscowość znane słownikowi nigdy nie trafiają do oceny: „Martą”, „Michałowi”
        if any(set(i.nazwy) & {"imię", "nazwisko", "nazwa_geograficzna"} for i in morf.analizuj(w) + morf.analizuj(w.capitalize())):
            return False
        if not any(i.klasa != "ign" for i in morf.analizuj(w.lower())):
            return False
    return True


def odsiej_ogolne(tekst: str, encje: list[Encja], pamiec: dict | None = None) -> tuple[list[Encja], list[str]]:
    """Zakresy wskazane tylko przez NER i złożone ze zwykłych słów („Nieruchomość Wspólna”, „Akt notarialny”)
    ocenia LLM. Odrzucane są wyłącznie te, które uzna za określenia ogólne."""
    llm_teksty = {e.tekst.strip(" .,;:\"„”()") for e in encje if e.zrodlo == "llm"}
    kandydaci: dict[str, str] = {}
    for e in encje:
        if e.zrodlo not in ("spacy", "hf"):
            continue
        f = e.tekst.strip(" .,;:\"„”()\n")
        if f and "\n" not in f and f not in llm_teksty and f not in kandydaci and _same_pospolite(f):
            kandydaci[f] = tekst[max(0, e.start - 60):e.end + 40].replace("\n", " ")
    if not kandydaci:
        return encje, []
    pamiec = pamiec if pamiec is not None else {}
    nowe = [(f, k) for f, k in kandydaci.items() if f not in pamiec]
    if nowe:
        ogolne = detekcja.llm.zweryfikuj(nowe)
        pamiec.update({f: f in ogolne for f, _ in nowe})
    odrzucone = {f for f in kandydaci if pamiec.get(f)}
    return [e for e in encje if not (e.zrodlo in ("spacy", "hf") and e.tekst.strip(" .,;:\"„”()\n") in odrzucone)], sorted(odrzucone)


def _sygnatura(fragment: str) -> list:
    return [_lematy(w) for w in re.findall(r"[\p{L}\d]+", fragment)]


def _pasuje(a: list, b: list) -> bool:
    """Te same słowa w dowolnych formach gramatycznych."""
    return bool(a) and len(a) == len(b) and all(x & y for x, y in zip(a, b))


# Polityka: co robić z nazwą danej kategorii. Kategorię ustala LLM z kontekstu (detekcja.llm.klasyfikuj).
KATEGORIE_ZOSTAW = {"INSTYTUCJA", "AKT_PRAWNY", "DOKUMENT", "POJECIE"}   # zostaje; podmieniane są tylko człony własne
TYP_KATEGORII = {"OSOBA": "OSOBA", "FIRMA": "FIRMA", "PRODUKT": "NAZWA", "MIEJSCE": "MIEJSCE"}   # podmiana w całości


def _slowa_osobowe(fragment: str) -> list[str]:
    return [w for w in re.findall(r"\p{L}+", fragment) if len(w) > 1]


def _pewna_osoba(fragment: str) -> bool:
    """Każde słowo jest w słowniku imieniem lub nazwiskiem i co najmniej jedno nie ma znaczenia pospolitego."""
    slowa = _slowa_osobowe(fragment)
    return (bool(slowa) and all(osoby._imie_i(w) or osoby._nazw_i(w) for w in slowa)
            and any(morf.rodzaj_slowa(w) == "wlasne" for w in slowa))


def kategorie_zakresow(tekst: str, zakresy: list[Zakres], pamiec: dict | None = None, model: str | None = None,
                       encje: list[Encja] | None = None, zapisz_pamiec=None, czasy: dict | None = None) -> dict[str, str]:
    """Kategoria każdej wykrytej nazwy. Bez klasyfikacji (zawsze podmiana) zostają: osoby pewne słownikowo, nazwiska
    występujące w dokumencie obok imienia oraz firmy z formą prawną.

    Klucz pamięci zaczyna się od odcisku promptu, wariantu i modelu, więc zmiana któregokolwiek nie używa starych ocen.
    zapisz_pamiec(pamiec) jest wołane po każdej paczce zapytań. czasy dostają czas i liczbę zapytanych nazw na wariant."""
    znane_nazwiska = [lem for z in zakresy if z.typ == "OSOBA" and _pewna_osoba(z.tekst) for lem in _sygnatura(z.tekst)]
    llm_syg = [_sygnatura(e.tekst) for e in (encje or []) if e.zrodlo == "llm"]
    z_gory: dict[str, str] = {}
    kandydaci: dict[str, str] = {}
    for z in zakresy:
        if z.typ not in ("OSOBA", "FIRMA", "NAZWA", "MIEJSCE") or z.tekst in kandydaci or z.tekst in z_gory:
            continue
        if nazwy.RX_FORMA_KONIEC.search(z.tekst) or nazwy.RX_FORMA_SRODEK.search(z.tekst):
            continue
        syg0 = _sygnatura(z.tekst)
        tylko_pospolite = len(syg0) == 1 and bool(re.fullmatch(r"\p{L}+", z.tekst)) and not any(
            i.klasa == "ign" or set(i.nazwy) & {"imię", "nazwisko", "nazwa_geograficzna"} for i in morf.analizuj_ocr(z.tekst))
        if (llm_syg and tylko_pospolite and z.typ in ("FIRMA", "NAZWA") and not z.zrodla & {"llm", "propagacja-llm"}
                and not any(_pasuje(syg0, s[:1]) for s in llm_syg)):
            z_gory[z.tekst] = "POJECIE"   # wskazał go tylko NER; nazwy jednowyrazowe ze zwykłego słowa zna detektor LLM
            continue
        if z.typ == "OSOBA" and any(osoby._imie_i(w) or osoby._nazw_i(w) for w in _slowa_osobowe(z.tekst)):
            continue   # zakres osobowy zawierający słowo znane słownikowi jako imię lub nazwisko jest podmieniany zawsze
        kandydaci[z.tekst] = tekst[max(0, z.start - 220):z.end + 160].replace("\n", " ")
    pamiec = pamiec if pamiec is not None else {}
    glosy: dict[str, list[str]] = {f: [] for f in kandydaci}
    for wariant in detekcja.llm.WARIANTY_KLASYFIKACJI:
        odcisk = detekcja.llm.odcisk_klasyfikacji(wariant, model)
        nowe = [(f, k) for f, k in kandydaci.items() if f"{odcisk}|{f}|{k}" not in pamiec]
        t0 = time.time()
        if nowe:
            def po_paczce(paczka, oceny, odcisk=odcisk):
                # Brak oceny też jest zapamiętany (None), żeby wznowienie nie pytało drugi raz
                pamiec.update({f"{odcisk}|{f}|{k}": oceny.get(f) for f, k in paczka})
                if zapisz_pamiec:
                    zapisz_pamiec(pamiec)
            detekcja.llm.klasyfikuj(nowe, model, wariant, po_paczce=po_paczce)
        if czasy is not None:
            czasy[f"klasyfikacja_{wariant}"] = {"s": round(time.time() - t0, 1), "zapytane": len(nowe), "z_pamieci": len(kandydaci) - len(nowe)}
        for f, k in kandydaci.items():
            if pamiec.get(f"{odcisk}|{f}|{k}"):
                glosy[f].append(pamiec[f"{odcisk}|{f}|{k}"])
    wynik = dict(z_gory)
    for f, g in glosy.items():
        zostaw = [x for x in g if x in KATEGORIE_ZOSTAW]
        podmien = [x for x in g if x not in KATEGORIE_ZOSTAW]
        # Nazwa zostaje tylko przy co najmniej dwóch głosach „zostaw”. Remis i brak ocen oznaczają podmianę.
        strona = zostaw if len(zostaw) >= 2 else podmien
        if strona:
            wynik[f] = max(set(strona), key=strona.count)
        if zostaw and len(zostaw) < 2:
            wynik[f] = "SPORNE:" + wynik.get(f, "FIRMA")   # głosy podzielone, większość za podmianą
    return wynik


def anonimizuj(sesja: Sesja, tekst: str, encje: list[Encja] | None = None, detektory: list[str] | None = None,
               weryfikuj: bool = True, pamiec: dict | None = None, model_klasyfikacji: str | None = None,
               zapisz_pamiec=None, czasy: dict | None = None) -> dict:
    """czasy, jeśli podane, dostają czas faz w sekundach: detekcja, scalanie, klasyfikacja (na wariant), podmiana."""
    czasy = czasy if czasy is not None else {}
    t0 = time.time()
    if encje is None:
        encje = detekcja.wykryj(tekst, detektory or DOMYSLNE_DETEKTORY)
        czasy["detekcja"] = round(time.time() - t0, 1)
    t0 = time.time()
    zakresy = scal(tekst, encje)
    czasy["scalanie"] = round(time.time() - t0, 1)
    kategorie = kategorie_zakresow(tekst, zakresy, pamiec, model_klasyfikacji, encje, zapisz_pamiec, czasy) if weryfikuj else {}
    t_podmiana = time.time()
    ctx = Kontekst(sesja, tekst, zakresy)

    # Przebieg 1: pary imię + nazwisko z całego dokumentu (potrzebne dla inicjałów i płci samych nazwisk)
    for z in zakresy:
        if z.typ == "OSOBA":
            an = osoby.rozbierz(sesja, z.tekst, tekst, z.start)
            if an:
                osoby.zarejestruj_pary(sesja, an)

    # Przebieg 2: podmiana
    out, pos, podmiany, pominiete = [], 0, [], []
    poprz = None
    for z in zakresy:
        pierwsze = nazwy.RX_W.search(z.tekst)
        odstep = tekst[poprz.end:z.start] if poprz else ""
        nazwisko_po_osobie = (z.typ == "MIEJSCE" and poprz is not None and poprz.typ == "OSOBA" and bool(re.fullmatch(r"\p{L}+", z.tekst))
                              and morf.rodzaj_slowa(z.tekst) == "ign" and len(odstep) <= 25
                              and not re.search(r"[.;\n]|(?:^|\s)(?:w|we|z|ze|do)\s*$", odstep))
        poprz = z
        if nazwisko_po_osobie:
            z.typ = "OSOBA"  # nieznane słowo tuż po osobie, oznaczone jako miejsce: „Jan Paweł (drugie imię) Kowalczyk”
        z_malej = bool(re.match(r"\p{Ll}+(?![\p{Lu}\d])", z.tekst)) and not z.zrodla & {"regex", "llm", "propagacja-llm"}
        if z_malej and z.typ in ("FIRMA", "NAZWA", "MIEJSCE", "OSOBA") and morf.rodzaj_slowa(re.match(r"\p{L}+", z.tekst).group()) == "pospolite":
            # „dnia 27.04.2016 r., w sprawie ochrony osób fizycznych…”, „rozporządzenie o ochronie danych”
            pominiete.append({**z.jako_dict(), "powod": "zaczyna się małą literą, bez potwierdzenia LLM"})
            continue
        kategoria = kategorie.get(z.tekst)
        if kategoria and kategoria.startswith("SPORNE:"):
            # Głosy podzielone. Jeśli nazwa ma budowę opisową (zaczyna się zwykłym słowem i zawiera człon własny), to
            # podmieniany jest tylko ten człon: „Kancelaria Notarialna we Wrocławiu”. W innym razie podmiana w całości.
            kategoria = kategoria.split(":", 1)[1]
            pierwsze_slowo = re.match(r"\P{L}*(\p{L}+)", z.tekst)
            if (pierwsze_slowo and morf.rodzaj_slowa(pierwsze_slowo.group(1)) == "pospolite"
                    and not nazwy.RX_FORMA_KONIEC.search(z.tekst) and not nazwy.RX_FORMA_SRODEK.search(z.tekst)):
                nowe = nazwy.podmien_wlasne(sesja, z.tekst, tekst, z.start, ctx)
                if nowe and nowe != z.tekst:
                    out += [tekst[pos:z.start], nowe]
                    pos = z.end
                    podmiany.append({"start": z.start, "end": z.end, "typ": "OPISOWA", "oryginal": z.tekst, "surogat": nowe})
                    continue
        if kategoria in KATEGORIE_ZOSTAW:
            # „Kodeks cywilny”, „Umowa Przedwstępna”, „Specjalna Strefa Ekonomiczna” zostają; w „Sąd Rejonowy w Gliwicach”
            # i „Rada Miejska Wrocławia” podmieniana jest tylko miejscowość
            nowe = nazwy.podmien_wlasne(sesja, z.tekst, tekst, z.start, ctx)
            if nowe is None or nowe == z.tekst:
                pominiete.append({**z.jako_dict(), "powod": f"kategoria {kategoria}"})
                continue
            out += [tekst[pos:z.start], nowe]
            pos = z.end
            podmiany.append({"start": z.start, "end": z.end, "typ": kategoria, "oryginal": z.tekst, "surogat": nowe})
            continue
        if kategoria in TYP_KATEGORII and not (z.typ == "OSOBA" and kategoria == "MIEJSCE"):
            z.typ = TYP_KATEGORII[kategoria]
        if z.typ in ("FIRMA", "NAZWA") and re.fullmatch(r"\p{L}+", z.tekst) and morf.rodzaj_slowa(z.tekst) == "wlasne" and any(
                "nazwa_geograficzna" in i.nazwy for i in morf.analizuj_ocr(z.tekst.capitalize() if z.tekst.isupper() else z.tekst)):
            z.typ = "MIEJSCE"  # pojedyncze słowo znane słownikowi wyłącznie jako miejscowość
        if z.typ == "OSOBA":
            nowe = osoby.podmien(sesja, z.tekst, tekst, z.start, ctx)
        elif z.typ in ("FIRMA", "NAZWA"):
            nowe = nazwy.nazwa(sesja, z.tekst, tekst, z.start, ctx, z.typ)
        elif z.typ == "MIEJSCE":
            nowe = nazwy.miejsce(sesja, z.tekst, tekst, z.start, ctx)
        elif z.typ == "ADRES":
            nowe = adresy.podmien(sesja, z.tekst, tekst, z.start, ctx)
        else:
            nowe = numery.podmien(sesja, z.typ if z.typ in NUMEROWE else "INNE", z.tekst, ctx)
        if nowe is None or nowe == z.tekst:
            pominiete.append(z.jako_dict())
            continue
        out.append(tekst[pos:z.start])
        out.append(nowe)
        pos = z.end
        podmiany.append({"start": z.start, "end": z.end, "typ": z.typ, "oryginal": z.tekst, "surogat": nowe})
    out.append(tekst[pos:])
    czasy["podmiana"] = round(time.time() - t_podmiana, 1)
    return {"tekst": "".join(out), "podmiany": podmiany, "pominiete": pominiete, "kategorie": kategorie,
            "odrzucone_jako_ogolne": sorted(f for f, k in kategorie.items() if k in KATEGORIE_ZOSTAW),
            "sporne": sorted(f for f, k in kategorie.items() if k.startswith("SPORNE:"))}


def deanonimizuj(sesja: Sesja, tekst: str) -> dict:
    trafienia: list[tuple[int, int, str, bool]] = []

    def wolne(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y, _, _ in trafienia)

    for t in numery.znajdz(sesja, tekst) + adresy.znajdz(sesja, tekst):
        if wolne(t[0], t[1]):
            trafienia.append(t)

    idx_os, idx_nz = osoby.indeks(sesja), nazwy.indeks(sesja)
    formy = {}
    for idx, rodzaj in ((idx_os, "os"), (idx_nz, "nz")):
        for forma, wpisy in idx.items():
            for wariant in {forma, forma.upper()}:
                formy.setdefault(wariant, (rodzaj, wpisy))
    if formy:
        rx = re.compile(r"(?<![\p{L}\d])(?:" + "|".join(re.escape(f) for f in sorted(formy, key=len, reverse=True)) + r")(?![\p{L}\d])")
        grupa: list[dict] = []

        def zamknij() -> None:
            if grupa:
                trafienia.extend(osoby.odtworz(sesja, list(grupa), tekst))
                grupa.clear()

        for m in rx.finditer(tekst):
            if not wolne(m.start(), m.end()):
                continue
            rodzaj, wpisy = formy[m.group()]
            if rodzaj == "os":
                if grupa and not re.fullmatch(r"[  ]|\s?[-–]\s?", tekst[grupa[-1]["b"]:m.start()]):
                    zamknij()
                grupa.append({"a": m.start(), "b": m.end(), "w": m.group(), "wpisy": wpisy})
            else:
                zamknij()
                t = nazwy.odtworz(sesja, m.start(), m.end(), m.group(), wpisy, tekst)
                if t:
                    trafienia.append(t)
        zamknij()

    trafienia.sort()
    out, pos, niepewne = [], 0, []
    for a, b, nowe, niepewna in trafienia:
        if a < pos:
            continue
        out.append(tekst[pos:a])
        out.append(nowe)
        if niepewna:
            niepewne.append({"surogat": tekst[a:b], "oryginal": nowe, "kontekst": tekst[max(0, a - 40):b + 30].replace("\n", " ")})
        pos = b
    out.append(tekst[pos:])
    return {"tekst": "".join(out), "niepewne": niepewne}

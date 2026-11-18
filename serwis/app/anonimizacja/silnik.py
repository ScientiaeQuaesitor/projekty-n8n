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
        # Aliasy: nazwa skrócona odpowiada początkowi dokładnie jednej dłuższej nazwy. Słowo po słowie albo skrótowcem,
        # którego litery są inicjałami kolejnych członów: „PPH „Orzeł”” i „Przedsiębiorstwo Produkcyjno-Handlowe „Orzeł””.
        klucze: dict[str, set[str]] = {"FIRMA": {k for k, _, _ in sesja.wpisy("FIRMA")}, "NAZWA": {k for k, _, _ in sesja.wpisy("NAZWA")}}
        skroty: dict[str, set[str]] = {}
        for kat, rdzen in rdzenie:
            an = self.analizy_zakresu(kat, rdzen)
            if an:
                klucze[kat].add(an["klucz"])
                skroty.setdefault(an["klucz"], set()).update(w.lower() for w in nazwy.RX_W.findall(rdzen) if nazwy.skrotowiec(w))
                self.analizy.setdefault((kat, an["klucz"]), (an, next((p for p in ("nom", "gen", "acc", "inst", "loc", "dat") if p in an["kand"]), "nom")))
        for kat, zbior in klucze.items():
            for k in zbior:
                kt = k.split(" ")
                dluzsze = {k2 for k2 in zbior if len(k2.split(" ")) > len(kt) and nazwy.poczatek_nazwy(kt, k2.split(" "), skroty.get(k, set()))}
                if len(dluzsze) == 1 and (kat, next(iter(dluzsze))) in self.analizy | {(kat, x): None for x, _, _ in sesja.wpisy(kat)}:
                    dlugi = next(iter(dluzsze))
                    if (kat, dlugi) in self.analizy or sesja.wez(kat, dlugi):
                        self.aliasy[(kat, k)] = dlugi
                        self.dlugie.add((kat, dlugi))

    def lemat_ign(self, w: str) -> str:
        # Forma z wymianą spółgłoski („Stalmecie”, „Budimpeksu”) nie zaczyna się od formy podstawowej, więc lemat
        # rozpoznaje też reguła odmiany
        kand = [s for s in self.ign if (w.lower().startswith(s.lower()) and w[len(s):].lower() in nazwy.KONCOWKI_IGN)
                or w.lower() in {f.lower() for f in nazwy.formy_ign(s).values()}]
        # Remis długości („Medika” i „Medice”, „Lakma” i „Lakmy”) rozstrzyga forma inna niż samo słowo, potem alfabet.
        # Bez tego wynik zależał od kolejności zbioru, czyli zmieniał się między uruchomieniami procesu.
        return min(kand, key=lambda s: (len(s), s == w, s)) if kand else w

    def analizy_zakresu(self, kat: str, rdzen: str) -> dict | None:
        if (kat, rdzen) not in self._pamiec:
            self._pamiec[(kat, rdzen)] = nazwy.analizuj_nazwe(rdzen, self)
        return self._pamiec[(kat, rdzen)]


def _same_pospolite(fragment: str) -> bool:
    """Prawda, gdy każde słowo fragmentu istnieje w słowniku jako zwykły wyraz (pisane małą literą)."""
    slowa = re.findall(r"\p{L}+", fragment)
    if len(fragment) < 4 or not slowa:
        return False
    dlugie = [w for w in slowa if len(w) > 1]
    for w in slowa:
        # Imię znane słownikowi nigdy nie trafia do oceny: „Martą”, „Michałowi”. Nazwisko albo nazwa geograficzna, która
        # jest też zwykłym wyrazem („Danych”, „Ksiąg”, „Wieczystych”), przechodzi tylko w nazwie z co najmniej trzech słów
        # i nie na początku: w „Portalu … Bazy Danych Ksiąg Wieczystych” to wyrazy pospolite, a „Kowal i Syn”
        # i „Dąbrowski i Partnerzy” zaczynają się nazwiskiem i dalej są podmieniane. Słowo bez znaczenia pospolitego
        # („Wrocław”) odpada niżej, bo małą literą nie ma go w słowniku.
        nazwy_slowa = {n for i in morf.analizuj(w) + morf.analizuj(w.capitalize()) for n in i.nazwy}
        if "imię" in nazwy_slowa:
            return False
        if nazwy_slowa & {"nazwisko", "nazwa_geograficzna"} and (
                w == dlugie[0] or len(dlugie) < 3
                # wyraz pospolity (lemat małą literą) w dopełniaczu, czyli człon łańcucha „Bazy Danych Ksiąg”, a nie
                # nazwisko w mianowniku dopisane do opisu („Hurtownia Kowal Bis”, „Pracownia Ceramiki Wrocław”)
                or not any(i.lemat[:1].islower() and "gen" in i.przypadki for i in morf.analizuj(w.lower()))
                # na końcu nazwy tylko przymiotnik („Wieczystych”); rzeczownik na końcu to typowy dopisek właściciela
                # („Biuro Rachunkowe Nowaka”, „Pracownia Ceramiki Kowala”)
                or (w == dlugie[-1] and not any(i.klasa == "adj" and i.lemat[:1].islower() for i in morf.analizuj(w.lower())))):
            return False
        if not any(i.klasa != "ign" for i in morf.analizuj(w.lower())):
            return False
    return True


def _sygnatura(fragment: str) -> list:
    return [_lematy(w) for w in re.findall(r"[\p{L}\d]+", fragment)]


def _pasuje(a: list, b: list) -> bool:
    """Te same słowa w dowolnych formach gramatycznych."""
    return bool(a) and len(a) == len(b) and all(x & y for x, y in zip(a, b))


# Polityka: co robić z nazwą danej kategorii. Kategorię ustala LLM z kontekstu (detekcja.llm.klasyfikuj),
# a dla nazw złożonych z samych wyrazów pospolitych reguła _nazwa_ogolna (kategoria OGOLNA, bez pytania modelu).
KATEGORIE_ZOSTAW = {"INSTYTUCJA", "AKT_PRAWNY", "DOKUMENT", "POJECIE", "OGOLNA"}   # zostaje; podmieniane są tylko człony własne


def _nazwa_ogolna(z: Zakres, encje: list[Encja]) -> bool:
    """Zakres pisany w całości małymi literami, zaczynający się wyrazem pospolitym: „wielostanowiskowym garażu
    podziemnym numer 4”. Nazwy własne pisze się wielką literą, więc taki zakres jest opisem, nie nazwą, i zostaje bez
    pytania modelu, także gdy wskazał go detektor LLM. Nazw pisanych wielką literą („Specjalna Strefa Ekonomiczna”
    i „Zdrowa Apteka”) słownik nie rozróżnia: o nich decyduje klasyfikacja."""
    if z.typ == "OSOBA" or any(e.typ == "OSOBA" and e.start < z.end and e.end > z.start for e in encje):
        return False
    slowa = re.findall(r"\p{L}+", z.tekst)
    return (bool(slowa) and not re.search(r"\p{Lu}", z.tekst) and morf.rodzaj_slowa(slowa[0]) == "pospolite"
            and not any(osoby._imie_i(w.capitalize()) for w in slowa if len(w) >= 3))


def _same_pospolite_wielka(z: Zakres) -> list[str] | None:
    """Słowa zakresu, gdy jest to co najmniej dwa słowa pisane wielką literą, oddzielone odstępami, każde w słowniku
    wyrazem pospolitym i żadne imieniem. Inaczej None."""
    if z.typ == "OSOBA" or not re.fullmatch(r"\p{Lu}\p{Ll}*(?:\s+\p{Lu}\p{Ll}*)+", z.tekst):
        return None
    slowa = z.tekst.split()
    if any(morf.rodzaj_slowa(w) != "pospolite" or osoby._imie_i(w) for w in slowa):
        return None
    return slowa


def _termin_malymi(z: Zakres, tekst: str) -> bool:
    """Termin umowny (zgłoszenie 2026-11-18): „Lokal Mieszkalny”, gdy ten sam dokument pisze te same wyrazy w dowolnej
    formie małymi literami („lokalu mieszkalnego”). Nazwa własna nie występuje w tekście małymi literami, więc wersja
    wielką literą to wyróżnienie pojęcia, a nie nazwa. Nie dotyczy nazw w cudzysłowie."""
    slowa = _same_pospolite_wielka(z)
    if not slowa or re.search(r"[„”\"]", tekst[max(0, z.start - 1):z.end + 1]):
        return False
    syg = _sygnatura(z.tekst)
    wzor = r"(?<!\p{L})\p{Ll}+" + r"\s+\p{Ll}+" * (len(slowa) - 1) + r"(?!\p{L})"
    return any(_pasuje(syg, _sygnatura(m.group())) for m in re.finditer(wzor, tekst, overlapped=True)
               if _lematy(m.group().split()[0]) & syg[0])


RX_DEFINICJA = re.compile(r"(?:\(\s*dalej|zwan\p{L}*\s+(?:dalej|w\s+dalszej\s+części(?:\s+umowy)?))\s*:?\s*[„\"]?$", re.I)


def _termin_zdefiniowany(z: Zakres, tekst: str, zakresy: list[Zakres]) -> bool:
    """Termin zdefiniowany w dokumencie („zwany dalej Lokalem”, „(dalej: Nieruchomość)”) złożony z wyrazów pospolitych.
    Nie dotyczy skrótu nazwy podmiotu: „PPH „Orzeł” (dalej: „Orzeł”)” ma słowo z nazwy firmy lub osoby stojącej
    tuż przed definicją, więc jest jej aliasem i podlega podmianie."""
    if z.typ == "OSOBA" or not RX_DEFINICJA.search(tekst[max(0, z.start - 40):z.start]):
        return False
    slowa = re.findall(r"\p{L}+", z.tekst)
    if not slowa or any(morf.rodzaj_slowa(w) != "pospolite" or osoby._imie_i(w) for w in slowa):
        return False
    lematy = set().union(*_sygnatura(z.tekst))
    for y in zakresy:
        if y is not z and y.end <= z.start and z.start - y.end <= 200 and y.typ in ("OSOBA", "FIRMA", "NAZWA"):
            if any(_lematy(w) & lematy for w in re.findall(r"\p{L}+", y.tekst)):
                return False
    return True


TYP_KATEGORII = {"OSOBA": "OSOBA", "FIRMA": "FIRMA", "PRODUKT": "NAZWA", "MIEJSCE": "MIEJSCE"}   # podmiana w całości


def _slowa_osobowe(fragment: str) -> list[str]:
    return [w for w in re.findall(r"\p{L}+", fragment) if len(w) > 1]


def _pewna_osoba(fragment: str) -> bool:
    """Każde słowo jest w słowniku imieniem lub nazwiskiem i co najmniej jedno nie ma znaczenia pospolitego."""
    slowa = _slowa_osobowe(fragment)
    return (bool(slowa) and all(osoby._imie_i(w) or osoby._nazw_i(w) for w in slowa)
            and any(morf.rodzaj_slowa(w) == "wlasne" for w in slowa))


def _budowa_opisowa(fragment: str) -> bool:
    """Zaczyna się wyrazem pospolitym i nie ma formy prawnej: „Kancelaria Notarialna we Wrocławiu”, „Zdrowa Apteka”."""
    pierwsze = re.match(r"\P{L}*(\p{L}+)", fragment)
    return (bool(pierwsze) and morf.rodzaj_slowa(pierwsze.group(1)) == "pospolite"
            and not nazwy.RX_FORMA_KONIEC.search(fragment) and not nazwy.RX_FORMA_SRODEK.search(fragment))


def kandydaci_klasyfikacji(tekst: str, zakresy: list[Zakres], encje: list[Encja] | None = None) -> tuple[dict, dict]:
    """(kategorie ustalone bez modelu, nazwy do klasyfikacji z kontekstem). Bez klasyfikacji (zawsze podmiana) zostają:
    osoby pewne słownikowo, nazwiska występujące w dokumencie obok imienia oraz firmy z formą prawną."""
    llm_syg = [_sygnatura(e.tekst) for e in (encje or []) if e.zrodlo == "llm"]
    z_gory: dict[str, str] = {}
    kandydaci: dict[str, str] = {}
    # Termin umowny rozpoznany przy którymkolwiek wystąpieniu: pierwsze bywa w cudzysłowie definicji („Lokal Mieszkalny”),
    # a kolejne wystąpienia tego samego tekstu nie są już oceniane osobno
    terminy = {z.tekst for z in zakresy if z.typ in ("FIRMA", "NAZWA", "MIEJSCE")
               and (_termin_malymi(z, tekst) or _termin_zdefiniowany(z, tekst, zakresy))}
    for z in zakresy:
        if z.tekst in terminy and z.tekst not in z_gory and not (nazwy.RX_FORMA_KONIEC.search(z.tekst) or nazwy.RX_FORMA_SRODEK.search(z.tekst)):
            z_gory[z.tekst] = "OGOLNA"
        if z.typ not in ("OSOBA", "FIRMA", "NAZWA", "MIEJSCE") or z.tekst in kandydaci or z.tekst in z_gory:
            continue
        if nazwy.RX_FORMA_KONIEC.search(z.tekst) or nazwy.RX_FORMA_SRODEK.search(z.tekst):
            continue
        if _nazwa_ogolna(z, encje or []):
            z_gory[z.tekst] = "OGOLNA"
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
    return z_gory, kandydaci


def kategorie_zakresow(tekst: str, zakresy: list[Zakres], pamiec: dict | None = None, model: str | None = None,
                       encje: list[Encja] | None = None, zapisz_pamiec=None, czasy: dict | None = None) -> dict[str, str]:
    """Kategoria każdej wykrytej nazwy (kandydaci_klasyfikacji, potem głosowanie wariantów pytania).

    Klucz pamięci zaczyna się od odcisku promptu, wariantu i modelu, więc zmiana któregokolwiek nie używa starych ocen.
    zapisz_pamiec(pamiec) jest wołane po każdej paczce zapytań. czasy dostają czas i liczbę zapytanych nazw na wariant."""
    z_gory, kandydaci = kandydaci_klasyfikacji(tekst, zakresy, encje)
    pamiec = pamiec if pamiec is not None else {}
    glosy: dict[str, list[str]] = {f: [] for f in kandydaci}
    warianty = list(detekcja.llm.WARIANTY_KLASYFIKACJI)
    for nr, wariant in enumerate(warianty):
        odcisk = detekcja.llm.odcisk_klasyfikacji(wariant, model)
        pytane = kandydaci
        if nr == 2:
            # Głosowanie etapowe: trzeci, najdroższy wariant tylko gdy dwa pierwsze nie są zgodne (inna kategoria, także
            # osoba wobec firmy, bo od niej zależy rodzaj surogatu) albo brak oceny. Zabezpieczenie: nazwa o budowie
            # opisowej dostaje trzeci głos zawsze, bo przy zgodnej podmianie tylko on może dać podział głosów, przy
            # którym zmienia się sam człon własny.
            pytane = {f: k for f, k in kandydaci.items() if len(glosy[f]) < 2 or len(set(glosy[f])) > 1 or _budowa_opisowa(f)}
        nowe = [(f, k) for f, k in pytane.items() if f"{odcisk}|{f}|{k}" not in pamiec]
        t0 = time.time()
        if nowe:
            def po_paczce(paczka, oceny, odcisk=odcisk):
                # Brak oceny też jest zapamiętany (None), żeby wznowienie nie pytało drugi raz
                pamiec.update({f"{odcisk}|{f}|{k}": oceny.get(f) for f, k in paczka})
                if zapisz_pamiec:
                    zapisz_pamiec(pamiec)
            detekcja.llm.klasyfikuj(nowe, model, wariant, po_paczce=po_paczce)
        if czasy is not None:
            czasy[f"klasyfikacja_{wariant}"] = {"s": round(time.time() - t0, 1), "zapytane": len(nowe), "z_pamieci": len(pytane) - len(nowe),
                                                "pominiete": len(kandydaci) - len(pytane)}
        for f, k in pytane.items():
            if pamiec.get(f"{odcisk}|{f}|{k}"):
                glosy[f].append(pamiec[f"{odcisk}|{f}|{k}"])
    wynik = dict(z_gory)
    for f, g in glosy.items():
        zostaw = [x for x in g if x in KATEGORIE_ZOSTAW]
        podmien = [x for x in g if x not in KATEGORIE_ZOSTAW]
        # Nazwa zostaje tylko przy co najmniej dwóch głosach „zostaw”. Remis i brak ocen oznaczają podmianę.
        strona = zostaw if len(zostaw) >= 2 else podmien
        if strona:
            # Remis kategorii rozstrzyga wcześniejszy wariant (lista, potem uzasadnienie). max po zbiorze zależał od
            # kolejności haszy, czyli zmieniał wynik między uruchomieniami procesu.
            wynik[f] = max(strona, key=lambda x: (strona.count(x), -strona.index(x)))
        if zostaw and len(zostaw) < 2:
            wynik[f] = "SPORNE:" + wynik.get(f, "FIRMA")   # głosy podzielone, większość za podmianą
    return wynik


# Przyimek „w”/„we” albo „z”/„ze” stojący bezpośrednio przed nazwą
RX_PRZYIMEK = re.compile(r"(?<![\p{L}\d.])([wWzZ])([eE]?)([ \t\u00a0]+)$")


def przyimek(przed: str, nowe: str) -> tuple[int, str] | None:
    """Jeśli tekst przed nazwą kończy się przyimkiem w/we albo z/ze, którego forma nie pasuje do nagłosu nowej nazwy,
    zwraca (długość przyimka z odstępem, poprawiony przyimek z odstępem). Reguła fonetyczna (nazwy.klasa_naglosu):
    „we” przed w/f i spółgłoską, „ze” przed s/z/ś/ź/ż i spółgłoską: „ze Stanisławem” -> „z Bronisławem”,
    „z Mirtasem” -> „ze Stalmetem”. Inne przyimki i formy zostają."""
    m = RX_PRZYIMEK.search(przed)
    if not m:
        return None
    litera, e, odstep = m.groups()
    klasa = nazwy.klasa_naglosu(nowe)
    potrzebne = (litera.lower() == "w" and klasa == "we") or (litera.lower() == "z" and klasa == "ze")
    if potrzebne == bool(e):
        return None
    # „We Wrocławiu” na początku zdania: wielka zostaje tylko pierwsza litera
    return len(m.group(0)), litera + ("e" if potrzebne else "") + odstep


def _dodaj(tekst: str, out: list, podmiany: list, pos: int, z, typ: str, nowe: str) -> int:
    """Dopisuje podmianę zakresu z. Przyimek przed nim dopasowuje się do nagłosu surogatu i wtedy wchodzi do zakresu
    podmiany, żeby zmiana trafiła także do pliku (model pośredni zmienia tylko zakresy podmian)."""
    start = z.start
    p = przyimek(tekst[pos:z.start], nowe)
    if p:
        dl, nowy = p
        start, nowe = z.start - dl, nowy + nowe
    out += [tekst[pos:start], nowe]
    podmiany.append({"start": start, "end": z.end, "typ": typ, "oryginal": tekst[start:z.end], "surogat": nowe})
    return z.end


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
            if _budowa_opisowa(z.tekst):
                nowe = nazwy.podmien_wlasne(sesja, z.tekst, tekst, z.start, ctx)
                if nowe and nowe != z.tekst:
                    pos = _dodaj(tekst, out, podmiany, pos, z, "OPISOWA", nowe)
                    continue
                if ((nowe is None or nowe == z.tekst) and _same_pospolite(z.tekst)
                        and not re.search(r"[„”\"]", tekst[max(0, z.start - 1):z.end + 1])):
                    # Głosy podzielone, a każde słowo nazwy jest w słowniku wyłącznie wyrazem pospolitym, bez znaczenia
                    # imienia, nazwiska ani nazwy geograficznej, i nie stoi w cudzysłowie: „Specjalna Strefa Ekonomiczna”.
                    # Podmiana w całości dawałaby szum zamiast ochrony. „Dąbrowski i Partnerzy”, „Zabór” tu nie wchodzą.
                    pominiete.append({**z.jako_dict(), "powod": "głosy podzielone, bez członu własnego"})
                    continue
        if kategoria in KATEGORIE_ZOSTAW:
            # „Kodeks cywilny”, „Umowa Przedwstępna”, „Specjalna Strefa Ekonomiczna” zostają; w „Sąd Rejonowy w Gliwicach”
            # i „Rada Miejska Wrocławia” podmieniana jest tylko miejscowość
            nowe = nazwy.podmien_wlasne(sesja, z.tekst, tekst, z.start, ctx)
            if nowe is None or nowe == z.tekst:
                pominiete.append({**z.jako_dict(), "powod": f"kategoria {kategoria}"})
                continue
            pos = _dodaj(tekst, out, podmiany, pos, z, kategoria, nowe)
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
        pos = _dodaj(tekst, out, podmiany, pos, z, z.typ, nowe)
    out.append(tekst[pos:])
    czasy["podmiana"] = round(time.time() - t_podmiana, 1)
    wyjscie = "".join(out)
    t0 = time.time()
    kontrola = kontrola_wycieku(sesja, wyjscie)
    czasy["kontrola"] = round(time.time() - t0, 1)
    return {"tekst": wyjscie, "kontrola": kontrola, "podmiany": podmiany, "pominiete": pominiete, "kategorie": kategorie,
            "zostawione": {f: k for f, k in sorted(kategorie.items()) if k in KATEGORIE_ZOSTAW},
            "sporne": sorted(f for f, k in kategorie.items() if k.startswith("SPORNE:"))}


KAT_ORYGINALOW = ("IMIE", "NAZWISKO", "MIEJSCE", "ULICA", "FIRMA", "NAZWA")


TYPY_Z_SUMA = {"PESEL", "NIP", "REGON", "IBAN", "DOWOD"}


def kontrola_wycieku(sesja: Sesja, wyjscie: str) -> dict:
    """Bezpiecznik po podmianie, bez modelu. (1) Każdy oryginał z mapy sesji (klucze i formy zaobserwowane we wszystkich
    dokumentach sesji) szukany dosłownie w tekście wynikowym. (2) Ponowna detekcja numerów regexami: numer, który nie
    jest surogatem ani odwołaniem chronionym (artykuł, publikator, numer aktu), nie został podmieniony.
    Trafienie oznacza status „do_przegladu”: błąd propagacji albo detekcji, niezależnie od tego, który detektor zawiódł."""
    from ..detekcja import regexy
    from ..detekcja.scal import RX_CHRONIONE, numery_aktow

    oryginaly: dict[str, str] = {}
    for (kat, klucz), _ in sesja.mapa.items():
        if kat in KAT_ORYGINALOW:
            oryginaly.setdefault(klucz, kat)
    for (kat, _, _), forma in sesja.formy.items():
        if kat in KAT_ORYGINALOW:
            oryginaly.setdefault(forma, kat)
        elif kat in ("ODWR", "ODWR_N"):
            oryginaly.setdefault(forma, "NUMER")
    warianty = {}
    for o, kat in oryginaly.items():
        if len(re.sub(r"\W", "", o)) < 3:
            continue
        warianty.setdefault(o, kat)
        if len(o) >= 4 and o.upper() != o:
            warianty.setdefault(o.upper(), kat)   # nazwisko pisane wersalikami: „KOWALSKI”
    trafienia = []
    if warianty:
        rx = re.compile(r"(?<![\p{L}\d])(?:" + "|".join(re.escape(o) for o in sorted(warianty, key=len, reverse=True)) + r")(?![\p{L}\d])")
        for m in rx.finditer(wyjscie):
            trafienia.append({"start": m.start(), "end": m.end(), "tekst": m.group(), "rodzaj": "oryginał z mapy sesji",
                              "kat": warianty[m.group()], "pewny": True})

    chronione = [(m.start(), m.end()) for m in RX_CHRONIONE.finditer(wyjscie)] + numery_aktow(wyjscie)
    surogaty = ({s for (kat, _), (s, _) in sesja.mapa.items() if kat in ("NUMER", "NRDOM")}
                | {k for (kat, k, _) in sesja.formy if kat in ("ODWR", "ODWR_N")})
    for e in regexy.wykryj(wyjscie):
        if e.typ == "ADRES" or any(e.start < b and e.end > a for a, b in chronione):
            continue   # adres sprawdza wyszukiwanie ulic i miejscowości z mapy
        if e.tekst in surogaty or numery._klucz(e.typ, e.tekst) in surogaty:
            continue
        if any(t["start"] < e.end and t["end"] > e.start for t in trafienia):
            continue
        # Pewny wyciek: numer z poprawną sumą kontrolną. Pozostałe (telefon, sygnatura, numer z błędną sumą, adres e-mail
        # przekłamany przez OCR) bywają fałszywym alarmem i użytkownik może je zatwierdzić po przejrzeniu raportu.
        trafienia.append({"start": e.start, "end": e.end, "tekst": e.tekst, "rodzaj": "numer bez podmiany", "kat": e.typ,
                          "pewny": bool(e.pewna and e.typ in TYPY_Z_SUMA)})
    trafienia.sort(key=lambda t: t["start"])
    return {"status": "do_przegladu" if trafienia else "ok", "trafienia": trafienia}


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
        przed = tekst[pos:a]
        p = przyimek(przed, nowe)
        if p:
            # Przyimek przed oryginałem według jego nagłosu: „z Mirtasem” -> „ze Stalmetem”
            przed = przed[:len(przed) - p[0]] + p[1]
        out.append(przed)
        out.append(nowe)
        if niepewna:
            niepewne.append({"surogat": tekst[a:b], "oryginal": nowe, "kontekst": tekst[max(0, a - 40):b + 30].replace("\n", " ")})
        pos = b
    out.append(tekst[pos:])
    return {"tekst": "".join(out), "niepewne": niepewne}

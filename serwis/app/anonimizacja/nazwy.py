"""Miejscowości, firmy, instytucje i nazwy własne (produkty, projekty).

Firma: podmieniany jest rdzeń nazwy, forma prawna zostaje. Instytucja: część ogólna zostaje, podmieniana
jest miejscowość. Surogat firmy ma odmianę regularną i rodzaj zgodny z oryginałem."""
import regex as re

from .. import morf
from ..detekcja.scal import FORMA_PRAWNA
from . import gram, osoby, pule
from .sesja import Sesja

RX_W = re.compile(r"[\p{L}\d]+(?:[-'’][\p{L}\d]+)*")
RX_FORMA_KONIEC = re.compile(r"\s+" + FORMA_PRAWNA + r"\s*$")
RX_FORMA_SRODEK = re.compile(r"\s+" + FORMA_PRAWNA + r"(?=[\s,;])")
ODMIENNE = ("subst", "adj", "ppas", "pact", "ger")
PRZYM = ("adj", "ppas", "pact")

def podmien_wlasne(sesja: Sesja, rdzen: str, tekst: str, start: int, ctx) -> str | None:
    """Dla nazw, które jako całość mają zostać (instytucja publiczna, akt prawny, dokument, pojęcie): zwykłe słowa
    zostają, a podmieniane są tylko człony identyfikujące, czyli imiona i nazwiska, miejscowości oraz słowa spoza
    słownika. „Sąd Rejonowy w Gliwicach” -> „Sąd Rejonowy w Radomiu”, „Kodeks cywilny” bez zmian.
    Dzięki temu błędna ocena kategorii nie może ujawnić nazwy własnej: zostawić da się tylko wyrazy pospolite."""
    slowa = list(RX_W.finditer(rdzen))
    if not slowa:
        return None
    # Grupa otwierająca: pierwsze słowo i zgodne z nim przymiotniki („Rada Miejska”, „Kancelarii Notarialnej”)
    tro = set().union(*(x.trojki() for x in _an(slowa[0].group())[1] if x.klasa in ODMIENNE))
    glowa = 1 if morf.rodzaj_slowa(slowa[0].group()) == "pospolite" else 0   # grupa otwierająca tylko ze zwykłych słów
    while 0 < glowa < len(slowa) and rdzen[slowa[glowa - 1].end():slowa[glowa].start()] == " ":
        wsp = tro & set().union(*(x.trojki() for x in _an(slowa[glowa].group())[1] if x.klasa in ("adj", "ppas", "pact")), set())
        if not wsp:
            break
        tro, glowa = wsp, glowa + 1

    def rodzaj(k: int) -> str | None:
        w = slowa[k].group()
        if k < glowa or not w[:1].isupper() or len(w) < 3:
            return None
        if osoby._imie_i(w):
            return "osoba"
        if osoby._nazw_i(w) and k > 0 and rodzaj(k - 1) == "osoba" and rdzen[slowa[k - 1].end():slowa[k].start()] in (" ", "-"):
            return "osoba"
        klasa = morf.rodzaj_slowa(w)
        geo_lematy = {x.lemat for cz in re.split(r"[-–]", w) for x in morf.analizuj_ocr(cz) if "nazwa_geograficzna" in x.nazwy}
        geo = bool(geo_lematy)
        po_przyimku = bool(re.search(r"(?:^|\s)(?:w|we|dla|przy|z|ze)\s+$", rdzen[:slowa[k].start()]))
        ciag_dalszy = k > 0 and rdzen[slowa[k - 1].end():slowa[k].start()] in (" ", "-") and rodzaj(k - 1) == "miejsce"
        # Miejscowość podmieniona już w sesji jest podmieniana wszędzie, także bez przyimka i gdy jest też zwykłym
        # słowem: „Sąd Rejonowy Poznań – Nowe Miasto” po „w Poznaniu”
        znana = any(sesja.wez("MIEJSCE", l) for l in geo_lematy)
        if geo and (klasa == "wlasne" or po_przyimku or ciag_dalszy or znana):
            return "miejsce"
        return "obce" if klasa == "ign" else None

    out, pos, i = [], 0, 0
    while i < len(slowa):
        r = rodzaj(i)
        if r is None:
            i += 1
            continue
        j = i
        while j + 1 < len(slowa) and rodzaj(j + 1) == r and re.fullmatch(r"[ -]", rdzen[slowa[j].end():slowa[j + 1].start()]):
            j += 1
        a, b = slowa[i].start(), slowa[j].end()
        frag = rdzen[a:b]
        if r == "miejsce":
            nowe = miejsce(sesja, frag, tekst, start + a, ctx)
        elif r == "osoba":
            nowe = osoby.podmien(sesja, frag, tekst, start + a, ctx)
        else:
            nowe = nazwa(sesja, frag, tekst, start + a, ctx, "FIRMA")
        if nowe and nowe != frag:
            out += [rdzen[pos:a], nowe]
            pos = b
        i = j + 1
    out.append(rdzen[pos:])
    return "".join(out) if pos else None


KONCOWKI_IGN = {"": {"nom", "acc"}, "u": {"gen", "loc"}, "a": {"gen"}, "owi": {"dat"}, "em": {"inst"}, "iem": {"inst"},
                "ie": {"loc"}, "y": {"gen"}, "i": {"gen"}, "ę": {"acc"}, "ą": {"inst"}}

# Wymiany spółgłosek przed końcówką -e miejscownika (rodzaj męski) i celownika/miejscownika (żeński): reguła
# fonologiczna polszczyzny, nie lista nazw. Najdłuższe zakończenie tematu wygrywa.
WYMIANY_E = [("st", "ście"), ("zd", "ździe"), ("sł", "śle"), ("zł", "źle"), ("sn", "śnie"), ("zn", "źnie"),
             ("t", "cie"), ("d", "dzie"), ("r", "rze"), ("ł", "le")]
TYLNE = ("k", "g", "ch")
MIEKKIE = ("c", "cz", "sz", "rz", "ż", "dz", "dż", "j", "l", "ś", "ź", "ć", "ń")


def _temat_e(temat: str) -> str:
    """Temat z końcówką -e po wymianie: „Stalmet” -> „Stalmecie”, „Ekoplast” -> „Ekoplaście”, „Elwod” -> „Elwodzie”."""
    for kon, zam in WYMIANY_E:
        if temat.endswith(kon):
            return temat[:-len(kon)] + zam
    return temat + "ie"


def formy_ign(lemat: str) -> dict[str, str]:
    """Odmiana nazwy spoza słownika według reguł wzorca regularnego. Rodzaj żeński dla zakończonych na -a, męski
    nieżywotny dla zakończonych spółgłoską; zakończone inną samogłoską są nieodmienne. Końcowe -x przechodzi w -ks
    („Budimpex”, „Budimpeksu”)."""
    if lemat.endswith("a"):
        t = lemat[:-1]
        if t.endswith(TYLNE):
            gen, dat = t + "i", {"k": t[:-1] + "ce", "g": t[:-1] + "dze"}.get(t[-1], t[:-2] + "sze")
        elif t.endswith(MIEKKIE):
            gen = t + ("i" if t.endswith(("l", "j", "ś", "ź", "ć", "ń")) else "y")
            dat = gen
        else:
            gen, dat = t + "y", _temat_e(t)
        return {"nom": lemat, "gen": gen, "dat": dat, "acc": t + "ę", "inst": t + "ą", "loc": dat, "voc": t + "o"}
    if not lemat or lemat[-1].lower() in "aąeęioóuy":
        return {p: lemat for p in ("nom", "gen", "dat", "acc", "inst", "loc", "voc")}
    t = lemat[:-1] + "ks" if lemat.endswith("x") else lemat
    if t.endswith(TYLNE):
        loc, inst = t + "u", t + "iem"
    elif t.endswith(MIEKKIE):
        loc, inst = t + "u", t + "em"
    else:
        loc, inst = _temat_e(t), t + "em"
    return {"nom": lemat, "gen": t + "u", "dat": t + "owi", "acc": lemat, "inst": inst, "loc": loc, "voc": loc}


def _an(w: str):
    """Analiza słowa; dla złożeń z łącznikiem analizowany jest ostatni człon. Zwraca (przedrostek, interpretacje)."""
    czlon = re.split(r"[-'’]", w)[-1]
    pre = w[:len(w) - len(czlon)]
    return pre, morf.analizuj_ocr(czlon.capitalize() if len(czlon) > 1 and czlon.isupper() else czlon)


def _wielkosc(wzor: str, forma: str) -> str:
    if len(wzor) > 1 and wzor.isupper():
        return forma.upper()
    return forma[0].upper() + forma[1:] if wzor[:1].isupper() else forma


# ---------- miejscowości ----------

def _geo(w: str):
    return [i for i in _an(w)[1] if (i.klasa == "subst" and "nazwa_geograficzna" in i.nazwy) or i.klasa == "adj"]


def klasa_naglosu(nazwa: str) -> str:
    """Przyimek wymagany przez początek nazwy: „we Wrocławiu”, „ze Słupska”, zwykle „w”/„z”. Reguła fonetyczna:
    w/f przed spółgłoską wymaga „we”, s/z/ś/ź/ż przed spółgłoską oraz „mn” wymagają „ze”."""
    if re.match(r"(?i)[wf](?![aąeęioóuyj])", nazwa):
        return "we"
    if re.match(r"(?i)(?:[szśźż](?![aąeęioóuyj])|mn)", nazwa):
        return "ze"
    return ""


def miejsce(sesja: Sesja, pow: str, tekst: str, start: int, ctx, wymuszony: str | None = None) -> str | None:
    slowa = RX_W.findall(pow)
    if not slowa:
        return None
    geo = [_geo(w) for w in slowa]
    znane = len(slowa) <= 2 and all(geo) and any("nazwa_geograficzna" in i.nazwy for g in geo for i in g)
    lematy = []
    if znane:
        zb = [set().union(*(i.trojki() for i in g)) for g in geo]
        tro = set.intersection(*zb) or zb[-1]
        kand = {p for _, p, _ in tro}
        przyp = wymuszony if wymuszony in kand else gram.rozstrzygnij(kand, tekst, start)
        for g in geo:
            traf = [i for i in g if przyp in i.przypadki and i.trojki() & tro] or g
            lematy.append((sorted(traf, key=lambda i: "nazwa_geograficzna" not in i.nazwy)[0]).lemat)
        klucz = " ".join(l[0].upper() + l[1:] for l in lematy)
    else:
        klucz = pow
        przyp = wymuszony or gram.rozstrzygnij(set(), tekst, start)
    wpis = sesja.wez("MIEJSCE", klucz)
    if wpis:
        sur = wpis[0]
    else:
        oryginaly = {k for k, _, _ in sesja.wpisy("MIEJSCE")}
        uzyte = sesja.uzyte("MIEJSCE")

        def zakazane(m) -> bool:
            return m in oryginaly or any(f.lower() in ctx.slowa for f in pule.formy_miasta(m).values())

        # Surogat z tej samej klasy nagłosu co oryginał, żeby przyimek przed nim („we”, „ze”) pozostał poprawny
        klasa = klasa_naglosu(klucz)
        pula = [m for m in pule.MIASTA if klasa_naglosu(m) == klasa and m not in uzyte and not zakazane(m)] or pule.MIASTA
        sur = sesja.z_puli(pula, uzyte, zakazane, pule.zapas_nazwy)
        sesja.ustaw("MIEJSCE", klucz, sur, {"znane": znane, "lematy": lematy})
    sesja.zapamietaj_forme("MIEJSCE", klucz, przyp, pow)
    return gram.jak_wzor(pow, pule.formy_miejsca(sur)[przyp])


def forma_miejsca(sesja: Sesja, klucz: str, dane: dict, przyp: str) -> tuple[str, bool]:
    widziana = sesja.forma("MIEJSCE", klucz, przyp)
    if widziana:
        return widziana, True
    if not dane.get("znane"):
        dowolna = next((f for (kat, k, _), f in sesja.formy.items() if kat == "MIEJSCE" and k == klucz), klucz)
        return dowolna, False
    out = []
    for lemat, slowo in zip(dane["lematy"], klucz.split(" ")):
        kand = [i for i in morf.generuj(lemat) if przyp in i.przypadki and (
            (i.klasa == "subst" and "nazwa_geograficzna" in i.nazwy) or (i.klasa == "adj" and "f" in i.rodzaje and i.liczba == "sg"))]
        if not kand:
            return klucz, przyp == "nom"
        out.append(_wielkosc(slowo, sorted(kand, key=lambda i: (i.klasa != "subst", i.liczba != "sg"))[0].forma))
    return " ".join(out), True


# ---------- firmy i nazwy ----------

def analizuj_nazwe(rdzen: str, ctx) -> dict | None:
    """Rozkłada rdzeń nazwy na grupę odmienną (rzeczownik z przymiotnikami na początku) i nieodmienną resztę."""
    slowa = list(RX_W.finditer(rdzen))
    if not slowa:
        return None
    pierwsze = slowa[0].group()
    inter = [i for i in _an(pierwsze)[1] if i.klasa in ODMIENNE]
    if not inter:
        if pierwsze.isupper() and len(pierwsze) <= 5:
            lemat, klasa, kand = pierwsze, "nieodm", set()
        else:
            lemat = ctx.lemat_ign(pierwsze)
            # Końcówka mówi coś o przypadku tylko wtedy, gdy znamy formę podstawową z dokumentu
            pewny_lemat = lemat != pierwsze or any(s != pierwsze and s.lower().startswith(pierwsze.lower()) for s in ctx.ign)
            kand = set()
            if pewny_lemat:
                kand = set(KONCOWKI_IGN.get(pierwsze[len(lemat):].lower(), set())) if pierwsze.lower().startswith(lemat.lower()) else set()
                kand |= {p for p, f in formy_ign(lemat).items() if p != "voc" and f.lower() == pierwsze.lower()}
            else:
                lemat, kand = lemat_z_koncowki(pierwsze)
            klasa = "ign"
        grupa = [{"lemat": lemat, "klasa": klasa, "wzor": pierwsze, "pre": ""}]
        tro = {("sg", p, "f" if lemat.endswith("a") and klasa == "ign" else "m3") for p in (kand or gram.KOLEJNOSC[:6])}
        koniec = slowa[0].end()
    else:
        tro = set().union(*(i.trojki() for i in inter))
        czlony = [(slowa[0], inter)]
        # Grupa to przymiotniki wokół co najwyżej jednego rzeczownika. Drugi rzeczownik nie wchodzi, nawet gdy jego forma
        # przypadkiem się zgadza: w „Lubuskiego Funduszu Rozwoju” dopełniacz „Rozwoju” to przydawka, nie część grupy,
        # inaczej klucz nazwy w dopełniaczu różniłby się od klucza w mianowniku i ta sama firma dostałaby dwa surogaty.
        rzecz = not any(i.klasa in PRZYM for i in inter)
        for nast in slowa[1:3]:
            if rdzen[czlony[-1][0].end():nast.start()] != " ":
                break
            it = [i for i in _an(nast.group())[1] if i.klasa in ODMIENNE and i.trojki() & tro]
            if rzecz:
                it = [i for i in it if i.klasa in PRZYM]
            if not it:
                break
            tro = tro & set().union(*(i.trojki() for i in it))
            rzecz = rzecz or not any(i.klasa in PRZYM for i in it)
            czlony.append((nast, it))
        grupa = []
        for m, it in czlony:
            traf = [i for i in it if i.trojki() & tro]
            if rzecz and len(czlony) > 1 and any(i.klasa in PRZYM for i in traf) and any(
                    not any(j.klasa in PRZYM for j in it2) for _, it2 in czlony):
                traf = [i for i in traf if i.klasa in PRZYM]   # jest rzeczownik jednoznaczny: pozostałe człony to przymiotniki
            wyb = sorted(traf, key=lambda i: (i.klasa != "subst", "nazwa_pospolita" not in i.nazwy, i.lemat))[0]
            grupa.append({"lemat": wyb.lemat, "klasa": "subst" if wyb.klasa in ("subst", "ger") else "adj",
                          "wzor": m.group(), "pre": _an(m.group())[0]})
        kand = {p for _, p, _ in tro}
        koniec = czlony[-1][0].end()
    reszta = rdzen[koniec:]
    klucz = " ".join([(g["pre"] + g["lemat"]).lower() for g in grupa] + [x.lower() for x in RX_W.findall(reszta)])
    return {"klucz": klucz, "grupa": grupa, "tro": tro, "kand": kand, "reszta": reszta, "przed": rdzen[:slowa[0].start()]}


# Końcówki, które w odmianie regularnej występują tylko w przypadkach zależnych: (końcówka, temat -> lemat)
KONCOWKI_ZALEZNE = [("iem", lambda t: t), ("em", lambda t: t), ("owi", lambda t: t),
                    ("ą", lambda t: t + "a"), ("ę", lambda t: t + "a")]


def lemat_z_koncowki(w: str) -> tuple[str, set]:
    """Nazwa spoza słownika, której forma podstawowa nie występuje w dokumencie: „ze Skalbudem”. Jeśli słowo kończy się
    końcówką typową tylko dla przypadka zależnego, a reguła odmiany (formy_ign) z odciętego tematu daje dokładnie to
    słowo, lemat i przypadek wynikają z odwrócenia reguły. Inaczej słowo jest swoim lematem, a przypadek rozstrzyga
    kontekst."""
    for kon, lem in KONCOWKI_ZALEZNE:
        if w.lower().endswith(kon) and len(w) - len(kon) >= 3:
            lemat = lem(w[:-len(kon)])
            kand = {p for p, f in formy_ign(lemat).items() if p != "voc" and f == w}
            if kand:
                return lemat, kand
    return w, set()


def skrotowiec(w: str) -> bool:
    """Słowo zapisane jak skrótowiec: co najmniej dwie wielkie litery, do sześciu liter, np. „PPH”, „TFI”, „TUiR”."""
    return bool(re.fullmatch(r"\p{L}{2,6}", w)) and sum(c.isupper() for c in w) >= 2


def poczatek_nazwy(krotka: list[str], dluga: list[str], skroty: set[str]) -> bool:
    """Słowa krótkiej nazwy (klucz) odpowiadają początkowi długiej: to samo słowo albo skrótowiec, którego litery są
    inicjałami kolejnych słów długiej nazwy (człony z łącznikiem liczą się osobno: „produkcyjno-handlowy” daje „ph”)."""
    if not krotka:
        return True
    if not dluga:
        return False
    w = krotka[0]
    if w == dluga[0] and poczatek_nazwy(krotka[1:], dluga[1:], skroty):
        return True
    if w in skroty:
        litery, i = w, 0
        for n, d in enumerate(dluga):
            ini = "".join(c[:1] for c in d.split("-"))
            if litery[i:i + len(ini)] == ini:
                i += len(ini)
            elif litery[i:i + 1] == ini[:1]:
                i += 1
            else:
                return False
            if i == len(litery):
                return n >= 1 and poczatek_nazwy(krotka[1:], dluga[n + 1:], skroty)
    return False


def _liczba_rodzaj(tro: set, przyp: str) -> tuple[str, str]:
    kand = sorted((l, r) for l, p, r in tro if p == przyp) or sorted((l, r) for l, _, r in tro)
    return sorted(kand, key=lambda x: x[0] != "sg")[0]


def _surogat(sesja: Sesja, kat: str, an: dict, przyp: str, ctx) -> tuple[str, dict]:
    wpis = sesja.wez(kat, an["klucz"])
    if wpis:
        return wpis
    liczba, rodzaj = _liczba_rodzaj(an["tro"], przyp)
    dane = {"grupa": an["grupa"], "liczba": liczba, "rodzaj": rodzaj, "reszta": an["reszta"], "przed": an["przed"], "sufiks": None, "alias": None}
    dluzszy = ctx.aliasy.get((kat, an["klucz"]))
    if dluzszy:
        # Pełna nazwa bywa znana tylko z wcześniejszego dokumentu sesji (skrót „TFI Sokół” w załączniku, pełna nazwa
        # w kopercie XML): wtedy jej surogat jest już w mapie sesji, a analizy w kontekście tego dokumentu nie ma
        wpis_dl = sesja.wez(kat, dluzszy)
        if wpis_dl:
            baza = wpis_dl[0]
        else:
            an2, przyp2 = ctx.analizy[(kat, dluzszy)]
            baza, _ = _surogat(sesja, kat, an2, przyp2, ctx)
        dane["alias"] = dluzszy
    else:
        # Surogat zgodny z liczbą i rodzajem oryginału, żeby orzeczenie i przydawki w zdaniu dalej się z nim zgadzały:
        # „Naleśniki … oświadczają” -> „Tarvony … oświadczają”, „Przedsiębiorstwem” -> „Tarvonem” (nijaki „Tarvono”)
        meskie = pule.NAZWY if kat == "NAZWA" else pule.FIRMY_M
        if liczba == "pl":
            pula, zapas = [pule.nazwa_mnoga(m) for m in meskie], lambda rng: pule.nazwa_mnoga(pule.zapas_nazwy(rng))
        elif rodzaj == "n":
            pula = [pule.nazwa_nijaka(m) for m in meskie if m.endswith("n")]
            zapas = lambda rng: pule.nazwa_nijaka(pule.zapas_nazwy(rng))
        else:
            pula, zapas = (pule.FIRMY_F if rodzaj == "f" and kat == "FIRMA" else meskie), pule.zapas_nazwy
        uzyte = sesja.uzyte("FIRMA", "NAZWA")
        # Jedna nazwa bazowa nie może dać dwóch surogatów („Tarvon” i „Tarvony”), bo odtwarzanie myliłoby formy
        rdzenie_uzyte = {u.rstrip("yo") for u in uzyte}
        baza = sesja.z_puli(pula, uzyte, lambda s: s.lower()[:-1] in ctx.tekst_l or s.rstrip("yo") in rdzenie_uzyte, zapas)
        if (kat, an["klucz"]) in ctx.dlugie:
            dane["sufiks"] = pule.SUFIKSY_FIRM[sesja.losowe("SUFIKS", an["klucz"]).randrange(len(pule.SUFIKSY_FIRM))]
    sesja.ustaw(kat, an["klucz"], baza, dane)
    return baza, dane


def nazwa(sesja: Sesja, pow: str, tekst: str, start: int, ctx, kat: str = "FIRMA") -> str | None:
    rdzen, forma_prawna = pow, ""
    if kat == "FIRMA":
        m = RX_FORMA_KONIEC.search(pow)
        if m:
            rdzen, forma_prawna = pow[:m.start()], pow[m.start():]
        else:
            # Forma prawna w środku zakresu: „Zakłady X S.A. w Puławach”. Ogon zostaje, a miejscowość idzie własną ścieżką.
            m = RX_FORMA_SRODEK.search(pow)
            if m:
                rdzen, forma_prawna, ogon = pow[:m.start()], m.group(), pow[m.end():]
                mm = re.match(r"(\s+we?\s+)(.+)$", ogon, re.S)
                if mm:
                    msc = miejsce(sesja, mm.group(2), tekst, start + m.end() + mm.start(2), ctx, "loc")
                    ogon = mm.group(1) + (msc or mm.group(2))
                forma_prawna += ogon
        slowa = RX_W.findall(rdzen)
        if not forma_prawna and slowa and all(osoby._imie_i(w) or osoby._nazw_i(w) for w in slowa) and any(osoby._imie_i(w) for w in slowa):
            return osoby.podmien(sesja, pow, tekst, start, ctx)  # model oznaczył osobę jako firmę
    an = ctx.analizy_zakresu(kat, rdzen)
    if an is None:
        return None
    # Ta sama nazwa raz oceniona jako firma, raz jako produkt („Aptekarz” obok „Aptekarz Polski S.A.”) to jeden byt:
    # dostaje kategorię, pod którą jest już znana w sesji albo w dokumencie, i ten sam surogat.
    inny = {"FIRMA": "NAZWA", "NAZWA": "FIRMA"}[kat]
    k = an["klucz"]
    if not (sesja.wez(kat, k) or (kat, k) in ctx.aliasy) and (sesja.wez(inny, k) or (inny, k) in ctx.aliasy):
        kat = inny
    przyp = gram.rozstrzygnij(an["kand"], tekst, start)
    baza, dane = _surogat(sesja, kat, an, przyp, ctx)
    sesja.zapamietaj_forme(kat, an["klucz"], przyp, rdzen)
    # Nazwa z rzeczownikiem żywotnym („Aptekarz”) ma biernik równy dopełniaczowi, a surogat (nieżywotny) mianownikowi.
    # Biernik takiej nazwy jest więc oddawany dopełniaczem surogatu, żeby przy powrocie dał tę samą formę.
    zywotna = dane["rodzaj"] in ("m1", "m2") and dane["liczba"] == "sg"
    forma = pule.formy_nazwy(baza)["gen" if zywotna and przyp == "acc" else przyp] + (f" {dane['sufiks']}" if dane.get("sufiks") else "")
    return gram.jak_wzor(rdzen, forma) + forma_prawna


def forma_nazwy(sesja: Sesja, kat: str, klucz: str, dane: dict, przyp: str) -> tuple[str, bool]:
    widziana = sesja.forma(kat, klucz, przyp)
    if widziana:
        return widziana, True
    out, pewna = [], True
    glowa_rodzaj, liczba = dane["rodzaj"], dane["liczba"]
    for g in dane["grupa"]:
        lemat, forma = g["lemat"], None
        if g["klasa"] == "nieodm":
            forma = lemat
        elif g["klasa"] == "ign":
            # Forma niewidziana w oryginale: reguła odmiany z wymianami spółgłosek („Stalmecie”, nie „Stalmetie”).
            # Nadal niepewna, bo nazwa spoza słownika może mieć odmianę nieregularną.
            forma = formy_ign(lemat)[przyp]
            pewna = pewna and przyp in ("nom", "acc" if not lemat.endswith("a") else "nom")
        else:
            for i in morf.generuj(lemat):
                if i.liczba == liczba and przyp in i.przypadki and (
                        (g["klasa"] == "subst" and i.klasa == "subst") or (g["klasa"] == "adj" and i.klasa == "adj" and glowa_rodzaj in i.rodzaje)):
                    forma = i.forma
                    break
            if forma is None:
                forma, pewna = g["wzor"], False
        out.append(g["pre"] + _wielkosc(g["wzor"][len(g["pre"]):], forma) if g["klasa"] not in ("nieodm",) else forma)
    return dane.get("przed", "") + " ".join(out) + dane["reszta"], pewna


# ---------- deanonimizacja ----------

def indeks(sesja: Sesja) -> dict[str, list[tuple]]:
    idx: dict[str, list[tuple]] = {}
    for sur in sesja.uzyte("MIEJSCE"):
        for przyp, forma in pule.formy_miejsca(sur).items():
            idx.setdefault(forma, []).append(("MIEJSCE", sur, przyp))
    for kat in ("FIRMA", "NAZWA"):
        for sur in sesja.uzyte(kat):
            for przyp, forma in pule.formy_nazwy(sur).items():
                idx.setdefault(forma, []).append((kat, sur, przyp))
    return idx


def odtworz(sesja: Sesja, a: int, b: int, w: str, wpisy: list[tuple], tekst: str) -> tuple[int, int, str, bool] | None:
    kat, sur = wpisy[0][0], wpisy[0][1]
    kand = {e[2] for e in wpisy if e[0] == kat}

    def widziane(klucz: str) -> set:
        return {wr for (k0, k1, wr) in sesja.formy if k0 == kat and k1 == klucz}

    if kat == "MIEJSCE":
        klucz, dane = next((k, d) for k, s, d in sesja.wpisy("MIEJSCE") if s == sur)
        forma, pewna = forma_miejsca(sesja, klucz, dane, gram.rozstrzygnij(kand, tekst, a, widziane(klucz)))
        return a, b, gram.jak_wzor(w, forma), not pewna
    kandydaci = [(k, d) for k, s, d in sesja.wpisy(kat) if s == sur]
    dlugi = next(((k, d) for k, d in kandydaci if d.get("sufiks")), None)
    if dlugi and tekst[b:b + 1 + len(dlugi[1]["sufiks"])].lower() == " " + dlugi[1]["sufiks"].lower():
        klucz, dane = dlugi
        b += 1 + len(dlugi[1]["sufiks"])
    else:
        krotkie = [(k, d) for k, d in kandydaci if d.get("alias")] if dlugi else []
        klucz, dane = (krotkie or [x for x in kandydaci if not x[1].get("alias")] or kandydaci)[0]
    przyp = gram.rozstrzygnij(kand, tekst, a, widziane(klucz))
    if dane["rodzaj"] in ("m1", "m2") and dane["liczba"] == "sg" and przyp == "acc":
        przyp = "nom"  # biernik nazwy żywotnej byłby oddany dopełniaczem surogatu (patrz nazwa())
    forma, pewna = forma_nazwy(sesja, kat, klucz, dane, przyp)
    return a, b, gram.jak_wzor(w, forma), not pewna

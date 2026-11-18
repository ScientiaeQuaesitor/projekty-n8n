"""Osoby: mapowanie na poziomie słowa. Lemat imienia -> imię zastępcze tej samej płci (z parą zdrobnienia),
lemat nazwiska -> nazwisko zastępcze na -ski. Forma surogatu ma ten sam przypadek co oryginał."""
import regex as re

from .. import morf
from . import gram, pule
from .sesja import Sesja

RX_SLOWO = re.compile(r"\p{L}+")
PLEC_SUROGATU = ({x: "m" for p in pule.IMIONA_M for x in p} | {x: "f" for p in pule.IMIONA_F for x in p}
                 | {x: "m" for x in pule.IMIONA_M_BEZ_PARY} | {x: "f" for x in pule.IMIONA_F_BEZ_PARY})
KONCOWKI_M = {"nom": "", "gen": "a", "dat": "owi", "acc": "a", "inst": "em", "loc": "ie", "voc": "ie"}


def _an(w: str):
    return morf.analizuj_ocr(w.capitalize() if len(w) > 1 and w.isupper() else w)


def _imie_i(w: str):
    return [i for i in _an(w) if "imię" in i.nazwy and i.klasa == "subst" and i.liczba == "sg"]


def _nazw_i(w: str):
    return [i for i in _an(w) if "nazwisko" in i.nazwy and i.klasa == "subst"]


def _plec(i) -> str:
    return "f" if i.rodzaj == "f" else "m"


def _rodzina(lemat: str) -> str:
    """Klucz rodziny: żeńskie nazwisko przymiotnikowe sprowadzone do męskiego (Kowalska -> Kowalski)."""
    return lemat[:-1] + "i" if re.search(r"(?:sk|ck|dzk)a$", lemat) else lemat


def _tytul_plec(tekst: str, pos: int) -> str | None:
    m = re.search(r"\b(pani|panią|pan|pana|panu|panem|panie)\.?\s+$", tekst[max(0, pos - 12):pos], re.I)
    if not m:
        return None
    return "f" if m.group(1).lower() in ("pani", "panią") else "m"


def rozbierz(sesja: Sesja, pow: str, tekst: str, start: int) -> dict | None:
    """Analiza zakresu osoby: role słów, płeć, przypadek, lematy. None, gdy to nie wygląda na osobę."""
    slowa = []
    for m in RX_SLOWO.finditer(pow):
        w = m.group()
        inicjal = len(w) == 1 and w.isupper() and pow[m.end():m.end() + 1] == "."
        slowa.append({"a": m.start(), "b": m.end(), "w": w, "rola": "INICJAL" if inicjal else None})
    zwykle = [s for s in slowa if s["rola"] is None]
    if not zwykle:
        return None
    sam = len(zwykle) == 1 and len(slowa) == 1
    for i, s in enumerate(zwykle):
        ostatnie = i == len(zwykle) - 1
        s["rola"] = "IMIE" if _imie_i(s["w"]) and (not ostatnie or sam) else "NAZWISKO"
    # „Jan Paweł”, „Anna Maria”: ostatnie słowo jest częstym imieniem, a nie nazwiskiem
    if (len(zwykle) >= 2 and len(zwykle) == len(slowa) and all(_imie_i(s["w"]) for s in zwykle)
            and any(i.lemat in pule.CZESTE_IMIONA for i in _imie_i(zwykle[-1]["w"]))):
        for s in zwykle:
            s["rola"] = "IMIE"

    def zbiory(plec: str):
        out = []
        for s in zwykle:
            if s["rola"] == "IMIE":
                z = {p for i in _imie_i(s["w"]) if _plec(i) == plec for p in i.przypadki}
                if not z:
                    return None
                out.append(z)
            else:
                inter = _nazw_i(s["w"])
                if inter:
                    z = {p for i in inter if _plec(i) == plec and (i.rodzaj in ("m1", "f")) for p in i.przypadki}
                    if z:
                        out.append(z)
        return out

    imiona = [s for s in zwykle if s["rola"] == "IMIE"]
    hipotezy = {}
    for plec in ("m", "f"):
        z = zbiory(plec)
        if z is None:
            continue
        wspolne = set.intersection(*z) if z else set()
        hipotezy[plec] = (wspolne, z)
    if not hipotezy:
        hipotezy = {"m": (set(), [])}
    zgodne = [p for p, (w, z) in hipotezy.items() if w or not z]
    if imiona:
        kand = zgodne or list(hipotezy)
        znane = [p for p in kand if any(i.lemat in pule.ZNANE_IMIONA and _plec(i) == p for i in _imie_i(imiona[0]["w"]))]
        # Imię dwuznaczne („Romana”: kobieta w mianowniku albo mężczyzna w dopełniaczu): rozstrzyga kontekst.
        # Bez przyimka przed nazwą bardziej prawdopodobny jest mianownik, po przyimku przypadek, którego on wymaga.
        # Mianownik jest domyślny tylko na początku wiersza lub pozycji listy („3. Romana X, córka …”);
        # w środku zdania nazwą może rządzić rzeczownik („córka Stanisława”), czego ta reguła nie widzi.
        przyimek = gram.przyimek_przed(tekst, start)
        poczatek = bool(re.search(r"(?:^|\n|\|)\s*(?:\d+[.)_]\s*)?$|\s\d+[.)_]\s*$", tekst[max(0, start - 12):start]))
        oczekiwane = set(gram.PRZYIMKI[przyimek]) if przyimek else ({"nom"} if poczatek else set())
        pasujace = [p for p in kand if (hipotezy[p][0] or (hipotezy[p][1][0] if hipotezy[p][1] else set())) & oczekiwane]
        if len(kand) == 1:
            plec = kand[0]
        elif len(pasujace) == 1:
            plec = pasujace[0]
        else:
            plec = (znane or kand)[0]
    else:
        # Samo nazwisko: tytuł przed nim, forma wyłącznie żeńska (-ska), osoba znana z dokumentu, na końcu słownik.
        # Słownik nie wystarcza, bo wiele nazwisk ma w nim tylko formy męskie („pani Marczak”).
        nazw = zwykle[-1]["w"]
        inter = [i for i in _nazw_i(nazw) if i.rodzaj in ("m1", "f")]
        plcie = {_plec(i) for i in inter if i.liczba == "sg"}
        klucze = {_rodzina(i.lemat) for i in inter} | {nazw.capitalize() if nazw.isupper() else nazw}
        z_par = {d["plec"] for k, _, d in sesja.wpisy("PARA") if k.split("|")[1] in klucze}
        plec = (_tytul_plec(tekst, start) or ("f" if plcie == {"f"} else None)
                or (next(iter(z_par)) if len(z_par) == 1 else None) or ("m" if "m" in plcie or not plcie else "f"))
        if plec not in hipotezy:
            hipotezy[plec] = (set(), [])
    wspolne, z = hipotezy.get(plec, (set(), []))
    kandydaci = wspolne or (z[0] if z else set())
    przypadek = gram.rozstrzygnij(kandydaci, tekst, start)

    for s in zwykle:
        w = s["w"]
        if s["rola"] == "IMIE":
            inter = [i for i in _imie_i(w) if _plec(i) == plec]
            trafne = [i for i in inter if przypadek in i.przypadki] or inter
            lematy = sorted({i.lemat for i in trafne})
            s["lemat"] = next((l for l in lematy if l in pule.ZNANE_IMIONA), lematy[0])
            s["liczba"] = "sg"
        else:
            inter = [i for i in _nazw_i(w) if _plec(i) == plec and i.rodzaj in ("m1", "f")]
            sg = [i for i in inter if i.liczba == "sg"]
            pl = [i for i in inter if i.liczba == "pl" and i.rodzaj == "m1"]
            wybor = sg or pl
            s["liczba"] = "sg" if sg or not pl else "pl"
            s["znane"] = bool(wybor)
            if wybor:
                trafne = [i for i in wybor if przypadek in i.przypadki] or wybor
                s["lemat"] = _rodzina(sorted(trafne, key=lambda i: (abs(len(i.lemat) - len(w)), i.lemat))[0].lemat)
            else:
                wn = w.capitalize() if w.isupper() else w
                konc = KONCOWKI_M.get(przypadek, "")
                s["lemat"] = wn[:-len(konc)] if plec == "m" and konc and wn.endswith(konc) and len(wn) - len(konc) >= 3 else wn
    return {"slowa": slowa, "plec": plec, "przypadek": przypadek}


def zarejestruj_pary(sesja: Sesja, analiza: dict) -> None:
    zw = [s for s in analiza["slowa"] if s["rola"] in ("IMIE", "NAZWISKO")]
    imiona = [s["lemat"] for s in zw if s["rola"] == "IMIE"]
    nazwiska = [s["lemat"] for s in zw if s["rola"] == "NAZWISKO"]
    for i in imiona:
        for n in nazwiska:
            if not sesja.wez("PARA", f"{i}|{n}"):
                sesja.ustaw("PARA", f"{i}|{n}", "", {"plec": analiza["plec"]})


def _zajete(ctx, formy) -> bool:
    return any(f.lower() in ctx.slowa for f in formy)


def _litery_innych(sesja: Sesja, nazwiska: set[str], litera: str) -> set[str]:
    """Pierwsze litery surogatów imion i inicjałów innych osób o tym samym nazwisku, których oryginalny inicjał
    jest inny niż litera. Inicjał przed nazwiskiem („A. Kowalska”) wraca po literze surogatu, więc dwie osoby
    o jednym nazwisku nie mogą dostać surogatów zaczynających się tą samą literą."""
    out = set()
    for k, _, _ in sesja.wpisy("PARA"):
        im, nz = k.split("|")
        wpis = sesja.wez("IMIE", im)
        if nz in nazwiska and im[:1] != litera and wpis:
            out.add(wpis[0][:1])
    for k, s, _ in sesja.wpisy("INICJAL"):
        lit, nz = k.split("|")
        if nz in nazwiska and lit != litera:
            out.add(s)
    return out


def surogat_imienia(sesja: Sesja, lemat: str, plec: str, ctx) -> str:
    wpis = sesja.wez("IMIE", lemat)
    if wpis:
        return wpis[0]
    baza = pule.PELNE.get(lemat, lemat)
    para = sesja.wez("IMIEPARA", baza)
    if para:
        pelne, zdrobn = para[0].split("|")
    else:
        # Imię mające zdrobnienie bierze surogat z parą; pozostałe najpierw imiona bez pary, żeby par nie zużywać
        pary = pule.IMIONA_F if plec == "f" else pule.IMIONA_M
        bez_pary = [(x, x) for x in (pule.IMIONA_F_BEZ_PARY if plec == "f" else pule.IMIONA_M_BEZ_PARY)]
        uzyte = {tuple(s.split("|")) for s in sesja.uzyte("IMIEPARA")}
        oryginaly = {k for k, _, _ in sesja.wpisy("IMIE")}
        nazwiska = {k.split("|")[1] for k, _, _ in sesja.wpisy("PARA") if k.split("|")[0] in (lemat, baza)}
        litery = _litery_innych(sesja, nazwiska, lemat[:1]) if nazwiska else set()

        def zakazane(p) -> bool:
            return (p[0] in oryginaly or p[1] in oryginaly or p[0][:1] in litery or p[1][:1] in litery
                    or _zajete(ctx, list(pule.formy_imienia(p[0]).values()) + list(pule.formy_imienia(p[1]).values())))

        kolejne = (pary, bez_pary) if baza in pule.ZDROBNIENIA else (bez_pary, pary)
        wolne = [p for pula in kolejne for p in pula if p not in uzyte and not zakazane(p)]
        if not wolne:
            raise RuntimeError(f"Wyczerpana pula imion zastępczych (płeć {plec}) w sesji {sesja.id}")
        pierwsza = [p for p in wolne if p in kolejne[0]] or wolne
        pelne, zdrobn = sesja.z_puli(pierwsza, uzyte, zakazane)
        sesja.ustaw("IMIEPARA", baza, f"{pelne}|{zdrobn}", {"plec": plec})
    if baza != lemat or baza in pule.ZDROBNIENIA:
        # imię z parą: pełne -> pełne, zdrobnienie -> zdrobnienie
        if not sesja.wez("IMIE", baza):
            sesja.ustaw("IMIE", baza, pelne, {"plec": plec})
        domyslne = pule.ZDROBNIENIA[baza][0]
        if not sesja.wez("IMIE", domyslne):
            sesja.ustaw("IMIE", domyslne, zdrobn, {"plec": plec, "domyslne": True})
        if not sesja.wez("IMIE", lemat):
            sesja.ustaw("IMIE", lemat, zdrobn, {"plec": plec})
    else:
        sesja.ustaw("IMIE", lemat, pelne, {"plec": plec})
    return sesja.wez("IMIE", lemat)[0]


def surogat_nazwiska(sesja: Sesja, klucz: str, znane: bool, ctx) -> str:
    wpis = sesja.wez("NAZWISKO", klucz)
    if wpis:
        return wpis[0]
    oryginaly = {k for k, _, _ in sesja.wpisy("NAZWISKO")}
    sur = sesja.z_puli(pule.NAZWISKA, sesja.uzyte("NAZWISKO"), lambda n: n in oryginaly or n[:-1].lower() in ctx.tekst_l, pule.zapas_nazwiska)
    return sesja.ustaw("NAZWISKO", klucz, sur, {"znane": znane})


def podmien(sesja: Sesja, pow: str, tekst: str, start: int, ctx) -> str | None:
    an = rozbierz(sesja, pow, tekst, start)
    if an is None:
        return None
    plec, przyp = an["plec"], an["przypadek"]
    out, pos = [], 0
    zw = an["slowa"]
    for idx, s in enumerate(zw):
        out.append(pow[pos:s["a"]])
        w = s["w"]
        wn = w.capitalize() if len(w) > 1 and w.isupper() else w
        if s["rola"] == "IMIE":
            sur = surogat_imienia(sesja, s["lemat"], plec, ctx)
            forma = pule.formy_imienia(sur).get(przyp) or sur
            sesja.zapamietaj_forme("IMIE", s["lemat"], przyp, wn)
        elif s["rola"] == "NAZWISKO":
            sur = surogat_nazwiska(sesja, s["lemat"], s["znane"], ctx)
            forma = pule.formy_nazwiska(sur, plec, s["liczba"])[przyp]
            sesja.zapamietaj_forme("NAZWISKO", s["lemat"], f"{plec}:{s['liczba']}:{przyp}", wn)
        else:
            nazw = next((x["lemat"] for x in zw[idx + 1:] if x["rola"] == "NAZWISKO"), "")
            imiona = [k.split("|")[0] for k, _, _ in sesja.wpisy("PARA") if k.split("|")[1] == nazw and k.startswith(w)]
            if len(set(imiona)) == 1:
                forma = surogat_imienia(sesja, imiona[0], plec, ctx)[0]
            else:
                wpis = sesja.wez("INICJAL", f"{w}|{nazw}")
                if wpis:
                    forma = wpis[0]
                else:
                    zajete = _litery_innych(sesja, {nazw}, w)
                    rng = sesja.losowe("INICJAL", w, nazw)
                    litery = [chr(c) for c in range(65, 91) if chr(c) not in zajete] or [chr(c) for c in range(65, 91)]
                    forma = sesja.ustaw("INICJAL", f"{w}|{nazw}", rng.choice(litery))
        out.append(gram.jak_wzor(w, forma))
        pos = s["b"]
    out.append(pow[pos:])
    return "".join(out)


# ---------- deanonimizacja ----------

def indeks(sesja: Sesja) -> dict[str, list[tuple]]:
    """forma surogatu -> wpisy (rola, surogat, płeć, liczba, przypadek)."""
    idx: dict[str, list[tuple]] = {}
    for sur in sesja.uzyte("IMIE"):
        for przyp, forma in pule.formy_imienia(sur).items():
            idx.setdefault(forma, []).append(("IMIE", sur, PLEC_SUROGATU[sur], "sg", przyp))
    for sur in sesja.uzyte("NAZWISKO"):
        for plec, liczba in (("m", "sg"), ("f", "sg"), ("m", "pl"), ("f", "pl")):
            for przyp, forma in pule.formy_nazwiska(sur, plec, liczba).items():
                idx.setdefault(forma, []).append(("NAZWISKO", sur, plec, liczba, przyp))
    return idx


def _oryginal_imienia(sesja: Sesja, sur: str) -> str:
    kand = [(k, d) for k, s, d in sesja.wpisy("IMIE") if s == sur]
    widziane = [k for k, _ in kand if any(kk == ("IMIE", k) for kk in {(a, b) for a, b, _ in sesja.formy})]
    return (widziane or [k for k, d in kand if not d.get("domyslne")] or [k for k, _ in kand])[0]


def forma_nazwiska(sesja: Sesja, klucz: str, znane: bool, plec: str, liczba: str, przyp: str) -> tuple[str, bool]:
    """Oryginalne nazwisko w żądanej formie: (forma, pewna)."""
    widziana = sesja.forma("NAZWISKO", klucz, f"{plec}:{liczba}:{przyp}")
    if widziana:
        return widziana, True
    if plec == "f" and liczba == "sg":
        if not re.search(r"(?:sk|ck|dzk)i$", klucz):
            return klucz, True  # żeńskie nazwisko rzeczownikowe jest nieodmienne
        lemat, rodzaj = klucz[:-1] + "a", "f"
    else:
        lemat, rodzaj = klucz, "m1"
    for i in morf.generuj(lemat):
        if i.klasa == "subst" and i.liczba == liczba and i.rodzaj == rodzaj and przyp in i.przypadki and "nazwisko" in i.nazwy:
            return i.forma, True
    if przyp == "nom" and liczba == "sg":
        return lemat, True
    return (klucz + KONCOWKI_M[przyp] if plec == "m" and liczba == "sg" else lemat), False


def odtworz(sesja: Sesja, grupa: list[dict], tekst: str) -> list[tuple[int, int, str, bool]]:
    """grupa: sąsiednie trafienia form osobowych [{a, b, w, wpisy}]. Zwraca podmiany na oryginały."""
    start = grupa[0]["a"]
    imie = next((e for g in grupa for e in g["wpisy"] if e[0] == "IMIE"), None)
    kolejnosc = [imie[2]] if imie else ([_tytul_plec(tekst, start)] if _tytul_plec(tekst, start) else []) + ["m", "f"]
    wybrane = None
    for plec in dict.fromkeys(kolejnosc):
        for liczba_n in ("sg", "pl"):
            zb = []
            for g in grupa:
                z = {e[4] for e in g["wpisy"] if e[2] == plec and (e[0] == "IMIE" or e[3] == liczba_n)}
                zb.append(z)
            if all(zb) and (set.intersection(*zb) or len(zb) == 1):
                wybrane = (plec, liczba_n, set.intersection(*zb))
                break
        if wybrane:
            break
    if not wybrane:
        return []
    plec, liczba_n, kand = wybrane
    # Przypadki, w których wszystkie słowa grupy widziano w dokumentach (rozstrzyga np. dopełniacz i biernik)
    widziane = set(gram.KOLEJNOSC)
    for g in grupa:
        rola, sur = next((e[0], e[1]) for e in g["wpisy"] if e[2] == plec)
        if rola == "IMIE":
            lemat = _oryginal_imienia(sesja, sur)
            widziane &= {w for (kat, k, w) in sesja.formy if kat == "IMIE" and k == lemat}
        else:
            klucz = next(k for k, s, _ in sesja.wpisy("NAZWISKO") if s == sur)
            widziane &= {w.split(":")[2] for (kat, k, w) in sesja.formy if kat == "NAZWISKO" and k == klucz and w.startswith(f"{plec}:{liczba_n}:")}
    przyp = gram.rozstrzygnij(kand, tekst, start, widziane)
    out = []
    for g in grupa:
        rola, sur = next((e[0], e[1]) for e in g["wpisy"] if e[2] == plec)
        if rola == "IMIE":
            lemat = _oryginal_imienia(sesja, sur)
            forma = sesja.forma("IMIE", lemat, przyp) or pule.formy_imienia(lemat).get(przyp)
            pewna = forma is not None or przyp == "nom"
            forma = forma or lemat
        else:
            klucz, dane = next((k, d) for k, s, d in sesja.wpisy("NAZWISKO") if s == sur)
            forma, pewna = forma_nazwiska(sesja, klucz, dane.get("znane", False), plec, liczba_n, przyp)
        out.append((g["a"], g["b"], gram.jak_wzor(g["w"], forma), not pewna))
    # Inicjał przed nazwiskiem: „B. Zawilska”
    pierwszy = grupa[0]
    m = re.search(r"(\p{Lu})\.\s?$", tekst[max(0, start - 4):start])
    if m and all(e[0] == "NAZWISKO" for e in pierwszy["wpisy"]):
        sur = pierwszy["wpisy"][0][1]
        klucz = next(k for k, s, _ in sesja.wpisy("NAZWISKO") if s == sur)
        kandydaci = set()
        for k, _, _ in sesja.wpisy("PARA"):
            im, nz = k.split("|")
            wpis = sesja.wez("IMIE", im)
            if nz == klucz and wpis and wpis[0][0] == m.group(1):
                kandydaci.add(im[0])
        if not kandydaci:
            kandydaci = {k.split("|")[0] for k, s, _ in sesja.wpisy("INICJAL") if k.split("|")[1] == klucz and s == m.group(1)}
        if kandydaci:
            a = start - len(m.group(0))
            # Kilka osób o tym nazwisku z tą samą literą surogatu: wybór niepewny, do przejrzenia
            out.append((a, a + 1, sorted(kandydaci)[0], len(kandydaci) > 1))
    return out

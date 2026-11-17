"""Adresy: podmiana po składnikach. Ulica -> ulica o nazwie nieodmiennej, numery i kod losowo,
miejscowość zgodnie z mapą miejscowości sesji."""
import regex as re

from .. import morf
from . import gram, nazwy, numery, pule
from .sesja import Sesja

PRE = r"(?:ul\.|ulic\p{L}+|al\.|alei|aleja|aleję|pl\.|plac\p{L}*|os\.|osiedl\p{L}+)"
NR = r"\d+[A-Za-z]?(?:\s?/\s?\d+[A-Za-z]?)?(?:\s+(?:m\.|lok\.)\s?\d+)?"
RX_ADRES = re.compile(rf"^(?P<pre>{PRE})(?P<s1>\s+)(?P<nazwa>.+?)(?P<s2>\s+)(?P<nr>{NR})(?P<reszta>.*)$", re.S)
RX_KOD = re.compile(r"^(?P<s3>,?\s+)?(?P<kod>\d{2}-\d{3})(?P<s4>\s+)(?P<miasto>.+)$", re.S)
RX_W = re.compile(r"^(?P<s3>,?\s+we?\s+)(?P<miasto>.+)$", re.S)


def _przym_f(w: str):
    return [i for i in morf.analizuj(w) if i.klasa == "adj" and i.liczba == "sg" and "f" in i.rodzaje]


def _ulica(sesja: Sesja, nazwa: str, tekst: str, start: int, ctx) -> tuple[str, str]:
    """Zwraca (klucz, surogat ulicy)."""
    inter = _przym_f(nazwa) if " " not in nazwa else []
    if inter:  # ulica przymiotnikowa: „Chorzowskiej” -> klucz „Chorzowska”
        mian = next((i.forma for i in morf.generuj(inter[0].lemat) if i.klasa == "adj" and i.liczba == "sg" and "f" in i.rodzaje and "nom" in i.przypadki), nazwa)
        klucz = mian[0].upper() + mian[1:]
        przyp = gram.rozstrzygnij({p for i in inter for p in i.przypadki}, tekst, start)
        sesja.zapamietaj_forme("ULICA", klucz, przyp, nazwa)
    else:
        klucz = nazwa
    wpis = sesja.wez("ULICA", klucz)
    if wpis:
        return klucz, wpis[0]
    sur = sesja.z_puli(pule.ULICE, sesja.uzyte("ULICA"), lambda u: u.lower() in ctx.tekst_l, lambda rng: pule.zapas_nazwiska(rng) + "ego")
    sesja.ustaw("ULICA", klucz, sur, {"odmienna": bool(inter), "lemat": inter[0].lemat if inter else None})
    return klucz, sur


def _numer(sesja: Sesja, klucz_ulicy: str, nr: str, ctx=None) -> str:
    wpis = sesja.wez("NRDOM", f"{klucz_ulicy}|{nr}")
    if wpis:
        return wpis[0]
    rng = sesja.losowe("NRDOM", klucz_ulicy, nr)
    for _ in range(50):
        nowy = re.sub(r"\d+", lambda m: str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in m.group()[1:]), nr)
        # jak przy numerach: bez ciągu obecnego w tekście oryginału i bez powtórzenia innego surogatu sesji
        if nowy != nr and not numery.zajety(sesja, ctx, nowy):
            break
    if nowy == nr:
        nowy = re.sub(r"\d", lambda m: str((int(m.group()) + 3) % 9 + 1), nr, count=1)
    return sesja.ustaw("NRDOM", f"{klucz_ulicy}|{nr}", nowy)


def _ogon(sesja: Sesja, reszta: str, tekst: str, pos: int, ctx) -> str | None:
    if not reszta:
        return ""
    m = RX_KOD.match(reszta)
    if m:
        miasto = nazwy.miejsce(sesja, m["miasto"], tekst, pos + m.start("miasto"), ctx, "nom")
        return (m["s3"] or "") + numery.podmien(sesja, "KOD", m["kod"], ctx) + m["s4"] + (miasto or m["miasto"])
    m = RX_W.match(reszta)
    if m:
        miasto = nazwy.miejsce(sesja, m["miasto"], tekst, pos + m.start("miasto"), ctx, "loc")
        return m["s3"] + (miasto or m["miasto"])
    return None


def podmien(sesja: Sesja, pow: str, tekst: str, start: int, ctx) -> str | None:
    m = RX_ADRES.match(pow)
    if m:
        klucz, sur = _ulica(sesja, m["nazwa"], tekst, start, ctx)
        ogon = _ogon(sesja, m["reszta"], tekst, start + m.start("reszta"), ctx)
        if ogon is not None:
            return m["pre"] + m["s1"] + sur + m["s2"] + _numer(sesja, klucz, m["nr"], ctx) + ogon
    ogon = _ogon(sesja, pow, tekst, start, ctx)
    if ogon:
        return ogon
    return nazwy.miejsce(sesja, pow, tekst, start, ctx)  # zakres bez rozpoznanej struktury: jedna nazwa miejsca


def znajdz(sesja: Sesja, tekst: str) -> list[tuple[int, int, str, bool]]:
    out = []
    for klucz, sur, dane in sesja.wpisy("ULICA"):
        for m in re.finditer(rf"(?<![\p{{L}}\d]){re.escape(sur)}(?![\p{{L}}\d])(?:(\s+)({NR}))?", tekst):
            forma, pewna = klucz, True
            if dane.get("odmienna"):
                pre = re.search(rf"{PRE}\s+$", tekst[:m.start()])
                przyp = gram.rozstrzygnij({"nom", "gen", "loc"}, tekst, pre.start() if pre else m.start())
                forma = sesja.forma("ULICA", klucz, przyp)
                if not forma:
                    gen = next((i.forma for i in morf.generuj(dane["lemat"]) if i.klasa == "adj" and i.liczba == "sg" and "f" in i.rodzaje and przyp in i.przypadki), None)
                    forma, pewna = (gen[0].upper() + gen[1:], True) if gen else (klucz, False)
            out.append((m.start(), m.start() + len(sur), forma, not pewna))
            if m.group(2):
                oryg = next((k.split("|", 1)[1] for k, s, _ in sesja.wpisy("NRDOM") if k.startswith(klucz + "|") and s == m.group(2)), None)
                if oryg:
                    out.append((m.start(2), m.end(2), oryg, False))
    return out

"""Reguły gramatyczne wspólne dla podmiany i deanonimizacji: wybór przypadka z kontekstu."""
import regex as re

KOLEJNOSC = ("nom", "gen", "acc", "inst", "dat", "loc", "voc")

# Przyimek -> przypadki, którymi rządzi (kolejność = preferencja przy niejednoznaczności)
PRZYIMKI = {
    "w": ("loc", "acc"), "we": ("loc", "acc"), "na": ("loc", "acc"), "o": ("loc", "acc"), "po": ("loc", "acc"), "przy": ("loc",),
    "z": ("gen", "inst"), "ze": ("gen", "inst"),
    "do": ("gen",), "od": ("gen",), "dla": ("gen",), "bez": ("gen",), "u": ("gen",), "wobec": ("gen",), "według": ("gen",),
    "obok": ("gen",), "koło": ("gen",), "podczas": ("gen",), "spośród": ("gen",), "oprócz": ("gen",), "zamiast": ("gen",),
    "przez": ("acc",),
    "przed": ("inst", "acc"), "nad": ("inst", "acc"), "pod": ("inst", "acc"), "za": ("inst", "acc"),
    "między": ("inst",), "pomiędzy": ("inst",), "poza": ("inst",),
    "ku": ("dat",), "dzięki": ("dat",), "przeciw": ("dat",), "przeciwko": ("dat",), "wbrew": ("dat",),
}
# Słowa między przyimkiem a nazwą, które nie zmieniają rządu: „z panią Ewą”, „przy ul. Długiej”
PRZEZROCZYSTE = re.compile(r"^(?:pan|pani|pana|panu|panem|panią|panie|państwa|państwem|państwu|dr|inż|mgr|prof|mec|mecenas\p{L}*|hab"
                           r"|ul|ulic\p{L}*|al|alei|pl|os)$", re.I)


def przyimek_przed(tekst: str, pos: int) -> str | None:
    """Przyimek stojący bezpośrednio przed pozycją, w tym samym wierszu. Między nim a nazwą mogą stać
    tylko tytuły i skróty adresowe („z panią Ewą”, „przy ul. Długiej”)."""
    wiersz = tekst[max(0, pos - 60):pos].rsplit("\n", 1)[-1]
    slowa = re.findall(r"(\p{L}+)\.?[  ]+", wiersz)
    if not re.search(r"\p{L}\.?[  ]+$", wiersz):
        return None
    for s in reversed(slowa[-4:]):
        if s.lower() in PRZYIMKI:
            # „o” w „sp. z o.o.” nie jest przyimkiem: przed prawdziwym przyimkiem stoi odstęp albo początek wiersza
            return s.lower() if re.search(rf"(?:^|[\s(„]){re.escape(s)}[  ]", wiersz) else None
        if not PRZEZROCZYSTE.match(s):
            return None
    return None


def rozstrzygnij(kandydaci: set, tekst: str, pos: int, widziane: set | None = None) -> str:
    """Wybiera jeden przypadek z możliwych. Miejscownik w polszczyźnie występuje tylko po przyimku.
    widziane: przypadki, w których tę nazwę zaobserwowano w dokumentach (używane przy deanonimizacji)."""
    kandydaci = set(kandydaci) or set(KOLEJNOSC[:6])
    p = przyimek_przed(tekst, pos)
    if p:
        zgodne = [x for x in PRZYIMKI[p] if x in kandydaci]
        if zgodne:
            return next((x for x in zgodne if widziane and x in widziane), zgodne[0])
    else:
        if "voc" in kandydaci and _wolacz(tekst, pos):
            return "voc"
        kandydaci = (kandydaci - {"loc"}) or kandydaci
    kandydaci = (kandydaci - {"voc"}) or kandydaci
    kolejne = [k for k in KOLEJNOSC if k in kandydaci]
    return next((k for k in kolejne if widziane and k in widziane), kolejne[0])


def _wolacz(tekst: str, pos: int) -> bool:
    """Zwrot do adresata: „Panie Grzegorzu,” na początku wiersza albo po powitaniu."""
    return bool(re.search(r"(?:^|\n|,[ ]|[Dd]obry[ ]|[Ww]itaj[ ]|[Cc]ześć[ ])(?:Panie|Pani|Szanown\p{L}+|Drog\p{L}+)(?:[ ]\p{L}+)?[ ]$",
                          tekst[max(0, pos - 40):pos]))


def jak_wzor(wzor: str, tekst: str) -> str:
    """Przenosi wielkość liter wzoru (WERSALIKI) na tekst."""
    return tekst.upper() if len(wzor) > 1 and wzor.isupper() else tekst

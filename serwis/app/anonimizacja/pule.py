"""Pule surogatów i tabele ich odmiany.

Imiona i miasta odmienia Morfeusz (wpisy bez pełnego paradygmatu są odrzucane przy imporcie).
Nazwiska, firmy i nazwy produktów mają odmianę regularną, liczoną regułą."""
from functools import lru_cache

from .. import morf

P6 = ("nom", "gen", "dat", "acc", "inst", "loc")

# (imię pełne, zdrobnienie). Celowo imiona rzadsze, żeby nie kolidowały z prawdziwymi w dokumentach.
IMIONA_M = [("Bronisław", "Bronek"), ("Zdzisław", "Zdzisiek"), ("Mieczysław", "Mietek"), ("Wiesław", "Wiesiek"),
            ("Kazimierz", "Kazik"), ("Ryszard", "Rysiek"), ("Antoni", "Antek"), ("Franciszek", "Franek"),
            ("Józef", "Józek"), ("Władysław", "Władek"), ("Witold", "Witek"), ("Tadeusz", "Tadek"),
            ("Czesław", "Czesiek"), ("Zenon", "Zenek"), ("Lucjan", "Lucek"), ("Waldemar", "Waldek"),
            ("Bolesław", "Bolek"), ("Edward", "Edek"), ("Feliks", "Felek"), ("Roman", "Romek"),
            ("Zygmunt", "Zygmuś"), ("Ignacy", "Ignaś"), ("Leon", "Leoś"), ("Eugeniusz", "Gienek")]
# Bez żeńskich odpowiedników imion męskich z puli: „Bronisława” to także dopełniacz od „Bronisław”.
IMIONA_F = [("Genowefa", "Gienia"), ("Kazimiera", "Kazia"), ("Jadwiga", "Jadzia"), ("Stefania", "Stefcia"), ("Helena", "Hela"), ("Wanda", "Wandzia"), ("Danuta", "Danusia"),
            ("Krystyna", "Krysia"), ("Urszula", "Ula"), ("Lucyna", "Lusia"), ("Bogumiła", "Bogusia"),
            ("Elżbieta", "Ela"), ("Jolanta", "Jola"), ("Wioletta", "Wiola"), ("Zuzanna", "Zuzia"),
            ("Emilia", "Emilka"), ("Cecylia", "Cesia"), ("Felicja", "Fela"), ("Leokadia", "Lodzia")]

# Zdrobnienia imion spotykanych w dokumentach: pełne imię -> zdrobnienia (pierwsze jest domyślne)
ZDROBNIENIA = {
    "Katarzyna": ["Kasia", "Kaśka"], "Aleksandra": ["Ola", "Olka"], "Małgorzata": ["Gosia", "Małgosia"],
    "Agnieszka": ["Aga", "Agusia"], "Anna": ["Ania", "Anka"], "Maria": ["Marysia", "Maryla"], "Joanna": ["Asia", "Joasia"],
    "Barbara": ["Basia", "Baśka"], "Magdalena": ["Magda", "Madzia"], "Zofia": ["Zosia", "Zośka"], "Ewa": ["Ewka", "Ewunia"],
    "Dorota": ["Dorotka", "Dosia"], "Monika": ["Monia"], "Natalia": ["Natalka"], "Karolina": ["Karolcia", "Karola"],
    "Justyna": ["Justynka"], "Beata": ["Beatka"], "Iwona": ["Iwonka"], "Teresa": ["Tereska", "Renia"], "Halina": ["Halinka"],
    "Irena": ["Irenka", "Irka"], "Sylwia": ["Sylwka"], "Marta": ["Martusia"], "Paulina": ["Paula"], "Izabela": ["Iza"],
    "Bożena": ["Bożenka"], "Weronika": ["Wera"], "Julia": ["Julka"], "Wiktoria": ["Wika"], "Patrycja": ["Pati"],
    "Tomasz": ["Tomek"], "Jakub": ["Kuba"], "Piotr": ["Piotrek"], "Krzysztof": ["Krzysiek", "Krzyś"], "Stanisław": ["Staszek", "Stach"],
    "Jan": ["Janek", "Jaś"], "Andrzej": ["Jędrek"], "Michał": ["Michaś"], "Paweł": ["Pawełek"], "Marek": ["Mareczek"],
    "Grzegorz": ["Grzesiek", "Grześ"], "Zbigniew": ["Zbyszek"], "Jerzy": ["Jurek"], "Adam": ["Adaś"], "Wojciech": ["Wojtek"],
    "Robert": ["Robercik"], "Dariusz": ["Darek"], "Mariusz": ["Mariuszek"], "Henryk": ["Heniek"], "Radosław": ["Radek"],
    "Bartosz": ["Bartek"], "Mateusz": ["Mati"], "Marcin": ["Marcinek"], "Rafał": ["Rafałek"], "Sławomir": ["Sławek"],
    "Jarosław": ["Jarek"], "Mirosław": ["Mirek"], "Przemysław": ["Przemek"], "Bogdan": ["Boguś"], "Leszek": ["Lesio"],
    "Maciej": ["Maciek"], "Łukasz": ["Łukaszek"], "Kamil": ["Kamilek"], "Dawid": ["Dawidek"], "Karol": ["Karolek"],
    "Arkadiusz": ["Arek"], "Sebastian": ["Seba"], "Dominik": ["Domino"], "Aleksander": ["Olek"], "Ireneusz": ["Irek"],
}
PELNE = {z: p for p, zz in ZDROBNIENIA.items() for z in zz}
ZNANE_IMIONA = set(ZDROBNIENIA) | set(PELNE) | {x for para in IMIONA_M + IMIONA_F for x in para}
# Imiona na tyle częste, że jako ostatnie słowo po innym imieniu są raczej drugim imieniem niż nazwiskiem
CZESTE_IMIONA = set(ZDROBNIENIA) | {
    "Maksymilian", "Antoni", "Franciszek", "Stanisław", "Józef", "Kazimierz", "Tadeusz", "Ryszard", "Zygmunt", "Edward", "Roman",
    "Wiktor", "Filip", "Szymon", "Igor", "Oliwer", "Oskar", "Hubert", "Julian", "Leon", "Ignacy", "Tymoteusz", "Krystian", "Damian",
    "Daniel", "Patryk", "Konrad", "Emil", "Eryk", "Fabian", "Gabriel", "Jacek", "Kacper", "Norbert", "Wiesław", "Zdzisław",
    "Maria", "Anna", "Zuzanna", "Hanna", "Helena", "Alicja", "Amelia", "Emilia", "Oliwia", "Lena", "Maja", "Laura", "Nina", "Klara",
    "Elżbieta", "Krystyna", "Danuta", "Jadwiga", "Grażyna", "Jolanta", "Urszula", "Renata", "Wanda", "Stefania", "Genowefa", "Janina",
    "Kinga", "Ewelina", "Aneta", "Edyta", "Marzena", "Agata", "Bogusława", "Marianna", "Antonina", "Michalina", "Gabriela", "Martyna"}

NAZWISKA = ["Zawilski", "Jarzębski", "Modrzewski", "Wrzosowski", "Jesionowski", "Świerkowski", "Klonowski", "Cisowski",
            "Jodłowski", "Kasztanowski", "Tarninowski", "Osinowski", "Cedrowski", "Łozinowski", "Jałowcowski", "Bzowski",
            "Kalinowski", "Berberyski", "Derenowski", "Głogowiński", "Jaśminowski", "Limbowski", "Morwowski", "Rokitnikowski",
            "Trzmielinowski", "Wiązowski", "Żarnowcowski", "Bukszpanowski", "Czeremchowski", "Dziurawcowski"]

MIASTA = ["Radom", "Olsztyn", "Tarnów", "Płock", "Kalisz", "Sieradz", "Konin", "Elbląg", "Toruń", "Legnica", "Łomża",
          "Nysa", "Ostrołęka", "Piła", "Bytom", "Chełm", "Przemyśl", "Słupsk", "Koszalin", "Włocławek", "Mielec", "Tczew",
          "Sanok", "Inowrocław", "Zgierz", "Ełk", "Sopot", "Kołobrzeg", "Wałbrzych", "Głogów", "Racibórz", "Pabianice"]

FIRMY_M = ["Tarvon", "Melkam", "Sorbin", "Vadrem", "Kelbon", "Nordam", "Lirten", "Balvis", "Zefiron", "Maltis",
           "Rodavin", "Varnis", "Dentrom", "Kortas", "Embras", "Galdon", "Hestim", "Kastom", "Lodvin", "Mirtas",
           "Ostrim", "Pravon", "Rimtas", "Sulden", "Tevrom", "Ulvis", "Voltram", "Wersan", "Zoltim", "Arvelon"]
FIRMY_F = ["Belmina", "Kordana", "Marvena", "Solvina", "Teksana", "Virama", "Zentiwa", "Albesa", "Dormina", "Felkana",
           "Gostiwa", "Helvina", "Irkama", "Jantesa", "Kalvina", "Lermana", "Mostina", "Nardewa", "Orlesa", "Pilvana"]
SUFIKSY_FIRM = ["Group", "Holding", "Invest", "Partner", "Polska", "Trade", "System", "Serwis"]
NAZWY = ["Avelin", "Borwen", "Cytram", "Delvon", "Elaris", "Fintem", "Gorvis", "Halmen", "Ikaron", "Jaspem",
         "Kevlim", "Lumaris", "Meltan", "Norvim", "Opalin", "Pertas", "Kwantem", "Rubiton", "Saltem", "Tirvon"]
# Ulice o nazwach nieodmiennych w zapisie adresowym (dopełniacz patrona)
ULICE = ["Kopernika", "Słowackiego", "Konopnickiej", "Reymonta", "Prusa", "Orzeszkowej", "Norwida", "Staffa", "Tuwima",
         "Żeromskiego", "Kochanowskiego", "Sienkiewicza", "Chopina", "Moniuszki", "Matejki", "Wyspiańskiego",
         "Kasprowicza", "Asnyka", "Fredry", "Reja", "Ogrodników", "Hutników", "Tkaczy", "Kolejarzy"]


@lru_cache(maxsize=None)
def formy_imienia(lemat: str) -> dict[str, str]:
    """przypadek -> forma, według Morfeusza. Pusty słownik, gdy Morfeusz nie zna imienia."""
    out: dict[str, str] = {}
    for i in morf.generuj(lemat):
        if i.klasa == "subst" and i.liczba == "sg" and "imię" in i.nazwy:
            for p in i.przypadki:
                out.setdefault(p, i.forma)
    return out


@lru_cache(maxsize=None)
def formy_miasta(lemat: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in morf.generuj(lemat):
        if i.klasa == "subst" and i.liczba == "sg" and "nazwa_geograficzna" in i.nazwy:
            for p in i.przypadki:
                out.setdefault(p, i.forma)
    return out


def formy_nazwiska(nazwisko: str, plec: str, liczba: str = "sg") -> dict[str, str]:
    """Nazwisko na -ski: odmiana regularna. plec: m albo f."""
    r = nazwisko[:-1]  # Zawilsk
    if liczba == "pl":
        return {"nom": r[:-1] + "cy", "gen": r + "ich", "dat": r + "im", "acc": r + "ich", "inst": r + "imi", "loc": r + "ich", "voc": r[:-1] + "cy"}
    if plec == "f":
        return {"nom": r + "a", "gen": r + "iej", "dat": r + "iej", "acc": r + "ą", "inst": r + "ą", "loc": r + "iej", "voc": r + "a"}
    return {"nom": r + "i", "gen": r + "iego", "dat": r + "iemu", "acc": r + "iego", "inst": r + "im", "loc": r + "im", "voc": r + "i"}


def formy_nazwy(nazwa: str) -> dict[str, str]:
    """Wymyślona nazwa firmy lub produktu: rodzaj żeński dla zakończonych na -a, męski w pozostałych."""
    if nazwa.endswith("a"):
        r = nazwa[:-1]
        return {"nom": nazwa, "gen": r + "y", "dat": r + "ie", "acc": r + "ę", "inst": r + "ą", "loc": r + "ie", "voc": r + "o"}
    return {"nom": nazwa, "gen": nazwa + "u", "dat": nazwa + "owi", "acc": nazwa, "inst": nazwa + "em", "loc": nazwa + "ie", "voc": nazwa + "ie"}


_NAGLOSY = ["B", "D", "G", "K", "L", "M", "N", "P", "R", "S", "T", "V", "Z", "Br", "Dr", "Gr", "Kr", "Pr", "Tr", "Kl", "Pl", "St"]
_SRODKI = ["al", "an", "ar", "el", "en", "er", "il", "in", "ir", "ol", "on", "or", "ul", "un", "ur", "av", "ev", "iv", "od", "ad", "em", "om"]
_KONCE = ["dan", "den", "kan", "kon", "lan", "len", "man", "men", "ran", "ren", "tan", "ten", "van", "ven", "zan", "zen", "bin", "din", "lin", "min", "rin", "tin", "vin"]


def zapas_nazwy(rng) -> str:
    """Wymyślona nazwa o regularnej odmianie męskiej: „Kralvin”, „Borden”. Ponad 10 tys. kombinacji."""
    return rng.choice(_NAGLOSY) + rng.choice(_SRODKI) + rng.choice(_KONCE)


def zapas_nazwiska(rng) -> str:
    return rng.choice(_NAGLOSY) + rng.choice(_SRODKI) + rng.choice(["anowski", "enowski", "inowski", "onowski", "arowski", "elowski", "ikowski"])


def formy_miejsca(nazwa: str) -> dict[str, str]:
    """Miasto z puli odmienia Morfeusz, nazwę zapasową reguła."""
    return formy_miasta(nazwa) or formy_nazwy(nazwa)


def _pelny(formy: dict) -> bool:
    return all(p in formy for p in P6)


# Odrzucenie wpisów, których Morfeusz nie odmienia w całości
IMIONA_M = [p for p in IMIONA_M if all(_pelny(formy_imienia(x)) for x in p)]
IMIONA_F = [p for p in IMIONA_F if all(_pelny(formy_imienia(x)) for x in p)]
MIASTA = [m for m in MIASTA if _pelny(formy_miasta(m))]

# Imiona zastępcze bez zdrobnienia, dla oryginałów, które zdrobnienia w słowniku nie mają
IMIONA_M_BEZ_PARY = [x for x in ["Alojzy", "Benedykt", "Cezary", "Edmund", "Fabian", "Gerard", "Hieronim", "Kornel", "Ludwik",
                                 "Marceli", "Norbert", "Oskar", "Rudolf", "Seweryn", "Teodor", "Wacław", "Klemens", "Konstanty",
                                 "Leopold", "Maurycy", "Oktawian", "Remigiusz", "Tymoteusz", "Wincenty"] if _pelny(formy_imienia(x))]
IMIONA_F_BEZ_PARY = [x for x in ["Adela", "Bernadeta", "Celina", "Eleonora", "Florentyna", "Gertruda", "Hortensja", "Idalia",
                                 "Klementyna", "Leontyna", "Matylda", "Otylia", "Pelagia", "Rozalia", "Sabina", "Teodozja",
                                 "Wilhelmina", "Zenobia", "Aurelia", "Brygida", "Kornelia", "Ludmiła", "Apolonia", "Balbina"]
                     if _pelny(formy_imienia(x))]

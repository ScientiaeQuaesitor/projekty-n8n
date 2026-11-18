"""Sesja anonimizacji: mapa oryginał -> surogat wspólna dla wszystkich dokumentów sprawy, trwała w SQLite."""
import hashlib
import json
import os
import random
import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "anonimizator.db"

SCHEMAT = """
CREATE TABLE IF NOT EXISTS sesja (id TEXT PRIMARY KEY, nazwa TEXT, utworzona TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS mapa (sesja TEXT, kat TEXT, klucz TEXT, surogat TEXT, dane TEXT, PRIMARY KEY (sesja, kat, klucz));
CREATE TABLE IF NOT EXISTS formy (sesja TEXT, kat TEXT, klucz TEXT, wariant TEXT, forma TEXT, PRIMARY KEY (sesja, kat, klucz, wariant));
"""


def _polacz(sciezka) -> sqlite3.Connection:
    if str(sciezka) != ":memory:":
        Path(sciezka).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sciezka, isolation_level=None, check_same_thread=False)
    conn.executescript(SCHEMAT)
    return conn


class Sesja:
    """kat: IMIE, NAZWISKO, PARA, INICJAL, MIEJSCE, FIRMA, NAZWA, ULICA, NRDOM, KOD, NUMER."""

    def __init__(self, id: str | None = None, nazwa: str = "", sciezka=None, nowe_id: str | None = None):
        """id: wczytanie istniejącej sesji. nowe_id: nowa sesja o ustalonym id (pomiary powtarzalne), domyślnie losowe."""
        self.conn = _polacz(sciezka or DB_PATH)
        if id is None:
            id = nowe_id or uuid.uuid4().hex[:12]
            self.conn.execute("INSERT INTO sesja (id, nazwa) VALUES (?, ?)", (id, nazwa))
        elif not self.conn.execute("SELECT 1 FROM sesja WHERE id = ?", (id,)).fetchone():
            raise KeyError(f"Nie ma sesji {id}")
        self.id = id
        self.mapa: dict[tuple[str, str], tuple[str, dict]] = {}
        self.formy: dict[tuple[str, str, str], str] = {}
        for kat, klucz, surogat, dane in self.conn.execute("SELECT kat, klucz, surogat, dane FROM mapa WHERE sesja = ?", (id,)):
            self.mapa[(kat, klucz)] = (surogat, json.loads(dane))
        for kat, klucz, wariant, forma in self.conn.execute("SELECT kat, klucz, wariant, forma FROM formy WHERE sesja = ?", (id,)):
            self.formy[(kat, klucz, wariant)] = forma

    # --- mapa ---
    def wez(self, kat: str, klucz: str):
        return self.mapa.get((kat, klucz))

    def ustaw(self, kat: str, klucz: str, surogat: str, dane: dict | None = None) -> str:
        dane = dane or {}
        self.mapa[(kat, klucz)] = (surogat, dane)
        self.conn.execute("INSERT OR REPLACE INTO mapa VALUES (?, ?, ?, ?, ?)", (self.id, kat, klucz, surogat, json.dumps(dane, ensure_ascii=False)))
        return surogat

    def uzyte(self, *kategorie: str) -> set[str]:
        return {s for (kat, _), (s, _) in self.mapa.items() if kat in kategorie}

    def wpisy(self, kat: str) -> list[tuple[str, str, dict]]:
        return [(klucz, s, d) for (k, klucz), (s, d) in self.mapa.items() if k == kat]

    def z_puli(self, pula: list, uzyte: set, zakazane, zapas=None) -> object:
        """Pierwszy wolny element puli w kolejności właściwej dla sesji. zakazane(element) -> bool."""
        kolejnosc = list(pula)
        random.Random(self.id).shuffle(kolejnosc)
        for x in kolejnosc:
            if x not in uzyte and not zakazane(x):
                return x
        if zapas is None:
            raise RuntimeError("Wyczerpana pula surogatów dla tej sesji")
        # Pula stała się skończyła: nazwy generowane z sylab, bez ograniczenia liczby
        rng = self.losowe("ZAPAS", len(uzyte))
        for _ in range(10000):
            x = zapas(rng)
            if x not in uzyte and not zakazane(x):
                return x
        raise RuntimeError("Nie udało się wygenerować wolnego surogatu")

    # --- formy zaobserwowane w dokumentach: pierwsza zapamiętana wygrywa ---
    def zapamietaj_forme(self, kat: str, klucz: str, wariant: str, forma: str) -> None:
        if (kat, klucz, wariant) not in self.formy:
            self.formy[(kat, klucz, wariant)] = forma
            self.conn.execute("INSERT OR IGNORE INTO formy VALUES (?, ?, ?, ?, ?)", (self.id, kat, klucz, wariant, forma))

    def forma(self, kat: str, klucz: str, wariant: str) -> str | None:
        return self.formy.get((kat, klucz, wariant))

    def losowe(self, *ziarno) -> random.Random:
        return random.Random(hashlib.sha256("|".join(map(str, (self.id,) + ziarno)).encode()).hexdigest())

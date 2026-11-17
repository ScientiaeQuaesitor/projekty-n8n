import os
import sqlite3
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import detekcja
from .anonimizacja import silnik
from .anonimizacja.sesja import Sesja

DOCLING_URL = os.environ.get("DOCLING_URL", "http://docling:5001")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "anonimizator.db"

app = FastAPI(title="anonimizator", version="0.2.0")


def _sprawdz_baze() -> dict:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1")
        return {"ok": True, "sciezka": str(DB_PATH)}
    except Exception as e:  # zdrowie ma raportować, nie wywracać się
        return {"ok": False, "blad": str(e)}


async def _sprawdz_http(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
        return {"ok": r.status_code == 200, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "blad": f"{type(e).__name__}: {e}"}


class ZapytanieWykryj(BaseModel):
    tekst: str
    detektory: list[str] = ["regex", "spacy", "hf", "llm"]


class NowaSesja(BaseModel):
    nazwa: str = ""


class ZapytanieTekst(BaseModel):
    tekst: str
    detektory: list[str] = ["regex", "spacy", "hf", "llm"]


def _sesja(id: str) -> Sesja:
    try:
        return Sesja(id)
    except KeyError:
        raise HTTPException(404, f"Nie ma sesji {id}")


def _detektory(lista: list[str]) -> None:
    nieznane = [d for d in lista if d not in detekcja.DETEKTORY]
    if nieznane:
        raise HTTPException(422, f"Nieznane detektory: {nieznane}. Dostępne: {list(detekcja.DETEKTORY)}")


@app.post("/wykryj")
def wykryj(z: ZapytanieWykryj) -> dict:
    """Surowa detekcja encji w tekście. Bez scalania i podmiany."""
    _detektory(z.detektory)
    try:
        encje = detekcja.wykryj(z.tekst, z.detektory)
    except detekcja.llm.BladLLM as e:
        raise HTTPException(502, str(e))
    return {"encje": [e.jako_dict() for e in encje]}


@app.post("/sesje")
def nowa_sesja(z: NowaSesja) -> dict:
    s = Sesja(nazwa=z.nazwa)
    return {"id": s.id, "nazwa": z.nazwa}


@app.post("/sesje/{id}/anonimizuj-tekst")
def anonimizuj_tekst(id: str, z: ZapytanieTekst) -> dict:
    """Zwraca tekst z surogatami oraz listę podmian. Mapa surogatów zostaje w sesji."""
    _detektory(z.detektory)
    try:
        return silnik.anonimizuj(_sesja(id), z.tekst, detektory=z.detektory)
    except detekcja.llm.BladLLM as e:
        # Bez pełnej detekcji nie oddajemy tekstu: lepiej błąd niż częściowa anonimizacja
        raise HTTPException(502, str(e))


@app.post("/sesje/{id}/deanonimizuj-tekst")
def deanonimizuj_tekst(id: str, z: ZapytanieTekst) -> dict:
    """Przywraca oryginalne nazwy w tekście z surogatami. Pole niepewne wskazuje miejsca do przejrzenia."""
    return silnik.deanonimizuj(_sesja(id), z.tekst)


@app.get("/sesje/{id}/mapa")
def mapa(id: str) -> dict:
    s = _sesja(id)
    widoczne = ("IMIE", "NAZWISKO", "MIEJSCE", "FIRMA", "NAZWA", "ULICA", "NUMER")
    return {"id": id, "mapa": [{"kategoria": kat, "oryginal": klucz, "surogat": sur}
                               for (kat, klucz), (sur, _) in sorted(s.mapa.items()) if kat in widoczne]}


@app.get("/zdrowie")
async def zdrowie() -> dict:
    """Stan serwisu i jego zależności. Pole ok jest prawdziwe tylko, gdy wszystko działa."""
    zaleznosci = {
        "baza": _sprawdz_baze(),
        "docling": await _sprawdz_http(f"{DOCLING_URL}/health"),
        "ollama": await _sprawdz_http(f"{OLLAMA_URL}/api/version"),
    }
    return {"ok": all(z["ok"] for z in zaleznosci.values()), "wersja": app.version, "zaleznosci": zaleznosci}

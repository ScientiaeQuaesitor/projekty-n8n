"""Dokumenty i zadania anonimizacji plików (PLAN 4.7): stan w SQLite, jeden wątek roboczy, jedno zadanie naraz.

Plik przyjęty przez API trafia do katalogu dokumentu (DATA_DIR/dokumenty/<id>/), zadanie czeka w kolejce. Wątek
roboczy bierze najstarsze zadanie, a po restarcie kontenera zadania przerwane w toku wracają do kolejki. Oceny
klasyfikacji są zapisywane w katalogu dokumentu po każdej paczce, więc wznowione zadanie nie pyta modelu drugi raz.

Statusy: czeka, w_toku, gotowe (plik do pobrania), do_przegladu (kontrola znalazła problem, plik nie jest wydawany),
blad. Audyt zapisuje zdarzenia z sumą SHA-256 tekstu zanonimizowanego, bez treści oryginałów."""
import hashlib
import json
import os
import sqlite3
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import pliki, raport
from .anonimizacja import silnik
from .anonimizacja.sesja import DB_PATH, Sesja
from .detekcja import llm

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
KATALOG = DATA_DIR / "dokumenty"

SCHEMAT = """
CREATE TABLE IF NOT EXISTS dokument (id TEXT PRIMARY KEY, sesja TEXT, nazwa TEXT, typ TEXT, status TEXT,
    utworzony TEXT DEFAULT CURRENT_TIMESTAMP, plik_wynikowy TEXT, raport TEXT, podsumowanie TEXT);
CREATE TABLE IF NOT EXISTS zadanie (id TEXT PRIMARY KEY, dokument TEXT, etap TEXT, status TEXT, blad TEXT,
    utworzone TEXT DEFAULT CURRENT_TIMESTAMP, rozpoczete TEXT, zakonczone TEXT, czasy TEXT);
CREATE TABLE IF NOT EXISTS audyt (id INTEGER PRIMARY KEY AUTOINCREMENT, kiedy TEXT DEFAULT CURRENT_TIMESTAMP,
    zdarzenie TEXT, sesja TEXT, dokument TEXT, model TEXT, skrot TEXT);
"""

# Sesja ma mapę w pamięci procesu: dwie operacje na tej samej sesji naraz (zadanie i anonimizacja tekstu z API)
# mogłyby dać ten sam surogat dwóm oryginałom. Blokada jest wspólna dla całego procesu.
BLOKADA_SESJI = threading.Lock()
_budzik = threading.Event()


def _baza() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMAT)
    return c


def audyt(zdarzenie: str, sesja: str = "", dokument: str = "", model: str = "", skrot: str = "") -> None:
    with _baza() as c:
        c.execute("INSERT INTO audyt (zdarzenie, sesja, dokument, model, skrot) VALUES (?, ?, ?, ?, ?)",
                  (zdarzenie, sesja, dokument, model, skrot))


def przyjmij(sesja: str, nazwa: str, dane: bytes) -> dict:
    """Zapisuje plik i tworzy zadanie. Typ jest sprawdzany od razu, żeby nieobsługiwany plik nie czekał w kolejce."""
    typ = pliki.rodzaj(nazwa, dane)
    dok, zad = uuid.uuid4().hex[:12], uuid.uuid4().hex[:12]
    katalog = KATALOG / dok
    katalog.mkdir(parents=True, exist_ok=True)
    (katalog / f"oryginal{Path(nazwa).suffix.lower()}").write_bytes(dane)
    with _baza() as c:
        c.execute("INSERT INTO dokument (id, sesja, nazwa, typ, status) VALUES (?, ?, ?, ?, 'czeka')", (dok, sesja, nazwa, typ))
        c.execute("INSERT INTO zadanie (id, dokument, etap, status) VALUES (?, ?, 'kolejka', 'czeka')", (zad, dok))
    audyt("przyjęty", sesja, dok, skrot=hashlib.sha256(dane).hexdigest())
    _budzik.set()
    return {"dokument": dok, "zadanie": zad, "typ": typ, "status": "czeka"}


def zadanie(id: str) -> dict | None:
    with _baza() as c:
        z = c.execute("SELECT * FROM zadanie WHERE id = ?", (id,)).fetchone()
        if not z:
            return None
        d = c.execute("SELECT * FROM dokument WHERE id = ?", (z["dokument"],)).fetchone()
    out = dict(z)
    out["czasy"] = json.loads(z["czasy"] or "{}")
    out["dokument"] = _dokument_dict(d)
    return out


def dokument(id: str) -> dict | None:
    with _baza() as c:
        d = c.execute("SELECT * FROM dokument WHERE id = ?", (id,)).fetchone()
    return _dokument_dict(d) if d else None


def _dokument_dict(d) -> dict:
    out = dict(d)
    out["podsumowanie"] = json.loads(d["podsumowanie"] or "{}")
    for k in ("plik_wynikowy", "raport"):
        out[k] = bool(out[k])
    return out


def sciezka(dok: str, co: str) -> Path | None:
    with _baza() as c:
        d = c.execute("SELECT plik_wynikowy, raport FROM dokument WHERE id = ?", (dok,)).fetchone()
    if not d or not d[co]:
        return None
    return KATALOG / dok / d[co]


def _etap(c, zad: str, etap: str) -> None:
    c.execute("UPDATE zadanie SET etap = ? WHERE id = ?", (etap, zad))


def _wykonaj(c, z) -> None:
    dok = c.execute("SELECT * FROM dokument WHERE id = ?", (z["dokument"],)).fetchone()
    katalog = KATALOG / dok["id"]
    oryginal = next(katalog.glob("oryginal.*"))
    dane = oryginal.read_bytes()
    model = llm.LLM_MODEL_KLASYFIKACJA
    from .ewaluacja import pamiec as pamiec_plik
    p_pamiec = pamiec_plik.sciezka(katalog, "klasyfikacja_", model)
    pamiec = pamiec_plik.wczytaj(p_pamiec)
    zapisz_pamiec = pamiec_plik.zapisywacz(p_pamiec, model)
    czasy: dict = {}
    t0 = time.time()
    with BLOKADA_SESJI:
        sesja = Sesja(dok["sesja"])
        if dok["typ"] == "pdf_skan":
            # Skan: tekst z OCR, wynik tekstowy. Odtworzenie dokumentu ze skanu to faza E (PLAN 6.1).
            from . import ekstrakcja
            _etap(c, z["id"], "ocr")
            tekst, info = ekstrakcja.tekst_z_pdf(oryginal)
            czasy["ekstrakcja"] = round(time.time() - t0, 1)
            _etap(c, z["id"], "anonimizacja")
            wynik = silnik.anonimizuj(sesja, tekst, pamiec=pamiec, model_klasyfikacji=model, zapisz_pamiec=zapisz_pamiec, czasy=czasy)
            # Dokument odtworzony z akapitów OCR (struktura, nie wygląd, bez pikseli oryginału) z tą samą kontrolą
            # pliku co zwykły DOCX
            wyjscie, tekst_pliku = pliki.docx_z_tekstu(wynik["tekst"])
            nazwa_wy = "zanonimizowany.docx"
            wynik["kontrola_pliku"] = pliki.kontrola_pliku(sesja, "docx", wyjscie, tekst_pliku)
            ok = wynik["kontrola"]["status"] == "ok" and wynik["kontrola_pliku"]["status"] == "ok"
            status = "gotowe" if ok else "do_przegladu"
            ocr_info, oryginal_tekst = info.get("ocr"), tekst
        else:
            _etap(c, z["id"], "anonimizacja")
            wyjscie, wynik = pliki.anonimizuj_plik(sesja, dok["nazwa"], dane, pamiec=pamiec, model_klasyfikacji=model,
                                                   zapisz_pamiec=zapisz_pamiec, czasy=czasy)
            nazwa_wy = f"zanonimizowany{oryginal.suffix}"
            ok = wynik["kontrola"]["status"] == "ok" and wynik["kontrola_pliku"]["status"] == "ok"
            status = "gotowe" if ok else "do_przegladu"
            ocr_info, oryginal_tekst = None, wynik["tekst_oryginalu"]
    zapisz_pamiec(pamiec)
    _etap(c, z["id"], "zapis")
    (katalog / nazwa_wy).write_bytes(wyjscie)
    (katalog / "raport.html").write_text(raport.zbuduj(f"{dok['nazwa']}: raport porównawczy", oryginal_tekst, wynik, ocr_info,
                                                       raport.obrazy_stron(oryginal) if dok["typ"] == "pdf_skan" else None),
                                         encoding="utf-8")
    # Pełny wynik z oryginałami zostaje lokalnie w katalogu dokumentu; w bazie tylko liczniki
    (katalog / "wynik.json").write_text(json.dumps({k: v for k, v in wynik.items() if k != "tekst_oryginalu"},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    kp = wynik.get("kontrola_pliku") or {}
    podsumowanie = {"podmiany": len(wynik["podmiany"]), "sporne": len(wynik["sporne"]), "zostawione": len(wynik["zostawione"]),
                    "kontrola_tekstu": wynik["kontrola"]["status"], "trafien_kontroli": len(wynik["kontrola"]["trafienia"]),
                    "kontrola_pliku": kp.get("status", "brak"), "roznic_tekstu_pliku": kp.get("liczba_roznic", 0),
                    "wyciekow_w_pliku": len(kp.get("wyciek", [])), "pozostalosci": len(kp.get("pozostalosci", [])),
                    "czyszczenie": wynik.get("czyszczenie", {}),
                    "mozna_zatwierdzic": status == "do_przegladu" and not alarm_pewny(wynik)}
    czasy["razem"] = round(time.time() - t0, 1)
    c.execute("UPDATE dokument SET status = ?, plik_wynikowy = ?, raport = 'raport.html', podsumowanie = ? WHERE id = ?",
              (status, nazwa_wy, json.dumps(podsumowanie, ensure_ascii=False), dok["id"]))
    c.execute("UPDATE zadanie SET status = ?, etap = 'koniec', zakonczone = CURRENT_TIMESTAMP, czasy = ? WHERE id = ?",
              (status, json.dumps(czasy), z["id"]))
    audyt(f"anonimizacja: {status}", dok["sesja"], dok["id"], model, hashlib.sha256(wynik["tekst"].encode()).hexdigest())


def alarm_pewny(wynik: dict) -> bool:
    """Alarm, którego nie można zatwierdzić: oryginał z mapy sesji albo numer z poprawną sumą kontrolną w tekście lub
    w pliku, albo pozostałość (obraz, załącznik) w pliku wynikowym. Różnice tekstu pliku i numery niepewne można
    zatwierdzić po przejrzeniu raportu."""
    kp = wynik.get("kontrola_pliku") or {}
    trafienia = list(wynik["kontrola"]["trafienia"]) + list(kp.get("wyciek", []))
    return any(t.get("pewny", True) for t in trafienia) or bool(kp.get("pozostalosci"))


def zatwierdz(id: str) -> dict:
    """Ręczne zatwierdzenie dokumentu do przeglądu z alarmem niepewnym: status gotowe, wpis w audycie."""
    d = dokument(id)
    if not d:
        raise KeyError(id)
    if d["status"] != "do_przegladu" or not d["podsumowanie"].get("mozna_zatwierdzic"):
        raise ValueError(f"Dokument ma status {d['status']} i nie może być zatwierdzony"
                         + (": kontrola znalazła pewny wyciek" if d["status"] == "do_przegladu" else ""))
    with _baza() as c:
        pods = dict(d["podsumowanie"], zatwierdzony_recznie=True)
        c.execute("UPDATE dokument SET status = 'gotowe', podsumowanie = ? WHERE id = ?", (json.dumps(pods, ensure_ascii=False), id))
    audyt("zatwierdzenie ręczne", d["sesja"], id)
    return dokument(id)


def _petla() -> None:
    c = _baza()
    # Zadania przerwane restartem wracają do kolejki
    c.execute("UPDATE zadanie SET status = 'czeka', etap = 'kolejka (wznowione)' WHERE status = 'w_toku'")
    c.execute("UPDATE dokument SET status = 'czeka' WHERE status = 'w_toku'")
    while True:
        z = c.execute("SELECT * FROM zadanie WHERE status = 'czeka' ORDER BY utworzone, rowid LIMIT 1").fetchone()
        if not z:
            _budzik.wait(5)
            _budzik.clear()
            continue
        c.execute("UPDATE zadanie SET status = 'w_toku', rozpoczete = CURRENT_TIMESTAMP WHERE id = ?", (z["id"],))
        c.execute("UPDATE dokument SET status = 'w_toku' WHERE id = ?", (z["dokument"],))
        try:
            _wykonaj(c, z)
        except Exception as e:
            blad = f"{type(e).__name__}: {e}"
            # Komunikat bez treści dokumentu: wyjątki z detekcji i plików nie zawierają tekstu oryginału
            c.execute("UPDATE zadanie SET status = 'blad', blad = ?, zakonczone = CURRENT_TIMESTAMP WHERE id = ?", (blad[:500], z["id"]))
            c.execute("UPDATE dokument SET status = 'blad' WHERE id = ?", (z["dokument"],))
            audyt("błąd", dokument=z["dokument"])
            traceback.print_exc()


_watek: threading.Thread | None = None


def uruchom() -> None:
    global _watek
    if _watek is None or not _watek.is_alive():
        _watek = threading.Thread(target=_petla, name="zadania", daemon=True)
        _watek.start()

"""Plik pamięci ocen klasyfikacji używany przez pomiary (obieg na zestawie, dokument prawdziwy).

Klucz oceny: „odcisk|fragment|kontekst”, gdzie odcisk zależy od promptu, wariantu i modelu (llm.odcisk_klasyfikacji).
Przy zapisie zostają tylko oceny z bieżącymi odciskami, więc oceny sprzed zmiany promptu same znikają z pliku."""
import json
import os
import pathlib

import regex as re

from ..detekcja import llm


def sciezka(katalog: pathlib.Path, przedrostek: str, model: str) -> pathlib.Path:
    return katalog / (przedrostek + re.sub(r"[^\w.-]", "_", model) + ".json")


def wczytaj(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def zapisywacz(p: pathlib.Path, model: str):
    """Funkcja do przekazania jako zapisz_pamiec: zapis atomowy (plik tymczasowy i podmiana), bez nieaktualnych ocen."""
    aktualne = {llm.odcisk_klasyfikacji(w, model) for w in llm.WARIANTY_KLASYFIKACJI}

    def zapisz(pamiec: dict) -> None:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps({k: v for k, v in pamiec.items() if k.split("|", 1)[0] in aktualne}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)

    return zapisz

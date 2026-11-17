"""Porównanie ustawień OCR Doclinga na jednym pliku, bez wzorca.

Uruchomienie w kontenerze:  python -m app.ewaluacja.ocr /srv/testy/prawdziwe/akt_notarialny.pdf

Miary zastępcze jakości (nie wypisują treści dokumentu):
  znane   odsetek słów (od 3 liter) znanych słownikowi Morfeusza
  ogonki  liczba polskich znaków diakrytycznych na 1000 liter (typowy polski tekst: 60 do 75)
  smieci  odsetek „słów” jedno i dwuliterowych spoza słownika (rozsypany tekst)"""
import pathlib
import sys
import time

import httpx
import regex as re

from .. import morf

DOCLING_URL = "http://docling:5001"
WARIANTY = {
    "auto": {},
    "auto+force": {"force_ocr": "true"},
    "easyocr-pl+force": {"ocr_preset": "easyocr", "ocr_lang": "pl", "force_ocr": "true"},
    "rapidocr+force": {"ocr_preset": "rapidocr", "force_ocr": "true"},
    "easyocr-pl+force+skala3": {"ocr_preset": "easyocr", "ocr_lang": "pl", "force_ocr": "true", "images_scale": "3"},
}


def miary(tekst: str) -> dict:
    slowa = re.findall(r"\p{L}+", tekst)
    dlugie = [s for s in slowa if len(s) >= 3]
    znane = sum(1 for s in dlugie if any(i.klasa != "ign" for i in morf.analizuj(s)))
    litery = len(re.findall(r"\p{L}", tekst))
    krotkie_obce = sum(1 for s in slowa if len(s) <= 2 and not any(i.klasa != "ign" for i in morf.analizuj(s)))
    return {"znakow": len(tekst), "slow": len(slowa), "znane": round(znane / max(1, len(dlugie)), 3),
            "ogonki": round(1000 * len(re.findall(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", tekst)) / max(1, litery), 1),
            "smieci": round(krotkie_obce / max(1, len(slowa)), 3)}


def konwertuj(plik: pathlib.Path, opcje: dict) -> tuple[str, float]:
    t0 = time.time()
    r = httpx.post(f"{DOCLING_URL}/v1/convert/file", timeout=3600,
                   files={"files": (plik.name, plik.read_bytes(), "application/pdf")},
                   data={"to_formats": "md", "do_ocr": "true", "image_export_mode": "placeholder", **opcje})
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(str(j["errors"])[:300])
    return j["document"]["md_content"] or "", time.time() - t0


def main() -> None:
    plik = pathlib.Path(sys.argv[1])
    wybrane = sys.argv[2:] or list(WARIANTY)
    print("| wariant | czas [s] | znaków | słów | znane | ogonki | śmieci |\n|---|---|---|---|---|---|---|", flush=True)
    for nazwa in wybrane:
        try:
            tekst, czas = konwertuj(plik, WARIANTY[nazwa])
        except Exception as e:
            print(f"| {nazwa} | błąd: {type(e).__name__}: {str(e)[:120]} |", flush=True)
            continue
        (plik.parent / f"ocr_{nazwa}.md").write_text(tekst, encoding="utf-8")
        m = miary(tekst)
        print(f"| {nazwa} | {czas:.0f} | {m['znakow']} | {m['slow']} | {m['znane']:.1%} | {m['ogonki']} | {m['smieci']:.1%} |", flush=True)


if __name__ == "__main__":
    main()

"""Ekstrakcja tekstu z PDF. Skan: OCR Tesseractem (model polski) przez OCRmyPDF, potem Docling tylko do układu
i kolejności czytania. PDF cyfrowy: Docling bez OCR. Wszystko lokalnie."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from . import ocr

DOCLING_URL = os.environ.get("DOCLING_URL", "http://docling:5001")
PROG_ZNAKOW_NA_STRONE = 200  # mniej znaków w warstwie tekstowej oznacza skan


def _warstwa_tekstowa(pdf: Path) -> tuple[int, int]:
    strony = int(next(l.split()[1] for l in subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout.splitlines() if l.startswith("Pages:")))
    znaki = len(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout.strip())
    return strony, znaki


def _docling(pdf: Path, ocr: bool, tabele: bool) -> str:
    r = httpx.post(f"{DOCLING_URL}/v1/convert/file", timeout=7200,
                   files={"files": (pdf.name, pdf.read_bytes(), "application/pdf")},
                   data={"to_formats": "md", "do_ocr": str(ocr).lower(), "do_table_structure": str(tabele).lower(), "image_export_mode": "placeholder"})
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(f"Docling: {str(j['errors'])[:300]}")
    return j["document"]["md_content"] or ""


def tekst_z_pdf(pdf: Path, jezyk: str = "pol") -> tuple[str, dict]:
    """Zwraca (tekst w Markdown, informacje o przebiegu)."""
    t0 = time.time()
    strony, znaki = _warstwa_tekstowa(pdf)
    skan = znaki < PROG_ZNAKOW_NA_STRONE * strony
    info = {"strony": strony, "skan": skan}
    if not skan:
        tekst = _docling(pdf, ocr=False, tabele=True)
    else:
        # Skan: dwa silniki OCR z wyborem lepszego odczytu w każdym wierszu (app/ocr.py)
        tekst, info["ocr"] = ocr.czytaj(pdf)
    info["czas_s"] = round(time.time() - t0)
    return tekst, info

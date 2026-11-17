"""Skany wzorcowe (PLAN 6.2): prawdziwa miara błędów OCR i wycieków na skanach, na danych fikcyjnych.

Uruchomienie w kontenerze:  python -m app.ewaluacja.skany [--dpi 170] [--bez-anonimizacji]

Każdy dokument wzorcowy jest składany do PDF (szerokość strony jak w zwykłym dokumencie), renderowany do obrazu
z obniżoną rozdzielczością, szumem, lekkim obrotem i kompresją JPEG, i czytany przez app.ocr (dwa silniki). Znany
tekst źródłowy daje miary, których nie da raport jakości OCR (on ocenia tylko słowa znane słownikowi):
1. CER: udział błędnych znaków po ujednoliceniu odstępów.
2. Encje odczytane dokładnie: osobno numery (PESEL, NIP, IBAN …) i nazwy (osoby, firmy, miejscowości, adresy).
3. Po pełnej anonimizacji tekstu z OCR: wycieki dokładne (encja wzorcowa w tekście wynikowym) i przybliżone (encja
   z jednym błędem znaku, czyli dana przekłamana przez OCR, której detekcja nie rozpoznała: nadal identyfikuje osobę).
Tekst z OCR jest zapisywany w testy/wyniki/skany/ (poza Gitem) i używany ponownie, jeśli skan się nie zmienił."""
import argparse
import difflib
import hashlib
import io
import json
import time

import fitz
import numpy as np
import regex as re
from PIL import Image

from .. import ocr
from ..anonimizacja import silnik
from ..anonimizacja.sesja import Sesja
from ..detekcja import llm
from . import pamiec as pamiec_plik
from .pliki import pdf_z_wzorca
from .scalanie import wykryj_z_cache
from .uruchom import WYNIKI
from .wzorce import wczytaj, wczytaj_zostaw

KATALOG = WYNIKI / "skany"
NUMEROWE = {"PESEL", "NIP", "REGON", "KRS", "IBAN", "TELEFON", "DOWOD", "SYGNATURA", "EMAIL"}


def skan(pdf: bytes, dpi: int, ziarno: int) -> bytes:
    """PDF z samymi obrazami stron: render w dpi, szare, obrót 0,4°, szum gaussowski, JPEG jakości 60."""
    rng = np.random.default_rng(ziarno)
    zrodlo, wynik = fitz.open(stream=pdf, filetype="pdf"), fitz.open()
    for s in zrodlo:
        pix = s.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        obraz = Image.frombytes("L", (pix.width, pix.height), pix.samples).rotate(0.4, expand=False, fillcolor=255)
        tab = np.asarray(obraz, dtype=np.float32) + rng.normal(0, 14, (pix.height, pix.width))
        b = io.BytesIO()
        Image.fromarray(np.clip(tab, 0, 255).astype(np.uint8)).save(b, "JPEG", quality=60)
        strona = wynik.new_page(width=s.rect.width, height=s.rect.height)
        strona.insert_image(strona.rect, stream=b.getvalue())
    return wynik.tobytes()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def cer(wzor: str, odczyt: str) -> float:
    a, b = _norm(wzor), _norm(odczyt)
    bledy = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                if op != "equal")
    return bledy / max(1, len(a))


def _jest(fragment: str, tekst: str, bledy: int = 0) -> bool:
    f = re.escape(_norm(fragment))
    wzor = f"(?<![\\p{{L}}\\d])(?:{f}){{e<={bledy}}}(?![\\p{{L}}\\d])" if bledy else f"(?<![\\p{{L}}\\d]){f}(?![\\p{{L}}\\d])"
    return bool(re.search(wzor, tekst, re.BESTMATCH) if bledy else re.search(wzor, tekst))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=170)
    ap.add_argument("--bez-anonimizacji", action="store_true")
    ap.add_argument("--llm", default=llm.LLM_MODEL)
    ap.add_argument("--klasyfikator", default=llm.LLM_MODEL_KLASYFIKACJA)
    args = ap.parse_args()
    KATALOG.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    dokumenty, zostaw = wczytaj(), wczytaj_zostaw()
    p_pamiec = pamiec_plik.sciezka(WYNIKI, "cache_klasyfikacja_", args.klasyfikator)
    pamiec = pamiec_plik.wczytaj(p_pamiec)
    zapisz_pamiec = pamiec_plik.zapisywacz(p_pamiec, args.klasyfikator)

    linie = ["# Etap 5: skany wzorcowe\n", "",
             "| dokument | strony | CER % | numery dokładnie | nazwy dokładnie | OCR: jakość | OCR: niepewne wiersze "
             "| podmiany | wycieki dokładne | wycieki z 1 błędem | zepsute | kontrola |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    szczegoly = []
    for nr, (dok, (tekst, wzorce)) in enumerate(dokumenty.items()):
        pdf = skan(pdf_z_wzorca(tekst, wzorce, szer=430, rozmiar=11), args.dpi, nr)
        klucz = hashlib.sha256(pdf).hexdigest()[:16]
        p_txt, p_info = KATALOG / f"{dok}.{args.dpi}.txt", KATALOG / f"{dok}.{args.dpi}.json"
        if p_info.exists() and json.loads(p_info.read_text(encoding="utf-8")).get("klucz") == klucz:
            odczyt, info = p_txt.read_text(encoding="utf-8"), json.loads(p_info.read_text(encoding="utf-8"))
        else:
            p_pdf = KATALOG / f"{dok}.{args.dpi}.pdf"
            p_pdf.write_bytes(pdf)
            t0 = time.time()
            odczyt, raport = ocr.czytaj(p_pdf)
            info = {"klucz": klucz, "ocr": raport, "czas_s": round(time.time() - t0)}
            p_txt.write_text(odczyt, encoding="utf-8")
            p_info.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        r = info["ocr"]
        numery = [w for w in {w.tekst: w for w in wzorce}.values() if w.typ in NUMEROWE]
        nazwy = [w for w in {w.tekst: w for w in wzorce}.values() if w.typ not in NUMEROWE]
        num_ok = sum(_jest(w.tekst, _norm(odczyt)) for w in numery)
        naz_ok = sum(_jest(w.tekst, _norm(odczyt)) for w in nazwy)
        bledne = [f"{w.typ} „{w.tekst}”" for w in numery + nazwy if not _jest(w.tekst, _norm(odczyt))]
        wiersz = (f"| {dok} | {r.get('strony_liczba', len(r.get('strony', [])))} | {100 * cer(tekst, odczyt):.1f} "
                  f"| {num_ok}/{len(numery)} | {naz_ok}/{len(nazwy)} | {r.get('jakosc')} | {r.get('niepewnych')} ")
        if args.bez_anonimizacji:
            linie.append(wiersz + "| – | – | – | – | – |")
        else:
            wykryte = wykryj_z_cache({dok: (odczyt, [])}, args.llm)[dok]
            sesja = Sesja(sciezka=":memory:", nowe_id="skan-0")
            wynik = silnik.anonimizuj(sesja, odczyt, wykryte, pamiec=pamiec, model_klasyfikacji=args.klasyfikator,
                                      zapisz_pamiec=zapisz_pamiec)
            anon = _norm(wynik["tekst"])
            # Wyciek liczony tylko dla encji, które OCR odczytał (dokładnie albo z jednym błędem): encja nieodczytana
            # wcale nie może wyciec, a jej zniekształcenie łapie miara przybliżona
            dokladne = sorted({w.tekst for w in wzorce if len(w.tekst) >= 4 and _jest(w.tekst, anon)})
            przyblizone = sorted({w.tekst for w in wzorce if len(w.tekst) >= 6 and w.tekst not in dokladne
                                  and _jest(w.tekst, anon, 1)})
            zepsute = sorted({z.tekst for z in zostaw[dok] if _jest(z.tekst, _norm(odczyt)) and not _jest(z.tekst, anon)})
            linie.append(wiersz + f"| {len(wynik['podmiany'])} | {len(dokladne)} | {len(przyblizone)} | {len(zepsute)} "
                                  f"| {wynik['kontrola']['status']} |")
            if dokladne or przyblizone or zepsute:
                szczegoly.append(f"\n## {dok}\n")
                szczegoly += [f"1. WYCIEK: „{w}”" for w in dokladne] + [f"1. WYCIEK Z BŁĘDEM OCR: „{w}”" for w in przyblizone]
                szczegoly += [f"1. ZEPSUTE: „{z}”" for z in zepsute]
        if bledne:
            szczegoly.append(f"\n## {dok}: encje odczytane z błędem ({len(bledne)})\n")
            szczegoly += [f"1. {b}" for b in bledne]
    zapisz_pamiec(pamiec)
    linie[1] = (f"Render {args.dpi} DPI, szum σ=14, obrót 0,4°, JPEG 60. Czas: {time.time() - t_start:.0f} s. "
                f"Wycieki i zepsute liczone na jednej sesji (skan-0).\n")
    tresc = "\n".join(linie + szczegoly) + "\n"
    (WYNIKI / f"etap5_skany_{args.dpi}.md").write_text(tresc, encoding="utf-8")
    print(tresc)


if __name__ == "__main__":
    main()

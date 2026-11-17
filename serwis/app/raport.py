"""Lokalny raport porównawczy HTML do przeglądu dokumentu w kilka minut.

Na górze to, co wymaga oceny człowieka: wynik kontroli wycieku, nazwy sporne (głosy modelu podzielone), nazwy
zostawione z kategorią, wykryte bez podmiany i jakość OCR. Każda pozycja prowadzi do miejsca w tekście.
Niżej oryginał obok wersji zanonimizowanej i tabela podmian.
Raport zawiera dane oryginalne, więc nie może opuścić maszyny."""
import html
from collections import Counter, defaultdict

import regex as re

KOLORY = {"OSOBA": "#ffd6a5", "FIRMA": "#caffbf", "NAZWA": "#bde0fe", "MIEJSCE": "#e2c6ff", "ADRES": "#fdffb6"}
STYL = """body{font:14px/1.5 system-ui,sans-serif;margin:16px;color:#111;background:#fff;max-width:1600px}
h1{font-size:19px;margin:0 0 6px} h2{font-size:15px;margin:22px 0 6px}
.kol{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.kol>div{white-space:pre-wrap;word-break:break-word;border:1px solid #ccc;padding:12px;border-radius:6px}
.kol h3{font-size:13px;margin:0 0 8px;color:#555}
mark{padding:0 2px;border-radius:3px;scroll-margin-top:80px}
mark.zost{background:none;outline:1px dashed #2a7;color:inherit}
mark.pom{background:none;outline:1px dashed #999;color:inherit}
mark.alarm{background:#ff8a8a;outline:2px solid #c00}
mark.cel{box-shadow:0 0 0 3px #36f}
table{border-collapse:collapse;margin-top:6px} td,th{border:1px solid #ccc;padding:3px 8px;text-align:left;font-size:13px;vertical-align:top}
.leg span{padding:2px 6px;margin-right:6px;border-radius:3px}
.status{display:inline-block;padding:4px 10px;border-radius:4px;font-weight:600}
.ok{background:#d8f5d0;color:#1d5c12} .zle{background:#ffd9d9;color:#8a0000} .uwaga{background:#fff1c2;color:#6b4e00}
.przeglad{border:1px solid #ddd;border-radius:6px;padding:4px 14px 12px;margin-bottom:16px;background:#fafafa}
.kontekst{color:#555;font-size:13px} a{color:#1a4fd6}"""


def _zaznacz(tekst: str, zakresy: list[tuple]) -> str:
    """zakresy: (start, end, klasa_css_lub_typ, dymek, id). Nakładające się zakresy są pomijane (pierwszy wygrywa)."""
    out, pos = [], 0
    for a, b, rodzaj, dymek, ident in sorted(zakresy, key=lambda z: (z[0], -z[1])):
        if a < pos:
            continue
        out.append(html.escape(tekst[pos:a]))
        styl = f' style="background:{KOLORY.get(rodzaj, "#ddd")}"' if rodzaj not in ("zost", "pom", "alarm") else ""
        klasa = f' class="{rodzaj}"' if rodzaj in ("zost", "pom", "alarm") else ""
        idattr = f' id="{ident}"' if ident else ""
        out.append(f'<mark{idattr}{klasa}{styl} title="{html.escape(dymek)}">{html.escape(tekst[a:b])}</mark>')
        pos = b
    out.append(html.escape(tekst[pos:]))
    return "".join(out)


def _wystapienia(tekst: str, fragment: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"(?<![\p{L}\d])" + re.escape(fragment) + r"(?![\p{L}\d])", tekst)]


def _kontekst(tekst: str, a: int, b: int, n: int = 50) -> str:
    return (html.escape(tekst[max(0, a - n):a]).replace("\n", " ") + "<b>" + html.escape(tekst[a:b]) + "</b>"
            + html.escape(tekst[b:b + n]).replace("\n", " "))


def zbuduj(tytul: str, oryginal: str, wynik: dict, ocr: dict | None = None) -> str:
    anon = wynik["tekst"]
    podmiany = sorted(wynik["podmiany"], key=lambda p: p["start"])
    lewe, prawe, przes = [], [], 0
    poz_anon = []   # pozycje podmian w tekście zanonimizowanym
    for i, p in enumerate(podmiany):
        a = p["start"] + przes
        lewe.append((p["start"], p["end"], p["typ"], f'{p["typ"]} → {p["surogat"]}', f"o{i}"))
        prawe.append((a, a + len(p["surogat"]), p["typ"], f'{p["typ"]} ← {p["oryginal"]}', f"a{i}"))
        poz_anon.append((a, a + len(p["surogat"])))
        przes += len(p["surogat"]) - (p["end"] - p["start"])

    # 1. Kontrola wycieku: trafienia mają pozycje w tekście zanonimizowanym
    kontrola = wynik.get("kontrola") or {"status": "brak", "trafienia": []}
    alarmy = []
    for i, t in enumerate(kontrola["trafienia"]):
        prawe.append((t["start"], t["end"], "alarm", f'KONTROLA: {t["rodzaj"]} ({t["kat"]})', f"k{i}"))
        alarmy.append(f'<li><a href="#k{i}">{html.escape(t["rodzaj"])}, {html.escape(t["kat"])}</a>: '
                      f'<span class="kontekst">…{_kontekst(anon, t["start"], t["end"])}…</span></li>')

    # 2. Zostawione i sporne: zaznaczenie wszystkich wystąpień w tekście zanonimizowanym, odnośnik do pierwszego
    kategorie = wynik.get("kategorie", {})
    zostawione = wynik.get("zostawione", {})
    pierwsze: dict[str, str] = {}
    for j, f in enumerate(sorted(set(zostawione) | set(wynik.get("sporne", [])), key=len, reverse=True)):
        for n, (a, b) in enumerate(_wystapienia(anon, f)):
            if any(a < y and b > x for x, y in poz_anon):
                continue
            ident = f"z{j}_{n}"
            prawe.append((a, b, "zost", f"zostawione: {kategorie.get(f, '')}", ident))
            pierwsze.setdefault(f, ident)
    for f in zostawione:
        # Nazwa z podmienionym członem własnym („Kancelarii Notarialnej we Wrocławiu”): odnośnik do tej podmiany
        p = next((i for i, p in enumerate(podmiany) if p["oryginal"] == f), None)
        if f not in pierwsze and p is not None:
            pierwsze[f] = f"a{p}"
    po_kat = defaultdict(list)
    for f, k in zostawione.items():
        po_kat[k].append(f)
    wiersze_zost = "".join(
        f"<tr><td>{html.escape(k)}</td><td>" + ", ".join(
            (f'<a href="#{pierwsze[f]}">{html.escape(f)}</a>' if f in pierwsze else html.escape(f)) for f in sorted(fs)) + "</td></tr>"
        for k, fs in sorted(po_kat.items()))

    # Sporne: co ostatecznie stało się z nazwą
    sporne = []
    for f in wynik.get("sporne", []):
        p = next((p for p in podmiany if p["oryginal"] == f), None)
        if p:
            los = f'podmieniona: „{p["surogat"]}”' + (" (tylko człon własny)" if p["typ"] == "OPISOWA" else " w całości")
            cel = f'#o{podmiany.index(p)}'
        else:
            los, cel = "zostawiona", (f"#{pierwsze[f]}" if f in pierwsze else "")
        glos = kategorie.get(f, "").removeprefix("SPORNE:")
        nazwa = f'<a href="{cel}">{html.escape(f)}</a>' if cel else html.escape(f)
        sporne.append(f"<tr><td>{nazwa}</td><td>{html.escape(glos)}</td><td>{html.escape(los)}</td></tr>")

    # 3. Wykryte bez podmiany: zaznaczenie w oryginale. Pominięte z powodu kategorii są już w punkcie 3 raportu,
    # a powtórzenia tego samego fragmentu są zliczane w jednym wierszu.
    grupy: dict[tuple, list[int]] = {}
    for i, p in enumerate(wynik.get("pominiete", [])):
        powod = p.get("powod", "brak surogatu dla tego zapisu")
        if "start" in p:
            lewe.append((p["start"], p["end"], "pom", f"bez podmiany: {powod}", f"p{i}"))
        if not powod.startswith("kategoria "):
            grupy.setdefault((p["tekst"], p["typ"], powod), []).append(i)
    bez = [f'<tr><td><a href="#p{nry[0]}">{html.escape(t)}</a>{f" ({len(nry)}×)" if len(nry) > 1 else ""}</td>'
           f'<td>{html.escape(typ)}</td><td>{html.escape(powod)}</td></tr>' for (t, typ, powod), nry in grupy.items()]

    # 4. Jakość OCR (raport bez treści: numery stron i wierszy)
    sekcja_ocr = ""
    if ocr:
        jak = ocr.get("jakosc", "?")
        klasa = {"dobra": "ok", "średnia": "uwaga", "słaba": "zle"}.get(jak, "uwaga")
        strony = "".join(f'<tr><td>{s["strona"]}</td><td>{s["wierszy"]}</td><td>{s["zamienionych"]}</td><td>{s["niepewnych_po"]}</td>'
                         f'<td>{", ".join(map(str, s["niepewne_wiersze"])) or "–"}</td></tr>'
                         for s in ocr.get("strony", []) if s.get("niepewnych_po") or s.get("zamienionych"))
        sekcja_ocr = (f'<h2>Jakość OCR: <span class="status {klasa}">{html.escape(jak)}</span></h2>'
                      f'<p>Wierszy {ocr.get("wierszy")}, niepewnych po dwóch silnikach {ocr.get("niepewnych")} '
                      f'({100 * ocr.get("udzial_niepewnych", 0):.1f}%), poprawionych drugim silnikiem {ocr.get("zamienionych")}, '
                      f'szacowane DPI {ocr.get("szacowane_dpi") or "?"}. W niepewnych wierszach nazwiska i cyfry mogą być błędne, '
                      f'więc detekcja mogła je pominąć: porównaj je ze skanem.</p>'
                      + (f"<table><tr><th>strona</th><th>wierszy</th><th>poprawionych</th><th>niepewnych</th><th>numery niepewnych wierszy na stronie</th></tr>{strony}</table>" if strony else ""))

    liczniki = Counter(p["typ"] for p in podmiany)
    unikalne = sorted({(p["typ"], p["oryginal"], p["surogat"]) for p in podmiany})
    wiersze_map = "".join(f"<tr><td>{html.escape(t)}</td><td>{html.escape(o)}</td><td>{html.escape(s)}</td></tr>" for t, o, s in unikalne)
    legenda = ("".join(f'<span style="background:{k}">{t}</span>' for t, k in KOLORY.items())
               + '<span style="background:#ddd">numery i inne</span><span style="outline:1px dashed #2a7">zostawione</span>'
               + '<span style="outline:1px dashed #999">wykryte bez podmiany</span><span style="background:#ff8a8a">alarm kontroli</span>')

    if kontrola["status"] == "ok":
        status = '<span class="status ok">Kontrola wycieku: brak trafień</span>'
    elif kontrola["status"] == "do_przegladu":
        status = f'<span class="status zle">Kontrola wycieku: {len(alarmy)} do przeglądu</span>'
    else:
        status = '<span class="status uwaga">Kontrola wycieku: nie uruchomiona</span>'

    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>{html.escape(tytul)}</title><style>{STYL}</style>
<script>addEventListener("hashchange",()=>{{document.querySelectorAll(".cel").forEach(e=>e.classList.remove("cel"));
const e=document.getElementById(location.hash.slice(1));if(e)e.classList.add("cel");}});</script></head><body>
<h1>{html.escape(tytul)}</h1>
<p>{status} &nbsp; Podmian: {len(podmiany)} ({", ".join(f"{t}: {n}" for t, n in liczniki.most_common())}).</p>
<div class="przeglad">
<h2>1. Kontrola wycieku</h2>
{f"<ul>{''.join(alarmy)}</ul><p>Każde trafienie to oryginał z mapy sesji albo numer, który został w tekście zanonimizowanym. Popraw przed wysyłką.</p>" if alarmy else "<p>Żaden oryginał z mapy sesji ani niepodmieniony numer nie występuje w tekście zanonimizowanym. Kontrola nie widzi nazw, których nie wykrył żaden detektor: przejrzyj punkty 2 do 4.</p>"}
<h2>2. Sporne: głosy modelu podzielone ({len(sporne)})</h2>
{f"<table><tr><th>nazwa</th><th>kategoria większości</th><th>co się stało</th></tr>{''.join(sporne)}</table>" if sporne else "<p>Brak.</p>"}
<h2>3. Zostawione bez zmian ({len(zostawione)})</h2>
<p>Sprawdź, czy żadna z tych nazw nie jest nazwą firmy, osoby albo produktu. Miejscowości w nich są już podmienione.</p>
{f"<table><tr><th>kategoria</th><th>nazwy</th></tr>{wiersze_zost}</table>" if zostawione else "<p>Brak.</p>"}
<h2>4. Wykryte, ale bez podmiany ({len(bez)})</h2>
{f"<table><tr><th>fragment</th><th>typ</th><th>powód</th></tr>{''.join(bez)}</table>" if bez else "<p>Brak.</p>"}
{sekcja_ocr}
</div>
<p class="leg">{legenda}</p>
<p>Najedź na zaznaczenie, żeby zobaczyć drugą stronę podmiany.</p>
<div class="kol"><div><h3>Oryginał</h3>{_zaznacz(oryginal, lewe)}</div><div><h3>Wersja zanonimizowana</h3>{_zaznacz(anon, prawe)}</div></div>
<h2>Tabela podmian</h2>
<table><tr><th>typ</th><th>oryginał</th><th>surogat</th></tr>{wiersze_map}</table>
</body></html>"""

"""Lokalny raport porównawczy HTML: oryginał obok wersji zanonimizowanej, podmiany podświetlone.
Raport zawiera dane oryginalne, więc nie może opuścić maszyny."""
import html
from collections import Counter

KOLORY = {"OSOBA": "#ffd6a5", "FIRMA": "#caffbf", "NAZWA": "#bde0fe", "MIEJSCE": "#e2c6ff", "ADRES": "#fdffb6"}
STYL = """body{font:14px/1.5 system-ui,sans-serif;margin:16px;color:#111;background:#fff}
h1{font-size:18px} .kol{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.kol>div{white-space:pre-wrap;word-break:break-word;border:1px solid #ccc;padding:12px;border-radius:6px}
mark{padding:0 2px;border-radius:3px} table{border-collapse:collapse;margin-top:16px}
td,th{border:1px solid #ccc;padding:3px 8px;text-align:left;font-size:13px} .leg span{padding:2px 6px;margin-right:6px;border-radius:3px}"""


def _zaznacz(tekst: str, zakresy: list[tuple[int, int, str, str]]) -> str:
    out, pos = [], 0
    for a, b, typ, dymek in zakresy:
        out.append(html.escape(tekst[pos:a]))
        out.append(f'<mark style="background:{KOLORY.get(typ, "#ddd")}" title="{html.escape(typ + ": " + dymek)}">{html.escape(tekst[a:b])}</mark>')
        pos = b
    out.append(html.escape(tekst[pos:]))
    return "".join(out)


def zbuduj(tytul: str, oryginal: str, wynik: dict) -> str:
    podmiany = sorted(wynik["podmiany"], key=lambda p: p["start"])
    lewe, prawe, przes = [], [], 0
    for p in podmiany:
        lewe.append((p["start"], p["end"], p["typ"], p["surogat"]))
        a = p["start"] + przes
        prawe.append((a, a + len(p["surogat"]), p["typ"], p["oryginal"]))
        przes += len(p["surogat"]) - (p["end"] - p["start"])
    liczniki = Counter(p["typ"] for p in podmiany)
    unikalne = sorted({(p["typ"], p["oryginal"], p["surogat"]) for p in podmiany})
    wiersze = "".join(f"<tr><td>{html.escape(t)}</td><td>{html.escape(o)}</td><td>{html.escape(s)}</td></tr>" for t, o, s in unikalne)
    odrz = ", ".join(html.escape(x) for x in wynik.get("odrzucone_jako_ogolne", [])) or "brak"
    bez = ", ".join(html.escape(f'{p["typ"]}: {p["tekst"]}') for p in wynik.get("pominiete", [])) or "brak"
    legenda = "".join(f'<span style="background:{k}">{t}</span>' for t, k in KOLORY.items()) + '<span style="background:#ddd">numery</span>'
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>{html.escape(tytul)}</title><style>{STYL}</style></head><body>
<h1>{html.escape(tytul)}</h1>
<p>Podmian: {len(podmiany)} ({", ".join(f"{t}: {n}" for t, n in liczniki.most_common())}). Najedź na zaznaczenie, żeby zobaczyć drugą stronę podmiany.</p>
<p class="leg">{legenda}</p>
<div class="kol"><div>{_zaznacz(oryginal, lewe)}</div><div>{_zaznacz(wynik["tekst"], prawe)}</div></div>
<p><b>Wykryte, ale bez podmiany:</b> {bez}</p>
<p><b>Odrzucone jako określenia ogólne (ocena LLM):</b> {odrz}</p>
<table><tr><th>typ</th><th>oryginał</th><th>surogat</th></tr>{wiersze}</table>
</body></html>"""

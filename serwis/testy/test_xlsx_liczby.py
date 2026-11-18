"""XLSX (PRZEKAZANIE 2.00.17 i 2.00.18): liczba opisana etykietą na lewo albo nagłówkiem kolumny („PESEL”, „NIP”,
„Nr REGON”, „telefon”) jest podmieniana, każda inna komórka liczbowa zostaje bez zmian. Dane fikcyjne.
Uruchomienie: docker exec -w /srv -e PYTHONPATH=/srv anonimizator python testy/test_xlsx_liczby.py"""
import io, zipfile
from app import pliki
from app.anonimizacja.sesja import Sesja
from app.ewaluacja.pliki import _liczby_xlsx
M = pliki.fxlsx.M; R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
s = lambda r, t: f'<c r="{r}" t="inlineStr"><is><t>{t}</t></is></c>'
n = lambda r, v: f'<c r="{r}"><v>{v}</v></c>'
wiersze = [s("A1","Imię i nazwisko")+s("B1","PESEL")+s("C1","Kwota"),
           s("A2","Jan Testowy")+n("B2","93052549633")+n("C2","5846254620"),
           s("A3","Anna Próbna")+n("B3","2270812346")+n("C3","1234563218"),
           s("A4","Ewa Fikcyjna")+n("B4","8.501011234E+10")+n("C4","123456785"),
           s("A6","NIP")+n("B6","1234563218")+n("C6","5846254620"),
           s("A7","Nr REGON")+n("B7","123456785")+s("C7","telefon")+n("D7","601234567")]
czesci = {"[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
 "_rels/.rels": f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
 "xl/workbook.xml": f'<?xml version="1.0"?><workbook xmlns="{M}" xmlns:r="{R}"><sheets><sheet name="A" sheetId="1" r:id="rId1"/></sheets></workbook>',
 "xl/_rels/workbook.xml.rels": f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
 "xl/worksheets/sheet1.xml": f'<?xml version="1.0"?><worksheet xmlns="{M}"><sheetData>' + "".join(f'<row r="{i}">{w}</row>' for i, w in zip([1,2,3,4,6,7], wiersze)) + '</sheetData></worksheet>'}
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as z:
    for k, v in czesci.items(): z.writestr(k, v)
dane = b.getvalue()
p = pliki.otworz("xlsx", dane)
assert sorted(t for t, _ in p.typy_wymuszone.values()) == ["NIP", "PESEL", "PESEL", "PESEL", "REGON", "TELEFON"], p.typy_wymuszone
wy, w = pliki.anonimizuj_plik(Sesja(sciezka=":memory:", nowe_id="t"), "t.xlsx", dane, weryfikuj=False)
assert len([x for x in w["podmiany"] if x["typ"] in ("PESEL", "NIP", "REGON", "TELEFON")]) == 6
assert w["kontrola_pliku"]["status"] == "ok", w["kontrola_pliku"]
assert _liczby_xlsx(wy) == _liczby_xlsx(dane) and len(_liczby_xlsx(wy)) == 4
print("ok")

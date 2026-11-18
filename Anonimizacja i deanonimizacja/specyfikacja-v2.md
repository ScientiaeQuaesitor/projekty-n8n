# Anonimizacja i deanonimizacja v2: specyfikacja i plan wdrożenia

Stan na 2026-11-16. Dokument zastępuje podejście z v1 (`workflow.json`, `zrodla/`). V1 zostaje tylko jako materiał referencyjny, nie jest bazą dla v2.

## 1. Cel

1.1. Przetwarzać dokumenty zewnętrznymi modelami AI tak, żeby żadne dane identyfikujące osoby i firmy nie opuszczały maszyny lokalnej.
1.2. Różne typy dokumentów mają różne polecenia przetwarzania.
1.3. Priorytet: jakość anonimizacji przed szybkością. Przetwarzanie długich skanów może trwać kilkadziesiąt minut, ale nie powinno być zadaniem nocnym.

## 2. Ustalone decyzje

2.1. Surogaty zamiast placeholderów: „Jan Kowalski” staje się inną, fikcyjną osobą o regularnej polskiej odmianie, a nie `[NAME_1]`.
2.2. Pełna odmiana surogatów i oryginałów przez Morfeusz2, lokalny LLM tylko jako fallback.
2.3. Wszystkie nazwy własne wykrywa model, bez słowników klienta.
2.4. Architektura: n8n jako orkiestrator, logika NLP w serwisach Python w Dockerze (wariant B).
2.5. OCR i analiza układu: Docling.
2.6. Tryby pracy budowane kolejno na jednym rdzeniu: A (dwa kroki), potem B (chatbot), potem C (wsad).
2.7. Sesja to „sprawa”: może zawierać wiele dokumentów i ma jedną wspólną mapę surogatów.
2.8. Jeden użytkownik, bez uprawnień i kont.
2.9. Wejście: PDF cyfrowy, PDF skan, DOCX. Później także XLSX i XML (zgłoszone 2026-11-17, PLAN 4.9).
2.10. Wyjście zanonimizowane zachowuje typ pliku i układ:
2.10.1. PDF cyfrowy: podmiana w miejscu (PyMuPDF).
2.10.2. DOCX: podmiana w miejscu (python-docx).
2.10.3. Skan: dokument odtworzony z Doclinga (struktura, nie wygląd), bez pikseli oryginału.
2.11. Logo, pieczątki, obrazy podpisów i metadane plików są usuwane.
2.12. Do każdego dokumentu powstaje lokalny raport porównawczy HTML (oryginał obok wersji zanonimizowanej, podmiany podświetlone, tabela mapowań).
2.13. Plik przechodzi tylko w jedną stronę (oryginał → wersja zanonimizowana). Deanonimizowane są wyłącznie wyniki pracy, czyli tekst.

## 3. Ograniczenia sprzętowe

3.1. 16 GB RAM, 8 GB VRAM.
3.2. LLM lokalny: klasa 7 do 8B w kwantyzacji Q4.
3.3. Docling i LLM nie korzystają z GPU jednocześnie. Zadania ciężkie idą przez kolejkę, jedno naraz.
3.4. Liczba kontenerów ma być minimalna.

## 4. Komponenty

4.1. `n8n` (istniejący kontener `n8n-training`, port 5686): triggery, routing, kolejka zadań, obsługa błędów, interfejs użytkownika (formularze, później czat), wywołania zewnętrznego modelu.
4.2. `anonimizator` (nowy serwis, Python, FastAPI): cała logika anonimizacji i deanonimizacji.
4.2.1. NER klasyczny (spaCy `pl_core_news_lg` lub model HerBERT, do rozstrzygnięcia w etapie 1).
4.2.2. Morfeusz2: lematyzacja, rozpoznanie przypadka, generowanie form.
4.2.3. PyMuPDF i python-docx: podmiana w plikach, czyszczenie metadanych i obrazów.
4.2.4. Baza SQLite na wolumenie: sesje, encje, mapy surogatów, zadania, log audytowy.
4.2.5. Pula surogatów z tabelami odmiany (pliki danych w repozytorium serwisu).
4.3. `docling` (istniejący kontener `docling-serve-cpu` z projektu compose `training-mateusz`, adres w sieci: `http://docling:5001`): ekstrakcja tekstu i struktury, OCR skanów. Wersja CPU, więc nie konkuruje z LLM o VRAM.
4.4. Ollama (zainstalowana natywnie na hoście, z kontenerów pod `http://host.docker.internal:11434`): lokalny LLM do uzupełniania detekcji, klastrowania wariantów i fallbacku odmiany.
4.5. `anonimizator` ma własny compose w `serwis/docker-compose.yml` i dołącza do sieci `training-mateusz_default`. Z n8n: `http://anonimizator:8000`, z hosta: `http://127.0.0.1:8090`.
4.5.1. ZMIANA 2026-11-17 (zastępuje 4.1, 4.3 i 4.5 w części o sieci): projekt ma własny stos compose `anonimizacja` w `serwis/docker-compose.yml`: `anonimizator`, własne n8n `anonimizacja-n8n` pod `http://127.0.0.1:5687` z bazą Postgres i własny Docling. Stos nie zależy od `training-mateusz` (n8n 5686 bez zmian). Workflowy projektu działają na 5687 (serwer MCP `n8n-anonimizacja`).
4.6. Docker ma limit 7,6 GB RAM na wszystkie kontenery (n8n, Postgres, Qdrant, Docling, anonimizator).

### Stan etapu 0 (2026-11-16): zakończony

`GET /zdrowie` zwraca `ok: true` dla bazy, Doclinga i Ollamy, zarówno z kontenera n8n, jak i z hosta.

### Stan etapu 1 (2026-11-16): zakończony

Decyzja: detekcja to regex + spaCy `pl_core_news_lg` + FastPDN + LLM `gemma4:e4b`. Model LLM pozostaje parametrem `LLM_MODEL`.

Pełne wyniki: `serwis/testy/wyniki/etap1.md` i `etap1.json`. Zestaw: 6 syntetycznych dokumentów tekstowych, 12,8 tys. znaków, 218 encji wzorcowych. Pomiar powtarza komenda `docker compose exec anonimizator python -m app.ewaluacja.uruchom --llm gemma4:e4b` w katalogu `serwis`.

| konfiguracja | pełne pokrycie | częściowe | brak | nadmiar | czas |
|---|---|---|---|---|---|
| regex + spaCy + FastPDN + gemma4:e4b | 98,6% | 3 | 0 | 29 | 120 s |
| regex + FastPDN + gemma4:e4b | 97,7% | 3 | 2 | 13 | 120 s |
| regex + spaCy + FastPDN | 95,9% | 9 | 0 | 30 | 3 s |
| regex + FastPDN | 90,4% | 17 | 4 | 14 | 3 s |
| regex + spaCy | 86,7% | 18 | 11 | 20 | 0,3 s |

Porównanie LLM (drugi przebieg, kontekst 4096 tokenów, w konfiguracji regex + spaCy + FastPDN + LLM):

| model | pełne pokrycie | częściowe | brak | nadmiar | czas | VRAM |
|---|---|---|---|---|---|---|
| SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 99,5% | 1 | 0 | 20 | 349 s | 81% GPU, 19% CPU |
| gemma4:e4b | 99,1% | 2 | 0 | 29 | 115 s | całość na GPU (3,3 GB) |

Bielik jest o jedną encję lepszy i trzy razy wolniejszy, bo nie mieści się w 8 GB VRAM. Różnica jakości jest w granicach szumu przy 218 encjach.

Wnioski:
1. spaCy i FastPDN uzupełniają się (spaCy lepszy w osobach, FastPDN w firmach i nazwach produktów), więc zostają oba.
2. Regexy pokrywają 100% numerów, e-maili, telefonów i sygnatur z zestawu.
3. LLM domyka głównie formy prawne („Sp. z o.o.”) i nazwy produktów, ale kosztuje około 17 s na stronę. Sam LLM jest słaby (63%).
4. Trzy pozostałe częściowe pokrycia to pojedyncze łączniki wewnątrz encji („w”, „–”). Do rozwiązania regułą scalania sąsiednich zakresów w etapie 2.
5. Ograniczenie pomiaru: zestaw jest mały i napisany przez autora detektorów. Ostateczna ocena wymaga prawdziwych dokumentów.

### Stan etapu 2 (2026-11-16): zakończony na zestawie wzorcowym

Wynik pełnego obiegu (`serwis/testy/wyniki/etap2_obieg.md`, pomiar: `docker compose exec anonimizator python -m app.ewaluacja.obieg`): 6 dokumentów, 217 podmian, 0 wycieków, 0 różnic po deanonimizacji, 0 miejsc niepewnych. Dodatkowy test ręczny: odpowiedź z surogatami w przypadkach niewystępujących w oryginale wraca poprawnie dla osób, miejscowości i numerów; nazwa firmy spoza słownika w miejscowniku („Stalmetie” zamiast „Stalmecie”) wraca błędnie, ale trafia na listę niepewnych.

Kod: `serwis/app/anonimizacja/` (`pule.py` surogaty i zdrobnienia, `sesja.py` mapa w SQLite, `gram.py` wybór przypadka, `osoby.py`, `nazwy.py`, `adresy.py`, `numery.py`, `silnik.py`). API: `POST /sesje`, `POST /sesje/{id}/anonimizuj-tekst`, `POST /sesje/{id}/deanonimizuj-tekst`, `GET /sesje/{id}/mapa`.

Zmiany względem projektu poniżej:
1. Typ encji ustala LLM, a NER tylko gdy LLM zakresu nie wskazał. NER oznaczał tę samą firmę raz jako firmę, raz jako osobę lub miejscowość. Dodatkowo ta sama nazwa dostaje jeden typ we wszystkich wystąpieniach (głosowanie).
2. Zdrobnienia: słownik około 70 imion, pula surogatów złożona z par imię i zdrobnienie („Katarzyna” i „Kasia” dają „Krystyna” i „Krysia”).
3. Nazwa skrócona firmy („Stalmet”) i pełna („Stalmet Śląsk”) mają wspólny surogat, a pełna dostaje dodatkowy człon („Pravon” i „Pravon Trade”), żeby dało się je rozróżnić przy powrocie.

Znane ograniczenia po etapie 2:
1. Wynik 0 różnic dotyczy tekstu, który nie został zmieniony przez zewnętrzny model. Reguły stroiłem na tym samym zestawie, na którym mierzę.
2. Nazwy firm spoza słownika w przypadkach niewidzianych w dokumencie są odmieniane regułą i bywają błędne (lista niepewnych). Do rozważenia fallback LLM.
3. Skrótowiec i pełna nazwa tej samej firmy („PPH Orzeł” i „Przedsiębiorstwo Produkcyjno-Handlowe Orzeł”) dostają różne surogaty.
4. Firma o nazwie w liczbie mnogiej lub rodzaju nijakim dostaje surogat męski, więc czasowniki w tekście zanonimizowanym mogą się nie zgadzać.
5. Przyimek nie jest dopasowywany do surogatu („we Wrocławiu” daje „we Tarnowie”).
6. Zakres wykryty przez model nie może przechodzić przez koniec wiersza. W tekście z PDF z łamaniem wierszy w środku nazwy trzeba będzie to obsłużyć w etapie 3.
7. Kontrola wycieku przez ponowną detekcję na tekście wynikowym (punkt 7.10) jest zaplanowana na etap 3, razem z plikami.

### Test na prawdziwym dokumencie (2026-11-16): akt notarialny, skan

Pliki lokalne w `serwis/testy/prawdziwe/` (poza obrazem Dockera): `akt_notarialny.pdf`, `akt.md` (tekst z Doclinga), `akt_anon.md`, `akt_raport.html` (raport porównawczy), `akt_raport.json`. Docling CPU: 68 s na dokument, 14,4 tys. znaków. Detekcja z LLM: 77 s. Wynik końcowy: 123 podmiany, 2 różnice po obiegu, 0 awarii.

Błędy, których zestaw wzorcowy nie pokazał, i wprowadzone poprawki:
1. Wyczerpanie puli miast i awaria. Poprawka: generator nazw zapasowych, pula imion bez pary.
2. NER oznaczał jako nazwy pojęcia prawne („Stawający”, „Nieruchomość Wspólna”, „Akt notarialny”, nazwy ustaw). Poprawki: weryfikacja przez LLM zakresów wskazanych tylko przez NER i złożonych ze zwykłych słów (`silnik.odsiej_ogolne`), rozpoznawanie terminów zdefiniowanych zwrotem „zwany dalej”, lista słownictwa aktów i umów.
3. Podmieniane były kwoty i odwołania do przepisów. Poprawka: zakresy chronione (`RX_CHRONIONE` w `scal.py`): art., ust., Dz.U., akty UE, kwoty, powierzchnie.
4. OCR gubi polskie znaki („legitymujacy”, „Stawajacych”), a słowo spoza słownika wyglądało jak nazwisko. Poprawka: `morf.z_ogonkami` przywraca znaki i rozpoznaje wyraz pospolity albo nazwę („Wroclawiu”).
5. Imię dwuznaczne („Romana”: kobieta w mianowniku albo mężczyzna w dopełniaczu) na początku pozycji listy dostawało płeć męską. Poprawka: mianownik domyślny na początku wiersza.
6. LLM pomijał numery repertorium i działek w dalszej części dokumentu. Poprawka: regex dla numerów z ukośnikiem w kontekście słów „numer”, „działka”, „Rep. A”.

Otwarte po tym teście:
1. Nazwisko dwuczłonowe przełamane między wierszami dostaje inny surogat niż w pozostałych miejscach.
2. Trzy liczby z ukośnikiem zostały bez podmiany (do oceny w raporcie, czy to identyfikatory).
3. Pełnej oceny wycieków nie da się zrobić automatycznie bez wzorca. Wymaga przejrzenia `akt_raport.html` przez człowieka.
4. Reguły były strojone na jednym akcie. Kolejny typ dokumentu pokaże kolejne błędy tego rodzaju.

### Poprawki po przeglądzie raportu przez użytkownika (2026-11-16)

Zasada przyjęta po uwagach: tekst zanonimizowany ma zachować sens. Nazwy ogólne zostają, podmieniane są tylko człony identyfikujące.

1. Nazwy opisowe (`nazwy._opisowa`, lista `GLOWY_OPISOWE`): zostaje część ogólna, podmieniane są imiona, nazwiska, miejscowości i słowa spoza słownika. „Kancelarii Notarialnej we Wrocławiu” daje „Kancelarii Notarialnej we Toruniu”, „Rada Miejska Wrocławia” daje „Rada Miejska Sanoka”, „Baza Danych Ksiąg Wieczystych” zostaje bez zmian.
2. Nazwy ustaw, kodeksów, rozporządzeń, kategorie prawne: zakres bez potwierdzenia LLM, złożony ze zwykłych słów, ocenia LLM z kontekstem (`silnik.watpliwe_ogolne`). Reguła bez pytania LLM („same słowa pospolite, więc zostaje”) została odrzucona, bo na zestawie wzorcowym dała 16 wycieków: nazwy firmy i pojęcia ogólnego nie da się rozróżnić po samej formie.
3. Zakres zaczynający się małą literą i wskazany tylko przez NER nie jest podmieniany.
4. Daty, numery wewnętrzne („załącznik numer 2”) i liczby poniżej pięciu cyfr bez ukośnika nie są podmieniane.
5. Dwa imiona („Jan Paweł”) są rozpoznawane jako imiona, a nieznane słowo tuż po osobie oznaczone jako miejsce jest traktowane jak nazwisko.
6. Klasa słowa (`morf.rodzaj_slowa`) jest ustalana po wielkości litery lematu. Morfeusz dopasowuje małe litery także do nazw własnych, więc analiza formy pisanej małą literą nic nie rozstrzyga.

OCR skanów (`serwis/app/ekstrakcja.py`, pomiar `python -m app.ewaluacja.ocr plik.pdf`): OCRmyPDF z Tesseractem i modelem polskim tworzy warstwę tekstową, Docling bez własnego OCR i bez rozpoznawania tabel ustala układ. Porównanie na akcie (miary zastępcze, bez wzorca):

| wariant | czas | słów | słowa znane słownikowi | ogonki na 1000 liter |
|---|---|---|---|---|
| Docling auto (RapidOCR), poprzedni | 68 s | 1619 | 91,7% | 55,2 |
| Docling EasyOCR pl | 117 s | 1587 | 93,6% | 60,9 |
| Tesseract pol + Docling (wybrany) | 49 s | 1836 | 95,2% | 62,5 |
| Tesseract pol_best | 42 s | 1872 | 91,5% | 58,9 |

Ograniczenia OCR: strony aktu mają około 170 dpi (1409 x 2048 px), co ogranicza każdy silnik. Tesseract czyta tekst ciągły wyraźnie lepiej, ale blok danych jednej ze stron odczytał gorzej niż EasyOCR. Do sprawdzenia: skan w 300 dpi, połączenie dwóch silników, OCR modelem wizyjnym.

Pełny przebieg na pliku: `python -m app.ewaluacja.dokument /srv/testy/prawdziwe/plik.pdf [--od-nowa]`. Wynik na akcie po poprawkach: 120 podmian, 0 różnic po obiegu.

### OCR dwusilnikowy i testy trwałe (2026-11-16)

Zasada systemowa: błąd znaleziony na prawdziwym dokumencie jest naprawiany mechanizmem ogólnym i dostaje test w zestawie wzorcowym, a nie poprawkę pod ten jeden plik.

OCR skanów (`serwis/app/ocr.py`, wywoływany z `ekstrakcja.tekst_z_pdf`):
1. Strona jest renderowana do szerokości 2480 px (A4 w 300 dpi), także gdy skan ma niższą rozdzielczość.
2. Tesseract (model polski) czyta stronę i wyznacza układ: bloki, akapity, wiersze.
3. Każdy wiersz dostaje ocenę niezależną od silnika (`ocr.ocen`): udział słów znanych słownikowi Morfeusza, liczby i identyfikatory, premia za numer z poprawną sumą kontrolną.
4. Jeśli strona ma słabe wiersze, czyta ją też EasyOCR. W każdym wierszu wygrywa lepszy odczyt. Numer z poprawną sumą kontrolną wygrywa bezwarunkowo. Odczyt, który zgubił treść, nie wygrywa.
5. Wiersze, których Tesseract nie odczytał wcale, są dodawane z drugiego silnika.
6. Wiersze są łączone w akapity. Przeniesienie wyrazu jest sklejane, a nazwisko dwuczłonowe przełamane między wierszami zachowuje łącznik. Wypełniacze wierszy (kreski) i resztki po nich są usuwane.
7. Raport jakości (bez treści dokumentu): liczba wierszy, zamienionych, niepewnych, szacowane dpi i ocena „dobra”, „średnia” albo „słaba”. Wiersze niepewne mają numery stron i pozycji.

Wynik na akcie (5 stron, około 170 dpi):

| wariant | czas | słowa znane słownikowi | wiersze niepewne | PESEL z poprawną sumą |
|---|---|---|---|---|
| Docling auto, pierwszy przebieg | 68 s | 91,7% | nie mierzono | 4 |
| sam Tesseract | 28 s | 95,7% | 12 z 231 | 2 |
| Tesseract + EasyOCR (wybrany) | 134 s | 98,4% | 4 z 232 | 4 |

Testy trwałe: znacznik `{{ZOSTAW|…}}` w zestawie wzorcowym oznacza fragment, którego anonimizacja nie może zmienić. Pomiar obiegu ma nową kolumnę „zepsute”. Dokument `07_akt_notarialny.txt` (dane fikcyjne) koduje wszystkie uwagi z przeglądu aktu: nazwy opisowe, ustawy i kodeksy, terminy zdefiniowane, daty, kwoty, numery wewnętrzne, ułamek udziału, podwójne imię, imię dwuznaczne co do płci. Stan: 7 dokumentów, 260 podmian, 0 wycieków, 0 zepsutych, 0 różnic po obiegu.

Ograniczenia: koszt czasu około 27 s na stronę na CPU (300 stron to ponad 2 godziny). Ocena słownikowa nie wykrywa błędu w nazwisku ani w cyfrze bez sumy kontrolnej. Układ wielokolumnowy i tabele w skanach nie były testowane. Tekst ze skanu nie ma już nagłówków Markdown z Doclinga.

### Polityka kategorii zamiast list pojęć (2026-11-16, wieczór)

Bieżący stan pracy i pierwsze kroki dla następnej sesji: `PRZEKAZANIE.md`.

Wymaganie: żadnych list pojęć w kodzie. Ogólne nazwy własne (ustawa, kodeks, rodzaj dokumentu lub orzeczenia, sąd, organ publiczny) zostają, podmieniane są tylko dane identyfikujące strony.

1. LLM przypisuje każdej wykrytej nazwie kategorię z kontekstu: OSOBA, FIRMA, PRODUKT, MIEJSCE (podmiana) albo INSTYTUCJA, AKT_PRAWNY, DOKUMENT, POJECIE (zostaje).
2. Dla kategorii „zostaje” zwykłe słowa zostają, a człony własne (imię, nazwisko, miejscowość, słowo spoza słownika) są podmieniane: „Sąd Rejonowy w Gliwicach” daje „Sąd Rejonowy w Radomiu”. Błędna ocena kategorii może zostawić tylko wyrazy pospolite.
3. Bez klasyfikacji, zawsze podmiana: firma z formą prawną oraz zakres osobowy zawierający słowo znane słownikowi jako imię lub nazwisko.
4. Kategorię ustala głosowanie trzech wariantów pytania. Powód: pojedyncza ocena modelu 8B była niestabilna. Wariant „lista” przechodził zestaw wzorcowy, ale na akcie uznawał radę miejską i sąd za firmy. Wariant „uzasadnienie” działał na akcie, ale na zestawie dał 5 wycieków i 3 zepsute fragmenty.
5. Reguła „zakres ze zwykłych słów bez potwierdzenia LLM zostaje” (bez pytania modelu) była próbowana i odrzucona: 16 wycieków na zestawie.

Pomiary: zestaw wzorcowy z głosowaniem i gemmą 261 podmian, 0 wycieków, 0 zepsutych, 0 różnic (356 s klasyfikacji od zera). `qwen3-vl:8b` w roli klasyfikatora: 7 wycieków, 2 zepsute, 564 s. Akt z głosowaniem nie został jeszcze zmierzony.

### Etap 3 i początek etapu 4 (2026-11-17/18, praca samodzielna)

Szczegóły: `PRZEKAZANIE.md` 2.00, commity `ce3e823` do `7e36aab`.

1. Faza B (tekst): skrótowiec i formy jednej firmy z jednym surogatem (grupa odmienna z jednym rzeczownikiem, alias skrótowca, wspólna kategoria firma/produkt; nowa miara „niespójne” ze znacznikiem `{{TYP#grupa|…}}`), surogat w liczbie i rodzaju oryginału („Tarvony”, „Tarvono”), odmiana nazw spoza słownika z wymianami spółgłosek („Stalmecie”, test 19 nazw), sądy we wzorcach jako `ZOSTAW` z miejscowością.
2. Model pośredni dokumentu: tekst ciągły z mapą każdego znaku do kawałka pliku (DOCX: element `w:t` lub kod pola; PDF: wiersz). Wiersze akapitu PDF sklejone, przeniesienia rozwinięte (dywiz jako znak ukryty), więc nazwa przełamana między wierszami jest jednym zakresem (zamyka PLAN 3.7 dla PDF cyfrowego). Podmiana nazwy, w której część słów zostaje, zmienia w pliku tylko różniące się słowa.
3. DOCX: czyszczenie przed odczytem tekstu (zmiany śledzone przyjęte, komentarze, obrazy, osadzone obiekty, hiperłącza zewnętrzne, metadane, zmienne dokumentu, customXml), dzięki czemu detekcja widzi dokładnie to, co zostaje w pliku. PDF: redakcja wąskim pasem wokół linii bazowej, surogat w miejscu oryginału, nigdy poza nim (ściskanie, potem mniejsza czcionka), usunięte obrazy, adnotacje, łącza, formularze, załączniki, zakładki, XMP.
4. Kontrola wycieku na pliku (7.10): zgodność tekstu pliku z tekstem zanonimizowanym, bezpiecznik na całym pliku, brak obrazów i załączników. Ponowny NER zastąpiony porównaniem tekstu (przy zgodności dałby ten sam wynik co detekcja na tekście). Kontrola wykryła w pierwszej wersji PDF nakładanie się dłuższego surogatu na następne słowo; po poprawce 0 różnic.
5. Kolejka zadań w SQLite (dokument, zadanie, audyt bez treści), jeden wątek roboczy, wznowienie po restarcie; API z punktu 9 zrealizowane, plik „do przeglądu” nie jest wydawany (409).
6. Workflow n8n „Anonimizuj dokument” (10.1.1) w instancji 5687.

Wyniki: zestaw plikowy 7 DOCX + 7 PDF × 3 sesje: 0 wycieków, 0 alarmów kontroli, 0 różnic tekstu pliku, wszystkie pliki się otwierają; zepsute wyłącznie z niestabilności klasyfikacji. Zestaw tekstowy bez zmian (270 podmian, 0 wycieków, 1 zepsute, 0 różnic, 0 niespójnych). Czas zadania API dla fikcyjnego DOCX (4 strony tekstu): 72 s, w tym detekcja 33 s i klasyfikacja 39 s.

Etap 5 (skany), częściowo: skan przez API daje DOCX odtworzony z akapitów OCR z kontrolą pliku (2.10.3; OCR własny, nie Docling), raport skanu ma obrazy stron. Skany wzorcowe (`ewaluacja.skany`, 170 i 120 DPI z szumem): CER 0,1 do 2,8%, po regule adresów e-mail przekłamanych przez OCR 0 wycieków, także z jednym błędem znaku. Raport jakości OCR liczy wiersze z numerem o błędnej sumie kontrolnej jako niepewne (miara słownikowa ich nie widziała). Tabela i dwie kolumny w skanie czytane poprawnie; sklejone wiersze tabeli nie mogą już wciągać imienia do adresu. Przyimek przed podmienioną nazwą dopasowany do nagłosu w obu kierunkach.

Otwarte: zapis oryginału w danych wykonań n8n (PLAN 5.4), workflow błędów (5.3), test na prawdziwym DOCX lub PDF cyfrowym, odtworzenie dokumentu ze skanu (faza E), XLSX i XML (4.9).

### Domknięcie etapu 2 (2026-11-17)

Szczegóły i historia zmian: `PRZEKAZANIE.md` 5.15 do 5.20 i 5.2, 5.3; repozytorium Git w katalogu projektu (od 2026-11-17).

1. Pomiar powtarzalny. Surogaty losuje ziarno sesji, więc jeden przebieg zestawu nie dowodzi poprawności (2 z 12 przebiegów miały kolizję surogatów). Pomiar `obieg` liczy każdy wzorzec na 200 sesjach o stałych id (`wzorzec-0…199`), około 1,5 min przy zapamiętanych ocenach.
2. Kolizje surogatów usunięte: surogat numeru i numeru domu nie może wystąpić w tekście oryginału ani powtórzyć innego surogatu sesji; osoby o tym samym nazwisku i różnym inicjale nie dostają surogatów imion i inicjałów na tę samą literę. Wynik: 0 błędów na 1000 sesjach.
3. Pamięć ocen klasyfikacji z odciskiem promptu, wariantu, opcji i modelu; zapis po każdej paczce zapytań, więc przerwany pomiar wznawia się bez powtórnych pytań. Czasy faz w wyniku (`czasy`).
4. Nazwy ogólne (zasada użytkownika: akty prawne, ich numery, nazwy ustaw, ministerstw i inne nazwy ogólne nigdy się nie zmieniają): numer aktu w układzie rok/numer chroniony jak „Dz. U.”, zakres pisany małymi literami nie jest nazwą własną, prompt odróżnia nazwę wybraną przez właściciela (FIRMA) od określenia rodzaju podmiotu z miejscowością (INSTYTUCJA, POJECIE), przy podzielonych głosach nazwa z samych wyrazów pospolitych zostaje. Reguła „każda nazwa ze zwykłych słów zostaje” odrzucona: wyciekały nazwy firm i miejscowości będące zwykłymi słowami.
5. Bezpiecznik wycieku na tekście (wcześniejsza część 7.10): oryginały z mapy sesji szukane dosłownie w wyniku i ponowna detekcja numerów regexami, pole `kontrola` ze statusem `ok` albo `do_przegladu`. Test wstrzykiwania: 269 z 269 cofniętych podmian złapanych; od razu wykrył prawdziwy wyciek miejscowości w nazwie sądu.
6. Głosowanie etapowe: dwa warianty zawsze, trzeci przy niezgodzie kategorii i zawsze dla budowy opisowej; decyzje identyczne z pełnym głosowaniem, trzeci głos potrzebny dla około 70% nazw. Remis kategorii rozstrzyga wcześniejszy wariant (wcześniej wynik zależał od kolejności haszy w procesie).
7. Inny model jako głos: Bielik 11B v3 nie poprawia trafności (najlepsza trójka z nim zamienia jeden błąd szumu na wyciek) i jest 5 razy wolniejszy. Gemma 4 e4b zostaje jedynym klasyfikatorem. Model 8B przy temperaturze 0 zmienia około 3% ocen między uruchomieniami; głosowanie, reguły i bezpiecznik ograniczają skutki, nie usuwają przyczyny.
8. Surogat miejscowości z tej samej klasy nagłosu co oryginał (koniec „we Elblągu”).

Wyniki: zestaw wzorcowy (7 dokumentów, 269 podmian, 200 sesji) 0 wycieków, 0 różnic po obiegu, 0 fałszywych alarmów kontroli, 1 fragment zepsuty („Portalu Podsystemu Dostępu do Bazy Danych Ksiąg Wieczystych”, niestabilna ocena modelu). Akt notarialny (skan, 13 tys. znaków): 119 podmian, 0 różnic po obiegu, kontrola `ok`, wszystkie pojęcia ogólne zgłoszone przez użytkownika bez zmian, wynik identyczny w kolejnych uruchomieniach; klasyfikacja 47 nazw od zera około 3 min (lista 29 s, uzasadnienie 59 s, pojedynczo 106 s).

Otwarte po etapie 2: nazwy sądów we wzorcach oznaczone w całości jako firma (do zmiany na sąd zostaje, miejscowość podmieniana), niestabilność klasyfikacji nazw złożonych ze zwykłych słów, raport HTML do szybkiego przeglądu (PLAN 3.2).

### Etap 2, część 1: scalanie i Morfeusz

Część 1: scalanie zakresów (`serwis/app/detekcja/scal.py`) i warstwa Morfeusz2 (`serwis/app/morf.py`). Wyniki w `serwis/testy/wyniki/etap2_scalanie.md`, pomiar: `docker compose exec anonimizator python -m app.ewaluacja.scalanie`.

| wariant | pełne pokrycie | częściowe | brak | nadmiar |
|---|---|---|---|---|
| surowe, z LLM | 216/218 (99,1%) | 2 | 0 | 29 |
| scalone, z LLM | 218/218 (100%) | 0 | 0 | 3 |
| scalone, bez LLM | 215/218 (98,6%) | 3 | 0 | 3 |

Reguły scalania: pierwszeństwo regexów, przycinanie tytułów i interpunkcji, filtr określeń ogólnych („Spółka”, „Zgromadzenie Wspólników”) i słów funkcyjnych, propagacja wykrytej nazwy na wszystkie jej dokładne wystąpienia, dołączanie formy prawnej, sklejanie sąsiadów (łącznik, „w” między adresem lub instytucją a miejscowością).

Morfeusz2 (SGJP): rozpoznaje imiona, nazwiska i miejscowości z kategorią, lematem, przypadkiem i rodzajem, także nazwiska żeńskie nieodmienne. Nie zna nazw wymyślonych firm („Stalmet”, „Kodmistrz”) ani obcych nazwisk („Müller”). Dla nich potrzebne są formy zaobserwowane w dokumencie, reguły końcówek i fallback LLM.

Projekt części 2 (surogaty i deanonimizacja), do potwierdzenia:
1. Osoby są mapowane na poziomie słowa, nie całej osoby: lemat imienia → imię zastępcze tej samej płci, lemat nazwiska → nazwisko zastępcze. „Jan Kowalski”, „Kowalskiego” i „pan Jan” są wtedy spójne bez klastrowania, a małżonkowie zachowują wspólne nazwisko.
2. Nazwiska zastępcze są typu przymiotnikowego (-ski, -ska), bo odmieniają się regularnie w obu rodzajach. Imiona zastępcze pochodzą z listy z tabelami odmiany wygenerowanymi Morfeuszem i sprawdzonymi ręcznie.
3. Firmy: podmieniany jest tylko rdzeń nazwy, forma prawna („Sp. z o.o.”) zostaje bez zmian. Surogat to wymyślona nazwa o regularnej odmianie, z puli zgodnej z rodzajem oryginału (męska na spółgłoskę, żeńska na -a).
4. Instytucje („Sąd Rejonowy w Gliwicach”): część ogólna zostaje, podmieniana jest tylko miejscowość.
5. Miejscowości poza adresem są podmieniane na inne polskie miasta z puli (rozstrzyga punkt 6.3 na „tak”, z możliwością wyłączenia).
6. Adresy są podmieniane po składnikach: nazwa ulicy na ulicę o nazwie nieodmiennej („ul. Kopernika”), numery i kod pocztowy losowo, miejscowość zgodnie z mapą miejscowości.
7. Deanonimizacja: forma surogatu wskazuje przypadek, a oryginał w tym przypadku pochodzi kolejno z formy zaobserwowanej w dokumencie, z Morfeusza, z reguł, a na końcu z LLM (wtedy miejsce trafia na listę niepewnych).
8. Przypadki dwuznaczne w formie surogatu (celownik i miejscownik rodzaju żeńskiego, narzędnik i miejscownik nazwisk na -ski) rozstrzyga przyimek: miejscownik w polszczyźnie występuje wyłącznie po przyimku.
9. Znane ograniczenie: zdrobnienie („Kasia”) i pełne imię („Katarzyna”) dostają niezależne surogaty, więc zewnętrzny model traci tę wskazówkę.

## 5. Model danych

5.1. `sesja`: id, nazwa, data utworzenia, czas życia.
5.2. `dokument`: id, sesja, plik oryginalny, typ wejścia (pdf_cyfrowy, pdf_skan, docx), status, ścieżki artefaktów (plik zanonimizowany, raport HTML).
5.3. `encja`: id, sesja, typ, lemat oryginału, rodzaj, liczba, surogat (id z puli).
5.4. `wystapienie`: encja, dokument, pozycja w tekście, forma powierzchniowa, przypadek.
5.5. `zadanie`: id, dokument, etap, status, błąd, czasy.
5.6. `audyt`: co, kiedy, którym modelem, hash tekstu wysłanego na zewnątrz. Bez treści oryginałów.

## 6. Typy encji

6.1. Odmienne, z surogatem z puli: osoba (imię, nazwisko), firma lub instytucja, miejscowość i ulica w adresie, nazwa własna inna (projekt, produkt, kryptonim).
6.2. O stałym formacie, z fałszywką w tym samym formacie: PESEL, NIP, REGON, KRS, IBAN, telefon, e-mail, numer dowodu, numer umowy lub sprawy. PESEL i NIP z celowo błędną sumą kontrolną.
6.3. Otwarte: czy uogólniać kwoty, daty i lokalizacje (quasi-identyfikatory). Domyślnie nie, do decyzji po etapie 2.

## 7. Potok anonimizacji dokumentu

7.1. Rozpoznanie typu wejścia: rozszerzenie pliku, a dla PDF obecność warstwy tekstowej (liczba znaków na stronę).
7.2. Ekstrakcja: Docling zwraca tekst ze strukturą (nagłówki, akapity, tabele, strony).
7.3. Detekcja encji o stałym formacie: wyrażenia regularne z walidacją.
7.4. Detekcja nazw własnych: NER klasyczny na całym tekście oraz LLM na fragmentach. Wyniki są sumowane (priorytet: recall).
7.5. Normalizacja: Morfeusz ustala lemat, przypadek, rodzaj i liczbę każdego wystąpienia.
7.6. Klastrowanie wariantów tej samej encji („Jan Kowalski”, „pana Jana”, „J. Kowalski”) po lematach, LLM rozstrzyga niejednoznaczności. Rejestr encji jest wspólny dla sesji.
7.7. Przydział surogatów: ten sam typ, rodzaj i liczba, zbliżona długość. Surogat nie może występować w żadnym dokumencie sesji.
7.8. Podmiana: surogat w tym samym przypadku co wystąpienie, w pliku wyjściowym zgodnym z typem wejścia (punkt 2.10).
7.9. Czyszczenie: metadane, obrazy, komentarze, śledzenie zmian.
7.10. Kontrola wycieku na gotowym pliku: ponowna ekstrakcja tekstu z pliku wynikowego, drugi przebieg NER i regexów. Każda wykryta encja musi być znanym surogatem lub fałszywką. Inaczej dokument dostaje status „do przeglądu” i nie jest udostępniany. Część tekstowa (oryginały z mapy sesji i regexy na tekście wynikowym) działa od 2026-11-17 (`silnik.kontrola_wycieku`); na pliku do zrobienia w etapie 3.
7.11. Raport porównawczy HTML.

## 8. Deanonimizacja tekstu

8.1. Wejście: tekst z surogatami (wynik pracy zewnętrznego modelu) i id sesji.
8.2. Wyszukanie wszystkich form surogatów przez tabele odmiany (lookup, bez modelu).
8.3. Dla każdego trafienia: wygenerowanie oryginału w tym samym przypadku (Morfeusz, fallback LLM).
8.4. Fałszywki o stałym formacie: podmiana 1:1.
8.5. Wynik zawiera listę miejsc niepewnych (forma surogatu spoza tabeli, fallback LLM) do przejrzenia.

## 9. API serwisu `anonimizator`

9.1. `POST /sesje` tworzy sesję.
9.2. `POST /sesje/{id}/dokumenty` przyjmuje plik, zwraca id zadania (przetwarzanie asynchroniczne).
9.3. `GET /zadania/{id}` zwraca status i etap.
9.4. `GET /dokumenty/{id}/zanonimizowany` zwraca plik wynikowy.
9.5. `GET /dokumenty/{id}/raport` zwraca raport HTML.
9.6. `POST /sesje/{id}/anonimizuj-tekst` anonimizuje krótki tekst mapą sesji (potrzebne w trybie B dla wiadomości użytkownika).
9.7. `POST /sesje/{id}/deanonimizuj-tekst` deanonimizuje tekst.
9.8. `GET /sesje/{id}/mapa` zwraca tabelę encji i surogatów.

## 10. Workflowy n8n

10.1. Tryb A
10.1.1. „Anonimizuj dokument”: formularz (plik, sesja nowa lub istniejąca) → wysłanie do serwisu → odpytywanie statusu → zwrot pliku i raportu albo komunikat „do przeglądu”.
10.1.2. „Deanonimizuj wynik”: formularz (sesja, tekst) → serwis → tekst z listą miejsc niepewnych.
10.1.3. Workflow błędów wspólny dla wszystkich.
10.2. Tryb B: Chat Trigger z uploadem pliku, anonimizacja każdej wiadomości, zewnętrzny model, deanonimizacja odpowiedzi, RAG na tekście zanonimizowanym dla długich dokumentów.
10.3. Tryb C: trigger z folderu, klasyfikacja typu dokumentu lokalnym modelem, prompt i schemat wyjścia z Data Table `typy_dokumentow`, zewnętrzny model, deanonimizacja, zapis wyniku.
10.4. Zasada wspólna: przy każdym błędzie lub niepewności przebieg zatrzymuje się przed wysyłką na zewnątrz.

## 11. Testy i miary jakości

11.1. Zestaw wzorcowy: syntetyczne dokumenty (bez prawdziwych danych) w trzech typach wejścia, z ręcznie oznaczonymi encjami.
11.2. Miary: recall detekcji per typ encji, liczba wycieków w pliku wynikowym, poprawność odmiany surogatów, poprawność deanonimizacji (tekst po pełnym obiegu równy oczekiwanemu).
11.3. Testy regresji uruchamiane po każdej zmianie w serwisie.
11.4. Próg przejścia do trybu B: zero wycieków na zestawie wzorcowym i na próbie prawdziwych dokumentów ocenionych ręcznie przez raport porównawczy.

## 12. Plan wdrożenia

12.1. Etap 0: środowisko
12.1.1. Katalog serwisu, `docker-compose.yml` z kontenerami `anonimizator`, `docling`, `ollama` w sieci n8n.
12.1.2. Sprawdzenie, że n8n widzi serwisy, a Docling i Ollama mieszczą się w RAM i VRAM.
12.1.3. Gotowe, gdy: endpoint zdrowia każdego serwisu odpowiada z n8n.

12.2. Etap 1: detekcja
12.2.1. Zestaw wzorcowy (wersja pierwsza, PDF cyfrowy i DOCX).
12.2.2. Regexy z walidacją, NER klasyczny, LLM, sumowanie wyników.
12.2.3. Porównanie spaCy z HerBERT oraz dwóch kandydatów LLM na zestawie wzorcowym.
12.2.4. Gotowe, gdy: znany jest recall per typ encji i wybrane są modele.

12.3. Etap 2: morfologia i surogaty
12.3.1. Integracja Morfeusz2, klastrowanie wariantów, rejestr encji sesji.
12.3.2. Pula surogatów z tabelami odmiany, przydział, podmiana na czystym tekście.
12.3.3. Deanonimizacja tekstu.
12.3.4. Gotowe, gdy: tekst po anonimizacji i deanonimizacji wraca do oryginału na zestawie wzorcowym, a odmiana surogatów jest poprawna.

12.4. Etap 3: pliki
12.4.1. Podmiana w PDF cyfrowym i DOCX, czyszczenie metadanych i obrazów.
12.4.2. Kontrola wycieku na gotowym pliku, raport HTML.
12.4.3. Gotowe, gdy: zero wycieków w plikach wynikowych zestawu wzorcowego.

12.5. Etap 4: tryb A w n8n
12.5.1. Workflowy z punktu 10.1, API asynchroniczne, workflow błędów.
12.5.2. Gotowe, gdy: pełny obieg na prawdziwym dokumencie przechodzi z formularza n8n.

12.6. Etap 5: skany
12.6.1. OCR przez Docling, odtworzenie dokumentu, rozszerzenie zestawu wzorcowego o skany.
12.6.2. Pomiar czasu dla dokumentu kilkusetstronicowego.
12.6.3. Gotowe, gdy: zero wycieków na skanach wzorcowych i akceptowalny czas.

12.7. Etap 6: tryb B (chatbot), po spełnieniu progu z 11.4.

12.8. Etap 7: tryb C (wsad z typami dokumentów i promptami w Data Table).

## 13. Sprawy otwarte

13.1. Zewnętrzny dostawca modelu, umowa powierzenia, retencja (odłożone).
13.2. Wybór NER i LLM (etap 1).
13.3. Uogólnianie kwot, dat i lokalizacji (po etapie 2).
13.4. Czas życia sesji i map surogatów.
13.5. Poziomy polityki per klient (tylko lokalnie albo zewnętrznie po anonimizacji), jeśli pojawi się klient, dla którego surogaty nie wystarczą.

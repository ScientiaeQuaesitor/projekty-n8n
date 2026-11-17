# Plan dalszych prac: anonimizacja v2

Stan na 2026-11-16. Uzupełnia `PRZEKAZANIE.md` (gdzie przerwano) i `specyfikacja-v2.md` (decyzje i pomiary). Każdy krok kończy się pomiarem całego zestawu wzorcowego, wynik oczekiwany: 0 wycieków, 0 zepsutych, 0 różnic.

## 1. Kolejność

| faza | zakres | szacunek | warunek wejścia |
|---|---|---|---|
| A | domknięcie etapu 2: pomiar aktu, czas głosowania, porządki | 1 sesja | brak |
| B | naprawa znanych błędów tekstu i raportu | 1 do 2 sesji | A |
| C | etap 3: pliki PDF i DOCX, kontrola wycieku, API zadań | 2 do 3 sesji | A, B.1 |
| D | etap 4: workflowy n8n trybu A | 1 sesja | C |
| E | etap 5: dokończenie skanów | 1 do 2 sesji | C |
| F | etapy 6 i 7: chatbot, wsad | osobny plan | próg z 11.4 specyfikacji |

## 2. Faza A: domknięcie etapu 2

2.1. Pamięć klasyfikacji w pomiarze dokumentu. `ewaluacja/dokument.py` nie przekazuje `pamiec` do `silnik.anonimizuj`, więc przerwany pomiar aktu zaczyna od zera. Zmiana: plik pamięci obok PDF w `testy/prawdziwe/` (zostaje lokalnie), zapis po każdym wariancie głosowania. Gotowe, gdy: przerwany pomiar wznawia się bez powtórnych pytań do modelu.
2.2. Klucz pamięci z odciskiem promptu i modelu (`sha1(PROMPT_KLASYFIKACJA + wariant + model)`), w `dokument.py` i `obieg.py`. Zamyka sprawę 5.2 z przekazania: po zmianie promptu stare oceny nie są używane, pliku nie trzeba usuwać ręcznie.
2.3. Czasy faz w `dokument.py`: ekstrakcja, detekcja, klasyfikacja (osobno każdy wariant), podmiana. Bez tego nie da się ocenić kroku 2.5.
2.4. Pomiar aktu z głosowaniem (po 2.1 do 2.3, kilka do kilkunastu minut). Kontrola ośmiu pojęć ogólnych z punktu 4.2 przekazania w `akt_notarialny.anon.md`. Potem przegląd raportu HTML przez użytkownika.
2.5. Głosowanie etapowe. Warianty „lista” i „uzasadnienie” zawsze. Wariant „pojedynczo” (jedno zapytanie na nazwę, najdroższy) tylko dla nazw, przy których dwa pierwsze różnią się stroną (zostaw albo podmień).
2.5.1. Skutek uboczny do zmierzenia: znika przypadek „dwa głosy za podmianą, jeden za zostawieniem”, który dziś daje typ `OPISOWA`. Nazwa opisowa z dwoma głosami za podmianą byłaby podmieniana w całości.
2.5.2. Zabezpieczenie: przy zgodnej podmianie i budowie opisowej (pierwsze słowo pospolite, dalej człon własny, bez formy prawnej) nadal pytać trzeci wariant.
2.5.3. Gotowe, gdy: zestaw 0/0/0, akt nie gorszy niż w 2.4, czas klasyfikacji wyraźnie niższy. Jeśli wynik się pogorszy, zostaje pełne głosowanie.
2.6. Porządki: usunąć `silnik.odsiej_ogolne`, `silnik._same_pospolite` (jeśli nieużywane), `llm.zweryfikuj`, `PROMPT_WERYFIKACJA`, `SCHEMAT_WERYFIKACJA`. Dopisać `LLM_MODEL_KLASYFIKACJA` do `serwis/docker-compose.yml`. Zmienić etykietę „odrzucone jako ogólne” na „zostawione (kategoria)”.
2.7. Dopisać stan do `PRZEKAZANIE.md` i wyniki do specyfikacji.

## 3. Faza B: znane błędy

Kolejność według wartości. Każdy punkt dostaje test z danymi fikcyjnymi w `serwis/testy/wzorce/`.

3.1. Bezpiecznik wycieku na tekście (wcześniejsza część punktu 7.10 specyfikacji). Po podmianie: wyszukanie w tekście wynikowym wszystkich form oryginałów z mapy sesji (dopasowanie dokładne, bez modelu) oraz ponowne regexy numerów. Trafienie daje status „do przeglądu”. Tani test, który łapie błędy propagacji i klasyfikacji niezależnie od detektorów. Miejsce: nowa funkcja w `silnik.py`, pole `kontrola` w wyniku.
3.2. Raport HTML (`raport.py`): na górze lista „sporne” i „zostawione” z kategorią, sekcja jakości OCR (wiersze niepewne z numerem strony), wynik bezpiecznika z 3.1. Cel: przegląd dokumentu w kilka minut zamiast czytania całości.
3.3. Przyimek przy surogacie („we Elblągu”). Rozwiązanie bez zmiany tekstu poza zakresem: surogat miejscowości dobierany z tej samej klasy nagłosu co oryginał (wymaga „we”, wymaga „ze”, zwykły). Klasę wylicza reguła fonetyczna z pierwszych liter, nie lista. Deanonimizacja bez zmian. Miejsce: `nazwy.miejsce`, `pule.py`.
3.4. Skrótowiec i pełna nazwa firmy z różnymi surogatami. Reguła: jeśli litery skrótowca odpowiadają pierwszym literom członów pełnej nazwy z tego samego dokumentu lub sesji, oba wpisy dostają wspólny klucz, a surogat skrótowca powstaje z inicjałów surogatu pełnej nazwy. Miejsce: `nazwy.analizuj_nazwe`, `nazwy._surogat`.
3.5. Firma w liczbie mnogiej lub rodzaju nijakim dostaje surogat męski. `nazwy._liczba_rodzaj` już ustala liczbę i rodzaj. Brakuje puli: generator `pule.zapas_nazwy` z końcówką zgodną z rodzajem i liczbą oraz tabelą odmiany dla tego wzorca.
3.6. Nazwa firmy spoza słownika w niewidzianym przypadku („Stalmetie”). Dwa kroki: alternacje spółgłoskowe w miejscowniku w regule odmiany (t na ci, d na dzi, r na rz, ł na l, st na ści), potem fallback LLM z walidacją (forma musi zachować rdzeń i mieć końcówkę dopuszczalną dla przypadka). Miejsce nadal trafia na listę niepewnych. Miejsce: `nazwy.forma_nazwy`.
3.7. Nazwisko dwuczłonowe przełamane między wierszami i zakres przechodzący przez koniec wiersza. OCR już skleja wiersze w akapity. Dla PDF cyfrowego rozwiązuje to model pośredni z fazy C (punkt 4.2): detekcja na tekście ciągłym, mapa pozycji do pliku.
3.8. Trzy liczby z ukośnikiem bez podmiany na akcie: czeka na ocenę użytkownika w raporcie. Jeśli to identyfikatory, rozszerzyć kontekst w `RX_NR_KONTEKST` regułą ogólną i dodać test.
3.9. OCR, trzeci odczyt wierszy niepewnych modelem wizyjnym `qwen3-vl:8b` (tylko wycinki wierszy, na akcie 4 z 232). Opcjonalne, po fazie C. Miara: liczba wierszy niepewnych i numerów z poprawną sumą.

## 4. Faza C: etap 3, pliki

4.1. Zależności: `PyMuPDF` i `python-docx` do `requirements.txt` (dziś ich nie ma), przebudowa obrazu.
4.2. Model pośredni dokumentu: lista fragmentów z adresem w pliku (PDF: strona, prostokąt, czcionka; DOCX: akapit, run) oraz tekst ciągły z mapą pozycji. Detekcja i silnik pracują na tekście ciągłym, podmiana wraca pod adresy. Łamanie wiersza i przeniesienie wyrazu są rozwijane w tekście ciągłym.
4.3. DOCX: podmiana w runach (zakres w kilku runach: tekst do pierwszego, reszta czyszczona), także nagłówki, stopki, tabele, przypisy, pola tekstowe. Czyszczenie: komentarze, śledzenie zmian, metadane (core, app, custom), obrazy.
4.4. PDF cyfrowy: redakcja zakresu (`add_redact_annot`, `apply_redactions`) i wpisanie surogatu w ten sam prostokąt, czcionka zastępcza z polskimi znakami, zmniejszenie rozmiaru przy dłuższym surogacie. Czyszczenie: obrazy, metadane, XMP, załączniki, adnotacje. Zapis z `garbage=4, clean=True`, żeby usunięty tekst nie został w strumieniach.
4.5. Kontrola wycieku na pliku (pełny punkt 7.10): ponowna ekstrakcja z pliku wynikowego, bezpiecznik z 3.1, regexy i NER. Każda wykryta encja musi być surogatem z mapy. Inaczej status „do przeglądu”, plik nie jest wydawany.
4.6. Zestaw wzorcowy plikowy: skrypt generuje DOCX i PDF z siedmiu wzorców. Dodatkowe przypadki: tabela, nagłówek i stopka, nazwa rozbita na runy, nazwa przełamana między wierszami, metadane z nazwiskiem autora.
4.7. Baza i API: tabele `dokument`, `zadanie`, `audyt` w `sesja.py`. Endpointy `POST /sesje/{id}/dokumenty`, `GET /zadania/{id}`, pobranie pliku i raportu. Kolejka: jeden wątek roboczy, jedno zadanie naraz, stan w SQLite, wznowienie po restarcie kontenera.
4.8. Gotowe, gdy: 0 wycieków w plikach wynikowych zestawu, pliki otwierają się poprawnie, metadane są puste, zadanie przerwane restartem kończy się po wznowieniu.
4.9. XLSX i XML (zgłoszone 2026-11-17, po PDF i DOCX, ten sam model pośredni z 4.2). Adres fragmentu: XLSX arkusz i komórka, XML ścieżka elementu albo atrybutu. Kontekst dla detekcji: nagłówek kolumny (XLSX) i nazwa elementu (XML), bo pojedyncza komórka nie ma zdania wokół siebie; kolumna z nagłówkiem typu „Nazwisko” lub „PESEL” jest podmieniana w całości.
4.9.1. XLSX (`openpyxl`): komórki tekstowe i liczbowe (PESEL i NIP zapisane jako liczba, bez zer wiodących), formuły zostają, wartości w pamięci podręcznej formuł czyszczone; także nazwy arkuszy, komentarze, nagłówki i stopki, ukryte arkusze i wiersze, listy walidacji, nazwy zdefiniowane, metadane. Tabele przestawne trzymają kopię danych źródłowych: usuwać pamięć podręczną albo odrzucać plik.
4.9.2. XML (`lxml`): tekst elementów i wartości atrybutów, komentarze, CDATA, instrukcje przetwarzania; przestrzenie nazw i kolejność bez zmian, plik wynikowy zgodny z XSD, jeśli jest znany. Podpis elektroniczny (XAdES) traci ważność: usuwać i odnotować w raporcie.
4.9.3. Do ustalenia z użytkownikiem przed 4.9: jakie rodzaje XML (JPK, e-faktura KSeF, eksport z systemu, inne), czy wynik ma być plikiem w tym samym formacie, czy tylko tekstem dla modelu, i czy w XLSX liczby (kwoty, daty) zostają jak w tekście.

## 5. Faza D: etap 4, n8n tryb A

5.1. „Anonimizuj dokument”: Form Trigger (plik, sesja nowa lub istniejąca), HTTP Request z plikiem do `http://anonimizator:8000`, pętla Wait i `GET /zadania/{id}`, rozgałęzienie po statusie, zakończenie formularza z plikiem i adresem raportu albo komunikatem „do przeglądu”.
5.2. „Deanonimizuj wynik”: formularz (sesja, tekst), serwis, wynik z listą miejsc niepewnych.
5.3. Wspólny workflow błędów (Error Trigger). Zasada 10.4 specyfikacji: błąd lub niepewność zatrzymuje przebieg przed wysyłką na zewnątrz.
5.4. Raport HTML serwuje anonimizator pod `127.0.0.1:8090`, nie n8n. Oryginał nie trafia do danych wykonań n8n poza samym plikiem wejściowym; do rozważenia wyłączenie zapisu danych wykonań dla tych workflowów.
5.5. Gotowe, gdy: pełny obieg prawdziwego dokumentu przechodzi z formularza, a przebieg jest sprawdzony w `n8n_executions`.

## 6. Faza E: etap 5, skany

6.1. Odtworzenie dokumentu ze skanu: plik wynikowy z akapitów OCR (struktura, nie wygląd), bez pikseli oryginału.
6.2. Skany wzorcowe: wzorce renderowane do obrazu z obniżoną rozdzielczością i szumem. Znany tekst źródłowy daje prawdziwą miarę błędów OCR (znaki, nazwiska, cyfry) zamiast miary słownikowej. Zamyka sprawę 5.6 z przekazania.
6.3. Pomiar czasu dla dokumentu kilkusetstronicowego (dziś około 27 s na stronę, 300 stron to ponad 2 godziny). Do sprawdzenia: EasyOCR tylko dla stron ze słabymi wierszami już działa, kolejna oszczędność to równoległość Tesseracta po stronach.
6.4. Tabele i układ wielokolumnowy w skanach: test i decyzja, czy wracać do Doclinga dla układu.

## 7. Faza F: etapy 6 i 7 (zarys)

7.1. Warunek: próg 11.4, czyli zero wycieków na zestawie i na próbie prawdziwych dokumentów ocenionych w raporcie.
7.2. Tryb B: kategorie nazw zapisane w sesji, żeby wiadomość czatu nie czekała na głosowanie. Klasyfikowane są tylko nazwy nowe w sesji.
7.3. Tryb C: Data Table `typy_dokumentow` (prompt, schemat wyjścia), klasyfikacja typu modelem lokalnym.
7.4. Przed fazą F decyzja 13.1: dostawca zewnętrzny, umowa powierzenia, retencja.

## 8. Ryzyka

8.1. Reguły strojone na zestawie napisanym przez autora. Każdy nowy typ prawdziwego dokumentu pokaże nowe błędy. Potrzebne dokumenty innego rodzaju niż akt.
8.2. Model 8B jako klasyfikator jest niestabilny. Głosowanie to ogranicza, ale nie usuwa. Bezpiecznik 3.1 i reguła „zostawić można tylko wyrazy pospolite” ograniczają skutek błędu.
8.3. PDF: czcionki osadzone jako podzbiór bez potrzebnych glifów, tekst jako krzywe, surogat dłuższy niż miejsce.
8.4. Pamięć: spaCy, FastPDN i EasyOCR w jednym kontenerze przy limicie 7,6 GB na wszystkie kontenery.
8.5. Zmiany robione łatkami bez historii wersji. Regresji nie da się cofnąć do znanego stanu.

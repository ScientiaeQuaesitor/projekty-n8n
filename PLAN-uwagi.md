# Informacje i pomysły dla użytkownika

## 9. Czego potrzebuję od Ciebie

9.1. Przegląd nowego raportu HTML aktu po kroku 2.4. Poprzedni raport (po zmianie OCR) nie ma jeszcze Twoich uwag.
9.2. Ocena trzech liczb z ukośnikiem na akcie: identyfikatory czy nie.
9.3. Dwa do trzech prawdziwych dokumentów innego typu niż akt, najlepiej jeden DOCX i jeden PDF cyfrowy (umowa, pismo procesowe, faktura). Bez nich faza C będzie sprawdzona tylko na danych syntetycznych.
9.4. Decyzje otwarte ze specyfikacji: czas życia sesji (13.4), uogólnianie kwot i dat (13.3), dostawca zewnętrzny (13.1). Żadna nie blokuje faz A do D.

## 10. Liczby, które warto znać

| operacja | czas |
|---|---|
| OCR aktu, 5 stron, dwa silniki | 134 s |
| detekcja z LLM na akcie | 77 s |
| klasyfikacja z głosowaniem, zestaw 7 dokumentów od zera | 356 s |
| klasyfikacja aktu z głosowaniem | niezmierzone, kilka do kilkunastu minut |
| OCR skanu 300 stron | ponad 2 godziny |

10.1. Wąskie gardło dla dokumentów cyfrowych to klasyfikacja, dla skanów OCR.
10.2. `gemma4:e4b` mieści się w całości w VRAM (3,3 GB). Bielik i `qwen3-vl:8b` nie, stąd trzy do dziesięciu razy dłuższe czasy.

## 11. Pomysły

11.1. Lokalny Git w katalogu projektu (bez zdalnego repozytorium), z `.gitignore` na `serwis/testy/prawdziwe/` i `serwis/dane/`. Poprawa na jednym dokumencie kilka razy psuła pozostałe, a dziś nie ma jak wrócić do stanu sprzed zmiany. Najtańsza rzecz o największym zwrocie.
11.2. Krok zatwierdzenia w n8n: po anonimizacji formularz z listą „sporne” i przyciskami „wydaj” albo „do poprawy”. Plik wychodzi dopiero po Twojej decyzji. Zgodne z zasadą 10.4.
11.3. Poprawki ręczne per sprawa: w raporcie wskazujesz „to podmień” albo „to zostaw”, serwis zapisuje wyjątek w mapie sesji. To dane sprawy, nie lista pojęć w kodzie, więc nie łamie zasady uniwersalności. Każda taka poprawka to sygnał do nowego testu wzorcowego.
11.4. Kategorie nazw pamiętane w sesji. Drugi dokument tej samej sprawy klasyfikuje tylko nowe nazwy. W sprawach wielodokumentowych czas spada wielokrotnie.
11.5. Inny model jako trzeci głos zamiast trzeciego promptu tego samego modelu (na przykład Bielik tylko dla nazw spornych). Hipoteza: błędy dwóch modeli są mniej skorelowane niż błędy dwóch promptów. Koszt: przeładowanie modelu w VRAM. Do zmierzenia, nie do założenia.
11.6. Daty jako quasi-identyfikatory: zamiast zostawiać albo usuwać, przesunięcie wszystkich dat sesji o ten sam losowy odstęp. Odstępy między zdarzeniami i terminy zachowują sens, deanonimizacja jest odwracalna. Opcja per sesja, domyślnie wyłączona. Wada: dzień tygodnia i terminy ustawowe liczone od konkretnej daty mogą się rozjechać.
11.7. Test reidentyfikacji: po anonimizacji lokalny model dostaje tekst wynikowy i pytanie „kogo i czego dotyczy ten dokument”. Odpowiedź z prawdziwą nazwą oznacza wyciek przez kontekst (unikalny opis, rzadka funkcja, numer działki z obrębem). Wynik tylko jako ostrzeżenie w raporcie.
11.8. Numer księgi wieczystej ma cyfrę kontrolną. Walidacja jak dla PESEL dałaby pewniejszą detekcję i dodatkowy punkt zaczepienia przy wyborze odczytu OCR. Do sprawdzenia, czy obecny wzorzec sygnatur łapie wszystkie zapisy.
11.9. Skanowanie w 300 dpi u źródła. Akt miał około 170 dpi i to ogranicza każdy silnik. Żadna zmiana w kodzie nie da tyle, co lepszy skan.
11.10. Dziennik audytu od fazy D, nie od F: skrót tekstu wysłanego na zewnątrz, model, czas, sesja. Przy rozmowie z klientem o powierzeniu danych to dowód, co opuściło maszynę.
11.11. Tryb „tylko raport”: anonimizacja bez wydania pliku, sam raport i liczniki. Przydatny do szybkiej oceny nowego typu dokumentu przed dopuszczeniem go do obiegu.

## 12. Czego nie polecam

12.1. Większego modelu lokalnego jako klasyfikatora. Na 8 GB VRAM każdy model powyżej klasy 8B schodzi częściowo na CPU i wydłuża przebieg kilkukrotnie przy zysku w granicach szumu (pomiar z etapu 1).
12.2. Reguły „same słowa pospolite, więc zostaje” bez pytania modelu. Była mierzona: 16 wycieków.
12.3. Rozpoczynania trybu B przed kontrolą wycieku na pliku. Czat wysyła treść na zewnątrz bez Twojego przeglądu, więc bezpiecznik musi działać automatycznie.

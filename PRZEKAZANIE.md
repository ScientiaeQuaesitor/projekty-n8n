# Przekazanie do następnej sesji

Stan na 2026-11-16, godz. 21:45. Pełny opis decyzji i pomiarów: `specyfikacja-v2.md` w tym katalogu. Ten plik mówi, gdzie przerwano pracę i co zrobić najpierw.

## 1. Co jest zbudowane

1.1. Serwis `anonimizator` (FastAPI, katalog `serwis/`, kontener działa, z hosta `http://127.0.0.1:8090`, z n8n `http://anonimizator:8000`).
1.2. Detekcja: regex + spaCy `pl_core_news_lg` + FastPDN + LLM `gemma4:e4b` (Ollama na hoście).
1.3. Anonimizacja surogatami z odmianą (Morfeusz2), deanonimizacja tekstu, sesje w SQLite, API (`/sesje`, `/sesje/{id}/anonimizuj-tekst`, `/sesje/{id}/deanonimizuj-tekst`, `/sesje/{id}/mapa`).
1.4. OCR skanów dwoma silnikami (Tesseract pol + EasyOCR) z wyborem lepszego odczytu w każdym wierszu: `serwis/app/ocr.py`.
1.5. Lokalny raport porównawczy HTML: `serwis/app/raport.py`.
1.6. Zestaw wzorcowy: 7 dokumentów w `serwis/testy/wzorce/`, znaczniki `{{TYP|…}}` (ma zostać podmienione) i `{{ZOSTAW|…}}` (ma zostać bez zmian).

## 2. Nad czym przerwano

2.1. Wymaganie użytkownika: żadnych list pojęć w kodzie. Ogólne nazwy własne (ustawa, kodeks, rodzaj orzeczenia lub dokumentu, nazwa sądu, organ publiczny) mają zostać, podmieniane mają być tylko dane identyfikujące strony. Automatyzacja ma być uniwersalna, nie strojona pod jeden dokument.
2.2. Wdrożone rozwiązanie: polityka kategorii. LLM przypisuje każdej wykrytej nazwie kategorię z kontekstu (`detekcja/llm.py: klasyfikuj`, kategorie OSOBA, FIRMA, PRODUKT, MIEJSCE, INSTYTUCJA, AKT_PRAWNY, DOKUMENT, POJECIE). Polityka w `anonimizacja/silnik.py`: `KATEGORIE_ZOSTAW` i `TYP_KATEGORII`.
2.3. Dla kategorii „zostaw” działa `nazwy.podmien_wlasne`: zwykłe słowa zostają, podmieniane są tylko imiona, nazwiska, miejscowości i słowa spoza słownika. Błędna ocena kategorii może więc zostawić wyłącznie wyrazy pospolite.
2.4. Pojedyncza ocena modelu 8B okazała się niestabilna (zmiana wielkości paczki odwracała decyzje), więc kategorię ustala głosowanie trzech wariantów pytania (`WARIANTY_KLASYFIKACJI`: lista, uzasadnienie, pojedynczo). Nazwa zostaje przy co najmniej dwóch głosach „zostaw”. Głosy podzielone plus budowa opisowa dają podmianę samego członu własnego (typ podmiany `OPISOWA`).
2.5. Usunięte listy pojęć: `STOP_RDZENIE`, `JEDNOSTKI`, `INSTYTUCJE`, `GLOWY_OPISOWE`, `OGOLNE`, frazy nazw organów w `RX_CHRONIONE`. Zostały tylko elementy strukturalne: etykiety pól (`STOP_DOKLADNE`), tytuły grzecznościowe, formy prawne spółek, przyimki, wzorce dat, kwot i odwołań do przepisów.

## 3. Ostatnie pomiary

3.1. Zestaw wzorcowy z głosowaniem, klasyfikator `gemma4:e4b`: 261 podmian, 0 wycieków, 0 zepsutych, 0 różnic po obiegu. Czas klasyfikacji 7 dokumentów od zera: 356 s. Wyniki: `serwis/testy/wyniki/etap2_obieg.md`.
3.2. `qwen3-vl:8b` jako klasyfikator (wariant bez głosowania): 7 wycieków, 2 zepsute, 564 s. Model nie mieści się w 8 GB VRAM (22% na CPU). Gorszy i dziesięć razy wolniejszy od gemmy w tej roli. Wyniki: `serwis/testy/wyniki/etap2_obieg_qwen3-vl_8b.md`.
3.3. Akt notarialny z głosowaniem: NIE ZMIERZONY. Pomiar został przerwany przez użytkownika, bo trwał za długo. Pliki `serwis/testy/prawdziwe/akt_notarialny.raport.*` i `.anon.md` pochodzą z godz. 21:34, z wersji z jedną oceną (wariant „uzasadnienie”), czyli są nieaktualne względem kodu.
3.4. Znane wyniki na akcie z wersji jednoocenowych: wariant „lista” błędnie uznał radę miejską, sąd i portal ksiąg wieczystych za firmy. Wariant „uzasadnienie” zachował je poprawnie, ale popsuł zestaw wzorcowy. Stąd głosowanie.

## 4. Pierwsze kroki w następnej sesji

4.1. Zmierzyć akt z głosowaniem (kilka do kilkunastu minut, klasyfikacja około 60 nazw w trzech wariantach). W katalogu `serwis`:

```bash
docker compose exec anonimizator python -m app.ewaluacja.dokument /srv/testy/prawdziwe/akt_notarialny.pdf
```

W Git Bash dodać przed komendą `MSYS_NO_PATHCONV=1`, inaczej ścieżka `/srv/...` zostanie zamieniona na ścieżkę Windows.
4.2. Sprawdzić w `akt_notarialny.anon.md`, czy zostały: „Umowa Przedwstępna”, „Ordynacja podatkowa”, „Kodeks cywilny”, „Rada Miejska” (ze zmienioną miejscowością), „Sąd Rejonowy”, „Bazy Danych Ksiąg Wieczystych”, „Specjalnej Strefy Ekonomicznej”, „Kancelarii Notarialnej”. To pojęcia ogólne, wolno ich szukać w tekście.
4.3. Poprosić użytkownika o przejrzenie nowego raportu HTML. Poprzedniego raportu po zmianie OCR jeszcze nie skomentował.
4.4. Powtórzyć pomiar zestawu wzorcowego po każdej zmianie:

```bash
docker compose exec anonimizator python -m app.ewaluacja.obieg --klasyfikator gemma4:e4b
```

## 5. Otwarte sprawy

5.1. Czas klasyfikacji z głosowaniem: około 50 s na dokument wzorcowy, na długich dokumentach rośnie z liczbą unikalnych nazw. Do rozważenia: trzeci wariant („pojedynczo”) tylko przy niezgodzie dwóch pierwszych.
5.2. Pamięć klasyfikacji w pomiarach (`testy/wyniki/cache_klasyfikacja_*.json`) nie uwzględnia treści promptu. Po zmianie promptu lub wariantów plik trzeba usunąć ręcznie.
5.3. Martwy kod do usunięcia: `silnik.odsiej_ogolne`, `llm.zweryfikuj`, `PROMPT_WERYFIKACJA`.
5.4. Parametr modelu klasyfikacji: zmienna środowiskowa `LLM_MODEL_KLASYFIKACJA` (domyślnie równa `LLM_MODEL`). Nie jest jeszcze wpisana do `docker-compose.yml`.
5.5. Raport HTML nie pokazuje raportu jakości OCR (numery wierszy niepewnych są tylko w wyniku `ocr.czytaj`).
5.6. OCR: „słowa znane słownikowi” to miara zastępcza. Błąd w nazwisku albo w numerze bez sumy kontrolnej przejdzie niezauważony. Model wizyjny `qwen3-vl:8b` jako trzeci odczyt wierszy niepewnych nie był testowany.
5.7. Drobne wady tekstu zanonimizowanego: przyimek nie dopasowuje się do surogatu („we Elblągu”), firma w liczbie mnogiej dostaje surogat męski, skrótowiec i pełna nazwa firmy dostają różne surogaty, nazwa firmy spoza słownika w niewidzianym przypadku bywa źle odmieniona (trafia na listę niepewnych).
5.8. Etapy planu jeszcze niezaczęte: 3 (podmiana w plikach PDF i DOCX, kontrola wycieku na pliku), 4 (workflowy n8n dla trybu A), 6 (chatbot), 7 (wsad). Etap 5 (skany) jest zrobiony częściowo: OCR jest, odtwarzania dokumentu ze skanu nie ma.

5.9. Plan dalszych prac: `PLAN.md` (fazy A do F), pomysły: `PLAN-uwagi.md`, oba w `PLAN.pdf`.
5.10. Workflow n8n „Anonimizacja v2 « Deanonimizuj wynik” (id `nje0xEFugGXnrtgF`, aktywny, formularz `http://localhost:5686/form/deanonimizuj-wynik`): formularz (sesja, tekst) → `POST /sesje/{id}/deanonimizuj-tekst` → strona z tekstem i tabelą miejsc niepewnych. Błąd HTTP: IF na „Nie ma sesji” → komunikat o złej sesji, w innym razie komunikat o awarii serwisu. Ścieżka główna przetestowana 2026-11-17 na danych fikcyjnych (sesja testowa `70f5fbc93940`): osoby w celowniku i dopełniaczu, PESEL, firma, miasta wróciły poprawnie, „Mirtasie” wrócił jako „Stalmetie” i trafił na listę niepewnych (znany błąd, `PLAN.md` 3.6). Gałęzie „Brak sesji” i „Błąd serwisu” (kontener zatrzymany) przetestowane 2026-11-17, obie działają. Sesja przetrwała restart Dockera.
5.11. Adresy n8n: 2026-11-17 za zgodą użytkownika zmienione w `C:\Moja nauka\Szkolenie agenci AI\training-mateusz\.env` z tunelu `*.trycloudflare.com` na `http://localhost:5686/` (`N8N_TUNNEL=localhost`, `N8N_PROTOCOL=http`, `WEBHOOK_URL`, `N8N_EDITOR_BASE_URL`, `N8N_PROXY_HOPS=0`). Kopia poprzedniego `.env` i compose w `training-mateusz\backup\2026-11-17_*`. Kontener odtworzony przez `docker compose up -d --no-deps n8n-itself`. Formularz zwraca teraz `formWaitingUrl` na localhost, wykonanie 8381 zakończone statusem success. Przeglądarka wbudowana Claude blokuje POST na localhost (`ERR_BLOCKED_BY_CLIENT`), więc formularza nie da się w niej wysłać; testować curlem albo w zwykłej przeglądarce. Wiszące wykonania testowe 8376–8380 usunięte za zgodą użytkownika.
5.12. Eksport workflowów (2026-11-17, `n8n export:workflow --pretty` z `n8n-training`) w katalogu `workflowy/`: `anonimizacja-v1-dokumenty.json` (id `t2bGisJZ9WtC9y67`, 39 węzłów) i `anonimizacja-v2-deanonimizuj-wynik.json` (id `nje0xEFugGXnrtgF`, 6 węzłów). Bez pinData i bez sekretów, credentiale tylko jako odwołania (Ollama, OpenAI). Starszy `workflow.json` w katalogu projektu to wcześniejsza wersja v1. Plan użytkownika: instancja n8n na 5686 (`training-mateusz`) zostaje bez zmian, a compose projektu (`serwis/docker-compose.yml`) ma dostać własne n8n na porcie 5687, do którego te workflowy zostaną zaimportowane.
5.13. Stos `anonimizacja` z własnym n8n na 5687 uruchomiony 2026-11-17 (szczegóły w 7.1). Sprawdzone: healthz 5687 i 5686, `/zdrowie` anonimizatora (baza, docling, ollama ok), połączenie n8n 5687 → `http://anonimizator:8000` i → Ollama. 5.14. Instancja 5687 skonfigurowana 2026-11-17: konto właściciela (użytkownik), serwer MCP `n8n-anonimizacja` w `.mcp.json` katalogu nadrzędnego (klucz wygasa 24.11.2026, klucz `n8n-local` 21.11.2026). Oba workflowy zaimportowane z `workflowy/` z tymi samymi id. „Deanonimizuj wynik” aktywny pod `http://127.0.0.1:5687/form/deanonimizuj-wynik`, test curlem na sesji `70f5fbc93940` zakończony statusem success. v1 nieaktywny: Data Table `anonimizacja_mapowania` utworzona na nowo (id `4ePMzm1FvJkNlavE`, bez wierszy), credential „Ollama account” (`http://host.docker.internal:11434`) podpięty. Brakuje credentiala OpenAI (klucz wpisuje użytkownik w UI, węzeł „OpenAI (zewnętrzny)”). Katalogi `n8n/pliki/anonimizacja/{_zasoby,raporty,zanonimizowane}` utworzone, skopiowany tylko `_zasoby/Courier_New.ttf`, dokumentów z training nie kopiowano. Kopia „Deanonimizuj wynik” na 5686 wyłączona za zgodą użytkownika (formularz tam zwraca 404), workflow został w instancji.

## 6. Zasady pracy ustalone z użytkownikiem

6.1. Odpowiedzi po polsku, zwięźle. Punkty wyłącznie w numeracji 1., 1.1., 1.1.1., ciągłej w obrębie jednej wypowiedzi (pytania dostają kolejne numery główne). Bez myślników i wypunktowań.
6.2. Bez list pojęć w kodzie. Mechanizmy mają być uniwersalne.
6.3. Każdy błąd zgłoszony na prawdziwym dokumencie dostaje test na danych fikcyjnych w zestawie wzorcowym (to testy, nie listy używane przez silnik).
6.4. Tekst zanonimizowany ma zachować sens: nazwy ogólne zostają, w nazwach opisowych zmienia się tylko człon identyfikujący, daty, kwoty i numery wewnętrzne („załącznik numer 2”) zostają.
6.5. Prawdziwe dokumenty (`serwis/testy/prawdziwe/`) przetwarzać lokalnie i nie wypisywać ich oryginalnej treści do rozmowy. Oceniać po wersji zanonimizowanej, licznikach i kształtach. Wycieki ocenia użytkownik w raporcie HTML.
6.6. Długich pomiarów nie uruchamiać bez uprzedzenia o czasie. Użytkownik przerwał pomiar trwający kilka minut.
6.7. Lokalne repozytorium Git w katalogu projektu (od 2026-11-17, gałąź `main`, bez zdalnego). `.gitignore` wyklucza prawdziwe dane (`serwis/testy/prawdziwe/`, `serwis/dane/`, `n8n/`), sekrety (`.env`) i pamięć podręczną pomiarów (`serwis/testy/wyniki/cache_*.json`). Każda zmiana kodu kończy się commitem z wynikiem pomiaru zestawu w opisie. Przed `git add` sprawdzić `git status`, czy nie wchodzi nic z danych prawdziwych.

## 7. Środowisko

7.1. Docker: od 2026-11-17 projekt ma własny stos `anonimizacja` (`serwis/docker-compose.yml`, sekrety w `serwis/.env`): `anonimizator`, `anonimizacja-n8n` (n8n 2.33.7, `http://127.0.0.1:5687`, celowo 127.0.0.1, nie localhost, żeby ciasteczka nie kolidowały z 5686), `anonimizacja-n8n-baza` (Postgres 15), `anonimizacja-docling` (bez portu na hoście). Dane n8n w `n8n/dane`, `n8n/baza`, pliki dla węzłów Read/Write w `n8n/pliki` (w kontenerze `/data/shared`). Stos nie zależy od `C:\Moja nauka\Szkolenie agenci AI\training-mateusz` (n8n na 5686, nie modyfikować tamtego compose). Instancja 5686 nie widzi już anonimizatora (inna sieć), więc tamtejsza kopia „Deanonimizuj wynik” nie działa. Limit RAM Dockera: 7,6 GB, oba stosy w spoczynku zajmują ok. 2,9 GB, w tym dwa Doclingi po ok. 0,85 GB.
7.2. Ollama natywnie na Windows, modele: `gemma4:e4b` (używany), `qwen3-vl:8b`, `SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M`, `gemma4:26b`. GPU: RTX 4070 Laptop, 8 GB VRAM.
7.3. Na hoście nie ma Pythona. Wszystko uruchamia się w kontenerze przez `docker compose exec anonimizator python …`. Katalogi `serwis/app` i `serwis/testy` są montowane, zmiana kodu nie wymaga przebudowy obrazu.
7.4. Zmiany w kodzie robione były skryptami łatek uruchamianymi w kontenerze. Przed edycją pliku narzędziem Edit trzeba go ponownie odczytać, bo treść na dysku różni się od tej z początku sesji.

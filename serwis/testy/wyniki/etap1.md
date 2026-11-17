# Etap 1: pomiar detekcji

Dokumenty: 6, znaków: 12791, encji wzorcowych: 218.

Wartości w kolumnach typów: w pełni pokryte / wszystkie.

| konfiguracja | recall | częściowe | brak | nadmiar | czas [s] | OSOBA | FIRMA | ADRES | MIEJSCE | NAZWA | PESEL | NIP | REGON | KRS | IBAN | TELEFON | EMAIL | DOWOD | SYGNATURA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| regex+spacy+hf+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 99.5% | 1 | 0 | 20 | 351.7 | 81/81 | 41/42 | 12/12 | 19/19 | 11/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| regex+spacy+hf+llm:gemma4:e4b | 99.1% | 2 | 0 | 29 | 118.0 | 81/81 | 41/42 | 11/12 | 19/19 | 11/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| regex+hf+llm:gemma4:e4b | 97.7% | 3 | 2 | 13 | 117.7 | 79/81 | 40/42 | 11/12 | 19/19 | 11/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| regex+spacy+llm:gemma4:e4b | 97.7% | 3 | 2 | 20 | 115.4 | 81/81 | 40/42 | 11/12 | 19/19 | 9/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| regex+hf+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 97.2% | 4 | 2 | 6 | 351.4 | 79/81 | 38/42 | 12/12 | 19/19 | 11/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| regex+spacy+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 95.9% | 5 | 4 | 17 | 349.1 | 80/81 | 37/42 | 12/12 | 18/19 | 9/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| regex+spacy+hf | 95.9% | 9 | 0 | 30 | 2.9 | 81/81 | 37/42 | 10/12 | 19/19 | 9/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| spacy+hf+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 95.4% | 3 | 7 | 20 | 351.7 | 81/81 | 41/42 | 10/12 | 19/19 | 11/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 9/10 | 9/13 | 2/2 | 5/7 |
| hf+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 92.7% | 6 | 10 | 6 | 351.4 | 79/81 | 38/42 | 10/12 | 19/19 | 11/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 9/10 | 9/13 | 2/2 | 4/7 |
| spacy+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 91.7% | 7 | 11 | 17 | 349.1 | 80/81 | 37/42 | 10/12 | 18/19 | 9/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 9/10 | 9/13 | 2/2 | 5/7 |
| regex+hf | 90.4% | 17 | 4 | 14 | 2.6 | 75/81 | 31/42 | 10/12 | 19/19 | 9/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| spacy+hf+llm:gemma4:e4b | 88.5% | 9 | 16 | 29 | 118.0 | 81/81 | 41/42 | 5/12 | 19/19 | 11/11 | 2/4 | 3/6 | 1/3 | 0/3 | 4/5 | 8/10 | 11/13 | 2/2 | 5/7 |
| hf+llm:gemma4:e4b | 87.2% | 10 | 18 | 13 | 117.7 | 79/81 | 40/42 | 5/12 | 19/19 | 11/11 | 2/4 | 3/6 | 1/3 | 0/3 | 4/5 | 8/10 | 11/13 | 2/2 | 5/7 |
| regex+spacy | 86.7% | 18 | 11 | 20 | 0.3 | 80/81 | 25/42 | 10/12 | 18/19 | 3/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| spacy+llm:gemma4:e4b | 86.2% | 12 | 18 | 20 | 115.4 | 81/81 | 40/42 | 3/12 | 19/19 | 9/11 | 2/4 | 3/6 | 1/3 | 0/3 | 4/5 | 8/10 | 11/13 | 2/2 | 5/7 |
| regex+llm:gemma4:e4b | 75.2% | 3 | 51 | 0 | 115.1 | 48/81 | 33/42 | 11/12 | 12/19 | 7/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| spacy+hf | 68.3% | 20 | 49 | 30 | 2.9 | 81/81 | 37/42 | 0/12 | 19/19 | 9/11 | 0/4 | 0/6 | 0/3 | 0/3 | 0/5 | 0/10 | 2/13 | 0/2 | 1/7 |
| llm:gemma4:e4b | 63.8% | 12 | 67 | 0 | 115.1 | 48/81 | 33/42 | 3/12 | 12/19 | 7/11 | 2/4 | 3/6 | 1/3 | 0/3 | 4/5 | 8/10 | 11/13 | 2/2 | 5/7 |
| regex+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 62.8% | 3 | 78 | 0 | 348.8 | 35/81 | 25/42 | 12/12 | 5/19 | 7/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |
| hf | 61.5% | 28 | 56 | 14 | 2.6 | 75/81 | 31/42 | 0/12 | 19/19 | 9/11 | 0/4 | 0/6 | 0/3 | 0/3 | 0/5 | 0/10 | 0/13 | 0/2 | 0/7 |
| spacy | 59.2% | 29 | 60 | 20 | 0.3 | 80/81 | 25/42 | 0/12 | 18/19 | 3/11 | 0/4 | 0/6 | 0/3 | 0/3 | 0/5 | 0/10 | 2/13 | 0/2 | 1/7 |
| llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M | 58.3% | 4 | 87 | 0 | 348.8 | 35/81 | 25/42 | 10/12 | 5/19 | 7/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 9/10 | 9/13 | 2/2 | 4/7 |
| regex | 28.9% | 2 | 153 | 0 | 0.0 | 0/81 | 0/42 | 10/12 | 0/19 | 0/11 | 4/4 | 6/6 | 3/3 | 3/3 | 5/5 | 10/10 | 13/13 | 2/2 | 7/7 |

## Pominięte w najlepszej konfiguracji (regex+spacy+hf+llm:SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M)

1. `01_umowa_uslugi` FIRMA „Sąd Rejonowy Poznań – Nowe Miasto i Wilda w Poznaniu” (42/43): …u Sądowego prowadzonego przez Sąd Rejonowy Poznań – Nowe Miasto i Wilda w Poznaniu pod numerem KRS 000…

## Nadmiar w najlepszej konfiguracji (16 unikalnych)

„Dziale Rozwoju Produktu”, „Kodeksu”, „Krajowego Rejestru Sądowego”, „Nadzwyczajnego Zgromadzenia Wspólników”, „Pracodawcy”, „Spółka”, „Spółki”, „Spółkę”, „VAT”, „WZ.

Wskazuję,”, „Zarządu”, „Zgromadzenia”, „Zgromadzenie”, „Zgromadzenie Wspólników”, „Zgromadzeniu”, „„Pracodawcą””

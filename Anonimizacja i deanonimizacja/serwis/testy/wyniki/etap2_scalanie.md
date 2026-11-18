# Etap 2: scalanie zakresów

| wariant | detektory | pełne | częściowe | brak | nadmiar |
|---|---|---|---|---|---|
| surowe | bez LLM | 208/217 (95.9%) | 9 | 0 | 34 |
| scalone | bez LLM | 214/217 (98.6%) | 3 | 0 | 4 |
| surowe | z LLM | 215/217 (99.1%) | 2 | 0 | 33 |
| scalone | z LLM | 217/217 (100.0%) | 0 | 0 | 4 |

## Scalone, bez LLM: pominięte

1. `04_umowa_o_prace` NAZWA „TermoLak 2” (8/9): …macji dotyczących technologii TermoLak 2, również po ustaniu…
1. `05_korespondencja_email` NAZWA „Liść Monstery” (8/12): …w doniczek ceramicznych serii Liść Monstery. Kierowca odmówił w…
1. `05_korespondencja_email` FIRMA „Zielona Paczka sp. z o.o.” (14/21): …wczyk Kierownik ds. logistyki Zielona Paczka sp. z o.o. ul. Głogowska 218, …

## Scalone, bez LLM: nadmiar

„1/06/2025”, „2/06/2025”, „3/06/2025”, „Krajowego Rejestru Długów”

## Scalone, z LLM: pominięte

Brak.

## Scalone, z LLM: nadmiar

„1/06/2025”, „2/06/2025”, „3/06/2025”, „Krajowego Rejestru Długów”

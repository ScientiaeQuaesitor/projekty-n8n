"""Detekcja nazw własnych lokalnym LLM przez Ollamę. Model zwraca wartości, a pozycje w tekście
ustalamy sami przez wyszukanie dokładnych wystąpień, więc model nie może „przesunąć” encji."""
import os

import httpx
import regex as re

from .ner import fragmenty
from .typy import Encja

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma4:e4b")
TYPY_LLM = ["OSOBA", "FIRMA", "ADRES", "MIEJSCE", "NAZWA", "INNE"]

PROMPT = """Jesteś detektorem nazw własnych i danych identyfikujących w polskich dokumentach. Wypisz WSZYSTKIE takie fragmenty z tekstu użytkownika.

Typy:
OSOBA: imię, nazwisko, imię i nazwisko, inicjał z nazwiskiem, zdrobnienie imienia. Bez tytułów i zwrotów (pan, pani, dr, mec.).
FIRMA: nazwa firmy, spółki, kancelarii, banku, sądu, urzędu, fundacji, także skrócona lub potoczna.
ADRES: adres pocztowy lub jego część (ulica z numerem, kod pocztowy z miejscowością).
MIEJSCE: miejscowość, dzielnica, region występujące poza adresem.
NAZWA: nazwa własna projektu, produktu, systemu, marki, programu, technologii firmowej.
INNE: każdy inny identyfikator (numer umowy, faktury, sygnatura, numer rachunku, PESEL, NIP, telefon, e-mail).

Zasady:
1. Pole "tekst" kopiuj z dokumentu znak po znaku, w tej samej formie gramatycznej i z tą samą wielkością liter. Nie zamieniaj na mianownik.
2. Każdą formę wypisz osobno: "Jan Kowalski", "Kowalskiego", "Janem" to trzy pozycje.
3. Nie wypisuj stanowisk, dat, kwot, nazw ustaw ani ogólnych określeń stron (Zamawiający, Wykonawca, Spółka, Pracodawca).
4. W razie wątpliwości wypisz. Pominięcie jest gorsze niż nadmiar.
5. Gdy nic nie ma, zwróć pustą listę."""

SCHEMAT = {
    "type": "object",
    "properties": {"encje": {"type": "array", "items": {
        "type": "object",
        "properties": {"typ": {"type": "string", "enum": TYPY_LLM}, "tekst": {"type": "string"}},
        "required": ["typ", "tekst"],
    }}},
    "required": ["encje"],
}


class BladLLM(RuntimeError):
    pass


def _zapytaj(kawalek: str, model: str) -> list[dict]:
    r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
        "model": model,
        "stream": False,
        "think": False,
        "format": SCHEMAT,
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": kawalek}],
    })
    if r.status_code != 200:
        raise BladLLM(f"Ollama {r.status_code}: {r.text[:300]}")
    import json
    try:
        encje = json.loads(r.json()["message"]["content"])["encje"]
    except Exception as e:
        raise BladLLM(f"Model {model} nie zwrócił poprawnego JSON: {e}") from e
    return [e for e in encje if isinstance(e, dict)]


PROMPT_WERYFIKACJA = """Dostajesz ponumerowane fragmenty polskiego dokumentu, każdy z kontekstem. Oceń każdy fragment:
W: nazwa własna konkretnej osoby, firmy, instytucji, miejscowości, dzielnicy, ulicy, produktu albo projektu.
O: określenie ogólne, czyli pojęcie prawne lub rola strony (Kupujący, Stawający, Strony), termin zdefiniowany w umowie (Lokal Mieszkalny, Nieruchomość Wspólna, Bank), nazwa ustawy, kodeksu, rozporządzenia lub uchwały wraz z jej opisem (Kodeks cywilny, ustawa o rewitalizacji, rozporządzenie o ochronie danych osobowych, „w sprawie ochrony osób fizycznych”), tytuł albo rodzaj dokumentu (Akt notarialny, Umowa sprzedaży), organ lub system państwowy wymieniony ogólnie (Parlament Europejski, Baza Danych Ksiąg Wieczystych, Krajowy Rejestr Sądowy), kategoria prawna (specjalna strefa ekonomiczna, obszar rewitalizacji), skrót redakcyjny, zwykłe słowo.
W razie wątpliwości wybierz W. Oceń wszystkie fragmenty."""

SCHEMAT_WERYFIKACJA = {
    "type": "object",
    "properties": {"oceny": {"type": "array", "items": {
        "type": "object",
        "properties": {"nr": {"type": "integer"}, "ocena": {"type": "string", "enum": ["W", "O"]}},
        "required": ["nr", "ocena"],
    }}},
    "required": ["oceny"],
}


def zweryfikuj(fragmenty_z_kontekstem: list[tuple[str, str]], model: str | None = None) -> set[str]:
    """Zwraca fragmenty ocenione jako określenia ogólne. Brak oceny oznacza pozostawienie fragmentu (ostrożnie)."""
    import json
    ogolne: set[str] = set()
    for i in range(0, len(fragmenty_z_kontekstem), 25):
        paczka = fragmenty_z_kontekstem[i:i + 25]
        tresc = "\n".join(f"{n + 1}. „{f}” | kontekst: …{k}…" for n, (f, k) in enumerate(paczka))
        r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
            "model": model or LLM_MODEL, "stream": False, "think": False, "format": SCHEMAT_WERYFIKACJA,
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "system", "content": PROMPT_WERYFIKACJA}, {"role": "user", "content": tresc}],
        })
        if r.status_code != 200:
            raise BladLLM(f"Ollama {r.status_code}: {r.text[:300]}")
        try:
            oceny = json.loads(r.json()["message"]["content"])["oceny"]
        except Exception as e:
            raise BladLLM(f"Model nie zwrócił poprawnego JSON przy weryfikacji: {e}") from e
        for o in oceny:
            if isinstance(o, dict) and o.get("ocena") == "O" and isinstance(o.get("nr"), int) and 1 <= o["nr"] <= len(paczka):
                ogolne.add(paczka[o["nr"] - 1][0])
    return ogolne


LLM_MODEL_KLASYFIKACJA = os.environ.get("LLM_MODEL_KLASYFIKACJA", LLM_MODEL)
KATEGORIE = ["OSOBA", "FIRMA", "PRODUKT", "MIEJSCE", "INSTYTUCJA", "AKT_PRAWNY", "DOKUMENT", "POJECIE"]

PROMPT_KLASYFIKACJA = """Dostajesz ponumerowane fragmenty polskiego dokumentu, każdy z kontekstem. Przypisz każdemu fragmentowi jedną kategorię.

OSOBA: konkretna osoba fizyczna.
FIRMA: nazwa własna konkretnego podmiotu prywatnego (spółki, przedsiębiorcy, banku, fundacji, stowarzyszenia, sieci sklepów), czyli nazwa wybrana przez właściciela, która odróżnia ten podmiot od innych podmiotów tego samego rodzaju.
PRODUKT: nazwa własna produktu, projektu, systemu informatycznego albo marki należącej do konkretnej firmy, także nazwa nadana projektowi lub produktowi, gdy jest zwykłym słowem (nazwa kodowa projektu).
MIEJSCE: miejscowość, dzielnica, osiedle, ulica, region.
INSTYTUCJA: organ władzy lub instytucja publiczna, czyli sąd, urząd, ministerstwo, minister, rada gminy, organ państwa lub Unii Europejskiej, a także system, portal, baza danych, rejestr, strefa lub obszar ustanowione przez państwo albo przepisy. System państwowy to INSTYTUCJA, nie PRODUKT.
AKT_PRAWNY: ustawa, kodeks, rozporządzenie, dyrektywa, uchwała albo fragment jej tytułu.
DOKUMENT: rodzaj lub tytuł dokumentu, czynności prawnej albo orzeczenia.
POJECIE: pojęcie prawne lub ogólne, rola strony, termin zdefiniowany w dokumencie, nagłówek, zwykłe słowo.

Dla każdego fragmentu najpierw napisz w polu "uzasadnienie" jedno krótkie zdanie: czym ten fragment jest w tym dokumencie. Dopiero potem wybierz kategorię zgodną z uzasadnieniem.

Kieruj się kontekstem, nie samym brzmieniem. Nazwa złożona ze zwykłych słów może być firmą albo produktem, jeśli kontekst mówi o konkretnym podmiocie. Samo określenie rodzaju podmiotu lub zawodu, także pisane wielką literą i połączone z miejscowością (rodzaj kancelarii, sądu, urzędu albo strefy w danym mieście), to INSTYTUCJA albo POJECIE, nie FIRMA: taki fragment pasuje do wielu podmiotów, a miejscowość i nazwiska są podmieniane osobno. Gdy nie masz pewności, czy fragment wskazuje konkretną osobę lub konkretny podmiot prywatny, wybierz OSOBA albo FIRMA. Oceń wszystkie fragmenty."""

def _schemat_klasyfikacji(z_uzasadnieniem: bool) -> dict:
    pola = {"nr": {"type": "integer"}}
    if z_uzasadnieniem:
        pola["uzasadnienie"] = {"type": "string"}
    pola["kategoria"] = {"type": "string", "enum": KATEGORIE}
    return {"type": "object", "properties": {"oceny": {"type": "array", "items": {
        "type": "object", "properties": pola, "required": list(pola)}}}, "required": ["oceny"]}


# Trzy niezależne sposoby zadania tego samego pytania. Pojedyncza ocena modelu 8B jest niestabilna
# (zmiana wielkości paczki odwraca część decyzji), więc o kategorii decyduje głosowanie.
WARIANTY_KLASYFIKACJI = {
    "lista": {"paczka": 20, "uzasadnienie": False},        # wiele fragmentów naraz, sama kategoria
    "uzasadnienie": {"paczka": 6, "uzasadnienie": True},   # mała paczka, zdanie uzasadnienia przed kategorią
    "pojedynczo": {"paczka": 1, "uzasadnienie": True},     # każdy fragment osobno
}
ZDANIE_UZASADNIENIA = 'Dla każdego fragmentu najpierw napisz w polu "uzasadnienie" jedno krótkie zdanie: czym ten fragment jest w tym dokumencie. Dopiero potem wybierz kategorię zgodną z uzasadnieniem.\n\n'
OPCJE_KLASYFIKACJI = {"temperature": 0, "num_ctx": 8192}
# Podnieść przy zmianie sposobu budowania zapytania w klasyfikuj(), której nie widać w prompcie ani ustawieniach
WERSJA_ZAPYTANIA_KLASYFIKACJI = 1


def odcisk_klasyfikacji(wariant: str, model: str | None = None) -> str:
    """Skrót wszystkiego, od czego zależy ocena: prompt, ustawienia wariantu, kategorie, opcje i model.
    Zmiana któregokolwiek unieważnia zapamiętane oceny bez ręcznego usuwania plików pamięci."""
    import hashlib
    import json
    tresc = json.dumps([WERSJA_ZAPYTANIA_KLASYFIKACJI, PROMPT_KLASYFIKACJA, ZDANIE_UZASADNIENIA, wariant,
                        WARIANTY_KLASYFIKACJI[wariant], KATEGORIE, OPCJE_KLASYFIKACJI, model or LLM_MODEL_KLASYFIKACJA],
                       ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(tresc.encode("utf-8")).hexdigest()[:12]


def klasyfikuj(fragmenty_z_kontekstem: list[tuple[str, str]], model: str | None = None, wariant: str = "lista",
               po_paczce=None) -> dict[str, str]:
    """Kategoria każdego fragmentu według LLM, jednym z wariantów pytania. Fragment bez oceny nie trafia do wyniku.
    po_paczce(paczka, oceny_paczki) jest wołane po każdym zapytaniu, żeby przerwany przebieg nie tracił ocen."""
    import json
    ust = WARIANTY_KLASYFIKACJI[wariant]
    prompt = PROMPT_KLASYFIKACJA if ust["uzasadnienie"] else PROMPT_KLASYFIKACJA.replace(ZDANIE_UZASADNIENIA, "")
    wynik: dict[str, str] = {}
    for i in range(0, len(fragmenty_z_kontekstem), ust["paczka"]):
        paczka = fragmenty_z_kontekstem[i:i + ust["paczka"]]
        tresc = "\n".join(f"{n + 1}. „{f}” | kontekst: …{k}…" for n, (f, k) in enumerate(paczka))
        r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=900, json={
            "model": model or LLM_MODEL_KLASYFIKACJA, "stream": False, "think": False, "format": _schemat_klasyfikacji(ust["uzasadnienie"]),
            "options": OPCJE_KLASYFIKACJI,
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": tresc}],
        })
        if r.status_code != 200:
            raise BladLLM(f"Ollama {r.status_code}: {r.text[:300]}")
        try:
            oceny = json.loads(r.json()["message"]["content"])["oceny"]
        except Exception as e:
            raise BladLLM(f"Model nie zwrócił poprawnego JSON przy klasyfikacji: {e}") from e
        oceny_paczki: dict[str, str] = {}
        for o in oceny:
            if isinstance(o, dict) and o.get("kategoria") in KATEGORIE and isinstance(o.get("nr"), int) and 1 <= o["nr"] <= len(paczka):
                oceny_paczki[paczka[o["nr"] - 1][0]] = o["kategoria"]
        wynik.update(oceny_paczki)
        if po_paczce:
            po_paczce(paczka, oceny_paczki)
    return wynik


def wykryj(tekst: str, model: str | None = None, limit: int = 3000) -> list[Encja]:
    model = model or LLM_MODEL
    wynik, widziane = [], set()
    for offset, kawalek in fragmenty(tekst, limit):
        if not kawalek.strip():
            continue
        for e in _zapytaj(kawalek, model):
            wartosc = str(e.get("tekst", "")).strip()
            typ = e.get("typ") if e.get("typ") in TYPY_LLM else "INNE"
            if len(wartosc) < 2:
                continue
            # Wszystkie wystąpienia w całym tekście, na granicach słów
            for m in re.finditer(r"(?<![\p{L}\d])" + re.escape(wartosc) + r"(?![\p{L}\d])", tekst):
                klucz = (m.start(), m.end())
                if klucz not in widziane:
                    widziane.add(klucz)
                    wynik.append(Encja(m.start(), m.end(), typ, "llm", m.group()))
    return sorted(wynik, key=lambda e: e.start)

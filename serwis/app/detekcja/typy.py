from dataclasses import dataclass, asdict

# Typy encji. MIEJSCE to miejscowość poza adresem (decyzja, czy ją podmieniać, jest otwarta: specyfikacja 6.3).
TYPY = [
    "OSOBA", "FIRMA", "ADRES", "MIEJSCE", "NAZWA",
    "PESEL", "NIP", "REGON", "KRS", "IBAN", "TELEFON", "EMAIL", "DOWOD", "SYGNATURA",
]


@dataclass(frozen=True)
class Encja:
    start: int
    end: int
    typ: str
    zrodlo: str  # regex | spacy | hf | llm
    tekst: str
    pewna: bool = True  # False np. dla numeru o poprawnym formacie, ale błędnej sumie kontrolnej

    def jako_dict(self) -> dict:
        return asdict(self)

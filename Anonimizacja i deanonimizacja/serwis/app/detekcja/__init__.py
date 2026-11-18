from . import llm, ner, regexy
from .typy import Encja

DETEKTORY = {
    "regex": regexy.wykryj,
    "spacy": ner.wykryj_spacy,
    "hf": ner.wykryj_hf,
    "llm": llm.wykryj,
}


def wykryj(tekst: str, detektory: list[str]) -> list[Encja]:
    """Suma wyników wybranych detektorów, bez scalania nakładających się zakresów."""
    wynik: list[Encja] = []
    for nazwa in detektory:
        wynik.extend(DETEKTORY[nazwa](tekst))
    return sorted(wynik, key=lambda e: (e.start, -e.end))

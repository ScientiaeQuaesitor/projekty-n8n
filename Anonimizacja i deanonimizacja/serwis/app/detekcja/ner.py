"""Klasyczne modele NER: spaCy i model token-classification z Hugging Face (FastPDN).
Modele ładują się leniwie przy pierwszym użyciu i zostają w pamięci."""
import os
from functools import lru_cache

import regex as re

from .typy import Encja

SPACY_MODEL = os.environ.get("SPACY_MODEL", "pl_core_news_lg")
HF_MODEL = os.environ.get("HF_NER_MODEL", "clarin-pl/FastPDN")

SPACY_MAPA = {"persName": "OSOBA", "orgName": "FIRMA", "placeName": "MIEJSCE", "geogName": "MIEJSCE"}

# Etykiety KPWr (FastPDN) pomijane: przymiotniki, waluty, stanowiska, technologie i podobne
HF_POMIN = ("nam_adj", "nam_oth_currency", "nam_oth_data_format", "nam_oth_license", "nam_oth_position",
            "nam_oth_tech", "nam_liv_habitant", "nam_org_nation", "nam_liv_god", "nam_num_phone")


def _hf_typ(etykieta: str) -> str | None:
    if etykieta.startswith(HF_POMIN):
        return None
    if etykieta.startswith("nam_liv"):
        return "OSOBA"
    if etykieta.startswith("nam_org"):
        return "FIRMA"
    if etykieta.startswith(("nam_fac_road", "nam_fac_square", "nam_num_house")):
        return "ADRES"
    if etykieta.startswith(("nam_loc", "nam_fac")):
        return "MIEJSCE"
    if etykieta.startswith(("nam_pro", "nam_eve", "nam_oth")):
        return "NAZWA"
    # Modele o prostym zestawie etykiet (PER, ORG, LOC, MISC)
    return {"PER": "OSOBA", "ORG": "FIRMA", "LOC": "MIEJSCE", "MISC": "NAZWA"}.get(etykieta)


def fragmenty(tekst: str, limit: int = 900) -> list[tuple[int, str]]:
    """Dzieli tekst na kawałki do `limit` znaków, tnąc na końcach linii lub zdań. Zwraca (offset, kawałek)."""
    out, start = [], 0
    while start < len(tekst):
        end = min(start + limit, len(tekst))
        if end < len(tekst):
            okno = tekst[start:end]
            ciecie = max(okno.rfind("\n"), max((m.end() for m in re.finditer(r"[.!?;]\s", okno)), default=-1))
            if ciecie < limit // 3:
                ciecie = okno.rfind(" ")
            if ciecie > 0:
                end = start + ciecie
        out.append((start, tekst[start:end]))
        start = end
    return out


@lru_cache(maxsize=1)
def _spacy():
    import spacy
    return spacy.load(SPACY_MODEL, disable=["lemmatizer"])


@lru_cache(maxsize=1)
def _hf():
    from transformers import pipeline
    return pipeline("token-classification", model=HF_MODEL, aggregation_strategy="first", device=-1)


def wykryj_spacy(tekst: str) -> list[Encja]:
    doc = _spacy()(tekst)
    return [Encja(e.start_char, e.end_char, SPACY_MAPA[e.label_], "spacy", e.text)
            for e in doc.ents if e.label_ in SPACY_MAPA and e.text.strip()]


def wykryj_hf(tekst: str) -> list[Encja]:
    wynik = []
    for offset, kawalek in fragmenty(tekst):
        if not kawalek.strip():
            continue
        for e in _hf()(kawalek):
            typ = _hf_typ(e["entity_group"])
            if typ is None:
                continue
            a, b = offset + e["start"], offset + e["end"]
            while a < b and tekst[a].isspace():
                a += 1
            if b > a:
                wynik.append(Encja(a, b, typ, "hf", tekst[a:b]))
    return wynik

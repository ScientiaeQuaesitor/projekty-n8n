"""Głosowanie klasyfikacji przez n8n (PRZEKAZANIE 2.00.19) daje to samo co głosowanie w serwisie: te same głosy
każdego wariantu i te same kategorie, na fikcyjnych dokumentach wzorcowych, z pustą pamięcią ocen (model pytany
naprawdę). Drugi przebieg przez n8n z pamięcią z pierwszego nie może pytać modelu.
Uruchomienie (kilka minut, workflow musi być opublikowany):
docker exec -w /srv -e PYTHONPATH=/srv anonimizator python testy/test_glosowanie_n8n.py [dokument ...]"""
import sys
import time

from app.anonimizacja import silnik
from app.detekcja import llm
from app.detekcja.scal import scal
from app.ewaluacja.scalanie import wykryj_z_cache
from app.ewaluacja.wzorce import wczytaj

URL = "http://anonimizacja-n8n:5678/webhook/glosowanie"
dokumenty = wczytaj()
wybrane = sys.argv[1:] or ["03_notatka_spotkanie"]
bledy = 0
for dok in wybrane:
    tekst, _ = dokumenty[dok]
    encje = wykryj_z_cache({dok: (tekst, [])}, llm.LLM_MODEL)[dok]
    zakresy = scal(tekst, encje)
    wyniki = {}
    for droga, url in (("serwis", ""), ("n8n", URL)):
        llm.GLOSOWANIE_URL = url
        pamiec, czasy, t0 = {}, {}, time.time()
        kat = silnik.kategorie_zakresow(tekst, zakresy, pamiec, encje=encje, czasy=czasy)
        wyniki[droga] = (kat, pamiec)
        print(f"{dok} {droga}: {len(pamiec)} ocen, {time.time() - t0:.0f} s")
    (k1, p1), (k2, p2) = wyniki["serwis"], wyniki["n8n"]
    rozne_k = sorted(f for f in set(k1) | set(k2) if k1.get(f) != k2.get(f))
    rozne_p = sorted(k for k in set(p1) | set(p2) if p1.get(k) != p2.get(k))
    print(f"  różne kategorie: {len(rozne_k)} {rozne_k[:5]}  różne oceny: {len(rozne_p)} {rozne_p[:5]}")
    # Ponownie przez n8n z pamięcią: nic nowego do pytania, wynik ten sam
    llm.GLOSOWANIE_URL, czasy = URL, {}
    k3 = silnik.kategorie_zakresow(tekst, zakresy, dict(p2), encje=encje, czasy=czasy)
    zapytane = sum(czasy.get("klasyfikacja_n8n", {}).get("zapytane", {}).values())
    print(f"  z pamięci: zapytane {zapytane}, kategorie zgodne {k3 == k2}")
    bledy += len(rozne_k) + len(rozne_p) + zapytane + (k3 != k2)
print("ok" if not bledy else f"BŁĘDY: {bledy}")
sys.exit(1 if bledy else 0)

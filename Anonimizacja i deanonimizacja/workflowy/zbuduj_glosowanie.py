"""Buduje JSON workflowu „Anonimizacja v2 « Głosowanie klasyfikacji” (wypisuje na stdout). Wgrywanie (MCP zrywa połączenie
przy dłuższych węzłach Code): python zbuduj_glosowanie.py > anonimizacja-v2-glosowanie.json, potem docker cp do
anonimizacja-n8n i n8n import:workflow --input=…, publikacja w n8n."""
import json

ID = "QgipnuBxKHerRIKQ"
OLLAMA = "http://host.docker.internal:11434/api/chat"

PACZKA = r"""    const tresc = paczka.map((k, n) => `${n + 1}. „${k.fragment}” | kontekst: …${k.kontekst}…`).join('\n');"""

PACZKI_1 = r"""// Paczki pytań dla dwóch pierwszych wariantów (lista, uzasadnienie). Fragment z oceną z pamięci serwisu
// (wariant obecny w glosy, także z wartością null) nie jest pytany ponownie.
const z = $input.first().json.body;
const zapytania = [];
for (const w of z.warianty.slice(0, 2)) {
  const pytane = z.kandydaci.filter(k => !(w.nazwa in (k.glosy || {})));
  for (let i = 0; i < pytane.length; i += w.paczka) {
    const paczka = pytane.slice(i, i + w.paczka);
    // Ten sam zapis co detekcja.llm.klasyfikuj: odcisk ocen w serwisie zakłada identyczne zapytanie
""" + PACZKA + r"""
    zapytania.push({
      wariant: w.nazwa,
      fragmenty: paczka.map(k => k.fragment),
      body: { model: z.model, stream: false, think: false, format: w.format, options: z.opcje,
        messages: [{ role: 'system', content: w.prompt }, { role: 'user', content: tresc }] },
    });
  }
}
return [{ json: { zapytania } }];"""

OCENY = r"""// Odpowiedź modelu na każdą paczkę: kategoria z dozwolonej listy dla każdego numeru fragmentu. Fragment bez oceny
// dostaje null (serwis zapamiętuje brak oceny, żeby nie pytać drugi raz). Kolejność odpowiedzi = kolejność paczek,
// bo zapytania idą po jednym (batching 1), a błąd zapytania zatrzymuje workflow.
const paczki = $('ZRODLO').all();
const glosy = {};
$input.all().forEach((item, i) => {
  const p = paczki[i].json;
  let oceny;
  try {
    oceny = JSON.parse(item.json.message.content).oceny;
  } catch (e) {
    throw new Error(`Model nie zwrócił poprawnego JSON przy klasyfikacji (${p.wariant}): ${e.message}`);
  }
  const dozwolone = p.body.format.properties.oceny.items.properties.kategoria.enum;
  const odp = {};
  for (const o of Array.isArray(oceny) ? oceny : []) {
    if (o && dozwolone.includes(o.kategoria) && Number.isInteger(o.nr) && o.nr >= 1 && o.nr <= p.fragmenty.length) {
      odp[p.fragmenty[o.nr - 1]] = o.kategoria;
    }
  }
  const g = (glosy[p.wariant] = glosy[p.wariant] || {});
  for (const f of p.fragmenty) g[f] = odp[f] ?? null;
});
return [{ json: { glosy } }];"""

TRZECI = r"""// Trzeci, najdroższy wariant (pojedynczo) tylko dla nazw, przy których dwa pierwsze głosy się różnią, któregoś
// brakuje, albo nazwa ma budowę opisową (pole opisowa z serwisu). Ta sama reguła co silnik.kategorie_zakresow.
const z = $('Webhook głosowania').first().json.body;
const nowe = $('Oceny etap 1').isExecuted ? $('Oceny etap 1').first().json.glosy : {};
const [w1, w2, w3] = z.warianty;
const glos = (k, w) => (w.nazwa in (k.glosy || {})) ? k.glosy[w.nazwa] : (nowe[w.nazwa] || {})[k.fragment];
const trzeci = [], pytane = [];
for (const k of z.kandydaci) {
  const g = [glos(k, w1), glos(k, w2)].filter(Boolean);
  if (g.length < 2 || new Set(g).size > 1 || k.opisowa) {
    trzeci.push(k.fragment);
    if (!(w3.nazwa in (k.glosy || {}))) pytane.push(k);
  }
}
const zapytania = [];
for (let i = 0; i < pytane.length; i += w3.paczka) {
  const paczka = pytane.slice(i, i + w3.paczka);
""" + PACZKA + r"""
  zapytania.push({
    wariant: w3.nazwa,
    fragmenty: paczka.map(k => k.fragment),
    body: { model: z.model, stream: false, think: false, format: w3.format, options: z.opcje,
      messages: [{ role: 'system', content: w3.prompt }, { role: 'user', content: tresc }] },
  });
}
return [{ json: { trzeci, zapytania } }];"""

GLOSOWANIE = r"""// Głosowanie jak silnik.kategorie_zakresow: nazwa zostaje (kategoria z listy „zostaw”) tylko przy co najmniej dwóch
// takich głosach; remis i brak ocen oznaczają podmianę. Jeden głos „zostaw” przy podmianie daje SPORNE.
// Remis kategorii rozstrzyga wcześniejszy wariant. Trzeci głos liczy się tylko dla nazw wybranych do trzeciego etapu.
const z = $('Webhook głosowania').first().json.body;
const nowe = {};
for (const n of ['Oceny etap 1', 'Oceny etap 3']) {
  if (!$(n).isExecuted) continue;
  for (const [w, o] of Object.entries($(n).first().json.glosy)) nowe[w] = { ...(nowe[w] || {}), ...o };
}
const trzeci = new Set($('Trzeci głos: kto i paczki').first().json.trzeci);
const zostawKat = new Set(z.kategorie_zostaw);
const kategorie = {};
for (const k of z.kandydaci) {
  const g = [];
  z.warianty.forEach((w, nr) => {
    if (nr === 2 && !trzeci.has(k.fragment)) return;
    const v = (w.nazwa in (k.glosy || {})) ? k.glosy[w.nazwa] : (nowe[w.nazwa] || {})[k.fragment];
    if (v) g.push(v);
  });
  const zostaw = g.filter(x => zostawKat.has(x));
  const podmien = g.filter(x => !zostawKat.has(x));
  const strona = zostaw.length >= 2 ? zostaw : podmien;
  if (strona.length) {
    let naj = strona[0];
    for (const x of strona) {
      if (strona.filter(y => y === x).length > strona.filter(y => y === naj).length) naj = x;
    }
    kategorie[k.fragment] = naj;
  }
  if (zostaw.length && zostaw.length < 2) kategorie[k.fragment] = 'SPORNE:' + (kategorie[k.fragment] || 'FIRMA');
}
return [{ json: { kategorie, nowe_glosy: nowe } }];"""


def nid(n):
    return f"7f1c2a10-1b2c-4d3e-8f40-0a1b2c3d4e{n:02d}"


def code(n, nazwa, x, y, kod, why):
    return {"id": nid(n), "name": nazwa, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [x, y],
            "parameters": {"jsCode": kod}, "notes": why, "notesInFlow": True}


def jesli(n, nazwa, x, uwaga):
    return {"id": nid(n), "name": nazwa, "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [x, 0],
            "parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                                          "conditions": [{"id": f"a1b2c3d4-000{n % 10}-4000-8000-00000000000{n % 10}",
                                                          "leftValue": "={{ $json.zapytania.length }}", "rightValue": 0,
                                                          "operator": {"type": "number", "operation": "gt"}}],
                                          "combinator": "and"}, "options": {}},
            "notes": uwaga, "notesInFlow": True}


def podziel(n, nazwa, x):
    return {"id": nid(n), "name": nazwa, "type": "n8n-nodes-base.splitOut", "typeVersion": 1, "position": [x, -120],
            "parameters": {"fieldToSplitOut": "zapytania", "options": {}}}


def model(n, nazwa, x, why):
    return {"id": nid(n), "name": nazwa, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [x, -120],
            "retryOnFail": True, "maxTries": 2, "waitBetweenTries": 5000,
            "parameters": {"method": "POST", "url": OLLAMA, "sendBody": True, "specifyBody": "json",
                           "jsonBody": "={{ JSON.stringify($json.body) }}",
                           "options": {"timeout": 900000, "batching": {"batch": {"batchSize": 1, "batchInterval": 0}}}},
            "notes": why, "notesInFlow": True}


WHY_HTTP = ("Why HTTP: węzeł Ollama Chat Model nie ma pola format (schemat JSON odpowiedzi) ani think: false. "
            "Po jednym zapytaniu naraz: Ollama i tak liczy po kolei, a kolejka zapytań przekraczałaby limit czasu.")
WHY_OCENY = ("Why Code: odczyt JSON z treści odpowiedzi modelu i dopasowanie numerów do fragmentów paczki; "
             "żaden węzeł nie łączy odpowiedzi z paczką po pozycji.")

nodes = [
    {"id": nid(1), "name": "Webhook głosowania", "type": "n8n-nodes-base.webhook", "typeVersion": 2.1, "position": [0, 0],
     "webhookId": "3c6f1d2e-4a5b-4c7d-9e8f-0a1b2c3d4e5f",
     "parameters": {"httpMethod": "POST", "path": "glosowanie", "responseMode": "responseNode", "options": {}},
     "notes": "Woła go serwis anonimizator (detekcja.llm.glosowanie_n8n), gdy ma ustawione GLOSOWANIE_URL. Body: model, "
              "opcje, kategorie_zostaw, warianty (nazwa, paczka, prompt, format), kandydaci (fragment, kontekst, opisowa, "
              "glosy z pamięci serwisu). Prompt i pamięć ocen zostają w serwisie."},
    code(2, "Paczki: lista i uzasadnienie", 220, 0, PACZKI_1,
         "Why Code: Split Out i Aggregate rozważone — paczki po N fragmentów z numeracją w treści pytania nie dają się złożyć z węzłów."),
    jesli(3, "Są pytania? (etap 1)", 440, "Wszystkie oceny z pamięci serwisu: od razu do trzeciego głosu."),
    podziel(4, "Zapytania etap 1", 660),
    model(5, "Model: lista i uzasadnienie", 880, WHY_HTTP),
    code(6, "Oceny etap 1", 1100, -120, OCENY.replace("ZRODLO", "Zapytania etap 1"), WHY_OCENY),
    code(7, "Trzeci głos: kto i paczki", 1320, 0, TRZECI,
         "Why Code: IF i Filter rozważone — decyzja zależy od porównania głosów z dwóch źródeł (pamięć serwisu, etap 1) "
         "dla każdej nazwy, a potem paczki z numeracją."),
    jesli(8, "Są pytania? (etap 3)", 1540, "Dwa pierwsze głosy zgodne albo trzeci głos w pamięci serwisu: od razu do głosowania."),
    podziel(9, "Zapytania etap 3", 1760),
    model(10, "Model: pojedynczo", 1980, WHY_HTTP),
    code(11, "Oceny etap 3", 2200, -120, OCENY.replace("ZRODLO", "Zapytania etap 3"), WHY_OCENY),
    code(12, "Głosowanie", 2420, 0, GLOSOWANIE,
         "Why Code: Summarize rozważony — reguła większości z progiem dwóch głosów „zostaw”, remisem rozstrzyganym "
         "kolejnością wariantów i stanem SPORNE nie daje się wyrazić węzłami."),
    {"id": nid(13), "name": "Odpowiedź", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [2640, 0],
     "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}", "options": {"responseCode": 200}}},
]


def c(*cele):
    return {"main": [[{"node": t, "type": "main", "index": 0}] if t else [] for t in cele]}


connections = {
    "Webhook głosowania": c("Paczki: lista i uzasadnienie"),
    "Paczki: lista i uzasadnienie": c("Są pytania? (etap 1)"),
    "Są pytania? (etap 1)": c("Zapytania etap 1", "Trzeci głos: kto i paczki"),
    "Zapytania etap 1": c("Model: lista i uzasadnienie"),
    "Model: lista i uzasadnienie": c("Oceny etap 1"),
    "Oceny etap 1": c("Trzeci głos: kto i paczki"),
    "Trzeci głos: kto i paczki": c("Są pytania? (etap 3)"),
    "Są pytania? (etap 3)": c("Zapytania etap 3", "Głosowanie"),
    "Zapytania etap 3": c("Model: pojedynczo"),
    "Model: pojedynczo": c("Oceny etap 3"),
    "Oceny etap 3": c("Głosowanie"),
    "Głosowanie": c("Odpowiedź"),
}

print(json.dumps({"id": ID, "name": "Anonimizacja v2 « Głosowanie klasyfikacji", "active": False, "nodes": nodes,
                  "connections": connections, "settings": {"executionOrder": "v1", "errorWorkflow": "ZmyoOyeFadfW8IPI"},
                  "pinData": {}}, ensure_ascii=False, indent=2))

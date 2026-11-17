// ---- wspólna logika (identyczna w węzłach "Anonimizuj" i "Uzupełnij anonimizację") ----
const CHUNK = 3000, OVERLAP = 200;
const TYPES = ['NAME', 'COMPANY', 'ADDRESS', 'EMAIL', 'PHONE', 'PESEL', 'NIP'];
const TYPE_ALIAS = { PERSON: 'NAME', OSOBA: 'NAME', ORGANIZATION: 'COMPANY', ORG: 'COMPANY', FIRMA: 'COMPANY', ADRES: 'ADDRESS', TELEFON: 'PHONE', MAIL: 'EMAIL', 'E-MAIL': 'EMAIL' };
const PH_RX = /\[(?:NAME|COMPANY|ADDRESS|EMAIL|PHONE|PESEL|NIP)_\d+\]/g;

function splitText(text, size, overlap) {
  const out = [];
  let i = 0;
  while (i < text.length) {
    let end = Math.min(i + size, text.length);
    if (end < text.length) {
      const w = text.slice(i, end);
      let cut = w.lastIndexOf('\n\n');
      if (cut < size * 0.5) { const m = [...w.matchAll(/[.!?]\s/g)]; cut = m.length ? m[m.length - 1].index + 1 : -1; }
      if (cut < size * 0.5) cut = w.lastIndexOf(' ');
      if (cut <= 0) cut = w.length;
      end = i + cut;
    }
    out.push(text.slice(i, end));
    if (end >= text.length) break;
    const sp = text.indexOf(' ', end - overlap);
    i = overlap > 0 && sp > i && sp < end ? sp + 1 : end;
  }
  return out;
}

function parseEntities(items) {
  const out = [];
  for (const it of items) {
    const j = it.json;
    const raw = Array.isArray(j.entities) ? j : (j.text ?? j.output ?? j.response);
    let ents;
    try { ents = (typeof raw === 'string' ? JSON.parse(raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1)) : raw).entities; } catch (e) { /* niżej */ }
    if (!Array.isArray(ents)) throw new Error('Lokalny model nie zwrócił poprawnego JSON z encjami. Przerwano przed wysyłką do zewnętrznego AI.');
    for (const e of ents) {
      const t = String(e?.type || '').toUpperCase();
      const type = TYPE_ALIAS[t] || t;
      const value = String(e?.value ?? '').trim();
      if (!TYPES.includes(type) || value.length < 2 || /[\[\]]/.test(value)) continue;
      out.push({ type, value, gender: String(e?.gender || '').toLowerCase()[0] });
    }
  }
  return out;
}

const ENDINGS = new Set(['', 'a', 'ą', 'ę', 'e', 'y', 'i', 'u', 'o', 'em', 'im', 'ym', 'ie', 'ia', 'ię', 'ią', 'owi', 'ego', 'emu', 'ej', 'iej', 'iego', 'iemu', 'iem', 'ów', 'om', 'ami', 'ach', 'owie']);
const NAME_STOP = new Set(['pan', 'pani', 'pana', 'panu', 'panem', 'panią', 'państwo', 'dr', 'mgr', 'inż', 'prof', 'mec']);
const COMPANY_STOP = new Set(['sp', 'oo', 'sa', 'ska', 'spółka', 'spółki', 'spółce', 'spółkę', 'spółką', 'akcyjna', 'akcyjnej', 'ograniczoną', 'odpowiedzialnością', 'komandytowa', 'jawna', 'cywilna', 'firma', 'firmy', 'firmie', 'firmę', 'firmą']);
const LEGAL = String.raw`(?:Sp\.\s?z\s?o\.\s?o\.|S\.K\.A\.|S\.A\.|sp\.\s?k\.|sp\.\s?j\.|s\.c\.|[Ss]półka [Aa]kcyjna|[Ss]półka z ograniczoną odpowiedzialnością)`;

function stemVariants(lw) {
  const base = lw.replace(/[aąeęioóuy]+$/u, '');
  const v = new Set([base]);
  const m = base.match(/^(.+[^aąeęioóuy])i?e([^aąeęioóuy]{1,2})$/u); // Marek -> Mark, Paweł -> Pawł
  if (m) v.add(m[1] + m[2]);
  const k = base.match(/^(.+)io([^aąeęioóuy])$/u); // Kozioł -> Kozł
  if (k) v.add(k[1] + k[2]);
  for (const s of [...v]) { v.add(s.replace(/ó(?=[^ó]*$)/u, 'o')); v.add(s.replace(/ą(?=[^ą]*$)/u, 'ę')); }
  // Wymiany spółgłosek w odmianie: Agnieszce -> Agnieszk, Marcie -> Mart, Kindze -> King, Barbarze -> Barbar, Michale -> Michał, Budimpex -> Budimpeks
  for (const s of [...v]) for (const [a, b] of [['c', 'k'], ['c', 't'], ['dz', 'g'], ['dz', 'd'], ['rz', 'r'], ['l', 'ł'], ['x', 'ks']]) if (s.endsWith(a)) v.add(s.slice(0, -a.length) + b);
  return [...v].filter(s => s.length >= 3);
}
const SHORT_ENDINGS = new Set(['a', 'y', 'i', 'ie', 'ę', 'ą', 'o']); // dla imion trzyliterowych (Ewa, Ada, Iga)

// Rejestr rdzeni dla jednego typu (NAME albo COMPANY): łapie odmiany i formy skrócone
function makeStemmer(values, stop) {
  const stems = new Map(), short = new Map(), exact = new Map();
  const tokensOf = v => (v.match(/\p{L}+/gu) || []).map(t => t.toLowerCase()).filter(t => t.length >= 2 && !stop.has(t));
  const idOf = word => {
    const lw = word.toLowerCase();
    if (stop.has(lw)) return null;
    if (exact.has(lw)) return exact.get(lw);
    let best = null, bl = Infinity;
    for (const [s, id] of stems) if (s.length < bl && lw.startsWith(s) && ENDINGS.has(lw.slice(s.length))) { best = id; bl = s.length; }
    if (best === null) for (const [s, id] of short) if (lw.startsWith(s) && SHORT_ENDINGS.has(lw.slice(s.length))) best = id;
    return best;
  };
  // Od najkrótszych: formy podstawowe rejestrują rdzeń, a odmiany (Markowi, Budimpeksem) dopasowują się do już znanego
  const all = [...new Set(values.flatMap(tokensOf))].sort((a, b) => a.length - b.length);
  for (const lw of all) {
    if (idOf(lw) !== null) continue;
    const vs = stemVariants(lw);
    if (vs.length) {
      const id = vs.map(s => stems.get(s)).find(Boolean) || vs[0];
      for (const s of vs) if (!stems.has(s)) stems.set(s, id);
    } else if (lw.length === 3 && /[aąeęioóuy]$/u.test(lw)) short.set(lw.slice(0, 2), lw.slice(0, 2));
    else exact.set(lw, lw);
  }
  const keyOf = ids => [...new Set(ids)].sort().join('|');
  const keyOfValue = v => keyOf(tokensOf(v).map(idOf).filter(Boolean));
  const covers = v => { const t = tokensOf(v); return t.length > 0 && t.every(x => idOf(x) !== null); };
  const words = s => {
    const w = [];
    for (const m of s.matchAll(/\p{Lu}\p{L}*/gu)) { const id = idOf(m[0]); if (id !== null) w.push({ start: m.index, end: m.index + m[0].length, ids: [id] }); }
    return w;
  };
  const spans = s => {
    const out = [];
    for (const w of words(s)) {
      const last = out[out.length - 1];
      if (last && w.start - last.end === 1 && /[ -]/.test(s[last.end])) { last.end = w.end; last.ids.push(...w.ids); }
      else out.push({ ...w, ids: [...w.ids] });
    }
    return out;
  };
  return { keyOf, keyOfValue, words, spans, covers, empty: stems.size + short.size + exact.size === 0 };
}

// Formy tej samej osoby/firmy dostają jeden identyfikator, o ile przypisanie jest jednoznaczne
function groupKeys(keys) {
  const groups = [], of = new Map();
  for (const key of [...new Set(keys)].sort((a, b) => b.split('|').length - a.split('|').length)) {
    const ids = key.split('|');
    const cands = groups.filter(g => ids.every(i => g.ids.has(i)));
    if (cands.length === 1) of.set(key, cands[0]);
    else { const g = { ids: new Set(ids), key }; groups.push(g); of.set(key, g); }
  }
  return { groups, of };
}

function anonymize(text, entities) {
  const by = t => [...new Set(entities.filter(e => e.type === t).map(e => e.value))];
  const taken = new Uint8Array(text.length);
  const spans = [];
  const claim = (start, end, type, key, group) => {
    let s = start;
    while (s < end) {
      while (s < end && taken[s]) s++;
      let e = s;
      while (e < end && !taken[e]) e++;
      if (e <= s) break;
      let a = s, b = e;
      const whole = s === start && e === end;
      if (!whole) {
        while (a < b && /[\s,;:.()]/.test(text[a])) a++;
        while (b > a && /[\s,;:(]/.test(text[b - 1])) b--;
      }
      const frag = text.slice(a, b);
      if (whole) spans.push({ start: a, end: b, type, key, group });
      else if (frag.length >= 2 && /[\p{Lu}\d]/u.test(frag)) spans.push({ start: a, end: b, type, key: 'frag:' + frag.toLowerCase() });
      else { s = e; continue; }
      taken.fill(1, a, b);
      s = e;
    }
  };
  const digits = s => s.replace(/\D/g, '');
  const norm = s => s.toLowerCase().replace(/\s+/g, ' ').trim();
  const claimRx = (rx, type, keyFn) => { for (const m of text.matchAll(rx)) claim(m.index, m.index + m[0].length, type, keyFn(m[0])); };
  const claimValues = (values, type, keyFn, wordBound) => {
    for (const v of [...values].sort((a, b) => b.length - a.length)) {
      for (let i = text.indexOf(v); i !== -1; i = text.indexOf(v, i + 1)) {
        if (wordBound && (/[\p{L}\d]/u.test(text[i - 1] || '') || /[\p{L}\d]/u.test(text[i + v.length] || ''))) continue;
        claim(i, i + v.length, type, keyFn(v));
      }
    }
  };

  // 1. Identyfikatory o stałym formacie: regex niezależnie od LLM + wartości wskazane przez LLM
  const EMAIL_RX = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;
  const PHONE_RX = /(?<![\w+])(?:\+\d{1,3}[\s-]?)?(?:\d{3}[\s-]?\d{3}[\s-]?\d{3}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?!\d)/g;
  claimRx(EMAIL_RX, 'EMAIL', norm);
  claimRx(/(?<!\d)\d{11}(?!\d)/g, 'PESEL', digits);
  claimRx(/(?<![\d-])(?:PL\s?)?(?:\d{10}|\d{3}-\d{3}-\d{2}-\d{2}|\d{3}-\d{2}-\d{2}-\d{3})(?![\d-])/g, 'NIP', digits);
  claimRx(PHONE_RX, 'PHONE', v => digits(v).slice(-9));
  claimValues(by('EMAIL'), 'EMAIL', norm);
  claimValues(by('PESEL').filter(v => digits(v).length >= 9), 'PESEL', digits);
  claimValues(by('NIP').filter(v => digits(v).length >= 9), 'NIP', digits);
  claimValues(by('PHONE').filter(v => digits(v).length >= 7), 'PHONE', v => digits(v).slice(-9));

  // 2. Adresy: przed firmami i osobami, bo zawierają nazwiska patronów ulic
  claimValues(by('ADDRESS'), 'ADDRESS', norm);
  claimRx(/(?<!\p{L})(?:ul\.|ulic[aąęy]|al\.|alei|aleja|aleję|pl\.|placu?|os\.|osiedl[eu])\s+[\p{L}\d .'-]{2,50}?\s\d+[A-Za-z]?(?:\s?\/\s?\d+[A-Za-z]?)?(?:\s+(?:m\.|lok\.)\s?\d+)?(?:,?\s+\d{2}-\d{3}\s+\p{Lu}[\p{L}-]+(?:\s\p{Lu}[\p{L}-]+)?)?/gu, 'ADDRESS', norm);
  claimRx(/(?<!\d)\d{2}-\d{3}\s+\p{Lu}[\p{L}-]+(?:\s\p{Lu}[\p{L}-]+)?/gu, 'ADDRESS', norm);

  // 3. Firmy: rdzenie z nazw wskazanych przez LLM (plus regex po formie prawnej, gdy LLM firmę pominął)
  const nameValues = by('NAME');
  const ns = makeStemmer(nameValues, NAME_STOP);
  const companyValues = by('COMPANY').filter(v => !ns.covers(v)); // wartość rozpoznana też jako osoba zostaje osobą
  for (const m of text.matchAll(new RegExp(String.raw`(?:\p{Lu}[\p{L}\d&'-]*\s+){1,5}` + LEGAL, 'gu'))) {
    if (!companyValues.some(v => m[0].includes(v))) companyValues.push(m[0]);
  }
  const cs = makeStemmer(companyValues, COMPANY_STOP);
  const known = new Set(companyValues.map(cs.keyOfValue).filter(Boolean));
  const companySpans = s => {
    const out = [];
    for (const sp of cs.spans(s)) {
      if (known.has(cs.keyOf(sp.ids))) out.push(sp);
      else for (const w of cs.words(s.slice(sp.start, sp.end))) if (known.has(cs.keyOf(w.ids))) out.push({ start: sp.start + w.start, end: sp.start + w.end, ids: w.ids });
    }
    return out;
  };
  const cSpans = companySpans(text);
  const cGroups = groupKeys(cSpans.map(sp => cs.keyOf(sp.ids)));
  const legalRx = new RegExp(String.raw`^\s+` + LEGAL, 'u');
  for (const sp of cSpans) {
    const g = cGroups.of.get(cs.keyOf(sp.ids));
    const m = text.slice(sp.end, sp.end + 60).match(legalRx);
    claim(sp.start, sp.end + (m ? m[0].length : 0), 'COMPANY', 'g', g);
  }
  claimValues(companyValues, 'COMPANY', norm, true);
  for (const g of cGroups.groups) {
    g.type = 'COMPANY';
    g.original = companyValues.filter(v => text.includes(v) && cs.keyOfValue(v) === g.key).sort((a, b) => b.length - a.length)[0];
  }

  // 4. Osoby
  const nSpans = ns.spans(text);
  const nGroups = groupKeys(nSpans.map(sp => ns.keyOf(sp.ids)));
  for (const sp of nSpans) claim(sp.start, sp.end, 'NAME', 'g', nGroups.of.get(ns.keyOf(sp.ids)));
  claimValues(nameValues, 'NAME', norm, true);
  for (const g of nGroups.groups) {
    g.type = 'NAME';
    g.original = nameValues.find(v => text.includes(v) && ns.keyOfValue(v) === g.key); // tylko forma faktycznie obecna w tekście
    const votes = { m: 0, f: 0 };
    for (const e of entities) {
      if (e.type !== 'NAME' || !(e.gender in votes)) continue;
      const ids = ns.keyOfValue(e.value).split('|').filter(Boolean);
      if (ids.length && nGroups.groups.filter(x => ids.every(i => x.ids.has(i))).length === 1 && ids.every(i => g.ids.has(i))) votes[e.gender]++;
    }
    g.votes = votes;
  }

  // 5. Podmiana: numeracja identyfikatorów w kolejności wystąpień
  spans.sort((a, b) => a.start - b.start);
  const counters = {}, map = new Map();
  let out = '', pos = 0;
  for (const sp of spans) {
    const surface = text.slice(sp.start, sp.end);
    const id = sp.group || `${sp.type}:${sp.key}`;
    if (!map.has(id)) {
      counters[sp.type] = (counters[sp.type] || 0) + 1;
      const g = sp.group;
      const original = (g && g.original) || surface;
      let gender = '';
      if (sp.type === 'NAME') gender = g && g.votes.m !== g.votes.f ? (g.votes.m > g.votes.f ? 'm' : 'f') : (/a$/i.test(original.split(/[\s-]/)[0]) ? 'f' : 'm');
      map.set(id, { placeholder: `[${sp.type}_${counters[sp.type]}]`, type: sp.type, original, gender });
    }
    out += text.slice(pos, sp.start) + map.get(id).placeholder;
    pos = sp.end;
  }
  out += text.slice(pos);

  // 6. Kontrola wycieku
  const bare = out.replace(PH_RX, ' ');
  let leaks = 0;
  if (/[\w.+-]+@[\w-]+\.[\w-]+/.test(bare)) leaks++;
  if (/(?<!\d)\d{10,11}(?!\d)/.test(bare)) leaks++;
  if (!ns.empty) leaks += ns.spans(bare).length;
  if (!cs.empty) leaks += companySpans(bare).length;
  for (const e of entities) {
    if (e.value.length < 3 || !bare.includes(e.value)) continue;
    const wb = e.type === 'NAME' || e.type === 'COMPANY';
    if (!wb || new RegExp(`(?<![\\p{L}\\d])${e.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}\\d])`, 'u').test(bare)) leaks++;
  }
  return { out, entities: [...map.values()], leaks };
}
// ---- koniec wspólnej logiki ----

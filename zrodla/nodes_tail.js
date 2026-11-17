// Kod węzłów etapu deanonimizacji (osobny plik, bez zagnieżdżonych template literals)
const REPORT = String.raw`const report = String(($('Przygotuj części raportu').all().length > 1 ? $('Raport końcowy').first() : $('Raport częściowy').first()).json.text || '');
const TAG = /\[(NAME|COMPANY|ADDRESS|EMAIL|PHONE|PESEL|NIP)_(\d+)(?::(M|D|C|B|N|Ms|W))?\]/g;
const TYP = { NAME: 'osoba', COMPANY: 'firma', ADDRESS: 'adres' };
// Klucz formy: identyfikator + przypadek. Osoba i firma bez kodu to mianownik; adres bez kodu zostaje w formie z dokumentu
const formKey = (type, n, c) => !TYP[type] || (type === 'ADDRESS' && !c) ? null : '[' + type + '_' + n + ']:' + (c || 'M');
`;

exports.prepDecl = String.raw`// Why Code: wyłuskanie z raportu unikalnych par (identyfikator, przypadek) i pakowanie ich w partie dla lokalnego modelu
` + REPORT + String.raw`const orig = new Map($input.all().map(i => i.json).filter(r => r.placeholder).map(r => [r.placeholder, r.original]));
const genders = $('Uzupełnij anonimizację').first().json.genders || {};
const CASES = { M: 'mianownik', D: 'dopełniacz', C: 'celownik', B: 'biernik', N: 'narzędnik', Ms: 'miejscownik', W: 'wołacz' };
const pairs = new Map();
for (const [, type, n, c] of report.matchAll(TAG)) {
  const ph = '[' + type + '_' + n + ']';
  const key = formKey(type, n, c);
  if (!key || !orig.has(ph) || pairs.has(key)) continue;
  pairs.set(key, { typ: TYP[type], ...(type === 'NAME' ? { płeć: genders[ph] === 'f' ? 'kobieta' : 'mężczyzna' } : {}), tekst: orig.get(ph), przypadek: CASES[c || 'M'] });
}
const all = [...pairs.entries()];
if (!all.length) return [{ json: { none: true } }];
const BATCH = 8, out = [];
for (let i = 0; i < all.length; i += BATCH) {
  const batch = all.slice(i, i + BATCH);
  out.push({ json: { none: false, keys: batch.map(([k]) => k), prompt: JSON.stringify(batch.map(([, p], j) => ({ id: String(j + 1), ...p }))) } });
}
return out;
`;

exports.dean = String.raw`// Why Code: podmiana wielu identyfikatorów naraz z walidacją form odmienionych przez lokalny model; brak natywnego odpowiednika
` + REPORT + String.raw`const orig = new Map($('Pobierz mapowanie').all().map(i => i.json).filter(r => r.placeholder).map(r => [r.placeholder, r.original]));
// Forma z lokalnego modelu jest przyjmowana tylko wtedy, gdy jest odmianą oryginału (te same wyrazy, wspólny początek, te same cyfry)
const sameish = (a, b) => {
  const ta = a.match(/[\p{L}\d]+/gu) || [], tb = b.match(/[\p{L}\d]+/gu) || [];
  return ta.length === tb.length && ta.every((x, i) => {
    const y = tb[i];
    const xl = x.toLowerCase(), yl = y.toLowerCase();
    if (xl === yl) return true;
    if (/\d/.test(x) || /\d/.test(y)) return false;
    let p = 0;
    while (p < xl.length && p < yl.length && xl[p] === yl[p]) p++;
    return p >= Math.max(2, Math.min(xl.length, yl.length) - 3) && Math.abs(xl.length - yl.length) <= 4;
  });
};
const forms = new Map();
const prep = $('Przygotuj odmianę').all();
if (!prep[0].json.none) {
  const res = $('Odmień (Ollama)').all();
  prep.forEach((p, idx) => {
    let wyniki = [];
    try {
      const j = res[idx].json;
      const raw = Array.isArray(j.wyniki) ? j : (j.text ?? j.output ?? j.response);
      wyniki = (typeof raw === 'string' ? JSON.parse(raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1)) : raw).wyniki || [];
    } catch (e) { /* brak form: użyta zostanie forma z mapowania */ }
    p.json.keys.forEach((key, j) => {
      const w = wyniki.find(x => String(x?.id) === String(j + 1));
      const forma = String(w?.forma ?? '').trim().replace(/!+$/, '');
      if (forma && sameish(orig.get(key.slice(0, key.lastIndexOf(':'))), forma)) forms.set(key, forma);
    });
  });
}
let replaced = 0, inflected = 0, inflection_fallbacks = 0;
const out = report.replace(TAG, (m, type, n, c) => {
  const ph = '[' + type + '_' + n + ']';
  if (!orig.has(ph)) return m;
  replaced++;
  const key = formKey(type, n, c);
  if (!key) return orig.get(ph);
  const f = forms.get(key);
  if (f) inflected++; else inflection_fallbacks++;
  return f ?? orig.get(ph);
});
const first = $('Uzupełnij anonimizację').first().json;
return [{ json: {
  session_id: first.session_id,
  report: out,
  stats: { ...first.stats, report_parts: $('Przygotuj części raportu').all().length, placeholders_replaced: replaced, forms_inflected: inflected, inflection_fallbacks },
  unresolved_placeholders: out.match(/\[(?:NAME|COMPANY|ADDRESS|EMAIL|PHONE|PESEL|NIP)_\d+(?::\w+)?\]/g) || [],
} }];
`;

const fs = require('fs');
const P = require('./prompts');
const core = fs.readFileSync(__dirname + '/core.js', 'utf8');
const WHY = '// Why Code: dzielenie tekstu, dopasowanie odmian, łączenie form tej samej osoby i kontrola wycieku to pętle i regexy, których nie wyrazi żaden węzeł natywny\n';

exports.split = WHY + core + `
const text = $input.first().json.body?.text;
if (typeof text !== 'string' || !text.trim()) throw new Error('Brak pola "text" (string) w body żądania');
return splitText(text, CHUNK, OVERLAP).map((chunk, i) => ({ json: { i, chunk } }));
`;

exports.pass1 = WHY + core + `
const items = $input.all();
// Niepełny komplet fragmentów oznacza błąd lokalnego modelu; odpowiedź wysyła gałąź błędu
if (items.length !== $('Podziel na fragmenty').all().length) return [];
const r = anonymize($('Webhook').first().json.body.text, parseEntities(items));
// Wstępnie zanonimizowany tekst wraca do lokalnego modelu na drugi przebieg (weryfikację)
return splitText(r.out, CHUNK, OVERLAP).map((chunk, i) => ({ json: { i, chunk } }));
`;

exports.pass2 = WHY + core + `
const items = $input.all();
if (items.length !== $('Anonimizuj').all().length) return [];
const text = $('Webhook').first().json.body.text;
// Encje z obu przebiegów; anonimizacja liczona od nowa na oryginale, żeby identyfikatory były spójne
const r = anonymize(text, [...parseEntities($('Wykryj PII').all()), ...parseEntities(items)]);
if (r.leaks) throw new Error('Kontrola wycieku: ' + r.leaks + ' fragmentów danych osobowych nadal w tekście. Przerwano przed wysyłką do zewnętrznego AI.');

const session_id = String($execution.id);
const rows = r.entities.map(e => ({ json: { session_id, placeholder: e.placeholder, original: e.original } }));
// Wiersz-wartownik, gdy brak danych osobowych: utrzymuje przepływ i jest usuwany razem z sesją
if (!rows.length) rows.push({ json: { session_id, placeholder: '', original: '' } });
const by_type = {};
for (const e of r.entities) by_type[e.type] = (by_type[e.type] || 0) + 1;
Object.assign(rows[0].json, {
  anonymized_text: r.out,
  genders: Object.fromEntries(r.entities.filter(e => e.type === 'NAME').map(e => [e.placeholder, e.gender])),
  stats: { chars: text.length, chunks: $('Podziel na fragmenty').all().length, entities: by_type },
});
return rows;
`;

exports.parts = `// Why Code: podział na części z zachowaniem granic zdań i budowa legendy płci per część wymagają pętli
const PART = ${+process.env.PART || 80000}; // znaków na jedno wywołanie zewnętrznego modelu
const SINGLE = ${JSON.stringify(P.REPORT_SINGLE)};
const PARTIAL = ${JSON.stringify(P.REPORT_PART)};
const first = $('Uzupełnij anonimizację').first().json;
const text = first.anonymized_text;
const parts = [];
for (let i = 0; i < text.length;) {
  let end = Math.min(i + PART, text.length);
  if (end < text.length) {
    const w = text.slice(i, end);
    const cut = Math.max(w.lastIndexOf('\\n\\n'), w.lastIndexOf('. ') + 1, w.lastIndexOf(' '));
    if (cut > PART / 2) end = i + cut;
  }
  parts.push(text.slice(i, end));
  i = end;
}
const legend = part => {
  const l = Object.entries(first.genders || {}).filter(([ph]) => part.includes(ph)).map(([ph, g]) => ph + ' – ' + (g === 'f' ? 'kobieta' : 'mężczyzna'));
  return l.length ? 'Legenda płci osób: ' + l.join('; ') + '.' : 'Legenda płci osób: brak osób.';
};
const legend_all = legend(text);
return parts.map((part, i) => ({ json: { i, total: parts.length, system: parts.length > 1 ? PARTIAL : SINGLE, legend: legend(part), legend_all, part } }));
`;

Object.assign(exports, require('./nodes_tail'));

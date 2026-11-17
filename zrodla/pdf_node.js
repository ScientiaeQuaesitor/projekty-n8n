// Why Code: n8n nie ma natywnego węzła tworzącego PDF, a biblioteki zewnętrzne w Code są zablokowane; PDF jest składany ręcznie, lokalnie, bez usług zewnętrznych
const first = $('Uzupełnij anonimizację').first().json;
const body = $('Webhook').first().json.body || {};
const docName = String(body.name || 'dokument-' + $execution.id).replace(/[^\p{L}\d._ -]/gu, '_').slice(0, 120);
const fileName = docName + '.zanonimizowany.pdf';

// Font TrueType (Courier New) jest osadzany w PDF, żeby polskie znaki wyglądały tak samo w każdej przeglądarce
let font;
try { font = await this.helpers.getBinaryDataBuffer(0, 'data'); } catch (e) { font = Buffer.from($input.first().binary.data.data, 'base64'); }
const table = tag => {
  for (let i = 0, n = font.readUInt16BE(4); i < n; i++) {
    const o = 12 + i * 16;
    if (font.toString('latin1', o, o + 4) === tag) return font.readUInt32BE(o + 8);
  }
  throw new Error('Font: brak tablicy ' + tag);
};
const head = table('head'), hhea = table('hhea'), cmap = table('cmap');
const scale = 1000 / font.readUInt16BE(head + 18);
const bbox = [36, 38, 40, 42].map(o => Math.round(font.readInt16BE(head + o) * scale));
const ascent = Math.round(font.readInt16BE(hhea + 4) * scale), descent = Math.round(font.readInt16BE(hhea + 6) * scale);
let sub = 0;
for (let i = 0, n = font.readUInt16BE(cmap + 2); i < n; i++) {
  const o = cmap + 4 + i * 8;
  if (font.readUInt16BE(o) === 3 && font.readUInt16BE(o + 2) === 1) sub = cmap + font.readUInt32BE(o + 4);
}
if (!sub || font.readUInt16BE(sub) !== 4) throw new Error('Font: brak tablicy cmap w formacie 4');
const segX2 = font.readUInt16BE(sub + 6);
const glyphOf = cp => {
  for (let s = 0; s < segX2; s += 2) {
    if (cp > font.readUInt16BE(sub + 14 + s)) continue;
    const start = font.readUInt16BE(sub + 16 + segX2 + s);
    if (cp < start) return 0;
    const delta = font.readUInt16BE(sub + 16 + 2 * segX2 + s), roPos = sub + 16 + 3 * segX2 + s, ro = font.readUInt16BE(roPos);
    if (!ro) return (cp + delta) & 0xffff;
    const g = font.readUInt16BE(roPos + ro + 2 * (cp - start));
    return g ? (g + delta) & 0xffff : 0;
  }
  return 0;
};
const used = new Map(); // glif -> znak (do tablicy ToUnicode: kopiowanie i wyszukiwanie tekstu w PDF)
const fallback = glyphOf(63);
const hex = s => {
  let out = '';
  for (const ch of s.replace(/[\t ]/g, ' ')) {
    const cp = ch.codePointAt(0);
    const g = (cp < 0x10000 && glyphOf(cp)) || fallback;
    if (!used.has(g)) used.set(g, g === fallback && cp !== 63 ? 63 : cp);
    out += g.toString(16).padStart(4, '0');
  }
  return '<' + out + '>';
};

// Łamanie wierszy: Courier New 10 pt, 84 znaki w wierszu, 56 wierszy na stronie A4
const COLS = 84, ROWS = 56;
const lines = [];
for (const para of String(first.anonymized_text || '').replace(/\r/g, '').split('\n')) {
  let line = '';
  for (let word of para.split(' ')) {
    while (word.length > COLS) { if (line) { lines.push(line); line = ''; } lines.push(word.slice(0, COLS)); word = word.slice(COLS); }
    if ((line ? line.length + 1 : 0) + word.length > COLS) { lines.push(line); line = word; }
    else line = line ? line + ' ' + word : word;
  }
  lines.push(line);
}
const pages = [];
for (let i = 0; i < lines.length; i += ROWS) pages.push(lines.slice(i, i + ROWS));
if (!pages.length) pages.push(['']);

const objs = [];
const add = s => { objs.push(s); return objs.length; };
const stream = (dict, data) => '<< ' + dict + ' /Length ' + data.length + ' >>\nstream\n' + data + '\nendstream';
add('<< /Type /Catalog /Pages 2 0 R >>');
add(''); // 2: drzewo stron, uzupełniane niżej
add('<< /Type /Font /Subtype /Type0 /BaseFont /CourierNewPSMT /Encoding /Identity-H /DescendantFonts [4 0 R] /ToUnicode 7 0 R >>');
add('<< /Type /Font /Subtype /CIDFontType2 /BaseFont /CourierNewPSMT /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor 5 0 R /DW 600 /CIDToGIDMap /Identity >>');
add('<< /Type /FontDescriptor /FontName /CourierNewPSMT /Flags 33 /FontBBox [' + bbox.join(' ') + '] /ItalicAngle 0 /Ascent ' + ascent + ' /Descent ' + descent + ' /CapHeight 571 /StemV 80 /FontFile2 6 0 R >>');
add(stream('/Length1 ' + font.length, font.toString('latin1')));
add(''); // 7: ToUnicode, uzupełniane po złożeniu stron
const kids = [];
pages.forEach((pl, p) => {
  const head = hex(docName + '  |  DOKUMENT ZANONIMIZOWANY – do weryfikacji  |  sesja ' + first.session_id + '  |  strona ' + (p + 1) + ' z ' + pages.length);
  const content = add(stream('', 'BT /F1 7.5 Tf 45 806 Td ' + head + ' Tj ET\nBT /F1 10 Tf 13 TL 45 780 Td\n' + pl.map(l => hex(l) + ' Tj T*').join('\n') + '\nET'));
  kids.push(add('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ' + content + ' 0 R >>'));
});
objs[1] = '<< /Type /Pages /Kids [' + kids.map(k => k + ' 0 R').join(' ') + '] /Count ' + kids.length + ' >>';
const h4 = n => n.toString(16).padStart(4, '0');
const chars = [...used.entries()].map(([g, cp]) => '<' + h4(g) + '> <' + h4(cp) + '>');
let bf = '';
for (let i = 0; i < chars.length; i += 100) { const c = chars.slice(i, i + 100); bf += c.length + ' beginbfchar\n' + c.join('\n') + '\nendbfchar\n'; }
objs[6] = stream('', '/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <ffff>\nendcodespacerange\n' + bf + 'endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend');

let pdf = '%PDF-1.4\n';
const offsets = [];
objs.forEach((o, i) => { offsets.push(pdf.length); pdf += (i + 1) + ' 0 obj\n' + o + '\nendobj\n'; });
const xref = pdf.length;
pdf += 'xref\n0 ' + (objs.length + 1) + '\n0000000000 65535 f \n' + offsets.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
pdf += 'trailer\n<< /Size ' + (objs.length + 1) + ' /Root 1 0 R >>\nstartxref\n' + xref + '\n%%EOF\n';

return [{
  json: { pdf_file: fileName, pdf_pages: pages.length },
  binary: { data: { data: Buffer.from(pdf, 'latin1').toString('base64'), mimeType: 'application/pdf', fileName, fileExtension: 'pdf' } },
}];

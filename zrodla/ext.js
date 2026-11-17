// Rozszerzenia: PDF zanonimizowanego dokumentu przed wysyłką na zewnątrz + gałąź ręczna czytająca dokumenty z folderu
const fs = require('fs');
module.exports = ({ nodes, connections, add, link, code, cond, ERR }) => {
  const DIR = '/data/shared/anonimizacja'; // w kontenerze; na hoście: ...\Anonimizacja i deanonimizacja\dokumenty
  const node = name => nodes.find(n => n.name === name);
  const rw = (name, pos, parameters, extra) => add(name, 'n8n-nodes-base.readWriteFile', 1, pos, parameters, extra);

  // --- PDF: Zapisz mapowanie -> Utwórz PDF -> Zapisz PDF -> Przygotuj części raportu
  for (const n of nodes) if (n.position[0] >= 1740) n.position[0] += 660;
  rw('Wczytaj font', [1740, 0], { operation: 'read', fileSelector: `${DIR}/_zasoby/Courier_New.ttf`, options: {} }, { ...ERR, executeOnce: true });
  code('Utwórz PDF', [1960, 0], fs.readFileSync(__dirname + '/pdf_node.js', 'utf8'), ERR);
  rw('Zapisz PDF', [2180, 0], { operation: 'write', fileName: `=${DIR}/zanonimizowane/{{ $json.pdf_file }}`, dataPropertyName: 'data', options: {} }, ERR);
  connections['Zapisz mapowanie'].main[0] = [];
  link('Zapisz mapowanie', 'Wczytaj font');
  link('Wczytaj font', 'Utwórz PDF');
  link('Utwórz PDF', 'Zapisz PDF');
  link('Zapisz PDF', 'Przygotuj części raportu');
  for (const a of ['Wczytaj font', 'Utwórz PDF', 'Zapisz PDF']) link(a, 'Usuń mapowanie (błąd)', 1);
  const dean = node('Deanonimizuj');
  const anchor = '  report: out,\n';
  if (!dean.parameters.jsCode.includes(anchor)) throw new Error('anchor dean');
  dean.parameters.jsCode = dean.parameters.jsCode.replace(anchor, anchor + "  anonymized_pdf: 'dokumenty/zanonimizowane/' + $('Utwórz PDF').first().json.pdf_file,\n");

  // --- Gałąź ręczna: dokumenty z folderu -> własny webhook -> raport do pliku
  const Y = -460;
  const DOC = "$('Wczytaj dokumenty').item.json.fileName";
  add('Uruchom ręcznie', 'n8n-nodes-base.manualTrigger', 1, [0, Y], {});
  rw('Wczytaj gotowe raporty', [220, Y], { operation: 'read', fileSelector: `${DIR}/raporty/*.raport.md`, options: {} }, { alwaysOutputData: true });
  rw('Wczytaj dokumenty', [440, Y], { operation: 'read', fileSelector: `${DIR}/*.{txt,md,pdf}`, options: {} }, { executeOnce: true });
  add('Jeszcze bez raportu', 'n8n-nodes-base.filter', 2.2, [660, Y], cond("={{ $('Wczytaj gotowe raporty').all().some(i => i.json.fileName === $json.fileName + '.raport.md') }}", { type: 'boolean', operation: 'false', singleValue: true }));
  add('Czy PDF?', 'n8n-nodes-base.if', 2.2, [880, Y], cond("={{ $json.fileName.toLowerCase().endsWith('.pdf') }}", { type: 'boolean', operation: 'true', singleValue: true }));
  add('Wyodrębnij tekst z PDF', 'n8n-nodes-base.extractFromFile', 1, [1100, Y - 100], { operation: 'pdf', binaryPropertyName: 'data', options: {} });
  add('Wyodrębnij tekst z pliku', 'n8n-nodes-base.extractFromFile', 1, [1100, Y + 100], { operation: 'text', binaryPropertyName: 'data', destinationKey: 'text', options: {} });
  add('Uruchom anonimizację', 'n8n-nodes-base.httpRequest', 4.2, [1340, Y], {
    method: 'POST', url: 'http://localhost:5678/webhook/anonimizacja-raport', sendBody: true, specifyBody: 'json',
    jsonBody: `={{ JSON.stringify({ text: $json.text, name: ${DOC} }) }}`,
    options: { timeout: 7200000, batching: { batch: { batchSize: 1, batchInterval: 0 } } },
  }, { onError: 'continueRegularOutput', notes: 'Why HTTP: gałąź ręczna wywołuje webhook tego samego workflowu, żeby każdy plik miał osobne wykonanie i osobną sesję mapowania (Execute Workflow wymagałby drugiego workflowu). Pliki idą po kolei, bo lokalne modele nie obsłużą równoległych przebiegów.' });
  add('Jest raport?', 'n8n-nodes-base.filter', 2.2, [1560, Y], cond('={{ $json.report }}', { type: 'string', operation: 'notEmpty', singleValue: true }));
  add('Raport do pliku', 'n8n-nodes-base.convertToFile', 1.1, [1780, Y], { operation: 'toText', sourceProperty: 'report', options: { fileName: `={{ ${DOC} }}.raport.md` } });
  rw('Zapisz raport', [2000, Y], { operation: 'write', fileName: `=${DIR}/raporty/{{ ${DOC} }}.raport.md`, dataPropertyName: 'data', options: {} });
  const chain = ['Uruchom ręcznie', 'Wczytaj gotowe raporty', 'Wczytaj dokumenty', 'Jeszcze bez raportu', 'Czy PDF?'];
  chain.slice(0, -1).forEach((a, i) => link(a, chain[i + 1]));
  link('Czy PDF?', 'Wyodrębnij tekst z PDF', 0);
  link('Czy PDF?', 'Wyodrębnij tekst z pliku', 1);
  link('Wyodrębnij tekst z PDF', 'Uruchom anonimizację');
  link('Wyodrębnij tekst z pliku', 'Uruchom anonimizację');
  link('Uruchom anonimizację', 'Jest raport?');
  link('Jest raport?', 'Raport do pliku');
  link('Raport do pliku', 'Zapisz raport');

  if (process.env.TESTHOOK) { // tylko na czas testu: wyzwalacz HTTP podpięty pod gałąź ręczną
    add('TEST wyzwalacz', 'n8n-nodes-base.webhook', 2.1, [0, Y - 200], { httpMethod: 'POST', path: 'anonimizacja-test-recznie', responseMode: 'onReceived', options: {} }, { webhookId: 'c8d2e3f4-6a71-4b82-9ca3-d4e5f6a7b8c9' });
    link('TEST wyzwalacz', 'Wczytaj gotowe raporty');
  }
};

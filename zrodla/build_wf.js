const fs = require('fs');
const N = require('./nodes');
const P = require('./prompts');
const TABLE = { __rl: true, mode: 'id', value: 's2mnAYlDYtVj1DUv', cachedResultName: 'anonimizacja_mapowania' };
const SESSION = '={{ String($execution.id) }}';
const nodes = [], connections = {};
let n = 0;
const add = (name, type, typeVersion, position, parameters, extra = {}) => { nodes.push({ id: 'a' + (++n), name, type, typeVersion, position, parameters, ...extra }); return name; };
const link = (from, to, out = 0, kind = 'main') => {
  const c = (connections[from] ??= {})[kind] ??= [];
  while (c.length <= out) c.push([]);
  c[out].push({ node: to, type: kind, index: 0 });
};
const code = (name, pos, jsCode, extra) => add(name, 'n8n-nodes-base.code', 2, pos, { jsCode }, extra);
const chain = (name, pos, text, system, extra) => add(name, '@n8n/n8n-nodes-langchain.chainLlm', 1.9, pos,
  { promptType: 'define', text, messages: { messageValues: [{ type: 'SystemMessagePromptTemplate', message: system }] }, batching: {} },
  { retryOnFail: true, maxTries: 3, waitBetweenTries: 2000, ...extra });
const cond = (leftValue, operator, rightValue) => ({ conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 }, conditions: [{ id: 'c' + (++n), leftValue, ...(rightValue !== undefined ? { rightValue } : {}), operator }], combinator: 'and' }, options: {} });
const sessionFilter = { matchType: 'allConditions', filters: { conditions: [{ keyName: 'session_id', condition: 'eq', keyValue: SESSION }] } };
const dt = (name, pos, operation, params, extra) => add(name, 'n8n-nodes-base.dataTable', 1.1, pos, { resource: 'row', operation, dataTableId: TABLE, ...params }, extra);
const respond = (name, pos, responseBody, responseCode) => add(name, 'n8n-nodes-base.respondToWebhook', 1.4, pos, { respondWith: 'json', responseBody, options: responseCode ? { responseCode } : {} }, { executeOnce: true });
const ERR = { onError: 'continueErrorOutput' };
const Y = 0, YM = 240, YE = 460;

add('Webhook', 'n8n-nodes-base.webhook', 2.1, [0, Y], { httpMethod: 'POST', path: 'anonimizacja-raport', responseMode: 'responseNode', options: {} }, { webhookId: 'b7c1d2e3-5f60-4a71-8b92-c3d4e5f6a7b8' });
code('Podziel na fragmenty', [220, Y], N.split, ERR);
chain('Wykryj PII', [440, Y], '=Tekst do analizy:\n{{ $json.chunk }}', P.DETECT, ERR);
code('Anonimizuj', [760, Y], N.pass1, ERR);
chain('Weryfikuj anonimizację', [980, Y], '=Tekst do analizy:\n{{ $json.chunk }}', P.DETECT, ERR);
code('Uzupełnij anonimizację', [1300, Y], N.pass2, ERR);
dt('Zapisz mapowanie', [1520, Y], 'insert', { columns: { mappingMode: 'defineBelow', value: { session_id: '={{ $json.session_id }}', placeholder: '={{ $json.placeholder }}', original: '={{ $json.original }}' }, matchingColumns: [], schema: ['session_id', 'placeholder', 'original'].map(id => ({ id, displayName: id, required: false, defaultMatch: false, display: true, type: 'string', readOnly: false, removed: false })), attemptToConvertTypes: false, convertFieldsToString: false }, options: {} }, ERR);
code('Przygotuj części raportu', [1740, Y], N.parts, ERR);
chain('Raport częściowy', [1960, Y], '={{ $json.legend }}\n\nDokument:\n{{ $json.part }}', '={{ $json.system }}', ERR);
add('Komplet części?', 'n8n-nodes-base.filter', 2.2, [2280, Y], cond('={{ $input.all().length }}', { type: 'number', operation: 'equals' }, "={{ $('Przygotuj części raportu').all().length }}"));
add('Wiele części?', 'n8n-nodes-base.if', 2.2, [2500, Y], cond("={{ $('Przygotuj części raportu').all().length }}", { type: 'number', operation: 'gt' }, 1));
chain('Raport końcowy', [2720, Y - 180], "={{ $('Przygotuj części raportu').first().json.legend_all }}\n\nStreszczenia kolejnych części dokumentu:\n\n{{ $('Raport częściowy').all().map(i => i.json.text).join('\\n\\n---\\n\\n') }}", P.REPORT_FINAL, { ...ERR, executeOnce: true });
dt('Pobierz mapowanie', [3040, Y], 'get', { ...sessionFilter, returnAll: true }, { ...ERR, executeOnce: true });
code('Przygotuj odmianę', [3260, Y], N.prepDecl, ERR);
add('Jest co odmieniać?', 'n8n-nodes-base.if', 2.2, [3480, Y], cond('={{ $json.none }}', { type: 'boolean', operation: 'false', singleValue: true }));
chain('Odmień (Ollama)', [3700, Y - 180], '={{ $json.prompt }}', P.DECLINE, { onError: 'continueRegularOutput' });
code('Deanonimizuj', [4020, Y], N.dean, ERR);
dt('Usuń mapowanie', [4240, Y], 'deleteRows', { ...sessionFilter, options: {} }, { executeOnce: true });
respond('Zwróć raport', [4460, Y], "={{ JSON.stringify($('Deanonimizuj').first().json) }}");

add('Ollama detekcja (gemma4:e4b)', '@n8n/n8n-nodes-langchain.lmChatOllama', 1, [700, YM], { model: 'gemma4:e4b', options: { format: 'json', think: false, temperature: 0, numCtx: 8192, keepAlive: '10m' } }, { credentials: { ollamaApi: { id: 'ToHQYeWCfVmGq5qp', name: 'Ollama account' } } });
add('Ollama odmiana (gemma4:26b)', '@n8n/n8n-nodes-langchain.lmChatOllama', 1, [3700, YM], { model: process.env.DECL || 'gemma4:26b', options: { format: 'json', think: false, temperature: 0, numCtx: 4096, keepAlive: '30s' } }, { credentials: { ollamaApi: { id: 'ToHQYeWCfVmGq5qp', name: 'Ollama account' } } });
add('OpenAI (zewnętrzny)', '@n8n/n8n-nodes-langchain.lmChatOpenAi', 1.2, [2340, YM], { model: { __rl: true, mode: 'list', value: process.env.OAI || 'gpt-4.1-mini' }, options: {} }, { credentials: { openAiApi: { id: 'LScYyYk8KRHKlGjB', name: 'OpenAI twoj.email@example.com key' } } });

respond('Zwróć błąd anonimizacji', [1300, YE], "={{ JSON.stringify({ error: $json.error || 'Anonimizacja nie powiodła się. Nic nie wysłano do zewnętrznego AI.' }) }}", "={{ String($json.error || '').includes('Brak pola') ? 400 : 500 }}");
dt('Usuń mapowanie (błąd)', [3040, YE], 'deleteRows', { ...sessionFilter, options: {} }, { executeOnce: true });
respond('Zwróć błąd 502', [3260, YE], '{"error":"Przetwarzanie po anonimizacji nie powiodło się. Mapowanie usunięte."}', 502);

const main = ['Webhook', 'Podziel na fragmenty', 'Wykryj PII', 'Anonimizuj', 'Weryfikuj anonimizację', 'Uzupełnij anonimizację', 'Zapisz mapowanie', 'Przygotuj części raportu', 'Raport częściowy', 'Komplet części?', 'Wiele części?'];
main.slice(0, -1).forEach((a, i) => link(a, main[i + 1]));
link('Wiele części?', 'Raport końcowy', 0);
link('Wiele części?', 'Pobierz mapowanie', 1);
link('Raport końcowy', 'Pobierz mapowanie');
link('Pobierz mapowanie', 'Przygotuj odmianę');
link('Przygotuj odmianę', 'Jest co odmieniać?');
link('Jest co odmieniać?', 'Odmień (Ollama)', 0);
link('Jest co odmieniać?', 'Deanonimizuj', 1);
link('Odmień (Ollama)', 'Deanonimizuj');
link('Deanonimizuj', 'Usuń mapowanie');
link('Usuń mapowanie', 'Zwróć raport');
for (const a of ['Podziel na fragmenty', 'Wykryj PII', 'Anonimizuj', 'Weryfikuj anonimizację', 'Uzupełnij anonimizację']) link(a, 'Zwróć błąd anonimizacji', 1);
for (const a of ['Zapisz mapowanie', 'Przygotuj części raportu', 'Raport częściowy', 'Raport końcowy', 'Pobierz mapowanie', 'Przygotuj odmianę', 'Deanonimizuj']) link(a, 'Usuń mapowanie (błąd)', 1);
link('Usuń mapowanie (błąd)', 'Zwróć błąd 502');
for (const c of ['Wykryj PII', 'Weryfikuj anonimizację']) link('Ollama detekcja (gemma4:e4b)', c, 0, 'ai_languageModel');
link('Ollama odmiana (gemma4:26b)', 'Odmień (Ollama)', 0, 'ai_languageModel');
for (const c of ['Raport częściowy', 'Raport końcowy']) link('OpenAI (zewnętrzny)', c, 0, 'ai_languageModel');

require('./ext')({ nodes, connections, add, link, code, cond, ERR });
const wf = { name: 'Anonimizacja i deanonimizacja dokumentów', nodes, connections, settings: { executionOrder: 'v1', saveDataSuccessExecution: 'none', saveDataErrorExecution: 'none', saveManualExecutions: false, saveExecutionProgress: false } };
fs.writeFileSync(__dirname + '/workflow.json', JSON.stringify(wf, null, 2));
fs.writeFileSync(__dirname + '/call_update.json', JSON.stringify({ name: 'n8n_update_full_workflow', arguments: { id: 't2bGisJZ9WtC9y67', name: 'Anonimizacja i deanonimizacja dokumentów', nodes, connections, settings: { ...wf.settings, saveDataSuccessExecution: process.env.DEBUG ? 'all' : 'none', saveDataErrorExecution: process.env.DEBUG ? 'all' : 'none' } } }));
console.log('nodes', nodes.length, 'bytes', JSON.stringify(wf).length);

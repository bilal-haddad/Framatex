'use strict';
// Dossier Jaune (checklist par sous-dossier), tableau de bord et navigation simplifiée.
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
let source = fs.readFileSync('static/app.js', 'utf8');
source = source.substring(0, source.lastIndexOf('(async function init(){'));
const ctx = {document: {querySelector: () => ({}), addEventListener: () => {}}, window: {addEventListener: () => {}}, console, setTimeout, clearTimeout,
  MutationObserver: class { observe() {} }, matchMedia: () => ({matches: false})};
ctx.AREA_TARGETS = {};
vm.createContext(ctx);
vm.runInContext(source, ctx);
vm.runInContext(fs.readFileSync('static/internal.js', 'utf8'), ctx);
vm.runInContext('function focusWorkspaceArea(){}', ctx);
vm.runInContext(fs.readFileSync('static/dossier.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync('static/dashboard.js', 'utf8'), ctx);
const run = code => vm.runInContext(code, ctx);

// 1. Ordre métier des 22 lignes standard, quel que soit l'ordre renvoyé par le moteur.
const rule = (folder, title, status, extra = {}) => ({id: `${folder}-${title}`, folder, title, document_type: title, status,
  due_phase: 'preparation', due: !['not_due'].includes(status), required: true, documents: [], can_review: true, ...extra});
ctx.RULES = [rule('jaune', 'Test tissu', 'not_due', {due_phase: 'fabrication'}), rule('jaune', 'Calcul du besoin', 'missing'),
  rule('jaune', 'Dossier technique client', 'present', {documents: [{id: 'doc-1', version: 2}]}),
  rule('jaune', 'Fiche de prix', 'pending_validation', {documents: [{id: 'doc-2', version: 1}]}),
  rule('jaune', 'Emails techniques', 'not_due', {required: false}),
  rule('rose', 'Bon de livraison', 'missing'), rule('bleu', 'Déclaration douanière', 'exception', {exception_reason: 'Pas <b>d’import</b>'})];
run(`state.completeness = {configured: true, rows: RULES}`);
assert.deepEqual(run(`djSortedRows('jaune').map(r => r.title)`),
  ['Dossier technique client', 'Calcul du besoin', 'Fiche de prix', 'Test tissu', 'Emails techniques']);

// 2. Compteurs d'une carte : seuls les exigibles comptent ; facultatif et non exigible ne sont jamais manquants.
assert.deepEqual(JSON.parse(run(`JSON.stringify((({present, due, missing, pending, upcoming}) => ({present, due, missing, pending, upcoming}))(djFolderStats('jaune')))`)),
  {present: 1, due: 3, missing: 1, pending: 1, upcoming: 1});

// 3. Une ligne de checklist par type : état, version, action adaptée, texte échappé.
const docs = `new Map([['doc-1', {id: 'doc-1', title: 'Dossier technique client', doc_type: 'Dossier technique client', latest: {number: 2, created_at: '2026-10-21T10:00:00'}}],
  ['doc-2', {id: 'doc-2', title: 'Fiche de prix <img src=x>', doc_type: 'Fiche de prix', latest: {number: 1, created_at: '2026-10-21T10:00:00'}}]])`;
const row = title => run(`djRow(RULES.find(r => r.title === ${JSON.stringify(title)}), ${docs}, {can_write: true})`);
assert(row('Calcul du besoin').includes('Manquant') && row('Calcul du besoin').includes('data-dj-upload'));
assert(row('Dossier technique client').includes('Présent') && row('Dossier technique client').includes('V2') && row('Dossier technique client').includes('data-history="doc-1"'));
const pending = row('Fiche de prix');
assert(pending.includes('En validation') && pending.includes('data-complete-validate') && pending.includes('Examiner'));
assert(pending.includes('&lt;img src=x&gt;') && !pending.includes('<img src=x>'));
// Plus aucune lecture « par étape » : une pièce non exigée est « Non applicable », sans mention d'étape.
assert(row('Test tissu').includes('Non applicable') && !row('Test tissu').includes('étape'));
assert(row('Emails techniques').includes('Facultatif · à déposer si besoin') && !row('Emails techniques').includes('Manquant'));
const exception = run(`djRow(RULES.find(r => r.folder === 'bleu'), new Map(), {can_write: true})`);
assert(exception.includes('Exception') && exception.includes('&lt;b&gt;') && !exception.includes('Manquant'));
// Lecture seule : pas de bouton de dépôt.
assert(!run(`djRow(RULES.find(r => r.title === 'Calcul du besoin'), new Map(), {can_write: false})`).includes('data-dj-upload'));

// 3 bis. Doublon : prioritaire à l'affichage, la pièce reste présente pour la complétude.
ctx.GROUP = {sha256: 'a'.repeat(64), reviewed: false, documents: [
  {document_id: 'doc-1', title: 'Dossier technique client', folder: 'jaune', doc_type: 'Dossier technique client', version: 2, original_name: 'dt.pdf', created_at: '2026-10-21T10:00:00'},
  {document_id: 'doc-9', title: 'Copie <b>DT</b>', folder: 'rose', doc_type: 'Autre', version: 1, original_name: 'dt.pdf', created_at: '2026-10-21T11:00:00'}]};
run(`state.djDuplicates = [GROUP]; state.folder = 'jaune'`);
const dup = row('Dossier technique client');
assert(dup.includes('Doublon détecté') && dup.includes('data-dj-duplicate="' + 'a'.repeat(64) + '"') && dup.includes('data-state="duplicate"'));
assert(dup.includes('Contenu identique à « Copie &lt;b&gt;DT&lt;/b&gt; » (Réception)') && !dup.includes('<b>DT'));
assert.equal(run(`djFolderStats('rose').duplicates`), 1);
assert.equal(run(`djFolderStats('jaune').present`), 1);
run(`state.djDuplicates = [{...GROUP, reviewed: true}]`);
assert(row('Dossier technique client').includes('Présent') && !row('Dossier technique client').includes('Doublon'));
run(`state.djDuplicates = []`);

// 4. Navigation précise : un manquant du tableau de bord cible la règle, donc la ligne.
const target = JSON.parse(run(`opsTargetData({launch_id: 'L1', folder: 'rose', id: 'rule-bl', due: true})`).replace(/&quot;/g, '"'));
assert.equal(target.rule_id, 'rule-bl'); assert.equal(target.folder, 'rose');
const action = JSON.parse(run(`opsTargetData({launch_id: 'L1', folder: 'jaune', id: 'missing:rule-cb'})`).replace(/&quot;/g, '"'));
assert.equal(action.rule_id, 'rule-cb');
assert.equal(JSON.parse(run(`opsTargetData({launch_id: 'L1'})`).replace(/&quot;/g, '"')).rule_id, undefined);
// Les anciennes zones (ancres, recettes) restent adressables dans les onglets.
for (const area of ['documents', 'completeness', 'workflow', 'quality', 'intake', 'mail', 'sharing', 'notes', 'paper', 'orli', 'materials', 'simulation', 'spec', 'approvals'])
  assert(run(`Boolean(DJ_AREAS[${JSON.stringify(area)}])`), area);

// 5. Tableau de bord : colonnes demandées, 8 lignes puis « afficher les autres », filtre par sous-dossier.
ctx.REPORT = {missing_documents: Array.from({length: 10}, (_, i) => ({id: `r${i}`, launch_id: 'L1', title: i ? `Pièce ${i}` : 'Bon <script>', folder: i % 2 ? 'rose' : 'jaune',
  due_phase: 'approvisionnement', due: true, status: 'missing', order_ref: 'CMD-1', launch_name: 'Veste', article: 'Veste lin', client_name: 'Client & Co'}))};
run(`state.dashState = 'missing'; state.dashFilter = 'all'; state.dashShowAll = false`);
let table = run(`dashMissingTable(REPORT)`);
assert.equal((table.match(/data-ops-target=/g) || []).length, 8);
assert(table.includes('Afficher les 2 autres pièces'));
assert(table.indexOf('>Sous-dossier<') < table.indexOf('>Document<') && table.includes('>Client<') && table.includes('>État<'));
assert(table.includes('Client &amp; Co') && table.includes('Bon &lt;script&gt;') && !table.includes('Bon <script>'));
assert(table.includes('&quot;rule_id&quot;:&quot;r0&quot;'));
run(`state.dashFilter = 'rose'`);
table = run(`dashMissingTable(REPORT)`);
assert.equal((table.match(/data-ops-target=/g) || []).length, 5);
assert(!table.includes('Afficher les'));
run(`state.dashFilter = 'vert'`);
assert(run(`dashMissingTable(REPORT)`).includes('Rien à traiter dans ce sous-dossier'));
// Doublons et validations : même tableau, état explicite, cible = ligne du dossier.
ctx.REPORT.duplicate_documents = [{launch_id: 'L1', folder: 'rose', title: 'Email logistique', document_id: 'doc-9', sha256: 'b'.repeat(64), status: 'duplicate',
  order_ref: 'DR-1', client_name: 'Client', documents: [{document_id: 'doc-8', title: 'Email logistique', folder: 'rose'}, {document_id: 'doc-9', title: 'Email logistique', folder: 'rose'}]}];
ctx.REPORT.pending_validation_documents = [{id: 'rule-fp', launch_id: 'L1', folder: 'jaune', title: 'Fiche de prix', due: true, status: 'pending_validation', documents: [{id: 'doc-3', version: 1}], order_ref: 'DR-1'}];
run(`state.dashState = 'duplicate'; state.dashFilter = 'all'`);
table = run(`dashMissingTable(REPORT)`);
assert(table.includes('Doublon détecté') && table.includes('2 pièces identiques') && table.includes('&quot;row_document&quot;:&quot;doc-9&quot;') && table.includes('Examiner'));
run(`state.dashState = 'pending'`);
table = run(`dashMissingTable(REPORT)`);
assert(table.includes('En validation') && table.includes('&quot;rule_id&quot;:&quot;rule-fp&quot;'));
const panel = run(`state.dashState = 'missing'; dashMissingPanel(REPORT)`);
assert(panel.includes('data-dash-state="missing"') && panel.includes('data-dash-state="pending"') && panel.includes('data-dash-state="duplicate"'));
assert(run(`DASH_KPIS.todo.map(k => k[0]).includes('duplicate_documents')`));

// 6. Plus aucun libellé « Version 0.x » dans l'interface.
for (const file of fs.readdirSync('static').filter(f => f.endsWith('.js')))
  assert(!/[Vv]ersion 0\.\d+/.test(fs.readFileSync(`static/${file}`, 'utf8')), file);

// 7. Espace Client : 4 entrées de menu, onglets Documents sur les routes existantes.
const client = fs.readFileSync('static/client/client.js', 'utf8');
const nav = client.slice(client.indexOf('const NAV = ['), client.indexOf('];', client.indexOf('const NAV = [')));
assert.deepEqual([...nav.matchAll(/label: '([^']+)'/g)].map(m => m[1]), ['Mes demandes', 'Nouvelle demande', 'Documents', 'Mon compte']);
for (const route of ['#/documents-demandes', '#/documents-transmis', '#/documents']) assert(client.includes(`href: '${route}'`), route);

// 8. Landing : ordre demandé et mouvement réduit respecté.
const landing = fs.readFileSync('static/landing/index.html', 'utf8');
const order = [...landing.matchAll(/<section class="([^"]+)"(?: id="([^"]+)")?/g)].map(m => m[2] || m[1]);
assert.deepEqual(order, ['accueil', 'solution', 'espaces', 'savoir-faire', 'partenariat', 'cta']);
assert(fs.readFileSync('static/landing/landing.js', 'utf8').includes("prefers-reduced-motion: reduce"));
assert(fs.readFileSync('static/brand/dossier.css', 'utf8').includes('prefers-reduced-motion'));
console.log('Dossier Jaune : checklist, ordre métier, états, ciblage depuis le tableau de bord, menu Client et landing OK');

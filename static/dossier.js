'use strict';
// Dossier Jaune : la checklist documentaire d'abord, les contrôles avancés à la demande.
// Réutilise les moteurs et modules existants (complétude, décisions, cohérence, OCR,
// QR, exigences, emails, simulation, ORLI, matières, circuits, partages, mémoire) :
// ils sont rendus et liés comme avant, puis rangés dans des onglets.

const DJ_FOLDERS = {
  jaune: {name: 'Technique', color: 'Jaune', order: '01'},
  rose: {name: 'Réception', color: 'Rose', order: '02'},
  bleu: {name: 'Dédouanement', color: 'Bleu', order: '03'},
  vert: {name: 'Factures', color: 'Vert', order: '04'},
};
// États affichés d'une ligne. « Doublon détecté » se superpose à l'état du moteur de
// complétude (la pièce reste présente) tant que le doublon n'est pas examiné.
const DJ_STATES = {
  present: ['Présent', 'ok'], missing: ['Manquant', 'missing'], pending_validation: ['En validation', 'pending'],
  exception: ['Exception', 'exception'], duplicate: ['Doublon détecté', 'duplicate'], not_due: ['Non applicable', 'idle'],
};
const DJ_TABS = [['documents', 'Documents'], ['controles', 'Contrôles'], ['communication', 'Communication'], ['historique', 'Historique']];
const DJ_MODULES = {
  controles: [
    ['completude', 'Complétude', () => djCompletenessModule()],
    ['decisions', 'Décisions et impacts', () => renderWorkflow()],
    ['fiabilite', 'Cohérence et Excel', () => renderQuality()],
    ['lecture', 'Lecture OCR', () => renderIntake()],
    ['circuits', 'Circuits de validation', () => renderApprovals()],
    ['exigences', 'Exigences client', () => renderSpec()],
    ['simulation', 'Simulation', () => renderImpactSimulation()],
    ['matieres', 'Matières', () => renderMaterialReport()],
    ['orli', 'Rapprochement ORLI', () => renderOrliReconciliation()],
  ],
  communication: [
    ['demande', 'Demande Client', () => djClientRequestModule()],
    ['emails', 'Emails et engagements', () => renderMail()],
    ['partages', 'Partages et fournisseurs', () => renderSharing()],
  ],
  historique: [
    ['activite', 'Activité', () => djActivityModule()],
    ['memoire', 'Mémoire interne', () => djNotesModule()],
    ['passeports', 'QR et passeports', () => renderPaper()],
    ['technique', 'Détails techniques', () => djTechnicalModule()],
  ],
};
// Zones historiques (actions prioritaires, fiches document) → onglet et module.
const DJ_AREAS = {
  documents: ['documents'], completeness: ['controles', 'completude'], workflow: ['controles', 'decisions'],
  quality: ['controles', 'fiabilite'], intake: ['controles', 'lecture'], approvals: ['controles', 'circuits'],
  spec: ['controles', 'exigences'], simulation: ['controles', 'simulation'], materials: ['controles', 'matieres'],
  orli: ['controles', 'orli'], mail: ['communication', 'emails'], sharing: ['communication', 'partages'],
  request: ['communication', 'demande'], activity: ['historique', 'activite'], notes: ['historique', 'memoire'],
  paper: ['historique', 'passeports'],
};
const DJ_PHASES = ['preparation', 'approvisionnement', 'fabrication', 'expedition', 'cloture'];
// Ordre de lecture métier des lignes standard ; les autres règles suivent l'ordre du moteur.
const DJ_ORDER = ['Dossier technique client', 'Commande client', 'Lancement provisoire', 'Lancement définitif', 'Fiche d’emploi',
  'Calcul du besoin', 'Fiche de prix', 'Étude BE / Excel', 'Test tissu', 'Emails techniques', 'Bon de livraison', 'Bon / note de réception',
  'Document de réception matière', 'Emails réception / logistique', 'Déclaration douanière', 'Documents import / export', 'Document transit',
  'Document transport', 'Justificatif de dédouanement', 'Facture FRAMATEX', 'Pièce de facturation associée', 'Avoir / correction de facture'];

function djInitialUi() {
  return {tab: 'documents', module: {controles: 'completude', communication: 'demande', historique: 'activite'}, highlight: null};
}
state.dj = djInitialUi();

// --------------------------------------------------------------------------- chargement
async function djLoadExtras(id) {
  const enc = encodeURIComponent(id);
  const [summary, notes, activity, duplicates] = await Promise.all([
    api(`/api/launches/${enc}/operations`),
    can('document.read', 'jaune') ? api(`/api/launches/${enc}/experience-notes`).catch(() => []) : Promise.resolve([]),
    can('audit.read') ? api(`/api/workspace/activity?launch_id=${enc}&limit=40`).catch(() => null) : Promise.resolve(null),
    api(`/api/launches/${enc}/duplicates`).catch(() => []),
  ]);
  let request = null;
  if (summary.client_request && state.me?.admin) {
    request = await api(`/api/admin/client-order-requests/${encodeURIComponent(summary.client_request.id)}`).catch(() => null);
  }
  return {operationsDetail: summary, djNotes: notes, djActivity: activity, djClientRequest: request, djDuplicates: duplicates};
}

const djOriginalOpenLaunch = openLaunch;
openLaunch = async function(id, folder = state.folder, target = null) {
  const sameDossier = state.detail?.id === id;
  state.djSuspend = true;
  let extras;
  try {
    const pending = djLoadExtras(id);
    await djOriginalOpenLaunch(id, folder || 'jaune');
    extras = await pending;
  } finally {
    state.djSuspend = false;
  }
  Object.assign(state, extras);
  if (!sameDossier) state.dj = djInitialUi();
  state.dj.highlight = null;
  if (target) djApplyTarget(target);
  renderDetail();
};

function djApplyTarget(target) {
  if (target.folder) state.folder = target.folder;
  if (target.area && DJ_AREAS[target.area]) {
    const [tab, module] = DJ_AREAS[target.area];
    state.dj.tab = tab;
    if (module) state.dj.module[tab] = module;
  }
  const rows = state.completeness?.rows || [];
  const rule = rows.find(r => r.id === target.rule_id)
    || rows.find(r => target.row_document && r.documents.some(d => d.id === target.row_document))
    || rows.find(r => target.title && r.folder === state.folder && r.title === target.title);
  if (rule) {
    state.folder = rule.folder;
    state.dj.tab = 'documents';
    state.dj.highlight = rule.id;
  } else if (target.row_document) {
    // Pièce hors checklist : ligne « Autres pièces » de son sous-dossier.
    const folder = state.detail.folders.find(f => (f.documents || []).some(doc => doc.id === target.row_document));
    if (folder) { state.folder = folder.slug; state.dj.tab = 'documents'; state.dj.highlight = 'doc:' + target.row_document; }
  }
}

// --------------------------------------------------------------------------- calculs
function djDocIndex() {
  const index = new Map();
  for (const folder of state.detail.folders) for (const doc of folder.documents || []) index.set(doc.id, doc);
  return index;
}

// Doublons non examinés : document → groupe (même SHA-256 dans le dossier).
function djDuplicateIndex() {
  const index = new Map();
  for (const group of state.djDuplicates || []) {
    if (group.reviewed) continue;
    for (const doc of group.documents) index.set(doc.document_id, group);
  }
  return index;
}

function djFolderStats(slug) {
  const rows = (state.completeness?.rows || []).filter(r => r.folder === slug);
  const due = rows.filter(r => r.due);
  return {
    rows, due: due.length,
    present: due.filter(r => r.status === 'present').length,
    missing: due.filter(r => r.status === 'missing').length,
    pending: rows.filter(r => r.status === 'pending_validation').length,
    duplicates: (state.djDuplicates || []).filter(g => !g.reviewed && g.documents.some(d => d.folder === slug)).length,
    upcoming: rows.filter(r => r.required !== false && !r.due).length,
  };
}

// État affiché d'une ligne de checklist (doublon prioritaire sur l'état du moteur).
function djRowState(rule, duplicates = djDuplicateIndex()) {
  const group = rule.documents.map(d => duplicates.get(d.id)).find(Boolean);
  return group ? {status: 'duplicate', group} : {status: rule.status, group: null};
}

function djSortedRows(slug) {
  const known = r => DJ_ORDER.indexOf(r.title);
  const rank = r => known(r) >= 0 ? known(r) : 100 + DJ_PHASES.indexOf(r.due_phase);
  return djFolderStats(slug).rows.map((r, i) => [r, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([r]) => r);
}

// --------------------------------------------------------------------------- en-tête
function djFact(label, value) {
  return `<div class="dj-fact"><dt>${e(label)}</dt><dd>${value}</dd></div>`;
}

function djHeader() {
  const d = state.detail, s = state.operationsDetail || {}, request = s.client_request;
  const completion = s.completion || {};
  const c = state.completeness || {};
  const date = request?.date_souhaitee ? opsDay(request.date_souhaitee) : niceDate(d.created_at);
  const facts = [
    djFact('Commande', e(d.order_ref || '—')),
    djFact('Client', e(d.client_name || '—')),
    djFact('Modèle / article', e(s.article || '—')),
    djFact('Quantité', s.quantity ? `${e(s.quantity)} pièces` : '—'),
    djFact(request ? 'Date souhaitée' : 'Ouvert le', e(date)),
    djFact('Référence client', e(request?.reference_client || '—')),
    ...(d.orli_ref ? [djFact('Référence ORLI', e(d.orli_ref))] : []),
    djFact('État', statusTag(d.status)),
    ...(c.configured ? [djFact('Étape de la commande', `${e(phaseLabel(c.phase))}${c.can_change_context ? ' <button class="link dj-fact-link" id="dj-edit-phase">Changer</button>' : ''}`)] : []),
  ].join('');
  const percent = completion.percent ?? null;
  const progress = c.configured
    ? `<div class="dj-progress">
        <div class="dj-progress-text"><span class="dj-label">Complétude</span>
          <strong>${completion.present_due ?? 0} / ${completion.due_count ?? 0}</strong><span>pièces obligatoires présentes</span>
          <span class="dj-state is-${completion.state === 'complete' ? 'ok' : completion.state === 'incomplete' ? 'missing' : 'idle'}">${e(OPS_STATES[completion.state] || '—')}</span></div>
        <div class="dj-bar" role="img" aria-label="Complétude ${percent ?? 0} %"><span style="width:${percent ?? 0}%"></span></div>
        ${djDossierTally()}
      </div>`
    : `<div class="dj-progress dj-progress-empty"><span class="dj-label">Complétude</span><span>Aucune checklist associée pour l’instant.</span>
        ${c.can_change_context ? `<button class="secondary tiny" id="dj-apply-standard">Appliquer la checklist standard</button>` : ''}</div>`;
  const anyWritable = d.folders.some(f => f.can_write);
  return `<div class="page-heading dj-head">
      <div class="dj-head-main">
        <button class="link dj-back" id="back-launches">${icon('back')} Commandes</button>
        <p class="dj-eyebrow">Dossier Jaune</p>
        <h1 class="page-title dj-title">${e(d.name)}</h1>
      </div>
      <div class="dj-head-actions">
        ${anyWritable ? `<button class="primary" id="upload-doc">${icon('upload')} Déposer un document</button>` : ''}
        ${d.can_update ? `<button class="secondary" id="ops-edit">Suivi de la commande</button><button class="secondary" id="edit-launch">${icon('pencil')} Modifier</button>` : ''}
      </div>
    </div>
    <section id="ops-launch-summary" class="dj-summary" aria-label="Commande">
      <dl class="dj-facts">${facts}</dl>
      ${request ? `<p class="dj-origin ops-client-origin">Ouvert depuis la demande Client <strong>${e(request.request_number)}</strong> de ${e(request.client)} · <button class="link" data-dj-goto="communication:demande">Voir la demande</button></p>` : ''}
      ${progress}
    </section>`;
}

function djFolderCards() {
  return `<div class="dj-folders" aria-label="Sous-dossiers">${state.detail.folders.map(folder => {
    const meta = DJ_FOLDERS[folder.slug];
    const selected = folder.slug === state.folder;
    if (!folder.can_read) {
      return `<button class="folder-card dj-folder is-locked ${selected ? 'selected' : ''}" data-folder="${folder.slug}" aria-pressed="${selected}">
        <span class="dj-folder-top"><span class="dj-folder-name">${e(meta.name)}</span><span class="dj-folder-code">${meta.color} · ${meta.order}</span></span>
        <span class="dj-folder-meta">${icon('lock')} Accès restreint</span></button>`;
    }
    const st = djFolderStats(folder.slug);
    const ratio = st.due ? Math.round(100 * st.present / st.due) : 0;
    const count = st.due
      ? `<strong class="dj-folder-count">${st.present} / ${st.due}</strong><span class="dj-folder-unit">documents présents</span>`
      : `<strong class="dj-folder-count dj-folder-count-idle">${(folder.documents || []).length}</strong><span class="dj-folder-unit">${(folder.documents || []).length > 1 ? 'documents déposés' : 'document déposé'} · rien d’exigible</span>`;
    const notes = [st.missing ? `<span class="is-missing">${st.missing} manquant${st.missing > 1 ? 's' : ''}</span>` : '',
      st.pending ? `<span class="is-pending">${st.pending} en validation</span>` : '',
      st.duplicates ? `<span class="is-duplicate">${st.duplicates} doublon${st.duplicates > 1 ? 's' : ''}</span>` : '',
      !st.missing && !st.pending && !st.duplicates && st.due ? '<span class="is-ok">Complet</span>' : '',
      !st.due && st.upcoming ? `<span>${st.upcoming} à venir</span>` : ''].filter(Boolean).join('');
    return `<button class="folder-card dj-folder ${selected ? 'selected' : ''}" data-folder="${folder.slug}" aria-pressed="${selected}">
      <span class="dj-folder-top"><span class="dj-folder-name">${e(meta.name)}</span><span class="dj-folder-code">${meta.color} · ${meta.order}</span></span>
      <span class="dj-folder-body"><span class="dj-folder-figure">${count}</span>${djRing(ratio)}</span>
      <span class="dj-bar dj-folder-bar"><span style="width:${ratio}%"></span></span>
      <span class="dj-folder-meta">${notes || '<span>&nbsp;</span>'}</span></button>`;
  }).join('')}</div>`;
}

// --------------------------------------------------------------------------- onglet Documents
function djStatePill(status) {
  const [label, tone] = DJ_STATES[status] || [status, 'idle'];
  return `<span class="dj-state is-${tone}">${e(label)}</span>`;
}

function djRow(rule, docs, folder, duplicates = djDuplicateIndex()) {
  const doc = rule.documents.length ? docs.get(rule.documents[0].id) : null;
  const latest = doc?.latest;
  const {status, group} = djRowState(rule, duplicates);
  const subs = [];
  if (doc && doc.title !== rule.title && doc.title !== rule.document_type) subs.push(e(doc.title));
  if (group) subs.push(djDuplicateHint(group, rule.documents.slice(0, 1).map(d => d.id)));
  else if (rule.documents.length > 1) subs.push(`+ ${rule.documents.length - 1} autre(s) pièce(s) de ce type`);
  if (rule.status === 'not_due') subs.push(rule.required === false ? 'Facultatif · à déposer si besoin' : 'Non exigée par le profil de ce dossier');
  if (status === 'pending_validation') subs.push('Validation requise');
  if (rule.status === 'exception') subs.push(`Exception : ${e(rule.exception_reason || 'justifiée')}`);
  let action = '<span class="dj-none" aria-hidden="true">—</span>';
  if (group) {
    action = `<button class="secondary tiny dj-dup-btn" data-dj-duplicate="${e(group.sha256)}">Examiner le doublon</button>`;
  } else if (rule.status === 'missing' && folder.can_write) {
    action = `<button class="secondary tiny dj-upload-btn" data-dj-upload="${e(rule.id)}">${icon('upload')} Déposer</button>`;
  } else if (rule.status === 'pending_validation' && doc) {
    action = `${rule.can_review ? `<button class="primary tiny" data-complete-validate="${e(rule.id)}">${icon('check')} Valider</button>` : ''}<button class="secondary tiny" data-history="${e(doc.id)}">Examiner</button>`;
  } else if (doc) {
    action = `<button class="secondary tiny" data-history="${e(doc.id)}">Ouvrir</button>`;
  } else if (rule.status === 'not_due' && folder.can_write) {
    action = `<button class="link" data-dj-upload="${e(rule.id)}">Déposer</button>`;
  }
  const tone = DJ_STATES[status]?.[1] || 'idle';
  return `<tr class="dj-row is-${tone}" data-rule="${e(rule.id)}" data-state="${status}">
    <td data-label="Document"><strong>${e(rule.title)}</strong>${subs.length ? `<small>${subs.join(' · ')}</small>` : ''}</td>
    <td data-label="État">${djStatePill(status)}</td>
    <td data-label="Dernière version" class="${latest ? '' : 'is-empty'}">${latest ? `V${latest.number}` : '—'}</td>
    <td data-label="Date" class="${latest ? '' : 'is-empty'}">${latest ? niceDate(latest.created_at) : '—'}</td>
    <td class="dj-action" data-label="Action"><span class="dj-action-group">${action}</span></td></tr>`;
}

// « Identique à … » : la ou les autres pièces du groupe, avec leur sous-dossier.
function djDuplicateHint(group, ownIds) {
  const others = group.documents.filter(d => !ownIds.includes(d.document_id));
  const shown = (others.length ? others : group.documents.slice(1)).slice(0, 2)
    .map(d => `« ${e(d.title)} »${d.folder !== state.folder ? ` (${e(DJ_FOLDERS[d.folder]?.name || d.folder)})` : ''}`);
  return `Contenu identique à ${shown.join(', ')}`;
}

// Anneau de progression d'une carte de sous-dossier (SVG, sans texte).
function djRing(ratio) {
  const r = 15, length = 2 * Math.PI * r;
  return `<svg class="dj-ring" viewBox="0 0 36 36" aria-hidden="true" focusable="false"><circle class="dj-ring-track" cx="18" cy="18" r="${r}"/>
    <circle class="dj-ring-value" cx="18" cy="18" r="${r}" stroke-dasharray="${length.toFixed(2)}" stroke-dashoffset="${(length * (1 - ratio / 100)).toFixed(2)}"/></svg>`;
}

// Synthèse du dossier : un compteur par état, lisible d'un coup d'œil.
function djDossierTally() {
  const rows = state.completeness?.rows || [];
  const duplicates = djDuplicateIndex();
  const counts = {present: 0, missing: 0, pending_validation: 0, duplicate: 0, exception: 0};
  for (const rule of rows) { const {status} = djRowState(rule, duplicates); if (status in counts) counts[status] += 1; }
  const groups = (state.djDuplicates || []).filter(g => !g.reviewed).length;
  counts.duplicate = groups;
  const items = [['present', 'présent', 'présents'], ['missing', 'manquant', 'manquants'], ['pending_validation', 'en validation', 'en validation'],
    ['duplicate', 'doublon', 'doublons'], ['exception', 'exception', 'exceptions']]
    .filter(([key]) => key !== 'exception' || counts.exception)
    .map(([key, one, many]) => `<li class="dj-tally-item is-${DJ_STATES[key][1]}${counts[key] ? '' : ' is-zero'}"><strong>${counts[key]}</strong> ${counts[key] > 1 ? many : one}</li>`).join('');
  return `<ul class="dj-tally" aria-label="Synthèse des pièces">${items}</ul>`;
}

function djDocumentsPanel() {
  const folder = state.detail.folders.find(f => f.slug === state.folder) || state.detail.folders[0];
  const meta = DJ_FOLDERS[folder.slug];
  if (!folder.can_read) {
    return `<div class="detail-layout dj-docs"><div class="dj-empty">${icon('lock')}<p>Votre rôle ne donne pas accès au sous-dossier ${e(meta.name)}.</p></div></div>`;
  }
  const docs = djDocIndex();
  const duplicates = djDuplicateIndex();
  const rows = djSortedRows(folder.slug);
  const used = new Set(rows.flatMap(r => r.documents.slice(0, 1).map(x => x.id)));
  const others = (folder.documents || []).filter(doc => !used.has(doc.id));
  const configured = state.completeness?.configured;
  const checklist = rows.length
    ? `<div class="dj-table-wrap"><table class="dj-checklist"><caption class="sr-only">Checklist ${e(meta.name)}</caption>
        <colgroup><col class="dj-c-doc"><col class="dj-c-state"><col class="dj-c-ver"><col class="dj-c-date"><col class="dj-c-act"></colgroup>
        <thead><tr><th scope="col">Document</th><th scope="col">État</th><th scope="col">Dernière version</th><th scope="col">Date</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead>
        <tbody>${rows.map(rule => djRow(rule, docs, folder, duplicates)).join('')}</tbody></table></div>`
    : `<div class="dj-empty"><p>${configured ? 'Aucune pièce attendue dans ce sous-dossier pour ce profil.' : 'Ce dossier n’a pas encore de checklist documentaire.'}</p>
        ${!configured && state.completeness?.can_change_context ? '<button class="secondary tiny" id="dj-apply-standard-inline">Appliquer la checklist standard</button>' : ''}</div>`;
  const otherTable = others.length
    ? `<section class="dj-others"><h3>Autres pièces du sous-dossier</h3><div class="dj-table-wrap"><table class="dj-checklist dj-other-table">
        <colgroup><col class="dj-c-doc"><col class="dj-c-state"><col class="dj-c-ver"><col class="dj-c-date"><col class="dj-c-act"></colgroup>
        <thead><tr><th scope="col">Document</th><th scope="col">Type</th><th scope="col">Dernière version</th><th scope="col">Date</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead>
        <tbody>${others.map(doc => { const group = duplicates.get(doc.id);
          return `<tr class="dj-row${group ? ' is-duplicate' : ''}" data-doc="${e(doc.id)}"${group ? ' data-state="duplicate"' : ''}><td data-label="Document"><strong>${e(doc.title)}</strong><small>${e(doc.latest.original_name)}${group ? ` · ${djDuplicateHint(group, [doc.id])}` : ''}</small></td>
          <td data-label="Type">${group ? djStatePill('duplicate') : e(doc.doc_type)}</td><td data-label="Dernière version">V${doc.latest.number}</td><td data-label="Date">${niceDate(doc.latest.created_at)}</td>
          <td class="dj-action" data-label="Action"><span class="dj-action-group">${group ? `<button class="secondary tiny dj-dup-btn" data-dj-duplicate="${e(group.sha256)}">Examiner le doublon</button>` : `<button class="secondary tiny" data-history="${e(doc.id)}">Ouvrir</button>`}</span></td></tr>`; }).join('')}</tbody></table></div></section>`
    : '';
  const expected = rows.filter(r => r.required !== false).length;
  const phase = rows.length ? ` · ${expected} pièce${expected > 1 ? 's' : ''} obligatoire${expected > 1 ? 's' : ''}${rows.length > expected ? `, ${rows.length - expected} facultative${rows.length - expected > 1 ? 's' : ''}` : ''}` : '';
  return `<div class="detail-layout dj-docs" data-folder-panel="${folder.slug}">
      <div class="dj-docs-head"><div><h2><span class="dj-dot is-${folder.slug}" aria-hidden="true"></span>${e(meta.name)}</h2>
        <p>Checklist documentaire${phase}</p></div>
        ${folder.can_write ? `<div class="ops-dropzone dj-drop" id="ops-folder-drop">Glissez un fichier ici pour le déposer dans ${e(meta.name)}</div>` : ''}</div>
      ${checklist}${otherTable}</div>`;
}

// --------------------------------------------------------------------------- modules annexes
function djCompletenessModule() {
  const c = state.completeness;
  if (c && !c.configured) {
    return `<div class="section-heading"><div><h2>Complétude documentaire</h2></div></div>
      <div class="dj-empty"><p>Ce dossier n’a pas encore de checklist documentaire.</p>
      ${c.can_change_context ? '<button class="secondary tiny" id="dj-apply-standard-controls">Appliquer la checklist standard</button>' : ''}</div>`;
  }
  return renderCompleteness();
}

function djClientRequestModule() {
  const r = state.operationsDetail?.client_request, full = state.djClientRequest;
  if (!r) return `<div class="dj-empty"><p>Ce dossier a été ouvert directement par FRAMATEX, sans demande Client associée.</p></div>`;
  const docs = full?.documents || [];
  return `<div class="dj-module-head"><h2>Demande Client ${e(r.request_number)}</h2>${full ? `<button class="secondary tiny" id="dj-open-request">Ouvrir la demande</button>` : ''}</div>
    <dl class="dj-facts dj-facts-compact">${[djFact('Client', e(r.client)), djFact('Article', e(r.article)), djFact('Quantité', `${e(r.quantite)} pièces`),
      djFact('Date souhaitée', e(opsDay(r.date_souhaitee))), djFact('Référence client', e(r.reference_client || '—')),
      djFact('Statut', e(OPS_ORDER_LABELS[r.status] || r.status))].join('')}</dl>
    ${full ? `<h3>Pièces jointes par le client</h3>${docs.length ? `<ul class="dj-list">${docs.map(doc => `<li><strong>${e(opsDocTitle(doc.title))}</strong>${doc.versions.map(v => `<a class="link" href="/api/admin/client-order-requests/${encodeURIComponent(r.id)}/documents/${encodeURIComponent(doc.id)}/versions/${v.number}/download">${e(v.original_name)} · V${v.number}</a>`).join(' ')}</li>`).join('')}</ul>` : opsEmpty('Aucune pièce jointe à la demande.')}` : ''}`;
}

function djActivityModule() {
  const report = state.djActivity;
  if (!report) return `<div class="dj-empty"><p>Votre rôle ne donne pas accès à l’historique détaillé.</p></div>`;
  return `<div class="dj-module-head"><h2>Activité du dossier</h2><span class="dj-muted">${report.total} opération(s)</span></div>
    ${report.items.length ? `<ol class="dj-timeline">${report.items.map(row => `<li><time>${niceDate(row.occurred_at)}</time><div><strong>${e(opsAuditLabel(row.action))}</strong><span>${e(row.actor || 'Système')}${row.document_title ? ` · ${e(opsDocTitle(row.document_title))}` : ''}</span></div></li>`).join('')}</ol>` : opsEmpty('Aucune opération enregistrée.')}`;
}

function djNotesModule() {
  if (!can('document.read', 'jaune')) return '';
  const notes = state.djNotes || [];
  return `<section id="ops-notes"><div class="dj-module-head"><h2>Mémoire interne</h2>${can('document.write', 'jaune') ? '<button class="secondary tiny" id="ops-add-note">Ajouter un retour</button>' : ''}</div>
    <p class="dj-muted">Retours client, fournisseur et atelier liés à ce dossier. Ils restent internes.</p>
    ${notes.map(opsNote).join('') || opsEmpty('Aucun retour interne consigné.')}</section>`;
}

function djTechnicalModule() {
  const d = state.detail, c = state.completeness || {};
  return `<div class="dj-module-head"><h2>Détails techniques</h2></div>
    <dl class="dj-facts dj-facts-compact">${[djFact('Identifiant', `<code>${e(d.id)}</code>`), djFact('Créé le', niceDate(d.created_at)),
      djFact('Mis à jour le', niceDate(d.updated_at)), djFact('Accès', d.restricted ? 'Restreint aux membres' : 'Selon les rôles'),
      djFact('Profil documentaire', e(c.profile_name || 'Aucun')), djFact('Étape', e(phaseLabel(c.phase || 'preparation')))].join('')}</dl>`;
}

function djTabBadge(tab) {
  const s = state.operationsDetail || {};
  if (tab === 'documents') {
    const missing = (state.completeness?.counts?.missing) || 0;
    return missing ? `<span class="dj-badge is-missing">${missing}</span>` : '';
  }
  if (tab === 'controles' && s.alerts) return `<span class="dj-badge">${s.alerts}</span>`;
  return '';
}

function djModuleBadge(id) {
  const s = state.operationsDetail || {};
  const count = id === 'decisions' ? s.unacknowledged_changes : id === 'fiabilite' ? (s.inconsistencies || []).length
    : id === 'completude' ? ((state.completeness?.counts?.missing || 0) + (state.completeness?.counts?.pending_validation || 0)) : 0;
  return count ? `<span class="dj-badge">${count}</span>` : '';
}

function djPanels() {
  const ui = state.dj;
  const tabs = `<div class="dj-tabs" role="tablist" aria-label="Rubriques du dossier">${DJ_TABS.map(([id, label]) =>
    `<button role="tab" id="dj-tab-${id}" class="dj-tab" aria-selected="${ui.tab === id}" aria-controls="dj-panel-${id}" tabindex="${ui.tab === id ? 0 : -1}" data-dj-tab="${id}">${e(label)}${djTabBadge(id)}</button>`).join('')}</div>`;
  const panels = DJ_TABS.map(([id]) => {
    let body;
    if (id === 'documents') body = djDocumentsPanel();
    else {
      const modules = DJ_MODULES[id].map(([key, label, render]) => [key, label, render()]).filter(([, , html]) => html && String(html).trim());
      if (!modules.some(([key]) => key === ui.module[id]) && modules.length) ui.module[id] = modules[0][0];
      body = `<div class="dj-subnav" role="tablist" aria-label="${e(DJ_TABS.find(t => t[0] === id)[1])}">${modules.map(([key, label]) =>
          `<button role="tab" class="dj-chip" aria-selected="${ui.module[id] === key}" aria-controls="dj-module-${key}" data-dj-module="${id}:${key}">${e(label)}${djModuleBadge(key)}</button>`).join('')}</div>
        ${modules.map(([key, , html]) => `<section class="dj-module" role="tabpanel" id="dj-module-${key}" data-dj-section="${key}" ${ui.module[id] === key ? '' : 'hidden'}>${html}</section>`).join('')}`;
    }
    return `<div class="dj-panel" role="tabpanel" id="dj-panel-${id}" aria-labelledby="dj-tab-${id}" ${ui.tab === id ? '' : 'hidden'}>${body}</div>`;
  }).join('');
  return tabs + panels;
}

// --------------------------------------------------------------------------- rendu
renderDetail = function() {
  if (state.djSuspend || !state.detail) return;
  const d = state.detail;
  if (!d.folders.some(f => f.slug === state.folder)) state.folder = d.folders[0]?.slug || 'jaune';
  mount(`<div class="dj">${djHeader()}${djFolderCards()}${djPanels()}</div>`, 'Dossiers jaunes / ' + d.name);
  djBind();
};

function djSelectTab(tab, focus = false) {
  state.dj.tab = tab;
  app.querySelectorAll('[data-dj-tab]').forEach(button => {
    const active = button.dataset.djTab === tab;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  });
  app.querySelectorAll('.dj-panel').forEach(panel => {
    const active = panel.id === `dj-panel-${tab}`;
    panel.hidden = !active;
    if (active) panel.classList.add('is-entering');
  });
}

function djSelectModule(tab, module) {
  state.dj.module[tab] = module;
  const panel = app.querySelector(`#dj-panel-${tab}`);
  panel?.querySelectorAll('[data-dj-module]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.djModule === `${tab}:${module}`)));
  panel?.querySelectorAll('.dj-module').forEach(section => {
    section.hidden = section.dataset.djSection !== module;
    if (!section.hidden) section.classList.add('is-entering');
  });
}

async function djApplyStandard() {
  try {
    await api(`/api/launches/${encodeURIComponent(state.detail.id)}/completeness/standard`, {method: 'POST'});
    toast('Checklist standard appliquée · étape Préparation');
    await openLaunch(state.detail.id, state.folder);
  } catch (error) { showErr(error); }
}

const djAccessObserver = new MutationObserver(() => {
  const button = app.querySelector('.dj-head > #manage-launch-access');
  const actions = app.querySelector('.dj-head-actions');
  if (button && actions) { button.classList.remove('tiny'); actions.appendChild(button); }
});
djAccessObserver.observe(app, {childList: true, subtree: true});

function djBind() {
  const d = state.detail;
  app.querySelector('#back-launches').onclick = () => navigate('launches');
  app.querySelector('#edit-launch')?.addEventListener('click', openEditLaunch);
  app.querySelector('#ops-edit')?.addEventListener('click', () => operationsEditLaunch().catch(showErr));
  app.querySelector('#upload-doc')?.addEventListener('click', () => dossierUpload({folder: state.folder}).catch(showErr));
  app.querySelector('#dj-edit-phase')?.addEventListener('click', editCompletenessContext);
  ['#dj-apply-standard', '#dj-apply-standard-inline', '#dj-apply-standard-controls'].forEach(id => app.querySelector(id)?.addEventListener('click', djApplyStandard));
  app.querySelectorAll('.dj-folder[data-folder]').forEach(card => card.addEventListener('click', () => {
    state.folder = card.dataset.folder; state.dj.tab = 'documents'; state.dj.highlight = null; renderDetail();
    app.querySelector('.dj-tabs')?.scrollIntoView?.({block: 'nearest'});
  }));
  const tabs = [...app.querySelectorAll('[data-dj-tab]')];
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => djSelectTab(button.dataset.djTab));
    button.addEventListener('keydown', event => {
      const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      djSelectTab(tabs[(index + step + tabs.length) % tabs.length].dataset.djTab, true);
    });
  });
  app.querySelectorAll('[data-dj-module]').forEach(button => button.addEventListener('click', () => {
    const [tab, module] = button.dataset.djModule.split(':');
    djSelectModule(tab, module);
  }));
  app.querySelectorAll('[data-dj-goto]').forEach(button => button.addEventListener('click', () => {
    const [tab, module] = button.dataset.djGoto.split(':');
    djSelectTab(tab); djSelectModule(tab, module);
    app.querySelector('.dj-tabs')?.scrollIntoView?.({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  }));
  app.querySelectorAll('[data-dj-upload]').forEach(button => button.addEventListener('click', () => {
    const rule = state.completeness.rows.find(r => r.id === button.dataset.djUpload);
    dossierUpload({folder: rule.folder, type: rule.document_type, title: rule.title, ruleId: rule.id}).catch(showErr);
  }));
  app.querySelectorAll('[data-history]').forEach(button => button.addEventListener('click', () => openVersions(button.dataset.history)));
  app.querySelectorAll('[data-dj-duplicate]').forEach(button => button.addEventListener('click', () => djDuplicateModal(button.dataset.djDuplicate)));
  app.querySelector('#ops-add-note')?.addEventListener('click', () => operationsAddNote(d.id));
  app.querySelector('#dj-open-request')?.addEventListener('click', () => operationsClientRequest(state.operationsDetail.client_request.id).catch(showErr));
  opsBindDrop(app.querySelector('#ops-folder-drop'), file => dossierUpload({folder: state.folder, file}).catch(showErr));
  // Modules historiques : liaisons inchangées.
  bindCompleteness(); bindWorkflow(); bindQuality(); bindIntake(); bindPaper(); bindSpec(); bindMail();
  bindImpactSimulation(); bindOrliReconciliation(); bindMaterialReport(); bindApprovals(); bindSharing();
  djAnnotateExcelFindings();
  djConsolidateNotes();
  if (state.dj.highlight) {
    const target = state.dj.highlight;
    const row = target.startsWith('doc:') ? app.querySelector(`.dj-row[data-doc="${CSS.escape(target.slice(4))}"]`)
      : app.querySelector(`.dj-row[data-rule="${CSS.escape(target)}"]`);
    if (row) {
      row.classList.add('is-target');
      row.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
      row.querySelector('button')?.focus({preventScroll: true});
      setTimeout(() => row.classList.remove('is-target'), 2600);
    }
    state.dj.highlight = null;
  }
}

// Les précautions d'usage restent disponibles, regroupées dans une note « À savoir »
// repliée par module, au lieu d'être répétées en tête de chaque bloc.
// Phrases fixes de précaution des modules (jamais de contenu saisi par un utilisateur).
const DJ_NOTES = ['Les valeurs sont saisies à partir d’une version documentaire identifiable', 'Les alertes sont générées uniquement par des règles métier',
  'Une approbation porte sur une version donnée', 'Compare deux types de pièces d’un même lancement', 'Inspection lors du dépôt d’un .xlsx',
  'Les divergences et signaux Excel demandent une vérification humaine', 'Analyse locale du fichier', 'Les résultats de l’analyse n’équivalent pas',
  'Analyse limitée aux passages lisibles du document', 'Les liens de calcul sont explicites', 'Les données affichées proviennent de déclarations',
  '* Reste à recevoir', 'Les rapprochements proposés reposent uniquement', 'Seules les versions autorisées et validées',
  'Ces vues servent à tester les règles métier', 'Les contrôles sont indicatifs'].map(text => text.replace(/[’']/g, '\''));
function djConsolidateNotes() {
  const isNote = el => { const text = el.textContent.trim().replace(/[’']/g, '\''); return DJ_NOTES.some(prefix => text.startsWith(prefix)); };
  app.querySelectorAll('.dj-module').forEach(module => {
    if (module.querySelector(':scope > .dj-help')) return;
    const notes = [...module.querySelectorAll('p, .ops-muted, .notice')].filter(el =>
      !el.closest('table, form, li, button, label, details, .modal, #ops-notes, .ops-comment') && !el.querySelector('button, input, select, textarea, a') && isNote(el));
    if (!notes.length) return;
    const help = document.createElement('details');
    help.className = 'dj-help';
    help.innerHTML = `<summary>${icon('info')} À savoir sur ce contrôle</summary><div class="dj-help-body"></div>`;
    notes.forEach(note => help.lastElementChild.appendChild(note));
    module.appendChild(help);
  });
}

function djAnnotateExcelFindings() {
  const findings = (state.excelInspections || []).flatMap(row => row.inspection?.findings?.slice(0, 12) || []);
  app.querySelectorAll('.quality-findings li').forEach((element, index) => {
    const finding = findings[index];
    if (!finding) return;
    element.insertAdjacentHTML('beforeend', `<span class="ops-pill ${finding.level === 'critical' ? 'warn' : ''}">${e(finding.level === 'critical' ? 'Attention élevée' : 'À examiner')}</span>${finding.before !== undefined || finding.after !== undefined ? `<code class="ops-hash">Avant : ${e(finding.before ?? '—')}<br>Après : ${e(finding.after ?? '—')}</code>` : ''}`);
  });
}

// Accès direct depuis les actions et les fiches : bon onglet, bon module, bonne ligne.
focusWorkspaceArea = function(area) {
  const target = DJ_AREAS[area];
  if (!target || state.view !== 'detail') return;
  const [tab, module] = target;
  djSelectTab(tab);
  if (module) djSelectModule(tab, module);
  const node = module ? app.querySelector(`#dj-module-${module}`) : app.querySelector('#dj-panel-documents');
  node?.scrollIntoView?.({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
};

// --------------------------------------------------------------------------- doublons
function djDuplicateModal(digest) {
  const group = (state.djDuplicates || []).find(g => g.sha256 === digest);
  if (!group) return;
  const canReview = [...new Set(group.documents.map(d => d.folder))].every(folder => can('document.review', folder));
  modal('Doublon détecté', `<p class="modal-desc">Ces ${group.documents.length} pièces ont exactement le même contenu (empreinte SHA-256 identique). La complétude n’est pas modifiée : la pièce reste comptée présente.</p>
    <ul class="dj-dup-list">${group.documents.map(d => `<li>
      <span class="dj-dup-folder"><span class="dj-dot is-${e(d.folder)}" aria-hidden="true"></span>${e(DJ_FOLDERS[d.folder]?.name || d.folder)}</span>
      <span class="dj-dup-main"><strong>${e(d.title)}</strong><small>${e(d.doc_type)} · V${d.version} · ${e(d.original_name)} · ${niceDate(d.created_at)}</small></span>
      <button class="secondary tiny" type="button" data-dup-open="${e(d.document_id)}">Ouvrir</button></li>`).join('')}</ul>
    <div class="dj-dup-options">
      <p><strong>Pièce déposée par erreur ?</strong> Ouvrez-la et déposez la bonne version : elle quitte alors le doublon.</p>
      ${canReview ? `<form id="dj-dup-form" class="dj-dup-form" novalidate>
        <p><strong>Les deux pièces doivent rester ?</strong> Indiquez pourquoi ; la décision est conservée dans l’historique.</p>
        <div class="field"><label for="dj-dup-reason">Motif</label><textarea id="dj-dup-reason" rows="2" minlength="8" maxlength="1000" required placeholder="Ex. même email transmis par deux interlocuteurs"></textarea></div>
        <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Fermer</button><button class="primary" type="submit">${icon('check')} Conserver et marquer comme examiné</button></div>
      </form>` : '<p class="dj-muted">Votre rôle ne permet pas de statuer sur ce doublon.</p>'}
    </div>`);
  overlay.querySelector('#cancel-modal')?.addEventListener('click', closeModal);
  overlay.querySelectorAll('[data-dup-open]').forEach(button => button.addEventListener('click', () => openVersions(button.dataset.dupOpen)));
  overlay.querySelector('#dj-dup-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const reason = overlay.querySelector('#dj-dup-reason').value.trim();
    if (reason.length < 8) { toast('Indiquez un motif d’au moins 8 caractères.'); overlay.querySelector('#dj-dup-reason').focus(); return; }
    const submit = event.submitter || event.target.querySelector('[type=submit]');
    submit.disabled = true;
    try {
      await api(`/api/launches/${encodeURIComponent(state.detail.id)}/duplicates/review`, {method: 'POST', body: JSON.stringify({sha256: digest, reason})});
      closeModal();
      toast('Doublon examiné : les pièces sont conservées.');
      await openLaunch(state.detail.id, state.folder);
    } catch (error) { submit.disabled = false; showErr(error); }
  });
}

opsTargetData = function(item) {
  // Lignes de complétude (tableau de bord) ou actions « pièce manquante / validation » : aller à la ligne.
  const rule = item.rule_id || (/^(missing|validation):/.test(item.id || '') ? item.id.split(':')[1] : (item.due !== undefined ? item.id : undefined));
  return e(JSON.stringify({launch_id: item.launch_id, folder: item.folder, document_id: item.document_id, version_id: item.version_id, area: item.area, rule_id: rule,
    row_document: item.row_document}));
};

const djOriginalOpenTarget = opsOpenTarget;
opsOpenTarget = async function(target) {
  if (target.rule_id || target.row_document) {
    await openLaunch(target.launch_id, target.folder || 'jaune', {rule_id: target.rule_id, row_document: target.row_document, folder: target.folder});
    return;
  }
  return djOriginalOpenTarget(target);
};

// --------------------------------------------------------------------------- dépôt
async function dossierUpload(options = {}) {
  if (options instanceof Event) options = {};
  if (options instanceof File) options = {file: options};
  const d = state.detail;
  const folders = d.folders.filter(f => f.can_write);
  if (!folders.length) { toast('Votre rôle ne permet pas de déposer dans ce dossier.'); return; }
  const catalog = await api('/api/workspace/document-types');
  const start = folders.some(f => f.slug === options.folder) ? options.folder : folders.some(f => f.slug === state.folder) ? state.folder : folders[0].slug;
  modal('Déposer un document', `<form id="ops-upload-form" class="dj-upload" novalidate>
      <div class="two-fields">
        <div class="field"><label for="ops-folder">Sous-dossier</label><select id="ops-folder">${folders.map(f => `<option value="${f.slug}" ${f.slug === start ? 'selected' : ''}>${e(DJ_FOLDERS[f.slug].name)}</option>`).join('')}</select></div>
        <div class="field"><label for="ops-type">Type documentaire</label><input id="ops-type" list="ops-types" maxlength="100" required autocomplete="off" value="${e(options.type || '')}" placeholder="Choisir un type"><datalist id="ops-types"></datalist></div>
      </div>
      <div class="ops-dropzone" id="ops-upload-drop"><input id="ops-file" aria-label="Fichier à déposer" type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.txt,.eml,.csv"><p id="ops-file-name">${e(options.file?.name || 'Glissez le fichier ici ou choisissez-le · PDF, Word, Excel, image, TXT, EML, CSV · 20 Mo maximum')}</p></div>
      <div class="dj-version-note" id="dj-version-note" aria-live="polite" hidden></div>
      <div class="two-fields">
        <div class="field"><label for="ops-title">Titre affiché</label><input id="ops-title" maxlength="220" value="${e(options.title || options.type || '')}"></div>
        <div class="field"><label for="ops-upload-comment">Commentaire <span class="dj-optional">(facultatif)</span></label><input id="ops-upload-comment" maxlength="2000"></div>
      </div>
      <button class="link dj-ocr" type="button" id="ops-analyze">Proposer le type à partir du fichier</button>
      <div id="ops-analysis" aria-live="polite"></div>
      <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="submit">${icon('upload')} Déposer</button></div>
    </form>`);
  const form = overlay.querySelector('#ops-upload-form');
  const folderInput = overlay.querySelector('#ops-folder'), typeInput = overlay.querySelector('#ops-type');
  const titleInput = overlay.querySelector('#ops-title'), note = overlay.querySelector('#dj-version-note');
  let selected = options.file || null, titleEdited = Boolean(options.title && options.title !== options.type);
  const rulesFor = slug => (state.completeness?.rows || []).filter(r => r.folder === slug);
  const existingDoc = () => (d.folders.find(f => f.slug === folderInput.value)?.documents || [])
    .filter(doc => doc.doc_type === typeInput.value.trim()).sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at))[0];
  const drawTypes = () => {
    const rules = rulesFor(folderInput.value);
    const labelled = new Map(rules.map(r => [r.document_type, r.title]));
    const types = [...new Set([...rules.map(r => r.document_type), ...(catalog[folderInput.value]?.types || ['Autre'])])];
    overlay.querySelector('#ops-types').innerHTML = types.map(t => `<option value="${e(t)}"${labelled.get(t) && labelled.get(t) !== t ? ` label="${e(labelled.get(t))}"` : ''}></option>`).join('');
  };
  const drawNote = () => {
    const doc = existingDoc();
    note.hidden = !doc;
    note.innerHTML = doc ? `<p>« ${e(doc.title)} » existe déjà (V${doc.latest.number}). Ce fichier sera enregistré comme <strong>V${doc.latest.number + 1}</strong> sur la même ligne.</p>
      <label class="checkbox-line"><input type="checkbox" id="dj-separate"> Déposer plutôt comme un document distinct</label>` : '';
  };
  const choose = file => {
    selected = file;
    overlay.querySelector('#ops-file-name').textContent = file.name;
    if (!titleInput.value) titleInput.value = typeInput.value || file.name.replace(/\.[^.]+$/, '');
  };
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  overlay.querySelector('#ops-file').onchange = event => event.target.files[0] && choose(event.target.files[0]);
  opsBindDrop(overlay.querySelector('#ops-upload-drop'), choose);
  folderInput.onchange = () => { drawTypes(); drawNote(); };
  typeInput.addEventListener('input', () => {
    if (!titleEdited) titleInput.value = rulesFor(folderInput.value).find(r => r.document_type === typeInput.value.trim())?.title || typeInput.value;
    drawNote();
  });
  titleInput.addEventListener('input', () => { titleEdited = true; });
  drawTypes(); drawNote();
  if (selected) choose(selected);
  overlay.querySelector('#ops-analyze').onclick = async () => {
    if (!selected) { toast('Choisissez d’abord un fichier.'); return; }
    const fd = new FormData(); fd.append('file', selected);
    try {
      const result = await api(`/api/launches/${d.id}/intake/preview`, {method: 'POST', body: fd});
      const zone = overlay.querySelector('#ops-analysis');
      zone.innerHTML = result.classification.suggestions.length
        ? `<p class="dj-muted">Types proposés (à confirmer) :</p>${result.classification.suggestions.map((s, i) => `<button class="secondary tiny" type="button" data-ops-suggestion="${i}">${e(s.doc_type)} · ${e(DJ_FOLDERS[s.folder]?.name || s.folder)}</button>`).join(' ')}`
        : '<p class="dj-muted">Aucun type reconnu dans ce fichier.</p>';
      zone.querySelectorAll('[data-ops-suggestion]').forEach(button => button.onclick = () => {
        const proposal = result.classification.suggestions[Number(button.dataset.opsSuggestion)];
        if ([...folderInput.options].some(o => o.value === proposal.folder)) folderInput.value = proposal.folder;
        typeInput.value = proposal.doc_type; drawTypes(); typeInput.dispatchEvent(new Event('input'));
      });
    } catch (error) { showErr(error); }
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const type = typeInput.value.trim();
    if (!selected) { toast('Choisissez le fichier à déposer.'); return; }
    if (!type) { toast('Indiquez le type documentaire.'); typeInput.focus(); return; }
    if (selected.size > 20 * 1024 * 1024) { toast('Fichier supérieur à 20 Mo : dépôt impossible.'); return; }
    const submit = event.submitter || form.querySelector('[type=submit]');
    const label = submit.innerHTML;
    submit.disabled = true; submit.setAttribute('aria-busy', 'true'); submit.textContent = 'Dépôt en cours…';
    const folder = folderInput.value, existing = existingDoc(), separate = overlay.querySelector('#dj-separate')?.checked;
    const fd = new FormData();
    fd.append('file', selected);
    fd.append('comment', val('ops-upload-comment'));
    try {
      let result;
      if (existing && !separate) {
        result = await api(`/api/documents/${existing.id}/versions`, {method: 'POST', body: fd});
      } else {
        fd.append('folder', folder); fd.append('title', titleInput.value.trim() || type); fd.append('doc_type', type);
        result = await api(`/api/launches/${d.id}/documents`, {method: 'POST', body: fd});
      }
      closeModal();
      const rule = rulesFor(folder).find(r => r.document_type === type);
      await openLaunch(d.id, folder, rule ? {rule_id: rule.id} : {folder});
      const updated = rule && state.completeness.rows.find(r => r.id === rule.id);
      const status = updated ? DJ_STATES[updated.status]?.[0] : null;
      toast(`${rule ? rule.title : (result.title || 'Document')} déposé${existing && !separate ? ` · V${result.latest?.number || ''}` : ''}${status ? ` · ${status}` : ''}${result.duplicates?.length ? ' · contenu identique déjà présent' : ''}`);
    } catch (error) {
      showErr(error);
    } finally {
      if (submit.isConnected) { submit.disabled = false; submit.removeAttribute('aria-busy'); submit.innerHTML = label; }
    }
  };
}
operationsUpload = dossierUpload;
openUpload = function(file) { dossierUpload(file instanceof File ? {file} : {}).catch(showErr); };

// Nouveau dossier : la checklist standard est appliquée d'emblée (étape Préparation).
openNewLaunch = function() {
  modal('Nouveau Dossier Jaune', `<form id="new-launch-form">
      <div class="field"><label for="l-name">Nom du dossier</label><input id="l-name" maxlength="180" required placeholder="Ex. Vestes coton · lot automne"></div>
      <div class="two-fields"><div class="field"><label for="l-client">Client</label><input id="l-client" maxlength="150"></div>
        <div class="field"><label for="l-order">Référence commande</label><input id="l-order" maxlength="100"></div></div>
      <div class="field"><label for="l-orli">Référence ORLI <span class="dj-optional">(si disponible)</span></label><input id="l-orli" maxlength="100"></div>
      <p class="dj-muted">Le dossier est créé avec ses quatre sous-dossiers et la checklist standard, à l’étape Préparation.</p>
      <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="submit">${icon('plus')} Créer le dossier</button></div></form>`);
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  overlay.querySelector('#new-launch-form').onsubmit = async event => {
    event.preventDefault();
    try {
      const created = await api('/api/launches', {method: 'POST', body: JSON.stringify({name: val('l-name'), client_name: val('l-client') || null,
        order_ref: val('l-order') || null, orli_ref: val('l-orli') || null, standard_profile: true})});
      closeModal(); toast('Dossier Jaune créé avec sa checklist');
      await openLaunch(created.id, 'jaune');
    } catch (error) { showErr(error); }
  };
};

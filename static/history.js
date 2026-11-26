'use strict';
/* Historique détaillé et cliquable (global, par commande, par document), sur l'audit existant.
   Chaque ligne : date et heure, auteur, action, commande, sous-dossier, type, fichier, version,
   avant/après, motif. Les droits sont appliqués par le serveur ; un document supprimé n'est
   jamais rouvert depuis l'historique ordinaire (accès à la corbeille pour l'administrateur). */
const HIST_UNKNOWN = '<span class="hist-unknown">Information non enregistrée</span>';
const HIST_FOLDERS = {jaune: 'Sous-dossier jaune', rose: 'Sous-dossier rose', bleu: 'Sous-dossier bleu', vert: 'Sous-dossier vert'};

function histWhen(value) {
  const raw = String(value || ''); const date = new Date(/Z$|[+-]\d\d:\d\d$/.test(raw) ? raw : raw + 'Z');
  return {day: date.toLocaleDateString('fr-FR', {day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Africa/Casablanca'}),
          time: date.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Casablanca'})};
}
function histValue(value) {
  if (value === null || value === undefined || value === '') return '<em class="hist-empty">vide</em>';
  if (Array.isArray(value)) return value.length ? e(value.map(a => (typeof ACC_ACTION_LABELS === 'object' && ACC_ACTION_LABELS[a]) || a).join(', ')) : '<em class="hist-empty">aucun droit</em>';
  return e(String(value));
}

function histRows(items, {compact = false} = {}) {
  if (!items.length) return opsEmpty('Aucune opération enregistrée pour ce périmètre.');
  return `<ol class="hist-list">${items.map(row => {
    const when = histWhen(row.occurred_at);
    const isDoc = Boolean(row.document_id);
    const meta = [
      !compact && row.launch_name ? `<span>${e(row.launch_name)}</span>` : '',
      row.folder ? `<span><i class="hist-dot is-${e(row.folder)}"></i>${e(HIST_FOLDERS[row.folder] || row.folder)}</span>` : '',
      isDoc ? `<span>${e(row.doc_type || '')}${row.doc_type ? ' · ' : ''}${row.original_name ? e(row.original_name) : HIST_UNKNOWN}</span>` : '',
      isDoc ? `<span>${row.version_number ? `V${row.version_number}` : row.versions?.length ? row.versions.map(n => `V${n}`).join(', ') : HIST_UNKNOWN}</span>` : '',
    ].filter(Boolean).join('');
    const changes = row.changes?.length ? `<details class="hist-changes"><summary>${row.changes.length} modification${row.changes.length > 1 ? 's' : ''}</summary>
      <table><thead><tr><th>Champ</th><th>Avant</th><th>Après</th></tr></thead><tbody>${row.changes.map(c => `<tr><td>${e(c.label)}</td><td>${histValue(c.before)}</td><td>${histValue(c.after)}</td></tr>`).join('')}</tbody></table></details>` : '';
    let action = '';
    if (isDoc && (row.doc_deleted || row.version_deleted)) action = state.me?.admin ? `<button type="button" class="secondary tiny" data-hist-trash>Voir la corbeille</button>` : '<span class="hist-deleted">Supprimé</span>';
    else if (isDoc) action = `<button type="button" class="secondary tiny" data-hist-doc="${e(row.document_id)}" data-hist-version="${e(row.history_version_id || '')}" data-hist-launch="${e(row.launch_id)}" data-hist-folder="${e(row.folder || '')}">Ouvrir${row.version_number ? ` V${row.version_number}` : ''}</button>`;
    else if (row.launch_id && !compact) action = `<button type="button" class="link" data-hist-open-launch="${e(row.launch_id)}">Ouvrir la commande</button>`;
    return `<li class="hist-row"><time datetime="${e(row.occurred_at)}">${when.day}<small>${when.time}</small></time>
      <div class="hist-main"><strong>${e(opsAuditLabel(row.action))}</strong> <span class="hist-actor">par ${e(row.actor || 'Système')}</span>
        ${meta ? `<p class="hist-meta">${meta}</p>` : ''}${changes}${row.reason ? `<p class="hist-reason">Motif : ${e(row.reason)}</p>` : ''}</div>
      <div class="hist-act">${action}</div></li>`;
  }).join('')}</ol>`;
}

// Ouverture depuis l'historique (délégation : vue globale, commande, visionneuse).
document.addEventListener('click', async event => {
  const doc = event.target.closest('[data-hist-doc]');
  const launch = event.target.closest('[data-hist-open-launch]');
  const trash = event.target.closest('[data-hist-trash]');
  if (!doc && !launch && !trash) return;
  event.preventDefault();
  try {
    if (overlay.querySelector('.modal')) closeModal();
    if (trash) return await navigate('trash');
    if (launch) return await openLaunch(launch.dataset.histOpenLaunch);
    await openLaunch(doc.dataset.histLaunch, doc.dataset.histFolder || undefined);
    await operationsDocument(doc.dataset.histDoc, doc.dataset.histVersion || null);
  } catch (error) { showErr(error); }
});

// Historique global (administrateur et rôles disposant de l'audit) : mêmes filtres, rendu détaillé.
operationsAudit = async function() {
  state.view = 'audit';
  const [launches, users] = await Promise.all([api('/api/launches'), state.me.admin ? api('/api/admin/users') : Promise.resolve([])]);
  const actions = Object.entries(OPS_AUDIT_LABELS).sort((a, b) => a[1].localeCompare(b[1], 'fr'));
  mount(`${opsHeading('Historique et audit', 'Opérations horodatées et immuables ; chaque événement s’ouvre sur l’élément concerné, selon vos habilitations.')}
    <form class="ops-filters" id="ops-audit-form">
      <div class="field"><label for="launch_id">Commande</label><select id="launch_id" name="launch_id"><option value="">Toutes les commandes accessibles</option>${launches.map(l => `<option value="${e(l.id)}">${e(l.order_ref || l.name)}</option>`).join('')}</select></div>
      <div class="field"><label for="actor_id">Auteur</label><select id="actor_id" name="actor_id"><option value="">Tous les auteurs</option>${users.map(u => `<option value="${e(u.id)}">${e(u.name)}</option>`).join('')}</select></div>
      <div class="field"><label for="action">Action</label><input id="action" name="action" list="hist-actions" autocomplete="off" placeholder="Toutes les actions"><datalist id="hist-actions">${actions.map(([k, l]) => `<option value="${e(k)}">${e(l)}</option>`).join('')}</datalist></div>
      ${opsField('document_id', 'Identifiant document')}${opsField('date_from', 'Depuis', 'date')}${opsField('date_to', 'Jusqu’au', 'date')}
      <button class="primary" type="submit">Filtrer</button></form><section class="ops-panel" id="ops-audit-results" aria-live="polite"></section>`, 'Historique et audit');
  const form = app.querySelector('#ops-audit-form'); let offset = 0, seq = 0;
  const draw = async () => {
    const mine = ++seq; const params = new URLSearchParams();
    for (const [k, v] of new FormData(form)) if (v) params.set(k, v);
    params.set('offset', offset); params.set('limit', 50);
    const report = await api('/api/workspace/activity?' + params);
    if (mine !== seq) return;
    const box = app.querySelector('#ops-audit-results');
    const more = report.has_more ?? (offset + report.items.length < report.total);
    box.innerHTML = `<p class="ops-muted">${report.total ?? `${offset + report.items.length}${more ? '+' : ''}`} opération(s) · ${report.items.length ? `${offset + 1}–${offset + report.items.length}` : '0'}</p>${histRows(report.items)}
      <div class="hist-pager">${offset ? '<button type="button" class="secondary tiny" data-hist-prev>Précédentes</button>' : ''}${more ? '<button type="button" class="secondary tiny" data-hist-next>Suivantes</button>' : ''}</div>`;
    box.querySelector('[data-hist-prev]')?.addEventListener('click', () => { offset = Math.max(0, offset - 50); draw().catch(showErr); });
    box.querySelector('[data-hist-next]')?.addEventListener('click', () => { offset += 50; draw().catch(showErr); });
  };
  form.onsubmit = event => { event.preventDefault(); offset = 0; draw().catch(showErr); };
  await draw();
};

// Historique de la commande (onglet « Historique » du Dossier Jaune).
djActivityModule = function() {
  const report = state.djActivity;
  if (!report) return '<div class="dj-empty"><p>Votre rôle ne donne pas accès à l’historique détaillé.</p></div>';
  return `<div class="dj-module-head"><h2>Historique de la commande</h2><span class="dj-muted">${report.total} opération(s)</span></div>${histRows(report.items, {compact: true})}`;
};

// Historique du document, dans la colonne d'actions de la visionneuse.
const histBaseDocument = operationsDocument;
operationsDocument = async function(id, versionId = null) {
  await histBaseDocument(id, versionId);
  const side = overlay.querySelector('.dv-side');
  if (!side || side.querySelector('.hist-doc') || !can('audit.read')) return;   // sans droit d'audit : aucune requête
  try {
    const report = await api(`/api/workspace/activity?document_id=${encodeURIComponent(id)}&limit=50`);
    side.insertAdjacentHTML('beforeend', `<section class="hist-doc"><h3>Historique du document</h3>${histRows(report.items, {compact: true})}</section>`);
  } catch { /* sans droit d'audit : section absente, la fiche reste utilisable */ }
};

// Libellés lisibles des événements récents (les libellés existants sont conservés).
Object.assign(OPS_AUDIT_LABELS, Object.fromEntries(Object.entries({
  'launch.sheet.update': 'Fiche commande modifiée', 'launch.operations.update': 'Suivi de commande modifié',
  'access.assignment.grant': 'Habilitation accordée', 'access.assignment.update': 'Habilitation modifiée', 'access.assignment.revoke': 'Habilitation retirée',
  'intake.classification.confirm': 'Classement confirmé', 'intake.classification.publish': 'Classement publié', 'value.record': 'Valeur extraite confirmée',
  'completeness.validate': 'Validation de pièce', 'document.relationship.decide': 'Décision de rapprochement', 'document.duplicate.review': 'Doublon examiné',
  'client.shared_document.published': 'Partage avec le client', 'client.shared_document.revoked': 'Retrait du partage client',
  'optional_case.create': 'Case complémentaire créée', 'optional_case.update': 'Case complémentaire modifiée',
  'optional_case.delete': 'Case complémentaire supprimée', 'optional_case.restore': 'Case complémentaire restaurée',
  'optional_case.attach': 'Document complémentaire déposé',
}).filter(([key]) => !OPS_AUDIT_LABELS[key])));

/* Tableau de bord FRAMATEX : ce qui manque, ce qui attend une décision, et où cliquer.
   Ordre : indicateurs → actions prioritaires → documents manquants → complétude
   des dossiers → alertes → activité récente. Chaque ligne de document manquant
   ouvre le dossier, le bon sous-dossier et la bonne ligne de checklist. */

const DASH_FOLDERS = ['jaune', 'rose', 'bleu', 'vert'];
const DASH_KPIS = {
  dossiers: [['active_launches', 'Dossiers actifs'], ['complete_launches', 'Dossiers complets'], ['incomplete_launches', 'Dossiers incomplets']],
  todo: [['missing_documents', 'Documents manquants'], ['pending_documents', 'Documents à valider'], ['alerts', 'Alertes à traiter'],
    ['inconsistencies', 'Incohérences détectées'], ['unacknowledged_changes', 'Modifications à examiner']],
};
const DASH_PAGE = 8;

OPS_AUDIT_LABELS['client.order_request.launch_created'] = 'Dossier Jaune créé depuis une demande Client';

function dashKpi([key, label], k, attention) {
  return `<button class="ops-kpi dash-kpi ${attention && k[key] ? 'attention' : ''}" data-ops-kpi="${key}"><strong>${e(k[key] ?? 0)}</strong><span>${e(label)}</span></button>`;
}

function dashMissingRows(report) {
  const filter = state.dashFilter || 'all';
  const rows = report.missing_documents.filter(row => filter === 'all' || row.folder === filter);
  const shown = state.dashShowAll ? rows : rows.slice(0, DASH_PAGE);
  return {rows, shown};
}

function dashMissingTable(report) {
  const {rows, shown} = dashMissingRows(report);
  if (!rows.length) return opsEmpty(report.missing_documents.length ? 'Aucune pièce manquante dans ce sous-dossier.' : 'Aucune pièce exigible manquante.');
  const body = shown.map(row => {
    const meta = DJ_FOLDERS[row.folder] || {name: row.folder};
    return `<tr class="dj-row is-missing dash-row" data-dash-row>
      <td data-label="Sous-dossier"><span class="dash-folder"><span class="dj-dot is-${e(row.folder)}" aria-hidden="true"></span>${e(meta.name)}</span></td>
      <td data-label="Document"><strong>${e(row.title)}</strong><small>Exigible dès l’étape ${e(phaseLabel(row.due_phase))}</small></td>
      <td data-label="Commande / dossier"><strong class="dash-ref">${e(row.order_ref || row.launch_name)}</strong><small>${e(row.article || row.launch_name)}</small></td>
      <td data-label="Client">${e(row.client_name || '—')}</td>
      <td data-label="État">${djStatePill('missing')}</td>
      <td class="dj-action" data-label="Action"><span class="dj-action-group"><button class="secondary tiny" data-ops-target="${opsTargetData(row)}" aria-label="Ouvrir ${e(row.title)} · ${e(row.order_ref || row.launch_name)}">Ouvrir ${icon('arrow')}</button></span></td></tr>`;
  }).join('');
  const more = rows.length > shown.length
    ? `<button class="link dash-more" id="dash-more">Afficher les ${rows.length - shown.length} autres pièces</button>` : '';
  return `<div class="dj-table-wrap"><table class="dj-checklist dash-table dash-missing-table"><caption class="sr-only">Documents manquants</caption>
    <colgroup><col class="dash-c-folder"><col class="dash-c-doc"><col class="dash-c-ref"><col class="dash-c-client"><col class="dash-c-state"><col class="dash-c-act"></colgroup>
    <thead><tr><th scope="col">Sous-dossier</th><th scope="col">Document</th><th scope="col">Commande / dossier</th><th scope="col">Client</th><th scope="col">État</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead>
    <tbody>${body}</tbody></table></div>${more}`;
}

function dashMissingPanel(report) {
  const missing = report.missing_documents;
  const filter = state.dashFilter || 'all';
  const count = slug => missing.filter(row => row.folder === slug).length;
  const chips = [['all', 'Tous', missing.length], ...DASH_FOLDERS.map(slug => [slug, DJ_FOLDERS[slug].name, count(slug)])]
    .map(([key, label, n]) => `<button class="dj-chip" aria-pressed="${filter === key}" data-dash-filter="${key}"${key !== 'all' ? ` data-folder-dot="${key}"` : ''}>${key !== 'all' ? `<span class="dj-dot is-${key}" aria-hidden="true"></span>` : ''}${e(label)}<span class="dj-badge ${n ? 'is-missing' : ''}">${n}</span></button>`).join('');
  return `<section class="ops-panel dash-panel ops-missing" id="ops-missing" aria-labelledby="dash-missing-title">
      <div class="dash-panel-head"><div><h2 id="dash-missing-title">Documents manquants</h2>
        <p>Pièces exigibles à l’étape en cours et absentes du dossier. Cliquez pour ouvrir la ligne de checklist.</p></div>
        <span class="dj-state is-missing">${missing.length} pièce${missing.length > 1 ? 's' : ''}</span></div>
      ${missing.length ? `<div class="dj-subnav dash-filters" role="group" aria-label="Filtrer par sous-dossier">${chips}</div>` : ''}
      <div id="dash-missing-body">${dashMissingTable(report)}</div>
    </section>`;
}

function dashCompletionTable(report) {
  const missingBy = {};
  for (const row of report.missing_documents) missingBy[row.launch_id] = (missingBy[row.launch_id] || 0) + 1;
  const rank = {incomplete: 0, partial: 1, unconfigured: 2, complete: 3};
  const launches = [...report.launches].filter(row => row.status !== 'Clôturé')
    .sort((a, b) => (rank[a.completion.state] ?? 9) - (rank[b.completion.state] ?? 9) || (missingBy[b.id] || 0) - (missingBy[a.id] || 0));
  if (!launches.length) return opsEmpty('Aucun dossier actif.');
  return `<div class="dj-table-wrap"><table class="dj-checklist dash-table dash-completion"><caption class="sr-only">Complétude des dossiers</caption>
    <colgroup><col class="dash-c-ref"><col class="dash-c-client"><col class="dash-c-phase"><col class="dash-c-bar"><col class="dash-c-miss"><col class="dash-c-act"></colgroup>
    <thead><tr><th scope="col">Commande / article</th><th scope="col">Client</th><th scope="col">Étape</th><th scope="col">Complétude</th><th scope="col">Manquants</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead>
    <tbody>${launches.map(row => {
      const c = row.completion, n = missingBy[row.id] || 0;
      const tone = c.state === 'complete' ? 'ok' : c.state === 'incomplete' ? 'missing' : 'idle';
      const figure = c.percent !== null && c.percent !== undefined
        ? `<span class="dash-progress"><span class="dj-bar"><span style="width:${c.percent}%"></span></span><small>${c.present_due}/${c.due_count}</small></span>` : '';
      return `<tr class="dj-row dash-row" data-dash-row>
        <td data-label="Commande / article"><strong class="dash-ref">${e(row.order_ref || row.name)}</strong><small>${e(row.article || row.name)}</small></td>
        <td data-label="Client">${e(row.client_name || '—')}</td>
        <td data-label="Étape">${row.profile_name ? e(phaseLabel(row.phase)) : '<span class="dj-muted">Sans checklist</span>'}</td>
        <td data-label="Complétude"><span class="dash-completion-cell"><span class="dj-state is-${tone}">${e(OPS_STATES[c.state] || c.state)}</span>${figure}</span></td>
        <td data-label="Manquants">${n ? `<span class="dash-miss">${n}</span>` : '<span class="dj-muted">0</span>'}</td>
        <td class="dj-action" data-label="Action"><span class="dj-action-group"><button class="secondary tiny" data-ops-target="${opsTargetData({launch_id: row.id})}" aria-label="Ouvrir le dossier ${e(row.order_ref || row.name)}">Ouvrir</button></span></td></tr>`;
    }).join('')}</tbody></table></div>`;
}

function dashActivity(report) {
  const items = report.activity.slice(0, 7);
  if (!items.length) return opsEmpty('Aucune activité visible.');
  return `<ol class="dash-activity">${items.map(row => `<li>
      <time datetime="${e(row.occurred_at)}">${niceDate(row.occurred_at)}</time>
      <div><strong>${e(opsAuditLabel(row.action))}</strong><span>${e(row.document_title || row.launch_name || '—')} · ${e(row.actor)}</span></div></li>`).join('')}</ol>`;
}

function dashConcerns(report) {
  const rows = report.launches.filter(row => row.alerts);
  if (!rows.length) return opsEmpty('Aucune alerte ouverte.');
  return rows.map(row => {
    const parts = [row.inconsistencies.length ? `${row.inconsistencies.length} incohérence${row.inconsistencies.length > 1 ? 's' : ''}` : '',
      row.unacknowledged_changes ? `${row.unacknowledged_changes} modification${row.unacknowledged_changes > 1 ? 's' : ''} à examiner` : ''].filter(Boolean).join(' · ');
    return `<button class="ops-link-row" data-ops-target="${opsTargetData({launch_id: row.id, area: row.inconsistencies.length ? 'quality' : 'workflow'})}">
      <span><strong>${e(row.order_ref || row.name)}</strong><small>${e(row.client_name || '')}${row.client_name ? ' · ' : ''}${e(parts)}</small></span>
      <span class="ops-pill warn">${row.alerts}</span>${icon('arrow')}</button>`;
  }).join('');
}

async function dashboardHome() {
  const report = await api('/api/workspace/dashboard');
  state.view = 'home'; state.operationsDashboard = report; state.priorities = report.priorities;
  const k = report.kpis;
  const today = new Date().toLocaleDateString('fr-FR', {weekday: 'long', day: 'numeric', month: 'long'});
  const unconfigured = k.unconfigured_launches || k.partial_launches
    ? `<p class="dash-note">${k.unconfigured_launches ? `${k.unconfigured_launches} dossier(s) sans checklist` : ''}${k.unconfigured_launches && k.partial_launches ? ' · ' : ''}${k.partial_launches ? `${k.partial_launches} bilan(s) partiel(s) selon vos accès` : ''} : ils ne sont jamais comptés comme complets.</p>` : '';
  const priorities = report.priorities.items.slice(0, 6);
  mount(`<div class="dj dj-dash">
    ${opsHeading('Tableau de bord', `${today.charAt(0).toUpperCase() + today.slice(1)} · ${k.active_launches} dossier${k.active_launches > 1 ? 's' : ''} actif${k.active_launches > 1 ? 's' : ''}`,
      can('launch.create') ? `<button class="primary" id="ops-create">${icon('plus')} Nouveau dossier</button>` : '')}
    <section class="dash-kpis" aria-label="Indicateurs">
      <div class="dash-kpi-group"><p class="dj-label">Dossiers</p><div class="dash-kpi-row">${DASH_KPIS.dossiers.map(m => dashKpi(m, k, false)).join('')}</div></div>
      <div class="dash-kpi-group is-todo"><p class="dj-label">À traiter</p><div class="dash-kpi-row">${DASH_KPIS.todo.map(m => dashKpi(m, k, true)).join('')}</div></div>
    </section>
    ${unconfigured}
    <section class="ops-panel dash-panel" id="ops-priorities" aria-labelledby="dash-priorities-title">
      <div class="dash-panel-head"><div><h2 id="dash-priorities-title">Actions prioritaires</h2><p>Pièces à déposer, validations et vérifications qui vous concernent.</p></div>
        <button class="link" data-view="actions">Tout voir (${report.priorities.total})</button></div>
      <div class="dash-actions">${priorities.map(opsAction).join('') || opsEmpty('Aucune action prioritaire pour vos habilitations.')}</div>
    </section>
    ${dashMissingPanel(report)}
    <section class="ops-panel dash-panel" aria-labelledby="dash-completion-title">
      <div class="dash-panel-head"><div><h2 id="dash-completion-title">Complétude des dossiers</h2><p>Les dossiers incomplets d’abord.</p></div>
        <button class="link" data-view="launches">Commandes et lancements</button></div>
      ${dashCompletionTable(report)}
    </section>
    <div class="dash-grid">
      <section class="ops-panel dash-panel" id="ops-concerns" aria-labelledby="dash-concerns-title">
        <div class="dash-panel-head"><div><h2 id="dash-concerns-title">Alertes importantes</h2><p>Incohérences et changements à examiner.</p></div></div>
        ${dashConcerns(report)}
      </section>
      <section class="ops-panel dash-panel" aria-labelledby="dash-activity-title">
        <div class="dash-panel-head"><div><h2 id="dash-activity-title">Activité récente</h2></div>${can('audit.read') ? '<button class="link" data-view="audit">Historique complet</button>' : ''}</div>
        ${dashActivity(report)}
      </section>
    </div></div>`, 'Tableau de bord');
  dashBind(report);
}

function dashBindRows(root) {
  bindOpsTargets(root);
  // Toute la ligne est cliquable ; le bouton reste la cible clavier.
  root.querySelectorAll('[data-dash-row]').forEach(row => row.addEventListener('click', event => {
    if (event.target.closest('button, a')) return;
    row.querySelector('[data-ops-target]')?.click();
  }));
}

function dashBind(report) {
  dashBindRows(app.querySelector('.dj-dash'));
  app.querySelector('#ops-create')?.addEventListener('click', openNewLaunch);
  const refreshMissing = () => {
    const body = app.querySelector('#dash-missing-body');
    body.innerHTML = dashMissingTable(report);
    dashBindRows(body);
    body.querySelector('#dash-more')?.addEventListener('click', () => { state.dashShowAll = true; refreshMissing(); });
  };
  app.querySelector('#dash-more')?.addEventListener('click', () => { state.dashShowAll = true; refreshMissing(); });
  app.querySelectorAll('[data-dash-filter]').forEach(button => button.addEventListener('click', () => {
    state.dashFilter = button.dataset.dashFilter; state.dashShowAll = false;
    app.querySelectorAll('[data-dash-filter]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    refreshMissing();
  }));
  app.querySelectorAll('[data-ops-kpi]').forEach(button => button.onclick = () => {
    const key = button.dataset.opsKpi;
    const scroll = selector => app.querySelector(selector)?.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    if (key === 'missing_documents') scroll('#ops-missing');
    else if (['alerts', 'inconsistencies', 'unacknowledged_changes'].includes(key)) scroll('#ops-concerns');
    else if (key === 'pending_documents') navigate('actions');
    else { state.opsCompletionFilter = key === 'complete_launches' ? 'complete' : key === 'incomplete_launches' ? 'incomplete' : ''; navigate('launches'); }
  });
}

operationsHome = dashboardHome;
home = dashboardHome;

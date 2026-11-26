'use strict';
/* Recherche du technicien dans « Mes commandes » et « Mes sous-dossiers ».
   Même index que la recherche documentaire (commande, N° client, client, article, atelier, couleur,
   N° OF, références de documents), limité par le serveur aux sous-dossiers que le compte peut
   consulter. Le filtre de sous-dossier fonctionne aussi sans texte. Chaque résultat ouvre
   directement un sous-dossier réellement accessible. */
const TS_FOLDERS = [['', 'Tous mes sous-dossiers'], ['jaune', 'Sous-dossier jaune'], ['rose', 'Sous-dossier rose'],
  ['bleu', 'Sous-dossier bleu'], ['vert', 'Sous-dossier vert']];

function tsPanel(id) {
  return `<form class="ops-filters ts-search" id="${id}" role="search" aria-label="Rechercher dans mes commandes" novalidate>
      <div class="field wide ts-q"><label for="${id}-q">Rechercher</label><input id="${id}-q" name="q" type="search" maxlength="200" autocomplete="off"
        placeholder="N° commande, N° client, client, article, atelier, couleur, N° OF, document…"></div>
      <div class="field"><label for="${id}-folder">Sous-dossier</label><select id="${id}-folder" name="folder">${TS_FOLDERS.map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></div>
      <button class="primary" type="submit">Rechercher</button><button class="secondary" type="button" data-ts-reset>Réinitialiser</button>
    </form>
    <section class="ops-panel ts-results" id="${id}-results" aria-live="polite" hidden></section>`;
}

function tsRows(report, folder) {
  if (!report.items.length) {
    return opsEmpty(folder && !report.query ? `Aucune commande avec un ${TS_FOLDERS.find(([v]) => v === folder)[1].toLowerCase()} attribué.` : 'Aucune commande ni aucun document autorisé ne correspond à cette recherche.');
  }
  return `<p class="ops-muted">${report.total} commande${report.total > 1 ? 's' : ''} trouvée${report.total > 1 ? 's' : ''}</p>
    <table class="ops-table responsive ts-table"><thead><tr><th>Commande</th><th>Client / N° client</th><th>Article / atelier / couleur</th><th>Sous-dossiers</th></tr></thead><tbody>
    ${report.items.map(row => `<tr data-ts-launch="${e(row.launch_id)}">
      <td data-label="Commande"><button type="button" class="link" data-ts-open="${e(row.launch_id)}" data-ts-folder="${e(folder || row.folders[0]?.slug || '')}"><strong>${e(row.order_ref || row.name)}</strong></button><small>${e(row.name)}${row.of_number ? ` · OF ${e(row.of_number)}` : ''}</small></td>
      <td data-label="Client / N° client">${e(row.client_name || '—')}<small>${e(row.client_code || 'N° client non rattaché')}</small></td>
      <td data-label="Article / atelier / couleur">${e([row.article, row.workshop, row.color].filter(Boolean).join(' · ') || '—')}</td>
      <td data-label="Sous-dossiers"><div class="acc-folder-chips">${row.folders.map(f => `<button type="button" class="acc-folder-chip is-${e(f.slug)}" data-ts-open="${e(row.launch_id)}" data-ts-folder="${e(f.slug)}">
        <span class="dj-dot is-${e(f.slug)}" aria-hidden="true"></span><span><strong>${e(TS_FOLDERS.find(([v]) => v === f.slug)[1])}</strong>${f.documents.length ? `<small>${e(f.documents.join(' · '))}</small>` : ''}</span></button>`).join('')}</div></td></tr>`).join('')}
    </tbody></table>`;
}

// Installe la recherche en tête d'un écran ; `defaults` = éléments masqués pendant une recherche.
function tsInstall(id, defaults) {
  const heading = app.querySelector('.ops-heading');
  if (!heading || app.querySelector(`#${id}`)) return;
  heading.insertAdjacentHTML('afterend', tsPanel(id));
  const form = app.querySelector(`#${id}`), results = app.querySelector(`#${id}-results`);
  const view = state.view;
  let seq = 0;
  const show = searching => {
    results.hidden = !searching;
    app.querySelectorAll(defaults).forEach(node => { node.hidden = searching; });
  };
  const draw = async () => {
    const q = form.q.value.trim(), folder = form.folder.value;
    if (!q && !folder) { seq++; show(false); return; }
    const mine = ++seq;
    form.setAttribute('aria-busy', 'true');
    try {
      const report = await api('/api/workspace/my-launches?' + new URLSearchParams({q, folder}));
      if (mine !== seq || state.view !== view || !results.isConnected) return;   // réponse dépassée : ignorée
      results.innerHTML = tsRows(report, folder);
      show(true);
    } finally { if (mine === seq) form.removeAttribute('aria-busy'); }
  };
  form.addEventListener('submit', event => { event.preventDefault(); draw().catch(showErr); });
  form.folder.addEventListener('change', () => draw().catch(showErr));
  form.querySelector('[data-ts-reset]').addEventListener('click', () => { form.reset(); seq++; show(false); form.q.focus(); });
  results.addEventListener('click', event => {
    const button = event.target.closest('[data-ts-open]');
    if (!button) return;
    openLaunch(button.dataset.tsOpen, button.dataset.tsFolder || undefined).catch(showErr);
  });
}

const tsBaseLaunchList = launchList;
launchList = async function(...args) {
  await tsBaseLaunchList(...args);
  if (state.me && !state.me.admin && state.view === 'launches') tsInstall('ts-launches', '.fx-filterbar, #ops-launch-filters, #ops-launch-results');
};
const tsBaseMyFolders = accMyFoldersPage;
accMyFoldersPage = async function(...args) {
  await tsBaseMyFolders(...args);
  if (state.me && !state.me.admin && state.view === 'myfolders') tsInstall('ts-folders', '.acc-my-launch, .acc-empty');
};

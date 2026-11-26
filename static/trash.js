'use strict';
/* Corbeille documentaire (administrateur) : restauration et suppression définitive.
   Le serveur décide : la destruction n'est proposée que si aucune dépendance métier ne subsiste et si
   la conservation documentaire est vérifiée ; sinon le motif du blocage est affiché. */
const TRASH_RETENTION = {free: 'Aucune obligation connue', cleared: 'Vérifiée par l’administration', protected: 'Conservation obligatoire en cours', unknown: 'Obligation de conservation inconnue'};

function trashSize(bytes) { return bytes ? sizeText(bytes) : '—'; }

operationsTrash = async function() {
  state.view = 'trash';
  const report = await api('/api/admin/document-trash');
  state.trashItems = report.items;
  mount(`${opsHeading('Corbeille documentaire', 'Documents et versions retirés logiquement. Restauration ou suppression définitive : réservées à l’administration.')}
    <section class="ops-panel">${report.items.length ? `<table class="ops-table responsive trash-table"><thead><tr><th>Fichier</th><th>Commande / sous-dossier</th><th>Type / version / taille</th><th>Supprimé</th><th>Motif</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>
      ${report.items.map((item, index) => `<tr data-trash-row="${index}">
        <td data-label="Fichier"><strong>${e(item.title)}</strong><small>${e(item.original_name || '—')}</small></td>
        <td data-label="Commande / sous-dossier">${e(item.order_ref || item.launch_name)}<small>${e(djFolderTitle(item.folder))}</small></td>
        <td data-label="Type / version / taille">${e(item.doc_type)}<small>${item.kind === 'document' ? `Document complet · ${item.versions.map(n => `V${n}`).join(', ')}` : `Version V${item.version}`} · ${trashSize(item.size)}</small></td>
        <td data-label="Supprimé">${niceDate(item.deleted_at)}<small>par ${e(item.deleted_by || '—')}</small></td>
        <td data-label="Motif">${e(item.reason || '—')}</td>
        <td data-label="Actions"><span class="dj-action-group"><button class="secondary tiny" data-ops-restore-id="${e(item.kind === 'document' ? item.document_id : item.version_id)}" data-ops-restore-kind="${item.kind}">Restaurer</button>
          <button class="link trash-purge" data-trash-purge="${index}">Supprimer définitivement</button></span></td></tr>`).join('')}
      </tbody></table>` : opsEmpty('La corbeille est vide.')}</section>`, 'Corbeille documentaire');
  app.querySelectorAll('[data-ops-restore-id]').forEach(button => button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true;
    try {
      const kind = button.dataset.opsRestoreKind === 'document' ? 'documents' : 'versions';
      await api(`/api/admin/document-trash/${kind}/${encodeURIComponent(button.dataset.opsRestoreId)}/restore`, {method: 'POST'});
      toast('Document restauré.');
      await operationsTrash();
    } catch (error) { button.disabled = false; showErr(error); }
  });
  app.querySelectorAll('[data-trash-purge]').forEach(button => button.onclick = () => trashPurgeDialog(state.trashItems[Number(button.dataset.trashPurge)]));
};

function trashPurgeDialog(item) {
  const kind = item.kind === 'document' ? 'documents' : 'versions';
  const id = item.kind === 'document' ? item.document_id : item.version_id;
  const verdict = item.purge;
  const retention = verdict.retention;
  const blocked = verdict.blockers.length
    ? `<div class="error" role="alert"><strong>Destruction impossible :</strong> l’élément est encore utilisé (${e(verdict.blockers.join(', '))}). Retirez d’abord ces liens métier ou conservez-le.</div>` : '';
  const needsClearance = !verdict.blockers.length && ['unknown', 'protected'].includes(retention.status);
  const clearance = needsClearance ? `<form id="trash-clearance-form" class="trash-clearance" novalidate>
      <p class="modal-desc"><strong>${e(TRASH_RETENTION[retention.status])}.</strong> ${e(retention.message || '')} La destruction reste refusée jusqu’à une vérification administrative motivée.</p>
      <div class="field"><label for="trash-clearance-reason">Motif de la vérification</label><textarea id="trash-clearance-reason" rows="2" minlength="12" maxlength="1800" placeholder="Ex. dépôt erroné, doublon d’une facture conservée ailleurs"></textarea></div>
      <label class="checkbox-line"><input type="checkbox" id="trash-clearance-confirm"> Je confirme qu’aucune obligation de conservation ne s’applique à cet élément.</label>
      <div class="modal-actions"><button class="secondary" type="submit">Enregistrer la vérification</button></div></form>` : '';
  const destroy = verdict.allowed ? `<form id="trash-purge-form" novalidate>
      <div class="field"><label for="trash-purge-reason">Motif de la suppression définitive</label><textarea id="trash-purge-reason" rows="2" minlength="8" maxlength="1800"></textarea></div>
      <div class="field"><label for="trash-purge-confirm">Saisissez <strong>SUPPRIMER</strong> pour confirmer</label><input id="trash-purge-confirm" autocomplete="off" maxlength="40"></div>
      <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary danger" type="submit" disabled>Supprimer définitivement</button></div></form>`
    : `<div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Fermer</button></div>`;
  modal('Supprimer définitivement', `<p class="modal-desc">${item.kind === 'document' ? `Le document « ${e(item.title)} » et ses versions ${e(item.versions.map(n => `V${n}`).join(', '))}` : `La version V${item.version} de « ${e(item.title)} »`}
      (${e(item.order_ref || item.launch_name)} · ${e(djFolderTitle(item.folder))} · ${trashSize(item.size)}) seront détruits : fichier, aperçus, lecture OCR, index de recherche et commentaires.</p>
    <p class="modal-desc"><strong>Le fichier ne pourra plus être restauré depuis l’application.</strong> Une trace minimale reste dans l’historique. Les sauvegardes déjà réalisées ne sont pas modifiées : elles suivent leur propre durée de conservation.</p>
    <p class="modal-desc">Conservation : ${e(TRASH_RETENTION[retention.status])}${retention.reason ? ` · ${e(retention.reason)}` : ''}</p>
    ${blocked}${clearance}${destroy}`);
  overlay.querySelector('#cancel-modal')?.addEventListener('click', closeModal);
  overlay.querySelector('#trash-clearance-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const reason = overlay.querySelector('#trash-clearance-reason').value.trim();
    if (reason.length < 12) { toast('Indiquez un motif d’au moins 12 caractères.'); return; }
    if (!overlay.querySelector('#trash-clearance-confirm').checked) { toast('Cochez la confirmation de vérification.'); return; }
    const submit = event.target.querySelector('[type=submit]');
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      item.purge = await api(`/api/admin/document-trash/${kind}/${encodeURIComponent(id)}/retention-clearance`, {method: 'POST', body: JSON.stringify({reason})});
      toast('Vérification de conservation enregistrée.');
      trashPurgeDialog(item);
    } catch (error) { submit.disabled = false; showErr(error); }
  });
  const form = overlay.querySelector('#trash-purge-form');
  if (!form) return;
  const submit = form.querySelector('[type=submit]');
  const ready = () => { submit.disabled = form.querySelector('#trash-purge-confirm').value.trim().toUpperCase() !== 'SUPPRIMER' || form.querySelector('#trash-purge-reason').value.trim().length < 8; };
  form.addEventListener('input', ready);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    ready();
    if (submit.disabled) { toast('Indiquez un motif (8 caractères minimum) et saisissez SUPPRIMER.'); return; }
    submit.disabled = true;
    submit.textContent = 'Suppression…';
    try {
      await api(`/api/admin/document-trash/${kind}/${encodeURIComponent(id)}/purge`, {method: 'POST',
        body: JSON.stringify({confirmation: form.querySelector('#trash-purge-confirm').value, reason: form.querySelector('#trash-purge-reason').value})});
      closeModal();
      toast('Suppression définitive effectuée.');
      await operationsTrash();
    } catch (error) { submit.textContent = 'Supprimer définitivement'; ready(); showErr(error); }
  });
}

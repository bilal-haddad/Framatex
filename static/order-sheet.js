'use strict';
/* Fiche commande complète (modèle métier FRAMATEX) : création, panneau en tête du Dossier Jaune,
   « Modifier la fiche ». Seul le nom est obligatoire ; une valeur vide reste « Non renseigné ». */
const SHEET_GROUPS = [
  ['Commande', [['name', 'Nom de la commande / projet', 'text', 180, true], ['description', 'Description', 'textarea', 4000]]],
  ['Client', [['client_name', 'Client', 'text', 150], ['client_account_id', 'N° client', 'client'], ['client_order_ref', 'Référence de commande Client', 'text', 100]]],
  ['Production', [['workshop', 'Atelier', 'text', 150], ['article', 'Article', 'text', 180], ['order_ref', 'N° commande', 'text', 100],
    ['color', 'Couleur', 'text', 80], ['of_number', 'N° OF', 'text', 60], ['orli_ref', 'Référence ORLI', 'text', 100]]],
  ['Quantités', [['quantity', 'Quantité commandée', 'number'], ['quantity_launched', 'Quantité lancée', 'number'], ['quantity_delivered', 'Quantité livrée', 'number']]],
  ['Facturation et livraison', [['invoice_ref', 'Référence / N° facture', 'text', 100], ['desired_date', 'Date de livraison souhaitée', 'date']]],
];
const SHEET_FIELDS = SHEET_GROUPS.flatMap(([, fields]) => fields);
// Création : mêmes identifiants que l'ancien formulaire (#new-launch-form, #l-name, #l-client, #l-order, #l-orli).
const SHEET_LEGACY_IDS = {name: 'l-name', client_name: 'l-client', order_ref: 'l-order', orli_ref: 'l-orli'};
const sheetId = (key, legacy) => (legacy && SHEET_LEGACY_IDS[key]) || `sheet-${key}`;

async function sheetClients() {
  if (!state.me?.admin) return null;
  try { return await api('/api/admin/clients'); } catch { return null; }
}

function sheetForm(values = {}, clients = null, legacy = false) {
  const input = ([key, label, type, max, required]) => {
    const value = values[key] ?? '';
    const id = sheetId(key, legacy);
    let control;
    if (type === 'textarea') control = `<textarea id="${id}" maxlength="${max}" rows="3">${e(value)}</textarea>`;
    else if (type === 'client') {
      const current = values.client_account;
      control = clients
        ? `<select id="${id}"><option value="">Non rattaché</option>${clients.map(c => `<option value="${e(c.id)}" ${c.id === value ? 'selected' : ''}>${e(c.client_code)} · ${e(c.raison_sociale)}</option>`).join('')}</select>`
        : `<input id="${id}" type="text" value="${e(current ? `${current.client_code} · ${current.raison_sociale}` : 'Non rattaché')}" disabled>`;
    } else if (type === 'number') control = `<input id="${id}" type="number" min="${key === 'quantity' ? 1 : 0}" step="1" inputmode="numeric" value="${e(value)}" placeholder="Non renseigné">`;
    else if (type === 'date') control = `<input id="${id}" type="date" value="${e(value)}">`;
    else control = `<input id="${id}" type="text" maxlength="${max}" value="${e(value)}" ${required ? 'required' : 'placeholder="Non renseigné"'} autocomplete="off">`;
    return `<div class="field ${type === 'textarea' ? 'sheet-wide' : ''}"><label for="${id}">${e(label)}${required ? ' *' : ''}</label>${control}</div>`;
  };
  return SHEET_GROUPS.map(([title, fields]) => `<fieldset class="sheet-group"><legend>${e(title)}</legend><div class="sheet-grid">${fields.map(input).join('')}</div></fieldset>`).join('');
}

function sheetRead(root, editable, legacy = false) {
  const out = {};
  for (const [key, , type] of SHEET_FIELDS) {
    const el = root.querySelector(`#${sheetId(key, legacy)}`);
    if (!el || el.disabled || (type === 'client' && !editable)) continue;
    const raw = el.value.trim();
    out[key] = type === 'number' ? (raw === '' ? null : Number(raw)) : (raw || null);
  }
  return out;
}

// Rendu synchrone (les modules qui complètent ce formulaire le trouvent aussitôt) ; la liste des
// comptes Client est chargée ensuite pour le rattachement explicite du N° client.
openNewLaunch = function() {
  let clients = null;
  modal('Nouveau Dossier Jaune', `<form id="new-launch-form" novalidate><p class="modal-desc">Seul le nom est obligatoire : les autres informations peuvent être complétées plus tard. Les quatre sous-dossiers sont créés automatiquement.</p>
    <div id="sheet-error" role="alert"></div>${sheetForm({}, null, true)}
    <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="submit">${icon('plus')} Créer le dossier</button></div></form>`, true);
  overlay.querySelector('.modal')?.classList.add('sheet-modal');
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  sheetClients().then(list => {
    const slot = overlay.querySelector('#sheet-client_account_id');
    if (!list || !slot) return;
    clients = list;
    slot.outerHTML = `<select id="sheet-client_account_id"><option value="">Non rattaché</option>${list.map(c => `<option value="${e(c.id)}">${e(c.client_code)} · ${e(c.raison_sociale)}</option>`).join('')}</select>`;
  });
  // Clé d'idempotence propre à ce formulaire : un double envoi ne crée qu'une commande.
  overlay.querySelector('#new-launch-form').dataset.idempotencyKey = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  overlay.querySelector('#new-launch-form').onsubmit = async event => {
    event.preventDefault();
    const button = event.target.querySelector('[type=submit]');
    const values = sheetCreateValues();
    if (!values.name || values.name.length < 2) { overlay.querySelector('#sheet-error').innerHTML = '<div class="error">Indiquez le nom de la commande.</div>'; return; }
    button.disabled = true;
    try {
      const created = await api('/api/order-sheets', {method: 'POST', body: JSON.stringify(values), headers: {'Idempotency-Key': event.target.dataset.idempotencyKey}});
      closeModal(); toast('Dossier Jaune créé avec sa fiche commande.');
      await openLaunch(created.id, 'jaune');
    } catch (error) { button.disabled = false; overlay.querySelector('#sheet-error').innerHTML = `<div class="error">${e(error.message)}</div>`; }
  };
};
// Valeurs renseignées du formulaire de création (aussi utilisées par les modules qui le complètent).
function sheetCreateValues() {
  const editable = Boolean(overlay.querySelector('select#sheet-client_account_id'));
  return Object.fromEntries(Object.entries(sheetRead(overlay, editable, true)).filter(([, value]) => value !== null));
}

async function sheetEdit(launchId) {
  const [sheet, clients] = await Promise.all([api(`/api/launches/${launchId}/sheet`), sheetClients()]);
  modal('Modifier la fiche commande', `<form id="sheet-edit-form" novalidate><p class="modal-desc">Chaque modification est enregistrée dans l’historique avec l’ancienne et la nouvelle valeur.</p>
    <div id="sheet-error" role="alert"></div>${sheetForm(sheet.values, clients)}
    <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="submit">${icon('check')} Enregistrer la fiche</button></div></form>`, true);
  overlay.querySelector('.modal')?.classList.add('sheet-modal');
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  overlay.querySelector('#sheet-edit-form').onsubmit = async event => {
    event.preventDefault();
    const button = event.target.querySelector('[type=submit]');
    const values = sheetRead(overlay, Boolean(clients));
    const changed = Object.fromEntries(Object.entries(values).filter(([key, value]) => (sheet.values[key] ?? null) !== value));
    if (!changed.name && 'name' in changed) { overlay.querySelector('#sheet-error').innerHTML = '<div class="error">Le nom de la commande est obligatoire.</div>'; return; }
    if (!Object.keys(changed).length) { closeModal(); toast('Aucune modification.'); return; }
    button.disabled = true;
    try {
      const result = await api(`/api/launches/${launchId}/sheet`, {method: 'PATCH', body: JSON.stringify(changed)});
      closeModal(); toast(`Fiche enregistrée (${Object.keys(result.changes).length} modification${Object.keys(result.changes).length > 1 ? 's' : ''}).`);
      await openLaunch(launchId, state.folder);
    } catch (error) { button.disabled = false; overlay.querySelector('#sheet-error').innerHTML = `<div class="error">${e(error.message)}</div>`; }
  };
}

// Panneau « Fiche commande » en tête du Dossier Jaune (lecture selon les habilitations).
async function sheetPanel() {
  const anchor = app.querySelector('.dj-summary');
  const launchId = state.detail?.id;
  if (!anchor || !launchId || app.querySelector(`.fx-sheet[data-launch="${launchId}"]`)) return;
  const marker = document.createElement('section');
  marker.className = 'fx-sheet'; marker.dataset.launch = launchId; marker.setAttribute('aria-labelledby', 'fx-sheet-title');
  anchor.after(marker);
  let sheet;
  try {
    sheet = await api(`/api/launches/${launchId}/sheet`);
  } catch { marker.remove(); return; }       // module secondaire : n'empêche jamais l'ouverture de la commande
  const show = ([key, label, type]) => {
    let value = sheet.values[key];
    if (type === 'client') value = sheet.values.client_account ? `${sheet.values.client_account.client_code} · ${sheet.values.client_account.raison_sociale}` : null;
    if (type === 'date' && value) value = new Date(value + 'T00:00:00').toLocaleDateString('fr-FR', {day: '2-digit', month: 'long', year: 'numeric'});
    if (type === 'number' && value !== null && value !== undefined) value = Number(value).toLocaleString('fr-FR');
    const empty = value === null || value === undefined || value === '';
    return `<div class="${key === 'description' ? 'is-wide' : ''}"><dt>${e(label)}</dt><dd class="${empty ? 'is-empty' : ''}">${empty ? 'Non renseigné' : e(value)}</dd></div>`;
  };
  // Vue d'ensemble : fiche dépliée ; vue d'un sous-dossier : repliée pour laisser la place aux documents.
  const open = !app.querySelector('.dj-folder-switch');
  marker.innerHTML = `<details ${open ? 'open' : ''}><summary><h2 id="fx-sheet-title">Fiche commande</h2>${sheet.can_edit ? `<button type="button" class="primary tiny" id="fx-sheet-edit">${icon('edit') || ''}Modifier la fiche</button>` : ''}</summary>
    <dl class="fx-sheet-grid">${SHEET_FIELDS.map(show).join('')}</dl></details>`;
  marker.querySelector('#fx-sheet-edit')?.addEventListener('click', event => event.preventDefault(), {capture: true});
  marker.querySelector('#fx-sheet-edit')?.addEventListener('click', () => sheetEdit(launchId).catch(showErr));
}
let sheetPending = false;
new MutationObserver(() => {
  if (sheetPending || !app.querySelector('.dj-summary')) return;
  sheetPending = true;
  requestAnimationFrame(() => { sheetPending = false; sheetPanel(); });
}).observe(app, {childList: true, subtree: true});

'use strict';
// Collaborateurs et habilitations : administration du chef, matrice d'affectation par
// commande, changement obligatoire du mot de passe temporaire, « Mon compte ».
// Toutes les règles sont vérifiées par le serveur ; cet écran ne fait que les présenter.

const ACC_FOLDERS = [['jaune', 'Jaune', 'Sous-dossier jaune'], ['rose', 'Rose', 'Sous-dossier rose'], ['bleu', 'Bleu', 'Sous-dossier bleu'], ['vert', 'Vert', 'Sous-dossier vert']];
const accState = {catalog: null, tab: 'people', filters: {launch: '', user: '', folder: ''}};

// ------------------------------------------------------------------ permissions côté écran
// Les collaborateurs affectés voient leurs menus d'après l'union de leurs affectations ;
// chaque action reste contrôlée par le serveur, commande par commande.
const accOriginalCan = can;
can = function(action, folder = null) {
  if (state.me?.access_mode === 'assignments' && !state.me.admin) {
    if (['launch.create', 'launch.update', 'audit.read'].includes(action)) return accOriginalCan(action, folder);
    if (action === 'launch.read') return true;
    const sets = state.me.assigned_actions || {};
    return folder ? (sets[folder] || []).includes(action) : Object.values(sets).some(list => list.includes(action));
  }
  return accOriginalCan(action, folder);
};

async function accCatalog() {
  if (!accState.catalog) accState.catalog = await api('/api/admin/access/catalog');
  return accState.catalog;
}

function accActionsSummary(actions) {
  if (!actions || !actions.length) return '';
  const keys = new Set(actions);
  if (keys.has('document.review')) return 'Validation';
  if (keys.has('document.write') || keys.has('document.version')) return 'Dépôt';
  if (keys.has('document.download')) return 'Lecture + téléch.';
  return 'Lecture';
}

const ACC_LEVELS = [
  ['none', 'Aucun accès'], ['lecture', 'Lecture seule'],
  ['depot', 'Dépôt sans validation'], ['responsable', 'Responsable'], ['custom', 'Personnalisé…'],
];

function accSameActions(left, right) {
  return left.length === right.length && left.every(item => right.includes(item));
}

function accLevelFor(actions) {
  if (!actions?.length) return 'none';
  for (const key of ['lecture', 'depot', 'responsable']) {
    const preset = accState.catalog.presets.find(item => item.key === key);
    if (preset && accSameActions(actions, preset.actions)) return key;
  }
  return 'custom';
}

function accLevelLabel(actions) {
  const level = accLevelFor(actions || []);
  return ACC_LEVELS.find(item => item[0] === level)?.[1] || 'Personnalisé';
}

// ------------------------------------------------------------------ navigation et menus
const accOriginalMount = mount;
mount = function(html, label) {
  accOriginalMount(html, label);
  const nav = app.querySelector('.sidebar-nav');
  if (!nav || !state.me) return;
  if (!state.me.admin) {
    const labels = {home: 'Mon tableau de bord', launches: 'Mes commandes', notifications: 'Mes notifications'};
    for (const [view, text] of Object.entries(labels)) { const span = app.querySelector(`[data-view="${view}"] span`); if (span) span.textContent = text; }
    nav.insertAdjacentHTML('beforeend', `<button class="nav-btn ${state.view === 'myfolders' ? 'active' : ''}" data-acc-view="myfolders">${icon('folder')}<span>Mes sous-dossiers</span></button>`);
  }
  const tools = app.querySelectorAll('.sidebar-nav')[1] || nav;
  if (state.me.admin) tools.insertAdjacentHTML('afterbegin', `<button class="nav-btn ${state.view === 'access' ? 'active' : ''}" data-acc-view="access">${icon('users')}<span>Collaborateurs et habilitations</span></button>`);
  tools.insertAdjacentHTML('beforeend', `<button class="nav-btn ${state.view === 'account' ? 'active' : ''}" data-acc-view="account">${icon('users')}<span>Mon compte</span></button>`);
  app.querySelectorAll('[data-acc-view]').forEach(button => button.onclick = () => navigate(button.dataset.accView));
};

const accOriginalNavigate = navigate;
navigate = async function(view) {
  try {
    if (state.me?.must_change_password) return accPasswordScreen();
    if (view === 'access' && state.me?.admin) return await accAdminPage();
    if (view === 'account') return await accAccountPage();
    if (view === 'myfolders') return await accMyFoldersPage();
    if (view === 'home' && state.me && !state.me.admin && state.me.access_mode === 'assignments' && !state.me.assigned_launches) {
      return accEmptyHome();
    }
    return await accOriginalNavigate(view);
  } catch (error) { showErr(error); }
};

// ------------------------------------------------------------------ mot de passe temporaire
function accPasswordScreen() {
  state.view = 'password';
  app.innerHTML = `<div class="login-page"><section class="login-art"><a class="brand" href="/" aria-label="FRAMATEX — retour au site"><img class="brand-mark" src="/assets/landing/logo-framatex.jpg" alt="FRAMATEX" width="500" height="500"><span class="brand-text"><span class="brand-label">Espace FRAMATEX</span><span class="brand-sub">Accès collaborateurs</span></span></a>
    <div class="login-hero"><span class="eyebrow">PREMIÈRE CONNEXION</span><h1>Choisissez<br>votre mot de passe.</h1><p>Le mot de passe transmis par votre responsable est temporaire. Il doit être remplacé avant d'accéder aux commandes.</p></div></section>
    <section class="login-form-wrap"><form id="acc-password-form" class="login-form" novalidate><div class="page-kicker">SÉCURITÉ DU COMPTE</div><h2 style="margin-top:16px">Nouveau mot de passe</h2>
      <p>${e(state.me.name)} · ${e(state.me.email)}</p><div id="acc-password-error" role="alert"></div>
      <div class="field"><label for="acc-current">Mot de passe temporaire</label><input id="acc-current" type="password" autocomplete="current-password" required></div>
      <div class="field"><label for="acc-new">Nouveau mot de passe <span class="muted">(12 caractères minimum)</span></label><input id="acc-new" type="password" autocomplete="new-password" minlength="12" required></div>
      <div class="field"><label for="acc-confirm">Confirmer le nouveau mot de passe</label><input id="acc-confirm" type="password" autocomplete="new-password" minlength="12" required></div>
      <button class="primary" type="submit">Enregistrer et continuer ${icon('arrow')}</button>
      <button class="link" type="button" id="acc-password-logout">Se déconnecter</button></form></section></div>`;
  app.querySelector('#acc-password-logout').onclick = async () => { fxAbortPending(); try { await api('/api/auth/logout', {method: 'POST'}); } catch {} state.me = null; renderLogin(); };
  app.querySelector('#acc-password-form').addEventListener('submit', async event => {
    event.preventDefault();
    const error = app.querySelector('#acc-password-error');
    const current = app.querySelector('#acc-current').value, next = app.querySelector('#acc-new').value;
    if (next.length < 12) { error.innerHTML = '<div class="error">Le nouveau mot de passe doit contenir au moins 12 caractères.</div>'; return; }
    if (next !== app.querySelector('#acc-confirm').value) { error.innerHTML = '<div class="error">Les deux saisies ne correspondent pas.</div>'; return; }
    const button = event.target.querySelector('[type=submit]'); button.disabled = true;
    try {
      await api('/api/account/password', {method: 'POST', body: JSON.stringify({current_password: current, new_password: next})});
      state.me = await api('/api/auth/me');
      toast('Mot de passe enregistré.');
      await navigate('home');
    } catch (err) { error.innerHTML = `<div class="error">${e(err.message)}</div>`; button.disabled = false; }
  });
}

// ------------------------------------------------------------------ technicien : état vide, mes sous-dossiers
function accEmptyHome() {
  state.view = 'home';
  mount(`${opsHeading('Mon tableau de bord', 'Vos commandes, vos sous-dossiers et vos actions apparaîtront ici dès qu’un responsable vous en attribue.')}
    <section class="ops-panel acc-empty" aria-live="polite"><div class="acc-empty-icon">${icon('folder')}</div>
      <h2>Aucune commande ne vous est attribuée pour le moment</h2>
      <p>Votre compte est actif. Le chef FRAMATEX choisit, commande par commande, les sous-dossiers sur lesquels vous travaillez et les actions autorisées.</p>
      <div class="acc-empty-actions"><button class="secondary" data-acc-go="account">Mon compte</button><button class="secondary" data-acc-go="assistant">Assistant FRAMATEX</button></div></section>`, 'Mon tableau de bord');
  app.querySelectorAll('[data-acc-go]').forEach(button => button.onclick = () => navigate(button.dataset.accGo));
}

async function accMyFoldersPage() {
  const account = await api('/api/account');
  state.view = 'myfolders';
  const rows = account.assignments.map(item => `<article class="ops-panel acc-my-launch"><div class="acc-my-head"><div><strong>${e(item.launch.order_ref || item.launch.name)}</strong><small>${e(item.launch.name)} · ${e(item.launch.client_name || '—')}</small></div>
      <button class="secondary tiny" data-acc-open="${e(item.launch.id)}">Ouvrir la commande</button></div>
      <div class="acc-folder-chips">${ACC_FOLDERS.filter(([slug]) => item.folders[slug]).map(([slug, color, name]) => `<button class="acc-folder-chip is-${slug}" data-acc-open="${e(item.launch.id)}" data-acc-folder="${slug}">
        <span class="dj-dot is-${slug}" aria-hidden="true"></span><span><strong>${name}</strong><small>${e(item.folders[slug].map(a => account.action_labels[a] || a).join(' · '))}</small></span></button>`).join('')}</div></article>`).join('');
  mount(`${opsHeading('Mes sous-dossiers', 'Les sous-dossiers qui vous sont attribués, commande par commande, avec les actions autorisées.')}
    ${rows || `<section class="ops-panel acc-empty"><h2>Aucun sous-dossier attribué</h2><p>Votre responsable vous affectera aux commandes concernées.</p></section>`}`, 'Mes sous-dossiers');
  app.querySelectorAll('[data-acc-open]').forEach(button => button.onclick = () => openLaunch(button.dataset.accOpen, button.dataset.accFolder || undefined));
}

// ------------------------------------------------------------------ Mon compte
async function accAccountPage() {
  const account = await api('/api/account');
  state.view = 'account';
  const prefs = Object.entries(account.preference_labels).map(([key, label]) => `<label class="checkbox-line"><input type="checkbox" data-acc-pref="${key}" ${account.preferences[key] ? 'checked' : ''}> ${e(label)}</label>`).join('');
  const assigned = account.admin ? '<p class="ops-muted">Compte chef : accès complet à toutes les commandes et à l’administration.</p>'
    : account.assignments.length ? `<ul class="acc-list">${account.assignments.map(item => `<li><strong>${e(item.launch.order_ref || item.launch.name)}</strong> · ${ACC_FOLDERS.filter(([s]) => item.folders[s]).map(([, , n]) => n).join(', ')}</li>`).join('')}</ul>`
    : '<p class="ops-muted">Aucune commande attribuée pour le moment.</p>';
  mount(`${opsHeading('Mon compte', 'Identité, mot de passe, préférences de notification et habilitations.')}
    <div class="acc-grid">
      <section class="ops-panel"><h2>Identité</h2><dl class="acc-facts"><div><dt>Nom</dt><dd>${e(account.name)}</dd></div><div><dt>Email professionnel</dt><dd>${e(account.email)}</dd></div>
        <div><dt>Fonction</dt><dd>${e(account.job_title || (account.admin ? 'Chef — Administrateur' : '—'))}</dd></div></dl>
        <h3>Mes habilitations</h3>${assigned}</section>
      <section class="ops-panel"><h2>Changer de mot de passe</h2><form id="acc-change-form" novalidate>
        <div class="field"><label for="acc-old">Mot de passe actuel</label><input id="acc-old" type="password" autocomplete="current-password" required></div>
        <div class="field"><label for="acc-new2">Nouveau mot de passe (12 caractères minimum)</label><input id="acc-new2" type="password" autocomplete="new-password" minlength="12" required></div>
        <button class="primary" type="submit">Enregistrer</button><p class="ops-muted">Vos autres sessions ouvertes seront fermées.</p></form></section>
      <section class="ops-panel"><h2>Préférences de notification</h2><div class="acc-prefs">${prefs}</div>
        <p class="ops-muted">Les notifications email seront activées lors de l’intégration de la messagerie ; aucun email n’est envoyé aujourd’hui.</p>
        <button class="secondary" id="acc-save-prefs">Enregistrer les préférences</button></section>
    </div>`, 'Mon compte');
  app.querySelector('#acc-change-form').addEventListener('submit', async event => {
    event.preventDefault();
    const next = app.querySelector('#acc-new2').value;
    if (next.length < 12) { toast('Le nouveau mot de passe doit contenir au moins 12 caractères.'); return; }
    try { await api('/api/account/password', {method: 'POST', body: JSON.stringify({current_password: app.querySelector('#acc-old').value, new_password: next})}); toast('Mot de passe modifié.'); event.target.reset(); }
    catch (error) { showErr(error); }
  });
  app.querySelector('#acc-save-prefs').onclick = async () => {
    const preferences = Object.fromEntries([...app.querySelectorAll('[data-acc-pref]')].map(box => [box.dataset.accPref, box.checked]));
    try { await api('/api/account/preferences', {method: 'PUT', body: JSON.stringify({preferences})}); toast('Préférences enregistrées.'); } catch (error) { showErr(error); }
  };
}

// ------------------------------------------------------------------ administration : collaborateurs
async function accAdminPage() {
  state.view = 'access';
  await accCatalog();
  const tabs = [['people', 'Collaborateurs'], ['overview', 'Vue globale des affectations'], ['legacy', 'Droits hérités à vérifier']];
  mount(`${opsHeading('Collaborateurs et habilitations', 'Comptes individuels, affectations par commande et par sous-dossier, actions autorisées.',
      '<button class="primary" id="acc-new">' + icon('plus') + ' Nouveau collaborateur</button>')}
    <div class="acc-tabs" role="tablist">${tabs.map(([key, label]) => `<button role="tab" class="acc-tab" aria-selected="${accState.tab === key}" data-acc-tab="${key}">${label}</button>`).join('')}</div>
    <div id="acc-body">${'<p class="ops-muted">Chargement…</p>'}</div>`, 'Collaborateurs et habilitations');
  app.querySelector('#acc-new').onclick = accCreateModal;
  app.querySelectorAll('[data-acc-tab]').forEach(button => button.onclick = () => { accState.tab = button.dataset.accTab; accAdminPage(); });
  const body = app.querySelector('#acc-body');
  if (accState.tab === 'overview') return accOverview(body);
  if (accState.tab === 'legacy') return accLegacy(body);
  const people = await api('/api/admin/collaborators');
  body.innerHTML = `<div class="ops-table-wrap"><table class="ops-table responsive acc-table"><thead><tr><th>Collaborateur</th><th>Fonction</th><th>État</th><th>Commandes</th><th>Dernière activité</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>
    ${people.map(p => `<tr data-acc-user="${e(p.id)}">
      <td data-label="Collaborateur"><strong>${e(p.name)}</strong><small>${e(p.email)}</small></td>
      <td data-label="Fonction">${p.admin ? '<span class="ops-pill ok">Chef — Administrateur</span>' : e(p.job_title || '—')}</td>
      <td data-label="État"><span class="ops-pill ${p.active ? 'ok' : 'warn'}">${p.active ? 'Actif' : 'Désactivé'}</span>${p.must_change_password ? '<small>Mot de passe temporaire</small>' : ''}${p.legacy_pending ? `<small>${p.legacy_pending} droit(s) hérité(s) à vérifier</small>` : ''}</td>
      <td data-label="Commandes">${p.admin ? 'Toutes' : `${p.launches_count} commande${p.launches_count > 1 ? 's' : ''}<small>${p.folders_count} sous-dossier${p.folders_count > 1 ? 's' : ''}</small>`}</td>
      <td data-label="Dernière activité">${p.last_activity ? niceDate(p.last_activity) : '—'}</td>
      <td class="acc-row-actions" data-label="Actions">${p.admin ? '' : `<button class="secondary tiny" data-acc-rights="${e(p.id)}">Habilitations</button>`}
        <button class="secondary tiny" data-acc-edit="${e(p.id)}">Modifier</button>
        ${p.admin && p.id === state.me.id ? '' : `<button class="link" data-acc-toggle="${e(p.id)}" data-active="${p.active}">${p.active ? 'Désactiver' : 'Activer'}</button>`}
        ${p.id === state.me.id ? '' : `<button class="link" data-acc-reset="${e(p.id)}">Réinitialiser le mot de passe</button>`}
        <button class="link" data-acc-history="${e(p.id)}">Historique</button></td></tr>`).join('')}</tbody></table></div>`;
  const find = id => people.find(p => p.id === id);
  body.querySelectorAll('[data-acc-rights]').forEach(b => b.onclick = () => accCollaboratorRights(b.dataset.accRights));
  body.querySelectorAll('[data-acc-edit]').forEach(b => b.onclick = () => accEditModal(find(b.dataset.accEdit)));
  body.querySelectorAll('[data-acc-history]').forEach(b => b.onclick = () => accHistory(find(b.dataset.accHistory)));
  body.querySelectorAll('[data-acc-toggle]').forEach(b => b.onclick = () => accConfirm(
    b.dataset.active === 'true' ? 'Désactiver ce compte ?' : 'Réactiver ce compte ?',
    b.dataset.active === 'true' ? 'L’accès est coupé immédiatement, y compris pour une session ouverte. Les affectations sont conservées.' : 'Le collaborateur retrouve ses affectations.',
    async () => { await api(`/api/admin/collaborators/${b.dataset.accToggle}`, {method: 'PATCH', body: JSON.stringify({active: b.dataset.active !== 'true'})}); accAdminPage(); }));
  body.querySelectorAll('[data-acc-reset]').forEach(b => b.onclick = () => accConfirm('Réinitialiser le mot de passe ?',
    'Un mot de passe temporaire est généré ; les sessions ouvertes sont fermées et le collaborateur devra le remplacer à sa prochaine connexion.',
    async () => { const result = await api(`/api/admin/collaborators/${b.dataset.accReset}/reset-password`, {method: 'POST'}); accShowSecret(result); }));
}

function accConfirm(title, text, action) {
  modal(title, `<p class="modal-desc">${e(text)}</p><div class="modal-actions"><button class="secondary" id="cancel-modal">Annuler</button><button class="primary" id="acc-confirm-go">Confirmer</button></div>`);
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  overlay.querySelector('#acc-confirm-go').onclick = async () => { try { await action(); if (overlay.querySelector('#acc-confirm-go')) closeModal(); } catch (error) { showErr(error); } };
}

function accShowSecret(result) {
  modal('Mot de passe temporaire', `<p class="modal-desc">Transmettez ce mot de passe à <strong>${e(result.collaborator.name)}</strong> par un canal sûr. Il ne sera <strong>plus jamais affiché</strong> et devra être remplacé à la première connexion.</p>
    <div class="acc-secret"><code id="acc-secret-value">${e(result.temporary_password)}</code><button class="secondary tiny" id="acc-copy">Copier</button></div>
    <p class="ops-muted">Identifiant de connexion : ${e(result.collaborator.email)} · page de connexion de l’Espace FRAMATEX.</p>
    <div class="modal-actions"><button class="primary" id="acc-secret-done">J’ai transmis le mot de passe</button></div>`);
  overlay.querySelector('#acc-copy').onclick = async () => { try { await navigator.clipboard.writeText(result.temporary_password); toast('Copié.'); } catch { toast('Sélectionnez le mot de passe pour le copier.'); } };
  overlay.querySelector('#acc-secret-done').onclick = () => { closeModal(); accAdminPage(); };
}

function accCreateModal() {
  modal('Nouveau collaborateur', `<form id="acc-create-form" novalidate><p class="modal-desc">Le compte est créé <strong>sans aucune commande</strong>. Vous l’affecterez ensuite, commande par commande.</p>
    <div class="two-fields"><div class="field"><label for="acc-name">Nom</label><input id="acc-name" required maxlength="120"></div>
    <div class="field"><label for="acc-email">Email professionnel</label><input id="acc-email" type="email" required maxlength="254" placeholder="prenom.nom@framatex.com"></div></div>
    <div class="field"><label for="acc-job">Fonction</label><input id="acc-job" maxlength="120" placeholder="Technicien, assistante logistique…"></div>
    <label class="checkbox-line"><input type="checkbox" id="acc-generate" checked> Générer un mot de passe temporaire sécurisé</label>
    <div class="field" id="acc-pw-field" hidden><label for="acc-pw">Mot de passe temporaire (12 caractères minimum)</label><input id="acc-pw" type="password" autocomplete="new-password" minlength="12"></div>
    <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="submit">Créer le compte</button></div></form>`);
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  overlay.querySelector('#acc-generate').onchange = event => { overlay.querySelector('#acc-pw-field').hidden = event.target.checked; };
  overlay.querySelector('#acc-create-form').onsubmit = async event => {
    event.preventDefault();
    const payload = {name: val('acc-name'), email: val('acc-email'), job_title: val('acc-job')};
    if (!overlay.querySelector('#acc-generate').checked) payload.password = overlay.querySelector('#acc-pw').value;
    if (payload.name.length < 2 || !payload.email.includes('@')) { toast('Indiquez un nom et une adresse email valides.'); return; }
    try { accShowSecret(await api('/api/admin/collaborators', {method: 'POST', body: JSON.stringify(payload)})); } catch (error) { showErr(error); }
  };
}

function accEditModal(person) {
  modal('Modifier le collaborateur', `<form id="acc-edit-form" novalidate>
    <div class="two-fields"><div class="field"><label for="acc-ename">Nom</label><input id="acc-ename" value="${e(person.name)}" maxlength="120"></div>
    <div class="field"><label for="acc-eemail">Email professionnel</label><input id="acc-eemail" type="email" value="${e(person.email)}" maxlength="254"></div></div>
    <div class="field"><label for="acc-ejob">Fonction</label><input id="acc-ejob" value="${e(person.job_title || '')}" maxlength="120"></div>
    <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="submit">Enregistrer</button></div></form>`);
  overlay.querySelector('#cancel-modal').onclick = closeModal;
  overlay.querySelector('#acc-edit-form').onsubmit = async event => {
    event.preventDefault();
    try { await api(`/api/admin/collaborators/${person.id}`, {method: 'PATCH', body: JSON.stringify({name: val('acc-ename'), email: val('acc-eemail'), job_title: val('acc-ejob')})}); closeModal(); toast('Collaborateur modifié.'); accAdminPage(); }
    catch (error) { showErr(error); }
  };
}

async function accHistory(person) {
  const items = await api(`/api/admin/collaborators/${person.id}/history`);
  const labels = {'user.create': 'Compte créé', 'user.update': 'Informations modifiées', 'user.activate': 'Compte réactivé', 'user.deactivate': 'Compte désactivé',
    'user.password.reset': 'Mot de passe réinitialisé', 'user.password.change': 'Mot de passe changé', 'user.sessions.revoke': 'Sessions révoquées',
    'user.preferences.update': 'Préférences modifiées', 'access.assignment.grant': 'Sous-dossier attribué', 'access.assignment.update': 'Actions modifiées',
    'access.assignment.revoke': 'Sous-dossier retiré', 'access.legacy.apply': 'Droit hérité confirmé', 'access.legacy.dismiss': 'Droit hérité écarté'};
  modal(`Historique · ${person.name}`, items.length ? `<ol class="acc-history">${items.map(item => `<li><time>${niceDate(item.at)}</time><div><strong>${e(labels[item.action] || item.action)}</strong>
    <span>${e(item.actor || 'Système')}${item.detail.folder ? ' · ' + e(item.detail.folder) : ''}${item.detail.after ? ' · ' + e(item.detail.after.length ? item.detail.after.length + ' action(s)' : 'aucune action') : ''}</span></div></li>`).join('')}</ol>`
    : '<p class="ops-muted">Aucun événement.</p>', true);
}

// ------------------------------------------------------------------ éditeur d'actions
function accActionEditor(actions, onApply) {
  const catalog = accState.catalog;
  const chosen = new Set(actions);
  const draw = () => `<p class="modal-desc">Toute action implique la consultation des documents ; la validation reste distincte du dépôt.</p>
    <div class="acc-presets">${catalog.presets.map(p => `<button class="secondary tiny" type="button" data-acc-preset="${e(p.key)}">${e(p.label)}</button>`).join('')}</div>
    <div class="acc-actions">${catalog.actions.map(a => `<label class="checkbox-line"><input type="checkbox" data-acc-action="${e(a.key)}" ${chosen.has(a.key) ? 'checked' : ''} ${a.key === 'document.read' && chosen.size > 1 ? 'disabled' : ''}><span><strong>${e(a.label)}</strong><small>${e(a.help)}</small></span></label>`).join('')}</div>
    <div class="modal-actions"><button class="secondary" type="button" data-acc-clear>Aucun accès</button><button class="primary" type="button" data-acc-apply>Appliquer</button></div>`;
  return {
    html: draw(),
    bind(root, rerender) {
      root.querySelectorAll('[data-acc-preset]').forEach(b => b.onclick = () => { chosen.clear(); catalog.presets.find(p => p.key === b.dataset.accPreset).actions.forEach(a => chosen.add(a)); rerender(draw()); });
      root.querySelectorAll('[data-acc-action]').forEach(box => box.onchange = () => {
        box.checked ? chosen.add(box.dataset.accAction) : chosen.delete(box.dataset.accAction);
        if (chosen.size && !chosen.has('document.read')) chosen.add('document.read');
        rerender(draw());
      });
      root.querySelector('[data-acc-clear]').onclick = () => onApply([]);
      root.querySelector('[data-acc-apply]').onclick = () => onApply(catalog.actions.map(a => a.key).filter(k => chosen.has(k)));
    },
  };
}

// ------------------------------------------------------------------ matrice d'une commande
async function accLaunchMatrix(launchId) {
  await accCatalog();
  const [matrix, launches] = await Promise.all([api(`/api/admin/launches/${launchId}/assignments`), api('/api/workspace/launches')]);
  const original = JSON.stringify(matrix.collaborators.map(p => [p.id, p.folders]));
  const actionsFor = key => accState.catalog.presets.find(item => item.key === key)?.actions || [];
  const changedPeople = () => {
    const before = new Map(JSON.parse(original));
    return matrix.collaborators.filter(person => JSON.stringify(before.get(person.id) || {}) !== JSON.stringify(person.folders));
  };
  const removedCells = () => {
    const before = new Map(JSON.parse(original));
    return matrix.collaborators.reduce((count, person) => count + ACC_FOLDERS.filter(([slug]) =>
      (before.get(person.id) || {})[slug]?.length && !person.folders[slug]?.length).length, 0);
  };
  const draw = () => {
    const rows = matrix.collaborators.map(p => `<tr><th scope="row"><strong>${e(p.name)}</strong><small>${e(p.job_title || p.email)}${p.active ? '' : ' · désactivé'}</small></th>
      ${ACC_FOLDERS.map(([slug, color, name]) => { const acts = p.folders[slug] || []; const level = accLevelFor(acts); return `<td class="acc-cell is-${slug} ${acts.length ? 'is-on' : ''}">
        <label class="sr-only" for="acc-level-${e(p.id)}-${slug}">${e(p.name)} · ${e(name)}</label>
        <select id="acc-level-${e(p.id)}-${slug}" class="acc-level" data-acc-level="${e(p.id)}:${slug}" ${p.active ? '' : 'disabled'}>
          ${ACC_LEVELS.map(([key, label]) => `<option value="${key}" ${key === level ? 'selected' : ''}>${e(label)}</option>`).join('')}
        </select>
        <small>${acts.length ? e(accActionsSummary(acts)) : 'Aucune donnée visible'}</small>
        <button class="link acc-detail" type="button" data-acc-detail="${e(p.id)}:${slug}" ${p.active ? '' : 'disabled'}>${level === 'custom' ? 'Modifier les droits' : 'Personnaliser'}</button></td>`; }).join('')}</tr>`).join('');
    const sources = launches.filter(l => l.id !== launchId).map(l => `<option value="${e(l.id)}">${e(l.order_ref || l.name)}</option>`).join('');
    const changed = changedPeople().length, removals = removedCells();
    return `<p class="modal-desc">Choisissez indépendamment le niveau de chaque collaborateur et sous-dossier. Les droits sont appliqués uniquement à cette commande ; aucune case ne donne un accès administrateur.</p>
      <section class="acc-matrix-guide" aria-label="Niveaux d'autorisation"><span><strong>Lecture seule</strong> consulte sans télécharger</span><span><strong>Dépôt sans validation</strong> ajoute une pièce, pas une version</span><span><strong>Responsable</strong> traite les contrôles et valide</span></section>
      <details class="acc-copy-option"><summary>Copier les affectations d’une autre commande <span>optionnel</span></summary><div class="field"><label for="acc-copy-from">Proposition à vérifier avant enregistrement</label><select id="acc-copy-from"><option value="">— Choisir une commande —</option>${sources}</select></div></details>
      ${matrix.collaborators.length ? `<div class="acc-matrix-wrap"><table class="acc-matrix"><caption class="sr-only">Affectations de la commande</caption><thead><tr><th scope="col">Collaborateur</th>${ACC_FOLDERS.map(([slug, color, name]) => `<th scope="col"><span class="dj-dot is-${slug}" aria-hidden="true"></span> ${color}<small>${name}</small></th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`
        : '<p class="ops-muted">Aucun collaborateur : créez des comptes dans « Collaborateurs et habilitations ».</p>'}
      <p class="acc-save-summary" aria-live="polite">${changed ? `${changed} collaborateur${changed > 1 ? 's' : ''} modifié${changed > 1 ? 's' : ''}${removals ? ` · ${removals} accès retiré${removals > 1 ? 's' : ''}` : ''}` : 'Aucune modification à enregistrer.'}</p>
      <div class="modal-actions"><button class="secondary" type="button" id="cancel-modal">Annuler</button><button class="primary" type="button" id="acc-matrix-save">Enregistrer les affectations</button></div>`;
  };
  modal(`Affecter des collaborateurs · ${matrix.launch.order_ref || matrix.launch.name}`, draw(), true);
  overlay.querySelector('.modal')?.classList.add('acc-modal-matrix');
  const bind = () => {
    const root = overlay.querySelector('.modal-body');
    overlay.querySelector('#cancel-modal').onclick = closeModal;
    root.querySelector('#acc-copy-from').onchange = async event => {
      if (!event.target.value) return;
      const proposal = await api(`/api/admin/launches/${launchId}/assignments/copy-from/${event.target.value}`);
      for (const p of matrix.collaborators) { const found = proposal.proposal.find(x => x.user_id === p.id); p.folders = found ? {...found.folders} : {}; }
      toast(`Proposition chargée depuis ${proposal.source.order_ref || proposal.source.name} : vérifiez puis enregistrez.`);
      root.innerHTML = draw(); bind();
    };
    const editCell = (uid, slug) => {
      const person = matrix.collaborators.find(p => p.id === uid);
      const editor = accActionEditor(person.folders[slug] || actionsFor('lecture'), actions => {
        if (actions.length) person.folders[slug] = actions; else delete person.folders[slug];
        root.innerHTML = draw(); bind();
      });
      const title = `<h3>${e(person.name)} · ${ACC_FOLDERS.find(f => f[0] === slug)[2]}</h3><p class="ops-muted">Sélectionnez uniquement les actions nécessaires. Le téléchargement et les nouvelles versions restent indépendants.</p>`;
      const rerender = html => { root.innerHTML = title + html; editor.bind(root, rerender); };
      rerender(editor.html);
    };
    root.querySelectorAll('[data-acc-level]').forEach(select => select.onchange = () => {
      const [uid, slug] = select.dataset.accLevel.split(':');
      const person = matrix.collaborators.find(p => p.id === uid);
      if (select.value === 'custom') return editCell(uid, slug);
      const actions = select.value === 'none' ? [] : actionsFor(select.value);
      if (actions.length) person.folders[slug] = [...actions]; else delete person.folders[slug];
      root.innerHTML = draw(); bind();
    });
    root.querySelectorAll('[data-acc-detail]').forEach(button => button.onclick = () => {
      const [uid, slug] = button.dataset.accDetail.split(':');
      editCell(uid, slug);
    });
    root.querySelector('#acc-matrix-save')?.addEventListener('click', async () => {
      const changed = changedPeople();
      const save = async () => {
        await api(`/api/admin/launches/${launchId}/assignments`, {method: 'PUT', body: JSON.stringify({assignments: changed.map(p => ({user_id: p.id, folders: p.folders}))})});
        closeModal(); toast(changed.length ? `Affectations enregistrées pour ${changed.length} collaborateur${changed.length > 1 ? 's' : ''}.` : 'Aucun changement.');
        // Habilitations modifiées : la commande affichée est relue (droits, accès, compteurs).
        if (changed.length && state.view === 'detail' && state.detail?.id === launchId) await openLaunch(launchId, null, {keep: true});
      };
      if (removedCells()) return accConfirm('Retirer des accès ?', 'Les accès retirés seront refusés dès la prochaine requête, y compris pour une session déjà ouverte.', save);
      try { await save(); } catch (error) { showErr(error); }
    });
  };
  bind();
}

// Bouton « Affecter des collaborateurs » dans l'en-tête de chaque commande (chef uniquement).
new MutationObserver(() => {
  const actions = app.querySelector('.dj-head-actions');
  if (!actions || !state.me?.admin || !state.detail || actions.querySelector('#acc-assign')) return;
  actions.insertAdjacentHTML('afterbegin', `<button class="secondary" id="acc-assign">${icon('users')} Affecter des collaborateurs</button>`);
  actions.querySelector('#acc-assign').onclick = () => accLaunchMatrix(state.detail.id).catch(showErr);
}).observe(document.querySelector('#app'), {childList: true, subtree: true});

// ------------------------------------------------------------------ habilitations d'un collaborateur
async function accCollaboratorRights(userId) {
  await accCatalog();
  const data = await api(`/api/admin/collaborators/${userId}/assignments`);
  const person = data.collaborator;
  const drawRow = item => `<tr data-acc-launch="${e(item.launch.id)}"><th scope="row"><strong>${e(item.launch.order_ref || item.launch.name)}</strong><small>${e(item.launch.name)}</small></th>
    ${ACC_FOLDERS.map(([slug, color]) => { const acts = item.folders[slug] || []; return `<td class="acc-cell is-${slug} ${acts.length ? 'is-on' : ''}"><button class="link acc-detail" type="button" data-acc-edit-cell="${e(item.launch.id)}:${slug}" aria-label="${e(color)} · ${e(item.launch.order_ref || item.launch.name)}">${acts.length ? e(accActionsSummary(acts)) : 'Ajouter'}</button></td>`; }).join('')}</tr>`;
  const draw = () => `<p class="modal-desc">${e(person.email)} · ${person.launches_count} commande(s). Cliquez sur une case pour attribuer ou régler un sous-dossier ; chaque changement est enregistré et historisé.</p>
    <div class="acc-matrix-wrap"><table class="acc-matrix"><thead><tr><th scope="col">Commande</th>${ACC_FOLDERS.map(([slug, color, name]) => `<th scope="col"><span class="dj-dot is-${slug}" aria-hidden="true"></span> ${color}<small>${name}</small></th>`).join('')}</tr></thead>
    <tbody>${data.launches.map(drawRow).join('')}</tbody></table></div>`;
  modal(`Habilitations · ${person.name}`, draw(), true);
  overlay.querySelector('.modal')?.classList.add('acc-modal-matrix');
  const bind = () => {
    const root = overlay.querySelector('.modal-body');
    root.querySelectorAll('[data-acc-edit-cell]').forEach(button => button.onclick = () => {
      const [lid, slug] = button.dataset.accEditCell.split(':');
      const item = data.launches.find(x => x.launch.id === lid);
      const save = async actions => {
        const folders = {...item.folders};
        if (actions.length) folders[slug] = actions; else delete folders[slug];
        try {
          const saved = await api(`/api/admin/collaborators/${userId}/assignments/${lid}`, {method: 'PUT', body: JSON.stringify({folders})});
          item.folders = saved.folders; toast('Habilitation enregistrée.');
        } catch (error) { showErr(error); }
        root.innerHTML = draw(); bind();
      };
      const editor = accActionEditor(item.folders[slug] || accState.catalog.presets[0].actions, save);
      const title = `<h3>${e(item.launch.order_ref || item.launch.name)} · ${ACC_FOLDERS.find(f => f[0] === slug)[2]}</h3>`;
      const rerender = html => { root.innerHTML = title + html; editor.bind(root, rerender); };
      rerender(editor.html);
    });
  };
  bind();
}

// ------------------------------------------------------------------ vision globale
async function accOverview(body) {
  const f = accState.filters;
  const [data, people] = await Promise.all([api('/api/admin/access/overview?' + new URLSearchParams({launch_id: f.launch, user_id: f.user, folder: f.folder})),
    api('/api/admin/collaborators')]);
  const k = data.kpis;
  const kpis = [['active_collaborators', 'Collaborateurs actifs'], ['launches_assigned', 'Commandes attribuées'], ['launches_chef_only', 'Gérées par le chef seul'],
    ['assigned_folders', 'Sous-dossiers attribués'], ['unassigned_folders', 'Sous-dossiers sans technicien'], ['legacy_pending', 'Droits hérités à vérifier']];
  body.innerHTML = `<section class="acc-kpis">${kpis.map(([key, label]) => `<div class="ops-kpi"><strong>${k[key]}</strong><span>${label}</span></div>`).join('')}</section>
    <p class="ops-muted">Indicateurs de répartition : un sous-dossier sans technicien n’est pas une anomalie, le chef peut le gérer lui-même.</p>
    <form class="ops-filters" id="acc-filters"><div class="field"><label for="acc-f-user">Collaborateur</label><select id="acc-f-user"><option value="">Tous</option>${people.filter(p => !p.admin).map(p => `<option value="${e(p.id)}" ${f.user === p.id ? 'selected' : ''}>${e(p.name)}</option>`).join('')}</select></div>
      <div class="field"><label for="acc-f-folder">Sous-dossier attribué</label><select id="acc-f-folder"><option value="">Tous</option>${ACC_FOLDERS.map(([s, c, n]) => `<option value="${s}" ${f.folder === s ? 'selected' : ''}>${c} · ${n}</option>`).join('')}</select></div>
      <button class="secondary" type="submit">Filtrer</button></form>
    <div class="ops-table-wrap"><table class="ops-table responsive acc-overview"><thead><tr><th>Commande</th>${ACC_FOLDERS.map(([, c, n]) => `<th>${c}<small>${n}</small></th>`).join('')}<th><span class="sr-only">Action</span></th></tr></thead>
    <tbody>${data.launches.map(row => `<tr><td data-label="Commande"><strong>${e(row.launch.order_ref || row.launch.name)}</strong><small>${e(row.launch.client_name || '')}</small>${row.chef_only ? '<span class="ops-pill">Chef seul</span>' : ''}</td>
      ${ACC_FOLDERS.map(([slug, c]) => `<td data-label="${c}">${row.folders[slug].length ? row.folders[slug].map(p => e(p.name)).join('<br>') : '<span class="ops-muted">Chef</span>'}${row.pending_validation[slug] ? `<small>${row.pending_validation[slug]} en validation</small>` : ''}</td>`).join('')}
      <td data-label="Action"><button class="secondary tiny" data-acc-matrix="${e(row.launch.id)}">Affecter</button></td></tr>`).join('')}</tbody></table></div>
    <h2 class="acc-subtitle">Affectations par collaborateur</h2>
    <ul class="acc-list">${data.by_collaborator.map(p => `<li><strong>${e(p.name)}</strong>${p.active ? '' : ' (désactivé)'} · ${p.launches} commande(s), ${p.folders} sous-dossier(s)</li>`).join('')}</ul>`;
  body.querySelector('#acc-filters').onsubmit = event => { event.preventDefault(); f.user = body.querySelector('#acc-f-user').value; f.folder = body.querySelector('#acc-f-folder').value; accOverview(body); };
  body.querySelectorAll('[data-acc-matrix]').forEach(button => button.onclick = () => accLaunchMatrix(button.dataset.accMatrix).catch(showErr));
}

// ------------------------------------------------------------------ droits hérités
async function accLegacy(body) {
  const items = await api('/api/admin/access/legacy');
  body.innerHTML = `<p class="ops-muted">Droits d’avant la gestion par commande : aucun n’a été appliqué automatiquement. Confirmez ceux qui doivent être conservés.</p>
    ${items.length ? `<div class="ops-table-wrap"><table class="ops-table responsive"><thead><tr><th>Collaborateur</th><th>Commande</th><th>Origine</th><th>Sous-dossiers proposés</th><th><span class="sr-only">Décision</span></th></tr></thead><tbody>
    ${items.map(item => `<tr><td data-label="Collaborateur"><strong>${e(item.collaborator.name)}</strong><small>${e(item.collaborator.email)}</small></td>
      <td data-label="Commande">${e(item.launch.order_ref || item.launch.name)}</td>
      <td data-label="Origine">${{role: 'Rôle (accès à toutes les commandes ouvertes)', member: 'Membre explicite', creator: 'Créateur'}[item.origin] || e(item.origin)}</td>
      <td data-label="Sous-dossiers">${ACC_FOLDERS.filter(([s]) => item.folders[s]).map(([, c]) => c).join(', ') || '—'}</td>
      <td data-label="Décision"><button class="secondary tiny" data-acc-legacy="${e(item.id)}:apply" ${Object.keys(item.folders).length ? '' : 'disabled'}>Confirmer</button> <button class="link" data-acc-legacy="${e(item.id)}:dismiss">Écarter</button></td></tr>`).join('')}</tbody></table></div>`
      : '<section class="ops-panel acc-empty"><h2>Aucun droit hérité à vérifier</h2></section>'}`;
  body.querySelectorAll('[data-acc-legacy]').forEach(button => button.onclick = async () => {
    const [id, decision] = button.dataset.accLegacy.split(':');
    try { await api(`/api/admin/access/legacy/${id}/${decision}`, {method: 'POST', body: JSON.stringify({folders: {}})}); toast(decision === 'apply' ? 'Droit confirmé.' : 'Proposition écartée.'); accLegacy(body); }
    catch (error) { showErr(error); }
  });
}

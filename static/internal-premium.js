'use strict';
/* Espace interne FRAMATEX — refonte premium (dernière couche, chargée en dernier).
   - Coque : menu latéral bleu FRAMATEX regroupé, réductible, barre supérieure en français.
     Les boutons existants (et leurs gestionnaires) sont déplacés, jamais recréés :
     aucune fonction ni aucune permission n'est modifiée.
   - Accueils administrateur et technicien sans statistiques : listes de travail
     construites uniquement à partir des API existantes et des droits du compte. */

document.body.classList.add('fx-pro');

const FX_FOLDERS = [['jaune', 'Sous-dossier jaune'], ['rose', 'Sous-dossier rose'], ['bleu', 'Sous-dossier bleu'], ['vert', 'Sous-dossier vert']];
const FX_FOLDER_NAME = Object.fromEntries(FX_FOLDERS);
const fxStore = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* stockage indisponible : préférence non conservée */ } },
};
const fxNotes = {value: null, at: 0};
const FX_SVG = {
  collapse: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m11 17-5-5 5-5M18 17l-5-5 5-5"/></svg>',
  go: '<svg class="fx-row-go" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>',
  bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
  user: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
};

function fxInitials(name) {
  return String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() || 'FX';
}
function fxFirstName(name) { return String(name || '').split(/\s+/)[0] || ''; }
function fxToday() {
  const text = new Date().toLocaleDateString('fr-FR', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  return text.charAt(0).toUpperCase() + text.slice(1);
}
function fxHasView(view) { return Boolean(app.querySelector(`.sidebar [data-view="${view}"], .sidebar [data-ops-view="${view}"], .sidebar [data-acc-view="${view}"]`)); }

async function fxUnread(force = false) {
  if (!force && fxNotes.value && Date.now() - fxNotes.at < 60000) return fxNotes.value;
  try { fxNotes.value = await api('/api/notifications'); fxNotes.at = Date.now(); } catch { fxNotes.value = null; }
  return fxNotes.value;
}

// ------------------------------------------------------------------ coque
const fxPreviousMount = mount;
mount = function(html, label) {
  fxPreviousMount(html, label);
  fxShell();
};

function fxShell() {
  const shell = app.querySelector('.app-shell');
  const sidebar = shell?.querySelector('.sidebar');
  if (!sidebar || !state.me) return;
  const admin = state.me.admin;
  if (fxStore.get('fx-sidebar') === 'mini') shell.classList.add('fx-collapsed');

  const keyOf = button => button.dataset.view || button.dataset.opsView || button.dataset.accView;
  const buttons = new Map([...sidebar.querySelectorAll('.nav-btn')].map(button => [keyOf(button), button]));
  const labels = admin
    ? {home: 'Accueil', launches: 'Commandes', search: 'Recherche documentaire', experience: 'Mémoire métier', admin: 'Rôles et checklists', audit: 'Historique et audit', pilot: 'Recette pilote'}
    : {home: 'Mon accueil', launches: 'Mes commandes', search: 'Recherche documentaire', experience: 'Mémoire métier', notifications: 'Mes notifications', actions: 'Mes actions', audit: 'Historique et audit'};
  const groups = [
    ['Travail quotidien', ['home', 'launches', 'myfolders', 'actions', 'notifications', 'search']],
    ['Ressources', ['experience', 'assistant', 'pilot']],
    [admin ? 'Administration' : 'Contrôle', ['access', 'clients', 'orli', 'admin', 'audit']],
  ];
  const account = buttons.get('account');
  buttons.delete('account');
  const nav = document.createElement('nav');
  nav.className = 'fx-nav';
  nav.setAttribute('aria-label', 'Navigation principale');
  const placed = new Set();
  for (const [title, keys] of groups) {
    const present = keys.filter(key => buttons.has(key));
    if (!present.length) continue;
    const group = document.createElement('div');
    group.className = 'fx-nav-group';
    group.innerHTML = `<p class="fx-nav-title">${e(title)}</p>`;
    for (const key of present) { group.append(buttons.get(key)); placed.add(key); }
    nav.append(group);
  }
  // Toute entrée ajoutée par un autre module reste accessible.
  const rest = [...buttons.keys()].filter(key => !placed.has(key));
  if (rest.length) nav.querySelector('.fx-nav-group')?.append(...rest.map(key => buttons.get(key)));
  for (const [key, button] of buttons) {
    const span = button.querySelector('span');
    if (labels[key] && span) span.textContent = labels[key];
    button.title = span?.textContent || '';
    button.classList.toggle('active', fxActive(key));
    if (fxActive(key)) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  sidebar.querySelectorAll('.sidebar-nav, .nav-label, .sidebar-divider, .sidebar-assistant').forEach(node => node.remove());
  const context = document.createElement('div');
  context.className = 'fx-side-context';
  context.innerHTML = `<span>${admin ? 'Dossier jaune numérique' : 'Espace technicien'}</span><button type="button" class="fx-collapse" aria-label="Réduire le menu" title="Réduire le menu">${FX_SVG.collapse}</button>`;
  sidebar.querySelector('.brand').after(context, nav);
  context.querySelector('.fx-collapse').onclick = () => {
    const mini = !shell.classList.contains('fx-collapsed');
    shell.classList.toggle('fx-collapsed', mini);
    context.querySelector('.fx-collapse').setAttribute('aria-label', mini ? 'Déployer le menu' : 'Réduire le menu');
    fxStore.set('fx-sidebar', mini ? 'mini' : 'full');
  };

  // Profil et actions de compte, en bas du menu.
  const bottom = sidebar.querySelector('.sidebar-bottom');
  if (bottom) {
    const role = bottom.querySelector('.user-role');
    if (role) role.textContent = state.me.job_title || (admin ? 'Chef — Administrateur' : state.me.roles.join(', '));
    const avatar = bottom.querySelector('.avatar');
    if (avatar) avatar.textContent = fxInitials(state.me.name);
    const actions = document.createElement('div');
    actions.className = 'fx-side-actions';
    const accountButton = document.createElement('button');
    accountButton.type = 'button';
    accountButton.className = state.view === 'account' ? 'is-active' : '';
    accountButton.dataset.accView = 'account';
    accountButton.title = 'Mon compte';
    accountButton.innerHTML = `${FX_SVG.user}<span>Mon compte</span>`;
    accountButton.onclick = () => navigate('account');
    const logout = bottom.querySelector('#logout');
    actions.append(accountButton);
    if (logout) { logout.title = 'Déconnexion'; actions.append(logout); }
    bottom.append(actions);
    account?.remove();
  }

  // Barre supérieure : libellés français, recherche, notifications, profil.
  const topbar = app.querySelector('.topbar');
  const home = topbar?.querySelector('.breadcrumb-home');
  if (home) home.textContent = 'Espace FRAMATEX';
  const search = topbar?.querySelector('#global-search');
  if (search) {
    search.setAttribute('aria-label', 'Recherche documentaire');
    const text = search.querySelector('span');
    if (text) text.textContent = 'Rechercher un document, une commande…';
    const kbd = search.querySelector('kbd');
    if (kbd) kbd.textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';
  }
  const bell = topbar?.querySelector('#top-notifications');
  if (bell) { bell.innerHTML = FX_SVG.bell; bell.title = 'Notifications'; }
  const profile = topbar?.querySelector('#top-profile');
  if (profile) {
    const fresh = profile.cloneNode(false);
    fresh.innerHTML = `<span class="fx-initials">${e(fxInitials(state.me.name))}</span><span class="fx-user-name">${e(fxFirstName(state.me.name))}</span>`;
    fresh.title = 'Mon compte';
    fresh.setAttribute('aria-label', 'Mon compte');
    fresh.onclick = () => navigate('account');
    profile.replaceWith(fresh);
  }
  // Fil d'Ariane : « Dossiers jaunes / Commande » devient « Commandes › Commande ».
  const crumb = topbar?.querySelector('.breadcrumb strong');
  if (crumb && crumb.textContent.includes(' / ')) {
    const parts = crumb.textContent.split(' / ').map(part => part === 'Dossiers jaunes' ? 'Commandes' : part);
    const last = parts.pop();
    crumb.textContent = last;
    for (const part of parts) crumb.insertAdjacentHTML('beforebegin', `<span class="fx-crumb">${e(part)}</span>${icon('arrow')}`);
  }
  fxUnread(state.view === 'notifications').then(data => fxBadges(data?.unread || 0, data?.actions || 0));
  if (['launches', 'experience'].includes(state.view)) fxCompactFilters();
  fxGroupActions();
}

// Fiche commande : actions principales visibles, actions secondaires dans un menu.
// Les boutons arrivent de plusieurs modules (parfois après le rendu) : un observateur
// regroupe ceux qui suivent le bouton principal dès qu'il y en a plus de cinq.
function fxGroupActions() {
  const bar = app.querySelector('.dj-head-actions');
  if (!bar) return;
  const loose = [...bar.children].filter(node => node.matches('button, a'));
  let menu = bar.querySelector(':scope > .fx-more');
  const total = loose.length + (menu ? menu.querySelectorAll('.fx-more-menu > *').length : 0);
  if (total <= 5) return;
  const primary = loose.find(button => button.classList.contains('primary'));
  const extra = primary ? loose.slice(loose.indexOf(primary) + 1) : loose.slice(4);
  if (!extra.length || (!menu && extra.length < 2)) return;
  if (!menu) {
    menu = document.createElement('details');
    menu.className = 'fx-more';
    menu.innerHTML = '<summary>Plus d’actions</summary><div class="fx-more-menu" role="menu"></div>';
    menu.querySelector('.fx-more-menu').addEventListener('click', () => menu.removeAttribute('open'));
    bar.append(menu);
  }
  const list = menu.querySelector('.fx-more-menu');
  for (const button of extra) { button.setAttribute('role', 'menuitem'); list.append(button); }
}
document.addEventListener('click', event => {
  app.querySelectorAll('.fx-more[open]').forEach(menu => { if (!menu.contains(event.target)) menu.removeAttribute('open'); });
});
let fxGroupPending = false;
new MutationObserver(() => {
  if (fxGroupPending || !app.querySelector('.dj-head-actions')) return;
  fxGroupPending = true;
  requestAnimationFrame(() => { fxGroupPending = false; fxGroupActions(); });
}).observe(app, {childList: true, subtree: true});

function fxActive(key) {
  return state.view === key || (state.view === 'detail' && key === 'launches');
}

function fxBadges(unread, actions = 0) {
  const nav = app.querySelector('.sidebar [data-view="notifications"]');
  nav?.querySelector('.fx-badge')?.remove();
  if (nav && unread) nav.insertAdjacentHTML('beforeend', `<span class="fx-badge" aria-label="${unread} non lue${unread > 1 ? 's' : ''}">${unread > 99 ? '99+' : unread}</span>`);
  const bell = app.querySelector('#top-notifications');
  bell?.querySelector('.fx-top-count')?.remove();
  if (bell) {
    bell.setAttribute('aria-label', `Notifications : ${unread} non lue(s), ${actions} action(s) à traiter`);
    if (unread) bell.insertAdjacentHTML('beforeend', `<span class="fx-top-count">${unread > 99 ? '99+' : unread}</span>`);
    bell.title = actions && actions !== unread ? `${unread} non lue(s) · ${actions} action(s) à traiter` : 'Notifications';
  }
}

// Une seule requête groupée alimente les compteurs. Le polling est suspendu
// dans les onglets cachés et un BroadcastChannel accélère la synchronisation.
const fxNotificationChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('framatex-notifications') : null;
async function fxRefreshNotifications(force = true) {
  const data = await fxUnread(force);
  fxBadges(data?.unread || 0, data?.actions || 0);
  return data;
}
fxNotificationChannel?.addEventListener('message', () => fxRefreshNotifications(true));
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.me) fxRefreshNotifications(true); });
setInterval(() => { if (!document.hidden && state.me) fxRefreshNotifications(true); }, 15000);
window.fxRefreshNotifications = fxRefreshNotifications;

// Commandes : filtres principaux sur une ligne, critères secondaires repliés.
function fxCompactFilters() {
  const form = app.querySelector('form.ops-filters');
  if (!form || form.closest('.fx-filterbar')) return;
  const fields = [...form.querySelectorAll(':scope > .field, :scope > label, :scope > div:not(.ops-filter-actions)')].filter(node => node.querySelector('input, select'));
  if (fields.length <= 4) return;
  const bar = document.createElement('div');
  bar.className = 'fx-filterbar is-compact';
  form.before(bar);
  bar.append(form);
  fields.slice(4).forEach(node => node.classList.add('fx-filter-more'));
  // Un critère secondaire déjà renseigné garde les filtres dépliés.
  const active = fields.slice(4).some(node => [...node.querySelectorAll('input, select')].some(input =>
    input.tagName === 'SELECT' ? input.selectedIndex > 0 : Boolean(input.value)));
  if (active) bar.classList.remove('is-compact');
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'secondary fx-filter-toggle';
  const sync = () => { toggle.textContent = bar.classList.contains('is-compact') ? 'Plus de filtres' : 'Moins de filtres'; toggle.setAttribute('aria-expanded', String(!bar.classList.contains('is-compact'))); };
  toggle.onclick = () => { bar.classList.toggle('is-compact'); sync(); };
  sync();
  const submit = form.querySelector('[type=submit]');
  if (submit) submit.before(toggle); else form.append(toggle);
}

// ------------------------------------------------------------------ accueils
function fxSection(id, title, text, body, link = '') {
  return `<section class="fx-section" id="${id}" aria-labelledby="${id}-title"><header><div><h2 id="${id}-title">${e(title)}</h2>${text ? `<p>${e(text)}</p>` : ''}</div>${link}</header><div class="fx-section-body">${body}</div></section>`;
}
function fxEmpty(text) { return `<div class="ops-empty">${e(text)}</div>`; }
function fxLink(view, text) { return `<button type="button" class="link" data-fx-go="${view}">${e(text)}</button>`; }

function fxActionRows(items) {
  if (!items.length) return fxEmpty('Aucune action prioritaire pour vos habilitations.');
  return `<ul class="fx-list">${items.map(item => {
    const tone = item.priority === 'urgent' ? 'urgent' : 'warn';
    return `<li><button type="button" class="fx-row" data-ops-target="${opsTargetData(item)}"><span class="fx-mark is-${item.folder || tone}"></span>
      <span><strong>${e(item.title)}</strong><small>${e(item.launch_name)}${item.description ? ' · ' + e(item.description) : ''}</small></span>
      <span class="fx-state is-${tone}">${e(item.priority === 'urgent' ? (item.priority_reason || 'Échéance dépassée') : 'À traiter')}</span>${FX_SVG.go}</button></li>`;
  }).join('')}</ul>`;
}

function fxFolderTags(row) {
  const tags = (row.folders || []).filter(folder => folder.can_read).map(folder => {
    const c = folder.completion || {};
    const due = c.due_count ? `<b>${c.present_due}/${c.due_count}</b>` : '';
    return `<span class="fx-folder-tag is-${folder.slug} ${c.due_count && c.present_due < c.due_count ? 'is-missing' : ''}" title="${e(FX_FOLDER_NAME[folder.slug])}${c.due_count ? ` : ${c.present_due} pièce(s) exigible(s) présente(s) sur ${c.due_count}` : ''}">${e(folder.slug.charAt(0).toUpperCase() + folder.slug.slice(1))} ${due}</span>`;
  }).join('');
  return `<div class="fx-folders">${tags || '<span class="ops-muted">—</span>'}</div>`;
}
function fxOrders(launches) {
  const rows = [...launches].sort((a, b) => String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at))).slice(0, 6);
  if (!rows.length) return fxEmpty(state.me.admin ? 'Aucune commande enregistrée.' : 'Aucune commande attribuée.');
  const stateLabel = c => ({complete: ['Complet', 'ok'], incomplete: ['Incomplet', 'warn']}[c?.state] || [c?.state ? (OPS_STATES[c.state] || c.state) : '—', '']);
  return `<div class="table-scroll"><table class="fx-orders"><thead><tr><th scope="col">Commande</th><th scope="col" class="fx-col-client">Client</th><th scope="col" class="fx-col-folders">Sous-dossiers</th><th scope="col">État</th></tr></thead><tbody>${rows.map(row => {
    const [label, tone] = stateLabel(row.completion);
    return `<tr data-fx-launch="${e(row.id)}" tabindex="0"><td><strong>${e(row.order_ref || row.name)}</strong><small>${e(row.article || row.name)}</small></td>
      <td class="fx-col-client">${e(row.client_name || '—')}</td><td class="fx-col-folders">${fxFolderTags(row)}</td>
      <td><span class="fx-state ${tone ? 'is-' + tone : ''}">${e(label)}</span><small class="ops-muted" style="display:block;margin-top:4px">${e(row.status || '')}</small></td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function fxAlerts(report) {
  const rows = report.launches.filter(row => row.alerts);
  if (!rows.length) return fxEmpty('Aucune alerte ouverte.');
  return `<ul class="fx-list">${rows.slice(0, 6).map(row => {
    const parts = [row.inconsistencies?.length ? `${row.inconsistencies.length} incohérence${row.inconsistencies.length > 1 ? 's' : ''}` : '',
      row.unacknowledged_changes ? `${row.unacknowledged_changes} modification${row.unacknowledged_changes > 1 ? 's' : ''} à examiner` : ''].filter(Boolean).join(' · ');
    const target = opsTargetData({launch_id: row.id, area: row.inconsistencies?.length ? 'quality' : 'workflow'});
    return `<li><button type="button" class="fx-row" data-ops-target="${target}"><span class="fx-mark is-urgent"></span>
      <span><strong>${e(row.order_ref || row.name)}</strong><small>${e(parts || 'Alerte à examiner')}</small></span><span class="fx-state is-urgent">Intervention</span>${FX_SVG.go}</button></li>`;
  }).join('')}</ul>`;
}

function fxNotifications(data) {
  const items = (data?.items || []).slice(0, 5);
  if (!items.length) return fxEmpty('Aucune notification.');
  return `<ul class="fx-list">${items.map(item => {
    const target = item.launch_id ? opsTargetData({launch_id: item.launch_id, folder: item.folder}) : '';
    return `<li><button type="button" class="fx-row" ${target ? `data-ops-target="${target}"` : 'data-fx-go="notifications"'}><span class="fx-mark is-${item.read_at ? '' : 'info'}"></span>
      <span><strong>${e(item.title)}</strong><small>${e(item.message || '')}</small></span><span class="fx-state ${item.read_at ? '' : 'is-info'}">${item.read_at ? niceDate(item.created_at) : 'Non lue'}</span>${FX_SVG.go}</button></li>`;
  }).join('')}</ul>`;
}

function fxRequests(requests) {
  const open = (requests || []).filter(row => ['submitted', 'under_review'].includes(row.status));
  if (!open.length) return fxEmpty('Aucune demande client en attente.');
  return `<ul class="fx-list">${open.slice(0, 5).map(row => `<li><button type="button" class="fx-row" data-fx-request="${e(row.id)}"><span class="fx-mark is-info"></span>
    <span><strong>${e(row.request_number)} · ${e(row.article)}</strong><small>${e(row.client?.raison_sociale || '')} · ${e(row.quantite)} pièces · souhaitée le ${e(opsDay(row.date_souhaitee))}</small></span>
    <span class="fx-state is-info">${e(OPS_ORDER_LABELS[row.status] || row.status)}</span>${FX_SVG.go}</button></li>`).join('')}</ul>`;
}

function fxLevel(actions) {
  const set = new Set(actions || []);
  const depot = ['document.read', 'document.download', 'document.write', 'document.version', 'document.comment', 'controls.read'];
  if (!set.size) return 'Aucun accès';
  if (set.size === 1 && set.has('document.read')) return 'Lecture seule';
  if (set.size === depot.length && depot.every(a => set.has(a))) return 'Dépôt sans validation';
  if (set.size >= 10) return 'Responsable';
  return 'Personnalisé';
}
function fxAssigned(account) {
  if (!account.assignments.length) return '';
  return `<div class="fx-assigned">${account.assignments.map(item => `<div class="fx-assigned-row"><div><strong>${e(item.launch.order_ref || item.launch.name)}</strong>
      <small>${e(item.launch.name)}${item.launch.client_name ? ' · ' + e(item.launch.client_name) : ''}</small>
      <div class="fx-folder-links">${FX_FOLDERS.filter(([slug]) => item.folders[slug]?.length).map(([slug, name]) => `<button type="button" class="fx-folder-link is-${slug}" data-fx-open="${e(item.launch.id)}" data-fx-folder="${slug}"><i aria-hidden="true"></i>${e(name)} <em>· ${e(fxLevel(item.folders[slug]))}</em></button>`).join('')}</div></div>
    <button type="button" class="secondary tiny" data-fx-open="${e(item.launch.id)}">Ouvrir la commande</button></div>`).join('')}</div>`;
}

function fxQuick(items) {
  return `<div class="fx-quick">${items.map(([view, ico, title, text]) => `<button type="button" data-fx-go="${view}">${icon(ico)}<span><span>${e(title)}</span><small>${e(text)}</small></span>${FX_SVG.go}</button>`).join('')}</div>`;
}

function fxMemory(notes) {
  const rows = (notes?.items || []).slice(0, 4);
  if (!rows.length) return fxEmpty('Aucun retour enregistré dans vos sous-dossiers.');
  const tone = {critique: 'urgent', important: 'warn', surveiller: 'warn'};
  return `<ul class="fx-list">${rows.map(note => `<li><button type="button" class="fx-row" data-fx-go="experience"><span class="fx-mark is-${e(note.folder_slug || 'info')}"></span>
    <span><strong>${e(note.party_name)}</strong><small>${e(String(note.body || '').slice(0, 110))}${String(note.body || '').length > 110 ? '…' : ''}</small><small>${e(note.order_ref || 'Note générale')}${note.folder_slug ? ' · ' + e(FX_FOLDER_NAME[note.folder_slug]) : ''}</small></span>
    <span class="fx-state ${tone[note.importance] ? 'is-' + tone[note.importance] : ''}">${e(note.category || 'Retour')}</span>${FX_SVG.go}</button></li>`).join('')}</ul>`;
}

// Tableau de bord d'une commande (fonction existante orderDashboard), choisi depuis l'accueil.
function fxOrderPicker(launches) {
  if (!launches.length) return '';
  return `<form id="dash-select-order" class="fx-order-picker"><label for="dash-order">Tableau de bord d’une commande</label>
    <select id="dash-order" required><option value="">Sélectionnez une commande</option>${launches.map(row => `<option value="${e(row.id)}">${e(row.order_ref || row.name)}${row.client_name ? ' · ' + e(row.client_name) : ''}</option>`).join('')}</select>
    <button type="submit" class="secondary">Afficher</button></form>`;
}

function fxWelcome(title, text, shortcuts) {
  return `<section class="fx-welcome ops-heading" aria-labelledby="fx-welcome-title"><span class="fx-welcome-eyebrow">Espace FRAMATEX</span>
    <h1 id="fx-welcome-title">${e(title)}</h1><p>${e(text)}</p>
    ${shortcuts.length ? `<div class="fx-shortcuts">${shortcuts.map(([action, ico, label, main]) => `<button type="button" class="fx-shortcut ${main ? 'is-main' : ''}" data-fx-shortcut="${action}">${icon(ico)}${e(label)}</button>`).join('')}</div>` : ''}</section>`;
}

async function fxHome() {
  const admin = state.me.admin;
  const [report, account, notifications, requests] = await Promise.all([
    api('/api/workspace/dashboard'),
    admin ? Promise.resolve(null) : api('/api/account'),
    fxUnread(true),
    admin ? api('/api/admin/client-order-requests').catch(() => []) : Promise.resolve(null),
  ]);
  state.view = 'home'; state.operationsDashboard = report; state.priorities = report.priorities;
  const label = admin ? 'Accueil' : 'Mon accueil';
  const name = fxFirstName(state.me.name);
  if (admin) {
    const shortcuts = [
      ...(can('launch.create') ? [['new', 'plus', 'Nouvelle commande', true]] : []),
      ['search', 'search', 'Recherche documentaire'],
      ['access', 'users', 'Collaborateurs et habilitations'], ['clients', 'users', 'Clients et demandes'], ['experience', 'file', 'Mémoire métier'],
    ];
    state.dashState = 'missing'; state.dashFilter = 'all'; state.dashShowAll = false;
    mount(`<div class="fx-home dj-dash">
      ${fxWelcome(`Bonjour ${name}`, `${fxToday()}. Commandes, documents et demandes qui attendent une intervention.`, shortcuts)}
      <div class="fx-home-grid"><div class="fx-home-col">
        ${fxSection('fx-priorities', 'Actions prioritaires', 'Pièces à déposer, validations et vérifications à mener.', fxActionRows(report.priorities.items.slice(0, 6)), fxLink('actions', 'Toutes les actions'))}
        ${dashMissingPanel(report)}
        ${fxSection('fx-orders', 'Commandes récentes', 'Dernières commandes modifiées, avec l’avancement de chaque sous-dossier.', fxOrders(report.launches) + fxOrderPicker(report.launches), fxLink('launches', 'Toutes les commandes'))}
      </div><div class="fx-home-col fx-home-side">
        ${fxSection('fx-requests', 'Demandes clients à traiter', 'Demandes envoyées depuis l’Espace Client.', fxRequests(requests), fxLink('clients', 'Clients et demandes'))}
        ${fxSection('fx-alerts', 'Alertes à traiter', 'Incohérences et modifications qui demandent une décision.', fxAlerts(report))}
        ${fxSection('fx-notifications', 'Notifications', '', fxNotifications(notifications), fxLink('notifications', 'Toutes les notifications'))}
      </div></div></div>`, label);
  } else if (!account.assignments.length) {
    mount(`<div class="fx-home">
      ${fxWelcome(`Bonjour ${name}`, 'Votre compte est actif. Vos commandes et vos sous-dossiers apparaîtront ici dès qu’un responsable vous les attribuera.', [])}
      <div class="fx-home-grid"><div class="fx-home-col">
        <section class="fx-section acc-empty" aria-live="polite"><header><div><h2>Aucune commande ne vous est attribuée pour le moment</h2>
          <p>Le chef FRAMATEX choisit, commande par commande, les sous-dossiers sur lesquels vous travaillez et les actions autorisées.</p></div></header>
          <div class="fx-section-body">${fxQuick([['account', 'users', 'Mon compte', 'Mot de passe et préférences de notification'], ['assistant', 'layers', 'Assistant FRAMATEX', 'Procédures et bons écrans']])}</div></section>
      </div><div class="fx-home-col fx-home-side">${fxSection('fx-notifications', 'Mes notifications', '', fxNotifications(notifications), fxLink('notifications', 'Toutes les notifications'))}</div></div></div>`, label);
  } else {
    // La mémoire métier applique ses propres droits (lecture du sous-dossier) : un refus masque la section.
    const memory = await api('/api/workspace/business-memory').catch(() => null);
    const pending = (report.pending_validation_documents || []).length;
    const quick = [['myfolders', 'folder', 'Mes sous-dossiers', 'Commande par commande, avec vos actions autorisées'],
      ['search', 'search', 'Recherche documentaire', 'Uniquement dans vos sous-dossiers'],
      ...(memory ? [['experience', 'file', 'Mémoire métier', 'Retours sur vos sous-dossiers']] : []),
      ['assistant', 'layers', 'Assistant', 'Procédures et bons écrans'], ['account', 'users', 'Mon compte', 'Mot de passe et préférences']];
    state.dashState = 'missing'; state.dashFilter = 'all'; state.dashShowAll = false;
    mount(`<div class="fx-home dj-dash">
      ${fxWelcome(`Bonjour ${name}`, `${fxToday()}. Vos commandes attribuées et ce qui vous attend dans vos sous-dossiers.`,
        [['launches', 'folder', 'Mes commandes', true], ['myfolders', 'folder', 'Mes sous-dossiers'], ['search', 'search', 'Recherche documentaire']])}
      <div class="fx-home-grid"><div class="fx-home-col">
        ${fxSection('fx-assigned', 'Mes commandes attribuées', 'Ouvrez directement le sous-dossier sur lequel vous travaillez.', fxAssigned(account), fxLink('myfolders', 'Mes sous-dossiers'))}
        ${fxSection('fx-priorities', 'Mes actions prioritaires', 'Limitées à vos sous-dossiers et à vos actions autorisées.', fxActionRows(report.priorities.items.slice(0, 6)), fxLink('actions', 'Toutes mes actions'))}
        ${pending || (report.missing_documents || []).length ? dashMissingPanel(report) : ''}
      </div><div class="fx-home-col fx-home-side">
        ${fxSection('fx-notifications', 'Mes notifications', '', fxNotifications(notifications), fxLink('notifications', 'Toutes les notifications'))}
        ${fxSection('fx-quick', 'Accès rapides', '', fxQuick(quick))}
        ${memory ? fxSection('fx-memory', 'Mémoire métier', 'Derniers retours sur vos sous-dossiers.', fxMemory(memory), fxLink('experience', 'Ouvrir la mémoire métier')) : ''}
      </div></div></div>`, label);
  }
  fxBindHome(report);
}

function fxBindHome(report) {
  const root = app.querySelector('.fx-home');
  if (!root) return;
  // Avec le panneau « Documents à traiter », dashBind lie toutes les cibles de l'accueil (une seule fois).
  if (!root.querySelector('#ops-missing')) bindOpsTargets(root);
  root.querySelectorAll('[data-fx-go]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.fxGo)));
  root.querySelectorAll('[data-fx-shortcut]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.fxShortcut === 'new') openNewLaunch(); else navigate(button.dataset.fxShortcut);
  }));
  root.querySelectorAll('[data-fx-launch]').forEach(row => {
    const open = () => openLaunch(row.dataset.fxLaunch);
    row.addEventListener('click', open);
    row.addEventListener('keydown', event => { if (event.key === 'Enter') open(); });
  });
  root.querySelectorAll('[data-fx-open]').forEach(button => button.addEventListener('click', () => openLaunch(button.dataset.fxOpen, button.dataset.fxFolder || undefined)));
  root.querySelectorAll('[data-fx-request]').forEach(button => button.addEventListener('click', () => operationsClientRequest(button.dataset.fxRequest).catch(showErr)));
  // Documents à traiter : composant existant (états, filtre par sous-dossier, lignes cliquables).
  if (root.querySelector('#ops-missing')) dashBind(report);
  root.querySelector('#dash-select-order')?.addEventListener('submit', event => {
    event.preventDefault();
    orderDashboard(root.querySelector('#dash-order').value).catch(showErr);
  });
}

home = fxHome;
operationsHome = fxHome;
// Technicien sans affectation : même accueil, état vide explicite.
accEmptyHome = function() { return fxHome().catch(showErr); };

// ------------------------------------------------------------------ sessions : sortie volontaire
// Icônes Lucide (ISC, lucide.dev) intégrées en SVG : aucune dépendance chargée.
const FX_LUCIDE = {
  mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
  back: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  logIn: '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="m10 17 5-5-5-5"/><path d="M15 12H3"/>',
  logOut: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
};
function fxIcon(name, cls = 'fx-ico') { return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${FX_LUCIDE[name]}</svg>`; }

// Efface de la mémoire de la page les données chargées pendant la session.
function fxForgetSession() {
  for (const key of Object.keys(state)) delete state[key];
  state.me = null;
  overlay.innerHTML = '';
  app.innerHTML = '';
}

// « Quitter l'espace et retourner à l'accueil » : la session est révoquée côté serveur
// (jti enregistré, cookie supprimé) AVANT la redirection ; sinon l'utilisateur reste ici.
async function fxExitSpace(button) {
  fxAbortPending();
  const html = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `${fxIcon('loader', 'fx-ico fx-spin')}<span>Déconnexion…</span>`;
  try {
    const response = await fetch('/api/auth/logout', {method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: {'X-Framatex-Request': '1'}});
    if (!response.ok && response.status !== 401) throw new Error(`HTTP ${response.status}`);
  } catch {
    button.disabled = false;
    button.innerHTML = html;
    toast('La déconnexion n’a pas abouti : la session reste ouverte. Vérifiez la connexion puis réessayez.');
    return;
  }
  fxForgetSession();
  location.replace('/');
}

// Retour navigateur depuis le cache : l'application revérifie la session au lieu d'afficher l'ancien écran.
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });

const fxShellBeforeExit = fxShell;
fxShell = function() {
  fxShellBeforeExit();
  const actions = app.querySelector('.fx-side-actions');
  if (actions && !app.querySelector('.fx-exit')) {
    actions.insertAdjacentHTML('afterend', `<button type="button" class="fx-exit" data-fx-exit title="Quitter l’espace et retourner à l’accueil">${fxIcon('logOut')}<span>Quitter l’espace et retourner à l’accueil</span></button>`);
    app.querySelector('.topbar-actions')?.insertAdjacentHTML('beforeend', `<button type="button" class="fx-exit-top" data-fx-exit aria-label="Quitter l’espace et retourner à l’accueil" title="Quitter l’espace et retourner à l’accueil">${fxIcon('logOut')}<span>Quitter l’espace</span></button>`);
    app.querySelectorAll('[data-fx-exit]').forEach(button => button.addEventListener('click', () => fxExitSpace(button)));
  }
};

// ------------------------------------------------------------------ connexion
function fxPasswordToggles(root) {
  root.querySelectorAll('input[type="password"]').forEach(input => {
    if (input.parentElement.classList.contains('fx-input-wrap') && input.parentElement.querySelector('.fx-eye')) return;
    let wrap = input.parentElement;
    if (!wrap.classList.contains('fx-input-wrap')) {
      wrap = document.createElement('div');
      wrap.className = 'fx-input-wrap';
      input.before(wrap);
      wrap.append(input);
      wrap.insertAdjacentHTML('afterbegin', fxIcon('lock'));
    }
    wrap.insertAdjacentHTML('beforeend', `<button type="button" class="fx-eye" aria-controls="${input.id}" aria-pressed="false" aria-label="Afficher le mot de passe">${fxIcon('eye')}</button>`);
    const eye = wrap.querySelector('.fx-eye');
    eye.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      eye.setAttribute('aria-pressed', String(show));
      eye.setAttribute('aria-label', show ? 'Masquer le mot de passe' : 'Afficher le mot de passe');
      eye.innerHTML = fxIcon(show ? 'eyeOff' : 'eye');
      input.focus();
    });
  });
}

function fxAuthArt(kicker, title, text) {
  return `<section class="login-art fx-auth-art" aria-hidden="false">
    <img class="fx-auth-photo" src="/assets/landing/redesign/espace-framatex.webp" alt="" width="1448" height="1086" decoding="async">
    <div class="fx-auth-fabric" aria-hidden="true"></div>
    <a class="brand" href="/" aria-label="FRAMATEX — retour à l’accueil"><img class="brand-mark" src="/assets/landing/logo-framatex.jpg" alt="FRAMATEX" width="500" height="500"></a>
    <div class="login-hero"><p class="fx-auth-kicker">${e(kicker)}</p><h1>${title}</h1><p>${e(text)}</p></div>
    <p class="login-caption">Villeneuve-d’Ascq <span aria-hidden="true">—</span> Casablanca</p></section>`;
}

renderLogin = function() {
  overlay.innerHTML = '';
  app.innerHTML = `<div class="login-page fx-auth">${fxAuthArt('Espace FRAMATEX', 'Chaque commande.<br>Chaque document.<br><em>Au bon endroit.</em>', 'Commandes, sous-dossiers, versions et contrôles : l’espace de travail des équipes FRAMATEX.')}
    <section class="login-form-wrap"><a class="fx-auth-back" href="/">${fxIcon('back')}<span>Retour à l’accueil</span></a>
      <form id="login-form" class="login-form" novalidate>
        <h2>Connexion</h2><p class="fx-auth-lead">Espace réservé aux collaborateurs FRAMATEX.</p>
        <div id="login-error" role="alert" aria-live="assertive"></div>
        <div class="field"><label for="email">Adresse email professionnelle</label><div class="fx-input-wrap">${fxIcon('mail')}<input id="email" type="email" autocomplete="username" inputmode="email" required placeholder="prenom.nom@framatex.com"></div></div>
        <div class="field"><label for="password">Mot de passe</label><div class="fx-input-wrap">${fxIcon('lock')}<input id="password" type="password" autocomplete="current-password" required placeholder="Votre mot de passe"></div></div>
        <button class="primary fx-auth-submit" type="submit"><span>Se connecter</span>${fxIcon('logIn')}</button>
        <ul class="fx-auth-notes"><li>${fxIcon('shield')}<span>Les comptes sont créés par le chef FRAMATEX ; un mot de passe temporaire doit être remplacé à la première connexion.</span></li>
          <li>${fxIcon('lock')}<span>Mot de passe oublié : demandez une réinitialisation à votre responsable.</span></li></ul>
        <p class="fx-auth-switch">Vous êtes client ? <a href="/espace-client">Accéder à l’Espace Client</a></p>
      </form></section></div>`;
  fxPasswordToggles(app);
  const form = app.querySelector('#login-form');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('.fx-auth-submit');
    const error = app.querySelector('#login-error');
    const email = app.querySelector('#email').value.trim(), password = app.querySelector('#password').value;
    if (!email || !password) { error.innerHTML = `<div class="error">Saisissez votre adresse email et votre mot de passe.</div>`; return; }
    button.disabled = true;
    button.innerHTML = `${fxIcon('loader', 'fx-ico fx-spin')}<span>Connexion…</span>`;
    error.innerHTML = '';
    try {
      state.me = await api('/api/auth/login', {method: 'POST', body: JSON.stringify({email, password})});
      state.me = await api('/api/auth/me');
      if (!(await paperOpenDeepLink())) await navigate('home');
    } catch (err) {
      error.innerHTML = `<div class="error">${e(err.message)}</div>`;
      button.disabled = false;
      button.innerHTML = `<span>Se connecter</span>${fxIcon('logIn')}`;
    }
  });
};

// Changement de mot de passe temporaire : même composition, logique inchangée (access-admin.js).
const fxPasswordScreen = accPasswordScreen;
accPasswordScreen = function() {
  fxPasswordScreen();
  const page = app.querySelector('.login-page');
  if (!page) return;
  page.classList.add('fx-auth');
  page.querySelector('.login-art')?.replaceWith(Object.assign(document.createElement('div'), {innerHTML: fxAuthArt('Première connexion', 'Choisissez<br><em>votre mot de passe.</em>', 'Le mot de passe transmis par votre responsable est temporaire : remplacez-le avant d’accéder aux commandes.')}).firstElementChild);
  page.querySelector('.login-form-wrap')?.insertAdjacentHTML('afterbegin', `<span class="fx-auth-back is-static">${fxIcon('shield')}<span>Sécurité du compte</span></span>`);
  fxPasswordToggles(page);
};

// Tissu 3D dans le panneau décoratif des connexions (grands écrans, hors mouvement réduit, WebGL requis).
function fxMountAuthFabric() {
  const host = app.querySelector('.fx-auth-fabric:not([data-ready])');
  if (!host || innerWidth < 961 || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  try { const c = document.createElement('canvas'); if (!(c.getContext('webgl2') || c.getContext('webgl'))) return; } catch { return; }
  host.dataset.ready = '1';
  import('/assets/landing/fabric3d.js?v=cinematic-3d-1').then(m => m.mountFabric(host, {interactive: true})).catch(() => {});
}
const fxRenderLoginBase = renderLogin;
renderLogin = function() { fxRenderLoginBase(); fxMountAuthFabric(); };
const fxPasswordScreenBase = accPasswordScreen;
accPasswordScreen = function() { fxPasswordScreenBase(); fxMountAuthFabric(); };

// Espace Client FRAMATEX — interface (routeur par ancre, écrans, formulaires).
// Toutes les données passent par l'API client réelle (static/client/api.js → app/client_routes.py).

import * as api from './api.js?v=runtime-final-1';
import {
  icon, esc, fmtDate, fmtQty, fmtSize, statusBadge, REQUEST_STATUS, DOCUMENT_STATUS, documentStatusBadge, field, passwordField,
  setFieldError, clearErrors, showFormAlert, bindPasswordToggles, setLoading, toast,
  emptyState, errorState, loadingState,
} from './components/ui.js';

const source = api;

// Formats et taille alignés sur app/client_routes.py (EXTS, MAX_UPLOAD).
const UPLOAD = {
  maxBytes: 20 * 1024 * 1024,
  extensions: ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png', '.txt'],
  label: 'PDF, DOCX, XLSX, JPG, PNG ou TXT',
  sizeLabel: '20 Mo',
};
const CONTACT_EMAIL = 'contact@framatex.net';
const LOGO = '/assets/landing/logo-framatex.jpg';
const AUTH_PHOTO = '/assets/landing/redesign/espace-client.webp';

const app = document.getElementById('app');
const state = { client: null, hadSession: false, notice: '' };

// --------------------------------------------------------------------------
// Messages d'erreur (jamais de détail technique affiché)
// --------------------------------------------------------------------------
function messageFor(err, context = '') {
  switch (err?.code) {
    case 'invalid_credentials': return 'Adresse email ou mot de passe incorrect.';
    case 'inactive': return 'Votre compte est en attente de validation par FRAMATEX ou a été suspendu.';
    case 'pending': return 'Votre compte est en attente de validation par FRAMATEX.';
    case 'suspended': return 'Votre compte a été suspendu. Contactez FRAMATEX.';
    case 'rate_limited': return 'Trop de tentatives. Réessayez dans quelques minutes.';
    case 'conflict': return err.detail || 'Cet élément existe déjà.';
    case 'rejected': return err.detail || 'Ce fichier ou ces informations ont été refusés.';
    case 'unauthenticated': return 'Votre session a expiré. Veuillez vous reconnecter.';
    case 'forbidden': return 'Vous n’avez pas accès à cette ressource.';
    case 'not_found': return context === 'request' ? 'Cette demande est introuvable.' : 'Élément introuvable.';
    case 'too_large': return `Le fichier dépasse la taille maximale autorisée (${UPLOAD.sizeLabel}).`;
    case 'unsupported_type': return `Format non accepté. Formats autorisés : ${UPLOAD.label}.`;
    case 'validation': return 'Certaines informations sont invalides. Vérifiez le formulaire.';
    case 'network': return 'Connexion au serveur impossible. Vérifiez votre connexion internet.';
    default: return 'Une erreur est survenue. Veuillez réessayer dans quelques instants.';
  }
}

// --------------------------------------------------------------------------
// Routeur
// --------------------------------------------------------------------------
const ROUTES = [
  { path: '/', view: viewEntry, title: 'Espace Client' },
  { path: '/connexion', view: viewLogin, title: 'Connexion' },
  { path: '/inscription', view: viewRegister, title: 'Créer un compte client' },
  { path: '/inscription/envoyee', view: viewRegistered, title: 'Demande de compte enregistrée' },
  { path: '/en-attente', view: viewPending, title: 'Compte en attente de validation' },
  { path: '/suspendu', view: viewSuspended, title: 'Compte suspendu' },
  { path: '/demandes', view: viewRequests, title: 'Mes demandes', auth: true, nav: 'requests' },
  { path: '/demandes/nouvelle', view: viewNewRequest, title: 'Nouvelle demande', auth: true, nav: 'new' },
  { path: '/demandes/:id', view: viewRequestDetail, title: 'Détail de la demande', auth: true, nav: 'requests' },
  { path: '/documents', view: viewDocuments, title: 'Mes documents', auth: true, nav: 'documents' },
  { path: '/documents-demandes', view: viewDocumentRequests, title: 'Documents demandés par FRAMATEX', auth: true, nav: 'requested' },
  { path: '/documents-demandes/:id', view: viewDocumentRequest, title: 'Pièce demandée par FRAMATEX', auth: true, nav: 'requested' },
  { path: '/documents-transmis', view: viewSharedDocuments, title: 'Documents transmis par FRAMATEX', auth: true, nav: 'shared' },
  { path: '/compte', view: viewAccount, title: 'Mon compte', auth: true, nav: 'account' },
];

function currentPath() {
  const p = window.location.hash.replace(/^#/, '');
  return p.startsWith('/') ? p : '/';
}

function match(path) {
  for (const r of ROUTES) {
    const keys = [];
    const re = new RegExp('^' + r.path.replace(/:([a-z]+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '$');
    const m = re.exec(path);
    if (m) return { route: r, params: Object.fromEntries(keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) };
  }
  return null;
}

export function go(path) {
  if (currentPath() === path) render();
  else window.location.hash = path;
}

let firstRender = true;
async function render() {
  closeDrawer();
  const path = currentPath();
  const found = match(path);
  if (!found) { app.innerHTML = publicLayout(errorState({ title: 'Page introuvable', text: 'Cette page n’existe pas.', action: `<a class="btn btn-primary" href="#/">Retour à l’Espace Client</a>` })); return; }
  const { route, params } = found;

  if (route.auth && !state.client) {
    try {
      state.client = await source.getCurrentClient();
      state.hadSession = true;
    } catch (err) {
      if (['inactive', 'pending', 'suspended'].includes(err.code)) { go(err.code === 'suspended' ? '/suspendu' : '/en-attente'); return; }
      state.notice = state.hadSession ? messageFor({ code: 'unauthenticated' }) : '';
      state.hadSession = false;
      go('/connexion');
      return;
    }
  }
  if (!route.auth && state.client && (path === '/' || path === '/connexion')) { go('/demandes'); return; }

  document.title = `${route.title} · Espace Client FRAMATEX`;
  await route.view(params, route);
  if (!firstRender) app.querySelector('h1')?.focus({ preventScroll: false });
  firstRender = false;
  window.scrollTo(0, 0);
}

// Efface l'erreur d'un champ dès que l'utilisateur le corrige.
function liveClear(form) {
  const clear = e => {
    const w = e.target.closest('[data-field]');
    if (w?.classList.contains('has-error')) setFieldError(form, w.dataset.field, '');
  };
  form.addEventListener('input', clear);
  form.addEventListener('change', clear);
}

// Gestion centralisée des erreurs d'écran protégé.
function handleScreenError(err, container, context) {
  if (['inactive', 'pending', 'suspended'].includes(err.code)) { state.client = null; go(err.code === 'suspended' ? '/suspendu' : '/en-attente'); return; }
  if (err.code === 'unauthenticated') {
    state.client = null;
    state.notice = messageFor(err);
    go('/connexion');
    return;
  }
  const title = err.code === 'not_found' ? (context === 'request' ? 'Demande introuvable' : 'Introuvable')
    : err.code === 'forbidden' ? 'Accès refusé' : 'Chargement impossible';
  const text = err.code === 'not_found' && context === 'request'
    ? 'Cette demande n’existe pas ou n’est pas accessible depuis votre compte.'
    : messageFor(err, context);
  container.innerHTML = errorState({ title, text, action: `<a class="btn btn-secondary" href="#/demandes">${icon('back')}Retour à mes demandes</a>` });
}

// --------------------------------------------------------------------------
// Mises en page
// --------------------------------------------------------------------------
function publicLayout(content) {
  return `<header class="pub-header">
      <div class="pub-header-inner">
        <a class="brand" href="#/" aria-label="Espace Client FRAMATEX — accueil">
          <img src="${LOGO}" alt="FRAMATEX" width="500" height="500" />
          <span class="brand-label">Espace Client</span>
        </a>
        <a class="pub-back" href="/">${icon('back')}<span>Retour au site</span></a>
      </div>
    </header>
    <main id="contenu" class="pub-main">${content}</main>`;
}

function authLayout(content, { wide = false } = {}) {
  return publicLayout(`<div class="auth ${wide ? 'auth-wide' : ''}">
      <aside class="auth-visual" aria-hidden="true">
        <img src="${AUTH_PHOTO}" alt="" width="1448" height="1086" />
        <div class="auth-visual-text">
          <p class="eyebrow eyebrow-light">Espace Client FRAMATEX</p>
          <p class="auth-visual-title">Vos demandes de commande et vos documents, au même endroit.</p>
        </div>
      </aside>
      <section class="auth-panel">${content}</section>
    </div>`);
}

const NAV = [
  { key: 'requests', href: '#/demandes', label: 'Mes demandes', icon: 'layers' },
  { key: 'new', href: '#/demandes/nouvelle', label: 'Nouvelle demande', icon: 'plus' },
  { key: 'documents', href: '#/documents-demandes', label: 'Documents', icon: 'folder' },
  { key: 'account', href: '#/compte', label: 'Mon compte', icon: 'users' },
];
// Les trois vues documentaires partagent l'entrée « Documents » et des onglets.
const NAV_GROUP = { requested: 'documents', shared: 'documents', documents: 'documents' };
const DOC_TABS = [
  { key: 'requested', href: '#/documents-demandes', label: 'À fournir' },
  { key: 'shared', href: '#/documents-transmis', label: 'Reçus de FRAMATEX' },
  { key: 'documents', href: '#/documents', label: 'Mes dépôts' },
];
const PENDING_DOC = new Set(['requested', 'correction_required']);

function docTabs(active) {
  return `<nav class="doc-tabs" aria-label="Documents">${DOC_TABS.map(t => `<a class="doc-tab${t.key === active ? ' is-active' : ''}" href="${t.href}"${t.key === active ? ' aria-current="page"' : ''}>${t.label}${t.key === 'requested' ? '<span class="nav-badge" data-pending-docs hidden></span>' : ''}</a>`).join('')}</nav>`;
}

// Nombre de pièces à fournir : affiché sur l'entrée « Documents » et l'onglet « À fournir ».
async function refreshPendingBadge() {
  try {
    const items = await source.listDocumentRequests();
    const n = items.filter(item => PENDING_DOC.has(item.status)).length;
    app.querySelectorAll('[data-pending-docs]').forEach(badge => {
      badge.textContent = n; badge.hidden = !n;
      badge.setAttribute('aria-label', `${n} pièce${n > 1 ? 's' : ''} à fournir`);
    });
  } catch { /* le badge est un confort : son absence ne bloque rien */ }
}

function identity() {
  const c = state.client || {};
  return `<div class="identity">
      <p class="identity-company">${esc(c.raison_sociale || '')}</p>
      ${c.nom_contact ? `<p class="identity-contact">${esc(c.nom_contact)}</p>` : ''}
      ${c.client_code ? `<p class="identity-code">${esc(c.client_code)}</p>` : ''}
    </div>`;
}

function navList(active) {
  const current = NAV_GROUP[active] || active;
  return `<ul class="nav-list">${NAV.map(n => `<li><a class="nav-link${n.key === current ? ' is-active' : ''}" href="${n.href}"${n.key === current ? ' aria-current="page"' : ''}>${icon(n.icon)}<span>${n.label}</span>${n.key === 'documents' ? '<span class="nav-badge" data-pending-docs hidden></span>' : ''}</a></li>`).join('')}</ul>`;
}

function shellLayout(active, content) {
  return `<div class="shell">
    <aside class="sidebar" aria-label="Navigation de l’Espace Client">
      <a class="brand brand-side" href="#/demandes" aria-label="Espace Client FRAMATEX — mes demandes">
        <img src="${LOGO}" alt="FRAMATEX" width="500" height="500" />
        <span class="brand-label">Espace Client</span>
      </a>
      ${identity()}
      <nav aria-label="Menu principal">${navList(active)}</nav>
      <div class="sidebar-foot">
        <button type="button" class="nav-link nav-logout" data-logout>${icon('out')}<span>Déconnexion</span></button>
      </div>
    </aside>

    <header class="topbar">
      <a class="brand" href="#/demandes" aria-label="Espace Client FRAMATEX — mes demandes">
        <img src="${LOGO}" alt="FRAMATEX" width="500" height="500" />
        <span class="brand-label">Espace Client</span>
      </a>
      <button type="button" class="menu-btn" data-drawer-open aria-expanded="false" aria-controls="drawer">
        <span class="menu-bars" aria-hidden="true"><span></span><span></span><span></span></span><span>Menu</span>
      </button>
    </header>
    <div class="drawer-backdrop" data-drawer-close hidden></div>
    <div class="drawer" id="drawer" role="dialog" aria-modal="true" aria-label="Menu de l’Espace Client" hidden>
      <div class="drawer-head">
        ${identity()}
        <button type="button" class="icon-btn" data-drawer-close aria-label="Fermer le menu">${icon('x')}</button>
      </div>
      <nav aria-label="Menu principal">${navList(active)}</nav>
      <button type="button" class="nav-link nav-logout" data-logout>${icon('out')}<span>Déconnexion</span></button>
    </div>

    <main id="contenu" class="shell-main"><div class="page">${content}</div></main>
  </div>`;
}

function pageHead({ eyebrow = 'Espace Client', title, lead = '', actions = '', back = '' }) {
  return `<div class="page-head">
    ${back}
    <div class="page-head-row">
      <div>
        <p class="eyebrow">${esc(eyebrow)}</p>
        <h1 tabindex="-1">${esc(title)}</h1>
        ${lead ? `<p class="page-lead">${esc(lead)}</p>` : ''}
      </div>
      ${actions ? `<div class="page-actions">${actions}</div>` : ''}
    </div>
  </div>`;
}

function mountShell(active, content) {
  app.innerHTML = shellLayout(active, content);
  app.querySelectorAll('[data-logout]').forEach(b => b.addEventListener('click', logout));
  app.querySelector('[data-drawer-open]')?.addEventListener('click', openDrawer);
  app.querySelectorAll('[data-drawer-close]').forEach(b => b.addEventListener('click', closeDrawer));
  refreshPendingBadge();
}

function openDrawer() {
  const drawer = document.getElementById('drawer');
  if (!drawer) return;
  drawer.hidden = false;
  app.querySelector('.drawer-backdrop').hidden = false;
  app.querySelector('[data-drawer-open]').setAttribute('aria-expanded', 'true');
  document.body.classList.add('no-scroll');
  drawer.querySelector('.nav-link')?.focus();
}
function closeDrawer() {
  const drawer = document.getElementById('drawer');
  if (!drawer || drawer.hidden) return;
  drawer.hidden = true;
  app.querySelector('.drawer-backdrop').hidden = true;
  const btn = app.querySelector('[data-drawer-open]');
  btn?.setAttribute('aria-expanded', 'false');
  document.body.classList.remove('no-scroll');
  btn?.focus();
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

async function logout(e) {
  const btn = e.currentTarget;
  setLoading(btn, true, 'Déconnexion…');
  try { await source.logoutClient(); } catch { /* La session est de toute façon abandonnée côté interface. */ }
  state.client = null;
  state.hadSession = false;
  go('/');
  toast('Vous êtes déconnecté.', 'success');
}

// --------------------------------------------------------------------------
// A. Entrée
// --------------------------------------------------------------------------
function viewEntry() {
  app.innerHTML = authLayout(`
    <p class="eyebrow">Espace Client</p>
    <h1 tabindex="-1">Bienvenue dans votre Espace Client FRAMATEX</h1>
    <p class="auth-lead">Déposez une demande de commande et transmettez simplement les documents nécessaires à FRAMATEX.</p>
    <div class="choice-list">
      <a class="choice" href="#/connexion">
        <span class="choice-ico">${icon('lock')}</span>
        <span class="choice-body"><span class="choice-title">Se connecter</span><span class="choice-text">Vous avez déjà un compte client validé.</span></span>
        ${icon('arrow', 'ico choice-arrow')}
      </a>
      <a class="choice" href="#/inscription">
        <span class="choice-ico">${icon('users')}</span>
        <span class="choice-body"><span class="choice-title">Créer un compte client</span><span class="choice-text">Première demande auprès de FRAMATEX.</span></span>
        ${icon('arrow', 'ico choice-arrow')}
      </a>
    </div>
    <p class="auth-note">${icon('info')}<span>Chaque nouveau compte est validé par FRAMATEX avant le premier accès.</span></p>
  `);
}

// --------------------------------------------------------------------------
// B. Connexion
// --------------------------------------------------------------------------
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function viewLogin() {
  const notice = state.notice; state.notice = '';
  app.innerHTML = authLayout(`
    <p class="eyebrow">Accès client</p>
    <h1 tabindex="-1">Connexion</h1>
    <p class="auth-lead">Accédez à vos demandes de commande et à vos documents.</p>
    <form class="form" id="login-form" novalidate>
      <div class="form-alert" role="alert"${notice ? '' : ' hidden'}>${notice ? `${icon('info')}<span>${esc(notice)}</span>` : ''}</div>
      ${field({ id: 'login-email', label: 'Adresse email', type: 'email', required: true, autocomplete: 'username', attrs: 'inputmode="email"' })}
      ${passwordField({ id: 'login-password', label: 'Mot de passe', autocomplete: 'current-password' })}
      <button class="btn btn-primary btn-block" type="submit">Se connecter</button>
    </form>
    <p class="auth-switch">Pas encore de compte ? <a href="#/inscription">Créer un compte client</a></p>
  `);
  const form = app.querySelector('#login-form');
  bindPasswordToggles(form);
  liveClear(form);
  form.addEventListener('submit', async e => {
    e.preventDefault();
    clearErrors(form);
    const email = form['login-email'].value.trim();
    const password = form['login-password'].value;
    let ok = true;
    if (!email) { setFieldError(form, 'login-email', 'Saisissez votre adresse email.'); ok = false; }
    else if (!EMAIL_RE.test(email)) { setFieldError(form, 'login-email', 'Adresse email invalide.'); ok = false; }
    if (!password) { setFieldError(form, 'login-password', 'Saisissez votre mot de passe.'); ok = false; }
    if (!ok) { form.querySelector('[aria-invalid="true"]')?.focus(); return; }
    const btn = form.querySelector('[type="submit"]');
    setLoading(btn, true, 'Connexion…');
    try {
      await source.loginClient({ email, password });
      state.client = await source.getCurrentClient();
      state.hadSession = true;
      go('/demandes');
    } catch (err) {
      if (['inactive', 'pending', 'suspended'].includes(err.code)) { go(err.code === 'suspended' ? '/suspendu' : '/en-attente'); return; }
      showFormAlert(form, messageFor(err));
      form['login-password'].value = '';
      setLoading(btn, false);
    }
  });
}

// --------------------------------------------------------------------------
// C. Création de compte
// --------------------------------------------------------------------------
const COUNTRIES = ['France', 'Maroc', 'Belgique', 'Suisse', 'Luxembourg', 'Espagne', 'Portugal', 'Italie', 'Allemagne', 'Pays-Bas', 'Royaume-Uni', 'Tunisie', 'Autre'];
const PASSWORD_MIN = 12; // RegisterPayload.password : min_length=12.
// Champs backend → identifiants de champs du formulaire (erreurs de validation serveur).
const REGISTER_FIELDS = { raison_sociale: 'reg-company', identifiant_fiscal: 'reg-taxid', adresse: 'reg-address', pays: 'reg-country', nom_contact: 'reg-contact', telephone: 'reg-phone', email: 'reg-email', password: 'reg-password' };

function viewRegister() {
  app.innerHTML = authLayout(`
    <a class="back-link" href="#/">${icon('back')}Espace Client</a>
    <p class="eyebrow">Nouveau client</p>
    <h1 tabindex="-1">Créer un compte client</h1>
    <p class="auth-lead">Votre compte sera activé par FRAMATEX après vérification de vos informations.</p>
    <form class="form" id="register-form" novalidate>
      <div class="form-alert" role="alert" hidden></div>
      <fieldset class="form-section">
        <legend>Entreprise</legend>
        <div class="grid-2">
          ${field({ id: 'reg-company', label: 'Raison sociale', required: true, autocomplete: 'organization' })}
          ${field({ id: 'reg-taxid', label: 'ICE / identifiant fiscal', help: 'ICE pour une entreprise marocaine, SIRET ou n° de TVA sinon.' })}
        </div>
        ${field({ id: 'reg-address', label: 'Adresse', required: true, autocomplete: 'street-address' })}
        <div class="grid-2">
          ${field({ id: 'reg-country', label: 'Pays', required: true, autocomplete: 'country-name', options: [{ value: '', label: 'Sélectionnez un pays' }, ...COUNTRIES.map(c => ({ value: c, label: c }))] })}
        </div>
      </fieldset>
      <fieldset class="form-section">
        <legend>Contact</legend>
        <div class="grid-2">
          ${field({ id: 'reg-contact', label: 'Nom du contact', required: true, autocomplete: 'name' })}
          ${field({ id: 'reg-phone', label: 'Téléphone', type: 'tel', required: true, autocomplete: 'tel', attrs: 'inputmode="tel"' })}
        </div>
        ${field({ id: 'reg-email', label: 'Adresse email professionnelle', type: 'email', required: true, autocomplete: 'email', attrs: 'inputmode="email"' })}
      </fieldset>
      <fieldset class="form-section">
        <legend>Sécurité</legend>
        <div class="grid-2">
          ${passwordField({ id: 'reg-password', label: 'Mot de passe', autocomplete: 'new-password', help: `${PASSWORD_MIN} caractères minimum.` })}
          ${passwordField({ id: 'reg-password2', label: 'Confirmation du mot de passe', autocomplete: 'new-password' })}
        </div>
      </fieldset>
      <button class="btn btn-primary btn-block" type="submit">Envoyer ma demande de compte</button>
    </form>
    <p class="auth-switch">Déjà client ? <a href="#/connexion">Se connecter</a></p>
  `, { wide: true });

  const form = app.querySelector('#register-form');
  bindPasswordToggles(form);
  liveClear(form);
  form.addEventListener('submit', async e => {
    e.preventDefault();
    clearErrors(form);
    const v = id => form[id].value.trim();
    const errors = {};
    if (!v('reg-company')) errors['reg-company'] = 'Indiquez la raison sociale.';
    if (!v('reg-address')) errors['reg-address'] = 'Indiquez l’adresse de l’entreprise.';
    if (!v('reg-country')) errors['reg-country'] = 'Sélectionnez un pays.';
    if (!v('reg-contact')) errors['reg-contact'] = 'Indiquez le nom du contact.';
    if (!v('reg-phone')) errors['reg-phone'] = 'Indiquez un numéro de téléphone.';
    else if (!/^[+0-9 ().-]{6,}$/.test(v('reg-phone'))) errors['reg-phone'] = 'Numéro de téléphone invalide.';
    if (!v('reg-email')) errors['reg-email'] = 'Indiquez une adresse email.';
    else if (!EMAIL_RE.test(v('reg-email'))) errors['reg-email'] = 'Adresse email invalide.';
    const pw = form['reg-password'].value;
    if (pw.length < PASSWORD_MIN) errors['reg-password'] = `Le mot de passe doit contenir au moins ${PASSWORD_MIN} caractères.`;
    if (form['reg-password2'].value !== pw) errors['reg-password2'] = 'Les deux mots de passe ne correspondent pas.';
    Object.entries(errors).forEach(([id, msg]) => setFieldError(form, id, msg));
    if (Object.keys(errors).length) { form.querySelector('[aria-invalid="true"]')?.focus(); return; }

    const btn = form.querySelector('[type="submit"]');
    setLoading(btn, true, 'Envoi en cours…');
    try {
      await source.registerClient({
        raison_sociale: v('reg-company'), identifiant_fiscal: v('reg-taxid'), adresse: v('reg-address'), pays: v('reg-country'),
        nom_contact: v('reg-contact'), telephone: v('reg-phone'), email: v('reg-email'), password: pw,
      });
      form.reset();
      go('/inscription/envoyee');
    } catch (err) {
      if (err.fields) Object.entries(err.fields).forEach(([key, msg]) => REGISTER_FIELDS[key] && setFieldError(form, REGISTER_FIELDS[key], 'Valeur invalide.'));
      if (err.code === 'conflict') setFieldError(form, 'reg-email', 'Un compte existe déjà pour cette adresse email.');
      showFormAlert(form, messageFor(err));
      setLoading(btn, false);
    }
  });
}

// --------------------------------------------------------------------------
// D. Confirmation / compte en attente
// --------------------------------------------------------------------------
function statusPanel({ tone, ico, eyebrow, title, paragraphs, steps, actions }) {
  return authLayout(`
    <div class="status-panel status-${tone}">
      <div class="status-mark" aria-hidden="true">${icon(ico)}</div>
      <p class="eyebrow">${esc(eyebrow)}</p>
      <h1 tabindex="-1">${esc(title)}</h1>
      ${paragraphs.map(p => `<p class="auth-lead">${esc(p)}</p>`).join('')}
      <ol class="steps">
        ${steps.map(s => `<li class="step step-${s.state}"><span class="step-dot" aria-hidden="true">${s.state === 'done' ? icon('check') : ''}</span><span>${esc(s.label)}<span class="visually-hidden"> — ${s.state === 'done' ? 'terminé' : s.state === 'current' ? 'en cours' : 'à venir'}</span></span></li>`).join('')}
      </ol>
      <div class="status-actions">${actions}</div>
    </div>`);
}

function viewRegistered() {
  app.innerHTML = statusPanel({
    tone: 'success', ico: 'check', eyebrow: 'Demande enregistrée', title: 'Votre demande de compte a bien été enregistrée',
    paragraphs: [
      'Votre compte est en attente de validation par FRAMATEX.',
      'Il doit être validé avant que vous puissiez accéder à votre espace client. Vous pourrez ensuite vous connecter avec votre adresse email et votre mot de passe.',
    ],
    steps: [
      { label: 'Demande de compte envoyée', state: 'done' },
      { label: 'Validation par FRAMATEX', state: 'current' },
      { label: 'Accès à l’Espace Client', state: 'todo' },
    ],
    actions: `<a class="btn btn-primary" href="#/">Retour à l’Espace Client</a>`,
  });
}

function viewPending() {
  app.innerHTML = statusPanel({
    tone: 'warn', ico: 'clock', eyebrow: 'Compte en attente', title: 'Votre compte est en attente de validation par FRAMATEX',
    paragraphs: [
      'Vous pourrez vous connecter dès que FRAMATEX aura validé votre compte.',
      `Pour toute question, écrivez-nous à ${CONTACT_EMAIL}.`,
    ],
    steps: [
      { label: 'Demande de compte envoyée', state: 'done' },
      { label: 'Validation par FRAMATEX', state: 'current' },
      { label: 'Accès à l’Espace Client', state: 'todo' },
    ],
    actions: `<a class="btn btn-secondary" href="#/connexion">${icon('back')}Retour à la connexion</a><a class="btn btn-ghost" href="mailto:${CONTACT_EMAIL}">Contacter FRAMATEX</a>`,
  });
}

function viewSuspended() {
  app.innerHTML = statusPanel({
    tone: 'warn', ico: 'lock', eyebrow: 'Compte suspendu',
    title: 'Votre compte a été suspendu. Contactez FRAMATEX.',
    paragraphs: [`Votre accès est suspendu. Votre interlocuteur FRAMATEX peut vous renseigner à ${CONTACT_EMAIL}.`],
    steps: [], actions: `<a class="btn btn-secondary" href="#/connexion">Retour à la connexion</a><a class="btn btn-ghost" href="mailto:${CONTACT_EMAIL}">Contacter FRAMATEX</a>`,
  });
}

// --------------------------------------------------------------------------
// F. Mes demandes
// --------------------------------------------------------------------------
async function viewRequests() {
  mountShell('requests', `${pageHead({
    title: 'Mes demandes', lead: 'Vos demandes de commande transmises à FRAMATEX.',
    actions: `<a class="btn btn-primary" href="#/demandes/nouvelle">${icon('plus')}Nouvelle demande</a>`,
  })}<div id="requests-body">${loadingState('Chargement de vos demandes…')}</div>`);
  const body = app.querySelector('#requests-body');
  let items;
  try { items = await source.listOrderRequests(); } catch (err) { handleScreenError(err, body); return; }
  if (!items.length) {
    body.innerHTML = emptyState({
      title: 'Vous n’avez encore aucune demande de commande.',
      text: 'Créez une demande pour transmettre votre besoin et vos documents à FRAMATEX.',
      action: `<a class="btn btn-primary" href="#/demandes/nouvelle">${icon('plus')}Créer ma première demande</a>`,
    });
    return;
  }
  body.innerHTML = `<div class="table-card">
      <div class="req-head" aria-hidden="true"><span>Demande</span><span>Réf. client</span><span>Quantité</span><span>Date souhaitée</span><span>Créée le</span><span>Statut</span><span></span></div>
      <ul class="req-list">${items.map(r => `
        <li><a class="req-row" href="#/demandes/${encodeURIComponent(r.id)}">
          <span class="req-main"><span class="req-number">${esc(r.request_number)}</span><span class="req-article">${esc(r.article)}</span></span>
          <span class="req-cell" data-label="Réf. client">${esc(r.reference_client || '—')}</span>
          <span class="req-cell" data-label="Quantité">${fmtQty(r.quantite)}</span>
          <span class="req-cell" data-label="Date souhaitée">${fmtDate(r.date_souhaitee)}</span>
          <span class="req-cell" data-label="Créée le">${fmtDate(r.created_at)}</span>
          <span class="req-status">${statusBadge(r.status)}</span>
          ${icon('arrow', 'ico req-chevron')}
        </a></li>`).join('')}
      </ul></div>`;
}

// --------------------------------------------------------------------------
// Dépôt de fichiers (zone réutilisable)
// --------------------------------------------------------------------------
function uploaderHtml(id, { multiple = true, title = 'Déposer des documents' } = {}) {
  return `<div class="uploader" data-uploader="${id}">
    <label class="dropzone" for="${id}">
      <span class="dropzone-ico" aria-hidden="true">${icon('upload')}</span>
      <span class="dropzone-title">${esc(title)}</span>
      <span class="dropzone-text">Glissez vos fichiers ici ou <span class="dropzone-link">choisissez un fichier</span></span>
      <span class="dropzone-meta">${esc(UPLOAD.label)} · ${esc(UPLOAD.sizeLabel)} maximum par fichier</span>
    </label>
    <input class="visually-hidden" type="file" id="${id}" ${multiple ? 'multiple' : ''} accept="${UPLOAD.extensions.join(',')}" aria-describedby="${id}-status" />
    <p class="field-error" id="${id}-status" role="alert"></p>
    <ul class="file-list" aria-live="polite"></ul>
  </div>`;
}

function validateFile(file) {
  const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : '';
  if (!UPLOAD.extensions.includes(ext)) return messageFor({ code: 'unsupported_type' });
  if (file.size > UPLOAD.maxBytes) return messageFor({ code: 'too_large' });
  if (file.size === 0) return 'Ce fichier est vide.';
  return '';
}

function bindUploader(root, id) {
  const wrap = root.querySelector(`[data-uploader="${id}"]`);
  const input = wrap.querySelector('input[type=file]');
  const zone = wrap.querySelector('.dropzone');
  const list = wrap.querySelector('.file-list');
  const status = wrap.querySelector(`#${id}-status`);
  let files = [];

  const draw = () => {
    list.innerHTML = files.map((f, i) => `<li class="file-item" data-i="${i}">
      <span class="file-ico" aria-hidden="true">${icon('file')}</span>
      <span class="file-body"><span class="file-name">${esc(f.file.name)}</span><span class="file-meta">${fmtSize(f.file.size)}${f.state === 'done' ? ' · Déposé' : f.state === 'error' ? ` · ${esc(f.error)}` : ''}</span>
        ${f.state === 'uploading' ? `<span class="progress" role="progressbar" aria-label="Envoi de ${esc(f.file.name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(f.progress * 100)}"><span style="width:${Math.round(f.progress * 100)}%"></span></span>` : ''}
      </span>
      ${f.state === 'ready' ? `<button type="button" class="icon-btn" data-remove="${i}" aria-label="Retirer ${esc(f.file.name)}">${icon('x')}</button>` : f.state === 'done' ? `<span class="file-ok" aria-hidden="true">${icon('check')}</span>` : ''}
    </li>`).join('');
    list.querySelectorAll('[data-remove]').forEach(b => b.addEventListener('click', () => { files.splice(+b.dataset.remove, 1); draw(); input.focus(); }));
  };

  const add = fileList => {
    const rejected = [];
    if (!input.multiple) files = [];
    for (const file of input.multiple ? fileList : Array.from(fileList).slice(0, 1)) {
      const err = validateFile(file);
      if (err) rejected.push(`${file.name} : ${err}`);
      else files.push({ file, state: 'ready', progress: 0 });
    }
    status.textContent = rejected.join(' ');
    draw();
  };

  input.addEventListener('change', () => { add(input.files); input.value = ''; });
  ['dragenter', 'dragover'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.remove('is-over'); }));
  zone.addEventListener('drop', e => add(e.dataTransfer.files));

  return {
    pending: () => files.filter(f => f.state === 'ready'),
    clear: () => { files = []; status.textContent = ''; draw(); },
    async uploadAll(requestId, { requestedDocument = false } = {}) {
      let failures = 0;
      for (const f of files.filter(x => x.state === 'ready')) {
        f.state = 'uploading'; draw();
        try {
          const upload = requestedDocument ? source.uploadRequestedDocument : source.uploadDocument;
          await upload(requestId, f.file, { title: f.file.name, onProgress: p => { f.progress = p; draw(); } });
          f.state = 'done';
        } catch (err) {
          if (['unauthenticated', 'pending', 'suspended'].includes(err.code)) throw err;
          f.state = 'error'; f.error = messageFor(err); failures++;
        }
        draw();
      }
      return failures;
    },
  };
}

// --------------------------------------------------------------------------
// G. Nouvelle demande
// --------------------------------------------------------------------------
function viewNewRequest() {
  const today = new Date().toISOString().slice(0, 10);
  mountShell('new', `${pageHead({
    title: 'Nouvelle demande', lead: 'Décrivez votre besoin ; vous pourrez compléter les documents ensuite.',
    back: `<a class="back-link" href="#/demandes">${icon('back')}Mes demandes</a>`,
  })}
  <div class="notice">${icon('info')}<p>Cette étape crée une <strong>demande de commande</strong>. Cette demande ne constitue pas encore une commande officielle FRAMATEX / ORLI.</p></div>
  <form class="form card form-card" id="request-form" novalidate>
    <div class="form-alert" role="alert" hidden></div>
    <fieldset class="form-section">
      <legend>Article</legend>
      <div class="grid-2">
        ${field({ id: 'rq-article', label: 'Modèle / article', required: true, attrs: 'maxlength="180"' })}
        ${field({ id: 'rq-ref', label: 'Votre référence', help: 'Référence interne à votre entreprise, si vous en avez une.', attrs: 'maxlength="100"' })}
      </div>
    </fieldset>
    <fieldset class="form-section">
      <legend>Quantité et délai</legend>
      <div class="grid-2">
        ${field({ id: 'rq-qty', label: 'Quantité souhaitée', type: 'number', required: true, attrs: 'min="1" step="1" inputmode="numeric"', help: 'En nombre de pièces.' })}
        ${field({ id: 'rq-date', label: 'Date souhaitée', type: 'date', required: true, attrs: `min="${today}"` })}
      </div>
    </fieldset>
    <fieldset class="form-section">
      <legend>Précisions</legend>
      ${field({ id: 'rq-comment', label: 'Commentaire', rows: 4, attrs: 'maxlength="4000"', help: 'Coloris, tailles, contraintes particulières…' })}
    </fieldset>
    <fieldset class="form-section">
      <legend>Documents</legend>
      ${uploaderHtml('rq-files', { title: 'Joindre des documents (facultatif)' })}
    </fieldset>
    <div class="form-actions">
      <a class="btn btn-secondary" href="#/demandes">Annuler</a>
      <button class="btn btn-secondary" type="submit" data-status="draft">Enregistrer en brouillon</button>
      <button class="btn btn-primary" type="submit">Envoyer la demande</button>
    </div>
  </form>`);

  const form = app.querySelector('#request-form');
  const uploader = bindUploader(form, 'rq-files');
  liveClear(form);
  form.addEventListener('submit', async e => {
    e.preventDefault();
    clearErrors(form);
    const article = form['rq-article'].value.trim();
    const qtyRaw = form['rq-qty'].value.trim();
    const qty = Number(qtyRaw);
    const date = form['rq-date'].value;
    const errors = {};
    if (!article) errors['rq-article'] = 'Indiquez le modèle ou l’article.';
    if (!qtyRaw) errors['rq-qty'] = 'Indiquez une quantité.';
    else if (!Number.isInteger(qty) || qty < 1 || qty > 10000000) errors['rq-qty'] = 'La quantité doit être un nombre entier positif.';
    if (!date) errors['rq-date'] = 'Indiquez la date souhaitée.';
    else if (date < today) errors['rq-date'] = 'La date souhaitée ne peut pas être dans le passé.';
    Object.entries(errors).forEach(([id, msg]) => setFieldError(form, id, msg));
    if (Object.keys(errors).length) { form.querySelector('[aria-invalid="true"]')?.focus(); return; }

    const btn = e.submitter || form.querySelector('[type="submit"]');
    setLoading(btn, true, 'Envoi de la demande…');
    try {
      const status = e.submitter?.dataset.status === 'draft' ? 'draft' : 'submitted';
      const created = await source.createOrderRequest({ article, quantite: qty, date_souhaitee: date, reference_client: form['rq-ref'].value.trim(), commentaire: form['rq-comment'].value.trim(), status });
      let failures = 0;
      if (uploader.pending().length) { setLoading(btn, true, 'Envoi des documents…'); failures = await uploader.uploadAll(created.id); }
      go(`/demandes/${encodeURIComponent(created.id)}`);
      toast(failures ? `Demande ${created.request_number} créée. ${failures} document(s) n’ont pas pu être déposés.` : status === 'draft' ? `Brouillon ${created.request_number} enregistré.` : `Demande ${created.request_number} envoyée à FRAMATEX.`, failures ? 'warn' : 'success');
    } catch (err) {
      if (err.code === 'unauthenticated') { handleScreenError(err, form); return; }
      const ids = { article: 'rq-article', quantite: 'rq-qty', date_souhaitee: 'rq-date', reference_client: 'rq-ref', commentaire: 'rq-comment' };
      if (err.fields) Object.keys(err.fields).forEach(key => ids[key] && setFieldError(form, ids[key], 'Valeur invalide.'));
      showFormAlert(form, messageFor(err));
      setLoading(btn, false);
    }
  });
}

// --------------------------------------------------------------------------
// H. Détail d'une demande
// --------------------------------------------------------------------------
// Une ligne par document (titre), avec sa dernière version ; les versions précédentes restent sur le serveur.
function documentRows(request) {
  return (request.documents || []).filter(d => d.versions?.length).map(d => {
    const last = d.versions[d.versions.length - 1];
    // Le serveur suffixe le titre d'une pièce demandée par « · demande <id> » (unicité) : non affiché.
    return { id: d.id, name: String(d.title || '').replace(/ · demande [0-9a-f]{8}$/, ''), file: last.original_name, version: last.number, versions: d.versions.length,
      uploadedAt: last.created_at, size: last.size, sha256: last.sha256,
      requestId: request.id, requestNumber: request.request_number, article: request.article };
  });
}

function documentsTable(docs, { withRequest = false } = {}) {
  return `<div class="doc-table${withRequest ? ' doc-table-wide' : ''}" role="table" aria-label="Documents">
    <div class="doc-row doc-head" role="row">
      <span role="columnheader">Document</span>
      ${withRequest ? '<span role="columnheader">Demande associée</span>' : ''}
      <span role="columnheader">Version</span><span role="columnheader">Déposé le</span><span role="columnheader">Taille</span><span role="columnheader"><span class="visually-hidden">Action</span></span>
    </div>
    ${docs.map(d => `<div class="doc-row" role="row">
      <span class="doc-name" role="cell"><span class="file-ico" aria-hidden="true">${icon('file')}</span><span><span class="doc-title">${esc(d.name)}</span><span class="origin">${d.versions > 1 ? `${d.versions} versions · ` : ''}<span title="Empreinte SHA-256 calculée par le serveur">SHA-256 ${esc(String(d.sha256 || '').slice(0, 10))}…</span></span></span></span>
      ${withRequest ? `<span role="cell" data-label="Demande"><a class="text-link" href="#/demandes/${encodeURIComponent(d.requestId)}">${esc(d.requestNumber)}</a><span class="doc-sub">${esc(d.article || '')}</span></span>` : ''}
      <span role="cell" data-label="Version"><span class="version">v${esc(d.version)}</span></span>
      <span role="cell" data-label="Déposé le">${fmtDate(d.uploadedAt)}</span>
      <span role="cell" data-label="Taille">${fmtSize(d.size)}</span>
      <span role="cell" class="doc-action"><button type="button" class="btn btn-secondary btn-sm" data-download data-request="${esc(d.requestId)}" data-doc="${esc(d.id)}" data-version="${esc(d.version)}" data-file="${esc(d.file)}">${icon('download')}<span>Télécharger</span><span class="visually-hidden"> ${esc(d.name)}</span></button></span>
    </div>`).join('')}
  </div>`;
}

function bindDownloads(root) {
  root.querySelectorAll('[data-download]').forEach(b => b.addEventListener('click', async () => {
    setLoading(b, true, 'Préparation…');
    try {
      await source.downloadDocument(b.dataset.request, b.dataset.doc, Number(b.dataset.version), b.dataset.file);
    } catch (err) {
      if (err.code === 'unauthenticated') { state.client = null; state.notice = messageFor(err); go('/connexion'); return; }
      toast(messageFor(err), 'warn');
    } finally { setLoading(b, false); }
  }));
}

// Pièces demandées par FRAMATEX et documents transmis, pour cette demande seulement.
async function loadRequestExchanges(r, body) {
  const asked = body.querySelector('#req-asked'), received = body.querySelector('#req-received');
  const [requests, shared] = await Promise.allSettled([source.listDocumentRequests(), source.listSharedDocuments()]);
  if (requests.status === 'fulfilled') {
    const items = requests.value.filter(item => item.order_request_id === r.id);
    asked.innerHTML = items.length ? `<ul class="exchange-list">${items.map(item => `<li>
        <div><a class="text-link" href="#/documents-demandes/${encodeURIComponent(item.id)}">${esc(item.title)}</a><span class="doc-sub">Demandé le ${fmtDate(item.requested_at)}</span></div>
        ${documentStatusBadge(item.status)}</li>`).join('')}</ul>`
      : '<p class="muted-box">Aucune pièce demandée par FRAMATEX pour cette demande.</p>';
  } else asked.innerHTML = '<p class="muted-box">Liste momentanément indisponible.</p>';
  if (shared.status === 'fulfilled') {
    const items = shared.value.filter(item => item.order_request_id === r.id);
    received.innerHTML = items.length ? `<ul class="exchange-list">${items.map(item => `<li>
        <div><strong>${esc(item.title)}</strong><span class="doc-sub">V${item.version} · ${esc(item.original_name)} · ${fmtDate(item.published_at)}</span></div>
        <button type="button" class="btn btn-secondary btn-sm" data-shared-download="${esc(item.id)}" data-file="${esc(item.original_name)}">${icon('download')}Télécharger</button></li>`).join('')}</ul>`
      : '<p class="muted-box">Aucun document transmis par FRAMATEX pour cette demande.</p>';
    received.querySelectorAll('[data-shared-download]').forEach(button => button.addEventListener('click', async () => {
      setLoading(button, true, 'Préparation…');
      try { await source.downloadSharedDocument(button.dataset.sharedDownload, button.dataset.file); }
      catch (err) { toast(messageFor(err), 'warn'); }
      finally { setLoading(button, false); }
    }));
  } else received.innerHTML = '<p class="muted-box">Liste momentanément indisponible.</p>';
}

async function viewRequestDetail({ id }) {
  mountShell('requests', `<a class="back-link" href="#/demandes">${icon('back')}Mes demandes</a><div id="detail-body">${loadingState('Chargement de la demande…')}</div>`);
  const body = app.querySelector('#detail-body');
  let r;
  try { r = await source.getOrderRequest(id); } catch (err) { handleScreenError(err, body, 'request'); return; }
  const s = REQUEST_STATUS[r.status];
  const docs = documentRows(r);
  body.innerHTML = `
    <div class="page-head detail-head">
      <p class="eyebrow">Demande ${esc(r.request_number)}</p>
      <div class="page-head-row">
        <h1 tabindex="-1">${esc(r.article)}</h1>
        <div class="page-actions">${statusBadge(r.status)}</div>
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail-main">
        <section class="card" aria-labelledby="info-title">
          <h2 class="card-title" id="info-title">Informations</h2>
          <dl class="info-grid">
            <div><dt>Numéro de demande</dt><dd>${esc(r.request_number)}</dd></div>
            <div><dt>Modèle / article</dt><dd>${esc(r.article)}</dd></div>
            <div><dt>Votre référence</dt><dd>${esc(r.reference_client || '—')}</dd></div>
            <div><dt>Quantité</dt><dd>${fmtQty(r.quantite)} pièces</dd></div>
            <div><dt>Date souhaitée</dt><dd>${fmtDate(r.date_souhaitee)}</dd></div>
            <div><dt>Créée le</dt><dd>${fmtDate(r.created_at)}</dd></div>
          </dl>
          ${r.commentaire ? `<div class="comment"><p class="comment-label">Commentaire</p><p>${esc(r.commentaire)}</p></div>` : ''}
        </section>

        <section class="card" aria-labelledby="docs-title">
          <div class="card-head">
            <h2 class="card-title" id="docs-title">Vos documents déposés</h2>
            <span class="count">${docs.length}</span>
          </div>
          <div id="docs-zone">${docs.length ? documentsTable(docs) : '<p class="muted-box">Aucun document pour le moment.</p>'}</div>
          <form class="upload-form" id="upload-form" novalidate>
            ${uploaderHtml('detail-files', { title: 'Ajouter des documents' })}
            <p class="field-help upload-hint">Un fichier portant le même nom qu’un document existant en crée une nouvelle version.</p>
            <div class="form-actions form-actions-tight"><button class="btn btn-primary" type="submit">${icon('upload')}Déposer les documents</button></div>
          </form>
        </section>

        <section class="card" aria-labelledby="exchange-title" id="request-exchanges">
          <h2 class="card-title" id="exchange-title">Échanges avec FRAMATEX</h2>
          <div class="exchange-grid">
            <div><h3 class="exchange-title">Documents demandés</h3><div id="req-asked">${loadingState()}</div></div>
            <div><h3 class="exchange-title">Documents reçus</h3><div id="req-received">${loadingState()}</div></div>
          </div>
        </section>
      </div>

      <aside class="detail-side">
        <section class="card" aria-labelledby="status-title">
          <h2 class="card-title" id="status-title">Statut</h2>
          <p class="side-status">${statusBadge(r.status)}</p>
          <p class="side-text">${esc(s?.help || '')}</p>
          ${r.status === 'draft' ? '<button class="btn btn-primary btn-sm" id="submit-draft" type="button">Envoyer le brouillon</button>' : ''}
        </section>
        <section class="card card-quiet" aria-labelledby="help-title">
          <h2 class="card-title" id="help-title">Une question ?</h2>
          <p class="side-text">Indiquez le numéro <strong>${esc(r.request_number)}</strong> dans votre message.</p>
          <a class="text-link" href="mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Demande ' + r.request_number)}">${CONTACT_EMAIL}</a>
        </section>
      </aside>
    </div>`;
  bindDownloads(body);
  loadRequestExchanges(r, body);
  body.querySelector('#submit-draft')?.addEventListener('click', async () => {
    try { await source.submitOrderRequest(r.id); go(`/demandes/${encodeURIComponent(r.id)}`); }
    catch (err) { toast(messageFor(err), 'warn'); }
  });

  const form = body.querySelector('#upload-form');
  const uploader = bindUploader(form, 'detail-files');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!uploader.pending().length) { form.querySelector('#detail-files-status').textContent = 'Choisissez au moins un fichier à déposer.'; form.querySelector('#detail-files').focus(); return; }
    const btn = form.querySelector('[type="submit"]');
    setLoading(btn, true, 'Envoi…');
    try {
      const failures = await uploader.uploadAll(r.id);
      const fresh = await source.getOrderRequest(r.id);
      const zone = body.querySelector('#docs-zone');
      const freshRows = documentRows(fresh);
      zone.innerHTML = freshRows.length ? documentsTable(freshRows) : '<p class="muted-box">Aucun document pour le moment.</p>';
      body.querySelector('.count').textContent = freshRows.length;
      bindDownloads(zone);
      toast(failures ? `${failures} document(s) n’ont pas pu être déposés.` : 'Documents déposés.', failures ? 'warn' : 'success');
      if (!failures) uploader.clear();
    } catch (err) {
      if (err.code === 'unauthenticated') { handleScreenError(err, body); return; }
      toast(messageFor(err), 'warn');
    } finally { setLoading(btn, false); }
  });
}

// --------------------------------------------------------------------------
// I. Mes documents
// --------------------------------------------------------------------------
// Aucun endpoint global côté serveur : la vue est reconstruite à partir des demandes du client.
async function loadAllDocuments() {
  const requests = await source.listOrderRequests();
  const details = await Promise.all(requests.map(r => source.getOrderRequest(r.id)));
  return details.flatMap(documentRows).sort((a, b) => String(b.uploadedAt).localeCompare(String(a.uploadedAt)));
}

async function viewDocuments() {
  mountShell('documents', `${pageHead({ title: 'Documents', lead: 'Les fichiers que vous avez déposés sur vos demandes, toutes demandes confondues.' })}${docTabs('documents')}<div id="docs-body">${loadingState('Chargement des documents…')}</div>`);
  const body = app.querySelector('#docs-body');
  let docs;
  try { docs = await loadAllDocuments(); } catch (err) { handleScreenError(err, body); return; }
  if (!docs.length) {
    body.innerHTML = emptyState({ title: 'Aucun document pour le moment.', text: 'Les documents déposés sur vos demandes apparaîtront ici.', action: `<a class="btn btn-secondary" href="#/demandes">Voir mes demandes</a>` });
    return;
  }
  body.innerHTML = `<div class="toolbar">
      <div class="search">${icon('search')}<label class="visually-hidden" for="doc-search">Rechercher un document</label><input id="doc-search" type="search" placeholder="Rechercher un document ou une demande" /></div>
      <p class="toolbar-count" aria-live="polite"></p>
    </div>
    <div class="card card-flush" id="docs-table"></div>`;
  const tableWrap = body.querySelector('#docs-table');
  const count = body.querySelector('.toolbar-count');
  const draw = q => {
    const needle = q.trim().toLowerCase();
    const list = needle ? docs.filter(d => `${d.name} ${d.file} ${d.requestNumber} ${d.article}`.toLowerCase().includes(needle)) : docs;
    count.textContent = `${list.length} document${list.length > 1 ? 's' : ''}`;
    tableWrap.innerHTML = list.length ? documentsTable(list, { withRequest: true }) : '<p class="muted-box">Aucun document ne correspond à votre recherche.</p>';
    bindDownloads(tableWrap);
  };
  body.querySelector('#doc-search').addEventListener('input', e => draw(e.target.value));
  draw('');
}

// --------------------------------------------------------------------------
// Pièces attendues et transmissions explicites de FRAMATEX (composants existants).
async function viewDocumentRequests() {
  mountShell('requested', `${pageHead({ title: 'Documents', lead: 'Les pièces que FRAMATEX vous demande, leurs versions et ses retours.' })}${docTabs('requested')}<div id="requested-body">${loadingState()}</div>`);
  const body = app.querySelector('#requested-body');
  try {
    const items = await source.listDocumentRequests();
    body.innerHTML = items.length ? items.map(item => `<section class="card">
      <div class="card-head"><h2 class="card-title"><a class="text-link" href="#/documents-demandes/${encodeURIComponent(item.id)}">${esc(item.title)}</a></h2>${documentStatusBadge(item.status)}</div>
      <p>${esc(item.description)}</p><p class="side-text">${esc(item.request_number)} · Demandé par ${esc(item.requested_by)} le ${fmtDate(item.requested_at)}</p>
      <a class="btn btn-secondary btn-sm" href="#/documents-demandes/${encodeURIComponent(item.id)}">${icon('file')}${item.status === 'requested' ? 'À déposer' : item.status === 'correction_required' ? 'Déposer une correction' : 'Consulter'}</a>
    </section>`).join('') : emptyState({ title: 'Aucun document demandé.', text: 'Les demandes de pièces de FRAMATEX apparaîtront ici.' });
  } catch (err) { handleScreenError(err, body); }
}

async function viewDocumentRequest({ id }) {
  mountShell('requested', `${pageHead({ title: 'Pièce demandée par FRAMATEX', back: `<a class="back-link" href="#/documents-demandes">${icon('back')}Documents à fournir</a>` })}<div id="requested-detail">${loadingState()}</div>`);
  const body = app.querySelector('#requested-detail');
  try {
    const item = await source.getDocumentRequest(id);
    const editable = ['requested', 'correction_required'].includes(item.status);
    const versions = item.document?.versions || [];
    const correction = item.status === 'correction_required' ? [...item.history].reverse().find(ev => ev.status === 'correction_required' && ev.message) : null;
    body.innerHTML = `${correction ? `<div class="notice notice-warn">${icon('info')}<p><strong>Correction demandée par FRAMATEX :</strong> ${esc(correction.message)}</p></div>` : ''}<section class="card"><div class="card-head"><h2 class="card-title">${esc(item.title)}</h2>${documentStatusBadge(item.status)}</div>
      <p>${esc(item.description)}</p><p class="side-text">${esc(item.request_number)} · ${esc(item.requested_by)} · ${fmtDate(item.requested_at)}</p>
      ${item.accepted_at ? `<p class="side-text">Accepté le ${fmtDate(item.accepted_at)}</p>` : ''}
      <h3>Versions déposées</h3>${versions.length ? `<ul class="file-list">${[...versions].reverse().map(v => `<li class="file-item"><span class="file-ico">${icon('file')}</span><span class="file-body"><span class="file-name">${esc(v.original_name)} · V${v.number}</span><span class="file-meta" title="SHA-256 ${esc(v.sha256)}">${fmtDate(v.created_at)} · ${fmtSize(v.size)} · SHA-256 ${esc(v.sha256.slice(0, 16))}…</span></span><button type="button" class="btn btn-secondary btn-sm" data-requested-download="${v.number}" data-file="${esc(v.original_name)}">${icon('download')}Télécharger</button></li>`).join('')}</ul>` : '<p class="muted-box">À déposer : aucune version reçue.</p>'}
      ${editable ? `<form class="upload-form" id="requested-upload-form">${uploaderHtml('requested-file', { multiple: false, title: item.status === 'correction_required' ? 'Déposer une nouvelle version corrigée' : 'Déposer le document demandé' })}<div class="form-actions"><button class="btn btn-primary" type="submit">${icon('upload')}Déposer</button></div></form>` : ''}
      </section><section class="card"><h2 class="card-title">Historique de cette pièce</h2>${item.history.map(event => `<div class="comment"><p class="comment-label">${esc(DOCUMENT_STATUS[event.status]?.label || event.status)}${event.version ? ' · V' + event.version : ''} · ${esc(event.actor)} · ${fmtDate(event.occurred_at)}</p>${event.message ? `<p>${esc(event.message)}</p>` : ''}</div>`).join('')}</section>`;
    body.querySelectorAll('[data-requested-download]').forEach(button => button.addEventListener('click', async () => {
      try { await source.downloadRequestedDocument(item.id, Number(button.dataset.requestedDownload), button.dataset.file); }
      catch (err) { toast(messageFor(err), 'warn'); }
    }));
    const form = body.querySelector('#requested-upload-form');
    if (form) {
      const uploader = bindUploader(form, 'requested-file');
      form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!uploader.pending().length) { form.querySelector('#requested-file-status').textContent = 'Choisissez un fichier à déposer.'; return; }
        const button = form.querySelector('[type=submit]'); setLoading(button, true, 'Envoi…');
        try {
          const failures = await uploader.uploadAll(item.id, { requestedDocument: true });
          if (!failures) { toast('Document déposé. FRAMATEX peut le vérifier.', 'success'); go(`/documents-demandes/${encodeURIComponent(item.id)}`); }
        } catch (err) { handleScreenError(err, body); }
        finally { setLoading(button, false); }
      });
    }
  } catch (err) { handleScreenError(err, body); }
}

async function viewSharedDocuments() {
  mountShell('shared', `${pageHead({ title: 'Documents', lead: 'Les versions que FRAMATEX a explicitement partagées avec votre entreprise.' })}${docTabs('shared')}<div id="shared-body">${loadingState()}</div>`);
  const body = app.querySelector('#shared-body');
  try {
    const items = await source.listSharedDocuments();
    body.innerHTML = items.length ? items.map(item => `<section class="card"><div class="card-head"><h2 class="card-title">${esc(item.title)}</h2><span class="version">V${item.version}</span></div>
      <p class="side-text">${esc(item.original_name)} · ${fmtSize(item.size)} · Transmis le ${fmtDate(item.published_at)}</p>
      <p class="origin" title="SHA-256 ${esc(item.sha256)}">SHA-256 ${esc(item.sha256.slice(0, 16))}…</p>
      <button type="button" class="btn btn-secondary btn-sm" data-shared-download="${esc(item.id)}" data-file="${esc(item.original_name)}">${icon('download')}Télécharger</button></section>`).join('') : emptyState({ title: 'Aucun document transmis.', text: 'Seuls les documents explicitement partagés par FRAMATEX sont visibles ici.' });
    body.querySelectorAll('[data-shared-download]').forEach(button => button.addEventListener('click', async () => {
      setLoading(button, true, 'Préparation…');
      try { await source.downloadSharedDocument(button.dataset.sharedDownload, button.dataset.file); }
      catch (err) { toast(messageFor(err), 'warn'); }
      finally { setLoading(button, false); }
    }));
  } catch (err) { handleScreenError(err, body); }
}

// J. Mon compte (lecture seule : aucune modification de profil côté backend pour l'instant)
// --------------------------------------------------------------------------
const ACCOUNT_STATUS = { active: 'Actif', pending: 'En attente de validation', suspended: 'Suspendu' }; // ClientAccount.status

async function viewAccount() {
  mountShell('account', `${pageHead({ title: 'Mon compte', lead: 'Informations de votre entreprise enregistrées chez FRAMATEX.' })}<div id="account-body">${loadingState()}</div>`);
  const body = app.querySelector('#account-body');
  let c;
  try { c = await source.getCurrentClient(); state.client = c; } catch (err) { handleScreenError(err, body); return; }
  const row = (label, value) => `<div><dt>${esc(label)}</dt><dd>${value ? esc(value) : '<span class="muted">Non renseigné</span>'}</dd></div>`;
  body.innerHTML = `
    <div class="account-grid">
      <section class="card" aria-labelledby="acc-company">
        <h2 class="card-title" id="acc-company">Entreprise</h2>
        <dl class="info-list">
          ${row('Raison sociale', c.raison_sociale)}
          ${row('Code client', c.client_code)}
          ${row('ICE / identifiant fiscal', c.identifiant_fiscal)}
          <div><dt>Statut du compte</dt><dd><span class="badge badge-${c.status === 'active' ? 'success' : c.status === 'suspended' ? 'danger' : 'warn'}"><span class="badge-dot" aria-hidden="true"></span>${esc(ACCOUNT_STATUS[c.status] || c.status || '—')}</span></dd></div>
        </dl>
      </section>
      <section class="card" aria-labelledby="acc-contact">
        <h2 class="card-title" id="acc-contact">Contact</h2>
        <dl class="info-list">
          ${row('Nom du contact', c.nom_contact)}
          ${row('Adresse email', c.email)}
          ${row('Téléphone', c.telephone)}
          ${row('Client depuis', c.created_at ? fmtDate(c.created_at) : '')}
        </dl>
      </section>
      <section class="card" aria-labelledby="acc-address">
        <h2 class="card-title" id="acc-address">Adresse</h2>
        <dl class="info-list">
          ${row('Adresse', c.adresse)}
          ${row('Pays', c.pays)}
        </dl>
      </section>
    </div>
    <div class="notice notice-quiet">${icon('info')}<p>Pour modifier ces informations, contactez FRAMATEX à <a class="text-link" href="mailto:${CONTACT_EMAIL}">${CONTACT_EMAIL}</a>.</p></div>`;
}

window.addEventListener('hashchange', render);
render();

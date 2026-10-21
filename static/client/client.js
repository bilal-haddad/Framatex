// Espace Client FRAMATEX — interface (routeur par ancre, écrans, formulaires).
// Toutes les données passent par `source` : l'API réelle quand elle sera connectée,
// sinon la source de démonstration (static/client/demo-data.js).

import * as api from './api.js';
import { DEMO_MODE, DEMO_SCENARIO, demoSource } from './demo-data.js'; // À retirer avec la démo.
import {
  icon, esc, fmtDate, fmtQty, fmtSize, statusBadge, REQUEST_STATUS, field, passwordField,
  setFieldError, clearErrors, showFormAlert, bindPasswordToggles, setLoading, toast,
  emptyState, errorState, loadingState,
} from './components/ui.js';

const source = api.API_CONNECTED ? api : demoSource;
const IS_DEMO = !api.API_CONNECTED && DEMO_MODE;

// TODO(api) : confirmer formats et taille maximale avec le backend client.
const UPLOAD = {
  maxBytes: 20 * 1024 * 1024,
  extensions: ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png'],
  label: 'PDF, DOCX, XLSX, JPG ou PNG',
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
    case 'pending': return 'Votre compte est en attente de validation par FRAMATEX.';
    case 'unauthenticated': return 'Votre session a expiré. Veuillez vous reconnecter.';
    case 'forbidden': return 'Vous n’avez pas accès à cette ressource.';
    case 'not_found': return context === 'request' ? 'Cette demande est introuvable.' : 'Élément introuvable.';
    case 'too_large': return `Le fichier dépasse la taille maximale autorisée (${UPLOAD.sizeLabel}).`;
    case 'unsupported_type': return `Format non accepté. Formats autorisés : ${UPLOAD.label}.`;
    case 'validation': return 'Certaines informations sont invalides. Vérifiez le formulaire.';
    case 'network': return 'Connexion au serveur impossible. Vérifiez votre connexion internet.';
    case 'api_not_connected': return IS_DEMO ? 'Action indisponible en démonstration.' : 'Ce service n’est pas encore disponible.';
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
  { path: '/demandes', view: viewRequests, title: 'Mes demandes', auth: true, nav: 'requests' },
  { path: '/demandes/nouvelle', view: viewNewRequest, title: 'Nouvelle demande', auth: true, nav: 'new' },
  { path: '/demandes/:id', view: viewRequestDetail, title: 'Détail de la demande', auth: true, nav: 'requests' },
  { path: '/documents', view: viewDocuments, title: 'Mes documents', auth: true, nav: 'documents' },
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
      if (err.code === 'pending') { go('/en-attente'); return; }
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
  { key: 'documents', href: '#/documents', label: 'Mes documents', icon: 'folder' },
  { key: 'account', href: '#/compte', label: 'Mon compte', icon: 'users' },
];

function identity() {
  const c = state.client || {};
  return `<div class="identity">
      <p class="identity-company">${esc(c.company || '')}</p>
      ${c.contact ? `<p class="identity-contact">${esc(c.contact)}</p>` : ''}
      ${c.code ? `<p class="identity-code">${esc(c.code)}</p>` : ''}
    </div>`;
}

function navList(active) {
  return `<ul class="nav-list">${NAV.map(n => `<li><a class="nav-link${n.key === active ? ' is-active' : ''}" href="${n.href}"${n.key === active ? ' aria-current="page"' : ''}>${icon(n.icon)}<span>${n.label}</span></a></li>`).join('')}</ul>`;
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
      if (err.code === 'pending') { go('/en-attente'); return; }
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
const PASSWORD_MIN = 12; // TODO(api) : aligner sur la règle du backend client.

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
      // TODO(api) : renommer les clés selon les champs réellement attendus par le backend.
      await source.registerClient({
        company: v('reg-company'), taxId: v('reg-taxid'), address: v('reg-address'), country: v('reg-country'),
        contact: v('reg-contact'), phone: v('reg-phone'), email: v('reg-email'), password: pw,
      });
      form.reset();
      go('/inscription/envoyee');
    } catch (err) {
      if (err.fields) Object.entries(err.fields).forEach(([id, msg]) => setFieldError(form, id, msg));
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
      'Votre compte doit maintenant être validé par FRAMATEX avant que vous puissiez accéder à votre espace client.',
      'Vous recevrez ensuite l’autorisation d’utiliser le portail.',
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

// --------------------------------------------------------------------------
// F. Mes demandes
// --------------------------------------------------------------------------
const FILTERS = [
  { key: 'all', label: 'Toutes', test: () => true },
  { key: 'open', label: 'En cours', test: r => ['draft', 'submitted', 'under_review'].includes(r.status) },
  { key: 'accepted', label: 'Acceptées', test: r => r.status === 'accepted' },
  { key: 'rejected', label: 'Refusées', test: r => r.status === 'rejected' },
];

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
  let active = 'all';
  const draw = () => {
    const f = FILTERS.find(x => x.key === active);
    const list = items.filter(f.test);
    body.innerHTML = `
      <div class="filters" role="group" aria-label="Filtrer les demandes">
        ${FILTERS.map(x => `<button type="button" class="filter${x.key === active ? ' is-active' : ''}" data-filter="${x.key}" aria-pressed="${x.key === active}">${x.label}<span class="filter-count">${items.filter(x.test).length}</span></button>`).join('')}
      </div>
      ${list.length ? `<div class="table-card">
        <div class="req-head" aria-hidden="true"><span>Demande</span><span>Réf. client</span><span>Quantité</span><span>Date souhaitée</span><span>Créée le</span><span>Statut</span><span></span></div>
        <ul class="req-list">${list.map(r => `
          <li><a class="req-row" href="#/demandes/${encodeURIComponent(r.id)}">
            <span class="req-main"><span class="req-number">${esc(r.number)}</span><span class="req-article">${esc(r.article)}</span></span>
            <span class="req-cell" data-label="Réf. client">${esc(r.clientRef || '—')}</span>
            <span class="req-cell" data-label="Quantité">${fmtQty(r.quantity)}</span>
            <span class="req-cell" data-label="Date souhaitée">${fmtDate(r.desiredDate)}</span>
            <span class="req-cell" data-label="Créée le">${fmtDate(r.createdAt)}</span>
            <span class="req-status">${statusBadge(r.status)}</span>
            ${icon('arrow', 'ico req-chevron')}
          </a></li>`).join('')}
        </ul></div>` : `<p class="muted-box">Aucune demande dans cette catégorie.</p>`}`;
    body.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { active = b.dataset.filter; draw(); body.querySelector(`[data-filter="${active}"]`).focus(); }));
  };
  draw();
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
    for (const file of fileList) {
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
    async uploadAll(requestId) {
      let failures = 0;
      for (const f of files.filter(x => x.state === 'ready')) {
        f.state = 'uploading'; draw();
        try {
          await source.uploadDocument(requestId, f.file, p => { f.progress = p; draw(); });
          f.state = 'done';
        } catch (err) {
          if (err.code === 'unauthenticated') throw err;
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
  <div class="notice">${icon('info')}<p>Cette étape crée une <strong>demande de commande</strong>. Elle ne constitue pas encore une commande officielle FRAMATEX.</p></div>
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
        ${field({ id: 'rq-date', label: 'Date souhaitée', type: 'date', attrs: `min="${today}"` })}
      </div>
    </fieldset>
    <fieldset class="form-section">
      <legend>Précisions</legend>
      ${field({ id: 'rq-comment', label: 'Commentaire', rows: 4, attrs: 'maxlength="2000"', help: 'Coloris, tailles, contraintes particulières…' })}
    </fieldset>
    <fieldset class="form-section">
      <legend>Documents</legend>
      ${uploaderHtml('rq-files', { title: 'Joindre des documents (facultatif)' })}
    </fieldset>
    <div class="form-actions">
      <a class="btn btn-secondary" href="#/demandes">Annuler</a>
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
    else if (!Number.isInteger(qty) || qty < 1) errors['rq-qty'] = 'La quantité doit être un nombre entier positif.';
    if (date && date < today) errors['rq-date'] = 'La date souhaitée ne peut pas être dans le passé.';
    Object.entries(errors).forEach(([id, msg]) => setFieldError(form, id, msg));
    if (Object.keys(errors).length) { form.querySelector('[aria-invalid="true"]')?.focus(); return; }

    const btn = form.querySelector('[type="submit"]');
    setLoading(btn, true, 'Envoi de la demande…');
    try {
      // TODO(api) : renommer les clés selon les champs réellement attendus par le backend.
      const created = await source.createOrderRequest({ article, clientRef: form['rq-ref'].value.trim(), quantity: qty, desiredDate: date, comment: form['rq-comment'].value.trim() });
      let failures = 0;
      if (uploader.pending().length) { setLoading(btn, true, 'Envoi des documents…'); failures = await uploader.uploadAll(created.id); }
      go(`/demandes/${encodeURIComponent(created.id)}`);
      toast(failures ? `Demande ${created.number} créée. ${failures} document(s) n’ont pas pu être déposés.` : `Demande ${created.number} envoyée à FRAMATEX.`, failures ? 'warn' : 'success');
    } catch (err) {
      if (err.code === 'unauthenticated') { handleScreenError(err, form); return; }
      if (err.fields) Object.entries(err.fields).forEach(([id, msg]) => setFieldError(form, id, msg));
      showFormAlert(form, messageFor(err));
      setLoading(btn, false);
    }
  });
}

// --------------------------------------------------------------------------
// H. Détail d'une demande
// --------------------------------------------------------------------------
function originTag(origin) {
  return origin === 'framatex'
    ? '<span class="origin origin-framatex">Transmis par FRAMATEX</span>'
    : '<span class="origin">Déposé par vous</span>';
}

function documentsTable(docs, { withRequest = false } = {}) {
  return `<div class="doc-table${withRequest ? ' doc-table-wide' : ''}" role="table" aria-label="Documents">
    <div class="doc-row doc-head" role="row">
      <span role="columnheader">Document</span>
      ${withRequest ? '<span role="columnheader">Demande associée</span>' : ''}
      <span role="columnheader">Version</span><span role="columnheader">Déposé le</span><span role="columnheader">Taille</span><span role="columnheader"><span class="visually-hidden">Action</span></span>
    </div>
    ${docs.map(d => `<div class="doc-row" role="row">
      <span class="doc-name" role="cell"><span class="file-ico" aria-hidden="true">${icon('file')}</span><span><span class="doc-title">${esc(d.name)}</span>${originTag(d.origin)}</span></span>
      ${withRequest ? `<span role="cell" data-label="Demande"><a class="text-link" href="#/demandes/${encodeURIComponent(d.requestId)}">${esc(d.requestNumber)}</a><span class="doc-sub">${esc(d.article || '')}</span></span>` : ''}
      <span role="cell" data-label="Version"><span class="version">v${esc(d.version)}</span></span>
      <span role="cell" data-label="Déposé le">${fmtDate(d.uploadedAt)}</span>
      <span role="cell" data-label="Taille">${fmtSize(d.size)}</span>
      <span role="cell" class="doc-action"><button type="button" class="btn btn-secondary btn-sm" data-download data-request="${esc(d.requestId)}" data-doc="${esc(d.id)}" data-version="${esc(d.version)}">${icon('download')}<span>Télécharger</span><span class="visually-hidden"> ${esc(d.name)}</span></button></span>
    </div>`).join('')}
  </div>`;
}

function bindDownloads(root) {
  root.querySelectorAll('[data-download]').forEach(b => b.addEventListener('click', async () => {
    setLoading(b, true, 'Préparation…');
    try {
      await source.downloadDocument(b.dataset.request, b.dataset.doc, Number(b.dataset.version));
    } catch (err) {
      if (err.code === 'unauthenticated') { state.client = null; state.notice = messageFor(err); go('/connexion'); return; }
      toast(err.code === 'api_not_connected' && IS_DEMO ? 'Téléchargement indisponible en démonstration : aucun fichier réel.' : messageFor(err), 'warn');
    } finally { setLoading(b, false); }
  }));
}

async function viewRequestDetail({ id }) {
  mountShell('requests', `<a class="back-link" href="#/demandes">${icon('back')}Mes demandes</a><div id="detail-body">${loadingState('Chargement de la demande…')}</div>`);
  const body = app.querySelector('#detail-body');
  let r;
  try { r = await source.getOrderRequest(id); } catch (err) { handleScreenError(err, body, 'request'); return; }
  const s = REQUEST_STATUS[r.status];
  const docs = r.documents.map(d => ({ ...d, requestId: r.id }));
  body.innerHTML = `
    <div class="page-head detail-head">
      <p class="eyebrow">Demande ${esc(r.number)}</p>
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
            <div><dt>Numéro de demande</dt><dd>${esc(r.number)}</dd></div>
            <div><dt>Modèle / article</dt><dd>${esc(r.article)}</dd></div>
            <div><dt>Votre référence</dt><dd>${esc(r.clientRef || '—')}</dd></div>
            <div><dt>Quantité</dt><dd>${fmtQty(r.quantity)} pièces</dd></div>
            <div><dt>Date souhaitée</dt><dd>${fmtDate(r.desiredDate)}</dd></div>
            <div><dt>Créée le</dt><dd>${fmtDate(r.createdAt)}</dd></div>
          </dl>
          ${r.comment ? `<div class="comment"><p class="comment-label">Commentaire</p><p>${esc(r.comment)}</p></div>` : ''}
        </section>

        <section class="card" aria-labelledby="docs-title">
          <div class="card-head">
            <h2 class="card-title" id="docs-title">Documents liés à cette demande</h2>
            <span class="count">${docs.length}</span>
          </div>
          <div id="docs-zone">${docs.length ? documentsTable(docs) : '<p class="muted-box">Aucun document pour le moment.</p>'}</div>
          <form class="upload-form" id="upload-form" novalidate>
            ${uploaderHtml('detail-files', { title: 'Ajouter des documents' })}
            <div class="form-actions form-actions-tight"><button class="btn btn-primary" type="submit">${icon('upload')}Déposer les documents</button></div>
          </form>
        </section>
      </div>

      <aside class="detail-side">
        <section class="card" aria-labelledby="status-title">
          <h2 class="card-title" id="status-title">Statut</h2>
          <p class="side-status">${statusBadge(r.status)}</p>
          <p class="side-text">${esc(s?.help || '')}</p>
        </section>
        <section class="card card-quiet" aria-labelledby="help-title">
          <h2 class="card-title" id="help-title">Une question ?</h2>
          <p class="side-text">Indiquez le numéro <strong>${esc(r.number)}</strong> dans votre message.</p>
          <a class="text-link" href="mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Demande ' + r.number)}">${CONTACT_EMAIL}</a>
        </section>
      </aside>
    </div>`;
  bindDownloads(body);

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
      zone.innerHTML = documentsTable(fresh.documents.map(d => ({ ...d, requestId: fresh.id })));
      body.querySelector('.count').textContent = fresh.documents.length;
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
async function loadAllDocuments() {
  try { return await source.listDocuments(); } catch (err) {
    if (err.code !== 'api_not_connected') throw err;
    // Pas d'endpoint global : vue reconstruite à partir des demandes du client.
    const requests = await source.listOrderRequests();
    const details = await Promise.all(requests.map(r => source.getOrderRequest(r.id)));
    return details.flatMap(r => r.documents.map(d => ({ ...d, requestId: r.id, requestNumber: r.number, article: r.article })))
      .sort((a, b) => String(b.uploadedAt).localeCompare(String(a.uploadedAt)));
  }
}

async function viewDocuments() {
  mountShell('documents', `${pageHead({ title: 'Mes documents', lead: 'Documents déposés par vous ou transmis par FRAMATEX, toutes demandes confondues.' })}<div id="docs-body">${loadingState('Chargement des documents…')}</div>`);
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
    const list = needle ? docs.filter(d => `${d.name} ${d.requestNumber} ${d.article}`.toLowerCase().includes(needle)) : docs;
    count.textContent = `${list.length} document${list.length > 1 ? 's' : ''}`;
    tableWrap.innerHTML = list.length ? documentsTable(list, { withRequest: true }) : '<p class="muted-box">Aucun document ne correspond à votre recherche.</p>';
    bindDownloads(tableWrap);
  };
  body.querySelector('#doc-search').addEventListener('input', e => draw(e.target.value));
  draw('');
}

// --------------------------------------------------------------------------
// J. Mon compte (lecture seule : aucune modification de profil côté backend pour l'instant)
// --------------------------------------------------------------------------
const ACCOUNT_STATUS = { active: 'Actif', pending: 'En attente de validation', suspended: 'Suspendu' }; // TODO(api) : aligner.

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
          ${row('Raison sociale', c.company)}
          ${row('Code client', c.code)}
          ${row('ICE / identifiant fiscal', c.taxId)}
          <div><dt>Statut du compte</dt><dd><span class="badge badge-${c.status === 'active' ? 'success' : c.status === 'suspended' ? 'danger' : 'warn'}"><span class="badge-dot" aria-hidden="true"></span>${esc(ACCOUNT_STATUS[c.status] || c.status || '—')}</span></dd></div>
        </dl>
      </section>
      <section class="card" aria-labelledby="acc-contact">
        <h2 class="card-title" id="acc-contact">Contact</h2>
        <dl class="info-list">
          ${row('Nom du contact', c.contact)}
          ${row('Adresse email', c.email)}
          ${row('Téléphone', c.phone)}
        </dl>
      </section>
      <section class="card" aria-labelledby="acc-address">
        <h2 class="card-title" id="acc-address">Adresse</h2>
        <dl class="info-list">
          ${row('Adresse', c.address)}
          ${row('Pays', c.country)}
        </dl>
      </section>
    </div>
    <div class="notice notice-quiet">${icon('info')}<p>Pour modifier ces informations, contactez FRAMATEX à <a class="text-link" href="mailto:${CONTACT_EMAIL}">${CONTACT_EMAIL}</a>.</p></div>`;
}

// --------------------------------------------------------------------------
// Bandeau de démonstration (supprimé automatiquement quand l'API est connectée)
// --------------------------------------------------------------------------
function demoBanner() {
  if (!IS_DEMO) return;
  const el = document.getElementById('demo-banner');
  const scenarios = [['standard', 'Standard'], ['vide', 'Aucune demande'], ['attente', 'Compte en attente'], ['refus', 'Identifiants refusés']];
  el.hidden = false;
  el.innerHTML = `<p><strong>Démonstration de l’interface</strong> — données fictives, rien n’est envoyé ni enregistré.</p>
    <p class="demo-scenarios"><span>Scénario :</span>${scenarios.map(([k, l]) => `<a href="?demo=${k}#/connexion"${DEMO_SCENARIO === k ? ' aria-current="true"' : ''}>${l}</a>`).join('')}</p>`;
}

demoBanner();
window.addEventListener('hashchange', render);
render();

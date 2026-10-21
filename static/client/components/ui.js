// Espace Client FRAMATEX — composants d'interface partagés (sans dépendance).

// Pictogrammes repris à l'identique du jeu d'icônes de l'application interne (static/app.js).
const ICON = {
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 17v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  layers: '<rect x="4" y="5" width="16" height="14" rx="3"/><path d="M8 9h8M8 13h5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 1 1 8 0v3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  out: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
  arrow: '<path d="m9 18 6-6-6-6"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  check: '<path d="m4 12 5 5L20 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
};

export function icon(name, cls = 'ico') {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON[name] || ICON.file}</svg>`;
}

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const DATE_FMT = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
export function fmtDate(value) {
  if (!value) return '—';
  // Date seule (AAAA-MM-JJ) : interprétée en date locale pour éviter tout décalage de fuseau.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : DATE_FMT.format(d);
}
export function fmtQty(value) {
  return value == null || value === '' ? '—' : new Intl.NumberFormat('fr-FR').format(value);
}
export function fmtSize(bytes) {
  if (bytes == null) return '—';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} Mo`;
  return `${Math.max(1, Math.ceil(bytes / 1024))} Ko`;
}

// Statuts de demande : valeurs de ClientOrderRequest.status (OrderPayload : draft | submitted).
export const REQUEST_STATUS = {
  draft: { label: 'Brouillon', tone: 'neutral', help: 'La demande est enregistrée mais n’a pas été soumise à FRAMATEX.' },
  submitted: { label: 'Envoyée', tone: 'info', help: 'FRAMATEX a reçu votre demande et l’examinera avant toute commande officielle.' },
};
export function statusBadge(status) {
  const s = REQUEST_STATUS[status] || { label: status || 'Inconnu', tone: 'neutral' };
  return `<span class="badge badge-${s.tone}"><span class="badge-dot" aria-hidden="true"></span>${esc(s.label)}</span>`;
}

// Champ de formulaire avec label réel, aide et message d'erreur associés (aria-describedby).
export function field({ id, label, type = 'text', required = false, autocomplete = '', help = '', attrs = '', value = '', options = null, rows = 0 }) {
  const describedBy = [help ? `${id}-help` : '', `${id}-error`].filter(Boolean).join(' ');
  const req = required ? ' required aria-required="true"' : '';
  const ac = autocomplete ? ` autocomplete="${autocomplete}"` : '';
  let control;
  if (options) {
    control = `<select id="${id}" name="${id}"${req} aria-describedby="${describedBy}" ${attrs}>${options.map(o => `<option value="${esc(o.value)}"${o.value === value ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  } else if (rows) {
    control = `<textarea id="${id}" name="${id}" rows="${rows}"${req} aria-describedby="${describedBy}" ${attrs}>${esc(value)}</textarea>`;
  } else {
    control = `<input id="${id}" name="${id}" type="${type}"${req}${ac} aria-describedby="${describedBy}" value="${esc(value)}" ${attrs} />`;
  }
  return `<div class="field" data-field="${id}">
    <label for="${id}">${esc(label)}${required ? ' <span class="req" aria-hidden="true">*</span>' : ' <span class="opt">(facultatif)</span>'}</label>
    ${control}
    ${help ? `<p class="field-help" id="${id}-help">${esc(help)}</p>` : ''}
    <p class="field-error" id="${id}-error" role="alert"></p>
  </div>`;
}

export function passwordField({ id, label, autocomplete, help = '' }) {
  const describedBy = [help ? `${id}-help` : '', `${id}-error`].filter(Boolean).join(' ');
  return `<div class="field" data-field="${id}">
    <label for="${id}">${esc(label)} <span class="req" aria-hidden="true">*</span></label>
    <div class="password-wrap">
      <input id="${id}" name="${id}" type="password" required aria-required="true" autocomplete="${autocomplete}" aria-describedby="${describedBy}" />
      <button type="button" class="password-toggle" data-toggle-password="${id}" aria-controls="${id}" aria-pressed="false">Afficher</button>
    </div>
    ${help ? `<p class="field-help" id="${id}-help">${esc(help)}</p>` : ''}
    <p class="field-error" id="${id}-error" role="alert"></p>
  </div>`;
}

export function setFieldError(form, id, message) {
  const wrap = form.querySelector(`[data-field="${id}"]`);
  if (!wrap) return;
  const input = wrap.querySelector('input, select, textarea');
  wrap.classList.toggle('has-error', Boolean(message));
  if (input) input.setAttribute('aria-invalid', message ? 'true' : 'false');
  const err = wrap.querySelector('.field-error');
  if (err) err.textContent = message || '';
}

export function clearErrors(form) {
  form.querySelectorAll('[data-field]').forEach(w => setFieldError(form, w.dataset.field, ''));
  const alert = form.querySelector('.form-alert');
  if (alert) { alert.hidden = true; alert.textContent = ''; }
}

export function showFormAlert(form, message) {
  const alert = form.querySelector('.form-alert');
  if (!alert) return;
  alert.hidden = false;
  alert.innerHTML = `${icon('info')}<span>${esc(message)}</span>`;
}

export function bindPasswordToggles(root) {
  root.querySelectorAll('[data-toggle-password]').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = root.querySelector(`#${btn.dataset.togglePassword}`);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Masquer' : 'Afficher';
      btn.setAttribute('aria-pressed', String(show));
    });
  });
}

export function setLoading(button, loading, label) {
  if (!button) return;
  if (loading) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span>${esc(label || 'Chargement…')}`;
  } else {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

let toastTimer;
export function toast(message, tone = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.className = `toast toast-${tone} is-visible`;
  el.innerHTML = `${icon(tone === 'success' ? 'check' : 'info')}<span>${esc(message)}</span>`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('is-visible'), 4200);
}

export function emptyState({ title, text, action = '' }) {
  return `<div class="empty">
    <div class="empty-mark" aria-hidden="true">${icon('folder')}</div>
    <h2>${esc(title)}</h2>
    ${text ? `<p>${esc(text)}</p>` : ''}
    ${action}
  </div>`;
}

export function errorState({ title = 'Une erreur est survenue', text = 'Veuillez réessayer dans quelques instants.', action = '' } = {}) {
  return `<div class="empty empty-error" role="alert">
    <div class="empty-mark" aria-hidden="true">${icon('info')}</div>
    <h2>${esc(title)}</h2>
    <p>${esc(text)}</p>
    ${action}
  </div>`;
}

export function loadingState(label = 'Chargement…') {
  return `<div class="loading" role="status" aria-live="polite"><span class="spinner spinner-dark" aria-hidden="true"></span>${esc(label)}</div>`;
}

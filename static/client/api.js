// Espace Client FRAMATEX — accès à l'API client (app/client_routes.py).
//
// Sécurité :
//   - la session est portée par le cookie HttpOnly `framat_client_session` posé par le serveur
//     (SameSite=Strict, chemin /api/client) : aucun jeton n'est lu, stocké ni placé dans une URL ;
//   - en-tête X-Framatex-Request: 1 sur toutes les requêtes d'écriture (exigé par le serveur) ;
//   - le navigateur n'envoie jamais de client_id : le serveur le déduit de la session ;
//   - les fichiers ne sont récupérés que par l'endpoint de téléchargement.

export const API_CONNECTED = true;
const BASE = '/api/client';

// Erreur normalisée consommée par l'interface (client.js traduit `code` en message).
// Codes : unauthenticated, invalid_credentials, inactive, forbidden, not_found, conflict,
// too_large, rejected (refus métier explicite du serveur), validation, rate_limited, network, server.
export class ClientApiError extends Error {
  constructor(code, { status = 0, fields = null, message = '' } = {}) {
    super(message || code);
    this.name = 'ClientApiError';
    this.code = code;
    this.status = status;
    this.fields = fields;
    this.detail = message;
  }
}

// Champs de validation Pydantic : [{loc: ['body', 'email'], msg: '…'}] → { email: '…' }.
function validationFields(detail) {
  if (!Array.isArray(detail)) return null;
  const fields = {};
  for (const item of detail) {
    const key = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null;
    if (typeof key === 'string' && !fields[key]) fields[key] = item.msg || 'Valeur invalide';
  }
  return fields;
}

function toError(status, data, context) {
  const detail = data?.detail;
  const text = typeof detail === 'string' ? detail : '';
  if (status === 401) return new ClientApiError(context === 'login' ? 'invalid_credentials' : 'unauthenticated', { status });
  if (status === 403) return new ClientApiError(context === 'login' || context === 'session' ? 'inactive' : 'forbidden', { status });
  if (status === 404) return new ClientApiError('not_found', { status });
  if (status === 409) return new ClientApiError('conflict', { status, message: text });
  if (status === 413) return new ClientApiError('too_large', { status });
  if (status === 429) return new ClientApiError('rate_limited', { status });
  if (status === 422) return text ? new ClientApiError('rejected', { status, message: text })
    : new ClientApiError('validation', { status, fields: validationFields(detail) });
  return new ClientApiError('server', { status });
}

async function call(path, { method = 'GET', json, context = '' } = {}) {
  const headers = {};
  if (method !== 'GET') headers['X-Framatex-Request'] = '1';
  if (json !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, credentials: 'same-origin', body: json !== undefined ? JSON.stringify(json) : undefined });
  } catch {
    throw new ClientApiError('network');
  }
  let data = null;
  try { data = await res.json(); } catch { /* corps vide ou non JSON */ }
  if (!res.ok) throw toError(res.status, data, context);
  return data;
}

// ---- Compte ---------------------------------------------------------------
/** POST /api/client/register — le compte est créé au statut « pending ». */
export function registerClient(payload) {
  const { raison_sociale, nom_contact, email, telephone, adresse, pays, identifiant_fiscal, password } = payload;
  return call('/register', { method: 'POST', json: { raison_sociale, nom_contact, email, telephone, adresse, pays, identifiant_fiscal: identifiant_fiscal || null, password } });
}
/** POST /api/client/login — le serveur pose le cookie HttpOnly. 403 = compte non actif. */
export function loginClient({ email, password }) {
  return call('/login', { method: 'POST', json: { email, password }, context: 'login' });
}
/** POST /api/client/logout — le serveur révoque la session et retire le cookie. */
export function logoutClient() { return call('/logout', { method: 'POST' }); }
/** GET /api/client/me */
export function getCurrentClient() { return call('/me', { context: 'session' }); }

// ---- Demandes de commande --------------------------------------------------
/** GET /api/client/order-requests — demandes du client connecté uniquement. */
export function listOrderRequests() { return call('/order-requests'); }
/** POST /api/client/order-requests */
export function createOrderRequest({ article, quantite, date_souhaitee, reference_client, commentaire, status }) {
  return call('/order-requests', { method: 'POST', json: { article, quantite, date_souhaitee, reference_client: reference_client || null, commentaire: commentaire || null, status } });
}
/** GET /api/client/order-requests/{id} — détail avec documents et versions. */
export function getOrderRequest(requestId) { return call(`/order-requests/${encodeURIComponent(requestId)}`); }

// ---- Documents -------------------------------------------------------------
/**
 * POST /api/client/order-requests/{id}/documents (multipart : title + file).
 * Un titre déjà présent sur la demande crée une nouvelle version (versioning et SHA-256 côté serveur).
 * XHR plutôt que fetch pour suivre la progression de l'envoi.
 */
export function uploadDocument(requestId, file, { title, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('title', title || file.name);
    form.append('file', file);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/order-requests/${encodeURIComponent(requestId)}/documents`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-Framatex-Request', '1');
    xhr.responseType = 'json';
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? resolve(xhr.response) : reject(toError(xhr.status, xhr.response, 'upload'));
    xhr.onerror = () => reject(new ClientApiError('network'));
    xhr.send(form);
  });
}

/** GET …/documents/{documentId}/versions/{number}/download — fichier remis au navigateur. */
export async function downloadDocument(requestId, documentId, version, filename) {
  let res;
  try {
    res = await fetch(`${BASE}/order-requests/${encodeURIComponent(requestId)}/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(version)}/download`, { credentials: 'same-origin' });
  } catch {
    throw new ClientApiError('network');
  }
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch { /* corps non JSON */ }
    throw toError(res.status, data, 'download');
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || 'document';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Pas d'endpoint global des documents : la vue « Mes documents » est reconstruite côté interface
// à partir des demandes du client (voir client.js).

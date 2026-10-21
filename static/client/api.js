// Espace Client FRAMATEX — couche d'accès à l'API client.
//
// ÉTAT : NON CONNECTÉE. Le backend Espace Client n'est pas encore disponible sur GitHub.
// Aucune URL ni aucun champ n'est supposé ici : chaque fonction lève une erreur
// « api_not_connected » tant qu'elle n'est pas implémentée.
//
// Pour connecter le vrai backend :
//   1. implémenter chaque fonction TODO avec les endpoints et champs réels ;
//   2. passer API_CONNECTED à true ;
//   3. supprimer static/client/demo-data.js et son import dans client.js.
//
// Règles de sécurité à respecter lors de l'intégration :
//   - session portée par le cookie HttpOnly posé par le serveur (credentials: 'same-origin') ;
//   - aucun jeton ni mot de passe en localStorage/sessionStorage, ni dans l'URL ;
//   - en-tête X-Framatex-Request: 1 sur les requêtes POST/PUT/PATCH/DELETE (exigé par le serveur) ;
//   - ne jamais transmettre de client_id choisi côté navigateur : le serveur le déduit de la session ;
//   - téléchargements uniquement via l'endpoint de téléchargement, jamais par chemin de fichier.

export const API_CONNECTED = false;

// Erreur normalisée consommée par l'interface (client.js traduit `code` en message utilisateur).
// Codes prévus : unauthenticated (401), forbidden (403), not_found (404), pending (compte en attente),
// invalid_credentials, validation (avec `fields`), too_large, unsupported_type, network, server,
// api_not_connected.
export class ClientApiError extends Error {
  constructor(code, { status = 0, fields = null, message = '' } = {}) {
    super(message || code);
    this.name = 'ClientApiError';
    this.code = code;
    this.status = status;
    this.fields = fields;
  }
}

// Requête générique prête à l'emploi (cookie de session + en-tête anti-CSRF du serveur).
// À utiliser par les fonctions ci-dessous une fois les endpoints connus.
export async function request(url, { method = 'GET', json, body, headers = {} } = {}) {
  const h = { ...headers };
  if (method !== 'GET' && method !== 'HEAD') h['X-Framatex-Request'] = '1';
  if (json !== undefined) h['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(url, { method, headers: h, body: json !== undefined ? JSON.stringify(json) : body, credentials: 'same-origin' });
  } catch {
    throw new ClientApiError('network');
  }
  if (res.ok) return res.headers.get('content-type')?.includes('application/json') ? res.json() : res;
  // TODO(api) : affiner ce mapping avec les codes/erreurs réellement renvoyés (dont « compte en attente »).
  const byStatus = { 401: 'unauthenticated', 403: 'forbidden', 404: 'not_found', 413: 'too_large', 415: 'unsupported_type', 422: 'validation' };
  throw new ClientApiError(byStatus[res.status] || 'server', { status: res.status });
}

function notConnected(name) {
  return Promise.reject(new ClientApiError('api_not_connected', { message: `${name} : API client non connectée` }));
}

// ---- Compte ---------------------------------------------------------------
/** TODO(api) : inscription d'un nouveau client (le compte est créé en attente de validation). */
export function registerClient(_payload) { return notConnected('registerClient'); }
/** TODO(api) : connexion ; le serveur pose le cookie HttpOnly. Doit signaler un compte en attente. */
export function loginClient(_credentials) { return notConnected('loginClient'); }
/** TODO(api) : déconnexion ; le serveur invalide la session et retire le cookie. */
export function logoutClient() { return notConnected('logoutClient'); }
/** TODO(api) : profil du client connecté (raison sociale, contact, code client, statut…). */
export function getCurrentClient() { return notConnected('getCurrentClient'); }

// ---- Demandes de commande --------------------------------------------------
/** TODO(api) : liste des demandes du client connecté. */
export function listOrderRequests() { return notConnected('listOrderRequests'); }
/** TODO(api) : création d'une demande de commande. */
export function createOrderRequest(_payload) { return notConnected('createOrderRequest'); }
/** TODO(api) : détail d'une demande (avec ses documents). */
export function getOrderRequest(_requestId) { return notConnected('getOrderRequest'); }

// ---- Documents -------------------------------------------------------------
/** TODO(api) : dépôt d'un document sur une demande (multipart). `onProgress(0..1)` facultatif. */
export function uploadDocument(_requestId, _file, _onProgress) { return notConnected('uploadDocument'); }
/** TODO(api) : téléchargement d'une version de document via l'endpoint dédié (jamais par chemin disque). */
export function downloadDocument(_requestId, _documentId, _version) { return notConnected('downloadDocument'); }
/** TODO(api) : vue globale des documents si le backend fournit un endpoint ; sinon dérivée des demandes. */
export function listDocuments() { return notConnected('listDocuments'); }

// =============================================================================
// DONNÉES DE DÉMONSTRATION — À SUPPRIMER LORS DE L'INTÉGRATION DU VRAI BACKEND
// =============================================================================
// Ce fichier sert uniquement à présenter l'interface de l'Espace Client.
//  - Toutes les données sont fictives.
//  - Rien n'est envoyé ni enregistré : l'état vit en mémoire et disparaît au rechargement.
//  - Aucun mot de passe n'est conservé ; aucune vérification d'identifiants n'est faite.
//  - Ce n'est PAS une authentification : ne jamais s'en servir comme modèle de sécurité.
//
// Scénarios d'affichage (paramètre d'URL ?demo=…) :
//   ?demo=vide     → client sans aucune demande
//   ?demo=attente  → la connexion répond « compte en attente de validation »
//   ?demo=refus    → la connexion répond « identifiants incorrects »
// =============================================================================

import { ClientApiError } from './api.js';

export const DEMO_MODE = true;
export const DEMO_SCENARIO = new URLSearchParams(window.location.search).get('demo') || 'standard';

const wait = (ms = 450) => new Promise(r => setTimeout(r, ms));

const DEMO_CLIENT = {
  code: 'CL-0042',
  company: 'Maison Exemple SARL',
  contact: 'Sarah Martin',
  email: 'sarah.martin@exemple.com',
  phone: '+33 6 00 00 00 00',
  address: '12 rue de l’Exemple, 59000 Lille',
  country: 'France',
  taxId: 'FR00 000000000',
  status: 'active',
  since: '2026-09-02',
};

const DEMO_REQUESTS = [
  {
    id: 'demo-14', number: 'DC-2026-0014', article: 'Chemise popeline col officier', clientRef: 'SS27-CH-104',
    quantity: 1200, desiredDate: '2027-02-15', createdAt: '2026-10-14', status: 'under_review',
    comment: 'Coloris bleu nuit et blanc cassé. Merci de nous confirmer la faisabilité du délai.',
    documents: [
      { id: 'd1', name: 'Fiche technique chemise SS27-CH-104.pdf', version: 2, uploadedAt: '2026-10-16', size: 1240000, origin: 'client' },
      { id: 'd2', name: 'Tableau des mesures.xlsx', version: 1, uploadedAt: '2026-10-14', size: 86000, origin: 'client' },
      { id: 'd3', name: 'Proposition de tissus.pdf', version: 1, uploadedAt: '2026-10-18', size: 2310000, origin: 'framatex' },
    ],
  },
  {
    id: 'demo-11', number: 'DC-2026-0011', article: 'Veste blazer laine', clientRef: 'AW26-VE-021',
    quantity: 450, desiredDate: '2026-12-10', createdAt: '2026-09-28', status: 'accepted',
    comment: '', documents: [
      { id: 'd4', name: 'Dossier technique blazer.pdf', version: 3, uploadedAt: '2026-10-02', size: 3580000, origin: 'client' },
    ],
  },
  {
    id: 'demo-09', number: 'DC-2026-0009', article: 'Pantalon chino coton', clientRef: '',
    quantity: 800, desiredDate: '2027-01-20', createdAt: '2026-09-17', status: 'submitted', comment: '', documents: [],
  },
  {
    id: 'demo-06', number: 'DC-2026-0006', article: 'Robe midi viscose', clientRef: 'SS27-RO-008',
    quantity: 300, desiredDate: '', createdAt: '2026-09-05', status: 'rejected', comment: 'Délai trop court pour la saison.', documents: [],
  },
];

// État en mémoire (perdu au rechargement de la page, volontairement).
const memory = {
  signedIn: false,
  requests: DEMO_SCENARIO === 'vide' ? [] : structuredClone(DEMO_REQUESTS),
  seq: 15,
};

function requireSession() {
  if (!memory.signedIn) throw new ClientApiError('unauthenticated', { status: 401 });
}

export const demoSource = {
  async registerClient(_payload) {
    await wait(700);
    // Le mot de passe saisi n'est ni conservé ni transmis.
    return { status: 'pending' };
  },
  async loginClient(_credentials) {
    await wait(650);
    if (DEMO_SCENARIO === 'attente') throw new ClientApiError('pending', { status: 403 });
    if (DEMO_SCENARIO === 'refus') throw new ClientApiError('invalid_credentials', { status: 401 });
    memory.signedIn = true;
    return structuredClone(DEMO_CLIENT);
  },
  async logoutClient() {
    await wait(250);
    memory.signedIn = false;
    return { ok: true };
  },
  async getCurrentClient() {
    await wait(200);
    requireSession();
    return structuredClone(DEMO_CLIENT);
  },
  async listOrderRequests() {
    await wait();
    requireSession();
    return structuredClone(memory.requests).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  },
  async createOrderRequest(payload) {
    await wait(700);
    requireSession();
    const n = memory.seq++;
    const item = {
      id: `demo-${n}`, number: `DC-2026-${String(n).padStart(4, '0')}`,
      article: payload.article, clientRef: payload.clientRef || '', quantity: payload.quantity,
      desiredDate: payload.desiredDate || '', createdAt: new Date().toISOString().slice(0, 10),
      status: 'submitted', comment: payload.comment || '', documents: [],
    };
    memory.requests.push(item);
    return structuredClone(item);
  },
  async getOrderRequest(id) {
    await wait(300);
    requireSession();
    const item = memory.requests.find(r => r.id === id);
    if (!item) throw new ClientApiError('not_found', { status: 404 });
    return structuredClone(item);
  },
  async uploadDocument(requestId, file, onProgress) {
    requireSession();
    const item = memory.requests.find(r => r.id === requestId);
    if (!item) throw new ClientApiError('not_found', { status: 404 });
    for (let p = 0.1; p <= 1.001; p += 0.15) { onProgress?.(Math.min(p, 1)); await wait(110); }
    const existing = item.documents.find(d => d.name === file.name && d.origin === 'client');
    const doc = existing
      ? Object.assign(existing, { version: existing.version + 1, uploadedAt: new Date().toISOString().slice(0, 10), size: file.size })
      : { id: `u${Date.now()}`, name: file.name, version: 1, uploadedAt: new Date().toISOString().slice(0, 10), size: file.size, origin: 'client' };
    if (!existing) item.documents.push(doc);
    return structuredClone(doc);
  },
  async downloadDocument() {
    await wait(200);
    requireSession();
    // Aucun fichier réel en démonstration.
    throw new ClientApiError('api_not_connected');
  },
  async listDocuments() {
    await wait();
    requireSession();
    return memory.requests.flatMap(r => r.documents.map(d => ({ ...structuredClone(d), requestId: r.id, requestNumber: r.number, article: r.article })))
      .sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
  },
};

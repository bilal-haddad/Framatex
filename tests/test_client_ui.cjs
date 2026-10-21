'use strict';
// Espace Client (frontend isolé) : garde-fous de structure et de sécurité.
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict');
const dir = 'static/client';
const read = f => fs.readFileSync(path.join(dir, f), 'utf8');
const html = read('index.html'), api = read('api.js'), demo = read('demo-data.js'), client = read('client.js'), ui = read('components/ui.js');
const all = [api, demo, client, ui].join('\n');

// Isolation : aucune dépendance vers l'Espace FRAMATEX interne.
assert(!/\/assets\/(app|workspace|design-019|styles)\.(js|css)/.test(html + all));
// CSP : pas de script ni de gestionnaire d'événement inline.
assert(!/<script(?![^>]*\bsrc=)[^>]*>/.test(html));
assert(!/\son[a-z]+=/i.test(html));
// Sécurité : jamais de stockage navigateur ni de jeton dans l'URL.
assert(!/\b(localStorage|sessionStorage)\s*[.[]|document\.cookie/.test(all));
// API non connectée : aucune URL d'endpoint supposée, fonctions TODO présentes.
assert(!/['"`]\/api\//.test(api + client));
assert(api.includes('export const API_CONNECTED = false'));
for (const fn of ['registerClient', 'loginClient', 'logoutClient', 'getCurrentClient', 'listOrderRequests', 'createOrderRequest', 'getOrderRequest', 'uploadDocument', 'downloadDocument'])
  assert(new RegExp(`export function ${fn}\\(`).test(api), fn);
assert(api.includes("'X-Framatex-Request'") && api.includes("credentials: 'same-origin'"));
// Démo clairement isolée et identifiée.
assert(demo.includes('À SUPPRIMER') && client.includes("from './demo-data.js'"));
// Écrans attendus et textes métier clés.
for (const route of ['/connexion', '/inscription', '/en-attente', '/demandes', '/demandes/nouvelle', '/demandes/:id', '/documents', '/compte'])
  assert(client.includes(`path: '${route}'`), route);
assert(client.includes('Votre compte est en attente de validation par FRAMATEX'));
assert(client.includes('Elle ne constitue pas encore une commande officielle FRAMATEX'));
assert(client.includes('Vous n’avez encore aucune demande de commande.'));
// Données affichées échappées.
assert(client.includes('esc(r.article)') && client.includes('esc(d.name)'));
console.log('Espace Client UI : isolation, sécurité et écrans OK');

'use strict';
// Espace Client (static/client/) : branchement à l'API réelle, isolation et sécurité.
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict');
const dir = 'static/client';
const read = f => fs.readFileSync(path.join(dir, f), 'utf8');
const html = read('index.html'), api = read('api.js'), client = read('client.js'), ui = read('components/ui.js');
const all = [api, client, ui].join('\n');

// Plus aucune démonstration dans l'exécution normale.
assert(!fs.existsSync(path.join(dir, 'demo-data.js')));
assert(!/demo/i.test(html + all));
assert(api.includes('export const API_CONNECTED = true'));
// Isolation : aucune dépendance vers l'Espace FRAMATEX interne ni vers ses API.
assert(!/\/assets\/(app|workspace|internal|design-019|styles)\.(js|css)/.test(html + all));
assert(!/\/api\/(workspace|admin|launches|documents)\b/.test(all));
// CSP : pas de script ni de gestionnaire d'événement inline.
assert(!/<script(?![^>]*\bsrc=)[^>]*>/.test(html));
assert(!/\son[a-z]+=/i.test(html));
// Sécurité : session par cookie HttpOnly uniquement.
assert(!/\b(localStorage|sessionStorage)\s*[.[]|document\.cookie/.test(all));
assert(api.includes("credentials: 'same-origin'") && api.includes('xhr.withCredentials = true'));
assert((api.match(/'X-Framatex-Request'/g) || []).length >= 2);
const code = (api + client).replace(/^\s*\/\/.*$/gm, ''); // hors commentaires
assert(!/client_id/.test(code));
// Vrais endpoints de app/client_routes.py.
for (const ep of ["'/register'", "'/login'", "'/logout'", "'/me'", "'/order-requests'", '/documents`', '/download`'])
  assert(api.includes(ep), ep);
// Vrais champs backend.
for (const f of ['raison_sociale', 'nom_contact', 'telephone', 'adresse', 'pays', 'identifiant_fiscal', 'quantite', 'date_souhaitee', 'reference_client', 'commentaire', 'request_number', 'client_code'])
  assert(client.includes(f), f);
// Statuts réellement supportés.
for (const status of ['draft:', 'submitted:', 'under_review:', 'accepted:', 'rejected:']) assert(ui.includes(status));
// Écrans et messages métier.
for (const route of ['/connexion', '/inscription', '/en-attente', '/demandes', '/demandes/nouvelle', '/demandes/:id', '/documents', '/compte'])
  assert(client.includes(`path: '${route}'`), route);
assert(client.includes('Votre compte est en attente de validation par FRAMATEX'));
assert(client.includes('Cette demande ne constitue pas encore une commande officielle FRAMATEX / ORLI.'));
// Données affichées échappées.
assert(client.includes('esc(r.article)') && client.includes('esc(d.name)') && client.includes('esc(c.raison_sociale'));
console.log('Espace Client UI : API réelle, isolation, sécurité et écrans OK');

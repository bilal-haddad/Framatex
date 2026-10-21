# Espace Client FRAMATEX — frontend (préparation)

Interface isolée de l'Espace FRAMATEX et de la landing. Aperçu : `/assets/client/index.html`.

## Fichiers
- `index.html` — page unique (aucun script ni style inline : compatible avec la CSP du serveur).
- `client.css` — styles autonomes.
- `client.js` — routeur par ancre (`#/connexion`, `#/demandes`, …), écrans, formulaires, dépôt de fichiers.
- `components/ui.js` — composants partagés (champs accessibles, badges, toasts, états vide/erreur/chargement).
- `api.js` — couche API **non connectée** : fonctions TODO, aucune URL ni aucun champ supposé.
- `demo-data.js` — **données de démonstration à supprimer** lors de l'intégration.

## Brancher le vrai backend
1. Implémenter dans `api.js` : `registerClient`, `loginClient`, `logoutClient`, `getCurrentClient`,
   `listOrderRequests`, `createOrderRequest`, `getOrderRequest`, `uploadDocument`, `downloadDocument`,
   `listDocuments` (facultatif : sinon la vue « Mes documents » est reconstruite à partir des demandes).
2. Aligner les noms de champs (marqués `TODO(api)` dans `client.js`), les statuts (`REQUEST_STATUS`,
   `ACCOUNT_STATUS`), la règle de mot de passe et les formats/taille d'upload (`UPLOAD`).
3. Passer `API_CONNECTED` à `true`, supprimer `demo-data.js` et son import dans `client.js`.
4. Servir cette page sur `/espace-client` (modification de `app/main.py`, hors périmètre de cette branche).

## Sécurité (à respecter lors de l'intégration)
Cookie de session HttpOnly (aucun jeton en localStorage ni dans l'URL), en-tête `X-Framatex-Request: 1`
sur les requêtes d'écriture, aucun `client_id` envoyé par le navigateur, téléchargements uniquement
via l'endpoint dédié.

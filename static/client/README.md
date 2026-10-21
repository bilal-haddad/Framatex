# Espace Client FRAMATEX — frontend

Servi sur `/espace-client` (`app/main.py`). Interface isolée de l'Espace FRAMATEX et de la landing,
reliée au backend Client (`app/client_routes.py`, endpoints `/api/client/*`).

## Fichiers
- `index.html` — page unique (aucun script ni style inline : compatible avec la CSP du serveur).
- `client.css` — styles autonomes.
- `client.js` — routeur par ancre (`#/connexion`, `#/demandes`, …), écrans, formulaires, dépôt de fichiers.
- `components/ui.js` — composants partagés (champs accessibles, badges, toasts, états vide/erreur/chargement).
- `api.js` — appels à l'API client.

## Endpoints utilisés
| Fonction | Endpoint |
|---|---|
| `registerClient` | `POST /api/client/register` (compte créé `pending`) |
| `loginClient` | `POST /api/client/login` (401 identifiants, 403 compte non actif) |
| `logoutClient` | `POST /api/client/logout` |
| `getCurrentClient` | `GET /api/client/me` |
| `listOrderRequests` | `GET /api/client/order-requests` |
| `createOrderRequest` | `POST /api/client/order-requests` (statut `submitted`) |
| `getOrderRequest` | `GET /api/client/order-requests/{id}` |
| `uploadDocument` | `POST /api/client/order-requests/{id}/documents` (titre = nom du fichier ; même titre = nouvelle version) |
| `downloadDocument` | `GET /api/client/order-requests/{id}/documents/{document_id}/versions/{n}/download` |

« Mes documents » n'a pas d'endpoint dédié : la vue est reconstruite à partir des demandes.

## Sécurité
Cookie de session HttpOnly posé par le serveur (aucun jeton en localStorage, sessionStorage ni dans
l'URL), en-tête `X-Framatex-Request: 1` sur les écritures, aucun `client_id` envoyé par le navigateur,
fichiers récupérés uniquement via l'endpoint de téléchargement.

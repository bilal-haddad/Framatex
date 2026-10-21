# Workflow Client final — plateforme intégrée

Base : branche `integration/full-platform`, commit
`7deab9ab2fd4c0674e3f5f774a8271d34c71c688`.
Branche de livraison : `feature/client-workflow-final`.

Cette livraison complète le backend Client existant. Elle réutilise les sessions,
le stockage Client, SHA-256, le versioning, l'audit, les autorisations internes et
les composants d'interface déjà intégrés. Aucun fichier de landing ou de style
n'est modifié. L'authentification interne reste inchangée.

## Demandes de commande

| Statut | Libellé | Autorité |
| --- | --- | --- |
| `draft` | Brouillon | Client propriétaire |
| `submitted` | Envoyée | Client propriétaire |
| `under_review` | En cours d'étude | Administrateur FRAMATEX |
| `accepted` | Acceptée | Administrateur FRAMATEX |
| `rejected` | Refusée | Administrateur FRAMATEX |

Un client peut créer un brouillon ou une demande soumise, puis envoyer son propre
brouillon. Le retour de `submitted` vers `draft` est interdit. FRAMATEX peut
passer une demande soumise en étude, l'accepter ou la refuser ; une demande en
étude peut être acceptée ou refusée. Les états acceptée/refusée sont terminaux.
Une décision identique à l'état actuel est idempotente et ne crée pas un faux
changement d'audit. La comparaison atomique de l'ancien état empêche une décision
concurrente d'écraser silencieusement une autre décision.

L'acceptation ne crée aucune commande ni écriture ORLI.

## Demandes documentaires

`ClientDocumentRequest` relie une pièce attendue à un compte Client permanent et
à sa demande de commande. Le compte est déterminé depuis la demande côté serveur,
jamais envoyé par le portail Client.

Chemin normal : `requested` → `uploaded` → `under_review` → `accepted`.
En cas de correction : `uploaded` ou `under_review` → `correction_required` →
`uploaded` → `accepted` (ou nouvelle vérification). Une acceptation directe d'une
version déposée est également possible.

Chaque dépôt constitue une version du document réservé à cette demande
documentaire. Plusieurs demandes portant le même titre restent indépendantes.
Le client peut déposer seulement une pièce demandée ou à corriger. Une pièce en
vérification ou acceptée ne peut pas être remplacée par le dépôt générique des
documents de commande.

Chaque décision FRAMATEX cite obligatoirement l'identifiant de la version
courante. Une décision sur une ancienne version répond `409`. La correction
exige un message au client. Le contrôle optimiste de révision protège les
modifications concurrentes.

`ClientDocumentRequestEvent` conserve les états successifs, l'auteur, la date UTC,
la version concernée et le message explicitement destiné au client. Cet
historique métier est distinct du journal d'audit interne et des commentaires
internes. Toutes les versions restent téléchargeables par leur propriétaire et
par l'administrateur autorisé.

Le stockage existant est conservé : limite de 20 Mo, PDF/DOCX/XLSX/PNG/JPG/JPEG/TXT,
contrôles de format, nom disque aléatoire, SHA-256 et nettoyage d'un dépôt échoué.

## Partage FRAMATEX vers Client

`ClientSharedDocument` associe explicitement un compte destinataire et une version
interne précise. L'association facultative à une demande est contrôlée : la
demande doit appartenir au même compte. Aucune égalité de raison sociale et aucun
ancien aperçu simulé ne crée automatiquement un partage réel.

La politique réutilise les contrôles du module de partage antérieur : dossier
Jaune/Rose uniquement, type documentaire admissible, absence de marqueurs
sensibles dans le titre, le type et le nom du fichier de la version sélectionnée,
et approbation valide de cette version. Les types existants restent admissibles ;
`Confirmation de commande`, `Devis client` et `Document commercial client`
complètent explicitement la liste commerciale.

Les fiches de prix internes, coûts, marges, factures et documents marqués internes
ou confidentiels restent exclus. L'intégrité des octets est vérifiée avant la
publication et avant le téléchargement. Les commentaires, les décisions internes,
l'audit et la mémoire fournisseur/atelier ne figurent jamais dans la réponse
Client.

Une ancienne version peut être partagée explicitement si elle reste approuvée et
admissible. Une nouvelle version interne ne remplace jamais automatiquement la
version transmise. Les contrôles de type et d'approbation sont revérifiés à chaque
lecture : une version devenue inadmissible disparaît des accès Client.

Le retrait conserve la publication historique et le document interne. Il retire
immédiatement la pièce de la liste Client et rend les nouveaux téléchargements
inaccessibles (`404`, comme pour un partage étranger). Un fichier déjà téléchargé
ne peut pas être repris à son destinataire. Une nouvelle publication explicite
de la même version après retrait reste possible et crée un nouvel historique.

## Autorisations et notifications

Les décisions, demandes de pièces, publications et retraits sont réservés au rôle
`Administrateur` existant. Les vérifications d'accès au lancement et à la rubrique
source restent appliquées. Un collaborateur interne sans ce rôle reçoit `403` ;
une session Client seule ne permet jamais d'appeler une API administrative.

Les routes Client filtrent systématiquement par le compte actif de la session.
Les accès à une demande, une pièce ou une publication d'autrui répondent `404`.
Les opérations mutatives conservent l'en-tête `X-Framatex-Request: 1`.

La connexion distingue `account_pending` et `account_suspended` dans un refus
`403` seulement après vérification correcte du mot de passe. Pour une adresse
absente ou un mot de passe incorrect, le refus reste identique (`401`, message
générique). La vérification Argon2 d'un hash factice est exécutée pour les comptes
absents, et la limitation des tentatives existante reste active.

Aucun système d'envoi d'email n'était configuré. Les événements persistés dans
l'audit préparent les futures notifications, sans envoi externe :

- `client.order_request.status_changed` ;
- `client.document_request.requested`, `.uploaded`, `.under_review`, `.correction_required`, `.accepted` ;
- `client.shared_document.published`, `.revoked`, `.download`.

Les événements documentaires et leur audit sont écrits dans la même transaction.

## Migration additive

Révision `0006_client_workflow` du migrateur SQLite existant. Trois tables sont
ajoutées : `client_document_requests`, `client_document_request_events`,
`client_shared_documents`. Les tableaux de comptes, commandes, documents internes,
commentaires et publications simulées ne sont ni réécrits ni convertis.

Après arrêt des écritures et sauvegarde complète de `data/` :

```bash
source .venv/bin/activate
python -m app.migrate upgrade
python -m app.migrate status
```

La migration est rejouable. Une base existante versionnée est sauvegardée avant
application. Les tests couvrent une base vierge et une base précédente contenant
un compte, une demande et une version documentaire conservés à l'identique.

## Endpoints ajoutés

Préfixe `/api/client` :

| Méthode | Route | Fonction |
| --- | --- | --- |
| PATCH | `/order-requests/{id}/status` | Envoyer son brouillon |
| GET | `/document-requests` | Pièces demandées à son compte |
| GET | `/document-requests/{id}` | Détail et historique métier |
| POST | `/document-requests/{id}/upload` | Dépôt / nouvelle version après correction |
| GET | `/document-requests/{id}/versions/{number}/download` | Téléchargement d'une version propre |
| GET | `/shared-documents` | Versions explicitement transmises par FRAMATEX |
| GET | `/shared-documents/{id}/download` | Téléchargement sous contrôle du partage actif |

Préfixe `/api/admin` :

| Méthode | Route | Fonction |
| --- | --- | --- |
| PATCH | `/client-order-requests/{id}/status` | Étude / acceptation / refus |
| POST | `/client-order-requests/{id}/document-requests` | Demander une pièce au compte concerné |
| GET | `/clients/{id}/document-requests` | Pièces attendues / reçues, filtre optionnel `order_request_id` |
| GET | `/client-document-requests/{id}` | Détail et historique documentaire |
| PATCH | `/client-document-requests/{id}/status` | Vérification / correction / acceptation de `version_id` |
| GET | `/client-document-requests/{id}/versions/{number}/download` | Consulter la pièce reçue |
| GET | `/client-share-candidates` | Versions internes admissibles et approuvées |
| GET / POST | `/clients/{id}/shared-documents` | Historique / publication explicite |
| POST | `/client-shared-documents/{id}/revoke` | Retrait sans suppression du document |

## Interfaces raccordées

Le portail Client conserve les composants et styles de l'intégration : Mes
demandes, Documents demandés par FRAMATEX, Documents transmis par FRAMATEX, Mes
documents, Mon compte. Aucun dashboard Client supplémentaire n'est créé.

Dans « Clients et demandes », FRAMATEX peut changer l'état d'une demande, demander
une pièce, consulter les versions reçues, demander une correction, accepter une
version, partager un document et retirer un partage. Le bouton de partage est
également disponible dans la fiche d'une version interne. Les anciens aperçus
simulés restent séparés de ce partage réel et ne sont pas activés implicitement.

## Validation

```bash
PYTHONPATH=. python -m pytest -q
for file in tests/*.cjs; do node "$file" || exit; done
python scripts/validate_client_workflow_ui.py --output /workspace/artifacts/client-workflow
```

Résultat : 135 tests Python réussis (base de 106 + 29 nouveaux), 16 scripts JS
réussis (base de 15 + 1 nouveau), aucun test désactivé. Les deux anciennes
assertions de contrat ont été adaptées : les badges incluent les nouveaux états,
et le test de migration 0.20 continue de partir explicitement du schéma 0.19.

Le scénario navigateur valide les 15 étapes demandées, y compris correction V1
→ V2, acceptation, partage réel, téléchargement, isolation A/B, retrait effectif
et conservation du fichier interne. Il vérifie aussi les messages pending et
suspended, les routes intégrées et l'absence d'erreur JavaScript. Les nouvelles
sections sont contrôlées à 1440, 1024, 820 et 390 px sans débordement global.

Le runner réutilise le serveur et la base éphémères du runner existant. Il n'utilise
aucune donnée ni aucun identifiant réel de l'installation. Son `results.json`
contient la date, le SHA, l'état du worktree, les contrôles et les captures.

## Fichiers

Ajouts : `app/client_workflow_models.py`, `app/client_workflow.py`,
`app/client_workflow_routes.py`, `static/client-workflow-internal.js`,
`tests/test_client_workflow.py`, `tests/test_client_workflow_frontend.cjs`,
`scripts/validate_client_workflow_ui.py` et ce guide.

Modifications : `app/client_routes.py`, `app/main.py`, `app/migrate.py`,
`static/index.html`, `static/client/api.js`, `static/client/client.js`,
`static/client/components/ui.js`, `static/client/README.md`,
`tests/test_client_ui.cjs`, `tests/test_internal_operations.py` et `README.md`.

## Limites conservées

- Aucun envoi d'email externe, connecteur ORLI, chatbot ou appel d'API IA ajouté.
- Mot de passe oublié, édition de profil et multi-contact Client hors de cette phase.
- SQLite et les limites de stockage/contrôle de fichiers du prototype sont conservés ; aucun antivirus n'est introduit.
- Les décisions de workflow Client restent réservées aux administrateurs existants ; aucune nouvelle gestion de comptes n'est créée.
- Les documents déjà téléchargés avant un retrait ne peuvent pas être effacés du poste du destinataire.

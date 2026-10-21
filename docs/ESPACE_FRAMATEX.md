# Espace FRAMATEX interne — livraison 0.20

L'application existante FastAPI / SQLAlchemy / SQLite est conservée. Les modules
de pilotage agrègent les moteurs métier déjà présents. Les comptes internes, leurs
mots de passe, leurs rôles et leurs sessions n'ont pas été remplacés.

## État constaté avant intervention

| Fonction | État initial | Traitement |
| --- | --- | --- |
| Authentification, rôles, accès par lancement | Opérationnels | Conservés, tests historiques maintenus |
| Quatre sous-dossiers et documents | Opérationnels | Synthèses par rubrique, dépôt enrichi |
| Versions, SHA-256, passeport, QR | Opérationnels | Doublons et commentaires de version ajoutés |
| Complétude à cinq états | Opérationnelle | Agrégée sans assimiler `not_due` à `missing` |
| Décisions et circuits de validation | Opérationnels | Réutilisés pour les états et les priorités |
| Impacts, cohérence, Excel | Opérationnels | Actions consolidées et valeurs Excel avant/après |
| OCR / classement | Opérationnel sous réserve de Tesseract | Proposition intégrée au dépôt, confirmation humaine |
| EML / engagements | Opérationnels | Conservés, scénario réel d'archivage fictif dans le seed |
| Publication client / demandes fournisseur | Simulation interne contrôlée | Conservée ; aucun envoi ou accès externe inventé |
| Dashboard | Compteurs généraux / dossiers récents | Centre de pilotage opérationnel |
| Recherche | Noms et références de lancements | Recherche documentaire, fichiers et versions |
| Audit | Liste des 100 dernières opérations | Filtres, noms d'auteurs, pagination et portée |
| Commentaires / mémoire d'expérience | Absents | Ajoutés, strictement internes |
| Demandes clients | Backend Client présent, sans vue interne | Consultation administrative et téléchargement audité |
| Landing | Aucun écran réalisé dans ce checkout | `/` préservé ; aucun redesign de landing |
| Page Client | Backend présent, écran absent | Interface légère raccordée au backend existant |

## Installation et migration

Python 3.11+ (recette effectuée avec 3.12), SQLite et Node.js pour les tests JS.
Le migrateur du dépôt est `app/migrate.py` : aucun dossier `migrations/` ni Alembic
n'était présent.

```bash
cd /workspace/Framatex
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m app.migrate upgrade
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Avant mise à niveau d'une installation contenant des données : arrêter les
écritures et sauvegarder entièrement `data/`, y compris la clé de session. La
révision `0005_internal_operations` ajoute seulement trois tables :

- `launch_operations` : article, quantité, références provisoire/définitive et responsable ;
- `internal_document_comments` : commentaire attribué et horodaté sur une version précise ;
- `internal_experience_notes` : retour interne client, fournisseur ou atelier, lié à un lancement.

La migration est rejouable et sauvegarde une base versionnée avant une révision
en attente. Elle ne modifie ni les comptes, ni leurs hashes, ni les documents
historiques. Aucun rollback destructif automatique n'est introduit.

L'OCR nécessite le binaire Tesseract et les langues `fra` / `eng`. Dans cet
environnement, elles sont disponibles sous
`/workspace/.cache/framatex-tessdata`. Activer cette installation locale avec :

```bash
export TESSDATA_PREFIX=/workspace/.cache/framatex-tessdata
tesseract --list-langs
```

Le modèle français provient du dépôt officiel `tesseract-ocr/tessdata_fast`,
révision `87416418657359cb625c412a48b6e1d6d41c29bd`, fichier `fra.traineddata`.
SHA-256 : `ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca`.
La vérification TLS n'a pas été désactivée. Les langues système anglaise et OSD
sont réutilisées. Aucun accès à un fournisseur d'IA n'est nécessaire.

## Routes des écrans

| Chemin | Comportement |
| --- | --- |
| `/` | Point d'entrée interne historique conservé, notamment pour les liens QR |
| `/espace-framatex` | Alias explicite vers la même application interne |
| `/espace-client` | Interface Client : inscription, connexion, demandes et pièces de son compte |
| `/api/health` | Vérification de disponibilité existante |

Il n'existe toujours pas de landing institutionnelle dans ce checkout :
`static/landing/README.md` décrit des visuels à fournir, mais les images et une
page réalisée sont absentes. La réponse HTTP de `/` est vérifiée ; cela ne prouve
pas l'existence d'une landing distincte.

## Dashboard et complétude

Les huit indicateurs portent sur les dossiers actifs accessibles : actifs,
complets, incomplets, pièces manquantes, documents en attente de validation,
alertes ouvertes, incohérences non résolues et modifications à prendre en compte.
Les dossiers sans profil ou à visibilité partielle sont signalés séparément.

Le pourcentage utilise les seules règles exigibles. Une pièce `not_due` n'entre
pas dans le dénominateur. Les exceptions restent visibles et distinctes d'une
pièce présente : elles ne produisent pas artificiellement 100 %. Un dossier sans
exigence ou sans visibilité complète n'est pas annoncé comme complet.

Le compteur de validations déduplique les documents associés à des exigences
`pending_validation` ou à un circuit en cours. Un document facultatif sans revue
n'est pas ajouté artificiellement à ce compteur.

Les priorités réutilisent les actions existantes et ajoutent les incohérences,
corrections documentaires, circuits en attente et signaux Excel sur la version
courante. Les liens portent le lancement, la rubrique et, quand disponible, le
document et la version. Les dossiers clôturés sont exclus des actions.

## API ajoutées ou enrichies

Toutes les API internes utilisent `get_current_user`, les rôles existants et les
restrictions par lancement. Les requêtes mutatives exigent toujours
`X-Framatex-Request: 1`.

| Méthode | Route | Fonction / autorisation |
| --- | --- | --- |
| GET | `/api/workspace/dashboard` | Synthèse, `launch.read`, rubriques filtrées |
| GET | `/api/workspace/launches` | Commandes enrichies et filtres |
| GET | `/api/launches/{id}/operations` | Synthèse d'un dossier accessible |
| PATCH | `/api/launches/{id}/operations` | Suivi manuel, `launch.update` |
| GET | `/api/workspace/collaborators` | Responsables actifs, `launch.update` |
| GET | `/api/workspace/document-types` | Catalogue par rubrique lisible |
| GET | `/api/workspace/search` | Documents et versions filtrés par les droits |
| GET | `/api/workspace/activity` | Audit filtré, `audit.read` et `launch.read` |
| GET / POST | `/api/document-versions/{id}/comments` | Lecture / ajout, droits sur la rubrique |
| GET / POST | `/api/launches/{id}/experience-notes` | Mémoire interne, lecture / écriture Jaune |
| GET | `/api/workspace/experience` | Historique transversal limité aux dossiers accessibles |
| GET | `/api/admin/client-order-requests` | Demandes reçues, administrateur existant |
| GET | `/api/admin/client-order-requests/{id}` | Contenu et métadonnées des pièces client |
| GET | `/api/admin/client-order-requests/{id}/documents/{document_id}/versions/{number}/download` | Téléchargement administratif audité |

Conservées : `GET /api/admin/clients` et
`PATCH /api/admin/clients/{id}/status` pour l'activation/suspension.

Filtres commandes : `q`, `client`, `article`, `completion`, `with_alert`, `status`,
`date_from`, `date_to` (activité). Recherche documentaire : `q`, `folder`,
`doc_type`, `launch_id`, `date_from`, `date_to` (dépôt), `limit`, `offset`.
Audit : `actor_id`, `launch_id`, `document_id`, `action`, dates, `limit`, `offset`.
Les dates de fin sont inclusives dans l'API exposée aux utilisateurs.

Les endpoints documentaires existants acceptent désormais un champ formulaire
optionnel `comment`. Le dépôt renvoie `duplicates`, limité au même sous-dossier
accessible. Un document distinct peut conserver un contenu identique en le
signalant ; une version strictement identique d'un même document répond `409`.
Les anciennes versions restent téléchargeables et leurs validations ne sont
jamais transférées automatiquement à une nouvelle version.

## Fichiers et confidentialité

PDF, DOCX, XLSX, PNG, JPG/JPEG, TXT et EML restent acceptés. CSV UTF-8 est ajouté
avec contrôle du contenu textuel, des lignes et du nombre de colonnes. Les
exécutables et scripts ne sont pas ajoutés à la liste autorisée ; les signatures
MZ / ELF sont refusées, même avec une extension textuelle. Le format XLS ancien
reste refusé : aucun parseur fiable n'est ajouté pour cette extension.

Le stockage utilise toujours des noms aléatoires, la limite de 20 Mo, les contrôles
de signature/structure, le hash SHA-256 et les historiques. Les contrôles ne
constituent pas un antivirus. Les classeurs ne sont jamais exécutés.

Les agrégats ne donnent aucun titre, compteur, commentaire ou résultat de
recherche issu d'une rubrique inaccessible. Les commentaires et notes internes
n'ont aucun lien de publication vers les tables du portail Client. Une session
Client seule ne permet pas d'appeler les API internes, y compris l'API de lecture
des demandes Client par FRAMATEX.

Le module de publication antérieur conserve son contrôle explicite d'une
version approuvée et sa liste de types admissibles. La publication demeure une
simulation interne : aucun transfert vers un compte Client n'est ajouté ou
déduit d'une égalité de nom commercial. Les demandes fournisseurs ne provoquent
toujours aucun email sortant. ORLI demeure indépendant, sans faux connecteur.

## Démonstration A–E

Utiliser un compte administrateur existant, sans changer son mot de passe :

```bash
python -m app.seed_operations_demo --admin-email votre-compte-interne@example.test
```

Le seed est explicite et rejouable. Il n'est jamais exécuté au démarrage et ne
modifie aucun compte ni lancement préexistant. Les références sont réservées à
la démonstration et les données sont entièrement fictives.
Utiliser une base de démonstration dédiée : comme les modules antérieurs, les
règles d'impact et de cohérence sont globales, contrairement aux profils de
complétude affectés individuellement à chaque dossier.

| Cas | Référence | Résultat attendu |
| --- | --- | --- |
| A | FR-DEMO-2026-0141 | Dossier complet selon les règles exigibles |
| B | FR-DEMO-2026-0142 | Calcul du besoin absent dans Jaune / Technique |
| C | FR-DEMO-2026-0143 | Pièce douanière absente à l'expédition |
| D | FR-DEMO-2026-0144 | Fiche de prix présente, en attente de validation |
| E | FR-DEMO-2026-0145 | Fiche d'emploi V2, impact, écart de quantité, anomalie Excel et email archivé |

Parcours : ouvrir le dashboard, choisir une pièce manquante, ouvrir la commande
et sa rubrique ; consulter l'historique d'une fiche ; déposer un fichier et
demander une proposition de classement avant confirmation ; qualifier un écart
et enregistrer la prise en compte d'un impact ; retrouver les opérations dans
l'audit filtré. Les notes d'expérience restent dans la rubrique interne.

## Validation reproductible

```bash
PYTHONPATH=. python -m pytest -q
for file in tests/*.cjs; do node "$file" || exit; done
for file in static/*.js; do node --check "$file" || exit; done
python scripts/validate_internal_ui.py --output /workspace/artifacts/framatex
```

La recette Playwright nécessite Chromium installé (ou le navigateur Chromium
installé par Playwright) et les dépendances de `requirements-dev.txt`. Elle crée
une base, des comptes et un serveur éphémères, puis les ferme. Aucun identifiant
de connexion n'est affiché ou écrit dans les livrables. Elle n'utilise pas les
données ni les comptes de l'installation courante.

Résultat de livraison : 102 tests Python réussis, 14 scripts de tests JavaScript
réussis, contrôle syntaxique de tous les scripts. Un avertissement de dépréciation
de Starlette/TestClient subsiste ; aucun test n'est ignoré ou désactivé.

La recette navigateur couvre les largeurs 1440, 1024, 820 et 390 px, la navigation
mobile en drawer, les routes principales, le QR historique, les dépôts, les
commentaires, versions, la proposition OCR/classement, une véritable lecture OCR
d'image, les décisions d'incohérence et d'impact, et le parcours Client jusqu'à
la consultation des pièces côté FRAMATEX. Elle vérifie l'absence de débordement
horizontal global et d'erreur JavaScript. Le dossier de sortie contient 52
captures, `results.json`, `server.log` et un index de consultation.

## Limites conservées

- SQLite uniquement ; pas de migration PostgreSQL ni de déploiement de production réalisé.
- Profils et règles de démonstration à valider par les équipes FRAMATEX.
- Publication Client et échanges fournisseurs encore simulés en interne, sans envoi externe.
- La landing institutionnelle n'était pas fournie et n'a pas été créée.
- OCR local borné et dépendant de la lisibilité ; aucune mise à jour de valeur métier sans confirmation.
- Les synthèses et la recherche chargent les données accessibles du prototype en mémoire ; une indexation/pagination SQL sera nécessaire pour un volume industriel important.
- Aucune intégration ORLI nouvelle, aucune API d'IA, aucun chatbot nouveau. Framatex Assist conserve son guide déterministe existant.

## Inventaire de livraison

Ajouts : `app/internal_models.py`, `app/internal_service.py`, `app/internal_routes.py`,
`app/internal_uploads.py`, `app/seed_operations_demo.py`, `static/internal.js`,
`static/internal.css`, (interface client provisoire `static/client.*` remplacée à l'intégration par `static/client/`),
`tests/test_internal_operations.py`, `tests/test_internal_frontend.cjs`,
`scripts/validate_internal_ui.py`, `requirements-dev.txt`, ce document et
`VERSION_0.20.md`.

Modifications : `app/main.py`, `app/migrate.py`, `app/workspace_routes.py`,
`app/quality.py`, `app/intake.py`, `static/index.html` et `README.md`.
Les raccordements de navigation dans `static/workspace.js` et l'indicateur des
corrections ouvertes dans `static/quality.js` sont également complétés.
`app/core.py` et les modèles/routes du backend Client précédemment livré restent
inchangés.

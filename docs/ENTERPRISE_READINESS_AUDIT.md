# FRAMATEX — Audit de préparation à une utilisation en entreprise

Branche `feat/enterprise-production-readiness` (depuis `546f724`). Audit mené sur le code, par des
mesures reproductibles (`scripts/benchmark_endpoints.py`, `scripts/load_test_enterprise.py`), des tests
(pytest, recettes Chromium à clics réels) et des outils (bandit 1.x, ruff, pip-audit). Environnement de
mesure : conteneur Linux 4 vCPU, 16 Go, SQLite sur disque local ; client de charge sur la même machine
(il consomme une partie du CPU : chiffres prudents). Aucune donnée réelle, aucun système tiers testé,
aucune donnée envoyée à l'extérieur (pip-audit ne transmet que des noms de paquets publics). OWASP ZAP
n'était pas disponible dans l'environnement : le contrôle passif des en-têtes a été fait par tests.

**Priorités** : P0 bloquant avant production · P1 indispensable pour un usage fiable · P2 important après
le pilote · P3 facultatif. **État** : corrigé (dans cette branche) · à corriger · à étudier.

## 0. Grille de maturité (critères explicites, sans note globale)

| Critère | Statut | Justification |
|---|---|---|
| Aucune perte ni doublon de commande sous charge | Atteint | 645 créations confirmées = 645 en base, 0 doublon (charge 4 processus) ; idempotence de création |
| Zéro erreur serveur jusqu'à la charge visée | Atteint jusqu'à 100 utilisateurs simulés (4 processus) | 0 erreur à tous les paliers après correctif ; 6,7 % d'erreurs sur la référence |
| Latence acceptable (p95 < 3 s) sur les écrans courants | Atteint jusqu'à 50 utilisateurs (4 processus, charge soutenue) | p95 global 2,7 s ; tableau de bord général non conforme (A-02) |
| Sauvegarde restaurable et vérifiée | Outil prêt, planification à faire | `backup_framatex.py` testé (restauration, détection d'altération) |
| Dépendances sans vulnérabilité connue | Atteint | pip-audit : 0 après Pillow 13 |
| Exploitation multi-processus | Partiel | verrou de migration, WAL ; limite de connexion encore par processus (S-03) |
| Chiffrement en transit et au repos | Non atteint (déploiement) | HTTPS et chiffrement disque à configurer (I-01, D-04) |

## A. Performances et opérations simultanées

| ID | Problème | Module | Preuve | Risque | Gravité | Solution | Complexité | Priorité | Dépendances | État |
|---|---|---|---|---|---|---|---|---|---|---|
| A-01 | Pool de connexions épuisé pendant les dépôts : la connexion SQLAlchemy restait prise pendant le transfert et l'analyse/OCR | `document_intake_routes.stage_document`, `main.save_direct_upload`, `core.engine` | Référence `546f724`, 20 utilisateurs : p95 120 s, 6,7 % d'erreurs (délais) ; traces « QueuePool limit of size 5 overflow 10 reached » | Blocage de tous les utilisateurs dès 20 dépôts simultanés | Critique | Connexion rendue avant transfert/analyse/rendu ; pool 20+20 configurable | Faible | P0 | — | Corrigé : 20 utilisateurs, 0 erreur, p95 2,6 s |
| A-02 | Tableau de bord général en O(nombre de commandes) | `internal_routes.dashboard_report`, `internal_service._launch_summary`, `workspace_routes.build_priorities` | 200 commandes : 8,9 s → 2,5 s ; en charge (645 commandes, 50 utilisateurs) médiane 31 s | Accueil administrateur inutilisable au-delà de quelques centaines de commandes actives | Élevée | Fait : lectures groupées, complétude calculée une fois, historique borné, réponse allégée. Reste : synthèse précalculée par commande, mise à jour à l'écriture | Moyenne | P1 | — | Partiellement corrigé |
| A-03 | Requêtes N+1 (complétude, synthèse, actions, doublons, recherche) | `completeness._evaluate`, `internal_service`, `duplicates`, `internal_routes.search` | Profils pyinstrument : 22 requêtes par commande dans la complétude, chargement paresseux de chaque version | Lenteur proportionnelle au volume | Élevée | Requêtes groupées et jointures (`selectinload`) | Moyenne | P0 | — | Corrigé |
| A-04 | Historique global parcourant tout le journal | `internal_service.activity` | 8,0 s à 50 000 événements → 11 ms | Accueil et historique bloqués | Élevée | Préfiltre SQL par commande/document, arrêt anticipé sans filtre | Faible | P0 | — | Corrigé |
| A-05 | Liste des commandes non paginée, synthèse calculée pour toutes | `internal_routes.launches`, `static/internal.js` | 3,2 s / 1,8 Mo → 0,43 s / 108 Ko (page de 50) | Écran « Commandes » lent | Élevée | Filtres simples avant calcul, pagination, `X-Total-Count` | Faible | P0 | — | Corrigé |
| A-06 | Ouverture d'une commande : 22 requêtes, dont 3 allers-retours successifs | `static/app.js openLaunch`, `static/dossier.js` | Comptage des appels | Charge serveur ×3,7 à chaque ouverture et actualisation | Moyenne | 6 requêtes parallèles ; modules des onglets Contrôles/Communication/Historique chargés à l'ouverture de l'onglet | Moyenne | P1 | — | Corrigé |
| A-07 | Plafond d'un processus unique (GIL) | `scripts/start_windows.ps1` (1 processus) | 1 processus : p95 48 s à 50 utilisateurs, CPU ≈ 1,3 cœur ; 4 processus : p95 5,3 s à 50, 0 erreur à 100 | Saturation au-delà de ~20–30 utilisateurs actifs simultanés | Élevée | Plusieurs processus (verrou de migration ajouté, WAL optionnel) ; voir S-03 avant d'activer | Faible | P1 | S-03 | Partiellement corrigé |
| A-08 | Double création accidentelle (double clic, renvoi réseau) | `order_sheet.create_with_sheet` | 4 envois simultanés même clé → 1 commande (test) | Doublons de commandes | Moyenne | `Idempotency-Key` (table, migration 0019), clé par formulaire | Faible | P1 | — | Corrigé (création de commande) ; à étendre aux demandes Client |
| A-09 | Délai réseau de 8 s (corrigé dans la branche précédente) et absence de limites métier | `static/app.js`, `observability.rate_limited` | Mesures de rafale (≈ 25 requêtes par ouverture) | Abus ou client défaillant | Moyenne | Seau à jetons par session, configurable (rafale 400, 40/s), 429 + `Retry-After` | Faible | P1 | Nginx en production | Corrigé |
| A-10 | Analyse/OCR synchrone dans la requête, 2 analyses simultanées, repli « occupé » après 5 s | `document_intake.read_safely` | Dépôt PDF p95 5,6 s à 75 utilisateurs ; sous-processus Python lancé à chaque analyse | OCR long ressenti par l'utilisateur ; documents « à vérifier » en pic | Moyenne | Workers asynchrones (file Redis), états de tâche | Élevée | P1 | Redis | À corriger |
| A-11 | Réponse du tableau de bord volumineuse (≈ 2 Mo pour 200 commandes) | `dashboard_report` | `benchmark-apres.json` | Lenteur sur réseau lent | Faible | Pagination des listes de manquants, champs réduits | Faible | P2 | A-02 | À corriger |
| A-12 | Recherche plein texte limitée à 500 correspondances avant filtrage des droits | `document_search.search_content` | Lecture du code | Résultats autorisés manquants à grande échelle | Faible | Filtrer par commandes visibles dans la requête FTS | Faible | P2 | — | À corriger |

## B. Base de données

| ID | Problème | Module | Preuve | Risque | Gravité | Solution | Complexité | Priorité | Dépendances | État |
|---|---|---|---|---|---|---|---|---|---|---|
| B-01 | Clés étrangères non appliquées par SQLite | `core._sqlite_pragmas` | `PRAGMA foreign_keys` absent ; suite complète verte avec l'option `FRAMATEX_SQLITE_FOREIGN_KEYS=1` (239 tests) | Lignes orphelines silencieuses | Élevée | Contrôle `foreign_key_check` (ajouté à la vérification de sauvegarde) sur la base réelle, puis activation | Faible | P1 | sauvegarde | Option ajoutée, à activer |
| B-02 | Un seul écrivain SQLite | moteur | Aucune erreur de verrou en charge (busy_timeout 15 s, WAL) mais écritures sérialisées | Plafond d'écriture | Moyenne | PostgreSQL pour la configuration B | Élevée | P1 | — | À étudier (stratégie dans PRODUCTION_ARCHITECTURE) |
| B-03 | Migrateur maison limité à SQLite, exécuté au démarrage de chaque processus | `migrate.py` | Code | Conflit multi-processus ; pas de chemin PostgreSQL | Moyenne | Verrou ajouté ; Alembic à partir de 0019 | Moyenne | P1 | B-02 | Partiellement corrigé |
| B-04 | Spécificités SQLite : FTS5, `sqlite_master`, `PRAGMA` | `migrate.py`, `document_search.py`, `document_purge.py` | grep | Portage PostgreSQL | Faible | tsvector + GIN, information_schema | Moyenne | P2 | B-02 | À étudier |
| B-05 | Index manquants (versions par empreinte, audit par cible et par date) | `migrate` 0018 | Révocation de session = recherche dans l'audit à chaque requête | Lenteur croissante | Moyenne | Index ajoutés | Faible | P1 | — | Corrigé |

## C. Traitements documentaires

| ID | Problème | Module | Preuve | Risque | Gravité | Solution | Complexité | Priorité | Dépendances | État |
|---|---|---|---|---|---|---|---|---|---|---|
| C-01 | Pas d'antivirus sur les dépôts | `store_upload` | Code | Diffusion d'un fichier malveillant (y compris au Client) | Élevée | ClamAV en worker, quarantaine | Moyenne | P1 | A-10 | À corriger |
| C-02 | Analyse isolée en sous-processus avec délai (bon point) mais coût de démarrage Python à chaque fichier | `document_intake` | Code, mesures | Débit limité | Faible | Worker persistant | Moyenne | P2 | A-10 | À étudier |
| C-03 | Index plein texte : extrait seulement, sans page ni position | `document_search.index_document_version` | Code | Recherche et futur RAG incomplets | Moyenne | Table de segments (version, page, texte) | Moyenne | P2 | IA | À étudier |
| C-04 | Suppression définitive absente | corbeille | — | Impossible de purger un dépôt erroné | Élevée | API et écran dédiés, dépendances, conservation, file d'effacement | Moyenne | P0 | — | Corrigé |

## D. Sécurité (inspiré d'OWASP ASVS / Top 10)

| ID | Problème | Module | Preuve | Risque | Gravité | Solution | Complexité | Priorité | Dépendances | État |
|---|---|---|---|---|---|---|---|---|---|---|
| D-01 | Pillow 12.3 : 42 vulnérabilités connues (images téléversées) | `requirements.txt` | pip-audit | Exécution ou déni de service via image | Critique | Pillow ≥ 13 ; pip-audit propre ; suite verte | Faible | P0 | — | Corrigé |
| D-02 | Documentation d'API publique (`/docs`, `/openapi.json` 158 Ko) | `main.app` | Requête anonyme → 200 | Cartographie de l'API | Moyenne | Masquée si `FRAMATEX_ENV=production` | Faible | P1 | — | Corrigé |
| D-03 | Jeton de l'espace Client non rejeté explicitement par l'espace interne | `core.get_current_user`, `access.guard_http_request` | Jeton forgé `typ=client` (test) | Défense en profondeur (non exploitable : identifiants distincts) | Faible | Contrôle `typ` | Faible | P1 | — | Corrigé |
| D-04 | Cookie `Secure` et HSTS dépendants du déploiement | `core`, `main` | `FRAMATEX_COOKIE_SECURE` | Vol de session en HTTP | Élevée | HTTPS obligatoire, HSTS automatique | Faible | P0 | Déploiement | Corrigé (HSTS) / à configurer (HTTPS) |
| D-05 | Révocation de session vérifiée dans le journal d'audit | `core.get_current_user` | Code | Coût par requête (index ajouté) | Faible | Table de sessions révoquées | Faible | P2 | — | À corriger |
| D-06 | Protection CSRF (en-tête obligatoire + `SameSite=Strict`), CSP sans script en ligne | `main` | Tests existants | — | — | Conforme ; `style-src 'unsafe-inline'` résiduel | Faible | P3 | — | Conforme |
| D-07 | Injections SQL | `text()` paramétrés ; noms de tables constants (bandit B608, faux positifs vérifiés) | bandit | — | — | Conforme | — | — | — | Conforme |
| D-08 | Isolation des sous-dossiers et des comptes Client | `access_control.can`, recettes | 19 vérifications Chromium (dont sous-dossier non attribué), tests | — | — | Conforme ; nouvelles API (suppression, recherche, cases) vérifiées | — | — | — | Conforme |
| D-09 | Journalisation des événements sensibles | audit | Purge, conservation, habilitations, sessions tracées | — | — | Conforme ; journal d'accès JSON ajouté | — | — | — | Corrigé |
| D-10 | Fichiers malveillants : extensions, contenu, tailles contrôlés ; pas d'antivirus | `store_upload` | Tests existants | Voir C-01 | — | — | — | P1 | C-01 | À corriger |

## E. Stockage, sauvegardes, continuité

| ID | Problème | Module | Preuve | Risque | Gravité | Solution | Complexité | Priorité | Dépendances | État |
|---|---|---|---|---|---|---|---|---|---|---|
| E-01 | Aucune sauvegarde automatisée ni restauration testée (hors copie avant migration) | — | Absence d'outil | Perte totale en cas de panne disque | Critique | `backup_framatex.py` (copie en ligne, manifeste SHA-256, rotation, restauration vérifiée) + planification + copie hors site chiffrée | Faible | P0 | Exploitation | Outil corrigé, planification à faire |
| E-02 | Fichiers stockés en clair sur disque local | `data/files` | Code | Fuite en cas de vol du disque | Élevée | Chiffrement disque (BitLocker/LUKS), MinIO chiffré ensuite | Faible | P1 | — | À configurer |
| E-03 | Une suppression définitive reste dans les sauvegardes existantes | conception | — | Attente légitime d'effacement | Moyenne | Politique de rétention des sauvegardes documentée | Faible | P1 | Décision FRAMATEX | Documenté |
| E-04 | Politique de conservation documentaire non validée | `document_purge.DEFAULT_RETENTION` | Valeurs par défaut prudentes (10 ans financier/douane) | Destruction illégale ou conservation excessive | Élevée | Validation FRAMATEX + `retention-policy.json` | Faible | P0 | Décision FRAMATEX | À valider |
| E-05 | Aucun quota de stockage | — | — | Saturation disque | Faible | Quotas + alerte disque (`/api/health/ready`) | Faible | P2 | — | Partiellement (alerte) |

## F. Architecture, code, exploitation

| ID | Problème | Module | Preuve | Risque | Gravité | Solution | Complexité | Priorité | Dépendances | État |
|---|---|---|---|---|---|---|---|---|---|---|
| F-01 | Interface construite par surcharges successives de fonctions globales (`openLaunch`, `operationsDocument`…) dans 30 scripts, certains sur une seule ligne très longue | `static/*.js` | Ordre de chargement critique dans `index.html` | Régressions difficiles à anticiper | Moyenne | Modules ES, état centralisé, tests de composants | Élevée | P2 | — | À étudier |
| F-02 | `main.py` volumineux, responsabilités mêlées (routes, stockage, sécurité) | `app/main.py` | ~1 000 lignes | Maintenance | Faible | Découpage en routeurs et services | Moyenne | P2 | — | À étudier |
| F-03 | 77 imports inutilisés, gestion d'erreurs hétérogène (ruff B904) | `app/` | ruff | Bruit, traces moins lisibles | Faible | Nettoyage automatique, gestionnaire d'erreurs central avec `X-Request-ID` | Faible | P3 | — | À corriger |
| F-04 | Pas de versionnement d'API | `/api/*` | — | Intégrations futures (IA, ERP) | Faible | Préfixe `/api/v1` pour les nouvelles intégrations | Faible | P3 | — | À étudier |
| F-05 | Tests dépendants de l'ordre (base partagée) | `tests/` | Échecs en ordre réduit, verts en suite complète | Faux positifs/négatifs | Faible | Base temporaire par module | Moyenne | P2 | — | À corriger |
| F-06 | Supervision absente | — | — | Pannes non détectées | Élevée | Ajoutés : `X-Request-ID`, journal JSON, `/api/health/ready`, `/metrics` (jeton) ; reste : alertes | Faible | P1 | Exploitation | Partiellement corrigé |
| F-07 | Limite de connexion en mémoire de processus | `core.login_attempt_allowed` | Code | Limite multipliée par le nombre de processus | Moyenne | Compteur en base ou Redis | Faible | P1 | A-07 | À corriger |

## G. Interfaces et parcours

Parcours vérifiés par clics réels : 135 actions sur 5 profils internes (administrateur, lecture,
dépôt, responsable, personnalisé), parcours Client et traitement administrateur, suppression logique et
définitive, recherche technicien, documents complémentaires, vues 390 / 820 / 1024 / 1440 px sur les
recettes existantes et les nouveaux écrans (corbeille, fenêtre de destruction, sous-dossier).

| ID | Constat | Gravité | Priorité | État |
|---|---|---|---|---|
| G-01 | Écran « Commandes » lent avec beaucoup de commandes | Élevée | P0 | Corrigé (pagination, A-05) |
| G-02 | Accueil administrateur lent (tableau de bord) | Élevée | P1 | Partiellement corrigé (A-02) |
| G-03 | Modules des onglets secondaires : court message « Chargement des modules… » à la première ouverture | Faible | P3 | Choix assumé (A-06) |
| G-04 | Destruction irréversible : confirmation renforcée (motif + saisie « SUPPRIMER »), conservation expliquée | — | — | Corrigé |
| G-05 | Accessibilité : rôles, onglets et focus présents ; pas d'audit outillé (axe) complet | Moyenne | P2 | À étudier |

## H. Préparation du futur agent IA

| Point | Constat | Modification nécessaire |
|---|---|---|
| Données confirmées / proposées | Séparation déjà nette : `DocumentIdentification` (proposé) ; `ConfirmedField`, `BusinessValueRevision` (confirmés, avec version source) | Conserver : l'agent ne lit que le confirmé, ou signale explicitement le proposé |
| Provenance | Version source, auteur et date sur les valeurs confirmées ; historique complet | Ajouter la page/position pour les extraits (C-03) |
| Habilitations | `can()` centralisé ; l'assistant actuel est à réponses prévalidées, sans lecture des documents | Toute recherche de l'agent doit filtrer **avant** la récupération (A-12) ; jamais d'accès SQL libre |
| Mémoire métier | Notes classées par sous-dossier (0014) | Indexer avec leur portée de sous-dossier |
| API | Pas d'API versionnée ni de compte de service | `/api/v1`, compte technique « agent » soumis aux mêmes affectations, journal de chaque lecture |
| Ollama / RAG | Aucun composant | Serveur local, pgvector (après PostgreSQL), segments avec provenance, réponses citant leurs sources |

## I. Infrastructure

| ID | Problème | Gravité | Priorité | Solution | État |
|---|---|---|---|---|---|
| I-01 | HTTPS non fourni par l'application (proxy requis) | Élevée | P0 | Nginx ou IIS en frontal, certificat | À configurer |
| I-02 | Démarrage Windows en un processus (démonstrations) | — | — | Conservé ; production : Linux + Docker Compose | Conservé |
| I-03 | Aucune image Docker ni Compose | Moyenne | P1 | Proposition dans PRODUCTION_ARCHITECTURE.md | À réaliser après validation |

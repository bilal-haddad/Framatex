# Framatex — Dossier jaune numérique (MVP 0.19)

> **Workflow Client final sur la plateforme intégrée** : décisions de commande,
> pièces demandées avec corrections et versions, partage réel et retrait vers un
> compte Client explicite. Migration additive `0006_client_workflow`.
> [API, sécurité et recette](docs/CLIENT_WORKFLOW.md).

> **Livraison 0.20 — pilotage interne du Dossier Jaune.** Dashboard métier,
> commandes, recherche documentaire, audit filtré, commentaires de version,
> mémoire interne et consultation des demandes Client. Migration additive
> `0005_internal_operations`. Installation, recette, endpoints et limites :
> [Espace FRAMATEX](docs/ESPACE_FRAMATEX.md) · [Version 0.20](VERSION_0.20.md).

> **Version 0.19 — interface blanche, accents bleus et nouvel espace Framatex Assist.** Tableau de bord, navigation, bibliothèque documentaire et assistant harmonisés. [Détails](VERSION_0.19.md). Aucune migration supplémentaire.

> **Version 0.18 — refonte visuelle sombre inspirée des interfaces documentaires SaaS.** Tableau de bord restructuré, barre latérale, fiches et assistant conversationnel (toujours fondé sur des règles locales). [Détails](VERSION_0.18.md). Aucune migration supplémentaire.

> **Version 0.17 — retours de recette dans l’application et révocation des sessions.** [Détails](VERSION_0.17.md). Les ateliers avec les collaborateurs de Framatex restent à organiser.

> **Version 0.16 – stabilisation et recette du pilote local.** Sécurité HTTP, limitation locale des tentatives de connexion, navigation par rubriques, déconnexion mobile et suppression du débordement horizontal. Détails : [VERSION_0.16.md](VERSION_0.16.md) et [RECETTE_PILOTE.md](RECETTE_PILOTE.md).

**À lancer après sauvegarde du répertoire `data/` et arrêt des écritures :** `python -m app.migrate upgrade`, puis `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. N'ouvrez pas ce prototype sur Internet et ne chargez pas de données réelles sans autorisation de Framatex.

---

> **MVP 0.11** — Import contrôlé d’exports ORLI et rapprochement manuel : voir [VERSION_0.11.md](VERSION_0.11.md).

> **MVP 0.10** — Graphe des dépendances métier et simulation indicative des impacts : voir [VERSION_0.10.md](VERSION_0.10.md).

## Version 0.9 — tableau de bord d'actions et assistant de navigation

- **Mes actions** : sur l'accueil et dans la rubrique dédiée, les anomalies documentaires visibles, validations en attente, alertes d'impact, exigences client non vérifiées, ambiguïtés ouvertes et engagements email à échéance sont regroupés. Les actions ouvrent le lancement et la rubrique concernés.
- **Priorités explicites** : échéance dépassée = « urgent » ; document/écart/ambiguïté à examiner = « prioritaire » ; engagement arrivant dans les sept jours = « à suivre ». L'absence de date **ne crée pas** de retard fictif ; les dossiers clôturés sont exclus de la liste d'actions. Aucune décision automatique.
- **Assistant de navigation** : le bouton de la barre latérale ouvre une aide fondée sur des procédures locales prédéfinies (dépôt des pièces, validations, exigences, emails, administration). Il tient compte du lancement affiché et des droits de lecture, et propose un lien interne. **Ce n'est pas un chatbot génératif** : en cas d'absence de réponse vérifiée ou de droit, il demande de reformuler.
- **Confidentialité** : les actions sont calculées côté serveur à partir des seuls documents accessibles. Une vue agrégée ne doit jamais révéler une pièce, son titre ou son existence à un utilisateur non autorisé. Le service ne lit pas le contenu des fichiers pour répondre aux questions.

**Essai rapide :** après lancement, ouvrez « Vue d'ensemble » ou « Mes actions », puis cliquez sur une action pour accéder au dossier. Utilisez « Framatex Assist » pour demander « Où déposer une facture ? » ou « Comment vérifier une exigence client ? ».

**Tests 0.9 :** `python -m pytest -q tests/test_workspace.py` et `node tests/test_workspace_frontend.cjs`. La suite complète est lancée par GitHub Actions.


## Version 0.8 — courriels et engagements

Deux nouveaux modules sont accessibles en bas de la fiche de chaque **lancement de fabrication** :

1. **Archivage manuel des emails** : depuis un compte autorisé à lire et déposer dans le sous-dossier **Rose**, cliquer sur « Importer un email » et choisir un fichier `.eml`. Le fichier complet reste archivé comme document, avec son empreinte SHA-256 ; son objet, son expéditeur, sa date déclarée, le texte brut et la liste des pièces jointes sont consultables. Les pièces jointes elles-mêmes restent encapsulées dans l'original `.eml` ; aucune pièce jointe n'est déposée automatiquement comme document séparé.
2. **Registre des engagements** : cliquer sur « Repérer des engagements », puis « Vérifier et enregistrer ». Un utilisateur habilité `commitment.review` peut confirmer responsable, date, condition et phrase source. Ensuite, il peut documenter une réalisation, un report ou une annulation. Toutes ces décisions sont historisées.

**Important :** la détection repose sur des expressions régulières de portée limitée, **pas** sur une compréhension sémantique fiable. Une date relative comme « vendredi » n'est pas convertie en date absolue. Aucun email n'est envoyé, aucune boîte de messagerie n'est consultée, aucune tâche n'est créée automatiquement. Les formats `.msg` et HTML-only ne font pas partie de cette version. L'archivage n'équivaut pas à une validation juridique des engagements.

**Autorisations :** `launch.read` et `document.read` sur **rose** pour consulter les emails ; en plus, `document.write` sur **rose** pour importer ; `commitment.review` sur **rose** pour confirmer et mettre à jour les engagements. L'administrateur peut attribuer ce droit dans la gestion des rôles. Les utilisateurs sans lecture sur **rose** ne peuvent pas voir les messages, leurs métadonnées ou leurs engagements.

**Essai rapide :** se connecter avec l'administrateur de démonstration, créer un lancement, exporter un vrai courriel fictif en `.eml` et l'importer. Exemple de phrase en texte brut : « Nous vous transmettrons la confirmation le 20/10/2026, sous réserve du contrôle qualité. » Le module propose cette phrase ; la confirmer manuellement. Ne pas utiliser d'emails réels contenant des données clients avant autorisation de Framatex.

**Tests de la tranche :** `python -m pytest -q tests/test_mail.py` et `node tests/test_mail_frontend.cjs`. Les tests globaux restent disponibles via `python -m pytest -q`.

# Framatex — Dossier jaune numérique

> **Nouveauté 0.14 :** publication client contrôlée et demandes documentaires fournisseurs en simulation locale, sans aucun accès externe. Voir [VERSION_0.14.md](VERSION_0.14.md).

**MVP 0.14 — Prototype local du 17 octobre 2026.** Chaque dossier correspond à un **lancement de fabrication**, créé librement, avec identifiant technique indépendant de la référence ORLI. Les quatre sous-dossiers **Jaune, Rose, Bleu et Vert** sont générés automatiquement. Les exemples de démonstration sont entièrement fictifs.

## Installation

**Prérequis :** Python 3.11 ou ultérieur et accès Internet pour installer les dépendances. Aucun gestionnaire Node.js n'est nécessaire pour lancer l'interface.

Sous **Linux/macOS**, dans le dossier `framat-mvp` :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.bootstrap_admin --email admin@exemple.local
python -m app.seed_demo                 # facultatif : 3 lancements fictifs
python -m app.seed_completeness_demo    # facultatif : après seed_demo
python -m app.seed_workflow_demo        # facultatif : après seed_demo
python -m app.seed_quality_demo         # facultatif : après seed_demo
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Sous **Windows PowerShell** :

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.bootstrap_admin --email admin@exemple.local
python -m app.seed_demo
python -m app.seed_completeness_demo
python -m app.seed_workflow_demo
python -m app.seed_quality_demo
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si l'activation PowerShell échoue, utilisez directement `.venv\Scripts\python.exe` à la place de `python` pour les commandes suivantes. Le programme demande un mot de passe de 12 caractères minimum pour le premier administrateur : **aucun mot de passe par défaut n'est fourni**.

Ouvrez **http://127.0.0.1:8000** : la page d’accueil publique propose deux entrées. La connexion à l’espace interne FRAMATEX est servie sur **http://127.0.0.1:8000/espace-framatex** (l’entrée provisoire de l’espace Client sur `/espace-client`). L'API documentée est disponible sur **http://127.0.0.1:8000/docs**.

## Fonctions effectivement disponibles

| Volet | Fonctionnalités |
|---|---|
| Socle | Dossier par lancement, création sans ORLI, quatre sous-dossiers, recherche et tableau de bord |
| Documents | Dépôt PDF/DOCX/XLSX/images/TXT/EML (20 Mo max), versions conservées, SHA-256, téléchargement des anciennes versions |
| Utilisateurs | Administrateur, création de rôles et comptes, permissions par action et sous-dossier, contrôle côté serveur |
| Complétude 0.2 | Profils/règles par étape et type de document, cinq états, validations de règles, exceptions justifiées |
| Décisions 0.3 | Approuver / refuser / demander une reprise **par version**, commentaire, auteur et historique |
| Valeurs 0.3 | Consommation matière, quantité, besoin matière et prix unitaire, avec **unité**, document et version source, historique des révisions |
| Impacts 0.3 | Règles administrées sur changements de valeur ou nouvelles versions ; alertes par sous-dossier cible ; accusé de prise en compte, action nécessaire ou sans impact |
| Cohérence 0.4 | Comparaisons configurables de deux types documentaires (valeurs, unités, tolérance, qualification motivée), sans conversion implicite |
| Excel 0.4 | Inspection automatique des XLSX déposés : formules supprimées, modifiées et références `#REF!` ; historique des versions |
| Lecture 0.5 | Lecture de texte et OCR local (Tesseract optionnel), propositions de champs avec provenance, confirmation humaine par version |
| Classement 0.5 | Suggestions explicables de type et sous-dossier avant dépôt, choix final par un utilisateur habilité |
| QR papier 0.6 | Étiquette imprimable par lancement, lien sans secret et connexion obligatoire |
| Passeports 0.6 | Métadonnées par version, empreinte SHA-256 conservée et recalculée, auteur, décisions et état d’intégrité |
| Emails 0.8 | Archivage manuel EML et suivi d’engagements confirmés par une personne habilitée |
| Pilotage 0.9 | Vue priorisée des actions métier réellement visibles et de leurs échéances |
| Guide 0.9 | Assistant de navigation déterministe fondé sur des procédures locales et les droits utilisateur |
| Audit | Journal des opérations de création, mise à jour, dépôt, consultation et décisions |

**Les valeurs utilisées dans le moteur de cohérence restent relevées manuellement ; les champs OCR confirmés ne sont pas injectés dans ce moteur automatiquement.** Les formules Excel sont inspectées sans exécution. L'OCR local est disponible en option pour les images et PDF scannés ; cette version ne recalcule pas les besoins matière et n'utilise pas d'IA générative. Les alertes indiquent un **impact possible**, elles ne modifient pas les fichiers, le calcul des prix ou les données ORLI. Les règles et statuts de démonstration ne sont pas des règles officiellement validées par Framatex.

### Tester le parcours de démonstration

1. Dans **Dossiers jaunes**, ouvrez **« Chemises manches longues · pilote B »**.
2. Dans **Décisions et impacts métier**, consultez les deux révisions de consommation (1,8 → 1,9 m/pièce) et leurs documents sources.
3. Ouvrez les deux alertes créées par les règles d'exemple, puis enregistrez une décision motivée pour l'une d'elles.
4. Examinez la version actuelle de la fiche d'emploi : l'approbation de la version précédente ne s'applique pas automatiquement.
5. Dans **Administration**, désactivez ou créez une règle de propagation et attribuez à un rôle les autorisations `document.review`, `value.write` et `impact.review` selon les sous-dossiers.

Dans la section « Fiabilité documentaire » du lancement pilote B, le script `seed_quality_demo` crée un écart explicite (1 500 contre 1 450 pièces) et un fichier Excel dont une formule a été remplacée par une constante.

Sans les scripts de démonstration, le moteur ne génère **aucune règle ni alerte par défaut**. Consultez `VERSION_0.2.md` et `VERSION_0.3.md` pour les comportements détaillés et leurs limites.

## Architecture

```text
app/
  core.py                   SQLite, authentification et sessions
  models.py                 Lancements, sous-dossiers, documents, rôles, utilisateurs
  completeness_models.py    Règles de complétude et exceptions
  completeness.py           Évaluation contextuelle des pièces attendues
  workflow_models.py        Décisions, révisions de valeurs, règles et alertes
  workflow.py               Déclencheurs et constantes métier
  workflow_routes.py        API des fonctions 0.3
  quality_models.py         Valeurs documentaires, règles de comparaison, inspections Excel
  quality.py                Moteur de comparaison et inspection Excel statique
  quality_routes.py         API des fonctions 0.4
  intake.py                 Lecture, OCR, classification et extraction bornées
  intake_models.py          Champs confirmés par document et version
  intake_routes.py          API et autorisations du module 0.5
  paper_routes.py           QR papier, étiquette et passeport avec vérification de fichier
  main.py                   API FastAPI et fonctions de base
  bootstrap_admin.py        Création du premier administrateur
  seed_demo.py              Trois lancements fictifs
  seed_completeness_demo.py Jeu fictif de complétude
  seed_workflow_demo.py     Jeu fictif de valeurs et d'alertes
  seed_quality_demo.py      Deux scénarios fictifs de qualité 0.4
static/
  index.html                Point d'entrée web
  app.js                    Interface documentaire et complétude
  workflow.js               Interface des décisions, valeurs et impacts
  quality.js                Interface des comparaisons et constats Excel
  intake.js                 Aperçu OCR, classement et confirmation des champs
  paper.js                  Étiquette QR et visualisation des passeports
  spec.js                   Exigences client et ambiguïtés
  styles.css                Styles responsive
 tests/                     Tests API et tests de fragments frontend
```

**Stack utilisée pour cette étape :** FastAPI, SQLAlchemy et SQLite, frontend JavaScript et CSS fournis sans compilation. PostgreSQL et React/TypeScript restent possibles, mais **ne sont pas intégrés** au prototype actuellement livré.

## Tests

Après installation des dépendances :

```bash
python -m pip install pytest httpx
python -m pytest -q
```

Avec Node.js installé (facultatif), vous pouvez aussi vérifier le rendu des fragments frontend :

```bash
node tests/test_frontend_render.cjs
node tests/test_workflow_frontend.cjs
node tests/test_quality_frontend.cjs
```

## Mise à niveau depuis 0.3

Arrêtez l'application, puis **sauvegardez entièrement le dossier `data/`** avant de remplacer les fichiers sources. Ne remplacez ni n'effacez votre répertoire `data/` lors de la mise à jour. Au prochain démarrage, SQLAlchemy crée les quatre tables complémentaires de 0.4 pour les contrôles tout en conservant celles de 0.1 à 0.3. Ce mécanisme ne remplace **pas** une vraie migration versionnée (Alembic) ; la restauration doit être testée avant exploitation durable. Les rôles personnalisés précédents n'obtiennent pas automatiquement les nouvelles permissions.

## Précautions avant un pilote en entreprise

**Ce MVP est conçu pour une démonstration locale, pas pour un déploiement avec des documents confidentiels réels.** Ne l'ouvrez pas sur Internet et n'importez pas de données sensibles de Framatex sans accord et revue de sécurité.

Restent notamment à concevoir ou à valider : permissions **par type documentaire** (droits par lancement ajoutés en 0.15), habilitations nominatives des services, séparation entre auteur et approbateur, authentification renforcée, journal d'audit immuable, protection antivirus et examen approfondi des fichiers bureautiques, stockage sécurisé, chiffrement, sauvegarde/restauration, migrations, hébergement HTTPS sur réseau interne, tests de sécurité, politique de conservation, connexion éventuelle à ORLI. L'interface expose les quatre sous-dossiers avec droits de lecture configurables, mais **pas encore de circuit de validation à plusieurs étapes avec échéances et suppléants**.

`ROADMAP.md` présente les modules restant à développer, notamment la passerelle papier-numérique par QR code, les circuits d’approbation complets et la consolidation des champs OCR dans les contrôles métier.

## Limites des contrôles 0.4 et de leur articulation avec 0.5

- La comparaison inter-documents fonctionne sur **des valeurs explicitement relevées** et enregistrées par les utilisateurs ; les champs extraits par l'OCR 0.5 ne sont pas encore injectés automatiquement dans ces contrôles. Si plusieurs documents satisfont au même type, la règle affiche « Source ambiguë » plutôt que de choisir arbitrairement. Seules les versions courantes sont comparées.
- Le contrôle Excel est **statique** : il ne recalcule pas les formules, ne vérifie pas les résultats financiers et n’ouvre aucun lien externe. Le premier classeur sert de référence, sans pouvoir détecter qu’une formule manquait déjà. Taille d’inspection plafonnée à 5 Mo et 40 000 cellules ; les autres fichiers restent archivés mais leur inspection est marquée comme limitée.
- Aucune correction automatique de fichier, de prix, de besoin matière ou de donnée ORLI n’est réalisée. Les changements de type documentaire doivent être configurés à partir des intitulés réellement utilisés.
- Le serveur reste un **prototype local**. Les traitements de fichiers reçus depuis l’extérieur devront être isolés et soumis à une revue de sécurité avant un déploiement dans le système d’information de Framatex.


## Version 0.5 — lecture et classement assistés

Deux innovations ajoutées :

- Aperçu avant dépôt (`POST /api/launches/{id}/intake/preview`) : classement proposé par indices de nom et contenu, lecture de texte et extraction de champs métier. Aucun dépôt automatique.
- Lecture d’une version déjà conservée (`GET /api/document-versions/{id}/intake`) et confirmation manuelle de chaque champ (`POST /api/document-versions/{id}/intake/confirm`). Une version ultérieure n’hérite pas des champs confirmés.

Le moteur utilise en priorité les textes de PDF, DOCX, XLSX, TXT et EML. Pour les scans/images, il emploie Tesseract localement (langues française et anglaise), avec une analyse limitée à trois pages pour les PDF. L'installation de `tesseract-ocr`, `tesseract-ocr-fra`, `tesseract-ocr-eng` est nécessaire pour les scans ; si le moteur est absent, la fonctionnalité signale la limite sans inventer de texte.

Le classement repose sur des règles explicables, pas sur un modèle appris : toutes les propositions peuvent être corrigées. Les données confirmées restent distinctes des valeurs utilisées dans les calculs et ne sont jamais synchronisées automatiquement avec ORLI. Aucune information n'est envoyée à un fournisseur externe. Un environnement de production requiert une revue de sécurité, une file d'analyse isolée, un antivirus et des contrôles de performance.

Tests : `PYTHONPATH=. python -m pytest -q` (22 tests).


## Nouveautés de la version 0.6 — QR et passeports

Deux innovations ont été ajoutées ensemble :

1. **Passerelle papier-numérique** : depuis la page d’un lancement, ouvrir l’étiquette QR imprimable, la coller sur la chemise papier, scanner pour retrouver le dossier après authentification. Le dépôt continue à passer par les contrôles de permissions et par le classement humain.
2. **Passeport numérique de chaque version** : depuis « Passerelle papier et passeports numériques », vérifier le hash SHA-256 effectivement recalculé sur le fichier stocké, l’auteur, la provenance de version et les décisions. Le statut « intact » ne certifie ni le contenu métier ni l’immuabilité de la base.

Installer la nouvelle dépendance `qrcode` via `pip install -r requirements.txt`. Par défaut, le QR code encode `http://127.0.0.1:8000`, qui n’est **pas accessible depuis un téléphone**. L’option `FRAMATEX_PUBLIC_BASE_URL` permet d'indiquer une origine approuvée du réseau interne ; ne l’utilisez pas pour exposer le prototype sur Internet. Voir `VERSION_0.6.md`.

Test ajouté : `tests/test_paper.py` et `tests/test_paper_frontend.cjs`. **26 tests Python** passent.

## Version 0.7 — Exigences client et ambiguïtés documentaires

Deux fonctionnalités utilisables depuis la fiche d'un lancement :

- **Couverture des exigences client** : repérer des phrases candidates dans un document technique, enregistrer les exigences après confirmation, associer une preuve d'une version précise et faire enregistrer son examen par un responsable. Une source ou une preuve remplacée doit être réévaluée.
- **Détection des ambiguïtés** : repérer certains passages imprécis, confirmer les questions de clarification, suivre les résolutions motivées et réexaminer les passages après remplacement de la source.

Le repérage est **lexical, local et limité**. Il ne détecte pas toutes les exigences ni toutes les ambiguïtés, et ne garantit pas la conformité. Aucun statut n'est validé automatiquement. Des droits distincts `requirement.review` et `ambiguity.review` sont disponibles pour les rôles personnalisés, en plus des droits documentaires. Les compteurs sont calculés sur les éléments réellement accessibles.

Voir [`VERSION_0.7.md`](VERSION_0.7.md) pour les opérations, la confidentialité, les endpoints et les limites. Le projet contient **33 tests API** et des tests de fragments JavaScript.

## Version 0.12 — Suivi des matières et rapprochement des quantités

Le dossier de lancement contient désormais un espace **Traçabilité et rapprochement des matières**. On y définit les matières et leurs besoins prévus, on enregistre les quantités commandées et réceptionnées avec leurs justificatifs, puis on examine les écarts. Toutes les saisies sont manuelles, historisées et conservées en décimal ; aucun mouvement ORLI n'est créé. Les autorisations de lecture simultanées Jaune/Rose sont nécessaires pour consulter les totaux afin de ne pas dévoiler indirectement les mouvements de réception.

**Avant mise à jour :** arrêter l'application et sauvegarder `data/` en intégralité. L'ajout de tables au démarrage par SQLAlchemy est une facilité de démonstration et ne remplace pas une migration versionnée. Consultez [`VERSION_0.12.md`](VERSION_0.12.md) pour les écrans, routes, limites et scénarios de test.


## Version 0.15 — migrations et confidentialité des lancements

La mise à niveau 0.15 introduit un **migrateur SQLite versionné** et un périmètre d'accès configurable **par lancement**. La procédure, les commandes et les limites sont détaillées dans [VERSION_0.15.md](VERSION_0.15.md).

**Mise à niveau de la 0.14 :** arrêter le serveur, sauvegarder intégralement le dossier `data/`, remplacer les fichiers sources, puis exécuter :

```bash
python -m app.migrate upgrade
python -m app.migrate status
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Le système crée aussi une sauvegarde automatique datée avant d'ajouter des colonnes à une base SQLite 0.14. Les bases PostgreSQL **ne sont pas couvertes** par ce migrateur. La migration n'est pas un substitut à une politique de sauvegarde et de restauration éprouvée.

Depuis la fiche d'un lancement, l'administrateur dispose du bouton **Gérer les accès** pour restreindre sa visibilité et attribuer des membres nommément. La restriction s'ajoute aux permissions par rôle et sous-dossier. Elle ne les remplace pas. Les anciennes fiches restent en mode ouvert pour préserver les collaborations actuelles : leur restriction est **à activer explicitement** avant tout pilote sensible.

Si tous les nouveaux dossiers doivent être restreints dès leur création, définir `FRAMATEX_RESTRICT_NEW_LAUNCHES=1`.

La version actuelle constitue encore un démonstrateur local. L'accès réel aux données Framatex reste subordonné à une validation technique, juridique et organisationnelle.

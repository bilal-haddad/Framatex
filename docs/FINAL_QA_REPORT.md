# Rapport de recette final — plateforme FRAMATEX

Branche : `final/platform-review` — base : dernier commit de Codex `032d029`.
Recette du 21 octobre 2026. Aucun merge dans `main`.

Détail fonction par fonction : [`PLATFORM_FUNCTIONAL_REVIEW.md`](PLATFORM_FUNCTIONAL_REVIEW.md).
Planches de captures : [`qa-captures/`](qa-captures/).

## 1. Résultat

- Aucun bug bloquant restant.
- 10 bugs trouvés et corrigés (section 3), sans changement de logique métier ni du
  backend.
- Design unifié sur les trois espaces par un design system partagé.
- Seul le logo officiel FRAMATEX est utilisé ; aucun logo généré.

| Suite | Résultat |
| --- | --- |
| Tests Python (`pytest`) | **135 réussis**, 0 échec, 0 ignoré |
| Tests JS (`tests/*.cjs`) | **16 scripts réussis**, 0 échec |
| Recette plateforme (`scripts/qa_platform_review.py`) | **83 / 83** vérifications réussies |
| Recette navigateur interne de Codex (`scripts/validate_internal_ui.py`) | 7 parcours, 52 captures, aucune erreur JavaScript |
| Recette navigateur Client de Codex (`scripts/validate_client_workflow_ui.py`) | Scénario complet (15 étapes) validé, aucune erreur JavaScript |
| Accessibilité automatique (24 écrans) | 23 sans remarque ; 1 faux positif expliqué (section 5) |
| Défilement horizontal | Aucun, sur tous les écrans, à 1440, 1024, 820 et 390 px |
| Console navigateur | 0 erreur JavaScript ; seul le 401 normal de `/api/auth/me` avant connexion |

## 2. Environnement de test

| Élément | Version |
| --- | --- |
| Navigateur | Chromium 141.0.7390.37 headless, piloté par Playwright 1.56.1 (Node 22.22) et Playwright Python 1.56.0 |
| Largeurs | 1440, 1024, 820, 390 px (hauteur 1000, 844 px en mobile) |
| Serveur | Python 3.13, FastAPI, SQLAlchemy 2.1, SQLite, uvicorn |
| OCR | Tesseract 5.3.4 (`fra`, `eng`), PyMuPDF 1.28 |
| Données | Bases temporaires, démonstration A–E fictive, comptes de recette créés pour l'occasion |

Non testés : Firefox, Safari / WebKit, appareils mobiles physiques, lecteurs
d'écran.

## 3. Bugs trouvés et corrigés

| # | Bug | Effet constaté | Correction | Fichier |
| --- | --- | --- | --- | --- |
| 1 | Sélecteur ambigu dans la recette Client de Codex (deux boutons `submit`) | La recette navigateur interne échouait (mode strict Playwright) | Sélecteur ciblé `#request-form button.btn-primary[type=submit]` | `scripts/validate_internal_ui.py` |
| 2 | Carte « Framatex Assist » écrasée dans la barre latérale | Texte coupé sur les écrans peu hauts | `.sidebar > * { flex-shrink: 0 }` | `static/brand/framatex-app.css` |
| 3 | `@import url('')` dans la feuille principale | Requête inutile, la feuille s'importait elle-même | Ligne supprimée | `static/styles.css` |
| 4 | Google Fonts importées alors que la CSP les bloque | Erreurs console, polices de secours affichées | Imports supprimés, polices DM Sans / Manrope hébergées localement (licence OFL) | `static/design-019.css`, `static/brand/fonts/` |
| 5 | Suffixe technique « · demande 3fa2c1d8 » visible dans les titres | Libellés incompréhensibles côté Client et FRAMATEX | Suffixe retiré à l'affichage (donnée intacte) | `static/client/client.js`, `static/internal.js` |
| 6 | Audit affiché en codes bruts et JSON | Journal illisible pour un collaborateur | Libellés français, code technique discret, détails en pastilles, empreinte tronquée | `static/internal.js`, `static/brand/framatex-app.css` |
| 7 | Statut de compte client brut (« active ») | Mot anglais dans l'interface | Badge « Actif / En attente / Suspendu » | `static/internal.js` |
| 8 | Fenêtre « demande client » côté FRAMATEX : statut brut et dates ISO | « submitted », « 2027-03-20 » | Statuts et dates en français | `static/internal.js` |
| 9 | Dépôt de document et de version sans état de chargement ni contrôle de taille | Double envoi possible ; un fichier > 20 Mo partait avant d'être refusé | Refus immédiat > 20 Mo, bouton désactivé « Dépôt en cours… » (`aria-busy`), rétabli en fin de dépôt | `static/internal.js` |
| 10 | Fiche commande insérée entre le titre « Les quatre sous-dossiers » et les cartes | Hiérarchie du dossier confuse | Fiche commande placée avant le titre | `static/internal.js` |

## 4. Harmonisation du design

Un design system unique alimente les trois espaces :

- `static/brand/tokens.css` (nouveau) : palette validée (#0e2a5a, #0a1f44, #1d4f91,
  #29a8df, #ffffff, #f6f8fb, #e1e6ed), couleurs d'état, repères des quatre
  sous-dossiers, typographie, rayons (4 / 6 px), ombres légères, focus.
- Ce fichier est chargé en premier par la landing, l'Espace Client et l'Espace
  FRAMATEX.

Corrections de design (hors bugs) :

- **Espace FRAMATEX** : peau `static/brand/framatex-app.css` chargée en dernier,
  sans toucher à la logique. Elle couvre :
  - le logo officiel dans la barre latérale et à la connexion, en remplacement du
    monogramme générique ;
  - les boutons principaux en bleu nuit (au lieu de #125feb), les champs avec
    focus cyan, les cartes à rayon 6 px ;
  - les KPI en Manrope ;
  - le filet coloré des quatre sous-dossiers ;
  - les fenêtres sans flou ;
  - l'icône du menu mobile ;
  - le sous-titre de marque masqué sous 1100 px ;
  - l'écran de connexion avec la photo officielle.
- **Espace Client** :
  - `client.css` branché sur les jetons ;
  - libellés de navigation « Documents demandés » et « Documents transmis » ;
  - bandeau « Correction demandée par FRAMATEX » avec le message ;
  - espacements des listes ;
  - lignes de fichiers adaptées au mobile.
- **Landing** : vérification seulement, avec de petites corrections :
  - jetons partagés ;
  - favicon officiel ;
  - visuel « Notre solution » en WebP (452 → 42 Ko, PSNR 41,4 dB ; le PNG source
    est conservé) ;
  - poids de la page 1 331 → 921 Ko.

Le tableau de bord suit l'ordre demandé : KPI → Actions prioritaires → Documents
manquants → Complétude des dossiers → Alertes et incohérences → Dernières
activités (vérifié dans le navigateur).

Fichiers de design modifiés depuis `032d029` :

- nouveaux :
  - `static/brand/tokens.css` ;
  - `static/brand/framatex-app.css` ;
  - `static/brand/fonts/*` (7 woff2 + 2 licences OFL) ;
  - `static/landing/redesign/notre-solution.webp` ;
- modifiés :
  - `static/landing/landing.css` ;
  - `static/landing/index.html` ;
  - `static/client/client.css` ;
  - `static/client/index.html` ;
  - `static/index.html` ;
  - `static/design-019.css` ;
  - `static/styles.css` ;
- affichage seulement, sans logique métier :
  - `static/app.js` (bloc de marque) ;
  - `static/internal.js` (libellés, ordre de la fiche, garde-fous de dépôt) ;
  - `static/client/client.js` (libellés).

Aucun fichier backend (`app/`) n'a été modifié.

## 5. Défauts restants (non bloquants)

| Défaut | Gravité | Commentaire |
| --- | --- | --- |
| 401 de `/api/auth/me` dans la console avant connexion | Cosmétique | Sonde de session normale ; le navigateur journalise tout 401. |
| Format des champs date (jj/mm/aaaa ou mm/dd/yyyy) | Cosmétique | Dépend de la langue du navigateur ; en français il s'affiche jj/mm/aaaa. |
| Bouton « Profil et étape » sur deux lignes à 390 px | Cosmétique | Aucun impact d'usage. |
| Logo demandé deux fois au premier chargement | Négligeable | Favicon + image, puis mis en cache. |
| Contrôle d'accessibilité : focus jugé invisible sur le champ date « Nouvelle demande » | Faux positif | Mesure prise pendant la transition CSS ; l'anneau cyan est présent une fois la transition finie (vérifié). |
| Avertissement PyMuPDF « `fitz` API is deprecated » | Technique | Fonctionne avec la version épinglée (< 2) ; à migrer vers `import pymupdf` avant PyMuPDF 2. |
| API : modifier l'étape sans `profile_id` efface le profil | Faible | L'interface envoie toujours le profil ; comportement d'API existant non modifié. |

Les limites fonctionnelles (emails, mot de passe oublié, ORLI, etc.) sont listées
dans la section 16 de `PLATFORM_FUNCTIONAL_REVIEW.md`.

## 6. Tests exécutés

### Suites automatiques

```bash
PYTHONPATH=. python -m pytest -q                                  # 135 passed
for f in tests/*.cjs; do node "$f" || exit 1; done                # 16 scripts OK
python scripts/qa_platform_review.py --output data/qa-platform    # 83/83
python scripts/validate_internal_ui.py --output <dossier>         # 7 parcours, 52 captures
python scripts/validate_client_workflow_ui.py --output <dossier>  # scénario complet validé
```

Aucun test existant n'a été désactivé ni modifié pour passer. Aucun test unitaire
n'a été ajouté : les corrections portent sur l'affichage et sont couvertes par
les recettes navigateur. `scripts/qa_platform_review.py` est un script de
recette, pas une extension de la suite `pytest`.

### Recette plateforme : 83 vérifications sur serveur réel

| Domaine | Vérifications |
| --- | --- |
| Base | Migration sur base vierge ; copie d'une base existante migrée deux fois sans erreur ni perte (nombres de lignes identiques sur 9 tables) |
| Landing / QR | Routes et CSP ; logo, design system, polices et visuels servis localement ; redirection des anciens liens QR ; étiquette QR (lien + PNG) |
| Connexion interne | Succès ; mauvais mot de passe 401 ; session obligatoire (401) ; écriture sans en-tête refusée (403) |
| Dashboard | KPI ; actions prioritaires reliées à un dossier ; dernières activités issues de l'audit |
| Complétude | Pièces manquantes B (Jaune) et C (Bleu) ; `not_due` jamais compté manquant ; exception motivée ; les cinq états observés |
| Documents | Dépôt PDF, DOCX, XLSX, PNG, JPG, TXT, EML, CSV avec SHA-256 exact ; refus exécutable, faux PDF, > 20 Mo, rubrique invalide ; doublon détecté ; téléchargement identique |
| Versions | V1 → V2 → V3, anciennes versions conservées et téléchargeables, auteur, date, refus d'une version identique, audit, commentaires |
| Alertes | Nouvelle fiche d'emploi → alertes besoin et prix, décisions tracées ; simulation d'impact sans enregistrement, refus sans valeurs de référence |
| Cohérence | Cinq états (cohérent, écart, manquant, unité incompatible, ambigu) ; aucune décision automatique ; justification obligatoire |
| OCR | Image : OCR + classement proposé, confirmation obligatoire, aucun dépôt silencieux ; PDF scanné : OCR page par page |
| Excel | Formule modifiée, remplacée par une constante, `#REF!` détectées avec message clair ; import d'un export ORLI en lecture seule sans rapprochement automatique |
| EML | Sujet, expéditeur, date, suggestions d'engagement ; refus hors `.eml` |
| Recherche | 7 critères : commande, client, modèle, référence, nom, type, sous-dossier |
| Mémoire interne | Notes client, fournisseur, atelier ; lecture par dossier ; jamais renvoyées au Client |
| Client | Inscription « en attente », connexion refusée (403), activation, connexion, mauvais mot de passe (401), déconnexion |
| Workflow | Demande : brouillon → envoyée → en étude → acceptée (finale, 409), refus ; le client ne peut pas décider ; statut visible côté Client. Circuit de validation (auteur ≠ valideur, notification). Exigences et ambiguïtés. Matières |
| Client ↔ FRAMATEX | Pièce demandée → déposée → en vérification → à corriger → V2 → acceptée ; partage → visible par A seulement → retrait effectif, document interne conservé, pièces sensibles exclues ; demande fournisseur suivie sans email ; aperçu client simulé |
| Sécurité | Client B ne voit rien de A (404) ; session Client sans accès interne (401) ; compte suspendu (403) ; collaborateur : routes d'administration refusées (403), seule la rubrique autorisée visible ; accès restreint par dossier |
| Administration | Création d'un rôle et d'un collaborateur ; retours de recette pilote ; Framatex Assist déterministe ; vues de pilotage (200) |
| Audit | 141 opérations journalisées avec auteur, date, action et objet |

### Contrôles navigateur complémentaires

- **Captures** : 44 écrans Client et landing (14 × 3 largeurs + menus), 44 écrans
  FRAMATEX, 4 écrans collaborateur non administrateur.
- **Responsive** : `scrollWidth ≤ innerWidth` vérifié sur chaque capture.
- **Accessibilité** : 24 écrans contrôlés :
  - images avec `alt` ;
  - boutons et liens nommés ;
  - champs étiquetés ;
  - identifiants uniques ;
  - un seul `h1` ;
  - `lang="fr"` ;
  - focus visible sur 12 tabulations ;
  - menus mobiles fermés par Échap.
- **Vue collaborateur** (rôle limité à Jaune) : menu sans administration, rose /
  bleu / vert « Accès restreint », « Vue partielle », aucune erreur JavaScript,
  pas de défilement horizontal à 390 px.
- **OCR sans Tesseract** : l'image et le PDF scanné renvoient `ocr_unavailable`
  avec un message d'installation, sans erreur.
- **Performance** (premier chargement, cache vide) :

| Page | Requêtes | Poids | Erreurs réseau |
| --- | --- | --- | --- |
| Landing | 23 | 921 Ko | aucune |
| Espace Client | 14 | 430 Ko | aucune |
| Espace FRAMATEX (après connexion) | 32 | 680 Ko | 401 de sonde uniquement |

## 7. Captures

Planches dans `docs/qa-captures/` :

| Planche | Contenu |
| --- | --- |
| `01-landing-1440-390.jpg` | Landing desktop et mobile |
| `02-client-1440-acces.jpg` | Client : connexion, inscription |
| `03-client-1440-demandes.jpg` | Client : Mes demandes, détail d'une demande |
| `04-client-1440-documents.jpg` | Client : documents demandés, documents transmis, Mon compte |
| `05-client-820.jpg` | Client à 820 px |
| `06-client-390.jpg` | Client à 390 px |
| `07-framatex-1440-pilotage.jpg` | FRAMATEX : tableau de bord, commandes |
| `08-framatex-1440-dossier.jpg` | FRAMATEX : dossier jaune complet, document / versions |
| `09-framatex-1440-sous-dossiers.jpg` | FRAMATEX : Jaune, Rose, Bleu, Vert |
| `10-framatex-1440-controle.jpg` | FRAMATEX : audit, recherche, clients et demandes |
| `11-framatex-820.jpg` | FRAMATEX à 820 px |
| `12-framatex-390.jpg` | FRAMATEX à 390 px (connexion, dashboard, commandes, dossier, menu, clients) |
| `13-framatex-collaborateur.jpg` | FRAMATEX : vue d'un collaborateur non administrateur |
| `14-client-1440-workflow.jpg` | Client : pièce à corriger (message FRAMATEX, dépôt V2, historique), nouvelle demande, Mes documents |
| `15-client-etats-compte.jpg` | Client : entrée, compte en attente, compte suspendu |
| `16-framatex-1440-memoire-demande.jpg` | FRAMATEX : mémoire interne, fiche d'une demande client |

Les documents manquants figurent dans les planches 07 (dashboard) et 08
(dossier B).

## 8. Mise à jour `fix/windows-demo-final` : démonstration locale fiable

| Suite | Résultat |
| --- | --- |
| Tests Python (`pytest`) | **140 réussis** (+ 4 : Dossier Jaune depuis une demande ×3, guillemets du lanceur ×1) |
| Tests JS | **16 scripts réussis** |
| Recette API (`scripts/qa_platform_review.py`) | **87 / 87** (+ `/api/auth/me`, 4 sous-dossiers, documents non publiés, demande → Dossier Jaune) |
| Démonstration complète (`scripts/demo_full_platform.py`) | **111 / 111** : recette API + parcours Chromium (1440 de bout en bout, puis 1440 / 1024 / 820 / 390), 0 erreur JavaScript bloquante, aucun défilement horizontal |
| Recettes navigateur de Codex | Interne : 7 parcours, 52 captures ; Client : scénario complet ; aucune erreur JavaScript |
| Lanceur Windows | Syntaxe valide et 0 incompatibilité Windows PowerShell 5.1 (PSScriptAnalyzer) ; 11 tests de logique du port ; parcours réel `-Demo -CheckOnly` dans PowerShell 7 |

Bugs trouvés et corrigés :

| # | Bug | Correction |
| --- | --- | --- |
| 11 | Toute erreur du lanceur après le démarrage arrêtait le serveur (bloc de nettoyage), d'où `ERR_CONNECTION_REFUSED` | Erreurs signalées sans arrêter le serveur ; supervision jusqu'à Ctrl+C ou fermeture |
| 12 | Fenêtre fermée : serveur orphelin sur 8000, lancement suivant sur 8001, ancien onglet sur un port mort | Serveur lié à la fenêtre (objet « job » Windows) ; anciens serveurs FRAMATEX de ce dossier arrêtés au démarrage |
| 13 | Journaux du serveur dans la console : une sélection pouvait geler le serveur | Journaux redirigés vers `data\logs`, affichés par le lanceur |
| 14 | Apostrophes typographiques dans des chaînes PowerShell : script illisible pour PowerShell | Chaînes corrigées ; test de non-régression |
| 15 | Recette : mot de passe Client de recette écrit en dur | Mot de passe généré en mémoire |

Fonction ajoutée : **« Accepter et créer le Dossier Jaune »** depuis une demande Client.
- **Création.** Le dossier reçoit ses 4 sous-dossiers, le client, l'article et la
  quantité. Le numéro de demande devient la référence de commande.
- **Lien.** La référence client et la date souhaitée sont affichées dans la fiche
  commande. Le lien avec la demande est permanent (migration additive
  `0007_client_order_launch`), et l'opération est auditée.
- **Doublons.** Une seule création est possible : la base de données refuse la
  seconde, et un nouvel appel renvoie le dossier existant.
- **Accès.** La fonction est réservée aux administrateurs.

Un test de migration de Codex a été adapté. Il supposait que `0006` était la
dernière révision ; il sélectionne désormais explicitement les révisions
antérieures à `0006`. Sa vérification est inchangée.

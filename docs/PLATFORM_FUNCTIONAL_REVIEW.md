# Revue fonctionnelle de la plateforme FRAMATEX

Branche : `final/platform-review` — base : dernier commit de Codex
`032d029` (« feat: complete client request and document workflows »).
Recette du 21 octobre 2026, Chromium headless, largeurs 1440, 1024, 820 et 390 px.

> **Mise à jour `design/premium-ux-wow`** : checklist entièrement visible dès la
> création, état « Doublon détecté », tableau de bord « Documents à traiter »,
> finition premium (landing et deux espaces). Voir `docs/UX_PREMIUM_PASS.md`.
>
> **Mise à jour `design/final-framatex-ux`** : Dossier Jaune en checklist par
> sous-dossier (profil « Dossier Jaune FRAMATEX standard » appliqué automatiquement),
> tableau de bord centré sur les documents manquants, modules avancés regroupés en
> onglets, Espace Client à quatre entrées, landing réordonnée. Détails, checklists
> exactes et limites : `docs/UX_FINAL_FRAMATEX.md`. Recette : 171 tests Python,
> 18 scripts JS, 94 contrôles API, 132 contrôles de recette complète.

Ce document liste chaque fonction de la plateforme : ce qu'elle fait, où la
trouver, comment la tester et son état réel. Une fonction n'est notée
« Fonctionnel » que si elle a été exercée pendant la recette (API réelle, navigateur
ou suite de tests) et qu'elle s'est comportée comme décrit.

| Statut | Signification |
| --- | --- |
| **Fonctionnel** | Fonction complète, testée de bout en bout pendant la recette. |
| **Partiel** | Fonction utilisable mais volontairement limitée ; la limite est décrite. |
| **Non implémenté** | Absent de la plateforme. N'est présenté nulle part comme disponible. |

Colonne « Preuve » : `QA` = `scripts/qa_platform_review.py` (87 vérifications sur
serveur réel), `UI-int` = `scripts/validate_internal_ui.py`, `UI-cli` =
`scripts/validate_client_workflow_ui.py`, `pytest` / `JS` = suites de `tests/`,
`Nav` = parcours navigateur de recette (captures, accessibilité, responsive),
`Manuel` = vérification ponctuelle décrite dans `docs/FINAL_QA_REPORT.md`.

## Lancer la plateforme de démonstration

```bash
python -m pip install -r requirements-dev.txt
python -m app.migrate upgrade
python -m app.bootstrap_admin --email responsable@exemple.test --name "Responsable"
python -m app.seed_operations_demo --admin-email responsable@exemple.test   # dossiers fictifs A–E
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Recette automatique complète (base temporaire, aucune donnée réelle touchée) :

```bash
python scripts/qa_platform_review.py --output data/qa-platform     # API : 94 vérifications
python scripts/demo_full_platform.py --output data/demo-platform   # API + Chromium 1440/1024/820/390 : 132 vérifications
```

Sous Windows, une seule commande prépare et lance la démonstration :
`scripts\start_windows.cmd -Demo` (voir `docs/WINDOWS_LOCAL.md`).

Dossiers de démonstration : A `FR-DEMO-2026-0141` complet ; B `…0142` calcul du
besoin manquant (Jaune) ; C `…0143` pièce douanière manquante (Bleu) ; D `…0144`
fiche de prix en attente de validation ; E `…0145` fiche d'emploi V2, impact,
écart de quantité, anomalie Excel, email archivé.

---

## 1. Landing

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Page d'accueil publique | Hero → Notre solution (repères réels) → Nos espaces (« Choisissez votre espace ») → chaîne de valeur en 5 étapes → partenariat École Centrale Casablanca → appel à l'action → contact. Mouvements discrets désactivés en mouvement réduit. | `/` — `static/landing/index.html` | Ouvrir `/` en 1440 et 390 px. | Fonctionnel | QA, Nav |
| Accès aux deux espaces | Cartes photo vers l'Espace Client et l'Espace FRAMATEX. | `/` → `/espace-client`, `/espace-framatex` | Cliquer chaque carte. | Fonctionnel | QA, Nav |
| Contact | Liens `mailto:` et `tel:` (Maroc, France). Aucun formulaire. | Pied de page | Cliquer les liens. | Fonctionnel | Nav |
| Logo officiel | Seul le logo officiel `static/landing/logo-framatex.jpg` est utilisé (aussi favicon). | Les trois espaces | Comparer les en-têtes. | Fonctionnel | QA, Nav |
| Anciens liens QR | `/#/launch/<id>` est redirigé vers `/espace-framatex#/launch/<id>`. | `static/landing/landing-redirect.js` | Ouvrir `/#/launch/xyz`. | Fonctionnel | QA |
| Responsive et menu mobile | Mise en page 1440 → 390 px sans défilement horizontal. | `static/landing/landing.css` | Redimensionner, ouvrir le menu à 390 px. | Fonctionnel | Nav |
| Poids des pages | Photos servies en AVIF puis WebP (repli JPEG/WebP) : hero 107 → 47 Ko, espaces 217/231 → 89/91 Ko. | — | DevTools > Réseau. | Fonctionnel | Nav |

## 2. Espace Client

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Entrée | Choix « Se connecter » / « Créer un compte ». | `/espace-client` | Ouvrir la page. | Fonctionnel | UI-cli, Nav |
| Inscription | Raison sociale, contact, email, téléphone, adresse, pays, identifiant fiscal facultatif, mot de passe ≥ 12 caractères. Le compte est créé « en attente ». | `#/inscription` | S'inscrire puis tenter de se connecter. | Fonctionnel | QA, UI-cli |
| Connexion | Cookie de session HttpOnly limité à `/api/client`. Mauvais mot de passe : refus générique 401 ; trop de tentatives : 429. | `#/connexion` | Se connecter avec un compte actif / un mauvais mot de passe. | Fonctionnel | QA, pytest |
| Compte en attente | Écran dédié après un refus `403 account_pending`. | `#/en-attente` | Se connecter avant activation. | Fonctionnel | QA, UI-cli |
| Compte suspendu | Écran dédié ; la session ouverte est refusée immédiatement. | `#/suspendu` | Suspendre le compte côté FRAMATEX. | Fonctionnel | QA, UI-cli |
| Mes demandes | Liste des demandes de commande avec statut en français. | `#/demandes` | Se connecter avec un compte actif. | Fonctionnel | QA, UI-cli |
| Nouvelle demande | Article, quantité, date souhaitée, référence, commentaire, pièces jointes ; brouillon ou envoi. | `#/demandes/nouvelle` | Enregistrer un brouillon, puis l'envoyer. | Fonctionnel | QA, UI-cli |
| Détail d'une demande | Statut, informations, vos documents déposés, documents demandés par FRAMATEX et documents reçus pour cette demande. | `#/demandes/<id>` | Ouvrir une demande. | Fonctionnel | UI-cli, Nav |
| Menu | Quatre entrées : Mes demandes, Nouvelle demande, Documents (onglets À fournir · Reçus de FRAMATEX · Mes dépôts, pastille des pièces à fournir), Mon compte. | Menu latéral / tiroir | Ouvrir « Documents ». | Fonctionnel | JS, Nav |
| Documents demandés par FRAMATEX | Pièces attendues : À déposer → Déposée → En vérification → À corriger → Acceptée. | `#/documents-demandes` | Déposer une pièce demandée. | Fonctionnel | QA, UI-cli |
| Correction / nouvel envoi | Le message de FRAMATEX s'affiche en bandeau ; le nouvel envoi crée une V2, la V1 reste téléchargeable. | `#/documents-demandes/<id>` | Demander une correction côté FRAMATEX puis redéposer. | Fonctionnel | QA, UI-cli |
| Documents transmis par FRAMATEX | Versions explicitement partagées, téléchargeables ; disparaissent dès le retrait. | `#/documents-transmis` | Partager puis retirer côté FRAMATEX. | Fonctionnel | QA, UI-cli |
| Mes documents | Toutes les pièces déposées par le client. | `#/documents` | Ouvrir après un dépôt. | Fonctionnel | UI-cli, Nav |
| Mon compte | Affiche les informations du compte. | `#/compte` | Ouvrir la page. | Partiel — lecture seule : pas de modification du profil ni de changement de mot de passe. | Nav |
| Mot de passe oublié | — | — | — | Non implémenté | — |
| Déconnexion | Révoque la session côté serveur. | Menu | Se déconnecter puis recharger. | Fonctionnel | QA |
| Notifications email au client | Les événements sont journalisés pour une future notification. | — | — | Non implémenté — aucun email n'est envoyé. | — |

## 3. Espace FRAMATEX

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Connexion collaborateurs | Email + mot de passe internes (système existant, inchangé). | `/espace-framatex` | Bon / mauvais mot de passe. | Fonctionnel | QA |
| Tableau de bord | Dans l'ordre : 9 indicateurs → Actions prioritaires → **Documents à traiter** (onglets Manquants · En validation · Doublons avec compteurs ; Sous-dossier, Document, Commande, Client, État, Action ; filtre par sous-dossier) → Complétude des dossiers → Alertes importantes → Activité récente. Un clic ouvre le dossier, le sous-dossier et la ligne. | Tableau de bord | Cliquer « Doublons » puis « Examiner ». | Fonctionnel | pytest, JS, UI-int, Nav |
| Commandes et lancements | Liste filtrable : référence, client, modèle, complétude, statut, dates d'activité, alertes. | Commandes et lancements | Filtrer sur « Incomplet ». | Fonctionnel | UI-int, pytest |
| Création / modification de dossier | Création avec les quatre sous-dossiers ; référence ORLI facultative. | « Nouveau dossier », « Modifier le dossier » | Créer un dossier. | Fonctionnel | QA, pytest |
| Suivi métier | Article, quantité, références provisoire et définitive, responsable. | Fiche commande du dossier | « Modifier le suivi métier ». | Fonctionnel | pytest, UI-int |
| Mes actions | Priorités consolidées (pièces manquantes, validations, impacts, incohérences, Excel). | Mes actions | Ouvrir une action. | Fonctionnel | QA, pytest |
| Notifications internes | Notifications dans l'application (circuits de validation). | Notifications | Lancer un circuit de validation. | Fonctionnel — dans l'application seulement, pas d'email. | QA, pytest |
| Framatex Assist | Guide de procédures à réponses fixes (aucune IA, aucun modèle de langage). Réponse « Question à préciser » si aucune procédure ne correspond. | Assistant | Poser « Où déposer un document ? ». | Fonctionnel (guide déterministe) | QA, pytest |
| Chatbot / assistant IA | — | — | — | Non implémenté — hors périmètre. | — |
| Recette pilote | Signalement d'anomalies par les collaborateurs, résolution motivée par l'administrateur. | Recette pilote | Créer puis résoudre un signalement. | Fonctionnel | QA, pytest |
| Administration | Création de rôles (droits par rubrique) et de comptes collaborateurs. | Administration | Créer un rôle et un compte. | Partiel — pas de réinitialisation ni de changement de mot de passe dans l'interface. | QA, pytest |
| Vue collaborateur non administrateur | Menu sans les entrées d'administration ; rubriques non autorisées affichées « Accès restreint ». | Toute l'application | Se connecter avec un rôle limité à Jaune. | Fonctionnel | QA, Nav |
| Responsive et menu mobile | Tiroir de navigation à 820 et 390 px, fermeture par Échap. | Toute l'application | Réduire à 390 px. | Fonctionnel | UI-int, Nav |

## 4. Dossier Jaune

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| En-tête | Commande, client, modèle, quantité, date souhaitée, référence client, ORLI si renseigné, état, complétude X / Y et étape. | En tête du dossier | Ouvrir le dossier B. | Fonctionnel | UI-int, Nav |
| Quatre sous-dossiers | Technique, Réception, Dédouanement, Factures : X / Y présents, barre, manquants, à valider, à venir. | Cartes 01 à 04 | Cliquer chaque carte. | Fonctionnel | UI-int, Nav |
| Checklist par sous-dossier | Les 22 lignes standard visibles dès la création. États : Présent, Manquant, En validation, Exception, Doublon détecté, Non applicable (facultatif). Dernière version, date, action (Déposer prérempli, Valider, Ouvrir, Examiner le doublon). | Onglet Documents | Dossier créé depuis une demande. | Fonctionnel | pytest, JS, Nav |
| Repères couleur | Filet supérieur et pictogramme teintés par rubrique (jaune, rose, bleu, vert). Discrets, l'interface reste bleu nuit. | Cartes et en-têtes de rubrique | Visuel. | Fonctionnel | Nav (planche 09) |
| Droits par rubrique | Une rubrique non autorisée n'expose ni titre, ni compteur, ni document. | Cartes « Accès restreint » | Rôle limité à Jaune. | Fonctionnel | QA, Nav |
| Accès restreint par dossier | L'administrateur réserve un dossier à des membres nommés. | Panneau d'accès du dossier | Restreindre, ajouter puis retirer un membre. | Fonctionnel | QA, pytest |
| Onglets | Documents · Contrôles · Communication · Historique ; tous les modules avancés conservés en sous-navigation. Précautions regroupées dans « À savoir ». | Sous les cartes | Contrôles → Simulation. | Fonctionnel | UI-int, Nav |
| QR et passeport | Étiquette papier avec QR vers le dossier ; passeport d'une version (hash, auteur, date). | Section « QR et passeports » | Imprimer l'étiquette, ouvrir un passeport. | Fonctionnel | QA, pytest |

## 5. Documents

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Dépôt | PDF, DOCX, XLSX, PNG, JPG/JPEG, TXT, EML, CSV. Glisser-déposer ou bouton. | « Déposer un document » de chaque rubrique | Déposer un fichier de chaque format. | Fonctionnel | QA (8 formats) |
| Refus | Exécutable, faux PDF (signature), fichier > 20 Mo, rubrique invalide, XLS ancien. | Même formulaire | Déposer un `.exe` renommé. | Fonctionnel | QA |
| Contrôle côté navigateur | Fichier > 20 Mo refusé avant envoi ; bouton désactivé pendant le dépôt (pas de double envoi). | Formulaires de dépôt et de version | Déposer un gros fichier. | Fonctionnel | Nav |
| SHA-256 | Empreinte calculée et conservée ; téléchargement octet pour octet identique. | Historique d'un document | Comparer avec `sha256sum`. | Fonctionnel | QA |
| Doublons | Même contenu (SHA-256) dans plusieurs documents du dossier, sous-dossiers lisibles uniquement : « Doublon détecté » sur la ligne, la carte et au tableau de bord ; décision motivée et auditée pour conserver, ou nouvelle version pour corriger. Version identique d'un même document : refusée (409). | Dépôt, ligne de checklist | Déposer deux fois le même email. | Fonctionnel | QA, pytest, Nav |
| Versions V1 → V2 → V3 | Anciennes versions conservées et téléchargeables, auteur et date, validations jamais transférées. | « Historique » d'un document | Ajouter deux versions. | Fonctionnel | QA |
| Commentaires de version | Commentaire attribué et horodaté sur une version précise. | Fiche version | Commenter la V2. | Fonctionnel | QA |
| Revue simple | Approuver / demander une correction sur une version. | Fiche version | Approuver la fiche de prix (dossier D). | Fonctionnel | QA, pytest |
| Antivirus | — | — | — | Non implémenté — les contrôles de format ne remplacent pas un antivirus. | — |

## 6. Complétude

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Profil standard automatique | « Dossier Jaune FRAMATEX standard » (22 lignes, 19 obligatoires exigibles dès la création, 3 facultatives) appliqué depuis une demande Client et « Nouveau dossier ». L'étape de la commande ne masque aucune pièce. Jamais dupliqué ni imposé sur un profil existant. | Création du dossier | Accepter une demande Client. | Fonctionnel | pytest, Nav |
| Pièces facultatives | Règle `required = false` : jamais exigible, donc jamais manquante (migration 0008). | Checklist | Emails techniques. | Fonctionnel | pytest |
| Profils et règles | Profils de complétude par type de dossier, règles par rubrique et étape. | Administration (API `/api/admin/completeness/*`) | Lister les profils. | Fonctionnel | pytest |
| Contexte du dossier | Profil + étape (approvisionnement, fabrication, expédition…). | « Profil et étape » | Passer C de l'expédition à l'approvisionnement. | Fonctionnel | QA |
| Cinq états | `present`, `missing`, `pending_validation`, `not_due`, `exception`. | Section « Complétude documentaire » | Voir B (missing), C (not_due / exception), D (pending_validation). | Fonctionnel | QA (5 états observés) |
| `not_due` ≠ `missing` | Une pièce non exigible à l'étape n'est jamais comptée manquante ni dans le dénominateur. | Pourcentage et dashboard | Dossier C à l'approvisionnement. | Fonctionnel | QA |
| Exception motivée | Dérogation avec motif ; ne produit pas artificiellement 100 %. | Ligne de règle | Poser une exception sur C. | Fonctionnel | QA |
| Documents manquants | Liste globale reliée à la commande et à la rubrique. | Dashboard, dossier | Cliquer « Calcul du besoin » (B). | Fonctionnel | QA, UI-int |

## 7. Workflow

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Demande de commande client | `draft` → `submitted` (client) → `under_review` → `accepted` / `rejected` (FRAMATEX). États finaux bloqués (409) ; le client ne peut pas décider. | Client : Mes demandes · FRAMATEX : Clients et demandes | Envoyer, étudier, accepter. | Fonctionnel | QA, UI-cli |
| Demande de pièce au client | `requested` → `uploaded` → `under_review` → `correction_required` → `accepted`, décision sur la version courante uniquement. | Clients et demandes > « Documents demandés / partages » | Parcours complet avec correction. | Fonctionnel | QA, UI-cli |
| Circuits de validation | Étapes séquentielles par rôle ; l'auteur ne peut pas valider sa propre pièce ; notification du valideur. | Section « Circuits de validation » | Lancer un circuit sur une fiche. | Fonctionnel | QA, pytest |
| Exigences client | Exigence issue d'un document source, preuve obligatoire avant vérification, invalidée si la source ou la preuve change. | Section « Exigences client » | Ajouter une exigence, une preuve, vérifier. | Fonctionnel | QA, pytest |
| Ambiguïtés | Question tracée, résolution avec note obligatoire. | Section « Exigences client » | Ouvrir puis résoudre une ambiguïté. | Fonctionnel | QA, pytest |
| Matières | Besoin documenté, mouvements commandés / reçus justifiés par une pièce, annulation tracée. | Section « Traçabilité des matières » | Ajouter une ligne et un mouvement. | Fonctionnel | QA, pytest |
| Engagements issus d'emails | Suggestions d'engagements à confirmer par un humain. | Section « Emails et engagements » | Importer un `.eml` (dossier E). | Fonctionnel | QA, pytest |
| Accepter et créer le Dossier Jaune | Depuis une demande envoyée, en étude ou acceptée : acceptation si besoin, puis ouverture du dossier avec ses 4 sous-dossiers, client, article, quantité, numéro de demande ; référence client et date souhaitée affichées dans la fiche commande ; lien permanent ; audit ; une seule création possible (base de données). | Clients et demandes > fiche de la demande | Ouvrir une demande envoyée, cliquer « Accepter et créer le Dossier Jaune ». | Fonctionnel | QA, Nav, pytest |
| Acceptation → écriture ORLI | — | — | — | Non implémenté — aucun échange avec ORLI (hors périmètre). | — |

## 8. Alertes

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Alertes d'impact | Une nouvelle version (ex. fiche d'emploi) signale les pièces liées à revoir (calcul du besoin, fiche de prix). | Section « Décisions et impacts », dashboard | Nouvelle version de la fiche d'emploi (E). | Fonctionnel | QA |
| Décisions sur impact | Pris en compte / sans impact / à traiter, avec auteur et date. | Ligne d'alerte | Prendre une décision. | Fonctionnel | QA |
| Cohérence documentaire | Compare les valeurs enregistrées : cohérent, écart, donnée manquante, unité incompatible, ambigu. Aucune décision automatique. | Section « Fiabilité documentaire » | Écart de quantité (E). | Fonctionnel | QA (5 états) |
| Décision de cohérence | Justification humaine obligatoire (422 sinon). | Ligne de contrôle | Décider sans note. | Fonctionnel | QA |
| Simulation d'impact | Calcule l'effet d'une variation (consommation, quantité, coût) sans rien enregistrer ; refuse de calculer sans valeurs de référence. | Section « Graphe des dépendances et simulation » | Simuler 1,9 m/pièce. | Fonctionnel | QA, pytest |

## 9. OCR

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Lecture du contenu | PDF texte, PDF scanné (OCR page par page), image (OCR), DOCX, XLSX (valeurs), TXT, EML. | Section « Lecture et classement assistés » | Analyser un scan. | Fonctionnel — nécessite Tesseract (`fra`, `eng`) et PyMuPDF sur le serveur. | QA (image et PDF scanné) |
| Classement proposé | Type documentaire et rubrique suggérés, champs extraits (quantité, références…). | Même section | Analyser « calcul-du-besoin.png ». | Fonctionnel | QA |
| Confirmation humaine | Aucun document n'est créé sans confirmation explicite. | Même section | Vérifier le nombre de documents avant / après. | Fonctionnel | QA |
| Sans Tesseract | Méthode `ocr_unavailable` et message d'installation, pas d'erreur (image et PDF scanné). | — | Serveur sans Tesseract dans le `PATH`. | Fonctionnel | Manuel |

## 10. Excel

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Inspection des classeurs | Entre deux versions XLSX : formule modifiée, formule remplacée par une constante, `#REF!`, avec cellule et valeurs avant / après. | Section « Système immunitaire Excel » | Déposer une V2 d'un classeur modifié. | Fonctionnel | QA |
| Sécurité | Classeurs jamais exécutés ; XLS ancien refusé. | — | Déposer un `.xls`. | Fonctionnel | pytest |
| Import d'un export ORLI | Import de fichier CSV/tabulaire en lecture seule, rapprochement explicite par un humain. | Imports ORLI | Importer un CSV puis rapprocher. | Partiel — import de fichier uniquement, aucune connexion à ORLI. | QA, pytest |
| Intégration ORLI réelle | — | — | — | Non implémenté — hors périmètre. | — |

## 11. Recherche

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Recherche documentaire | Par commande, client, modèle, référence, nom de document ou de fichier, empreinte SHA-256, type documentaire, sous-dossier ; toutes les versions ; filtres de dates ; pagination. | Documents / recherche, raccourci « Rechercher » | Chercher `FR-DEMO-2026-0145`. | Fonctionnel | QA (7 critères) |
| Respect des droits | Aucun résultat issu d'une rubrique non autorisée. | — | Chercher avec un rôle limité à Jaune. | Fonctionnel | QA |
| Recherche plein texte dans le contenu | — | — | — | Non implémenté — la recherche porte sur les métadonnées, pas sur le texte des fichiers. | — |

## 12. Audit

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Journal | Dépôts, versions, revues, commentaires, décisions, exceptions, notes, comptes clients, statuts, publications, retraits, téléchargements. | Historique et audit | Filtrer sur « Nouvelle version ». | Fonctionnel | QA (141 opérations) |
| Lecture | Libellé français, code technique discret, détails sous forme de pastilles (empreinte tronquée). | Même écran | Ouvrir une ligne. | Fonctionnel | Nav |
| Filtres | Auteur, dossier, document, action, période, pagination. | Même écran | Filtrer par auteur. | Fonctionnel | pytest, UI-int |

## 13. Mémoire interne

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Notes d'expérience | Retours client, fournisseur, atelier liés à un dossier, attribués et datés. | Bas du dossier, « Mémoire d'expérience interne » | Ajouter un retour atelier. | Fonctionnel | QA |
| Vue transversale | Historique de toutes les notes des dossiers accessibles. | Mémoire interne | Ouvrir l'écran. | Fonctionnel | QA, Nav |
| Confidentialité | Notes et commentaires jamais renvoyés par les API Client. | — | Comparer les réponses Client. | Fonctionnel | QA |

## 14. Client ↔ FRAMATEX

| Fonction | Ce qu'elle fait | Où | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- | --- |
| Activation / suspension | L'administrateur active un compte en attente ou le suspend. | Clients et demandes > Comptes clients | Activer un compte. | Fonctionnel | QA, UI-cli |
| Demandes de commande reçues | Lecture, pièces jointes téléchargées (audit), décision de statut. | Clients et demandes > Demandes de commande | Passer une demande en étude. | Fonctionnel | QA, UI-cli |
| Demander une pièce | Pièce attendue rattachée au compte et à sa demande (compte déterminé côté serveur). | « Documents demandés / partages » | Demander un « Certificat ». | Fonctionnel | QA, UI-cli |
| Vérifier, corriger, accepter | Décision sur la version courante ; correction avec message obligatoire. | Même panneau | Demander une correction. | Fonctionnel | QA, UI-cli |
| Partager un document | Publication explicite d'une version approuvée et admissible ; fiches de prix, coûts, marges, factures et documents internes exclus. | Même panneau, ou fiche version | Partager une confirmation de commande. | Fonctionnel | QA, UI-cli |
| Retirer un partage | Retrait immédiat (404 côté client), document interne conservé. | Même panneau | Retirer puis tester le lien. | Fonctionnel — un fichier déjà téléchargé ne peut pas être repris. | QA, UI-cli |
| Publication et aperçu simulés (module antérieur) | Prévisualisation interne de ce qu'un client verrait ; n'ouvre aucun accès réel. | Section « Échanges documentaires » | Ouvrir l'aperçu client. | Partiel — simulation interne, distincte du partage réel. | QA, pytest |
| Demandes fournisseurs | Suivi interne d'une pièce attendue d'un fournisseur, résolution avec la version reçue. | Section « Échanges documentaires » | Créer une demande. | Partiel — suivi interne seulement, aucun email ni portail fournisseur. | QA, pytest |

## 15. Sécurité

| Fonction | Ce qu'elle fait | Comment tester | Statut | Preuve |
| --- | --- | --- | --- | --- |
| Sessions | Cookies HttpOnly séparés (interne / client) ; aucun jeton dans `localStorage`, `sessionStorage` ou `document.cookie`. | Inspecter le stockage du navigateur. | Fonctionnel | pytest, JS |
| Protection des écritures | En-tête `X-Framatex-Request: 1` obligatoire (403 sinon). | POST sans en-tête. | Fonctionnel | QA |
| En-têtes HTTP | CSP `default-src 'self'`, `frame-ancestors 'none'` ; polices et visuels servis localement. | Lire les en-têtes de `/`. | Fonctionnel | QA |
| Isolation Client A / B | B ne voit ni demandes, ni pièces, ni partages de A (404). | Parcours A/B. | Fonctionnel | QA, UI-cli |
| Cloisonnement Client / interne | Une session Client n'ouvre aucune API interne (401). | Appeler `/api/workspace/dashboard` en client. | Fonctionnel | QA |
| Droits internes | Rôles par action et par rubrique ; routes d'administration refusées aux collaborateurs (403). | Rôle limité à Jaune. | Fonctionnel | QA, Nav |
| Mots de passe | Hash Argon2, limitation des tentatives, refus générique. | Mauvais mot de passe répété. | Fonctionnel | pytest |
| Fichiers | Noms disque aléatoires, signatures contrôlées, 20 Mo maximum, intégrité vérifiée avant partage. | Dépôts refusés. | Fonctionnel | QA |
| Migration | Base vierge et copie d'une base existante : migration rejouable, aucune perte. | `python -m app.migrate upgrade` deux fois. | Fonctionnel | QA, pytest |

## 16. Limites restantes

Rien ci-dessous n'est présenté comme disponible dans l'interface.

- **Hors périmètre (volontairement non traité)** : chatbot, API d'IA, RAG,
  Ollama, identifiants ou matricules de techniciens, refonte du système interne
  email + mot de passe, intégration ORLI réelle.
- **Emails** : aucun envoi (client, fournisseur, collaborateur). Les événements
  sont journalisés pour une future notification.
- **Mots de passe** : pas de « mot de passe oublié » ni de changement de mot de
  passe, côté Client comme côté FRAMATEX.
- **Profil client** en lecture seule.
- **ORLI** : import de fichier uniquement.
- **Dossier créé depuis une demande** : ouvert sans profil de complétude ; le choisir ensuite avec « Profil et étape ». Aucune écriture ORLI.
- **Retrait d'un partage** : un fichier déjà téléchargé reste chez le client.
- **Recherche** sur les métadonnées seulement, pas sur le texte des fichiers.
- **OCR** dépendant de Tesseract (`fra`, `eng`) et PyMuPDF sur le serveur.
- **Antivirus** absent : les contrôles de format ne le remplacent pas.
- **Base SQLite** : adaptée à un pilote mono-serveur ; prévoir une sauvegarde de
  `data/` avant toute mise à niveau.
- **Contexte de complétude** : l'API efface le profil si `profile_id` est omis
  lors d'une modification de l'étape (l'interface l'envoie toujours).
- **Navigateur** : la sonde de session `/api/auth/me` produit un 401 normal
  dans la console avant connexion ; le format des champs date suit la langue du
  navigateur.
- **Mobile** : le bouton « Profil et étape » passe sur deux lignes à 390 px
  (sans gêne d'usage).

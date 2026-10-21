# Passe premium et logique documentaire visible — FRAMATEX

Branche : `design/premium-ux-wow` — base : `design/final-framatex-ux` (`1d8414f`).
Aucune fusion dans `main`. Logo : uniquement `static/landing/logo-framatex.jpg`.
Aucune image ni logo généré, aucun texte incrusté dans une image.

## 1. Dossier Jaune : tout est visible dès la création

Avant, une pièce pouvait être « Non exigible » tant qu'une étape n'était pas
atteinte. Désormais, dès qu'un Dossier Jaune est créé (depuis une demande Client
ou « Nouveau dossier ») :

- les 4 sous-dossiers et les 22 lignes de la checklist standard sont visibles ;
- chaque pièce obligatoire absente est **Manquant** immédiatement, quelle que soit
  l'étape de la commande ;
- l'étape reste une information de suivi (« Étape de la commande · Changer ») ;
  elle ne masque ni ne repousse plus aucune pièce du profil standard.

| État | Quand | Compté manquant ? |
| --- | --- | --- |
| Présent | Pièce déposée (et validée si la ligne l'exige) | non |
| Manquant | Pièce obligatoire absente | **oui** |
| En validation | Déposée, validation requise (Fiche d'emploi, Fiche de prix, Réception matière) | non |
| Exception | Dérogation motivée | non |
| Doublon détecté | Même contenu qu'une autre pièce du dossier, non examiné | non (la pièce reste présente) |
| Non applicable | Pièce facultative non déposée (emails, avoir) | non |

Exemple réel (dossier de démonstration, sous-dossier Réception) : Bon de
livraison → Manquant · Bon / note de réception → Présent · Document de réception
matière → En validation · Emails réception / logistique → Doublon détecté.

Mise en œuvre, compatible avec l'existant :

- le moteur de complétude est inchangé ; seul le **profil standard** change : ses
  règles obligatoires sont exigibles dès la création, et la réception matière
  demande une validation (migration `0009_visible_checklist_duplicates`, avec la
  sauvegarde SQLite automatique habituelle) ;
- les autres profils (dont les dossiers de démonstration A–E) gardent leurs étapes ;
  une règle non exigée y apparaît « Non applicable », sans mention d'étape ;
- en-tête du dossier : synthèse « présents · manquants · en validation · doublons » ;
  cartes de sous-dossier avec anneau de progression et compteurs.

## 2. Doublons

- **Détection** : même empreinte SHA-256 sur les versions courantes de plusieurs
  documents d'un même dossier, tous sous-dossiers lisibles par l'utilisateur
  (un document identique dans un sous-dossier non autorisé n'est jamais révélé).
  L'alerte existante au dépôt (même sous-dossier) est conservée ; une version
  identique d'un même document reste refusée (409).
- **Affichage** : état « Doublon détecté » sur la ligne concernée (« Contenu
  identique à … »), compteur sur la carte du sous-dossier, onglet « Doublons » et
  indicateur « Doublons à examiner » au tableau de bord.
- **Traitement**, depuis « Examiner le doublon » :
  1. pièce déposée par erreur : l'ouvrir et déposer la bonne version, elle quitte
     le groupe ;
  2. pièces à conserver toutes les deux : motif obligatoire (8 caractères minimum),
     décision auditée (`document.duplicate.review`). La décision ne couvre que les
     versions examinées : une nouvelle copie identique relance l'alerte.
- **Droits** : examiner un doublon demande `document.review` sur chaque
  sous-dossier concerné.
- **API** : `GET /api/launches/{id}/duplicates`,
  `POST /api/launches/{id}/duplicates/review` `{sha256, reason}` ; table additive
  `document_duplicate_reviews`.

## 3. Tableau de bord

Panneau **Documents à traiter** : trois onglets avec compteurs (Manquants · En
validation · Doublons), filtre par sous-dossier, colonnes Sous-dossier · Document ·
Commande / dossier · Client · État · Action. « Ouvrir » / « Examiner » ouvre le
dossier, le bon sous-dossier, et met en évidence la ligne concernée. Nouvel
indicateur « Doublons à examiner » (9 indicateurs au total) ; les chiffres
montent une fois par session (sauf mouvement réduit).

## 4. Landing

- Hero : profondeur légère (la photo et le texte se déplacent à des profondeurs
  différentes selon le pointeur), parallaxe au défilement, lumière douce qui suit
  le pointeur, entrée en cascade du titre, de l'accroche et des boutons.
- Photos des sections (solution, espaces, partenariat) : parallaxe dans leur cadre.
- Cartes d'espace : légère perspective qui suit la souris, reflet discret.
- Chaîne de valeur : trait qui se dessine, lueur qui le parcourt, chaque étape
  s'allume à son passage ; survol : point et titre mis en valeur.
- Révélations au défilement plus douces (montée et netteté), repères chiffrés qui
  se tracent, CTA avec reflet au survol, trame textile qui glisse très lentement,
  en-tête translucide.
- Une seule boucle `requestAnimationFrame`, uniquement `transform` / `opacity`,
  éléments hors écran ignorés ; inclinaison et lumière seulement à la souris ;
  parallaxe désactivée sous 641 px ; **tout est coupé en mouvement réduit**.
  Aucun WebGL, aucune bibliothèque.

## 5. Espace FRAMATEX et Espace Client

Même vocabulaire visuel que la landing, sans en faire une page vitrine :

- ruban aux quatre couleurs des sous-dossiers sous la marque et en tête de page ;
  trame textile très discrète dans les en-têtes et la synthèse du dossier ;
- cartes et panneaux plus nets (rayon 14 px, ombre douce, relief au survol) ;
- boutons avec léger relief et réponse au clic ; badges et états affinés ;
- transitions de vue courtes (0,4 s) seulement quand l'écran change ;
- barre supérieure translucide fixée ; modales sur fond flouté ;
- Espace Client : bandeau d'accueil (demandes en cours, acceptées, pièces à
  fournir), frise d'avancement de chaque demande (Brouillon → Envoyée → En cours
  d'étude → Acceptée / Refusée), lignes de demandes animées au survol.

Feuilles et scripts : `static/brand/premium.css`, `static/premium.js`,
compléments dans `static/brand/dossier.css`, `static/client/client.css`,
`static/landing/landing.css`, `static/landing/landing.js`.

## 6. Compatibilité

Routes, API existantes, versionnage, dépôts, workflow Client, runtime Windows
(lanceur, diagnostic, journaux) inchangés. Les recettes ont été adaptées aux
nouvelles règles : 9 indicateurs (au lieu de 8), titre « Documents à traiter »,
cas C/D (pièces désormais manquantes dès la création), parcours doublon ajouté.

## 7. Vérifications

| Contrôle | Résultat |
| --- | --- |
| Tests Python (`pytest`) | 174 réussis (171 avant la passe, + doublons, droits, migration 0009) |
| Tests JS (`tests/*.cjs`) | 18/18 (dont `test_dossier_frontend.cjs` étendu : états, doublons, onglets du tableau de bord) |
| Recette API (`qa_platform_review.py`) | 94/94 |
| Recette complète (`demo_full_platform.py`) | 133/133, dont 39 contrôles Chromium (nouveau parcours doublon) |
| Recette interne (`validate_internal_ui.py`) | 7 parcours, 52 captures, 0 erreur JavaScript |
| Recette Client (`validate_client_workflow_ui.py`) | 15 étapes validées |
| Responsive 1440 / 1024 / 820 / 390 | aucun défilement horizontal |
| Accessibilité (contrôle scripté) | aucun bouton sans nom, champ sans étiquette, image sans `alt`, identifiant dupliqué ni texte visible sous 4,5:1 |
| Fluidité landing (Chromium headless, défilement complet) | images de 16,7 ms en médiane, 16,8 ms au 95e centile, aucune tâche longue |
| Mouvement réduit | aucun effet activé (profondeur, parallaxe, inclinaison, révélations, compteurs) |

## 8. Captures

`docs/ux-captures/<écran>-<largeur>.jpg` (1440, 1024, 820, 390 px) : landing,
Espace Client (demandes, documents, nouvelle demande, détail avec frise),
tableau de bord, documents manquants, **documents en doublon**, Dossier Jaune,
Technique, **Réception (manquant / présent / en validation / doublon)**,
Dédouanement, Factures, acceptation FRAMATEX, dossier créé, **modale « Doublon
détecté »**.

## 9. Points mineurs restants

- Les dossiers de démonstration A–E gardent un profil par étapes (recettes
  historiques) : leurs pièces non exigées s'affichent « Non applicable ».
- Une pièce déposée par erreur ne peut pas être supprimée (choix d'audit existant) :
  on la corrige par une nouvelle version ou on conserve le doublon avec un motif.
- Aucune nouvelle photo : les domaines d'images générées restent bloqués par le
  réseau de l'environnement ; les photos validées du dépôt sont réutilisées.

# Simplification métier et design final — FRAMATEX

Branche : `design/final-framatex-ux` — base : `fix/windows-runtime-final` (`2675bc4`).
Aucune fusion dans `main`. Aucun logo généré : seul `static/landing/logo-framatex.jpg`
est utilisé, en petite taille, dans les trois espaces.

> **Mise à jour `design/premium-ux-wow`** — toute la checklist est visible et
> exigible dès la création du Dossier Jaune (plus de pièce « en attente d'une
> étape ») ; nouvel état **Doublon détecté** ; tableau de bord « Documents à
> traiter » (manquants, en validation, doublons) ; finition premium de la landing
> et des deux espaces. Détails : `docs/UX_PREMIUM_PASS.md`.

L'objectif : qu'un collaborateur FRAMATEX passe 80 % de son temps sur une
seule question — *quelles pièces manquent dans ce Dossier Jaune, et où les déposer ?* —
et n'ouvre les contrôles avancés que lorsqu'il en a besoin.

```
Commande → Dossier Jaune → 4 sous-dossiers → checklist → manquants → dépôt → validation → complet
```

## 1. Dossier Jaune

### En-tête

Commande, client, modèle / article, quantité, date souhaitée (ou date d'ouverture),
référence client, référence ORLI si renseignée, état, complétude « X / Y pièces
exigibles présentes » avec barre, étape courante et lien « Changer l'étape ».
Si le dossier vient d'une demande Client : « Ouvert depuis la demande Client … ·
Voir la demande ». Actions : **Déposer un document** (principale), Suivi de la
commande, Modifier, Gérer les accès.

### Quatre cartes

Technique (jaune), Réception (rose), Dédouanement (bleu), Factures (vert). Chaque
carte : X / Y documents présents parmi les pièces exigibles, barre de progression
à la couleur du sous-dossier, puis « N manquants · k à valider · Complet · n à venir ».
La couleur reste un repère (filet supérieur, barre) ; la hiérarchie est bleu nuit.

### Checklist (une ligne par type de document)

Colonnes : Document · État · Dernière version · Date · Action. V1, V2, V3 d'un même
type restent sur la même ligne (la dernière version est affichée ; l'historique
s'ouvre depuis « Ouvrir » ou « Examiner »).

| État | Sens | Action proposée |
| --- | --- | --- |
| Présent | Pièce déposée (et validée si la règle l'exige) | Ouvrir |
| Manquant | Pièce obligatoire absente (dès la création du dossier) | Déposer (modale préremplie) |
| En validation | Déposée, validation requise | Valider · Examiner |
| Exception | Dérogation motivée (motif affiché) | — |
| Doublon détecté | Même contenu (SHA-256) qu’une autre pièce du dossier, non examiné | Examiner le doublon |
| Non applicable | Pièce facultative non déposée (ou règle d'un autre profil non exigée) | Déposer (lien discret) |

« Non applicable », « Exception » et « Doublon détecté » ne sont jamais comptés
comme manquants ; un doublon reste compté présent.
Les autres pièces du sous-dossier (types hors checklist) restent listées sous la
checklist, sans être perdues.

### Checklists exactes (profil « Dossier Jaune FRAMATEX standard »)

| Sous-dossier | Ligne | Type documentaire | Exigible | Particularité |
| --- | --- | --- | --- | --- |
| Technique | Dossier technique client | Dossier technique client | dès la création | |
| Technique | Commande client | Commande client | dès la création | |
| Technique | Lancement provisoire | Lancement provisoire | dès la création | |
| Technique | Lancement définitif | Lancement définitif | dès la création | |
| Technique | Fiche d'emploi | Fiche d'emploi | dès la création | validation requise |
| Technique | Calcul du besoin | Calcul du besoin | dès la création | |
| Technique | Fiche de prix | Fiche de prix | dès la création | validation requise |
| Technique | Étude BE / Excel | Excel BE | dès la création | |
| Technique | Test tissu | Tests tissu | dès la création | |
| Technique | Emails techniques | Email | — | facultatif |
| Réception | Bon de livraison | Bon de livraison | dès la création | |
| Réception | Bon / note de réception | Bon de réception | dès la création | |
| Réception | Document de réception matière | Document réception | dès la création | validation requise |
| Réception | Emails réception / logistique | Email | — | facultatif |
| Dédouanement | Déclaration douanière | Pièce douanière | dès la création | |
| Dédouanement | Documents import / export | Justificatif import/export | dès la création | |
| Dédouanement | Document transit | Document transit | dès la création | |
| Dédouanement | Document transport | Document transport | dès la création | |
| Dédouanement | Justificatif de dédouanement | Justificatif de dédouanement | dès la création | |
| Factures | Facture FRAMATEX | Facture | dès la création | |
| Factures | Pièce de facturation associée | Document facturation | dès la création | |
| Factures | Avoir / correction de facture | Avoir / correction de facture | — | facultatif |

Étapes de la commande (suivi, sans effet sur la checklist standard) : Préparation →
Approvisionnement → Fabrication → Expédition → Clôture. Migration
`0009_visible_checklist_duplicates` : règles obligatoires du profil standard
exigibles dès la création, validation requise pour la réception matière.

Le moteur de complétude existant est réutilisé tel quel ; la seule extension est une
colonne `required` (migration `0008_optional_rules`) : une règle facultative n'est
jamais exigible, donc jamais manquante. Les règles existantes restent obligatoires.

### Profil automatique

- « Accepter et créer le Dossier Jaune » (demande Client) applique le profil standard,
  étape Préparation, et l'audite (`completeness.context.update`, origine `client_order`).
- « Nouveau Dossier Jaune » applique aussi le profil standard.
- Un dossier sans profil affiche « Appliquer la checklist standard » au lieu du
  message technique ; `POST /api/launches/{id}/completeness/standard` refuse (409)
  d'écraser un profil déjà choisi. Le profil n'est jamais dupliqué.
- Profil et étape restent modifiables (« Changer l'étape », Contrôles → Complétude).
  Le profil et ses règles se gèrent dans Administration.

### Dépôt et versions

La modale « Déposer un document » contient : Sous-dossier, Type documentaire (liste
des types de la checklist), Fichier (glisser-déposer), Titre, Commentaire, et
« Proposer le type à partir du fichier » (suggestions à confirmer). Depuis une ligne,
sous-dossier, type et titre sont préremplis. Si un document du même type existe,
la modale l'indique : « sera enregistré comme V{n+1} sur la même ligne », avec la
case « Déposer plutôt comme un document distinct ». Après le dépôt, le dossier se
rouvre sur la ligne concernée, qui passe à Présent ou En validation.

L'historique (auteur, date, SHA-256, décisions, commentaires) s'ouvre depuis la
ligne ; il n'est jamais affiché par défaut dans la checklist.

### Modules avancés : rien n'est supprimé

| Onglet | Modules |
| --- | --- |
| Documents | Checklist du sous-dossier choisi |
| Contrôles | Complétude, Décisions et impacts, Cohérence et Excel, Lecture OCR, Circuits de validation, Exigences client, Simulation, Matières, Rapprochement ORLI |
| Communication | Demande Client, Emails et engagements, Partages et fournisseurs |
| Historique | Activité, Mémoire interne, QR et passeports, Détails techniques (identifiants) |

Les anciennes ancres (`focusWorkspaceArea('quality')`, etc.) ouvrent le bon onglet.
Les identifiants techniques (UUID) n'apparaissent que dans « Détails techniques ».
Les libellés « Version 0.x » sont retirés. Les précautions d'usage des modules
(textes fixes, jamais le contenu saisi) sont regroupées dans une note repliée
« À savoir sur ce contrôle » en fin de module : rien n'est masqué ni reformulé.

## 2. Tableau de bord

Ordre : indicateurs (Dossiers : actifs, complets, incomplets · À traiter :
documents manquants, à valider, doublons, alertes, incohérences, modifications) →
Actions prioritaires → **Documents à traiter** (onglets Manquants · En validation ·
Doublons, avec compteurs) → Complétude des dossiers → Alertes importantes →
Activité récente.

Documents à traiter : Sous-dossier · Document · Commande / dossier · Client · État ·
Ouvrir, filtres par sous-dossier, 8 lignes puis « Afficher les N autres ». Un clic
ouvre le dossier, le bon sous-dossier, et met en évidence la ligne de checklist
(focus clavier sur son bouton « Déposer »). Exemple vérifié dans Chromium :
Documents manquants → Réception → Bon de livraison → ligne Bon de livraison.

## 3. Espace Client

Menu : Mes demandes · Nouvelle demande · Documents · Mon compte. « Documents »
regroupe trois onglets sur les routes existantes : À fournir (`#/documents-demandes`,
avec pastille du nombre de pièces à fournir), Reçus de FRAMATEX
(`#/documents-transmis`), Mes dépôts (`#/documents`). Le détail d'une demande
affiche référence, article, quantité, date souhaitée, statut, vos documents
déposés, les documents demandés par FRAMATEX et les documents reçus pour cette
demande.

## 4. Landing

Ordre : Hero → Notre solution (avec repères réels : 2 espaces, 4 sous-dossiers,
5 étapes, 2 bureaux) → Nos espaces → Chaîne de valeur → Partenariat École
Centrale Casablanca → appel à l'action (Espace Client / Espace FRAMATEX).

Mouvement, toujours désactivé si `prefers-reduced-motion: reduce` : parallaxe
légère de la photo du hero (écrans > 640 px, une écriture par image), apparition
des blocs sous la ligne de flottaison, étapes de la chaîne décalées et trait qui se
dessine, compteurs animés une fois, profondeur au survol des cartes d'espace. Le
contenu est visible sans JavaScript (les valeurs réelles sont dans le HTML).

## 5. Système de design

Un seul jeu de jetons (`static/brand/tokens.css`) pour les trois espaces : bleu nuit
`#0e2a5a`, bleu profond `#0a1f44`, bleu FRAMATEX `#1d4f91`, cyan `#29a8df`, blanc,
surface `#f6f8fb`, filets `#e1e6ed`. Polices locales (Manrope, DM Sans) compatibles
avec la CSP. Les états (Présent, Manquant, En validation, Exception, Doublon détecté, Non applicable)
ont une forme unique : pastille avec point, filet gauche pour Manquant et En validation.

Feuilles ajoutées : `static/brand/dossier.css` (Dossier Jaune, tableau de bord,
modules), complétée par `static/client/client.css` et `static/landing/landing.css`.
Scripts ajoutés : `static/dossier.js`, `static/dashboard.js` (surcharges
déclaratives des fonctions existantes ; aucune route serveur retirée).

## 6. Images

Aucune image générée n'a pu être récupérée en pleine résolution : le domaine
`media.canva.com` est bloqué par la politique réseau de cet environnement, et
`framatex.net` n'est pas joignable. Seules les photos déjà validées du dépôt sont
utilisées, servies en AVIF puis WebP, avec repli JPEG/WebP (`<picture>`) :

| Image | Original | WebP | AVIF |
| --- | --- | --- | --- |
| hero-textile-woman | 107 Ko (JPEG) | 61 Ko | 47 Ko |
| partnership-meeting | 103 Ko (JPEG) | 66 Ko | 52 Ko |
| espace-client | 217 Ko (WebP) | — | 89 Ko |
| espace-framatex | 231 Ko (WebP) | — | 91 Ko |
| notre-solution | 44 Ko (WebP) | — | 19 Ko |

Le type MIME `image/avif` est déclaré côté serveur (y compris sous Windows).

## 7. Responsive et accessibilité

- 1440 / 1024 / 820 / 390 px : aucun défilement horizontal (vérifié par script).
- ≤ 1100 px : cartes de sous-dossier sur deux colonnes ; documents manquants en cartes.
- ≤ 760 px : checklists en cartes (document, état, version · date, action pleine
  largeur), modales en feuille basse (94 dvh), cibles tactiles ≥ 40 px.
- Onglets `role="tablist"` avec flèches gauche/droite, `aria-selected`, sous-modules
  `aria-controls`, cartes `aria-pressed`, tableaux avec `caption` et en-têtes.
- Focus visible partout ; le lien depuis le tableau de bord place le focus sur
  l'action de la ligne ciblée.
- Contrôle scripté (Chromium, sans axe-core indisponible ici) sur landing, tableau de
  bord, dossier, modale de dépôt et détail Client : aucun bouton sans nom, aucun
  champ sans étiquette, aucune image sans `alt`, aucun identifiant dupliqué, aucun
  texte visible sous 4,5:1 (3:1 pour les grands titres).
- Mesures locales (serveur de développement, cache vide) : landing 16 requêtes,
  327 Ko, DOMContentLoaded ≈ 0,1 s ; tableau de bord affiché ≈ 0,9 s après la
  connexion ; Dossier Jaune ≈ 0,5 s. Les animations n'utilisent que `transform`
  et `opacity` ; la parallaxe écrit une variable CSS par image (`requestAnimationFrame`).
  Aucune mesure de fréquence d'images n'est revendiquée.

## 8. Windows

`tzdata` est ajouté à `requirements.txt` et au contrôle `windows_preflight.py` :
sans lui, `ZoneInfo("Africa/Casablanca")` échoue sous Windows. Le lanceur
(`start_windows.cmd`, `windows_runtime.py`, `runtime.json`, diagnostic, journaux,
délais du frontend) est inchangé.

## 9. Limites restantes

- Photos : pas de nouvelle image générée (domaine bloqué) ; les photos actuelles restent.
- Le profil standard est une proposition de checklist : son contenu et ses étapes
  sont à valider avec les équipes FRAMATEX (modifiable dans Administration).
- Le changement de type d'un document déjà déposé n'est pas proposé dans la checklist.
- Espace Client : « Mon compte » reste en lecture seule ; pas de mot de passe oublié.
- Pas d'antivirus, pas d'email sortant, ORLI non connecté (rapprochement manuel).

## 10. Captures

`docs/ux-captures/<écran>-<largeur>.jpg`, largeurs 1440, 1024, 820 et 390 px,
mouvement réduit, aucune donnée réelle ni mot de passe à l'écran :

| Écran | Fichier |
| --- | --- |
| Landing | `01-landing` |
| Espace Client · Mes demandes / Documents | `02-client-mes-demandes`, `02b-client-documents` |
| Tableau de bord FRAMATEX | `03-framatex-tableau-de-bord` |
| Dossier Jaune | `04-dossier-jaune` |
| Technique · Réception · Dédouanement · Factures | `05-technique`, `06-reception`, `07-dedouanement`, `08-factures` |
| Documents manquants | `09-documents-manquants` |
| Client → demande | `10-client-nouvelle-demande`, `10b-client-demande-detail` |
| FRAMATEX → acceptation | `11-framatex-acceptation` |
| Dossier créé depuis la demande (page entière) | `12-dossier-cree-depuis-demande` |
| Documents en doublon (tableau de bord) | `09b-documents-doublons` |
| Doublon détecté (modale) | `13-doublon-detecte` |

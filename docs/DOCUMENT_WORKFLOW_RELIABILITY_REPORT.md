# FRAMATEX — Corrections fonctionnelles, synchronisation et souplesse documentaire · rapport

Branche : `fix/document-workflow-reliability`, créée depuis `feat/framatex-business-requirements`
(`282447d`). Toutes les améliorations précédentes (Claude et Codex) sont conservées. `main` n'est pas
modifié. Aucune refonte graphique : seuls des éléments déjà présents sont réutilisés (tableaux,
champs, boutons, puces de sous-dossier) ; landing, 3D, carrousel, connexion, fiche commande et
visionneuse inchangés. Aucun agent IA.

| Lot | Commit |
|---|---|
| P0.2 Doublons et suppressions | `8029271` |
| P0.1 Boutons et requêtes · P0.3 Synchronisation | `78ae8e1` |
| P1.4 Recherche du technicien | `97dce14` |
| P1.5 Documents complémentaires facultatifs | `cbde48c` |
| P2 Performance de l'historique, courses restantes, recettes | `86fcac6` |
| Rapport | commit final de ce rapport |

## 1. P0.1 — Boutons et requêtes en échec

Reproduction par clics réels dans Chromium sur cinq profils internes (administrateur, technicien en
lecture seule, technicien avec dépôt, responsable complet, technicien à droits personnalisés),
avec relevé des erreurs JavaScript, des requêtes en échec et des durées. Les défauts trouvés et
corrigés :

| Symptôme | Cause | Correction |
|---|---|---|
| « Déposer une nouvelle version » impossible, ou création d'un **document séparé** | Si le fichier ressemblait à un **autre** document, la seule option de version visait cet autre document ; « Conserver comme nouveau document » remettait la cible à vide côté serveur | Serveur : sans rattachement au document proposé, la version va au document explicitement choisi. Libellés adaptés : « Ajouter comme nouvelle version de « X », sans rattachement » |
| « Supprimer Vn » absent quand on ouvre un document par « Ouvrir » | `latest` était une copie de la version courante **sans** les droits calculés pour l'historique | `latest` est désormais la même entrée que dans `versions` (droits compris) |
| Clic sans effet pendant une actualisation (« Tous les sous-dossiers », changement d'onglet) | Le rendu était suspendu pendant le rechargement, puis la réponse réappliquait l'écran d'origine | Rechargement appliqué d'un seul bloc ; l'écran reste utilisable avec les données précédentes ; une navigation faite entre-temps prime (§ 3) |
| Fiche document qui réapparaît par-dessus une autre action | Réouverture automatique après un dépôt, même si l'utilisateur avait ouvert autre chose | Réouverture annulée si l'utilisateur a agi entre-temps ; une fiche déjà ouverte est redessinée avec les données à jour |
| Retour forcé à l'onglet Documents ou à un sous-dossier après une action dans Contrôles | Chaque actualisation réappliquait « sous-dossier courant » comme une navigation | Actualisation **sur place** : sous-dossier, onglet et module conservés |
| « Impossible de joindre le serveur » alors que le serveur répondait | Toute requête coupée à **8 s**, y compris les écritures (risque de double saisie) ; message identique pour un délai dépassé et une coupure | Lecture 20 s, écriture 60 s, fichiers 120 s ; message distinct : « n'a pas répondu en 20 s » ou « n'a pas confirmé l'opération : elle a peut-être été enregistrée » |
| Espace Client : toute erreur affichée comme « connexion impossible » | Les erreurs inattendues étaient converties en erreur réseau | Délai dépassé et erreur serveur distingués ; l'erreur réelle est conservée dans la console |
| Requêtes 401 après « Se déconnecter » | Une actualisation encore en cours partait après la fermeture de session | Requêtes en cours annulées à la déconnexion, sans message parasite |
| Fiche ouverte pendant une relecture affichée avec l'ancien état (V2 sans « Supprimer V2 ») | Fiche construite avec le document lu avant ses requêtes ; copie locale incomplète après dépôt | Fiche redessinée si la commande a été relue entre-temps ; copie locale cohérente (liste et version courante) |
| Même contenu qu'une version supprimée refusé (« déjà conservé ») | Le contrôle portait aussi sur les versions supprimées | Seules les versions actives sont comparées |
| Historique de la commande lent (risque de délai dépassé) | Chaque ouverture parcourait **tout** le journal d'audit (2,3 s à 20 000 événements) | Préfiltre SQL par commande ou document, résultat strictement identique (vérifié) : **30 ms** |

Vérifiés sans défaut par clics : ouverture de commande, de sous-dossier et de document (PDF), Télécharger, Comparer,
Commenter, Ajouter une version, Déposer, Valider, Confirmer, Modifier la fiche, Supprimer, Restaurer,
historique global et Filtrer, recherche, Enregistrer les habilitations, corbeille, onglets et
modules. Les consultations Excel et Word sont couvertes par la recette de la visionneuse. Les demandes Client et leur traitement par
l'administrateur sont couverts par les recettes existantes (§ 7). Un module secondaire refusé
n'empêche toujours pas l'ouverture d'une commande autorisée (scénario Costume rejoué). Aucune
protection n'a été assouplie (limites de connexion, en-tête anti-CSRF et droits inchangés) ; les
vraies erreurs du serveur restent affichées telles quelles.

## 2. P0.2 — Doublons et documents supprimés

**Cause.** L'alerte au dépôt, les groupes de doublons (et donc le compteur du tableau de bord) et les
suggestions de rapprochement parcouraient tous les documents et toutes les versions, **supprimés
compris**, et prenaient la plus haute version même supprimée.

**Correction.** Une règle unique (`app/active_documents.py`) : version courante = plus haute version
non supprimée d'un document non supprimé ; un document dont toutes les versions sont supprimées est
inactif. Appliquée à : alerte au dépôt, groupes de doublons, compteur « doublons » de la commande et
du tableau de bord général, rapprochements du dépôt guidé (doublon exact, doublon potentiel,
nouvelle version probable), circuits de validation, contrôles Excel, valeurs métier, décisions,
exigences, simulation et pièces proposées au partage Client. La recherche et la complétude
filtraient déjà ces pièces.

- **Doublon courant ou correspondance historique.** Au dépôt, une version antérieure non supprimée
  identique est renvoyée à part (`historical_matches`) et n'est jamais comptée comme doublon courant
  entre deux documents actifs.
- **Recalcul.** Les doublons sont calculés à chaque lecture : la suppression et la restauration
  (document ou version) se répercutent immédiatement, et l'écran est relu automatiquement (§ 3).
- **Audit.** Aucune trace supprimée ; les événements de dépôt gardent leur `duplicate_count` d'origine.
- **Confidentialité.** Inchangée : un doublon n'est calculé que sur les sous-dossiers où le compte a
  la consultation et les contrôles ; l'alerte au dépôt reste limitée au sous-dossier de dépôt.

Scénario obligatoire exécuté par clics (§ 7) : PDF en Jaune, même PDF en Rose → doublon ; suppression
du Jaune → alerte et compteurs à 0 immédiatement ; restauration → doublon de retour ; suppression des
deux, nouveau dépôt en Bleu → aucun faux doublon. Suppression d'une version seule : la copie
identique de la V2 supprimée n'est plus un doublon ; la V1 redevenue courante est comparée.

## 3. P0.3 — Synchronisation automatique

Après chaque opération confirmée par le serveur, la commande est **relue intégralement**. Le serveur
fait foi et aucun compteur n'est modifié localement. Sont relus : fiche, listes de documents,
checklist, compteurs (présents, manquants, conformes, à valider, doublons), complétude, contrôles de
cohérence, alertes, historique, synthèse de la commande et fiche document ouverte. Les tableaux de
bord, Mes actions, les notifications et la recherche sont relus à chaque affichage.

- **Opérations concernées :** dépôt, nouvelle version, suppression, restauration, validation,
  reclassement, confirmation d'extraction, décision de doublon, cases complémentaires et
  modification des habilitations. La modification des habilitations relit désormais la commande ouverte ; les
  autres opérations relisaient déjà la commande et appliquent maintenant les garde-fous ci-dessous.
- **Garde-fous :** réponses appliquées d'un seul bloc (jamais de mélange ancien/nouveau) ; une réponse
  plus ancienne qu'une autre ouverture est ignorée ; une navigation de l'utilisateur pendant le
  chargement n'est jamais écrasée ; actualisation sur place, sans changer d'écran ni recharger
  l'application ; curseur d'attente pendant la relecture.
- **Retour sur l'onglet** après au moins 15 s : relecture légère de la commande affichée (jamais
  par-dessus une fenêtre ouverte ni pendant une autre relecture). Plus besoin de F5.
- « Présent », « identifié » et « validé » restent distincts : ce sont les états calculés par le
  moteur de complétude, affichés tels quels.

## 4. P1.4 — Recherche du technicien

« Mes commandes » et « Mes sous-dossiers » (comptes non administrateurs) ont une barre de recherche
et un filtre visible : Tous mes sous-dossiers / Sous-dossier jaune / rose / bleu / vert, utilisable sans
texte, avec « Réinitialiser ».

- **Index.** Le même que la recherche documentaire de l'administrateur (fonction `launch_index`
  partagée) : N° commande, N° client, client, nom de commande, article, atelier, couleur, N° OF,
  facture, références de documents et texte analysé ; valeurs partielles, casse et accents ignorés.
- **Résultats.** Chaque résultat ouvre directement le sous-dossier choisi par le filtre, sinon un
  sous-dossier réellement accessible (puces cliquables).
- **Droits.** Route `/api/workspace/my-launches` : seules les commandes attribuées et les
  sous-dossiers consultables interviennent, dans la correspondance comme dans le résultat. Un
  document d'un sous-dossier non autorisé ne fait jamais apparaître sa commande. Le serveur
  revérifie toute ouverture ; le problème Costume n'est pas réintroduit (recette rejouée).

## 5. P1.5 — Documents complémentaires facultatifs

Chaque sous-dossier a une section permanente « Documents complémentaires facultatifs », visible même
vide, avec « Ajouter un document facultatif » (nom, description facultative, « Créer la case » ou
« Créer et déposer »).

- **Cases.** Propres à la commande et au sous-dossier ; dépôt immédiat ou ultérieur ; plusieurs
  documents par case ; renommage ; suppression d'une case vide, avec historique. Une case revient
  automatiquement si l'un de ses documents est restauré.
- **Trois catégories distinctes.** Pièces standard obligatoires, pièces standard facultatives
  (« Facultatif · à déposer si besoin ») et pièces complémentaires personnalisées.
- **Complétude.** Les 22 exigences standard sont inchangées. Une case vide n'est jamais « manquante »
  et n'entre pas dans le dénominateur. Un document complémentaire porte le type « Document
  complémentaire » : il ne satisfait aucune exigence sans reclassement explicite (le serveur refuse
  case + exigence).
- **Documents.** Ce sont des documents ordinaires : OCR et analyse, visionneuse, SHA-256, doublons,
  versions, commentaires, historique, suppression et restauration, droits du sous-dossier.
- **Droits.** Consulter = consultation du sous-dossier ; créer ou renommer = dépôt ; supprimer une
  case vide = administration, validation ou son auteur. Aucune case d'un sous-dossier non autorisé
  n'est renvoyée ni révélée par l'historique.
- **Migration.** `0017_optional_documents`, additive et rejouable (table `optional_document_cases`,
  colonne nullable `documents.optional_case_id`). Validée sur une base créée par la version
  précédente, avec sauvegarde automatique et données intactes.

## 6. P2 — Performance mesurée

Base temporaire, 60 commandes, 480 documents et 20 541 événements d'audit :

| Requête | Avant | Après |
|---|---|---|
| Historique d'une commande (`/api/workspace/activity?launch_id=…`) | 2 317 ms | 30 ms |
| Détail de commande | 13 ms | 13 ms |
| Recherche technicien | — | 88–91 ms |
| Recherche documentaire | 117 ms | 120–128 ms |

Test de charge progressif (serveur unique, base temporaire ; création, ouverture, recherche, dépôts,
aperçus, fiche, suppression, restauration) :

| Utilisateurs | Requêtes | Débit | Erreurs | Verrous SQLite | Ouverture (médiane) | Recherche (médiane) | Dépôt PDF (médiane) |
|---|---|---|---|---|---|---|---|
| 1 | 11 | 28 req/s | 0 | 0 | 13 ms | 13 ms | 16 ms |
| 5 | 55 | 66 req/s | 0 | 0 | 35 ms | 63 ms | 53 ms |
| 10 | 110 | 51 req/s | 0 | 0 | 97 ms | 265 ms | 168 ms |
| 20 | 220 | 47 req/s | 0 | 0 | 231 ms | 725 ms | 458 ms |

Aucune requête n'approche les nouveaux délais (20 s en lecture, 60 s en écriture).

## 7. Tests réellement exécutés

Bases temporaires, documents et comptes fictifs (`example.test`), serveurs Uvicorn réels, Chromium
avec clics réels (aucune fonction de l'application appelée directement).

| Suite | Résultat |
|---|---|
| `pytest` (dont `test_document_reliability.py` : 6, `test_optional_documents.py` : 2) | **234 réussis** |
| Tests JS `node tests/*.cjs` | **21/21** |
| `validate_document_reliability_ui.py` (nouvelle) : doublons Jaune/Rose/Bleu, version, validation et compteurs, dépôt concurrent, navigation pendant une actualisation, documents complémentaires, persistance après redémarrage, recherche technicien, droits | **18/18** |
| `validate_buttons_profiles_ui.py` (nouvelle) : 5 profils, 135 actions | **0 échec, 0 erreur JS, 0 requête en échec** |
| Autres recettes Chromium et revues | voir tableau ci-dessous |

| Recette | Résultat |
|---|---|
| `validate_document_deletion_ui.py` (rejouée 6 fois après le dernier correctif) | **5/5** |
| `validate_costume_technician.py` (scénario Costume de Codex, rejoué 3 fois) | **réussi** |
| `validate_document_workspace.py` | **9/9** |
| `validate_business_requirements_ui.py` · `validate_document_viewer_ui.py` | **6/6** · **8/8** |
| `validate_client_workflow_ui.py` (demandes Client et traitement administrateur) · `validate_internal_ui.py` | réussis |
| `validate_access_ui.py` · `validate_sessions_ui.py` · `validate_business_memory_ui.py` | réussis |
| `validate_landing_motion.py` · `validate_partnership_carousel.py` · `validate_cinematic_3d.py` | réussis (non modifiés) |
| `qa_platform_review.py` · `demo_full_platform.py` | **96/96** · **135/135** |
| `load_test_platform.py` (1, 5, 10, 20 utilisateurs) | **0 erreur, 0 verrou SQLite**, 36 commandes, 0 doublon |

Seconde passe sur le code final (après les derniers correctifs de course) : les 12 recettes de l’espace interne (fiabilité, boutons par profil, suppression, Costume, espace documentaire, exigences métier, workflow Client, visionneuse, habilitations, mémoire métier, interface interne, sessions) **toutes réussies**.

Préparation par l'API dans les recettes : création des commandes, des comptes fictifs et un dépôt
concurrent simulant un autre utilisateur. Toutes les actions vérifiées sont faites par clics.
**Limite d'outillage :** Chromium automatisé ne masque jamais un onglet (ni changement d'onglet ni
fenêtre réduite). Le retour sur l'onglet est donc simulé par l'événement navigateur
`visibilitychange`, après une vraie absence de 15,5 s, sans appeler de fonction de l'application.

## 8. Restant et limites

Captures : `docs/document-workflow-reliability-captures/` (doublon détecté, dépôt Bleu sans faux doublon,
recherche du technicien, sous-dossier ouvert depuis la recherche, documents complémentaires).


- **Historique global sans filtre** (administrateur) : toujours calculé sur tout le journal avant
  pagination ; à optimiser si le journal dépasse quelques centaines de milliers d'événements.
- **Relecture après une opération** : la commande entière est relue (environ 20 requêtes légères,
  toutes inférieures à 0,5 s mesurées). Elle pourra être ciblée par module si le volume l'exige.
- **Document complémentaire reclassé** explicitement vers un type standard : il compte alors pour
  l'exigence et reste listé dans sa case (choix transparent, à confirmer avec la tutrice).
- **Case supprimée** : elle n'est restaurable qu'avec l'un de ses documents (aucune corbeille de cases).
- **Recherche technicien** : 200 commandes au plus par recherche, cinq références de documents
  affichées par sous-dossier.
- **Espace Client** : aucune nouvelle fonction ; seuls les messages d'erreur ont été rendus exacts.

## 9. Branche

`origin/fix/document-workflow-reliability` (commits `8029271`, `78ae8e1`, `97dce14`, `cbde48c`, `86fcac6`, puis le
commit de ce rapport : SHA donné dans le message de livraison, vérifiable par
`git ls-remote origin fix/document-workflow-reliability`). `main` non modifié.

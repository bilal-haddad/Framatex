# FRAMATEX — Rapport notifications centralisées et Outlook

Date de clôture : 27 novembre 2026  
Branche : `feat/unified-notifications-outlook`  
Base : `feat/postgresql-final-cutover` (`615b74cefb6de1195a209039568e9412ca86c766`)  
Moteur de recette : PostgreSQL 17, base jetable et stockage temporaire  
`main` : non modifiée

## Synthèse exacte

| Lot | État | Résultat |
|---|---|---|
| Consolidation Windows/PostgreSQL | Réussi | Correctifs PowerShell 5.1, fermeture SQLite/SQLAlchemy, validation de configuration et comparaison stricte des dates historiques. |
| Centre unifié persistant | Réussi | Une source PostgreSQL pour comptes internes et Clients, dédoublonnage par événement métier et destinataire. |
| Cycle de vie | Réussi | Non lue, lue, action en attente, résolue et archivée sont distinguées. Lire ne résout pas une action. |
| Workflow demande Client → Dossier Jaune | Réussi (API/tests) | Acceptation/création idempotente existante conservée ; la même action devient « technicien à affecter ». |
| Affectations | Réussi (API/tests) | Événement stable par commande/collaborateur ; résolution administrateur après couverture des quatre sous-dossiers. |
| Cloche interne et Client | Réussi (revue statique/tests JS) | Compteurs non lus/actions, interrogation groupée toutes les 15 s, suspension en onglet caché. |
| Chromium 3D | Réussi | Three.js, Dossier Jaune, tissu, carrousel et repli mobile 390 px vérifiés par clics réels. |
| Messagerie Outlook / Microsoft Graph | Non livré | Aucun faux mode Graph n’a été présenté comme opérationnel. Voir « Limites restantes ». |
| Recette Chromium complète des nouveaux workflows de notifications | Non testée | Les parcours existants n’ont pas été déclarés suffisants car certains runners historiques utilisent `page.evaluate()` pour naviguer. |

## Corrections Windows et PostgreSQL

- Les arguments `python -c` sont transmis à PowerShell 5.1 comme un seul argument correctement cité.
- Les connexions SQLite sources sont explicitement fermées.
- Les moteurs SQLAlchemy sont libérés avant la suppression des répertoires temporaires, ce qui évite `WinError 32`.
- Les seules dates neutralisées lors de la comparaison sont les dates techniques créées pour les révisions 0017, 0018 et 0019 absentes de la source.
- La date historique 0016 et toutes les dates métier restent comparées strictement.
- Hôte local, port, identifiants, répertoire, mot de passe et dépendances PostgreSQL sont validés avant démarrage.
- Aucune migration de données personnelles n’a été relancée et aucun stockage documentaire utilisateur n’a été ouvert.

## Architecture du centre de notifications

La table `unified_notifications` porte le destinataire (`internal` ou `client`), une clé d’événement métier unique, la priorité, la cible du clic, les dates de lecture/résolution/archivage et le contexte autorisé de commande/sous-dossier.

L’unicité `(recipient_type, recipient_id, event_key)` et l’UPSERT PostgreSQL assurent qu’une évolution met à jour la notification existante. Une action résolue reste dans l’historique. Une action non résolue ne peut pas être archivée.

Les droits d’un utilisateur interne sont revérifiés à chaque lecture. Une notification liée à une commande ou un sous-dossier devenu inaccessible est filtrée. Les comptes Clients n’interrogent que leur propre identifiant de session ; aucun identifiant Client n’est accepté depuis le navigateur.

## Événements et conditions de résolution

| Événement | Destinataire | Priorité | Action | Résolution |
|---|---|---:|---|---|
| Inscription Client | Administrateurs | Normale | Examiner le compte | Activation du compte |
| Compte activé | Client | Normale | Information | Archivable après lecture |
| Demande envoyée | Administrateurs | Haute | Examiner la demande | Refus, ou poursuite du même événement jusqu’aux affectations |
| Demande reçue | Client | Normale | Information | Archivable après lecture |
| Demande acceptée sans commande | Administrateurs | Haute | Créer le Dossier Jaune | Création atomique du dossier |
| Dossier Jaune créé | Administrateurs | Haute | Affecter les techniciens | Les quatre sous-dossiers possèdent au moins une affectation |
| Demande refusée | Client | Haute | Information avec motif communicable | Archivable après lecture |
| Affectation nouvelle/modifiée | Technicien/responsable | Haute | Ouvrir la commande | Information ; ne reste pas artificiellement dans les actions |
| Document demandé/correction | Client | Haute | Déposer une version | Dépôt effectif de la version |
| Document Client déposé | Administrateurs | Haute | Vérifier le document | Acceptation ou demande de correction |
| Document accepté | Client | Normale | Information | Archivable après lecture |
| Document partagé | Client | Normale | Consulter | Archivable après lecture |
| Validation/impact/qualité existants | Utilisateurs habilités | Haute | Ouvrir le dossier | Résolution métier existante ; historique conservé |

## Workflow Client

- L’activation du compte reste indépendante de la création d’une commande.
- L’action existante « Accepter et créer le Dossier Jaune » reste transactionnelle et idempotente grâce au lien unique `ClientOrderLaunch`.
- Elle conserve les champs projet, article, quantité, couleur, description, référence et date souhaitée, crée les quatre sous-dossiers et rattache le compte Client.
- Une seconde requête concurrente récupère le dossier déjà créé au lieu d’en créer un second.
- La migration 0021 réintroduit dans le centre les demandes historiques envoyées/en étude et les demandes acceptées sans Dossier Jaune.
- Après création, la notification administrateur évolue au lieu d’être dupliquée.

## Interfaces et synchronisation

- Espace interne : cloche de barre supérieure et entrée de menu, compteurs « non lues » et « actions », priorité, contexte, date, destination et archivage.
- Espace Client : cloche permanente (barre mobile et bouton fixe bureau), entrée de navigation et page d’historique.
- Une seule requête ramène toute la collection et les deux compteurs ; aucune requête par notification.
- Rafraîchissement toutes les 15 secondes seulement lorsque l’onglet est visible, plus rafraîchissement au retour au premier plan et canal inter-onglets.
- La persistance PostgreSQL garantit la reprise après redémarrage.

## Tests exécutés

### Réussis

- `python -m pytest -q tests/test_postgresql_final_cutover.py tests/test_client_backend.py tests/test_client_order_launch.py tests/test_client_workflow.py`
  - **46 réussis**, 0 échec.
- Migration réelle d’une base PostgreSQL jetable jusqu’à `0021`, puis contrôle de révision : **réussi**.
- `python -m compileall -q app` : **réussi**.
- `node --check` sur les scripts interne, Client et notifications modifiés : **réussi**.
- `git diff --check` : **réussi**.
- `scripts/validate_cinematic_3d.py` avec Chromium : **réussi**.
  - Dossier Jaune Three.js animé à 1440 px.
  - Tissu Three.js animé et réactif à 1440 px.
  - Carrousel manipulé par clics réels.
  - Repli statique sans WebGL à 390 px, sans erreur JavaScript.

### Non testés / non déclarés réussis

- Recette Chromium complète d’inscription → notification → acceptation → affectation sur le nouveau centre.
- Synchronisation réelle entre deux navigateurs simultanés.
- Windows PowerShell 5.1 natif (les tests automatisés valident le script et sa construction d’arguments, pas un poste Windows dans cet environnement Linux).
- Microsoft Graph et envoi simulé, car le lot Outlook n’est pas livré dans ce SHA.

## Messagerie Outlook — configuration prévue et limite

Le centre interne a été séparé des événements métier ; Outlook déconnecté ne bloque donc aucune notification. En revanche, le service OAuth 2.0/Graph, le chiffrement des jetons, les brouillons, pièces jointes, envois simulés et l’historique email n’ont pas été ajoutés dans ce lot de clôture. Aucun véritable email n’a été envoyé.

La future intégration devra demander uniquement `openid`, `profile`, `offline_access`, `User.Read` et `Mail.Send`, sans `Mail.Read`. Elle devra utiliser une application Microsoft Entra autorisée, un URI de retour local explicite, des jetons chiffrés au repos, une clé d’idempotence par envoi et un mode simulé visiblement étiqueté. Une réponse Graph acceptée devra être affichée comme « acceptée pour traitement », jamais comme preuve de réception.

## Récupérer la branche sans écraser des corrections locales

Depuis le clone Windows, ne pas lancer la migration de données personnelles. Conserver d’abord le travail local :

```powershell
git status --short
git stash push --include-untracked -m "corrections locales avant notifications"
git fetch origin
git switch feat/unified-notifications-outlook
git pull --ff-only origin feat/unified-notifications-outlook
git stash pop
```

Si les corrections locales sont déjà commitées, remplacer le `stash` par une branche de sauvegarde et fusionner ou sélectionner ces commits après la mise à jour. En cas de conflit, ne jamais utiliser `reset --hard` ; résoudre fichier par fichier.

## Limites restantes

1. P1 Outlook/Graph et Communications n’est pas livré.
2. La recette Chromium spécifique au nouveau centre reste à écrire avec uniquement des clics utilisateur réels.
3. Les captures de la recette 3D ont été produites dans l’espace de recette temporaire, pas ajoutées au dépôt.
4. Les familles d’alertes non raccordées à un événement métier existant restent à connecter au service central, sans créer de doublons.

## Révisions livrées

- `4e7388e` — consolidation Windows/PostgreSQL.
- `1ab633b` — centre de notifications et workflow Client.
- SHA final de livraison : le sommet publié de `origin/feat/unified-notifications-outlook` après ajout du présent rapport.

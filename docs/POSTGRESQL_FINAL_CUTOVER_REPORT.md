# FRAMATEX — Rapport de bascule définitive PostgreSQL

Date de validation : 27 novembre 2026  
Branche : `feat/postgresql-final-cutover`  
Base Git vérifiée : `bc9e0467e2c8466848f5823406a22900ae152431` (`feat/postgresql-migration`)  
Commit d'implémentation validé : `5b1b7c1`  
Commit contenant le code et le présent runbook validés : `42a6734`  

`main` n'a pas été modifiée. Aucune donnée personnelle ni aucun fichier du poste Windows n'a été
accessible depuis l'environnement de développement distant. La migration réelle de
`D:\Bilal\Downloads\bilaaaal\Framatex\data` reste donc à exécuter localement avec la procédure
ci-dessous.

## 1. Résultat livré

- PostgreSQL est le seul moteur courant. Une configuration absente ou une base indisponible produit
  une erreur claire ; aucun fichier SQLite neuf n'est créé comme solution de repli.
- SQLite reste disponible uniquement derrière `FRAMATEX_LEGACY_SQLITE_MODE=1`, pour la fixture et
  les outils explicites d'import historique. Le fichier original est toujours ouvert en lecture seule
  puis copié avant migration.
- `scripts\start_windows.cmd` démarre désormais PostgreSQL 17 local, vérifie la connexion, applique
  Alembic sous verrou, contrôle la révision, puis démarre la plateforme. Aucun Docker.
- Le démarrage normal ne crée aucune donnée fictive. `-Demo` exige une base `framatex_test` et un
  stockage de test distincts de `framatex`.
- La bascule finale est orchestrée par `scripts\migrate_to_postgresql_windows.cmd`. La configuration
  active n'est modifiée qu'après sauvegarde, simulation, confirmation exacte, transfert transactionnel,
  comparaison complète et sauvegarde PostgreSQL vérifiée.
- Aucune option `--replace`, aucun `TRUNCATE`, aucun effacement automatique d'une cible existante.

## 2. Corrections Windows

### Dépendances sous PowerShell 5.1

Les commandes natives sont exécutées par `Invoke-FramatexNative`. La valeur temporaire
`ErrorActionPreference=Continue` empêche stderr d'être transformé en `NativeCommandError`, le code
`$LASTEXITCODE` reste contrôlé, puis la politique initiale est restaurée. L'absence de `psycopg` ou
`alembic` déclenche donc l'installation de `requirements.txt` au lieu d'arrêter le script.

### Options du lanceur

`start_postgresql_windows.ps1` déclare maintenant des paramètres typés :

```powershell
[int]$Port
[switch]$Demo
[switch]$NoBrowser
[switch]$CheckOnly
[switch]$Reload
```

Ils sont retransmis à `start_windows.ps1` par splatting nommé. `-Demo` ne peut plus être interprété
comme la valeur entière de `-Port`. Le mode démonstration refuse explicitement la base ou le dossier
définitifs.

## 3. Préparation locale obligatoire

1. Installer PostgreSQL 17 et vérifier dans `services.msc` le service `postgresql-x64-17`.
2. Vérifier que le rôle `framatex` peut se connecter et créer une base vide. Le mot de passe n'est
   jamais placé dans Git ni dans `DATABASE_URL`.
3. Prévoir assez d'espace pour : l'archive complète source, la copie définitive des documents et une
   sauvegarde PostgreSQL après transfert.
4. Fermer FRAMATEX avec `Ctrl+C`, DB Browser for SQLite et tout outil pouvant écrire dans
   `framat.db`. L'assistant refuse aussi la bascule si un serveur écoute encore sur 8000–8020.
5. Ne pas créer manuellement `Framatex-pg-data` : la cible doit être absente pour garantir qu'aucun
   contenu antérieur n'est écrasé.

Depuis PowerShell, dans le dépôt :

```powershell
git fetch --prune origin
git switch feat/postgresql-final-cutover
git pull --ff-only origin feat/postgresql-final-cutover

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Valeurs attendues dans `.env` (remplacer uniquement le mot de passe par le vrai secret local) :

```dotenv
FRAMATEX_DATA_DIR=D:\Bilal\Downloads\bilaaaal\Framatex-pg-data
FRAMATEX_PG_HOST=127.0.0.1
FRAMATEX_PG_PORT=5432
FRAMATEX_PG_DATABASE=framatex
FRAMATEX_PG_USER=framatex
FRAMATEX_PG_PASSWORD=SECRET_LOCAL_LONG_NON_VERSIONNE
FRAMATEX_PG_MODE=local
FRAMATEX_PG_SERVICE=postgresql-x64-17
FRAMATEX_PG_MAINTENANCE_DATABASE=postgres
FRAMATEX_PG_DEMO_DATABASE=framatex_test
FRAMATEX_DEMO_DATA_DIR=D:\Bilal\Downloads\bilaaaal\Framatex-pg-test-data
```

Si les outils clients ne sont pas dans `PATH`, ajouter :

```dotenv
FRAMATEX_PG_BIN=C:\Program Files\PostgreSQL\17\bin
```

## 4. Commande de bascule définitive

Les chemins demandés sont les valeurs par défaut. La commande minimale est :

```powershell
.\scripts\migrate_to_postgresql_windows.cmd
```

Équivalent explicite :

```powershell
.\scripts\migrate_to_postgresql_windows.cmd `
  -Sqlite "D:\Bilal\Downloads\bilaaaal\Framatex\data\framat.db" `
  -SourceData "D:\Bilal\Downloads\bilaaaal\Framatex\data" `
  -TargetData "D:\Bilal\Downloads\bilaaaal\Framatex-pg-data" `
  -BackupDest "D:\Bilal\Downloads\bilaaaal\Framatex-pre-cutover-backups" `
  -TargetDatabase "framatex"
```

L'assistant exécute, dans cet ordre :

1. confirmation que FRAMATEX est arrêté ;
2. instantané SQLite en lecture seule, `integrity_check`, comptages, fichiers et SHA-256 ;
3. archive ZIP vérifiée de SQLite et des deux stockages documentaires ;
4. démarrage du service PostgreSQL local ;
5. création de `framatex` si elle n'existe pas, ou acceptation seulement si elle ne contient aucune
   table publique ;
6. simulation et rapport des anomalies, sans écriture PostgreSQL ;
7. affichage des chemins et demande de saisir exactement `BASCULER VERS POSTGRESQL` ;
8. copie des documents dans un dossier de staging, contrôle SHA-256, puis renommage atomique ;
9. migration de toutes les tables dans une transaction unique ;
10. comparaison table/identifiant/contenu, clés étrangères, index de recherche, fichiers et SHA-256 ;
11. `pg_dump`, restauration dans une base temporaire neuve, vérification puis suppression de cette
    base temporaire ;
12. sauvegarde de `.env`, activation atomique de `framatex` et contrôle Alembic final.

Toute anomalie arrête la procédure avant activation. Une cible existante n'est jamais vidée. En cas
d'échec après création de la base ou copie du stockage, les éléments de diagnostic sont conservés et
`.env` reste inchangé ; choisir une nouvelle cible vide après analyse, sans supprimer automatiquement.

Après le message `BASCULE VALIDÉE` :

```powershell
.\scripts\start_windows.cmd
```

Options contrôlées :

```powershell
.\scripts\start_windows.cmd -Port 8001
.\scripts\start_windows.cmd -NoBrowser
.\scripts\start_windows.cmd -CheckOnly
.\scripts\start_windows.cmd -Reload
.\scripts\start_windows.cmd -Demo
```

## 5. Contrôles réalisés sur données fictives

Une fixture créée par les parcours API réels contenait 71 tables SQLite, 517 lignes au total et 71
fichiers référencés. Les tables virtuelles FTS et le registre de migrations SQLite sont reconstruits,
pas copiés comme données métier ; le transfert comparable portait donc sur 70 tables et 512 lignes.

| Contrôle | Résultat |
|---|---:|
| Source SQLite `integrity_check` | conforme |
| Fichiers source référencés | 71/71, SHA-256 conformes |
| Simulation | 70 tables, 512 lignes, 0 anomalie |
| Transfert transactionnel | 70 tables, 512 lignes |
| Comparaison ligne par ligne | conforme, 0 anomalie |
| Fichiers après copie | 71/71, SHA-256 conformes |
| Index de recherche | 5 lignes SQLite / 5 PostgreSQL |
| Hachage Argon2 d'un ancien compte fictif | strictement identique |
| Connexion du compte migré | réussie avant et après redémarrage PostgreSQL + serveur |
| Cible de stockage déjà existante | refusée sans écrasement |
| Base de démonstration comme cible définitive | refusée |

Le premier essai de recette a détecté que le processus de simulation créait trop tôt le dossier cible
vide. La séquence a été corrigée : la copie vérifiée précède désormais toute activation de
`FRAMATEX_DATA_DIR`. La recette complète a ensuite été rejouée avec succès sur une nouvelle cible.

## 6. Suites de non-régression

Tous les tests courants ont utilisé PostgreSQL 17 jetable. Le conteneur utilisé dans l'environnement
de test est uniquement une infrastructure de recette ; le produit livré et les scripts Windows ne
dépendent pas de Docker.

| Suite | Résultat |
|---|---:|
| Python `python -m pytest -q` | **247 réussis**, 0 échec |
| JavaScript `node --test tests/*.cjs` | **21 réussis**, 0 échec |
| API + Chromium `demo_full_platform.py` | **135/135 réussis** |
| Responsive | 1440, 1024, 820 et 390 px, 0 erreur JS bloquante |
| Doublon email | même email déposé deux fois → « Doublon détecté » réussi |
| Three.js / Dossier Jaune | chargé et animé à 1440 px |
| Tissu textile Three.js | animé et réactif au pointeur |
| Carrousel | navigation, agrandissement et fermeture réussis |
| Mobile 390 px | fallback statique, aucun WebGL coûteux |

Les suites couvrent notamment la création simultanée/idempotente de commandes, habilitations
techniciens, recherches et filtres par sous-dossier, dépôts/OCR, visionneuses, doublons, versions,
suppression/restauration/purge, historique, mémoire métier, Client et création du Dossier Jaune.

## 7. Sauvegarde et restauration après bascule

Sauvegarde PostgreSQL courante et documents :

```powershell
.\scripts\backup_postgresql_windows.cmd `
  -Dest "D:\Bilal\Downloads\bilaaaal\Framatex-pg-backups" `
  -Keep 14
```

Le ZIP contient `pg_dump -Fc`, les documents et un manifeste SHA-256. Il n'est publié qu'après
restauration vérifiée dans une base temporaire neuve. Les outils proviennent de PostgreSQL 17 local
(`PATH` ou `FRAMATEX_PG_BIN`), jamais de Docker.

Restauration de test dans un dossier et une base **neufs** :

```powershell
.venv\Scripts\python.exe scripts\backup_framatex.py restore `
  "D:\Bilal\Downloads\bilaaaal\Framatex-pg-backups\framatex-backup-AAAA.zip" `
  --to "D:\Bilal\Downloads\bilaaaal\Framatex-pg-restore-test" `
  --pg-database "framatex_restore_test"
```

La restauration refuse un dossier non vide et une base existante. Elle ne remplace jamais `framatex`.

L'archive pré-bascule conserve l'état SQLite historique. Revenir à cette archive ne récupère **aucune
écriture réalisée ensuite sous PostgreSQL**. Cette branche ne redémarre pas automatiquement sur
SQLite ; toute consultation historique doit rester explicite et en lecture seule.

## 8. Risques et limites restants

- **Migration réelle non exécutée** : seul le propriétaire du poste peut lancer la commande sur les
  chemins `D:` et examiner les anomalies éventuelles.
- **Windows natif non disponible dans l'environnement de validation** : PowerShell 5.1, le service
  `postgresql-x64-17`, CIM, Job Objects, Ctrl+C et les cinq variantes de paramètres ont été contrôlés
  par lecture/tests statiques, mais doivent recevoir le smoke test final sur le poste Windows.
- **Sauvegarde PostgreSQL native non exécutée ici** : `pg_dump`/`pg_restore` n'étaient pas installés
  sur l'hôte Linux. La procédure refuse clairement leur absence ; elle doit être validée avec les
  binaires PostgreSQL 17 du poste avant exploitation.
- La base cible doit être vide. Après un essai interrompu ayant créé des tables, aucune purge n'est
  automatique : analyser les rapports et sélectionner une nouvelle base vide.
- Les archives ne sont pas chiffrées par l'outil ; les conserver sur un volume Windows chiffré et
  protégé avec le secret `.env` sauvegardé séparément.

Le SHA exact de la tête distante de livraison doit être contrôlé après le dernier commit documentaire :

```powershell
git rev-parse origin/feat/postgresql-final-cutover
```

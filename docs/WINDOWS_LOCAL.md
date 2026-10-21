# Démonstration locale sous Windows

Depuis le dossier du dépôt, dans PowerShell :

```powershell
.\scripts\start_windows.cmd -Demo
```

Le lanceur vérifie tout, démarre le serveur, ouvre Chrome sur la landing et reste
actif dans la fenêtre. **Ctrl+C** ou la fermeture de la fenêtre arrête le serveur.
Après Ctrl+C, Windows peut demander « Terminer le programme de commandes (O/N) ? » :
répondez O, le serveur est déjà arrêté.

| Option | Effet |
| --- | --- |
| `-Demo` | Compte `admin.test@framatex.com` (créé si absent) et dossiers A–E (sans doublon), connexion admin vérifiée |
| `-Port 8010` | Port de départ (8000 par défaut ; le suivant libre est pris si besoin) |
| `-NoBrowser` | N'ouvre pas le navigateur |
| `-CheckOnly` | Vérifie tout puis arrête le serveur (diagnostic) |
| `-Reload` | Rechargement automatique du code (développement uniquement) |

## Mot de passe du compte de test

Aucun mot de passe n'est écrit dans le dépôt, les scripts, les journaux ou les captures.

- **Première fois.** Le lanceur demande le mot de passe à définir pour
  `admin.test@framatex.com`, deux fois, en saisie masquée (12 caractères minimum).
  Il n'est conservé qu'en mémoire, le temps de créer le compte (hash Argon2) et de
  vérifier la connexion.
- **Fois suivantes.** Le lanceur demande le mot de passe pour vérifier réellement
  la connexion (`POST /api/auth/login`, puis `GET /api/auth/me`). Appuyez sur
  Entrée pour passer cette vérification.
- **Sans saisie.** On peut le fournir dans une variable temporaire de la session
  PowerShell : `$env:FRAMATEX_DEMO_PASSWORD = Read-Host -AsSecureString | ConvertFrom-SecureString -AsPlainText`
  (PowerShell 7). Le lanceur la lit, puis la retire de l'environnement avant de
  démarrer le serveur.

## Étapes du lanceur

1. **Code.** Branche, commit, présence de tout `final/platform-review`, syntaxe Python.
2. **Python.** Environnement `.venv` créé si besoin, dépendances installées si elles manquent.
3. **Réseau.** Variables et proxy système. Seules les adresses locales sont exclues
   du proxy.
4. **Port.**
   - Les anciens serveurs FRAMATEX de ce dossier sont arrêtés.
   - Si 8000 est pris par un autre programme, celui-ci n'est pas touché et le port
     suivant libre est utilisé (8001, 8002…).
5. **Données.** Dossier `data`, verrou SQLite, sauvegarde du jour dans `data\backups`,
   migrations.
6. **Comptes.** Administrateurs et comptes Client ; en `-Demo`, compte de test et
   dossiers A–E.
7. **Serveur.** Uvicorn sans `--reload`, journaux dans
   `data\logs\uvicorn-<date>.err.log`, serveur lié à la fenêtre.
8. **Vérifications HTTP réelles.**
   - `/api/health`, `/`, `/espace-client`, `/espace-framatex` ;
   - les CSS / JS des trois pages, avec leur type ;
   - `Test-NetConnection` et `curl` ;
   - la connexion admin en `-Demo`.
9. **Navigateur.** Chrome est ouvert sur la landing ; la fenêtre affiche ensuite
   l'activité du serveur.

En cas d'échec, le lanceur affiche :

```
  ÉTAPE    : 5. Données (data, SQLite, sauvegarde, migrations)
  CAUSE    : Base SQLite verrouillée par un autre programme.
  SOLUTION : Fermez DB Browser for SQLite, un autre serveur FRAMATEX ou la synchronisation de fichiers, puis relancez.
```

Le journal complet, sans mot de passe, est dans
`data\logs\start-windows-AAAAMMJJ-HHMMSS.log`.

## Pourquoi Chrome affichait ERR_CONNECTION_REFUSED

Ce message signifie que plus aucun serveur n'écoute sur le port de l'onglet. Avec
le premier lanceur, cela pouvait arriver de quatre façons :

| Cause | Correction |
| --- | --- |
| Toute erreur du lanceur **après** le démarrage (ouverture du navigateur, contrôle réseau…) passait par le nettoyage final, qui arrêtait le serveur. | Une fois le serveur prêt, les erreurs sont signalées mais ne l'arrêtent plus. |
| Une fenêtre fermée pouvait laisser un serveur orphelin sur 8000 ; le lancement suivant prenait 8001, et l'ancien onglet visait un port qui ne répondait plus. | Le serveur est lié à la fenêtre (objet « job » Windows) et les anciens serveurs FRAMATEX sont arrêtés au démarrage : le port reste stable. |
| Une sélection dans la console (« Édition rapide ») pouvait geler le serveur, qui écrivait ses journaux dans la console. | Les journaux du serveur vont dans des fichiers ; la fenêtre ne fait que les afficher. |
| Ctrl+C, la fermeture de la fenêtre ou `-CheckOnly` arrêtent le serveur. | Comportement voulu, désormais annoncé clairement, avec la cause de tout arrêt imprévu. |

Si le serveur s'arrête de lui-même, la fenêtre l'indique avec ÉTAPE / CAUSE / SOLUTION
et les dernières lignes de son journal.

## Autres causes connues traitées

| Symptôme | Cause | Traitement |
| --- | --- | --- |
| « Application startup complete » mais aucune réponse | En `--reload`, Uvicorn peut s'attacher à un port déjà occupé par un ancien serveur figé (option `SO_REUSEADDR` sous Windows). | Démarrage sans `--reload`, après un test d'accès exclusif au port. |
| Page blanche, erreurs « MIME type » | Le registre Windows déclare `.js` en `text/plain` ; avec `nosniff`, Chrome refuse le fichier. | Types fixés dans `app/main.py`. |
| `curl` bloqué mais Chrome fonctionne | Variable `HTTP_PROXY` sans exception locale. | `localhost,127.0.0.1,::1` ajoutés à `NO_PROXY`. |

## Recette complète sur une base temporaire

```powershell
.venv\Scripts\python.exe scripts\demo_full_platform.py
```

Elle exécute 111 vérifications : la recette API, plus un parcours Chromium à 1440,
1024, 820 et 390 px. Elle utilise une base jetable et des mots de passe générés en
mémoire. Le parcours navigateur demande Playwright : `pip install -r requirements-dev.txt`
puis `python -m playwright install chromium`.

# Démarrage local sous Windows

Depuis le dossier du dépôt, dans PowerShell ou l'invite de commandes :

```bat
scripts\start_windows.cmd
```

Le serveur reste en marche dans la fenêtre ; **Ctrl+C** l'arrête. Options :
`-Port 8010`, `-NoBrowser`, `-Reload` (développement), `-CheckOnly` (diagnostic
et vérifications, puis arrêt).

## Ce que fait le lanceur

1. **Contexte.** Il affiche la branche Git et le commit. Il choisit le Python à
   utiliser dans cet ordre : environnement virtuel actif, puis `.venv` du dépôt,
   puis `python`, puis `py -3`. Il vérifie les dépendances. S'il en manque, il les
   installe dans un environnement virtuel (`.venv` est créé si Python est global).
2. **Réseau.** Il contrôle les variables `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`,
   le proxy système, le fichier `hosts` et la résolution de `localhost`. Si un proxy
   intercepte les adresses locales, il ajoute uniquement `localhost`, `127.0.0.1`
   et `::1` aux exceptions. Le proxy reste actif pour Internet.
3. **Port.** Il liste les processus en écoute (équivalent de
   `netstat -ano | findstr :8000`).
   - **Ce qui est arrêté** : uniquement les serveurs Python / Uvicorn de FRAMATEX,
     y compris un worker `--reload` orphelin qui garde le socket.
   - **Ce qui est laissé intact** : tout autre programme. FRAMATEX prend alors le
     port libre suivant.
   - **Vérification** : le port est réservé en accès exclusif avant le démarrage.
4. **Données.** Il vérifie que `data` est accessible en écriture et que la base
   SQLite n'est pas verrouillée par un autre programme. Il fait une sauvegarde par
   jour dans `data\backups\`, puis applique les migrations. Aucune donnée n'est
   supprimée.
5. **Démarrage.** Il lance Uvicorn **sans `--reload`** et désactive l'« Édition
   rapide » (QuickEdit) de la console.
6. **Vérifications.** Il interroge en HTTP réel, sans proxy :
   - `/api/health`, `/`, `/espace-client`, `/espace-framatex` ;
   - chaque CSS / JS des trois pages, avec son type MIME ;
   - `Test-NetConnection` ;
   - `curl.exe` avec et sans `--noproxy`.
7. **Navigateur.** Il ouvre `http://127.0.0.1:8000/`.

Chaque exécution est journalisée dans `data\logs\start-windows-<date>.log`.

## Causes connues d'un serveur « démarré » qui ne répond pas

| Symptôme | Cause | Traitement |
| --- | --- | --- |
| « Application startup complete », mais le navigateur et `curl` restent bloqués | En mode `--reload`, Uvicorn ouvre le port avec `SO_REUSEADDR`. Sous Windows, cette option permet de s'attacher à un port **déjà en écoute** : un ancien serveur figé (ou un worker orphelin) continue de recevoir les connexions. Sans `--reload`, Windows refuse le démarrage (erreur 10048). | Le lanceur arrête l'ancien serveur FRAMATEX et démarre sans `--reload`, après un test d'accès exclusif au port. |
| Les requêtes se débloquent quand on appuie sur Échap ou Entrée dans la console | Mode « Édition rapide » : une sélection à la souris dans la console met en pause le processus dès qu'il écrit un journal. | Le lanceur désactive l'Édition rapide pour sa fenêtre. |
| Page blanche ou sans styles, erreurs « MIME type » dans la console | Le registre Windows déclare `.js` (parfois `.css`) en `text/plain` ; avec `X-Content-Type-Options: nosniff`, Chrome refuse le fichier. | Corrigé dans `app/main.py` : les types des fichiers servis sont fixés explicitement. |
| `curl` bloqué mais Chrome fonctionne | Variable `HTTP_PROXY` sans exception pour les adresses locales. | Le lanceur ajoute `localhost,127.0.0.1,::1` à `NO_PROXY`. |
| Démarrage interrompu : « base verrouillée » | Base ouverte par un autre programme (DB Browser for SQLite, ancien serveur, synchronisation de fichiers). | Fermer ce programme, puis relancer. |

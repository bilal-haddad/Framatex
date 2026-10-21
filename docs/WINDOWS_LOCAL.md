# Démarrage fiable — Windows PowerShell 5.1 et suivants

Depuis la racine du dépôt :

```powershell
.\scripts\start_windows.cmd -Demo
```

Le port est choisi et l'unique URL est ouverte automatiquement. Gardez cette
fenêtre ouverte : **Ctrl+C ou fermeture volontaire = arrêt du serveur**. La fin
d'une sonde HTTP, du test Chromium ou l'ouverture de Chrome ne l'arrête pas.

## Préparation et administrateur

Python 3.11+ est requis. Le lanceur utilise exclusivement le `.venv` Windows de
ce dépôt, créé si absent, sans effacer un environnement existant. Il vérifie les
imports et installe les dépendances manquantes. En `-Demo`, il prépare Playwright
et Chromium : Chrome/Edge installé, sinon téléchargement Playwright. Le premier
démarrage nécessite Internet. Après nettoyage des anciens serveurs, SQLite est
contrôlée, sauvegardée et migrée selon le mécanisme existant. Une intégrité SQLite
non valide est bloquante. Aucun schéma ni migration métier n'est ajouté ici.

Fuseau horaire : Windows ne fournit pas la base IANA. Le paquet `tzdata` est
déclaré dans `requirements.txt` et vérifié par `scripts/windows_preflight.py` ;
sans lui, `ZoneInfo("Africa/Casablanca")` lève `ZoneInfoNotFoundError`. Une base
existante reçoit au démarrage la migration `0008_optional_rules` (colonne
`required` des règles de complétude, valeur 1 pour les règles existantes), par le
mécanisme de migration habituel, après la sauvegarde SQLite.

Compte : `admin.test@framatex.com`.

- Absent : mot de passe demandé deux fois, en saisie masquée.
- Existant : mot de passe demandé en saisie masquée, vérification **obligatoire**.
- Aucun compte existant réactivé, promu ou réinitialisé automatiquement.
- Dossiers de démonstration A–E chargés sans doublon.
- POST login 200, GET me (email, `admin=true`, rôle `Administrateur`), dashboard
  authentifié et vraie connexion Chromium vérifiés.

Aucun mot de passe dans Git, les arguments ou les journaux : mémoire et variable
enfant temporaire, retirée avant le worker ; stockage Argon2 existant.
`FRAMATEX_DEMO_PASSWORD` reste disponible pour une automatisation éphémère ; ne
pas l'enregistrer dans un profil PowerShell ou un fichier.

## Processus et ports

`windows_runtime.py` inventorie tous les processus (CIM), parents, sockets IPv4/
IPv6 (netstat indépendant de la langue Windows) et cwd des Python (psutil Windows).
Un worker `.venv` peut réellement utiliser l'exécutable **global** Python.

Seuls les serveurs identifiés comme appartenant à ce dépôt et leurs descendants
sont arrêtés, sur **tous** leurs ports : Uvicorn avec preuve chemin/cwd,
superviseur/worker du lanceur, worker reload `spawn_main` en écoute avec cwd exact.
PID et date de création sont revérifiés avant `taskkill /T /F` des anciens arbres.
Les autres programmes restent intacts. Un Python en écoute au cwd inaccessible
provoque un diagnostic **bloquant**, pas un arrêt hasardeux ni un basculement
laissant potentiellement un vieux FRAMATEX actif. Relancer sous le compte Windows
qui a démarré cet ancien serveur.

La disparition des processus/sockets est attendue. 8000 est préféré ; un autre
programme identifié sur 8000 est conservé et 8001, 8002, etc. sont essayés (20
candidats supplémentaires maximum). Un bind refusé couvre aussi les réservations
Windows Hyper-V/WSL.

Le socket choisi utilise `SO_EXCLUSIVEADDRUSE` et n'est **jamais libéré entre le
test et Uvicorn** : transfert `socket.share/fromshare` sous Windows, descripteur
hérité sous Linux. Le worker annonce son vrai PID avant transfert, distinct si
nécessaire du redirecteur `.venv/python.exe`.

## Cycle de vie

PowerShell prépare puis attend le superviseur Python au premier plan. Uvicorn
n'est plus lancé par `Start-Process`, ni capturé dans un pipeline. Aucun callback
PowerShell, `Register-EngineEvent` ou `WaitForExit` PowerShell ne possède sa durée
de vie.

Le superviseur possède un Job Windows non héritable `KILL_ON_JOB_CLOSE`. Le
redirecteur et le vrai worker sont rattachés, avec vérification du Job déjà
hérité. Le worker attend son socket avant démarrage. stdout/stderr vont directement
dans des **fichiers**, sans pipe à vider ni console susceptible de bloquer Uvicorn
pendant une sélection « Édition rapide ». Une vérification facultative en échec
laisse le serveur actif, en état dégradé.

Une identité d'instance non secrète et le PID sont vérifiés dans `/api/health` :
un ancien serveur répondant simplement 200 ne suffit pas. Sans
`FRAMATEX_RUNTIME_ID`, ces champs additionnels ne sont pas exposés.

Depuis la première réponse de la bonne instance, un moniteur indépendant contrôle
T+0, T+2, T+10, T+30, T+60 : même PID, réponse < 3 s et socket LISTENING. Windows
compare aussi les propriétaires à netstat. Le succès global n'est annoncé qu'après
ces cinq sondes, sans échec des pages, assets, connexion ou Chromium.
La santé HTTP continue ensuite d'être vérifiée toutes les 15 secondes ; un échec
met l'état en dégradé sans provoquer l'arrêt du serveur.

`data/runtime.json` (ou `FRAMATEX_DATA_DIR/runtime.json`) contient notamment :

```json
{"host":"127.0.0.1","port":8001,"url":"http://127.0.0.1:8001/","pid":1234}
```

Également : superviseur, identité, contrôles et état `checking/ready/degraded`.
Retrait à l'arrêt uniquement si le fichier appartient encore à cette instance.
Historique : `data/logs/runtime-<identité>.json`, `uvicorn-*.out.log` et
`uvicorn-*.err.log`. En cas de mort imprévue, la vraie fin de stderr est affichée.
Un rapport historique avec `stopped_at` ne prouve pas qu'un serveur tourne encore.

## Interface et cache

API internes : délai de 8 s incluant le corps, 60 s pour les fichiers. API Client :
8 s, upload XHR 60 s. Garde indépendante de `app.js` : après 10 s de démarrage
bloqué, y compris script principal absent/MIME invalide/en erreur, affichage :

> Impossible de joindre le serveur FRAMATEX. — Réessayer

Le bouton recharge la même URL. Un vrai 401 affiche la connexion ; une API
indisponible affiche une erreur. L'initialisation attend `DOMContentLoaded` et
toutes les extensions. Les changements d'écran sont sérialisés : une réponse
ancienne ne remplace plus la page suivante.

Pages/API et JS/CSS : `Cache-Control: no-store`. Les principaux points d'entrée
ont une clé `?v=runtime-final-1`, pour sortir d'un ancien cache déjà frais.
Aucun service worker. Types MIME Windows corrigés conservés ; CSP, `nosniff`,
cookies HttpOnly et règles d'autorisation inchangés.

## Diagnostic en lecture seule

```powershell
.\scripts\diagnose_windows.cmd
```

Affiche branche, SHA, Python, DB (URL externe masquée), migrations appliquées
(SQLite `mode=ro`), ports/PID, ancien serveur, santé/identité et URL finale.
Appels externes bornés : budget inférieur à 30 s sur une machine normalement
réactive. Aucun import `app.core`, donc aucune DB, clé, table ou migration créée.
Une URL déclarée n'est pas présentée comme une preuve de disponibilité.

## Recette reproductible

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\qa_platform_review.py
.venv\Scripts\python.exe scripts\demo_full_platform.py
.venv\Scripts\python.exe scripts\demo_browser_full.py
```

Les deux dernières commandes exécutent la même suite API + vrai Chromium + T+60,
sur base temporaire. Captures 1440/1024/820/390 px ; cycle documentaire A/B existant
réutilisé intégralement. Les pannes HTTP/timeout/MIME/script absent sont injectées
dans des contextes dédiés puis « Réessayer » réellement cliqué. Playwright absent
ou navigateur non démarré = échec, jamais recette complète passée.

OCR : Tesseract et langues `fra/eng` requis dans PATH/TESSDATA_PREFIX. Le lanceur
ne prétend pas installer Tesseract ; les recettes OCR réelles restent rouges
s'il manque.

## Limites et options

Développé/exercé sous Linux : worker, socket, API, Chromium, migration de copie,
T+60 réels. La politique Windows PID/parents/cwd/ports/netstat a des tests unitaires
portables. **CIM, WSADuplicateSocket, Job Object et Ctrl+C/fermeture d'une vraie
console PowerShell 5.1 restent à exécuter sur Windows.** Aucun succès natif Windows
n'est revendiqué sur la seule foi des tests Linux.

`-NoBrowser` : pas d'ouverture visible, mais smoke test headless en `-Demo`.
`-Port` : premier candidat. `-CheckOnly` : arrêt automatique **explicitement
demandé**, après T+60. `-Reload` : signalé et ignoré, pour conserver un worker
unique et un port stable.

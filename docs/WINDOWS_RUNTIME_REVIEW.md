# Correction runtime et recette finale

Branche : `fix/windows-runtime-final`, créée directement sur
`fix/windows-demo-final` / `fe88076a29ec7baf4f027f8c65e2c47cc310772e`.
Aucun merge de main, aucun changement de design/CSS/landing ou de schéma métier.
Le SHA de livraison est donné par `git rev-parse HEAD` et le compte rendu final.

## Constats indépendants

| Constat vérifié dans la base | Traitement |
| --- | --- |
| `fetch` initial `/api/auth/me` sans délai ; corps HTTP également sans borne. | Timeout complet 8 s, écran explicite et Réessayer. |
| HTML « Chargement… » sans garde si `app.js` ne s'exécute pas. | Garde indépendante 10 s, test navigateur de mauvais MIME et script absent. |
| Initialisation lancée avant la fin des extensions `defer`. | Attente de DOMContentLoaded, puis authentification et navigation. |
| Requêtes SQLAlchemy synchrones dans le middleware async d'accès. | Exécution dans le threadpool ; test de santé/page pendant un contrôle bloqué. Autorisations identiques. |
| Réponse d'une ancienne navigation pouvant écraser la page suivante. Reproduit pendant dashboard → actions → commandes. | Sérialisation des navigations et ouvertures de dossiers ; tests JS et clics réels. |
| Nettoyage basé sur ExecutablePath `.venv`, alors que Windows peut utiliser le Python global ; repli acceptant tout Uvicorn sur le port. | Inventaire parents/cwd réel/ports, identification exacte du dépôt, PID/date revérifiés, aucun arrêt de programme étranger ; ambiguïté bloquante. |
| Test de bind suivi d'une libération avant lancement. | Socket exclusif conservé et transmis au véritable PID worker. |
| Santé 200 pouvant provenir d'un ancien serveur ; absence de preuve à 60 s. | Identité d'instance + PID, cinq sondes indépendantes puis surveillance continue. |
| Vérification admin facultative, pouvant être passée avec un résultat sans erreur. | Mot de passe masqué obligatoire en Demo, HTTP authentifié + Chromium. |
| Recette navigateur absente pouvant être affichée comme un succès API. KPI seulement non vides et certaines recherches sans prédicat pertinent. | Manque Chromium = rouge ; KPI, recherche, OCR et audit vérifiés strictement. |

Les types MIME explicitement corrigés **étaient déjà présents** au commit de base.
Ils ont été conservés et retestés avec un registre Windows simulé corrompu.
Aucun service worker n'est trouvé. Les en-têtes no-store et nouvelles clés des
points d'entrée protègent contre un ancien cache frais.

Sans journaux du PC concerné, il serait incorrect d'attribuer avec certitude son
ERR_CONNECTION_REFUSED à une exception particulière. Le nouveau lanceur rend
observables identité, PID, stderr et arrêt, et ne lie plus la vie d'Uvicorn aux
contrôles PowerShell/navigateur. Sa fermeture automatique n'est autorisée que par
Ctrl+C, fermeture volontaire, worker mort ou `-CheckOnly` explicitement demandé.

## Validation et preuves

Base reproduite : 140 Python, 16 scripts JS. Livraison : 166 Python, 17 scripts JS,
94 contrôles API/runtime (87 existants + 7), 131 contrôles de recette complète
(contre 111 annoncés), dont 37 contrôles navigateur supplémentaires à l'API/runtime.
Le cycle documentaire navigateur réutilise aussi ses 15 étapes déjà livrées.
Un avertissement préexistant Starlette TestClient/httpx reste sans test ignoré.

Commandes exactes :

```sh
PYTHONPATH=. .venv/bin/python -m pytest -q
for file in tests/*.cjs; do node "$file" || exit; done
PYTHONPATH=. .venv/bin/python scripts/qa_platform_review.py --output /workspace/artifacts/windows-runtime-api
PYTHONPATH=. .venv/bin/python scripts/demo_full_platform.py --output /workspace/artifacts/windows-runtime-final
```

Pour l'OCR réel de ce cloud, `TESSDATA_PREFIX=/workspace/.cache/framatex-tessdata`
(modèles Tesseract fra/eng déjà installés pendant l'onboarding). Aucun moteur
OCR n'est simulé. Les JSON de recette incluent date, SHA source, état dirty, chaque
contrôle et les preuves T+0/2/10/30/60 ; les captures sont dans `captures/`.
Ils restent hors Git, ainsi que les DB et mots de passe aléatoires éphémères.

Parcours : inscription/pending/activation/login, brouillon/soumission/étude,
acceptation et rejet distinct, demande de pièce/V1/correction/V2/acceptation,
publication explicite/téléchargement/retrait, suspension et déconnexion.
Demande → Dossier Jaune : quatre rubriques, origine/référence/date, lien permanent,
idempotence de création, bouton d'ouverture et refus d'accès Client aux API internes.
Isolation A/B, commentaires/mémoire/audit non publiés et retrait sont vérifiés.

FRAMATEX : KPI réels, actions visibles des trois panneaux cliquées vers la bonne
cible, quatre rubriques, dépôt, SHA, V1/V2/V3, commentaire, validation, impacts,
cohérence, Excel (changement/constante/#REF!), OCR et confirmation, EML et engagement,
recherche, mémoire atelier et audit filtré. Formats PDF/DOCX/XLSX/PNG/JPG/TXT/EML/CSV,
refus EXE/faux PDF/>20 Mo, doublons et cinq états de complétude couverts par API.
Responsive 1440/1024/820/390 sans débordement ni erreur JS sur les parcours normaux.

## Processus et ports observés ici

Linux, avant nettoyage final : ancien PID 5622, parent 1, cwd vérifié
`/workspace/Framatex`, commande `.venv/bin/python -m uvicorn app.main:app`, socket
`127.0.0.1:8765`, démarré le 21 octobre à 07:17 UTC. Arrêt SIGTERM propre demandé ;
socket libéré. Le PID peut rester zombie chez le PID 1, sans code exécuté ni socket.
Aucune DB ou donnée de cet ancien serveur n'a été supprimée.

Les serveurs de recette utilisent des ports éphémères, une identité distincte et
leur propre DB temporaire. Les rapports donnent le port/PID exact et les cinq
réponses de la même instance. Après fermeture des contextes Chromium, les trois
pages et la santé sont recontrôlées **avant** l'arrêt volontaire de la recette.

Les tableaux Windows dans les rapports Linux sont explicitement non applicables,
pas une prétendue preuve d'absence de processus sur le PC Windows de l'utilisateur.

## Fichiers touchés

- Backend : `app/main.py` (threadpool, cache, identité locale de santé).
- Dépendances : `requirements.txt` (psutil uniquement sur Windows).
- Lanceur : `scripts/start_windows.cmd`, `scripts/start_windows.ps1`,
  `scripts/windows_preflight.py`, nouveau `scripts/windows_runtime.py` et
  `scripts/diagnose_windows.cmd`.
- Recettes : `scripts/qa_platform_review.py`, `scripts/demo_full_platform.py`,
  nouveau `scripts/demo_browser_full.py`, `scripts/validate_client_workflow_ui.py`
  (réutilisation du même navigateur sans double démarrage Playwright).
- Interface : `static/app.js`, `static/index.html`, nouveaux `static/boot-guard.js`
  et `static/runtime-navigation.js`, `static/client/api.js`,
  `static/client/client.js`, `static/client/index.html`. Aucun CSS ni visuel changé.
- Tests : `tests/test_windows_local.py`, nouveaux `tests/test_windows_runtime.py`
  et `tests/test_runtime_frontend.cjs`.
- Documentation : `README.md`, `docs/WINDOWS_LOCAL.md`, ce rapport.

## Limite à ne pas masquer

La machine de travail est Linux. CIM, duplication de socket, redirecteur venv,
Job Object et événements de vraie console Windows PowerShell 5.1 n'ont **pas** été
exécutés nativement ici. Politique de décision testée avec snapshots Windows et
API natives écrites défensivement ; cela ne remplace pas le test sur ce PC.
Exécuter `.\scripts\start_windows.cmd -Demo` puis, en cas de défaut,
`.\scripts\diagnose_windows.cmd` et conserver les journaux. Aucun mot de passe
réel de `admin.test@framatex.com` n'a été demandé ni testé dans ce cloud : la
recette crée cette même adresse dans sa DB jetable, avec un secret aléatoire,
et vérifie réellement son login HTTP et Chromium ; le lanceur testera le vrai.

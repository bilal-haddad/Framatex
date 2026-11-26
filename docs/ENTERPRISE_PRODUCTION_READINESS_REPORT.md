# FRAMATEX — Préparation à une utilisation en entreprise · rapport de livraison

Branche `feat/enterprise-production-readiness`, créée depuis `fix/document-workflow-reliability`
(`546f7243`). Toutes les améliorations précédentes (Claude et Codex) sont conservées ; `main` n'est pas
modifié ; aucun déploiement n'a été lancé. Détail des constats : `ENTERPRISE_READINESS_AUDIT.md` ;
architecture : `PRODUCTION_ARCHITECTURE.md` ; feuille de route : `ENTERPRISE_ROADMAP.md`.

> **Verdict : la plateforme n'est pas encore prête pour la production.** Elle l'est pour un **pilote
> encadré** sur un serveur unique, sous réserve des exigences bloquantes restantes : HTTPS, sauvegarde
> planifiée avec restauration testée, politique de conservation validée par FRAMATEX (voir § 7).

## 1. Corrections effectuées

| Lot | Contenu | Commit |
|---|---|---|
| Suppression définitive | Corbeille enrichie (fichier, commande, sous-dossier, type, version, taille, auteur et date de suppression) ; « Supprimer définitivement » réservé à l'administrateur, confirmation renforcée (motif + « SUPPRIMER ») ; refus si dépendance métier (17 tables vérifiées) ou conservation obligatoire/inconnue sans vérification administrative motivée ; données dérivées effacées (OCR, index, inspections, rapprochements, commentaires) ; fichier effacé **après** validation en base via une file reprise au démarrage, jamais s'il est encore référencé ; trace minimale dans l'audit | `a0e0f26` |
| Requêtes et API | Fin des N+1 (complétude, synthèse, priorités, doublons, recherche) ; historique préfiltré ; liste paginée ; ouverture de commande en 6 requêtes au lieu de 22, modules secondaires à la demande ; idempotence de création ; limites des API configurables | `ab65f20` |
| Concurrence | Cause racine des blocages en charge : connexion gardée pendant transferts et OCR → connexion rendue au pool ; pool dimensionné ; analyses simultanées configurables | `7579dda` |
| Multi-processus | Verrou de migration inter-processus ; WAL optionnel ; bancs reproductibles | `175f055` |
| Sécurité | Pillow 13 (42 vulnérabilités connues corrigées) ; jeton Client refusé côté interne ; documentation d'API masquée en production ; HSTS derrière HTTPS ; limites des API métier (429 + `Retry-After`) ; option clés étrangères | `ab65f20`, commit final |
| Exploitation | `X-Request-ID`, journal d'accès JSON, `/api/health/ready`, `/metrics` (jeton) ; `backup_framatex.py` (sauvegarde en ligne, manifeste SHA-256, rotation, restauration vérifiée, contrôle des clés étrangères) | `ab65f20`, `7579dda` |
| Correctif fonctionnel | Compteur de documents d'un sous-dossier : documents supprimés exclus | `ab65f20` |

Migrations additives : `0018_document_purge` (file d'effacement, vérifications de conservation, index de
performance), `0019_idempotency`.

## 2. Performances avant / après

### 2.1 Endpoints (200 commandes, 3 000 documents, 50 000 événements ; un utilisateur ; médianes)

| Requête | Avant | Après |
|---|---|---|
| Tableau de bord général | 8 864 ms (3,4 Mo) | 2 533 ms (2,0 Mo) |
| Historique global | 8 030 ms | 11 ms |
| Liste des commandes | 3 239 ms (1,8 Mo, tout) | 426 ms (page de 50) |
| Recherche documentaire | 576 ms | 170 ms |
| Recherche technicien | 622 ms | 135 ms |
| Ouverture d'une commande | 22 requêtes | 6 requêtes |

Sources : `docs/enterprise-load/benchmark-avant.json`, `benchmark-apres.json`.

### 2.2 Charge (scénario complet par utilisateur : liste, création, ouverture, fiche, dépôts PDF avec analyse/OCR, Excel et Word, aperçus, recherche, validation, historique, suppression, restauration, habilitations, tableau de bord)

| Configuration | Utilisateurs | Erreurs | Médiane | p95 | p99 |
|---|---|---|---|---|---|
| Référence `546f724`, 1 processus | 20 | **6,7 %** (délais) | 480 ms | 120 s | 120 s |
| Après requêtes, avant correctif du pool | 20 | 1,7 % (pool épuisé) | 428 ms | 60 s | 61 s |
| Après, 1 processus | 20 / 30 / 50 | 0 / 0 / 0 | 279 ms / 0,8 s / 1,5 s | 2,6 s / 14 s / **48 s** | 6,9 s / 25 s / 74 s |
| Après, 4 processus + WAL | 20 / 30 / 50 | 0 / 0 / 0 | 113 / 206 / 373 ms | 1,2 / 2,4 / 5,3 s | 1,8 / 7,7 / 21 s |
| Après, 4 processus + WAL | 75 / 100 | 0 / 0 | 639 ms / 1,0 s | 11,5 s / 27,5 s | 66 s / 116 s |
| Après, 4 processus + WAL, **charge soutenue 120 s** | 50 | **0** | 428 ms | **2,7 s** | 5,2 s |

Soutenu : 6 020 requêtes, 46 req/s. Le p99 des paliers élevés est dû au **tableau de bord général**
(médiane 110 s à 100 utilisateurs simultanés, sur ~250 commandes) ; hors tableau de bord, p95 ≤ 11 s à
100 utilisateurs. CPU (4 processus) : 171 % à 50 utilisateurs, 243 % à 100 (sur 400 %) ; mémoire RSS
totale 1,0–2,0 Go. Aucun verrou SQLite, aucune erreur serveur à aucun palier après correctif.
Intégrité : toutes les créations confirmées sont en base (645/645), aucun doublon, documents comptés.
Sources : `docs/enterprise-load/*.json`.

## 3. Capacité réellement vérifiée

Sur 4 vCPU / 16 Go, SQLite, client de charge sur la même machine :

- **Un processus (configuration actuelle de démonstration Windows)** : 20 utilisateurs simultanés
  intensifs avec p95 2,6 s et 0 erreur. À 30, l'usage se dégrade (p95 14 s). **Capacité vérifiée :
  20 utilisateurs actifs simultanés.**
- **Quatre processus + WAL** : 50 utilisateurs en charge soutenue (p95 2,7 s, 0 erreur) ; 100
  utilisateurs sans erreur ni perte, mais avec un tableau de bord inutilisable. **Capacité vérifiée
  pour un usage confortable : 50 utilisateurs actifs simultanés, hors tableau de bord général.**
- 100 utilisateurs **n'est pas** une capacité validée pour un usage normal (p99 116 s) : il faut
  d'abord la synthèse précalculée (audit A-02) et la limite de connexion partagée (F-07).

« Utilisateur actif simultané » = un compte qui enchaîne le scénario complet sans pause : un
collaborateur réel est bien moins intensif ; le nombre de collaborateurs supportés est donc supérieur,
mais n'a pas été mesuré tel quel.

## 4. Tests exécutés

| Suite | Résultat |
|---|---|
| `pytest` (dont `test_document_purge.py` : purge, blocages, conservation, file d'effacement, idempotence, supervision, limites) | **240 réussis** ; aussi verts avec les clés étrangères SQLite appliquées |
| Tests JS (`node tests/*.cjs`) | **21/21** |
| `validate_document_purge_ui.py` (nouvelle) : corbeille, destruction de document et de version, URL directe, compteurs, conservation, responsable refusé, mobile 390 px | **9/9** |
| `validate_document_reliability_ui.py` (étendue) | **19/19** |
| Autres recettes Chromium et revues (batterie finale) | voir ci-dessous |
| Outils | bandit (0 constat élevé ; 3 « moyens » vérifiés faux positifs), ruff (aucune erreur bloquante), pip-audit (0 vulnérabilité après correctif) |
| Sauvegarde | Sauvegarde de 4 856 versions, restauration dans un dossier neuf vérifiée, altération d'un fichier détectée |

Batterie finale sur le code livré (limites des API actives) : **toutes réussies** —
`validate_document_purge_ui`, `validate_document_reliability_ui`, `validate_buttons_profiles_ui`
(135 actions, 5 profils), `validate_document_deletion_ui`, `validate_costume_technician`,
`validate_document_workspace`, `validate_business_requirements_ui`, `validate_client_workflow_ui`,
`validate_document_viewer_ui`, `validate_access_ui`, `validate_business_memory_ui`,
`validate_internal_ui`, `validate_sessions_ui`, `validate_landing_motion`,
`validate_partnership_carousel`, `validate_cinematic_3d`, `qa_platform_review` (**96/96**),
`demo_full_platform` (**135/135**). Charge de contrôle (4 processus, limites actives) : 20 et 50
utilisateurs sans erreur (p95 1,2 s / 5,0 s), charge soutenue 30 utilisateurs/60 s : 63 req/s,
p95 1,6 s, 0 erreur, 320/320 créations (`docs/enterprise-load/final-4-processus-avec-limites.json`).

## 5. Vulnérabilités identifiées

Corrigées : dépendance Pillow vulnérable (critique) ; documentation d'API publique ; contrôle du type de
jeton ; HSTS absent ; absence de limite sur les API métier. Restantes (voir audit D, E, F) : absence
d'antivirus, HTTPS et chiffrement au repos dépendant du déploiement, limite de connexion par processus,
révocation de session lue dans le journal (indexée).

## 6. Risques restants

1. Tableau de bord général en O(commandes) (A-02) — premier frein à la montée en charge.
2. Analyse/OCR dans la requête (A-10) — dépôts lents en pic, repli « type à vérifier ».
3. SQLite à un seul écrivain et clés étrangères à activer après contrôle (B-01, B-02).
4. Sauvegarde non encore planifiée ni externalisée chez FRAMATEX (E-01).
5. Interface fondée sur des surcharges globales (F-01) : risque de régression à chaque évolution,
   atténué par la batterie de recettes.

## 7. Recommandations (ordre)

Avant tout déploiement réel (P0) : HTTPS + `FRAMATEX_ENV=production` + `FRAMATEX_COOKIE_SECURE=1` ;
sauvegarde nocturne planifiée, copie hors site chiffrée, restauration testée ; validation de
`retention-policy.json` par FRAMATEX. Pour le pilote (P1) : clés étrangères, limite de connexion
partagée, antivirus, alertes. Pour la production (P1/P2) : synthèse précalculée, workers + Redis,
PostgreSQL, Docker Compose, supervision Prometheus/Grafana. Voir `ENTERPRISE_ROADMAP.md`.

## 8. Architecture proposée

Pilote : serveur unique (actuel), sauvegardé et en HTTPS. Production : Nginx → 2 à 4 processus API →
PostgreSQL, Redis + workers documentaires, stockage local chiffré puis MinIO, Prometheus/Grafana.
Configurations A/B/C détaillées dans `PRODUCTION_ARCHITECTURE.md`.

## 9. Fonctionnalités préservées

Landing, 3D, carrousel, connexion, fiche commande (14 champs), visionneuse, historique, doublons et
corbeille logique, synchronisation automatique, recherche technicien, documents complémentaires,
espace Client, habilitations par sous-dossier, démarrage Windows (un processus) : inchangés et
couverts par la batterie de recettes. Une seule recette existante a été adaptée (Costume : le refus d'un
module secondaire est désormais vérifié à l'ouverture de son onglet, puisque ce module est chargé à la
demande ; l'intention est conservée).

## 10. Commit final

Branche `origin/feat/enterprise-production-readiness` : `a0e0f26`, `ab65f20`, `7579dda`, `175f055`,
`91d28e9`, puis le commit de ce rapport (SHA donné dans le message de livraison, vérifiable par
`git ls-remote origin feat/enterprise-production-readiness`). `main` non modifié.

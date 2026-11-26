# FRAMATEX — Feuille de route vers la production

Quatre étapes, chacune avec ses critères de validation. Les priorités P0–P3 renvoient à
`ENTERPRISE_READINESS_AUDIT.md`. Les durées sont des estimations pour un développeur expérimenté à
temps plein, à confirmer.

## Étape 0 — Prototype actuel (branche `feat/enterprise-production-readiness`)

Fait dans cette branche : suppression définitive contrôlée, requêtes groupées et chargement à la
demande, correctif d'épuisement du pool de connexions, idempotence de la création de commande,
durcissements (Pillow 13, jetons, documentation d'API, HSTS), supervision de base, sauvegarde et
restauration vérifiées, bancs de mesure et de charge reproductibles.

## Étape 1 — Pilote chez FRAMATEX (≈ 3 à 4 semaines)

Objectif : 5 à 20 collaborateurs réels sur un serveur unique (configuration A), données réelles,
sauvegardes testées.

| # | Travail | Priorité | Dépendances | Effort |
|---|---|---|---|---|
| 1.1 | Serveur dédié (VM Windows ou Linux), disque chiffré, HTTPS (Nginx ou IIS + certificat), `FRAMATEX_ENV=production`, `FRAMATEX_COOKIE_SECURE=1` | P0 | — | 2–3 j |
| 1.2 | Sauvegarde nocturne planifiée + copie hors site chiffrée + **test de restauration** consigné | P0 | 1.1 | 1–2 j |
| 1.3 | Politique de conservation documentaire validée par FRAMATEX (`retention-policy.json`) | P0 | décision FRAMATEX | 1 j + validation |
| 1.4 | Activer `PRAGMA foreign_keys` en préproduction, corriger les orphelins, puis en production | P1 | 1.2 | 3–5 j |
| 1.5 | Limite de connexion partagée (base) et révocation de session indexée | P1 | — | 1–2 j |
| 1.6 | Antivirus sur les dépôts (ClamAV, quarantaine) | P1 | 1.1 | 2–3 j |
| 1.7 | Supervision : alerte santé/disque/sauvegarde (même sans Grafana) | P1 | 1.1 | 1–2 j |
| 1.8 | Formation des utilisateurs, procédure d'incident, journal des anomalies du pilote | P1 | — | 2 j |

Critères de sortie : 4 semaines sans perte de données ; sauvegarde restaurée avec succès au moins
deux fois ; aucune erreur 5xx non expliquée ; p95 < 2 s sur les écrans courants avec la charge
réelle ; validation des utilisateurs clés.

## Étape 2 — Production (≈ 6 à 10 semaines)

Objectif : configuration B (20–60 collaborateurs), plusieurs processus, traitements asynchrones.

| # | Travail | Priorité | Dépendances | Effort |
|---|---|---|---|---|
| 2.1 | ~~Migration PostgreSQL~~ **fait** (branche `feat/postgresql-migration`, voir POSTGRESQL_MIGRATION_REPORT.md) ; reste : serveur PostgreSQL dédié, optimisation liste/tableau de bord | P1 | 1.4 | — |
| 2.2 | Workers documentaires (Redis + RQ/Celery), états de tâche visibles, reprise automatique | P1 | — (compatible SQLite) | 2–3 sem |
| 2.3 | Docker Compose (Nginx, API ×N, worker, PostgreSQL, Redis), secrets, volumes, migrations dédiées | P1 | 2.1, 2.2 | 1–2 sem |
| 2.4 | Synthèse par commande précalculée (tableau de bord en O(1) par commande) | P1 | — | 1–2 sem |
| 2.5 | Prometheus + Grafana + alertes, journaux centralisés | P2 | 2.3 | 1 sem |
| 2.6 | Stockage objet (MinIO) si plusieurs serveurs ; contrôle d'intégrité périodique | P2 | 2.3 | 1–2 sem |
| 2.7 | MFA administrateurs ; SSO si annuaire | P2 | — | 1 sem |
| 2.8 | Isolation des tests (base par test), CI avec recettes Chromium et pip-audit | P2 | — | 1 sem |

Critères de sortie : test de charge de la configuration cible à 1,5 × la charge attendue sans erreur ;
PRA testé (RTO ≤ 4 h) ; audit de sécurité externe ; documentation d'exploitation.

## Étape 3 — Plateforme évolutive avec IA (après stabilisation)

| # | Travail | Prérequis |
|---|---|---|
| 3.1 | Couche d'accès « IA » : uniquement par l'API ou `can()`, jamais de requête SQL libre ; journal de chaque consultation | 2.1 |
| 3.2 | Index sémantique (pgvector) des seules versions confirmées, avec provenance (version, page, auteur) | 2.1, 2.2 |
| 3.3 | Modèle local (Ollama) sur serveur dédié GPU/CPU, aucune donnée envoyée à l'extérieur | 3.1 |
| 3.4 | RAG filtré par habilitations **avant** la recherche (pas après) ; réponses citant leurs sources | 3.2, 3.3 |
| 3.5 | Séparation stricte proposé / confirmé (déjà en place pour l'extraction) ; aucune écriture sans validation humaine | — |

## Ce qui doit précéder tout déploiement réel

1.1, 1.2 (avec restauration testée), 1.3, et la décision explicite de FRAMATEX sur la capacité visée
(la capacité mesurée de la configuration actuelle est donnée dans le rapport ; elle ne doit pas être
extrapolée).

## Ce qui peut attendre le pilote

PostgreSQL, Redis, Docker, MinIO, Grafana, MFA, IA : utiles pour grandir, non bloquants pour un
pilote limité sur un serveur unique correctement sauvegardé.

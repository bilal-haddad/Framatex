# Framatex 0.20 — Pilotage du Dossier Jaune

Le dashboard interne présente les huit indicateurs métier, les documents
manquants, les actions précises, les complétudes, les alertes et les activités
réelles, filtrés par les habilitations existantes.

Commandes enrichies, recherche documentaire par version, audit filtré,
commentaires internes, mémoire d'expérience et consultation des demandes Client
complètent les modules existants. Les dépôts conservent SHA-256, versions et
contrôles ; les doublons sont signalés et les CSV UTF-8 validés. Les propositions
OCR/classement restent soumises à confirmation humaine.

Migration additive : `0005_internal_operations`. Après sauvegarde de `data/` et
arrêt des écritures, exécuter `python -m app.migrate upgrade`.

Le seed A–E est disponible avec
`python -m app.seed_operations_demo --admin-email <compte-existant>`.

Les comptes, mots de passe, sessions et liens QR existants sont conservés.
`/espace-framatex` ouvre l'application interne, `/espace-client` utilise le backend
Client existant et `/` reste le point d'entrée historique. Aucune landing
institutionnelle réalisée n'était présente dans le checkout ; elle n'a pas été
remplacée.

Aucun chatbot, appel d'API IA ou faux connecteur ORLI n'est ajouté. Le guide
déterministe, la publication interne contrôlée et les demandes fournisseurs
simulées restent disponibles.

Recette : 102 tests Python, 14 scripts de tests JavaScript et 52 captures sur les
largeurs 1440/1024/820/390. Voir [le guide complet](docs/ESPACE_FRAMATEX.md) pour les
API, l'audit initial, les décisions de sécurité, les fichiers et les limites.

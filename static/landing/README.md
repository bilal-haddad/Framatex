# Assets retenus — Landing page FRAMATEX

Ce dossier est réservé aux visuels de la nouvelle page d’accueil. Ne pas générer de logo alternatif : utiliser uniquement le logo FRAMATEX fourni.

## Assets validés / à intégrer

- `logo-framatex.jpg` — logo FRAMATEX officiel fourni par l’équipe.
- `hero-textile-woman.jpg` — visuel principal du hero : femme dans un environnement textile. À utiliser dès le haut de la landing page, avec le texte et les CTA dans la zone libre à gauche.
- `partnership-meeting.jpg` — photographie réelle de la réunion/partenariat au Maroc.
- `ecc-partnership-section.jpg` — référence de la section « Framatex s’associe à l’École Centrale Casablanca » ; sert de référence de contenu/mise en page, pas de hero.
- `value-chain-section.jpg` — référence visuelle de la section « De la collection jusqu’à la livraison de vos produits finis » avec les 5 étapes : Étude de vos besoins, Collectionning, Stratégie de sourcing, Gestion de production, Gestion de livraison.

## Règles de design

- Reprendre l’identité visuelle du site FRAMATEX : bleu profond, blanc, bleu clair, typographie sobre, beaucoup d’espace, mise en page éditoriale.
- Éviter les cartes arrondies en excès, gradients artificiels, icônes décoratives inutiles et tout rendu qui donne l’impression d’un template généré par IA.
- Conserver une cohérence forte avec le site institutionnel FRAMATEX tout en présentant la nouvelle plateforme numérique.
- La page d’accueil doit introduire clairement deux entrées : **Espace Client** et **Espace FRAMATEX**.
- La section partenariat ECC doit être présente sur la landing page.
- La chaîne de valeur FRAMATEX doit également être présente et pourra servir de transition vers les fonctionnalités de la plateforme.

## Ordre provisoire de la landing page

1. Header FRAMATEX
2. Hero avec `hero-textile-woman.jpg`
3. Présentation courte de la plateforme / digitalisation du dossier jaune
4. Deux accès : Espace Client / Espace FRAMATEX
5. Chaîne de valeur FRAMATEX (5 étapes)
6. Présentation du dossier jaune numérique et de ses quatre sous-dossiers
7. Partenariat FRAMATEX × École Centrale Casablanca
8. Contact / footer inspiré du site institutionnel FRAMATEX

Les détails fonctionnels et le prompt Claude seront définis séparément avant modification du frontend.

## Intégration technique (landing v1)

- `index.html`, `landing.css`, `landing.js`, `landing-redirect.js` : page d’accueil servie sur `/`.
- L’Espace Client est servi sur `/espace-client` depuis `static/client/` (voir son README).
- L’application interne (connexion FRAMATEX) est servie sur `/espace-framatex` ; les anciens liens QR `/#/launch/<id>` y sont redirigés.
- Fichiers attendus par la page (noms exacts) : `logo-framatex.jpg`, `hero-textile-woman.jpg`, `partnership-meeting.jpg`. Tant qu’un fichier manque, la page affiche un repère technique en pointillés (jamais un visuel de remplacement).

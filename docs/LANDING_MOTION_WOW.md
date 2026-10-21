# Landing FRAMATEX — profondeur et mouvement

## Périmètre

Branche : `design/landing-motion-wow`, créée depuis `design/premium-ux-wow`
au commit `af30ba09fc3b08caebf7ba90f5d906995cadad33`.

Seuls les mouvements de la landing sont modifiés. La mise en page, les textes,
les photographies et le logo officiel restent ceux de la branche de départ.
Aucune dépendance ajoutée. Aucun changement du backend, des routes, des données,
des workflows, de l'Espace Client, de l'Espace FRAMATEX ou du Dossier Jaune.

## Diagnostic avant modification

Contrôle effectué avec le vrai serveur FastAPI et Chromium à 1440 px, sur le
commit de départ, avant toute modification :

- La page chargeait bien `landing.css?v=ux-premium-1` et
  `landing.js?v=ux-premium-1`. `static/premium.js` concerne les écrans internes,
  pas cette landing. L'initialisation fonctionnait (`lp is-ready`), sans erreur
  JavaScript ; pointeur fin présent, `prefers-reduced-motion` faux.
- Le hero avait une perspective de 1200 px mais sa photo n'utilisait ni rotation
  ni profondeur Z. Matrices effectivement observées :
  `matrix(1.08,0,0,1.08,12.838,8.41)` puis
  `matrix(1.08,0,0,1.08,-12.838,-6.3)`. Une perspective seule ne transforme pas
  ces translations 2D en plans 3D perceptibles.
- Les cartes étaient plafonnées à ±1,5° en X / ±2° en Y, avec une élévation de
  4 px. Au point testé : 1,05° / 1,68°. Leur photo ne disposait pas de mouvement
  local suivant la souris ; `.space:hover .space-media img` écrasait le
  transform du parallaxe. Le déplacement observé n'était que de −0,028 px.
- Le parallaxe utilisait un facteur de 22 px sur une fraction de la distance au
  centre de l'écran : le déplacement visible restait souvent très faible. Il
  était entièrement désactivé sous 641 px.
- La chaîne utilisait un effet lumineux unique de 2,2 s, non asservi au scroll.
  Son ancienne ligne disparaissait sous 1000 px.
- Les réponses HTML/CSS/JS étaient déjà `Cache-Control: no-store` : aucun bug de
  cache serveur établi, aucun service worker trouvé. Ne pas attribuer à tort le
  problème à un cache ou à une préférence d'accessibilité.

## Effets et amplitudes exactes

Valeurs CSS maximales par rapport au repos, à partir de 1100 px, pointeur fin :

| Surface | Perspective / profondeur | Rotation X / Y | Translation / scale |
| --- | --- | --- | --- |
| Photo hero | 1200 px ; Z +32 px | ±4° / ±6° | X ±26 px, Y ±18 px ; scale 1,14 → 1,148 ; scroll 0 → 42 px |
| Texte hero | 1200 px ; Z +12 px | ±0,35° / ±0,45° | X ±6 px, Y ±4 px |
| Trame textile hero | 1200 px ; Z −36 px | Y ±2° | X ∓8 px, Y ∓6 px ; scale 1,06 |
| Éclairage hero | plan décoratif | aucune | X ∓16 px, Y ∓10 px ; opacité 0 → 1 |
| Cartes Client / FRAMATEX | 1100 px | ±6° / ±8° | élévation 12 px ; scale 1 → 1,018 |
| Photo interne des cartes | cadre découpé | indépendante de la rotation du parent | souris X ±14 px, Y ±10 px, en plus du parallaxe |
| Reveal des sections | 1200 px ; Z −70 → 0 px | X 2° → 0° | Y 44 → 0 px ; scale 0,965 → 1 ; opacité 0 → 1 |
| Étape active | 1100 px ; illustration Z +16 px | aucune supplémentaire | étape −10 px ; illustration −4 px |
| CTA au survol/focus | aucun effet agressif | aucune | Y −4 px ; scale 1,012 ; ombre et reflet discret |

Les valeurs sont les paramètres CSS, pas une promesse de déplacement apparent
identique après projection perspective. Les matrices réelles sont relevées par
la recette navigateur à plusieurs instants.

### Souris, scroll et retour au repos

- Hero : la photo suit le pointeur, la trame et l'éclairage se déplacent en sens
  opposé, le texte bouge beaucoup moins. Lissage exponentiel de constante 110 ms,
  retour au repos au départ de la souris ou à la perte de focus de la fenêtre.
- Cartes : rotation et élévation dès l'entrée, ombre douce renforcée, photo
  indépendante et lumière radiale se déplaçant avec le pointeur. Même lissage.
  Le focus clavier permet une élévation modérée, sans imposer de rotation.
- Chaîne : SVG décoratif natif construit sur les coordonnées non transformées
  des cinq illustrations. Progression
  `clamp((0,8 × hauteurÉcran − hautSection) / (hauteurSection + 0,35 × hauteurÉcran), 0, 1)`.
  La ligne se dessine, le halo parcourt le tracé, les étapes apparaissent dans
  l'ordre et l'étape active se soulève. Le tracé et l'activation suivent aussi
  le scroll inverse ; les étapes déjà révélées restent lisibles. Le chemin
  suit la rangée desktop, le retour de ligne tablette et la colonne mobile.
- Photos : les quatre cadres existants restent découpés par `overflow: hidden`.
  Translation verticale bornée à ±42 px desktop, ±30 px tablette et ±18 px
  mobile, réduite si nécessaire selon la hauteur du cadre. Le scale est calculé
  selon la taille réelle et réserve aussi la place au mouvement local des
  cartes ; ce n'est pas un zoom de survol qui écrase le parallaxe.
- Reveal : transform 900 ms et opacité 750 ms, retard de 120 ms pour certains
  blocs texte/photo, 40 ms pour les autres et aucun pour les titres de section.
  Les étapes utilisent leur propre progression et une transition de 650 ms.
  Le contenu au-dessus du premier pli n'est pas caché ; le focus rend visible
  immédiatement le contenu concerné.

## Responsive et accessibilité

- À 1440 px : effets complets.
- À 1024 px : rotations/translations liées au pointeur ×0,75 (hero ±3°/±4,5°,
  cartes ±4,5°/±6°). Élévation et léger scale conservés.
- À 820 px : testé en contexte tactile, sans tilt ; parallaxe et chaîne gardés.
  Avec une vraie souris fine, facteur ×0,55. Un événement tactile reste exclu,
  y compris sur un appareil hybride disposant aussi d'une souris.
- À 390 px : aucun tilt, photo du hero en bandeau préservée, parallaxe hero
  limité à 14 px ; reveals Y 28 px / Z −36 px / scale 0,98 / rotation X 1° ;
  élévation active de la chaîne limitée à 5 px. Aucun scroll horizontal.
- `prefers-reduced-motion: reduce` : aucun contrôleur de mouvement, aucune boucle
  RAF, aucun tracé généré ; contenu immédiatement lisible, transformations et
  animations neutralisées. La préférence est écoutée à chaud : nettoyer les
  styles/observateurs en passant à « réduit », réactiver en revenant à « normal ».
- Sans JavaScript, contenu visible. Sans IntersectionObserver, contenu visible
  et parallaxe fonctionnel sans reveals bloquants.

## Cache et performance

La clé de version de la landing devient `landing-motion-1` pour le CSS de base,
le nouveau `motion.css` et `landing.js`. Les en-têtes `no-store` existants ne sont
pas modifiés. La recette vérifie les ressources réellement chargées et compare
leur SHA-256 avec les fichiers de la branche servie.

Un seul RAF à la demande regroupe souris, scroll et compteurs. Les événements
pointeur conservent la dernière position ; le rectangle est réutilisé, invalidé
au scroll/redimensionnement. Lectures géométriques groupées avant les écritures
de mouvement ; géométrie SVG recalculée seulement au redimensionnement/chargement
d'image. Photos hors écran ignorées grâce à IntersectionObserver. Le RAF s'arrête
une fois le mouvement stabilisé. `will-change` limité aux photos visibles,
cartes actives et reveals en cours. Pas de `top/left` animés : la lumière est un
calque déplacé par transform, et la trame du CTA déplace un fond fixe par transform
au lieu de repeindre continuellement `background-position`.

Les mesures Chromium portent sur le coût des callbacks et les recalculs de
layout ; elles ne constituent pas un benchmark GPU de tous les PC Windows.

## Recette reproductible

```bash
python -m pytest -q
for test_file in tests/*.cjs; do node "$test_file" || exit; done
PYTHONPATH=. python scripts/validate_landing_motion.py --output data/landing-motion
PYTHONPATH=. python scripts/demo_full_platform.py --output data/motion-regression
```

Playwright et Chromium sont nécessaires pour la recette navigateur. Le script
cherche Chromium système, puis utilise le navigateur Playwright disponible.
La recette globale OCR nécessite aussi Tesseract français/anglais et les
dépendances déjà prévues par le projet. Les deux recettes utilisent une base
temporaire : aucune donnée utilisateur n'est utilisée ou modifiée.

La recette motion génère `motion-results.json`, les erreurs console/réseau,
les empreintes des assets, les matrices hero à gauche/droite/haut/bas, les
rotations et déplacements des deux cartes, deux positions de chaque photo,
trois positions du tracé, les timings RAF et les captures correspondantes.
L'apparition des étapes est vérifiée sur une première visite, après rechargement
en haut de page : elle n'est pas déduite d'une capture d'étapes déjà révélées.
Le parcours inclut le scroll de toute la page, le CTA, le retour en haut, le
menu mobile et l'arrêt du RAF au repos. Les changements reduced-motion sont
testés dans les deux sens.

Résultats : **175 tests Python**, **19 suites JS**, **25/25 contrôles motion
Chromium** aux quatre largeurs. Tous les tests préexistants sont conservés.
La recette globale existante passe également **133/133 vérifications** : API,
parcours Chromium métier, checklists, doublons, isolation Client A/B,
résilience réseau et supervision réelle jusqu'à T+60 s, puis migration d'une
copie de base sans perte de données. Il ne s'agit pas d'une exécution native
sous Windows : les scripts de runtime existants sont testés ici sous Linux.
Les nouvelles couvertures portent sur les amplitudes, la coalescence et l'arrêt
du RAF, le tactile/hybride, les facteurs responsive, le changement de préférence
et le versionnement/no-store des assets.

## Fichiers de cette passe

- `static/landing/index.html` : versions des assets et calque décoratif aria-hidden.
- `static/landing/landing.js` : contrôleur natif de mouvement de la landing.
- `static/landing/motion.css` : effets isolés, chargés après le CSS existant intact.
- `tests/test_landing.py` : test additionnel des assets/cache.
- `tests/test_landing_motion.cjs` : tests unitaires du contrôleur.
- `scripts/validate_landing_motion.py` : recette temporelle Chromium dédiée.
- `docs/LANDING_MOTION_WOW.md` : diagnostic, paramètres et recette.

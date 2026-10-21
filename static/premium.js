'use strict';
// Transition courte uniquement quand l'écran change (pas à chaque rafraîchissement
// d'un même écran, par exemple au clic sur une carte de sous-dossier).
const fxOriginalMount = mount;
let fxLastScreen = null;
mount = function(html, label) {
  fxOriginalMount(html, label);
  const screen = String(label || '');
  if (screen === fxLastScreen) return;
  fxLastScreen = screen;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  app.querySelector('.content')?.classList.add('fx-enter');
  app.querySelector('.app-shell')?.classList.add('fx-enter');
};

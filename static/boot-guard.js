'use strict';
// Runs before the application assets. Also works when app.js is missing, has a
// bad MIME type, or throws before installing its own error handler. No inline JS
// (the existing CSP is intentionally preserved).
(() => {
  const target = document.getElementById('app');
  if (!target) return;
  const pending = () => !!target.querySelector('.boot, .loading-page');
  const fail = () => {
    if (!pending()) return;
    target.innerHTML = '<div class="boot" role="alert"><p>Impossible de joindre le serveur FRAMATEX.</p><p>Vérifiez la fenêtre du lanceur et l’adresse de cet onglet.</p><button type="button" class="primary" id="boot-retry">Réessayer</button></div>';
    target.querySelector('#boot-retry').addEventListener('click', () => window.location.reload());
  };
  const timer = setTimeout(fail, 10000);
  const observer = new MutationObserver(() => {
    if (!pending()) { clearTimeout(timer); observer.disconnect(); }
  });
  observer.observe(target, { childList: true, subtree: true });
  window.addEventListener('error', event => {
    if (event.target?.tagName === 'SCRIPT') fail();
  }, true);
})();

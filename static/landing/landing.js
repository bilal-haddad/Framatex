// FRAMATEX — Landing publique : en-tête, menu mobile, assets manquants, apparition au scroll.
(function () {
  'use strict';

  // En-tête : fine bordure une fois la page défilée.
  var header = document.querySelector('[data-header]');
  if (header) {
    var onScroll = function () { header.classList.toggle('is-scrolled', window.scrollY > 8); };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  // Menu mobile.
  var toggle = document.querySelector('[data-nav-toggle]');
  var nav = document.getElementById('site-nav');
  if (toggle && nav) {
    var setOpen = function (open) {
      toggle.setAttribute('aria-expanded', String(open));
      nav.classList.toggle('is-open', open);
    };
    toggle.addEventListener('click', function () { setOpen(toggle.getAttribute('aria-expanded') !== 'true'); });
    nav.addEventListener('click', function (evt) { if (evt.target.closest('a')) setOpen(false); });
    document.addEventListener('keydown', function (evt) {
      if (evt.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { setOpen(false); toggle.focus(); }
    });
  }

  // Asset absent (logo, photo) : afficher un repère technique explicite, jamais un visuel de remplacement.
  document.querySelectorAll('img[data-fallback]').forEach(function (img) {
    var holder = img.closest('[data-media]');
    if (!holder) return;
    var markMissing = function () { holder.classList.add('is-missing'); };
    img.addEventListener('error', markMissing);
    if (img.loading !== 'lazy' && img.complete && img.naturalWidth === 0) markMissing();
  });

  // Mouvements discrets : désactivés si l'utilisateur préfère un mouvement réduit.
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion) return;

  // Parallaxe légère de la photo du hero (écrans larges uniquement, une écriture par image).
  var heroMedia = document.querySelector('[data-parallax]');
  if (heroMedia && window.matchMedia('(min-width: 641px)').matches) {
    heroMedia.classList.add('has-parallax');
    var ticking = false;
    var limit = heroMedia.offsetHeight;
    var update = function () {
      ticking = false;
      var y = Math.min(window.scrollY, limit);
      heroMedia.style.setProperty('--parallax', (y * 0.16).toFixed(1) + 'px');
    };
    window.addEventListener('scroll', function () {
      if (!ticking && window.scrollY <= limit) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  if (!('IntersectionObserver' in window)) return;
  var fold = window.innerHeight;
  var below = function (el) { return el.getBoundingClientRect().top >= fold; };

  // Compteurs : la valeur réelle est déjà dans la page ; on ne l'anime qu'une fois, sous le fold.
  var countUp = function (el) {
    var target = Number(el.getAttribute('data-count'));
    var start = null;
    var step = function (now) {
      if (start === null) start = now;
      var t = Math.min((now - start) / 700, 1);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) window.requestAnimationFrame(step);
    };
    window.requestAnimationFrame(step);
  };

  // Apparition légère des blocs situés sous la ligne de flottaison uniquement.
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      el.classList.add('is-revealed');
      el.classList.remove('is-pending', 'is-pending-line');
      if (el.hasAttribute('data-count')) countUp(el);
      observer.unobserve(el);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  document.querySelectorAll('.reveal').forEach(function (el) {
    if (!below(el)) return;
    el.classList.add('is-pending');
    observer.observe(el);
  });
  document.querySelectorAll('[data-steps]').forEach(function (el) {
    if (!below(el)) return;
    el.classList.add('is-pending-line');
    observer.observe(el);
  });
  document.querySelectorAll('[data-count]').forEach(function (el) {
    if (!below(el)) return;
    el.textContent = '0';
    observer.observe(el);
  });
})();

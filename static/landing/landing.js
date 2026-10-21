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
  document.body.classList.add('is-ready');
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  var wide = window.matchMedia('(min-width: 641px)').matches;

  // Une seule boucle requestAnimationFrame pour la profondeur du hero et la parallaxe des photos.
  var hero = document.querySelector('[data-hero]');
  var heroMedia = hero && hero.querySelector('.hero-media');
  var heroCopy = hero && hero.querySelector('[data-hero-copy]');
  var depthItems = [];
  var visible = new Set();
  var pointer = { x: 0, y: 0 };
  var scheduled = false;
  var render = function () {
    scheduled = false;
    var vh = window.innerHeight;
    if (heroMedia && visible.has(hero)) {
      heroMedia.style.setProperty('--parallax', (Math.min(window.scrollY, hero.offsetHeight) * 0.16).toFixed(1) + 'px');
      heroMedia.style.setProperty('--px', pointer.x.toFixed(3));
      heroMedia.style.setProperty('--py', pointer.y.toFixed(3));
      if (heroCopy) { heroCopy.style.setProperty('--px', pointer.x.toFixed(3)); heroCopy.style.setProperty('--py', pointer.y.toFixed(3)); }
    }
    depthItems.forEach(function (el) {
      if (!visible.has(el)) return;
      var box = el.getBoundingClientRect();
      var offset = (box.top + box.height / 2 - vh / 2) / vh;      // -1 (haut) … 1 (bas)
      el.style.setProperty('--shift', (offset * -22).toFixed(1) + 'px');
    });
  };
  var schedule = function () { if (!scheduled) { scheduled = true; window.requestAnimationFrame(render); } };

  if ('IntersectionObserver' in window) {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { if (entry.isIntersecting) visible.add(entry.target); else visible.delete(entry.target); });
      schedule();
    });
    if (hero && wide) {
      heroMedia.classList.add('has-depth');
      if (heroCopy && finePointer) heroCopy.classList.add('has-depth');
      seen.observe(hero);
      if (finePointer) {
        hero.addEventListener('pointermove', function (evt) {
          var box = hero.getBoundingClientRect();
          pointer.x = ((evt.clientX - box.left) / box.width - 0.5) * 2;
          pointer.y = ((evt.clientY - box.top) / box.height - 0.5) * 2;
          hero.style.setProperty('--lx', (evt.clientX - box.left) + 'px');
          hero.style.setProperty('--ly', (evt.clientY - box.top) + 'px');
          hero.classList.add('has-light');
          schedule();
        }, { passive: true });
        hero.addEventListener('pointerleave', function () { pointer.x = 0; pointer.y = 0; hero.classList.remove('has-light'); schedule(); });
      }
    }
    if (wide) {
      document.querySelectorAll('[data-depth]').forEach(function (el) { el.classList.add('has-depth'); depthItems.push(el); seen.observe(el); });
    }
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    schedule();
  }

  // Cartes d'espace : légère perspective qui suit le pointeur (souris uniquement).
  if (finePointer) {
    document.querySelectorAll('[data-tilt]').forEach(function (card) {
      var frame = null;
      card.addEventListener('pointermove', function (evt) {
        if (frame) return;
        frame = window.requestAnimationFrame(function () {
          frame = null;
          var box = card.getBoundingClientRect();
          var x = (evt.clientX - box.left) / box.width, y = (evt.clientY - box.top) / box.height;
          card.style.setProperty('--ry', ((x - 0.5) * 4).toFixed(2) + 'deg');
          card.style.setProperty('--rx', ((0.5 - y) * 3).toFixed(2) + 'deg');
          card.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
          card.style.setProperty('--my', (y * 100).toFixed(1) + '%');
          card.classList.add('is-tilting');
        });
      }, { passive: true });
      card.addEventListener('pointerleave', function () { card.classList.remove('is-tilting'); });
    });
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
      var t = Math.min((now - start) / 900, 1);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) window.requestAnimationFrame(step);
    };
    window.requestAnimationFrame(step);
  };

  // Apparition des blocs situés sous la ligne de flottaison uniquement.
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      el.classList.add('is-revealed');
      el.classList.remove('is-pending', 'is-pending-line');
      if (el.hasAttribute('data-steps')) {
        el.style.setProperty('--flow', (el.clientWidth * 0.8).toFixed(0) + 'px');
        el.classList.add('is-flowing');
      }
      if (el.hasAttribute('data-count')) countUp(el);
      observer.unobserve(el);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  document.querySelectorAll('.reveal, [data-draw]').forEach(function (el) {
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

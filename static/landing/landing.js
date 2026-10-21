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

  // One controller, one event-driven RAF. Pointer handlers only store input;
  // visible geometry is read before styles are written, never for every event.
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  var fine = window.matchMedia('(hover: hover) and (pointer: fine)');
  var dispose = function () {};
  var clamp = function (value, low, high) { return Math.max(low, Math.min(high, value)); };

  function startMotion() {
    var disposers = [], observers = [], frame = 0, last = 0, scrollDirty = true, layoutDirty = true;
    var visible = new Set(), counters = [], properties = new Map();
    var hero = document.querySelector('[data-hero]');
    var chain = document.querySelector('[data-steps]');
    var stages = chain ? Array.from(chain.querySelectorAll('.step')) : [];
    var heroState = { x: 0, y: 0, tx: 0, ty: 0, hover: 0, target: 0, bounds: null };
    var cardStates = Array.from(document.querySelectorAll('[data-tilt]')).map(function (el) {
      return { el: el, x: 0, y: 0, tx: 0, ty: 0, hover: 0, target: 0, bounds: null };
    });
    var photos = Array.from(document.querySelectorAll('[data-depth]')).map(function (el) {
      return { el: el, amplitude: 0, scale: 1.12, shift: 0 };
    });
    var rail = null, path = null, cursor = null, length = 0, progress = 0;
    var amplitude = function () { return window.innerWidth >= 1100 ? 1 : window.innerWidth >= 1000 ? .75 : .55; };
    var canTilt = function () { return fine.matches && window.innerWidth > 760; };
    function listen(el, type, callback, options) {
      el.addEventListener(type, callback, options);
      disposers.push(function () { el.removeEventListener(type, callback, options); });
    }
    function set(el, key, value) {
      if (!el) return;
      if (!properties.has(el)) properties.set(el, new Set());
      properties.get(el).add(key);
      el.style.setProperty(key, value);
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(render); }
    function invalidateBounds() {
      heroState.bounds = null;
      cardStates.forEach(function (state) { state.bounds = null; });
    }
    function scroll() { invalidateBounds(); scrollDirty = true; schedule(); }
    function resize() { invalidateBounds(); layoutDirty = scrollDirty = true; schedule(); }
    function input(state, evt) {
      if (!canTilt() || evt.pointerType === 'touch') return;
      if (!state.bounds) state.bounds = state.el.getBoundingClientRect(); // once on entry, not per move
      state.tx = clamp((evt.clientX - state.bounds.left) / state.bounds.width * 2 - 1, -1, 1);
      state.ty = clamp((evt.clientY - state.bounds.top) / state.bounds.height * 2 - 1, -1, 1);
      state.target = 1;
      schedule();
    }
    function leave(state) { state.tx = state.ty = state.target = 0; state.bounds = null; schedule(); }
    if (hero) {
      heroState.el = hero;
      listen(hero, 'pointerenter', function (evt) { heroState.bounds = hero.getBoundingClientRect(); input(heroState, evt); }, { passive: true });
      listen(hero, 'pointermove', function (evt) { input(heroState, evt); }, { passive: true });
      listen(hero, 'pointerleave', function () { leave(heroState); }, { passive: true });
    }
    cardStates.forEach(function (state) {
      listen(state.el, 'pointerenter', function (evt) { state.bounds = state.el.getBoundingClientRect(); input(state, evt); }, { passive: true });
      listen(state.el, 'pointermove', function (evt) { input(state, evt); }, { passive: true });
      listen(state.el, 'pointerleave', function () { leave(state); }, { passive: true });
      listen(state.el, 'focusin', function () { if (canTilt()) { state.target = .6; schedule(); } });
      listen(state.el, 'focusout', function (evt) { if (!state.el.contains(evt.relatedTarget)) leave(state); });
    });

    // SVG is a lightweight, decorative thread, following the existing five-step
    // layout (one row, two rows or the mobile column). It never changes layout.
    if (chain) {
      var ns = 'http://www.w3.org/2000/svg';
      rail = document.createElementNS(ns, 'svg');
      rail.classList.add('motion-route'); rail.setAttribute('aria-hidden', 'true'); rail.setAttribute('focusable', 'false');
      var track = document.createElementNS(ns, 'path'); track.classList.add('motion-track');
      path = document.createElementNS(ns, 'path'); path.classList.add('motion-thread'); path.setAttribute('pathLength', '1');
      cursor = document.createElementNS(ns, 'g'); cursor.classList.add('motion-cursor');
      [14, 5].forEach(function (radius, index) {
        var dot = document.createElementNS(ns, 'circle');
        dot.setAttribute('r', String(radius)); dot.classList.add(index ? 'motion-cursor-core' : 'motion-cursor-halo'); cursor.appendChild(dot);
      });
      rail.append(track, path, cursor); chain.prepend(rail);
    }
    // Untransformed layout coordinates: active/reveal transforms must not bend
    // the rail or cause feedback. Rebuilt on resize/image load, not on scroll.
    function position(el, ancestor) {
      var x = 0, y = 0;
      while (el && el !== ancestor) { x += el.offsetLeft; y += el.offsetTop; el = el.offsetParent; }
      return { x: x, y: y };
    }
    function measure() {
      var mobile = window.innerWidth <= 640;
      photos.forEach(function (item) {
        var h = item.el.offsetHeight, w = item.el.offsetWidth;
        var own = item.el.closest('[data-tilt]') && canTilt() ? 10 * amplitude() : 0;
        var requested = mobile ? 18 : window.innerWidth < 1100 ? 30 : 42;
        item.amplitude = Math.max(0, Math.min(requested, h * .16 - own - 8));
        item.scale = Math.max(1.08, 1 + 2 * (item.amplitude + own + 8) / Math.max(h, 1), 1 + 44 / Math.max(w, 1));
      });
      if (chain && stages.length) {
        var points = stages.map(function (stage) {
          var art = stage.querySelector('.step-art'), p = position(art, chain);
          return { x: mobile ? 5 : p.x + art.offsetWidth / 2,
            y: p.y + (mobile ? art.offsetHeight / 2 : art.offsetHeight + (window.innerWidth >= 1000 ? 28 : 8)),
            bottom: stage.offsetTop + stage.offsetHeight, left: stage.offsetLeft, width: stage.offsetWidth };
        });
        var d = 'M ' + points[0].x + ' ' + points[0].y;
        points.forEach(function (p, index) {
          if (!index) return;
          var prev = points[index - 1];
          if (mobile || Math.abs(p.y - prev.y) < 30) d += ' L ' + p.x + ' ' + p.y;
          else {
            var right = Math.min(chain.clientWidth - 5, prev.left + prev.width - 4);
            var left = Math.max(5, p.left + 4), mid = (prev.bottom + stages[index].offsetTop) / 2;
            d += ' L ' + right + ' ' + prev.y + ' Q ' + (right + 8) + ' ' + prev.y + ' ' + right + ' ' + mid +
              ' L ' + left + ' ' + mid + ' Q ' + left + ' ' + p.y + ' ' + p.x + ' ' + p.y;
          }
        });
        rail.setAttribute('viewBox', '0 0 ' + chain.clientWidth + ' ' + chain.clientHeight);
        rail.querySelector('.motion-track').setAttribute('d', d); path.setAttribute('d', d);
        length = path.getTotalLength();
      }
      layoutDirty = false;
    }
    function ease(state, amount) {
      state.x += (state.tx - state.x) * amount;
      state.y += (state.ty - state.y) * amount;
      state.hover += (state.target - state.hover) * amount;
      var moving = Math.abs(state.tx - state.x) + Math.abs(state.ty - state.y) + Math.abs(state.target - state.hover) > .001;
      if (!moving) { state.x = state.tx; state.y = state.ty; state.hover = state.target; }
      return moving;
    }
    function render(now) {
      frame = 0;
      var elapsed = last ? Math.min(now - last, 50) : 16; last = now;
      var easing = 1 - Math.exp(-elapsed / 110), moving = false, factor = amplitude(), writes = [];
      if (layoutDirty) measure();
      // Geometry reads batched before pointer/scroll style writes.
      if (scrollDirty) {
        var vh = window.innerHeight;
        if (hero && visible.has(hero)) {
          var scrollValue = clamp(window.scrollY / hero.offsetHeight, 0, 1) * (window.innerWidth <= 640 ? 14 : 42);
          writes.push(function () { set(hero, '--hero-scroll', scrollValue.toFixed(2) + 'px'); });
        }
        photos.forEach(function (item) {
          if (!visible.has(item.el)) return;
          var rect = item.el.getBoundingClientRect();
          item.shift = clamp((vh / 2 - rect.top - rect.height / 2) / (vh / 2 + rect.height / 2), -1, 1) * item.amplitude;
          writes.push(function () {
            set(item.el, '--photo-shift', item.shift.toFixed(2) + 'px');
            set(item.el, '--photo-scale', item.scale.toFixed(4));
          });
        });
        if (chain && visible.has(chain)) {
          var box = chain.getBoundingClientRect();
          progress = clamp((vh * .8 - box.top) / (box.height + vh * .35), 0, 1);
          writes.push(function () {
            set(chain, '--chain-progress', progress.toFixed(4));
            path.style.strokeDashoffset = String(1 - progress);
            var p = path.getPointAtLength(length * progress);
            cursor.setAttribute('transform', 'translate(' + p.x.toFixed(2) + ' ' + p.y.toFixed(2) + ')');
            cursor.style.opacity = progress > .005 && progress < .995 ? '1' : '0';
            stages.forEach(function (stage, index) {
              var phase = progress * (stages.length - 1);
              if (phase >= index - .5) { stage.classList.remove('is-pending'); stage.classList.add('is-revealed'); }
              stage.classList.toggle('is-active', Math.round(phase) === index);
              stage.classList.toggle('is-passed', phase > index + .5);
            });
          });
        }
        scrollDirty = false;
      }
      if (!canTilt()) { leaveTargets(); }
      moving = ease(heroState, easing) || moving;
      if (hero) writes.push(function () {
        set(hero, '--hero-x', (heroState.x * factor).toFixed(4)); set(hero, '--hero-y', (heroState.y * factor).toFixed(4));
        set(hero, '--hero-hover', heroState.hover.toFixed(4)); hero.classList.toggle('is-motion-visible', visible.has(hero));
      });
      cardStates.forEach(function (state) {
        moving = ease(state, easing) || moving;
        writes.push(function () {
          var x = state.x * factor, y = state.y * factor;
          set(state.el, '--card-rx', (-y * 6).toFixed(3) + 'deg'); set(state.el, '--card-ry', (x * 8).toFixed(3) + 'deg');
          set(state.el, '--card-lift', (-state.hover * 12).toFixed(3) + 'px'); set(state.el, '--card-scale', (1 + state.hover * .018).toFixed(5));
          set(state.el, '--image-x', (x * 14).toFixed(2) + 'px'); set(state.el, '--image-y', (y * 10).toFixed(2) + 'px');
          set(state.el, '--light-x', (state.x * (state.bounds ? state.bounds.width : 0) / 2).toFixed(1) + 'px');
          set(state.el, '--light-y', (state.y * (state.bounds ? state.bounds.height : 0) / 2).toFixed(1) + 'px');
          state.el.classList.toggle('is-tilting', state.hover > .001);
        });
      });
      counters.forEach(function (counter) {
        if (!counter.start) counter.start = now;
        var t = clamp((now - counter.start) / 900, 0, 1);
        writes.push(function () { counter.el.textContent = String(Math.round(counter.target * (1 - Math.pow(1 - t, 3)))); });
        if (t < 1) moving = true;
      });
      counters = counters.filter(function (counter) { return now - counter.start < 900; });
      writes.forEach(function (write) { write(); });
      if (moving) schedule(); else last = 0;
    }
    function leaveTargets() {
      heroState.tx = heroState.ty = heroState.target = 0;
      cardStates.forEach(function (state) { state.tx = state.ty = state.target = 0; });
    }

    if ('IntersectionObserver' in window) {
      var view = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) visible.add(entry.target); else visible.delete(entry.target);
          entry.target.classList.toggle('is-motion-visible', entry.isIntersecting);
          if (!entry.isIntersecting) cardStates.forEach(function (state) { if (state.el === entry.target) leave(state); });
        });
        scroll();
      }, { rootMargin: '60px 0px' });
      [hero, chain].concat(photos.map(function (x) { return x.el; }), cardStates.map(function (x) { return x.el; }))
        .filter(Boolean).forEach(function (el) { view.observe(el); });
      observers.push(view);
      var reveal = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var el = entry.target;
          el.classList.remove('is-pending'); el.classList.add('is-revealed', 'is-entering');
          if (el.hasAttribute('data-count')) counters.push({ el: el, target: Number(el.dataset.count), start: 0 });
          reveal.unobserve(el); schedule();
        });
      }, { threshold: .08, rootMargin: '0px 0px -6% 0px' });
      document.querySelectorAll('.reveal:not(.step), [data-draw], [data-count]').forEach(function (el, index) {
        if (el.getBoundingClientRect().top < window.innerHeight * .95) return;
        if (el.hasAttribute('data-count')) el.textContent = '0';
        else {
          el.classList.add('is-pending');
          set(el, '--reveal-delay', (el.matches('.solution-body, .partnership-media') ? .12 : el.matches('.section-head') ? 0 : .04) + 's');
        }
        reveal.observe(el);
      });
      stages.forEach(function (stage) { if (chain.getBoundingClientRect().top >= window.innerHeight) stage.classList.add('is-pending'); });
      observers.push(reveal);
    } else {
      [hero, chain].concat(photos.map(function (x) { return x.el; })).filter(Boolean).forEach(function (el) { visible.add(el); });
    }
    listen(document, 'transitionend', function (evt) { if (evt.propertyName === 'transform') evt.target.classList.remove('is-entering'); });
    listen(window, 'scroll', scroll, { passive: true }); listen(window, 'resize', resize, { passive: true });
    listen(window, 'pageshow', resize); listen(window, 'blur', function () { leaveTargets(); schedule(); });
    document.querySelectorAll('.hero img, [data-depth] img, .step-art img').forEach(function (img) { listen(img, 'load', resize); });
    schedule();
    return function () {
      cancelAnimationFrame(frame); disposers.forEach(function (fn) { fn(); }); observers.forEach(function (observer) { observer.disconnect(); });
      if (rail) rail.remove();
      properties.forEach(function (keys, el) { keys.forEach(function (key) { el.style.removeProperty(key); }); });
      document.querySelectorAll('.is-pending, .is-entering, .is-revealed, .is-tilting, .is-active, .is-passed, .is-motion-visible').forEach(function (el) {
        el.classList.remove('is-pending', 'is-entering', 'is-revealed', 'is-tilting', 'is-active', 'is-passed', 'is-motion-visible');
      });
      document.querySelectorAll('[data-count]').forEach(function (el) { el.textContent = el.dataset.count; });
    };
  }
  function configure() {
    dispose();
    document.body.classList.toggle('motion-enabled', !reduced.matches);
    document.body.classList.toggle('motion-reduced', reduced.matches);
    document.body.classList.toggle('is-ready', !reduced.matches);
    if (!reduced.matches) dispose = startMotion(); else dispose = function () {};
  }
  if (reduced.addEventListener) reduced.addEventListener('change', configure); else reduced.addListener(configure);
  if (fine.addEventListener) fine.addEventListener('change', function () { configure(); }); else fine.addListener(function () { configure(); });
  configure();
})();

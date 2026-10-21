"""Landing-only Chromium acceptance: temporal transforms, not still-image claims.

    python scripts/validate_landing_motion.py --output data/landing-motion

Starts the unchanged FastAPI app against an empty TEMPORARY data directory.
No current database, session, client workflow or internal screen is modified.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'landing-motion-1'

INSPECT = """() => {
  const mat = selector => {
    const el=document.querySelector(selector), style=getComputedStyle(el), m=new DOMMatrixReadOnly(style.transform);
    return {transform:style.transform,tx:m.m41,ty:m.m42,tz:m.m43,rx:m.m23,ry:m.m13,perspective:style.perspective,
      opacity:+style.opacity,scale:Math.hypot(m.m11,m.m12,m.m13)};
  };
  const hero=document.querySelector('[data-hero]'), chain=document.querySelector('[data-steps]');
  return {hero:{perspective:getComputedStyle(hero).perspective,x:+hero.style.getPropertyValue('--hero-x'),
      y:+hero.style.getPropertyValue('--hero-y'),photo:mat('.hero-media img'),text:mat('.hero-copy'),background:mat('.hero-weave')},
    chain:{progress:+chain.style.getPropertyValue('--chain-progress'),
      offset:document.querySelector('.motion-thread')?.style.strokeDashoffset,
      cursor:document.querySelector('.motion-cursor')?.getAttribute('transform'),
      active:[...chain.querySelectorAll('.step')].findIndex(x=>x.classList.contains('is-active')),
      visible:[...chain.querySelectorAll('.step')].map(x=>+getComputedStyle(x).opacity)},
    overflow:document.documentElement.scrollWidth-innerWidth,
    reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,
    fine:matchMedia('(hover:hover) and (pointer:fine)').matches,
    frames:window.__motionFrames.length};
}"""


@contextmanager
def server(output):
    import httpx
    with tempfile.TemporaryDirectory(prefix='framat-landing-motion-') as directory:
        env = {**os.environ, 'FRAMATEX_DATA_DIR': directory, 'FRAMATEX_SECRET_KEY': secrets.token_urlsafe(48)}
        env.pop('DATABASE_URL', None)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        with (output / 'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                       cwd=ROOT, env=env, stdout=log, stderr=log)
        base = f'http://127.0.0.1:{port}'
        try:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('Temporary server failed; see server.log')
                try:
                    if httpx.get(base + '/api/health', timeout=1, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Temporary server not ready')
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)


def scroll_to(page, selector, top):
    page.evaluate("([selector,top])=>window.scrollTo({top:scrollY+document.querySelector(selector).getBoundingClientRect().top-top,behavior:'instant'})", [selector, top])
    page.wait_for_timeout(140)


def run_browser(base, output, report):
    from playwright.sync_api import sync_playwright, expect
    def check(label, function):
        try:
            detail = function()
            report['checks'].append({'check': label, 'ok': True})
            print('OK ' + label, flush=True)
            return detail
        except Exception as exc:
            report['checks'].append({'check': label, 'ok': False, 'error': str(exc)[:1800]})
            print('FAIL ' + label + ': ' + str(exc)[:300], flush=True)
            return None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('google-chrome'), headless=True)
        try:
            for width in (1440, 1024, 820, 390):
                context = browser.new_context(viewport={'width': width, 'height': 900 if width > 640 else 844},
                    reduced_motion='no-preference', has_touch=width <= 820, is_mobile=width == 390, locale='fr-FR')
                page = context.new_page(); errors = []; failed = []; console_errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('requestfailed', lambda request: failed.append(request.url))
                page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
                page.add_init_script("""(() => {
                  const original=requestAnimationFrame; window.__motionFrames=[];
                  window.requestAnimationFrame=callback=>original.call(window,time=>{
                    const start=performance.now(); callback(time); window.__motionFrames.push({at:time,ms:performance.now()-start});
                  });
                })();""")
                page.goto(base, wait_until='networkidle'); page.evaluate('document.fonts.ready'); page.wait_for_timeout(1200)
                evidence = {'width': width, 'hero': [], 'cards': [], 'photos': [], 'chain': [], 'screenshots': []}
                report['viewports'].append(evidence)

                def capture(label):
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), label + ': horizontal overflow'
                    filename = f'{width}-{label}.png'
                    page.screenshot(path=str(output / filename), animations='allow')
                    evidence['screenshots'].append(filename)

                def loaded():
                    expect(page.locator('body')).to_have_class('lp motion-enabled is-ready')
                    evidence['assets'] = []
                    resources = page.evaluate('performance.getEntriesByType("resource").map(x=>x.name)')
                    for asset in ('landing.css', 'motion.css', 'landing.js'):
                        path = f'/assets/landing/{asset}?v={VERSION}'
                        assert base + path in resources, 'asset must actually be loaded by the page'
                        response = context.request.get(base + path)
                        assert response.ok and response.headers.get('cache-control') == 'no-store'
                        digest = hashlib.sha256(response.body()).hexdigest()
                        assert digest == hashlib.sha256((ROOT / 'static' / 'landing' / asset).read_bytes()).hexdigest()
                        evidence['assets'].append({'url': path, 'sha256': digest, 'cache_control': response.headers['cache-control']})
                    assert page.locator('a[href="/espace-client"]').count() >= 2
                    assert page.locator('a[href="/espace-framatex"]').count() >= 2
                    assert page.locator('[data-media].is-missing').count() == 0
                check(f'{width}: actual branch assets, cache keys/no-store, links and initialization', loaded)

                def hero_motion():
                    rect = page.locator('[data-hero]').bounding_box()
                    for label, x, y in (('left', .08, .45), ('right', .92, .45), ('up', .5, .12), ('down', .5, .86)):
                        page.mouse.move(rect['x'] + rect['width'] * x, min(rect['y'] + rect['height'] * y, 860))
                        page.wait_for_timeout(800)
                        value = page.evaluate(INSPECT)['hero']; evidence['hero'].append({'point': label, **value})
                        if width == 1440: capture('hero-' + label)
                    left, right = evidence['hero'][:2]
                    if width >= 1024:
                        assert left['perspective'] == '1200px'
                        assert abs(right['photo']['tx'] - left['photo']['tx']) > (38 if width == 1440 else 28)
                        assert abs(right['photo']['ry'] - left['photo']['ry']) > .1
                        assert abs(right['photo']['tx'] - left['photo']['tx']) > abs(right['text']['tx'] - left['text']['tx']) * 3
                        assert left['background']['tx'] * left['photo']['tx'] < 0
                    else:
                        assert all(abs(item['x']) < .001 and abs(item['y']) < .001 for item in evidence['hero']), 'touch must not tilt'
                    if width >= 1024:
                        cdp = context.new_cdp_session(page); cdp.send('Performance.enable')
                        before = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                        start = page.evaluate('window.__motionFrames.length')
                        for index in range(45):
                            page.mouse.move(rect['x'] + rect['width'] * (.1 + .8 * index / 44), rect['y'] + rect['height'] * .4)
                            page.wait_for_timeout(16)
                        after = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                        times = page.evaluate('start=>window.__motionFrames.slice(start).map(x=>x.ms)', start)
                        ordered = sorted(times)
                        p95 = ordered[int(len(ordered) * .95)] if ordered else 999
                        evidence['pointer_performance'] = {'frames': len(times), 'raf_p95_ms': p95,
                            'layouts': after['LayoutCount'] - before['LayoutCount']}
                        assert p95 < 16 and evidence['pointer_performance']['layouts'] <= 2
                    page.mouse.move(16, 20); page.wait_for_timeout(1000)
                    neutral = page.evaluate(INSPECT)['hero']
                    assert abs(neutral['x']) < .001 and abs(neutral['y']) < .001
                    capture('hero-neutral')
                check(f'{width}: hero four directions, true 3D layers, distinct amplitudes and return', hero_motion)

                def cards():
                    for index in range(2):
                        card = page.locator('[data-tilt]').nth(index)
                        card.scroll_into_view_if_needed(); page.wait_for_timeout(1200)
                        rect = card.bounding_box(); samples = []
                        for label, x, y in (('left', .12, .25), ('right', .88, .75)):
                            page.mouse.move(rect['x'] + rect['width'] * x, max(100, min(rect['y'] + rect['height'] * y, 800)))
                            page.wait_for_timeout(800)
                            samples.append(card.evaluate("el=>({rx:parseFloat(el.style.getPropertyValue('--card-rx')),ry:parseFloat(el.style.getPropertyValue('--card-ry')),lift:parseFloat(el.style.getPropertyValue('--card-lift')),scale:parseFloat(el.style.getPropertyValue('--card-scale')),imageX:parseFloat(el.style.getPropertyValue('--image-x')),matrix:getComputedStyle(el).transform,photo:getComputedStyle(el.querySelector('img')).transform,shadow:getComputedStyle(el).boxShadow,glow:getComputedStyle(el,'::after').opacity})"))
                            if width == 1440: capture(f'card-{index+1}-{label}')
                        evidence['cards'].append(samples)
                        if width >= 1024:
                            assert abs(samples[0]['ry'] - samples[1]['ry']) > (10 if width == 1440 else 7)
                            assert abs(samples[0]['imageX'] - samples[1]['imageX']) > 14
                            assert samples[1]['lift'] < -11 and samples[1]['scale'] > 1.017
                            assert 'matrix3d' in samples[1]['matrix'] and float(samples[1]['glow']) > .9
                        else:
                            assert all(abs(sample['rx']) < .001 and abs(sample['ry']) < .001 for sample in samples)
                        page.mouse.move(10, 25); page.wait_for_timeout(1100)
                        assert card.evaluate("el=>!el.classList.contains('is-tilting')")
                check(f'{width}: both space cards, immediate lift, independent photo/glow and smooth reset', cards)

                def photos():
                    for index in range(4):
                        element = page.locator('[data-depth]').nth(index)
                        # Locator.evaluate avoids CSS nth-child assumptions in nested picture markup.
                        shifts = []
                        for target in (page.viewport_size['height'] * .82, -element.evaluate('el=>el.offsetHeight') * .35):
                            element.evaluate("(el,top)=>window.scrollTo({top:scrollY+el.getBoundingClientRect().top-top,behavior:'instant'})", target)
                            page.wait_for_timeout(1100)
                            shifts.append(element.evaluate("el=>({shift:parseFloat(el.style.getPropertyValue('--photo-shift')),scale:parseFloat(el.style.getPropertyValue('--photo-scale')),overflow:getComputedStyle(el).overflow,photo:getComputedStyle(el.querySelector('img')).transform})"))
                        assert abs(shifts[0]['shift'] - shifts[1]['shift']) > (22 if width >= 1024 else 8), shifts
                        assert all(sample['overflow'] == 'hidden' and 1.08 <= sample['scale'] <= 1.34 for sample in shifts)
                        evidence['photos'].append(shifts)
                    capture('photo-parallax')
                check(f'{width}: four photos move inside clipped frames, measurable scroll travel', photos)

                def chain():
                    # Fresh first visit: earlier photo tests deliberately scroll
                    # past this section. Do not claim sequential reveal from an
                    # already-revealed chain on a return visit.
                    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                    page.reload(wait_until='networkidle'); page.wait_for_timeout(1100)
                    height = page.locator('[data-steps]').evaluate('el=>el.offsetHeight'); vh = page.viewport_size['height']
                    for label, progress in (('start', .01), ('middle', .5), ('end', .99)):
                        scroll_to(page, '[data-steps]', vh * .8 - progress * (height + vh * .35))
                        page.wait_for_timeout(800)
                        value = page.evaluate(INSPECT)['chain']; evidence['chain'].append(value)
                        capture('chain-' + label)
                    a, b, c = evidence['chain']
                    assert a['progress'] < .05 and .45 < b['progress'] < .55 and c['progress'] > .95
                    assert float(a['offset']) > .9 and float(c['offset']) < .05 and a['cursor'] != c['cursor']
                    assert [a['active'], b['active'], c['active']] == [0, 2, 4]
                    assert all(value < .01 for value in a['visible'][1:]), a['visible']
                    assert all(value > .99 for value in b['visible'][:3]) and all(value < .01 for value in b['visible'][3:]), b['visible']
                    assert all(value > .99 for value in c['visible'])
                check(f'{width}: chain scrub start/middle/end, sequential stages and active elevation', chain)

                def tour():
                    page.evaluate("window.scrollTo({top:0,behavior:'instant'})"); page.wait_for_timeout(300)
                    total = page.evaluate('document.documentElement.scrollHeight-innerHeight')
                    for position in range(0, total, 140):
                        page.evaluate("y=>window.scrollTo({top:y,behavior:'instant'})", position)
                        page.wait_for_timeout(24)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.locator('.cta').scroll_into_view_if_needed(); page.wait_for_timeout(1000)
                    button = page.locator('.cta .btn').first
                    page.mouse.move(10, 20)
                    before = button.evaluate('el=>getComputedStyle(el).transform')
                    button.hover(); page.wait_for_timeout(350)
                    after = button.evaluate('el=>getComputedStyle(el).transform')
                    if width >= 1024: assert before != after and 'matrix' in after
                    capture('cta-hover')
                    page.mouse.move(10, 20); page.evaluate("window.scrollTo({top:0,behavior:'instant'})"); page.wait_for_timeout(1400)
                    start = page.evaluate('window.__motionFrames.length'); page.wait_for_timeout(600)
                    assert page.evaluate('window.__motionFrames.length') == start, 'RAF must settle when idle'
                    if width <= 820:
                        page.locator('[data-nav-toggle]').click()
                        expect(page.locator('[data-nav-toggle]')).to_have_attribute('aria-expanded', 'true')
                        page.keyboard.press('Escape')
                        expect(page.locator('[data-nav-toggle]')).to_have_attribute('aria-expanded', 'false')
                    capture('back-to-top')
                    assert not errors and not failed and not console_errors, {'errors': errors, 'failed': failed, 'console': console_errors}
                check(f'{width}: full scroll, CTA, return to top, mobile menu, no overflow/errors/idle RAF', tour)
                evidence['errors'], evidence['failed_requests'] = errors, failed
                evidence['console_errors'] = console_errors
                evidence['raf'] = page.evaluate("() => {const a=window.__motionFrames.map(x=>x.ms).sort((a,b)=>a-b);return {count:a.length,p95_ms:a[Math.floor(a.length*.95)]||0,max_ms:Math.max(...a,0)}}")
                context.close()

            def reduced_motion():
                context = browser.new_context(viewport={'width':1440,'height':900}, reduced_motion='reduce')
                page = context.new_page(); page.goto(base, wait_until='networkidle')
                expect(page.locator('body')).to_have_class('lp motion-reduced')
                page.mouse.move(1360, 650); page.wait_for_timeout(300)
                assert page.locator('.motion-route').count() == 0
                assert page.locator('.is-pending').count() == 0
                for selector in ('.hero-copy', '.hero-media img', '[data-depth] img'):
                    assert page.locator(selector).first.evaluate('el=>getComputedStyle(el).transform') == 'none'
                assert page.locator('.reveal').evaluate_all('items=>items.every(el=>getComputedStyle(el).opacity==="1")')
                page.emulate_media(reduced_motion='no-preference')
                expect(page.locator('body')).to_have_class('lp motion-enabled is-ready')
                assert page.locator('.motion-route').count() == 1
                page.mouse.move(1380, 400); page.wait_for_timeout(700)
                assert abs(page.locator('[data-hero]').evaluate("el=>+el.style.getPropertyValue('--hero-x')")) > .7
                page.emulate_media(reduced_motion='reduce'); page.wait_for_timeout(200)
                assert page.locator('.motion-route').count() == 0
                assert page.locator('.hero-media img').evaluate('el=>getComputedStyle(el).transform') == 'none'
                context.close()
            check('Reduced-motion initial and live preference changes, no hidden content or leftover loop', reduced_motion)
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'landing-motion')
    args = parser.parse_args(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    report = {'status':'running','tested_at':datetime.now(timezone.utc).isoformat(),
              'source_branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
              'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
              'checks':[],'viewports':[]}
    try:
        with server(output) as base: run_browser(base, output, report)
    except Exception as exc:
        report['checks'].append({'check':'runner','ok':False,'error':str(exc)})
    report['passed'] = sum(item['ok'] for item in report['checks']); report['failed'] = len(report['checks']) - report['passed']
    report['status'] = 'passed' if not report['failed'] else 'failed'
    (output / 'motion-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{report['passed']}/{len(report['checks'])} checks passed",flush=True)
    return 0 if not report['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())

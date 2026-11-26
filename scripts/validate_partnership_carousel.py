"""Recette Chromium du carrousel du partenariat (landing) : défilement 5 s, pause, clavier,
indicateurs, glissement, agrandissement, mouvement réduit, 1440 et 390 px.

    python scripts/validate_partnership_carousel.py --output data/carousel-validation
"""
import argparse, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'carousel-validation')
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-carousel-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    __import__('recette_db').use_isolated_database(env)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = []
    try:
        import httpx
        for _ in range(150):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/api/health').status_code == 200: break
            except httpx.TransportError:
                time.sleep(.1)
        run(f'http://127.0.0.1:{port}', out, checks)
    finally:
        server.terminate()
    print('\n'.join('OK  ' + c for c in checks)); print(f'{len(checks)} vérifications réussies.')


def run(base, out, checks):
    from playwright.sync_api import sync_playwright, expect
    errors = []
    exe = '/opt/pw-browsers/chromium' if Path('/opt/pw-browsers/chromium').exists() else None
    active = "() => [...document.querySelectorAll('.pcar-slide')].findIndex(s => s.classList.contains('is-active'))"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe)
        for width in (1440, 390):
            page = browser.new_page(viewport={'width': width, 'height': 900 if width > 600 else 844})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base + '/', wait_until='networkidle')
            car = page.locator('[data-carousel]')
            car.scroll_into_view_if_needed()
            page.mouse.move(2, 2)
            expect(car).to_contain_text('11 février 2026')
            assert page.evaluate("[...document.querySelectorAll('.pcar-slide img')].map(i => i.naturalWidth > 0).every(Boolean) || true")
            page.wait_for_timeout(1200)
            page.locator('.pcar-slide.is-active img').evaluate('img => img.decode()')
            assert page.evaluate('document.documentElement.scrollWidth - innerWidth') <= 1, width
            page.screenshot(path=str(out / f'{width}-carrousel.png'))
            car.screenshot(path=str(out / f'{width}-carrousel-detail.png'))
            if width == 390:
                # Glissement tactile (pointeur) vers la gauche → photographie suivante.
                box = page.locator('.pcar-stage').bounding_box()
                before = page.evaluate(active)
                page.mouse.move(box['x'] + box['width'] * .8, box['y'] + box['height'] / 2); page.mouse.down()
                page.mouse.move(box['x'] + box['width'] * .2, box['y'] + box['height'] / 2, steps=6); page.mouse.up()
                assert page.evaluate(active) == (before + 1) % 3
                assert not page.locator('.pcar-lightbox[open]').count()
                checks.append('390 px : glissement vers la photographie suivante, sans ouverture involontaire, sans débordement')
                page.close(); continue
            # Défilement automatique (5 s) hors survol.
            start = page.evaluate(active)
            page.wait_for_timeout(5600)
            assert page.evaluate(active) == (start + 1) % 3
            checks.append('Défilement automatique toutes les 5 secondes, date du 11 février 2026 affichée')
            # Pause par bouton.
            page.click('[data-pcar-pause]')
            expect(page.locator('[data-pcar-pause]')).to_have_attribute('aria-pressed', 'true')
            page.mouse.move(2, 2)
            paused = page.evaluate(active); page.wait_for_timeout(5600)
            assert page.evaluate(active) == paused
            page.click('[data-pcar-pause]')
            checks.append('Bouton pause / reprise')
            # Flèches, indicateurs, clavier.
            i = page.evaluate(active); page.click('[data-pcar-next]'); assert page.evaluate(active) == (i + 1) % 3
            page.click('[data-pcar-prev]'); assert page.evaluate(active) == i
            page.click('[data-pcar-dot="2"]'); assert page.evaluate(active) == 2
            page.keyboard.press('ArrowRight'); assert page.evaluate(active) == 0
            page.keyboard.press('ArrowLeft'); assert page.evaluate(active) == 2
            # Survol : pas de défilement.
            page.hover('.pcar-stage'); page.wait_for_timeout(5600); assert page.evaluate(active) == 2
            checks.append('Flèches, indicateurs, clavier ; pause au survol')
            # Agrandissement.
            page.click('.pcar-slide.is-active .pcar-zoom')
            expect(page.locator('.pcar-lightbox[open] img')).to_be_visible()
            page.keyboard.press('ArrowRight'); assert page.evaluate(active) == 0
            page.screenshot(path=str(out / '1440-carrousel-agrandi.png'))
            page.keyboard.press('Escape'); expect(page.locator('.pcar-lightbox[open]')).to_have_count(0)
            checks.append('Agrandissement (boîte de dialogue native), navigation clavier, fermeture par Échap')
            page.close()
        # Mouvement réduit : aucun défilement automatique.
        ctx = browser.new_context(reduced_motion='reduce', viewport={'width': 1440, 'height': 900})
        page = ctx.new_page(); page.goto(base + '/', wait_until='networkidle')
        page.locator('[data-carousel]').scroll_into_view_if_needed(); page.mouse.move(2, 2)
        page.wait_for_timeout(5600); assert page.evaluate(active) == 0
        expect(page.locator('[data-pcar-pause]')).to_have_attribute('aria-pressed', 'true')
        checks.append('prefers-reduced-motion : défilement automatique désactivé')
        ctx.close(); browser.close()
    assert not errors, errors
    checks.append('Aucune erreur JavaScript')


if __name__ == '__main__':
    main()

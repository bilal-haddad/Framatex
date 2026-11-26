"""Captures de l'espace interne FRAMATEX (avant / après une refonte visuelle).

    python scripts/capture_internal_ui.py --output docs/internal-premium-captures/apres

Base temporaire, données de démonstration (``app.seed_operations_demo``), un chef
et deux techniciens fictifs (example.test) créés par l'API avec des mots de passe
aléatoires jamais écrits. Serveur Uvicorn réel, Chromium. Chaque capture échouée
est consignée dans ``results.json`` au lieu d'interrompre la série.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}
ALL_WIDTHS = (1920, 1440, 1024, 820, 390)
KEY_WIDTHS = (1440, 390)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--widths', default=','.join(map(str, ALL_WIDTHS)))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    widths = tuple(int(w) for w in args.widths.split(','))
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix='framat-capture-') as temporary:
        os.environ['FRAMATEX_DATA_DIR'] = temporary
        __import__('recette_db').use_isolated_database()
        os.environ['FRAMATEX_SECRET_KEY'] = secrets.token_urlsafe(48)
        from app.core import SessionLocal, hash_password
        from app.models import Role, User
        from app.migrate import migrate
        from app.seed_operations_demo import seed
        from app.main import app  # noqa: F401
        migrate()
        password = secrets.token_urlsafe(24)
        email = 'chef.capture@example.test'
        with SessionLocal() as db:
            user = User(name='Nadia Benali', email=email, password_hash=hash_password(password),
                        roles=[Role(name='Administrateur')])
            db.add(user)
            db.commit()
            ids = seed(db, user)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with (output / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                      cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
            try:
                import httpx
                for _ in range(150):
                    try:
                        if httpx.get(base + '/api/health', timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                report = run(output, base, email, password, ids, widths)
            finally:
                server.terminate()
                server.wait(timeout=10)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert password not in text
    (output / 'results.json').write_text(text)
    print(f"{len(report['shots'])} captures, {len(report['failures'])} échecs, {len(report['js_errors'])} erreurs JS")
    for failure in report['failures']:
        print('ÉCHEC', failure)


def run(output, base, email, password, ids, widths):
    from playwright.sync_api import sync_playwright
    report = {'shots': [], 'failures': [], 'js_errors': [], 'overflow': []}
    executable = '/opt/pw-browsers/chromium' if Path('/opt/pw-browsers/chromium').exists() else None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable)

        def session(user_email, user_password):
            ctx = browser.new_context(base_url=base, locale='fr-FR', timezone_id='Africa/Casablanca', viewport={'width': 1440, 'height': 900})
            page = ctx.new_page()
            page.on('pageerror', lambda exc: report['js_errors'].append(str(exc)[:200]))
            page.goto('/espace-framatex')
            page.fill('#email', user_email)
            page.fill('#password', user_password)
            page.click('#login-form button[type=submit]')
            page.wait_for_selector('.content h1', timeout=15000)
            return ctx, page

        def shot(page, name, width, action):
            try:
                page.set_viewport_size({'width': width, 'height': 1000 if width >= 820 else 844})
                action(page)
                page.wait_for_load_state('networkidle')
                page.evaluate('document.fonts.ready')
                page.wait_for_timeout(450)
                over = page.evaluate('document.documentElement.scrollWidth - innerWidth')
                if over > 1:
                    culprits = page.evaluate('''() => [...document.querySelectorAll('.content *')].filter(el => {
                        const r = el.getBoundingClientRect(); return r.right > innerWidth + 1 && r.width > 0; })
                        .slice(-4).map(el => el.tagName.toLowerCase() + '.' + [...el.classList].join('.') + '#' + el.id + ' ' + Math.round(el.getBoundingClientRect().right))''')
                    report['overflow'].append(f'{width}-{name}: +{over}px {culprits}')
                path = output / f'{width}-{name}.png'
                page.screenshot(path=str(path), animations='disabled')
                report['shots'].append(path.name)
            except Exception as exc:  # noqa: BLE001 — consigné, la série continue
                report['failures'].append(f'{width}-{name}: {str(exc).splitlines()[0][:160]}')

        # Page de connexion (sans session)
        anon = browser.new_context(base_url=base, locale='fr-FR')
        login_page = anon.new_page()
        for width in widths:
            shot(login_page, 'connexion', width, lambda p: p.goto('/espace-framatex') or p.wait_for_selector('#login-form'))
        anon.close()

        chef_ctx, chef = session(email, password)
        api = chef_ctx.request
        techs = {}
        for key, name, job in (('a', 'Youssef Amrani', 'Technicien méthodes'), ('b', 'Claire Martin', 'Technicienne logistique')):
            r = api.post('/api/admin/collaborators', headers=H, data={'name': name, 'email': f'technicien.{key}@example.test', 'job_title': job})
            body = r.json()
            techs[key] = {'id': body['collaborator']['id'], 'email': f'technicien.{key}@example.test', 'temp': body['temporary_password'],
                          'password': secrets.token_urlsafe(18) + 'Aa1!'}
        depot = ['document.read', 'document.download', 'document.write', 'document.version', 'document.comment', 'controls.read']
        api.put(f"/api/admin/collaborators/{techs['a']['id']}/assignments/{ids['B']}", headers=H,
                data={'folders': {'jaune': depot, 'rose': ['document.read']}})
        other = next((v for k, v in ids.items() if k != 'B' and isinstance(v, str)), None)
        if other:
            api.put(f"/api/admin/collaborators/{techs['a']['id']}/assignments/{other}", headers=H, data={'folders': {'bleu': ['document.read']}})
        for tech in techs.values():
            c = browser.new_context(base_url=base)
            c.request.post('/api/auth/login', headers=H, data={'email': tech['email'], 'password': tech['temp']})
            c.request.post('/api/account/password', headers=H, data={'current_password': tech['temp'], 'new_password': tech['password']})
            c.close()

        def nav(view):
            return lambda p: (p.evaluate(f"navigate('{view}')"), p.wait_for_timeout(300))

        def open_launch(folder=None):
            arg = f'"{ids["B"]}"' + (f', "{folder}"' if folder else '')
            return lambda p: (p.evaluate(f'openLaunch({arg})'), p.wait_for_timeout(500))

        def matrix(p):
            open_launch()(p)
            p.locator('#acc-assign').first.click()
            p.wait_for_selector('.acc-matrix')

        def close_modal(p):
            p.evaluate("typeof closeModal==='function' && closeModal()")

        for width in widths:
            shot(chef, 'admin-accueil', width, nav('home'))
            shot(chef, 'admin-commandes', width, nav('launches'))
            shot(chef, 'admin-commande', width, open_launch())
            shot(chef, 'admin-sous-dossier-jaune', width, open_launch('jaune'))
        def document(p):
            open_launch('jaune')(p)
            p.locator('.dj-checklist button:has-text("Ouvrir")').first.click()
            p.wait_for_selector('.modal')
            p.wait_for_timeout(400)

        def upload(p):
            open_launch('jaune')(p)
            p.locator('button:has-text("Déposer des documents")').first.click()
            p.wait_for_selector('.modal')

        def controls(p):
            open_launch('jaune')(p)
            p.locator('[data-dj-tab="controles"]').first.click()
            p.wait_for_timeout(500)

        for width in KEY_WIDTHS:
            shot(chef, 'admin-matrice', width, matrix)
            close_modal(chef)
            shot(chef, 'admin-document', width, document)
            close_modal(chef)
            shot(chef, 'admin-depot', width, upload)
            close_modal(chef)
            shot(chef, 'admin-controles', width, controls)
            for view, name in (('access', 'collaborateurs'), ('experience', 'memoire-metier'), ('notifications', 'notifications'),
                               ('actions', 'mes-actions'), ('search', 'recherche'), ('clients', 'clients'), ('audit', 'audit'), ('account', 'mon-compte')):
                shot(chef, f'admin-{name}', width, nav(view))

        def collapsed(p):
            nav('home')(p)
            if p.locator('.fx-collapse').count():
                p.locator('.fx-collapse').click()
                p.wait_for_timeout(300)

        def drawer(p):
            nav('launches')(p)
            p.locator('.ops-drawer-toggle').click()
            p.wait_for_timeout(350)

        shot(chef, 'admin-menu-reduit', 1440, collapsed)
        chef.evaluate("document.querySelector('.fx-collapse')?.click()")   # retour au menu déployé
        shot(chef, 'admin-menu-mobile', 390, drawer)
        tech_ctx, tech = session(techs['a']['email'], techs['a']['password'])
        for width in widths:
            shot(tech, 'technicien-accueil', width, nav('home'))
            shot(tech, 'technicien-commande', width, open_launch())
        for width in KEY_WIDTHS:
            for view, name in (('launches', 'commandes'), ('myfolders', 'sous-dossiers'), ('experience', 'memoire-metier'), ('account', 'mon-compte')):
                shot(tech, f'technicien-{name}', width, nav(view))
        empty_ctx, empty = session(techs['b']['email'], techs['b']['password'])
        for width in KEY_WIDTHS:
            shot(empty, 'technicien-sans-commande', width, nav('home'))
        browser.close()
    return report


if __name__ == '__main__':
    main()

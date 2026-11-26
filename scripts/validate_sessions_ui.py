"""Recette Chromium des sessions : sortie volontaire, retour navigateur, cookie révoqué, isolation.

    python scripts/validate_sessions_ui.py --output data/sessions-validation

Base temporaire, comptes fictifs (example.test), mots de passe aléatoires jamais écrits.
Vérifie aussi les pages de connexion FRAMATEX et Client à 1440 et 390 px (captures).
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'sessions-validation')
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix='framat-sessions-') as temporary:
        os.environ.update(FRAMATEX_DATA_DIR=temporary, FRAMATEX_SECRET_KEY=secrets.token_urlsafe(48))
        __import__('recette_db').use_isolated_database()
        from app.core import SessionLocal, hash_password
        from app.models import Role, User
        from app.migrate import migrate
        from app.main import app  # noqa: F401
        migrate()
        chef_pw, client_pw = secrets.token_urlsafe(20), secrets.token_urlsafe(16) + 'Aa1!'
        with SessionLocal() as db:
            db.add(User(name='Chef Recette', email='chef.sessions@example.test', password_hash=hash_password(chef_pw), roles=[Role(name='Administrateur')]))
            db.commit()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        log = (output / 'server.log').open('w')
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                  cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
        try:
            import httpx
            for _ in range(150):
                try:
                    if httpx.get(base + '/api/health', timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(.1)
            checks = run(output, base, chef_pw, client_pw)
        finally:
            server.terminate()
            server.wait(timeout=10)
    text = json.dumps({'status': 'passed', 'checks': checks}, ensure_ascii=False, indent=2)
    assert chef_pw not in text and client_pw not in text
    (output / 'results.json').write_text(text)
    print('\n'.join('OK  ' + c for c in checks))
    print(f'{len(checks)} vérifications réussies.')


def run(output, base, chef_pw, client_pw):
    from playwright.sync_api import sync_playwright, expect
    from windows_runtime import browser_executable
    checks, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_executable())

        def context(width=1440):
            ctx = browser.new_context(base_url=base, locale='fr-FR', viewport={'width': width, 'height': 900 if width > 600 else 844})
            page = ctx.new_page()
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            return ctx, page

        def shot(page, name):
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')
            page.wait_for_timeout(400)
            assert page.evaluate('document.documentElement.scrollWidth - innerWidth') <= 1, name
            page.screenshot(path=str(output / f'{name}.png'), animations='disabled')

        def internal_login(page):
            page.goto('/espace-framatex')
            page.fill('#email', 'chef.sessions@example.test')
            page.fill('#password', chef_pw)
            page.click('#login-form [type=submit]')
            expect(page.locator('#fx-welcome-title')).to_be_visible(timeout=15000)

        # Pages de connexion (captures 1440 et 390 px), bouton afficher/masquer.
        for width in (1440, 390):
            ctx, page = context(width)
            page.goto('/espace-framatex')
            expect(page.locator('#login-form')).to_be_visible()
            expect(page.locator('.fx-auth-back')).to_have_attribute('href', '/')
            page.fill('#password', 'abc')
            page.click('.fx-eye')
            assert page.get_attribute('#password', 'type') == 'text'
            page.click('.fx-eye')
            assert page.get_attribute('#password', 'type') == 'password'
            page.fill('#password', '')
            shot(page, f'{width}-connexion-framatex')
            page.goto('/espace-client#/connexion')
            expect(page.locator('#login-form')).to_be_visible()
            expect(page.locator('.auth-back')).to_have_attribute('href', '/')
            shot(page, f'{width}-connexion-client')
            ctx.close()
        checks.append('Connexions FRAMATEX et Client : retour à l’accueil, afficher/masquer, 1440 et 390 px sans débordement')

        # Erreur lisible sur identifiants invalides.
        ctx, page = context()
        page.goto('/espace-framatex')
        page.fill('#email', 'chef.sessions@example.test')
        page.fill('#password', 'mauvais-mot-de-passe')
        page.click('#login-form [type=submit]')
        expect(page.locator('#login-error .error')).to_be_visible()
        expect(page.locator('#login-form [type=submit]')).to_be_enabled()
        checks.append('Identifiants invalides : message lisible, bouton réactivé')

        # Session conservée à l'actualisation et en navigation interne.
        internal_login(page)
        page.reload()
        expect(page.locator('#fx-welcome-title')).to_be_visible(timeout=15000)
        page.click('[data-view="launches"]')
        expect(page.locator('#ops-launch-results')).to_be_visible()
        checks.append('Actualisation et navigation interne : session conservée')

        # Échec serveur : l'utilisateur reste connecté et peut réessayer.
        page.route('**/api/auth/logout', lambda route: route.abort())
        page.locator('.topbar [data-fx-exit]').click()
        expect(page.locator('#toast')).to_contain_text('La déconnexion n’a pas abouti')
        assert page.url.endswith('/espace-framatex'), page.url
        assert ctx.request.get('/api/auth/me').status == 200
        page.unroute('**/api/auth/logout')
        checks.append('Échec de déconnexion : erreur affichée, session conservée, nouvel essai possible')

        # Sortie volontaire réelle.
        cookie = next(c for c in ctx.cookies() if c['name'] not in ('',))
        page.locator('.sidebar [data-fx-exit]').click()
        page.wait_for_url(base + '/')
        assert ctx.request.get('/api/auth/me').status == 401
        assert not [c for c in ctx.cookies() if c['name'] == cookie['name']]
        page.goto('/espace-framatex')
        expect(page.locator('#login-form')).to_be_visible()
        checks.append('Quitter l’espace : API de déconnexion, cookie supprimé, retour à la landing, nouvelle authentification exigée')
        # Retour navigateur : aucun écran connecté réaffiché.
        page.goto('/')
        page.go_back()
        expect(page.locator('#login-form')).to_be_visible(timeout=15000)
        assert page.locator('#fx-welcome-title').count() == 0
        checks.append('Retour navigateur après sortie : formulaire de connexion, aucun contenu de session')
        # Copie de l'ancien cookie : refusée côté serveur.
        thief = browser.new_context(base_url=base)
        thief.add_cookies([cookie])
        assert thief.request.get('/api/auth/me').status == 401
        assert thief.request.get('/api/workspace/launches').status == 401
        thief.close()
        checks.append('Ancien cookie réutilisé : 401 (session révoquée côté serveur)')
        ctx.close()

        # Espace Client : compte activé, sortie volontaire, isolation des sessions.
        api = httpx_client(base)
        reg = api.post('/api/client/register', json={'raison_sociale': 'Client Sessions', 'nom_contact': 'Contact Fictif', 'email': 'client.sessions@example.test',
                                                     'telephone': '0600000000', 'adresse': '1 rue fictive', 'pays': 'France', 'password': client_pw})
        assert reg.status_code == 201, reg.text
        chef = httpx_client(base)
        assert chef.post('/api/auth/login', json={'email': 'chef.sessions@example.test', 'password': chef_pw}).status_code == 200
        assert chef.patch(f"/api/admin/clients/{reg.json()['id']}/status", json={'status': 'active'}).status_code == 200
        # Isolation : la session interne n'ouvre pas l'Espace Client.
        assert chef.get('/api/client/me').status_code == 401
        ctx, page = context(390)
        page.goto('/espace-client#/connexion')
        page.fill('#login-email', 'client.sessions@example.test')
        page.fill('#login-password', client_pw)
        page.click('#login-form [type=submit]')
        page.wait_for_url('**#/demandes*', timeout=15000)
        assert ctx.request.get('/api/auth/me').status == 401          # la session Client n'ouvre pas l'espace FRAMATEX
        page.reload()
        page.wait_for_url('**#/demandes*', timeout=15000)
        page.click('[data-drawer-open]')
        page.locator('#drawer [data-exit]').click()
        page.wait_for_url(base + '/')
        assert ctx.request.get('/api/client/me').status == 401
        page.goto('/espace-client#/demandes')
        expect(page.locator('#login-form')).to_be_visible(timeout=15000)
        checks.append('Espace Client : quitter l’espace révoque la session (mobile), URL directe → connexion ; sessions Client et FRAMATEX isolées')
        ctx.close()
        assert not errors, errors
        checks.append('Aucune erreur JavaScript')
        browser.close()
    return checks


def httpx_client(base):
    import httpx
    return httpx.Client(base_url=base, headers=H, timeout=20)


if __name__ == '__main__':
    main()

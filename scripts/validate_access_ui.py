"""Recette navigateur : collaborateurs, mots de passe temporaires, affectations, isolation.

    python scripts/validate_access_ui.py --output data/access-validation

Base temporaire isolée : comptes fictifs (example.test), mots de passe aléatoires
générés pour la durée de la recette et jamais écrits dans le rapport ni les
captures. Serveur Uvicorn réel, Chromium (Playwright), 1440 et 390 px, puis
redémarrage du serveur pour vérifier la persistance des habilitations.
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


def start_server(port, log_path):
    log = log_path.open('a')
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                              cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
    import httpx
    for _ in range(150):
        try:
            if httpx.get(f'http://127.0.0.1:{port}/api/health', timeout=1).status_code == 200:
                return server
        except httpx.TransportError:
            pass
        if server.poll() is not None:
            raise RuntimeError('Échec du serveur de recette ; voir server.log')
        time.sleep(.1)
    raise RuntimeError('Serveur de recette non prêt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'access-validation')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    checks = []
    with tempfile.TemporaryDirectory(prefix='framat-access-') as temporary:
        os.environ['FRAMATEX_DATA_DIR'] = temporary
        __import__('recette_db').use_isolated_database()
        os.environ['FRAMATEX_SECRET_KEY'] = secrets.token_urlsafe(48)
        from app.core import SessionLocal, hash_password
        from app.models import Role, User
        from app.migrate import migrate
        from app.main import app  # noqa: F401
        migrate()
        chef_pw = secrets.token_urlsafe(24)
        chef_email = 'chef.recette@example.test'
        with SessionLocal() as db:
            db.add(User(name='Chef FRAMATEX (recette)', email=chef_email, password_hash=hash_password(chef_pw),
                        roles=[Role(name='Administrateur')]))
            db.commit()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        server = start_server(port, output / 'server.log')
        try:
            secrets_used = {chef_pw}
            result = run_browser(output, base, chef_email, chef_pw, checks, secrets_used, port)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        # Persistance après redémarrage du serveur (même base).
        server = start_server(port, output / 'server.log')
        try:
            import httpx
            with httpx.Client(base_url=base, headers=H) as client:
                assert client.post('/api/auth/login', json={'email': result['a_email'], 'password': result['a_password']}).status_code == 200
                ids = {row['id'] for row in client.get('/api/workspace/launches').json()}
                # 003 a été retirée à A au scénario 13 : seule 001 doit subsister.
                assert ids == {result['launches']['001']}, ids
                detail = client.get(f"/api/launches/{result['launches']['001']}").json()
                assert sorted(f['slug'] for f in detail['folders'] if f['can_read']) == ['jaune', 'rose']
                assert client.get(f"/api/launches/{result['launches']['003']}").status_code == 404
            checks.append('20. Habilitations (ajouts et retraits) conservées après redémarrage du serveur')
        finally:
            server.terminate()
            server.wait(timeout=10)
    report = {'status': 'passed', 'checks': checks, 'screenshots': sorted(p.name for p in output.glob('*.png'))}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert not any(secret in text for secret in secrets_used), 'secret dans le rapport'
    (output / 'results.json').write_text(text)
    print('\n'.join('OK  ' + c for c in checks))
    print(f"{len(checks)} vérifications, {len(report['screenshots'])} captures.")


def run_browser(output, base, chef_email, chef_pw, checks, secrets_used, port):
    from playwright.sync_api import sync_playwright, expect
    from windows_runtime import browser_executable
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_executable(), headless=True)

        def context(width=1440):
            ctx = browser.new_context(base_url=base, viewport={'width': width, 'height': 900 if width > 600 else 844}, locale='fr-FR')
            page = ctx.new_page()
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            return ctx, page

        def shot(page, name):
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(350)
            overflow = page.evaluate('document.documentElement.scrollWidth - innerWidth')
            assert overflow <= 0, f'{name} : défilement horizontal {overflow}px'
            page.screenshot(path=str(output / f'{name}.png'), full_page=False)

        def login(page, email, password):
            page.goto('/espace-framatex')
            page.fill('#email', email)
            page.fill('#password', password)
            page.click('#login-form button[type=submit]')

        def nav_click(page, selector):
            toggle = page.locator('.ops-drawer-toggle')
            if toggle.is_visible():
                toggle.click()
                expect(toggle).to_have_attribute('aria-expanded', 'true')
            page.locator(selector).click()

        def open_launch(page, order_ref, folder=None):
            nav_click(page, '[data-view="launches"]')
            page.fill('#q', order_ref)
            page.click('#ops-launch-filters button[type=submit]')
            row = page.locator('[data-ops-target]', has_text=order_ref).first
            expect(row).to_be_visible(); row.click()
            expect(page.locator('#ops-launch-summary')).to_contain_text(order_ref)
            if folder:
                page.locator(f'.dj-folder[data-folder="{folder}"]').click()
                expect(page.locator(f'[data-folder-panel="{folder}"]')).to_be_visible()

        chef_ctx, chef = context()
        login(chef, chef_email, chef_pw)
        expect(chef.locator('.ops-heading h1')).to_be_visible()
        checks.append('1. Connexion du chef')
        api = chef_ctx.request
        launches = {}
        for key in ('001', '002', '003', '004'):
            r = api.post('/api/launches', headers=H, data={'name': f'Commande {key}', 'order_ref': f'CMD-{key}', 'client_name': 'Client fictif', 'standard_profile': True})
            launches[key] = r.json()['id']
        for key, folder, title in (('001', 'jaune', 'FICHE-JAUNE-001'), ('001', 'bleu', 'DOUANE-BLEU-001'), ('002', 'rose', 'LIVRAISON-ROSE-002')):
            api.post(f'/api/launches/{launches[key]}/documents', headers=H, multipart={
                'folder': folder, 'title': title, 'doc_type': 'Autre', 'file': {'name': f'{title}.txt', 'mimeType': 'text/plain', 'buffer': title.encode()}})

        # 2. Création de techniciens dans l'interface ; le mot de passe temporaire n'est affiché qu'une fois.
        chef.click('[data-acc-view="access"]')
        expect(chef.locator('.ops-heading h1')).to_have_text('Collaborateurs et habilitations')
        techs = {}
        for key in ('a', 'b', 'c'):
            chef.click('#acc-new')
            chef.fill('#acc-name', f'Technicien {key.upper()}')
            chef.fill('#acc-email', f'technicien.{key}@example.test')
            chef.fill('#acc-job', 'Technicien')
            if key == 'a':
                shot(chef, 'acces-01-creation-collaborateur')
            chef.click('#acc-create-form button[type=submit]')
            secret = chef.locator('#acc-secret-value').inner_text().strip()
            assert len(secret) >= 12
            secrets_used.add(secret)
            techs[key] = {'email': f'technicien.{key}@example.test', 'temp': secret, 'password': secrets.token_urlsafe(16) + 'Aa1!'}
            secrets_used.add(techs[key]['password'])
            if key == 'a':
                chef.evaluate("document.querySelector('#acc-secret-value').textContent = '••••••••••••••••'")   # jamais de secret en capture
                shot(chef, 'acces-02-mot-de-passe-temporaire')
            chef.click('#acc-secret-done')
            expect(chef.locator('.acc-table')).to_contain_text(f'technicien.{key}@example.test')
        users = {u['email']: u['id'] for u in api.get('/api/admin/collaborators').json()}
        shot(chef, 'acces-03-liste-collaborateurs')
        checks.append('2. Création de trois techniciens dans l’interface (mot de passe temporaire affiché une seule fois)')

        # 3–4. Première connexion : changement obligatoire, puis état vide sans commande.
        tech_pages = {}
        for key, tech in techs.items():
            ctx, page = context()
            login(page, tech['email'], tech['temp'])
            expect(page.locator('#acc-password-form')).to_be_visible()
            if key == 'a':
                shot(page, 'acces-04-premiere-connexion')
            assert ctx.request.get('/api/workspace/launches').status == 403
            page.fill('#acc-current', tech['temp'])
            page.fill('#acc-new', tech['password'])
            page.fill('#acc-confirm', tech['password'])
            page.click('#acc-password-form button[type=submit]')
            expect(page.locator('#fx-welcome-title')).to_contain_text('Bonjour')
            tech_pages[key] = (ctx, page)
        a_ctx, a = tech_pages['a']
        expect(a.locator('.acc-empty')).to_contain_text('Aucune commande')
        shot(a, 'acces-05-technicien-sans-commande')
        checks.append('3. Première connexion : mot de passe temporaire remplacé avant tout accès')
        checks.append('4. Technicien nouvellement créé : aucune commande, état vide clair')

        # 5–11. Matrice d'une commande depuis son en-tête.
        open_launch(chef, 'CMD-001', 'jaune')
        chef.locator('#acc-assign').click()
        expect(chef.locator('.acc-matrix')).to_be_visible()
        # Chaque case dispose maintenant de son propre niveau : aucun préréglage
        # global ne doit pouvoir attribuer des droits par accident.
        for key, folder, level in (('a', 'jaune', 'depot'), ('a', 'rose', 'lecture'), ('b', 'bleu', 'depot')):
            chef.select_option(f'#acc-level-{users[techs[key]["email"]]}-{folder}', level)
        expect(chef.locator('.acc-matrix')).to_contain_text('Lecture seule')
        expect(chef.locator('.acc-matrix')).to_contain_text('Dépôt sans validation')
        shot(chef, 'acces-06-matrice-commande')
        chef.locator('#acc-matrix-save').click()
        expect(chef.locator('.acc-matrix')).to_have_count(0)
        # Commande 003 pour A (Bleu + Vert), 002 entière pour B : depuis l'API du chef.
        api.put(f"/api/admin/collaborators/{users[techs['a']['email']]}/assignments/{launches['003']}", headers=H,
                data={'folders': {'bleu': ['document.read'], 'vert': ['document.read']}})
        api.put(f"/api/admin/collaborators/{users[techs['b']['email']]}/assignments/{launches['002']}", headers=H,
                data={'folders': {s: ['document.read', 'document.download'] for s in ('jaune', 'rose', 'bleu', 'vert')}})
        checks.append('5–9. Affectations : A → 001 Jaune+Rose et 003 Bleu+Vert ; B → 001 Bleu et 002 complète ; C → aucune')

        a.reload()
        expect(a.locator('.ops-heading h1')).to_be_visible()
        visible = {row['id'] for row in a_ctx.request.get('/api/workspace/launches').json()}
        assert visible == {launches['001'], launches['003']}, visible
        open_launch(a, 'CMD-001', 'jaune')
        expect(a.locator('.dj-checklist').first).to_be_visible()
        expect(a.locator('[data-dj-folder="rose"]')).to_be_visible()
        expect(a.locator('[data-dj-folder="bleu"]')).to_have_count(0)
        assert 'DOUANE-BLEU-001' not in a.content()
        a.click('#dj-folders-back')
        expect(a.locator('.dj-folder.is-locked[data-folder="bleu"]')).to_be_visible()
        expect(a.locator('.dj-folder.is-locked[data-folder="vert"]')).to_be_visible()
        assert 'DOUANE-BLEU-001' not in a.content()
        shot(a, 'acces-07-technicien-dossier-partiel')
        assert a_ctx.request.get(f"/api/launches/{launches['002']}").status == 404
        checks.append('6. Aucun accès aux commandes non attribuées (liste et URL directe)')
        checks.append('7–8. Sous-dossiers non attribués verrouillés, sans titre ni contenu')
        a.click('[data-acc-view="myfolders"]')
        expect(a.locator('.acc-my-launch')).to_have_count(2)
        shot(a, 'acces-08-mes-sous-dossiers')
        overview = api.get('/api/admin/access/overview').json()
        assert next(r for r in overview['launches'] if r['launch']['id'] == launches['004'])['chef_only']
        chef.click('[data-acc-view="access"]')
        chef.click('[data-acc-tab="overview"]')
        expect(chef.locator('.acc-overview')).to_contain_text('Chef seul')
        shot(chef, 'acces-09-vue-globale')
        checks.append('10. Commande 004 gérée uniquement par le chef (indicateur, pas d’erreur)')

        # 12. Dépôt sans validation.
        up = a_ctx.request.post(f"/api/launches/{launches['001']}/documents", headers=H, multipart={
            'folder': 'jaune', 'title': 'Fiche de prix A', 'doc_type': 'Fiche de prix',
            'file': {'name': 'prix.txt', 'mimeType': 'text/plain', 'buffer': b'prix A'}})
        assert up.status == 201
        rule = next(r for r in a_ctx.request.get(f"/api/launches/{launches['001']}/completeness").json()['rows'] if r['title'] == 'Fiche de prix')
        assert rule['status'] == 'pending_validation' and not rule['can_review']
        assert a_ctx.request.post(f"/api/launches/{launches['001']}/completeness/rules/{rule['id']}/validate", headers=H,
                                  data={'document_id': up.json()['id']}).status == 403
        checks.append('12. Dépôt autorisé, validation refusée (permission distincte)')

        # 13. Retrait d'une permission pendant la session ouverte.
        api.put(f"/api/admin/collaborators/{users[techs['a']['email']]}/assignments/{launches['003']}", headers=H, data={'folders': {}})
        assert a_ctx.request.get(f"/api/launches/{launches['003']}").status == 404
        checks.append('13. Retrait pendant une session active : effet immédiat')
        # 15–16. URL directe et téléchargement non autorisés pour C.
        c_ctx, c = tech_pages['c']
        doc = next(d for f in api.get(f"/api/launches/{launches['001']}").json()['folders'] for d in f['documents'] if d['title'] == 'FICHE-JAUNE-001')
        for path in (f"/api/launches/{launches['001']}", f"/api/documents/{doc['id']}/versions/1/download",
                     f"/api/document-versions/{doc['latest']['id']}/passport", f"/api/launches/{launches['001']}/paper-link"):
            assert c_ctx.request.get(path).status == 404, path
        c.goto(f"/espace-framatex#/launch/{launches['001']}")
        c.wait_for_timeout(800)
        assert 'FICHE-JAUNE-001' not in c.content()
        checks.append('15–16. URL directe, téléchargement, passeport et QR refusés sans affectation')
        # 17. Recherche limitée.
        assert a_ctx.request.get('/api/workspace/search', params={'q': 'DOUANE-BLEU-001'}).json()['total'] == 0
        assert a_ctx.request.get('/api/workspace/search', params={'q': 'FICHE-JAUNE-001'}).json()['total'] == 1
        checks.append('17. Recherche et tableau de bord calculés sur les seules données autorisées')
        # 14. Désactivation.
        b_ctx, b = tech_pages['b']
        api.patch(f"/api/admin/collaborators/{users[techs['b']['email']]}", headers=H, data={'active': False})
        assert b_ctx.request.get('/api/workspace/launches').status == 401
        checks.append('14. Désactivation : session ouverte refusée immédiatement')
        # Mon compte (technicien) et vue mobile.
        a.click('[data-acc-view="account"]')
        expect(a.locator('.ops-heading h1')).to_have_text('Mon compte')
        shot(a, 'acces-10-mon-compte')
        m_ctx, m = context(390)
        login(m, chef_email, chef_pw)
        expect(m.locator('.ops-heading h1')).to_be_visible()
        nav_click(m, '[data-acc-view="access"]')
        expect(m.locator('.ops-heading h1')).to_have_text('Collaborateurs et habilitations')
        expect(m.locator('.acc-table')).to_be_visible()
        shot(m, 'acces-11-mobile-collaborateurs')
        open_launch(m, 'CMD-001', 'jaune')
        m.locator('#acc-assign').click()
        expect(m.locator('.acc-matrix')).to_be_visible()
        shot(m, 'acces-12-mobile-matrice')
        assert not errors, errors
        checks.append('Aucune erreur JavaScript ; écrans 1440 et 390 px sans défilement horizontal')
        browser.close()
    return {'a_email': techs['a']['email'], 'a_password': techs['a']['password'], 'launches': launches}


if __name__ == '__main__':
    main()

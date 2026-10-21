"""Recette navigateur isolée + captures 1440/1024/820/390.

python scripts/validate_internal_ui.py --output /workspace/artifacts/framatex
N'utilise ni comptes ni données de l'installation courante.
"""
from __future__ import annotations

import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'validation')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    # Les valeurs sont aléatoires et limitées à cette recette éphémère.
    with tempfile.TemporaryDirectory(prefix='framat-ui-') as temporary:
        os.environ['FRAMATEX_DATA_DIR'] = temporary
        os.environ.pop('DATABASE_URL', None)
        os.environ['FRAMATEX_SECRET_KEY'] = secrets.token_urlsafe(48)
        os.environ.pop('FRAMATEX_COOKIE_SECURE', None)
        local_tessdata = Path('/workspace/.cache/framatex-tessdata')
        if local_tessdata.is_dir():
            os.environ['TESSDATA_PREFIX'] = str(local_tessdata)
        from app.core import SessionLocal, hash_password
        from app.models import Role, User
        from app.migrate import migrate
        from app.seed_operations_demo import seed
        from app.main import app  # noqa: F401
        migrate()
        password = secrets.token_urlsafe(24)
        email = 'recette-interne@example.test'
        with SessionLocal() as db:
            role = Role(name='Administrateur')
            user = User(name='Responsable démonstration', email=email,
                        password_hash=hash_password(password), roles=[role])
            db.add(user)
            db.commit()
            ids = seed(db, user)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base_url = f'http://127.0.0.1:{port}'
        with (output / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
            try:
                import httpx
                for _ in range(100):
                    try:
                        if httpx.get(base_url + '/api/health', timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError('Échec du serveur de recette ; voir server.log')
                    time.sleep(.1)
                else:
                    raise RuntimeError('Serveur de recette non prêt')
                run_browser(output, base_url, email, password, ids)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def run_browser(output, base_url, email, password, ids):
    from playwright.sync_api import sync_playwright, expect
    results = {'status': 'running', 'run_id': secrets.token_hex(8),
               'tested_at': datetime.now(timezone.utc).isoformat(),
               'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
               'screenshots': [], 'widths': [], 'checks': [], 'errors': []}
    (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    with sync_playwright() as playwright:
        chromium = shutil.which('chromium') or shutil.which('google-chrome')
        browser = playwright.chromium.launch(executable_path=chromium, headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(base_url=base_url, locale='fr-FR', timezone_id='Africa/Casablanca')
        page = context.new_page()
        page.on('pageerror', lambda error: results['errors'].append(str(error)))
        failures = []
        page.on('response', lambda response: failures.append(f'{response.status} {response.url.split("/api/")[-1]}')
                if '/api/' in response.url and response.status >= 400 and not response.url.endswith('/api/auth/me') else None)
        page.goto('/espace-framatex')
        page.locator('#email').fill(email)
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        expect(page.locator('.ops-heading h1')).to_have_text('Tableau de bord')
        assert page.locator('.ops-kpi').count() == 8
        expect(page.locator('#ops-missing')).to_contain_text('Calcul du besoin')
        results['checks'].append('Connexion interne existante et 8 KPI réels')

        def ready():
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')

        def capture(name, width, selector=None, full_page=False):
            ready()
            if selector:
                page.locator(selector).first.scroll_into_view_if_needed()
            ready()
            dimensions = page.evaluate('({viewport:innerWidth,width:document.documentElement.scrollWidth})')
            assert dimensions['width'] <= width + 1, (name, width, dimensions)
            path = output / f'{width}-{name}.png'
            page.screenshot(path=str(path), full_page=full_page, animations='disabled')
            results['screenshots'].append(path.name)

        for width in (1440, 1024, 820, 390):
            page.set_viewport_size({'width': width, 'height': 1000 if width >= 820 else 844})
            page.evaluate("navigate('home')")
            expect(page.locator('.ops-heading h1')).to_have_text('Tableau de bord')
            capture('dashboard', width, full_page=True)
            capture('documents-manquants', width, '#ops-missing')
            page.evaluate("navigate('launches')")
            expect(page.locator('#ops-launch-results')).to_contain_text('FR-DEMO-2026-0142')
            capture('commandes', width)
            page.evaluate('(id)=>openLaunch(id,"jaune")', ids['B'])
            expect(page.locator('#ops-launch-summary')).to_be_visible()
            capture('dossier-jaune', width)
            for slug in ('jaune', 'rose', 'bleu', 'vert'):
                page.locator(f'[data-folder="{slug}"]').click()
                expect(page.locator('#ops-launch-summary')).to_be_visible()
                capture(slug, width, '.detail-layout')
            page.evaluate('(id)=>openLaunch(id,"jaune")', ids['E'])
            expect(page.locator('#ops-launch-summary')).to_be_visible()
            row = page.locator('.detail-layout tbody tr').filter(has_text='Fiche d’emploi').first
            row.locator('[data-history]').click()
            expect(page.locator('.modal')).to_be_visible()
            expect(page.locator('.modal-body')).to_contain_text('SHA-256')
            capture('fiche-document', width)
            page.locator('[data-ops-version]').last.click()
            expect(page.locator('.modal-body')).to_contain_text('Commentaires internes · V1')
            capture('historique-versions', width)
            page.locator('#close-modal').click()
            # Les contrôles avancés sont regroupés dans l'onglet « Contrôles ».
            page.evaluate("focusWorkspaceArea('workflow')")
            capture('alertes', width, '.workflow-root')
            page.evaluate("navigate('audit')")
            expect(page.locator('#ops-audit-results')).to_contain_text('Responsable démonstration')
            capture('audit', width)
            page.evaluate("navigate('search')")
            page.locator('#ops-search-form #q').fill('emploi')
            page.locator('#ops-search-form button[type=submit]').click()
            expect(page.locator('#ops-search-results')).to_contain_text('Fiche d’emploi')
            capture('recherche', width)
            if width <= 820:
                page.locator('.ops-drawer-toggle').click()
                expect(page.locator('.app-shell')).to_have_class('app-shell drawer-open')
                page.locator('.ops-drawer-close').click()
            results['widths'].append(width)
            print(f'Recette responsive {width}px et 13 captures : OK', flush=True)

        # Parcours réel dépôt + commentaire + doublon + nouvelle version.
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.evaluate('(id)=>openLaunch(id,"jaune")', ids['B'])
        expect(page.locator('#ops-launch-summary')).to_be_visible()
        page.locator('#upload-doc').click()
        page.locator('#ops-file').set_input_files({'name': 'calcul-du-besoin.txt',
                    'mimeType': 'text/plain', 'buffer': 'Calcul du besoin\nQuantité : 1800 pièces'.encode()})
        page.locator('#ops-title').fill('Calcul du besoin recette navigateur')
        page.locator('#ops-type').fill('Calcul du besoin')
        page.locator('#ops-upload-comment').fill('Commentaire interne de la recette navigateur')
        if page.locator('#dj-separate').count():
            page.check('#dj-separate')
        page.locator('#ops-analyze').click()
        expect(page.locator('#ops-analysis')).to_contain_text('Calcul du besoin')
        page.locator('#ops-upload-form button[type=submit]').click()
        expect(page.locator('.detail-layout')).to_contain_text('Calcul du besoin recette navigateur')
        row = page.locator('.detail-layout tbody tr').filter(has_text='Calcul du besoin recette navigateur')
        row.locator('[data-history]').click()
        expect(page.locator('.modal')).to_contain_text('Commentaire interne de la recette navigateur')
        page.locator('#ops-new-version').set_input_files({'name': 'besoin-v2.txt', 'mimeType': 'text/plain', 'buffer': b'Calcul du besoin revise 3500 metres'})
        page.locator('#ops-version-form button[type=submit]').click()
        expect(page.locator('.modal')).to_contain_text('Commentaires internes · V2')
        page.locator('#close-modal').click()
        results['checks'].append('Dépôt via interface, OCR/classement proposé, commentaire, SHA-256, nouvelle version')

        page.evaluate('(id)=>openLaunch(id,"jaune")', ids['E'])
        expect(page.locator('#ops-launch-summary')).to_be_visible()
        page.evaluate("focusWorkspaceArea('quality')")
        page.locator('[data-quality-decision]').first.click()
        page.locator('#qdec-type').select_option('to_correct')
        page.locator('#qdec-note').fill('Écart vérifié : comparer les quantités avec le responsable production.')
        page.locator('#qdec-form button[type=submit]').click()
        expect(page.locator('.quality-root')).to_contain_text('Correction demandée')
        page.evaluate("focusWorkspaceArea('workflow')")
        page.locator('[data-impact-review]').first.click()
        page.locator('#impact-status').select_option('acknowledged')
        page.locator('#impact-note').fill('Calcul du besoin et fiche de prix examinés pendant la recette fictive.')
        page.locator('#impact-form button[type=submit]').click()
        expect(page.locator('.workflow-root')).to_contain_text('Pris en compte')
        results['checks'].append('Qualification humaine de l’incohérence et prise en compte d’impact via interface')

        # OCR d'une image réelle, sans mock du moteur.
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (1400, 420), 'white')
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 44)
        draw = ImageDraw.Draw(image)
        draw.multiline_text((45, 45), 'Calcul du besoin\nQuantite : 1800 pieces\nDate : 21/10/2026', font=font, fill='black', spacing=20)
        image_path = output / 'ocr-source.png'
        image.save(image_path)
        response = context.request.post(f'/api/launches/{ids["B"]}/intake/preview',
            headers={'X-Framatex-Request': '1'}, multipart={'file': {
                'name': 'calcul-du-besoin.png', 'mimeType': 'image/png', 'buffer': image_path.read_bytes()}})
        assert response.ok, response.text()
        ocr = response.json()
        assert ocr['method'] == 'image_ocr', ocr
        assert any(field['key'] == 'quantite' for field in ocr['fields']), ocr
        results['checks'].append('OCR réel français/anglais sur image et extraction de quantité')

        # Les anciens liens QR restent utilisables depuis la racine existante.
        page.goto('/#/launch/' + ids['B'])
        expect(page.locator('.page-title')).to_contain_text('Démo B')
        expect(page.locator('#ops-launch-summary')).to_be_visible()
        for path in ('/', '/espace-framatex', '/espace-client', '/api/health'):
            assert context.request.get(path).ok
        results['checks'].append('Routes principales et lien QR historique')

        # Parcours client (portail static/client/) avec un autre contexte de cookies.
        client_context = browser.new_context(base_url=base_url, locale='fr-FR', accept_downloads=True)
        client_page = client_context.new_page()
        client_page.on('pageerror', lambda error: results['errors'].append('Client : ' + str(error)))
        client_email = 'recette-client@example.test'
        client_page.goto('/espace-client')
        client_page.locator('a[href="#/inscription"]').first.click()
        for key, value in {'reg-company': 'Collection Atlas Client', 'reg-contact': 'Contact recette',
             'reg-email': client_email, 'reg-phone': '0600000000', 'reg-address': '1 rue fictive',
             'reg-password': password, 'reg-password2': password}.items():
            client_page.locator('#' + key).fill(value)
        client_page.locator('#reg-country').select_option('Maroc')
        client_page.locator('#register-form button[type=submit]').click()
        expect(client_page.locator('main')).to_contain_text('Votre compte est en attente de validation par FRAMATEX')
        # Connexion refusée tant que le compte est en attente.
        client_page.goto('/espace-client#/connexion')
        client_page.locator('#login-email').fill(client_email)
        client_page.locator('#login-password').fill(password)
        client_page.locator('#login-form button[type=submit]').click()
        expect(client_page.locator('h1')).to_have_text('Votre compte est en attente de validation par FRAMATEX')
        clients = context.request.get('/api/admin/clients').json()
        account = next(c for c in clients if c['email'] == client_email)
        assert account['status'] == 'pending'
        assert context.request.patch(f'/api/admin/clients/{account["id"]}/status',
                headers={'X-Framatex-Request': '1'}, data={'status': 'active'}).ok
        client_page.goto('/espace-client#/connexion')
        client_page.locator('#login-email').fill(client_email)
        client_page.locator('#login-password').fill(password)
        client_page.locator('#login-form button[type=submit]').click()
        expect(client_page.locator('h1')).to_have_text('Mes demandes')
        client_page.locator('a[href="#/demandes/nouvelle"]').first.click()
        client_page.locator('#rq-article').fill('Chemise client recette')
        client_page.locator('#rq-qty').fill('750')
        client_page.locator('#rq-date').fill('2027-01-15')
        client_page.locator('#rq-files').set_input_files({'name': 'specification.txt', 'mimeType': 'text/plain', 'buffer': b'Specification Client navigateur'})
        client_page.locator('#request-form button.btn-primary[type=submit]').click()
        expect(client_page.locator('.detail-head .eyebrow')).to_contain_text('DR-')
        expect(client_page.locator('#docs-zone')).to_contain_text('specification.txt')
        expect(client_page.locator('#docs-zone')).to_contain_text('SHA-256')
        with client_page.expect_download() as download_info:
            client_page.locator('[data-download]').first.click()
        assert Path(download_info.value.path()).read_bytes() == b'Specification Client navigateur'
        assert client_context.request.get('/api/workspace/dashboard').status == 401
        page.evaluate("navigate('clients')")
        expect(page.locator('[data-ops-request]')).to_contain_text('Chemise client recette')
        page.locator('[data-ops-request]').first.click()
        expect(page.locator('.modal')).to_contain_text('specification.txt')
        client_page.set_viewport_size({'width': 1440, 'height': 1000})
        client_page.locator('.sidebar [data-logout]').click()
        expect(client_page.locator('h1')).to_contain_text('Bienvenue dans votre Espace Client')
        results['checks'].append('Inscription/activation/connexion/demande/pièce Client et consultation interne sans fuite')
        assert not results['errors'], results['errors']
        assert not failures, failures
        results['checks'].append('Aucune erreur JavaScript ni erreur API métier pendant les parcours internes')
        client_context.close()
        context.close()
        browser.close()
    results['status'] = 'passed'
    (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    links = ''.join(f'<li><a href="{name}">{name}</a></li>' for name in results['screenshots'])
    (output / 'index.html').write_text('<!doctype html><html lang="fr"><meta charset="utf-8"><title>Recette FRAMATEX</title><h1>Captures de recette</h1><ul>' + links + '</ul></html>')
    print(f"{len(results['screenshots'])} captures, {len(results['checks'])} parcours validés, aucune erreur JavaScript.", flush=True)


if __name__ == '__main__':
    main()

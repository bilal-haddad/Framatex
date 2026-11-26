"""Recette Chromium : suppression d'un document et d'une version, corbeille, restauration.

    python scripts/validate_document_deletion_ui.py --output data/deletion-validation

Clics réels, sans actualisation manuelle. Base temporaire, données de démonstration,
compte fictif (example.test), mot de passe aléatoire jamais écrit.
"""
import argparse, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'deletion-validation')
    out = parser.parse_args().output.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-deletion-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    __import__('recette_db').use_isolated_database()
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    from app.seed_operations_demo import seed
    import app.main  # noqa: F401
    migrate()
    pw = secrets.token_urlsafe(18)
    with SessionLocal() as db:
        user = User(name='Chef Recette', email='chef.suppression@example.test', password_hash=hash_password(pw), roles=[Role(name='Administrateur')])
        db.add(user); db.commit(); ids = seed(db, user)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=os.environ.copy(),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx
        for _ in range(150):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/api/health').status_code == 200: break
            except httpx.TransportError:
                time.sleep(.1)
        checks = run(f'http://127.0.0.1:{port}', pw, ids, out)
    finally:
        server.terminate()
    print('\n'.join('OK  ' + c for c in checks)); print(f'{len(checks)} vérifications réussies.')


def run(base, pw, ids, out):
    from playwright.sync_api import sync_playwright, expect
    from windows_runtime import browser_executable
    checks, errors, deletes = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable())
        page = browser.new_page(base_url=base, viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: deletes.append(r.url) if r.method == 'DELETE' else None)
        page.goto('/espace-framatex'); page.fill('#email', 'chef.suppression@example.test'); page.fill('#password', pw)
        page.click('#login-form [type=submit]'); page.wait_for_selector('.content h1')
        req = page.context.request

        def detail():
            return req.get(f"/api/launches/{ids['B']}").json()

        def documents():
            return [d for f in detail()['folders'] if f['slug'] == 'jaune' for d in f['documents']]

        def open_launch():
            launch = detail()
            page.click('[data-view="launches"]')
            page.fill('#q', launch.get('order_ref') or launch['name'])
            page.click('#ops-launch-filters button[type=submit]')
            row = page.locator('[data-ops-target]', has_text=launch.get('order_ref') or launch['name']).first
            expect(row).to_be_visible(); row.click()
            expect(page.locator('#ops-launch-summary')).to_be_visible()
            page.locator('.dj-folder[data-folder="jaune"]').click()
            expect(page.locator('[data-folder-panel="jaune"]')).to_be_visible()

        def open_document(document_id):
            button = page.locator(f'[data-history="{document_id}"]').first
            expect(button).to_be_visible(); button.click()
            expect(page.locator('.modal')).to_be_visible()

        # 1. Suppression d'un document complet (double clic neutralisé).
        open_launch()
        doc = next(d for d in documents() if (d.get('latest') or {}).get('number', 1) == 1)
        open_document(doc['id']); page.wait_for_selector('#ops-document-delete')
        page.click('#ops-document-delete')
        submit = page.locator('#ops-delete-form [type=submit]')
        page.fill('#ops-delete-reason', 'Recette : pièce déposée par erreur')
        submit.dblclick()
        expect(page.locator('#toast')).to_contain_text('Document supprimé avec succès')
        expect(page.locator('.modal')).to_have_count(0)
        assert len(deletes) == 1, deletes
        row = page.locator('.dj-checklist tr', has_text=doc['title']).first
        expect(row).to_contain_text('Manquant')                     # la pièce redevient manquante, sans actualisation
        assert doc['id'] not in [d['id'] for d in documents()]
        assert 'JSON' not in page.locator('#toast').inner_text()
        page.screenshot(path=str(out / 'suppression-document.png'))
        checks.append('Document : un seul DELETE (double clic neutralisé), fenêtre fermée, « Document supprimé avec succès », retiré du sous-dossier sans actualisation')

        # 2. Suppression d'une version individuelle.
        target = next(d for d in documents() if d['id'] != doc['id'])
        open_document(target['id'])
        page.click('#ops-version-upload')
        page.locator('#ops-file').set_input_files({
            'name': 'v2.txt', 'mimeType': 'text/plain',
            'buffer': b'version 2 de recette, contenu modifie',
        })
        expect(page.locator('#ops-analysis')).not_to_be_empty()
        if page.locator('#du-relationship-action').count():
            page.select_option('#du-relationship-action', 'new_version')
        if page.locator('#du-confirm-type').count():
            page.check('#du-confirm-type')
        submit_version = page.locator('#ops-upload-form [type=submit]')
        expect(submit_version).to_be_enabled(); submit_version.click()
        expect(page.locator('#ops-upload-form')).to_have_count(0)
        multi = next(d for d in documents() if d['id'] == target['id'])
        assert multi['latest']['number'] >= 2
        if multi:
            # La version se choisit dans l'historique du document (entrée portant le droit de suppression).
            open_document(multi['id']); page.wait_for_selector('#ops-version-delete')
            page.click('#ops-version-delete'); page.click('#ops-delete-form [type=submit]')
            expect(page.locator('#toast')).to_contain_text('Version supprimée avec succès')
            expect(page.locator('.modal')).to_have_count(0)
            after = next(d for d in documents() if d['id'] == multi['id'])
            assert after['latest']['number'] < multi['latest']['number'], after
            checks.append(f"Version : V{multi['latest']['number']} supprimée, version précédente active, sous-dossier actualisé")

        # 3. Corbeille administrateur et restauration, par clics.
        page.click('[data-ops-view="trash"]'); page.wait_for_selector('[data-ops-restore-id]')
        expect(page.locator('.ops-table')).to_contain_text(doc['title'])
        expect(page.locator('.ops-table')).to_contain_text('Recette : pièce déposée par erreur')
        page.screenshot(path=str(out / 'corbeille.png'))
        page.locator(f'[data-ops-restore-id="{doc["id"]}"]').click()
        expect(page.locator('#toast')).to_contain_text('Document restauré')
        expect(page.locator(f'[data-ops-restore-id="{doc["id"]}"]')).to_have_count(0)
        assert doc['id'] in [d['id'] for d in documents()]
        open_launch()
        expect(page.locator('.dj-checklist tr', has_text=doc['title']).first).to_contain_text('Présent')
        checks.append('Corbeille : document et motif listés ; restauration par clic, document de retour dans le sous-dossier')

        # 4. Une véritable erreur API reste affichée (pas masquée), le bouton redevient utilisable.
        open_document(doc['id']); page.wait_for_selector('#ops-document-delete')
        page.click('#ops-document-delete')
        page.route('**/api/documents/*', lambda route: route.fulfill(status=403, content_type='application/json', body='{"detail":"Suppression interdite pour ce document"}') if route.request.method == 'DELETE' else route.continue_())
        page.click('#ops-delete-form [type=submit]')
        expect(page.locator('#toast')).to_contain_text('Suppression interdite pour ce document')
        expect(page.locator('#ops-delete-form [type=submit]')).to_be_enabled()
        page.unroute('**/api/documents/*')
        checks.append('Erreur API réelle affichée telle quelle, bouton réactivé, fenêtre conservée')
        assert not errors, errors
        checks.append('Aucune erreur JavaScript')
        browser.close()
    return checks


if __name__ == '__main__':
    main()

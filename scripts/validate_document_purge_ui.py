"""Recette Chromium : suppression définitive depuis la corbeille (clics réels).

    python scripts/validate_document_purge_ui.py --output data/purge-validation

Préparation par l'API (commande, comptes fictifs, dépôts) ; suppressions, corbeille, vérification
de conservation et destruction par clics. Base temporaire, comptes example.test.
"""
import argparse, json, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}


def pdf(text):
    import fitz
    doc = fitz.open(); doc.new_page().insert_text((72, 90), text, fontsize=14)
    return doc.tobytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'purge-validation')
    out = parser.parse_args().output.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
    data_dir = tempfile.mkdtemp(prefix='framat-purge-')
    os.environ.update(FRAMATEX_DATA_DIR=data_dir, FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    os.environ.pop('DATABASE_URL', None)
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    import app.main  # noqa: F401
    migrate()
    pw = secrets.token_urlsafe(18) + 'Aa1!'
    with SessionLocal() as db:
        db.add(User(name='Chef Corbeille', email='chef.corbeille@example.test', password_hash=hash_password(pw), roles=[Role(name='Administrateur')]))
        db.commit()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=os.environ.copy(),
                              stdout=(out / 'server.log').open('w'), stderr=subprocess.STDOUT)
    try:
        import httpx
        for _ in range(150):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/api/health').status_code == 200: break
            except httpx.TransportError:
                time.sleep(.1)
        checks = run(f'http://127.0.0.1:{port}', pw, out, Path(data_dir) / 'files')
    finally:
        server.terminate()
    (out / 'results.json').write_text(json.dumps({'status': 'passed', 'checks': checks}, ensure_ascii=False, indent=2))
    print('\n'.join('OK  ' + c for c in checks)); print(f'{len(checks)} vérifications réussies.')


def run(base, pw, out, storage):
    import httpx
    from playwright.sync_api import sync_playwright, expect
    from windows_runtime import browser_executable
    checks, errors, failed = [], [], []
    api = httpx.Client(base_url=base, headers=H, timeout=60)
    api.post('/api/auth/login', json={'email': 'chef.corbeille@example.test', 'password': pw}).raise_for_status()
    tag = secrets.token_hex(3).upper()
    lid = api.post('/api/order-sheets', json={'name': f'Corbeille {tag}', 'order_ref': f'COR-{tag}'}).json()['id']
    api.post(f'/api/launches/{lid}/completeness/standard').raise_for_status()

    def deposit(folder, title, data, doc_type='Autre'):
        r = api.post(f'/api/launches/{lid}/documents', data={'folder': folder, 'title': title, 'doc_type': doc_type},
                     files={'file': (f'{title}.pdf', data, 'application/pdf')})
        r.raise_for_status(); return r.json()

    same = pdf(f'Copie identique {tag}')
    wrong = deposit('jaune', f'Pièce erronée {tag}', same)
    copy = deposit('rose', f'Copie rose {tag}', same)
    plan = deposit('jaune', f'Plan {tag}', pdf(f'Plan V1 {tag}'))
    plan_v2 = api.post(f"/api/documents/{plan['id']}/versions", files={'file': ('plan-v2.pdf', pdf(f'Plan V2 {tag}'), 'application/pdf')}).json()
    invoice = deposit('vert', f'Facture {tag}', pdf(f'Facture {tag}'), doc_type='Facture')
    tech = api.post('/api/admin/collaborators', json={'name': 'Responsable Corbeille', 'email': 'resp.corbeille@example.test'}).json()
    api.put(f"/api/admin/collaborators/{tech['collaborator']['id']}/assignments/{lid}",
            json={'folders': {s: ['document.read', 'document.write', 'document.review'] for s in ('jaune', 'rose', 'bleu', 'vert')}}).raise_for_status()
    tech_pw = secrets.token_urlsafe(16) + 'Aa1!'
    with httpx.Client(base_url=base, headers=H) as t:
        t.post('/api/auth/login', json={'email': 'resp.corbeille@example.test', 'password': tech['temporary_password']}).raise_for_status()
        t.post('/api/account/password', json={'current_password': tech['temporary_password'], 'new_password': tech_pw}).raise_for_status()
    files_before = {p.name for p in storage.iterdir()}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable())
        context = browser.new_context(base_url=base, viewport={'width': 1440, 'height': 900}, locale='fr-FR')
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('response', lambda r: failed.append((r.status, r.url)) if r.status >= 400 and '/api/' in r.url and not r.url.endswith('/auth/me') else None)

        def login(email, password):
            page.goto('/espace-framatex'); page.fill('#email', email); page.fill('#password', password)
            page.click('#login-form [type=submit]'); page.wait_for_load_state('networkidle')

        def open_order():
            page.click('[data-view="launches"]'); page.fill('#q', f'COR-{tag}'); page.click('#ops-launch-filters button[type=submit]')
            page.locator('[data-ops-target]', has_text=f'COR-{tag}').first.click()
            expect(page.locator('#ops-launch-summary')).to_be_visible()

        def open_folder(slug):
            if not page.locator(f'button.dj-folder[data-folder="{slug}"]').count():
                page.click('#dj-folders-back')
            page.click(f'button.dj-folder[data-folder="{slug}"]')
            expect(page.locator(f'[data-folder-panel="{slug}"]')).to_be_visible()

        def open_document(doc_id):
            row = page.locator(f'.dj-row:has([data-history="{doc_id}"]), .dj-row[data-doc="{doc_id}"]').first
            if row.locator(f'[data-history="{doc_id}"]').count():
                row.locator(f'[data-history="{doc_id}"]').click()
            else:
                row.locator('[data-dj-duplicate]').click(); page.locator(f'[data-dup-open="{doc_id}"]').click()
            expect(page.locator('.modal .dv-layout')).to_be_visible()

        def remove(selector, toast):
            page.click(selector); page.fill('#ops-delete-reason', 'Recette : dépôt erroné')
            page.click('#ops-delete-form [type=submit]')
            expect(page.locator('#toast')).to_contain_text(toast)
            expect(page.locator('body[aria-busy="true"]')).to_have_count(0)

        def duplicates_tally():
            if page.locator('#dj-folders-back').count():
                page.click('#dj-folders-back')
            return int(page.locator('.dj-tally-item.is-duplicate strong').inner_text())

        def trash_row(text):
            return page.locator('.trash-table tr', has_text=text)

        def purge_from_trash(text, reason='Recette : destruction validée'):
            row = trash_row(text)
            row.locator('[data-trash-purge]').click()
            expect(page.locator('.modal')).to_contain_text('ne pourra plus être restauré depuis l’application')
            submit = page.locator('#trash-purge-form [type=submit]')
            page.fill('#trash-purge-reason', reason)
            page.fill('#trash-purge-confirm', 'supprimé')
            expect(submit).to_be_disabled()                                         # confirmation renforcée
            page.fill('#trash-purge-confirm', 'SUPPRIMER')
            expect(submit).to_be_enabled(); submit.click()
            expect(page.locator('#toast')).to_contain_text('Suppression définitive effectuée')
            expect(trash_row(text)).to_have_count(0)

        login('chef.corbeille@example.test', pw)
        open_order()
        assert duplicates_tally() == 1
        open_folder('jaune'); open_document(wrong['id']); remove('#ops-document-delete', 'Document supprimé avec succès')
        assert duplicates_tally() == 0
        page.click('[data-ops-view="trash"]')
        row = trash_row(f'Pièce erronée {tag}')
        for value in (f'Pièce erronée {tag}.pdf', f'COR-{tag}', 'Sous-dossier jaune', 'Autre', 'V1', 'Chef Corbeille', 'Recette : dépôt erroné'):
            expect(row).to_contain_text(value)
        expect(row.locator('[data-ops-restore-id]')).to_be_visible()
        page.screenshot(path=str(out / '01-corbeille.png'), animations='disabled')
        checks.append('Corbeille : fichier, commande, sous-dossier, type, version, taille, auteur et date de suppression, Restaurer et Supprimer définitivement')
        purge_from_trash(f'Pièce erronée {tag}')
        assert api.post(f"/api/admin/document-trash/documents/{wrong['id']}/restore").status_code == 404
        assert page.context.request.get(f"/api/document-versions/{wrong['latest']['id']}/preview").status == 404
        assert page.context.request.get(f"/api/documents/{wrong['id']}/versions/1/download").status == 404
        checks.append('Document détruit par clics (saisie « SUPPRIMER » obligatoire) : absent de la corbeille, non restaurable, inaccessible par URL directe')
        open_order()
        assert duplicates_tally() == 0
        open_folder('rose')
        expect(page.locator(f'.dj-row[data-doc="{copy["id"]}"]')).not_to_have_attribute('data-state', 'duplicate')
        assert len({p.name for p in storage.iterdir()}) == len(files_before) - 1
        checks.append('Compteurs à jour, copie identique conservée sans faux doublon, un seul fichier physique effacé')

        # Version seule.
        open_folder('jaune'); open_document(plan['id']); remove('#ops-version-delete', 'Version supprimée avec succès')
        page.click('[data-ops-view="trash"]')
        expect(trash_row(f'Plan {tag}')).to_contain_text('Version V2')
        purge_from_trash(f'Plan {tag}')
        open_order(); open_folder('jaune'); open_document(plan['id'])
        expect(page.locator('.modal')).to_contain_text('V1 · courante')
        expect(page.locator('.modal [data-ops-version]')).to_have_count(1)
        page.locator('#close-modal').click()
        assert page.context.request.get(f"/api/document-versions/{plan_v2['latest']['id']}/preview").status == 404
        checks.append('Version V2 détruite ; le document et sa V1 restent consultables')

        # Facture : conservation obligatoire, vérification administrative avant destruction.
        open_folder('vert'); open_document(invoice['id']); remove('#ops-document-delete', 'Document supprimé avec succès')
        page.click('[data-ops-view="trash"]')
        trash_row(f'Facture {tag}').locator('[data-trash-purge]').click()
        expect(page.locator('.modal')).to_contain_text('Conservation obligatoire en cours')
        expect(page.locator('#trash-purge-form')).to_have_count(0)
        page.screenshot(path=str(out / '02-conservation-obligatoire.png'), animations='disabled')
        page.fill('#trash-clearance-reason', 'Facture déposée par erreur, original conservé en comptabilité')
        page.check('#trash-clearance-confirm'); page.click('#trash-clearance-form [type=submit]')
        expect(page.locator('#trash-purge-form')).to_be_visible()
        page.locator('#cancel-modal').click()
        purge_from_trash(f'Facture {tag}')
        checks.append('Facture : destruction refusée tant que la conservation n’est pas vérifiée ; vérification motivée puis destruction')
        page.click('#logout')

        # Responsable : suppression logique conservée, aucune corbeille ni destruction.
        context.clear_cookies()
        login('resp.corbeille@example.test', tech_pw)
        expect(page.locator('[data-ops-view="trash"]')).to_have_count(0)
        assert page.context.request.get('/api/admin/document-trash').status == 403
        assert page.context.request.post(f"/api/admin/document-trash/documents/{copy['id']}/purge", headers={**H, "Content-Type": "application/json"},
                                         data=json.dumps({'confirmation': 'SUPPRIMER', 'reason': 'tentative'})).status == 403
        checks.append('Responsable : aucune corbeille ni suppression définitive (403), suppression logique inchangée')
        events = api.get('/api/workspace/activity', params={'launch_id': lid, 'action': 'document.purge'}).json()['items']
        assert len(events) == 3 and all('original_name' not in json.dumps(e['detail']) for e in events)
        checks.append('Trois destructions tracées dans l’historique (trace minimale)')
        assert not errors, errors
        unexpected = [f for f in failed if not f[1].endswith('/api/admin/document-trash') and '/purge' not in f[1] and '/preview' not in f[1] and '/download' not in f[1]]
        assert not unexpected, unexpected
        checks.append('Aucune erreur JavaScript ni requête en échec hors refus attendus')
        browser.close()
    return checks


if __name__ == '__main__':
    main()

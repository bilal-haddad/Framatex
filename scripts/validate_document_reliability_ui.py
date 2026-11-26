"""Recette Chromium : fiabilité documentaire, synchronisation et recherche du technicien.

    python scripts/validate_document_reliability_ui.py --output data/reliability-validation

Clics réels uniquement pour les parcours vérifiés (dépôts, suppressions, restaurations, navigation,
recherche). L'API sert à préparer la base (commande, comptes fictifs) et à vérifier l'état serveur
après les clics. Base temporaire, comptes example.test, mots de passe aléatoires jamais écrits.
"""
import argparse, io, json, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}


def pdf(text):
    import fitz
    doc = fitz.open(); doc.new_page().insert_text((72, 90), text, fontsize=14)
    return doc.tobytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'reliability-validation')
    out = parser.parse_args().output.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-reliability-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    os.environ.pop('DATABASE_URL', None)
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    import app.main  # noqa: F401
    migrate()
    pw = secrets.token_urlsafe(18) + 'Aa1!'
    with SessionLocal() as db:
        db.add(User(name='Chef Fiabilité', email='chef.fiabilite@example.test', password_hash=hash_password(pw), roles=[Role(name='Administrateur')]))
        db.commit()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    import httpx
    servers = []

    def start():
        servers.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=os.environ.copy(),
                                        stdout=(out / 'server.log').open('a'), stderr=subprocess.STDOUT))
        for _ in range(150):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/api/health').status_code == 200: return
            except httpx.TransportError:
                time.sleep(.1)
        raise RuntimeError('Serveur de recette indisponible')

    def restart():
        servers[-1].terminate(); servers[-1].wait(timeout=15); start()

    start()
    try:
        checks = run(f'http://127.0.0.1:{port}', pw, out, restart)
    finally:
        servers[-1].terminate()
    (out / 'results.json').write_text(json.dumps({'status': 'passed', 'checks': checks}, ensure_ascii=False, indent=2))
    print('\n'.join('OK  ' + c for c in checks)); print(f'{len(checks)} vérifications réussies.')


def run(base, pw, out, restart):
    import httpx
    from playwright.sync_api import sync_playwright, expect
    from windows_runtime import browser_executable
    checks, errors, refused = [], [], []
    api = httpx.Client(base_url=base, headers=H, timeout=60)
    api.post('/api/auth/login', json={'email': 'chef.fiabilite@example.test', 'password': pw}).raise_for_status()
    tag = secrets.token_hex(3).upper()
    order = api.post('/api/order-sheets', json={'name': f'Costume fiabilité {tag}', 'order_ref': f'FIA-{tag}', 'client_name': 'Atelier fictif',
                                                  'workshop': 'Atelier Sud', 'color': 'Gris anthracite', 'of_number': f'OF-{tag}'}).json()
    other = api.post('/api/order-sheets', json={'name': f'Veste fiabilité {tag}', 'order_ref': f'VES-{tag}', 'workshop': 'Atelier Nord'}).json()
    secret = api.post('/api/order-sheets', json={'name': f'Commande non attribuée {tag}', 'order_ref': f'SEC-{tag}'}).json()
    lid = order['id']
    api.post(f'/api/launches/{lid}/completeness/standard').raise_for_status()        # checklist standard (22 pièces)
    # Pièce confidentielle dans le rose (jamais attribué au technicien).
    api.post(f'/api/launches/{lid}/documents', data={'folder': 'rose', 'title': f'Bon confidentiel {tag}', 'doc_type': 'Autre'},
             files={'file': ('confidentiel.pdf', pdf(f'Confidentiel {tag}'), 'application/pdf')}).raise_for_status()
    tech = api.post('/api/admin/collaborators', json={'name': 'Technicien Fiabilité', 'email': 'tech.fiabilite@example.test', 'job_title': 'Technicien'}).json()
    tid = tech['collaborator']['id']
    api.put(f'/api/admin/collaborators/{tid}/assignments/{lid}', json={'folders': {'jaune': ['document.read', 'document.write'], 'bleu': ['document.read']}}).raise_for_status()
    api.put(f"/api/admin/collaborators/{tid}/assignments/{other['id']}", json={'folders': {'vert': ['document.read']}}).raise_for_status()
    tech_pw = secrets.token_urlsafe(16) + 'Aa1!'
    with httpx.Client(base_url=base, headers=H) as t:
        t.post('/api/auth/login', json={'email': 'tech.fiabilite@example.test', 'password': tech['temporary_password']}).raise_for_status()
        t.post('/api/account/password', json={'current_password': tech['temporary_password'], 'new_password': tech_pw}).raise_for_status()
    same = pdf(f'Fiche technique identique {tag}')

    def documents(folder):
        return [d for f in api.get(f'/api/launches/{lid}').json()['folders'] if f['slug'] == folder for d in f['documents']]

    def duplicate_groups():
        return api.get(f'/api/launches/{lid}/duplicates').json()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable())
        context = browser.new_context(base_url=base, viewport={'width': 1440, 'height': 900}, locale='fr-FR')
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('response', lambda r: refused.append((r.status, r.url)) if r.status >= 400 and '/api/' in r.url and not r.url.endswith('/auth/me') else None)

        def login(email, password):
            page.goto('/espace-framatex'); page.fill('#email', email); page.fill('#password', password)
            page.click('#login-form [type=submit]'); page.wait_for_load_state('networkidle')

        def open_order(ref):
            page.click('[data-view="launches"]')
            page.fill('#q', ref); page.click('#ops-launch-filters button[type=submit]')
            row = page.locator('[data-ops-target]', has_text=ref).first
            expect(row).to_be_visible(); row.click()
            expect(page.locator('#ops-launch-summary')).to_be_visible()

        def open_folder(slug):
            if not page.locator(f'button.dj-folder[data-folder="{slug}"]').count():
                page.click('#dj-folders-back')
            page.click(f'button.dj-folder[data-folder="{slug}"]')
            expect(page.locator(f'[data-folder-panel="{slug}"]')).to_be_visible()

        def deposit(title, data):
            page.click('#upload-doc')
            page.locator('#ops-file').set_input_files({'name': f'{title}.pdf', 'mimeType': 'application/pdf', 'buffer': data})
            expect(page.locator('#ops-analysis')).not_to_be_empty()
            page.fill('#ops-type', 'Autre'); page.fill('#ops-title', title)
            if page.locator('#du-relationship-action').count():
                page.select_option('#du-relationship-action', 'new_document')
            if page.locator('#du-confirm-type').count():
                page.check('#du-confirm-type')
            with page.expect_response(lambda r: r.url.endswith('/publish')) as published:
                page.click('#ops-upload-form [type=submit]')
            assert published.value.status == 201, published.value.text()
            expect(page.locator('#ops-upload-form')).to_have_count(0)
            expect(page.locator('body[aria-busy="true"]')).to_have_count(0)
            return published.value.json()

        def overview_duplicates():
            if page.locator('#dj-folders-back').count():
                page.click('#dj-folders-back')
            return int(page.locator('.dj-tally-item.is-duplicate strong').inner_text())

        def open_document(doc_id):
            row = page.locator(f'.dj-row:has([data-history="{doc_id}"]), .dj-row[data-doc="{doc_id}"]').first
            row.wait_for()
            if row.locator(f'[data-history="{doc_id}"]').count():
                row.locator(f'[data-history="{doc_id}"]').click()
            else:                                                   # ligne en doublon : « Examiner le doublon » puis « Ouvrir »
                row.locator('[data-dj-duplicate]').click(); page.locator(f'[data-dup-open="{doc_id}"]').click()
            expect(page.locator('.modal .dv-layout')).to_be_visible()

        def delete_document(doc_id):
            open_document(doc_id)
            page.click('#ops-document-delete'); page.fill('#ops-delete-reason', 'Recette : dépôt en double')
            page.click('#ops-delete-form [type=submit]')
            expect(page.locator('#toast')).to_contain_text('Document supprimé avec succès')
            expect(page.locator('body[aria-busy="true"]')).to_have_count(0)

        def restore(doc_id):
            page.click('[data-ops-view="trash"]')
            page.locator(f'[data-ops-restore-id="{doc_id}"]').click()
            expect(page.locator('#toast')).to_contain_text('Document restauré')

        # ------------------------------------------------------------ 1. Doublons : Jaune, Rose, Bleu
        login('chef.fiabilite@example.test', pw)
        open_order(f'FIA-{tag}')
        open_folder('jaune'); jaune = deposit('Fiche jaune', same)
        open_folder('rose'); rose = deposit('Fiche rose', same)
        expect(page.locator(f'[data-folder-panel="rose"] .dj-row[data-doc="{rose["id"]}"]')).to_have_attribute('data-state', 'duplicate')
        assert overview_duplicates() == 1 and len(duplicate_groups()) == 1
        page.screenshot(path=str(out / '01-doublon-detecte.png'))
        checks.append('Même PDF déposé en Jaune puis en Rose (clics) : « Doublon détecté » et compteur 1, sans actualisation')
        open_folder('jaune'); delete_document(jaune['id'])
        assert overview_duplicates() == 0 and duplicate_groups() == []
        assert api.get('/api/workspace/dashboard').json()['kpis'].get('duplicate_documents', 0) == 0
        open_folder('rose')
        expect(page.locator(f'.dj-row[data-doc="{rose["id"]}"]')).not_to_have_attribute('data-state', 'duplicate')
        checks.append('Suppression du Jaune : alerte, compteur de la commande et tableau de bord général à 0 immédiatement')
        restore(jaune['id']); open_order(f'FIA-{tag}')
        assert overview_duplicates() == 1 and len(duplicate_groups()) == 1
        checks.append('Restauration depuis la corbeille : le doublon réapparaît (compteur 1)')
        open_folder('jaune'); delete_document(jaune['id'])
        open_folder('rose'); delete_document(rose['id'])
        open_folder('bleu'); bleu = deposit('Fiche bleue', same)
        assert bleu['id'] not in {jaune['id'], rose['id']}
        expect(page.locator(f'.dj-row[data-doc="{bleu["id"]}"]')).not_to_have_attribute('data-state', 'duplicate')
        assert overview_duplicates() == 0 and duplicate_groups() == []
        page.screenshot(path=str(out / '02-depot-bleu-sans-faux-doublon.png'))
        checks.append('Suppression des deux pièces puis dépôt en Bleu : aucun faux doublon')

        # Suppression d'une version seule : la copie de la V2 n'est plus un doublon courant.
        open_folder('jaune'); plan = deposit('Plan de coupe', pdf(f'Plan V1 {tag}'))
        v2 = pdf(f'Plan V2 {tag}')
        open_document(plan['id'])
        page.click('#ops-version-upload')
        page.locator('#ops-file').set_input_files({'name': 'plan-v2.pdf', 'mimeType': 'application/pdf', 'buffer': v2})
        expect(page.locator('#ops-analysis')).not_to_be_empty()
        if page.locator('#du-relationship-action').count():
            options = page.locator('#du-relationship-action option').evaluate_all('nodes => nodes.map(n => n.value)')
            page.select_option('#du-relationship-action', 'new_version' if 'new_version' in options else 'new_document')
        if page.locator('#du-confirm-type').count():
            page.check('#du-confirm-type')
        page.click('#ops-upload-form [type=submit]')
        expect(page.locator('.modal')).to_contain_text('V2 · courante')            # fiche rouverte sur la nouvelle version
        page.locator('#close-modal').click()
        open_folder('bleu'); copy = deposit('Copie du plan', v2)
        assert len(duplicate_groups()) == 1
        open_folder('jaune'); open_document(plan['id'])
        page.click('#ops-version-delete'); page.click('#ops-delete-form [type=submit]')
        expect(page.locator('#toast')).to_contain_text('Version supprimée avec succès')
        expect(page.locator('body[aria-busy="true"]')).to_have_count(0)
        assert overview_duplicates() == 0 and duplicate_groups() == []
        checks.append('Nouvelle version par « Déposer une nouvelle version » puis suppression de la V2 : la copie identique n’est plus un doublon')

        # ------------------------------------------------------------ 2. Synchronisation sans F5
        # Dépôt concurrent par un autre utilisateur, puis retour sur l'onglet : liste et compteurs relus.
        open_folder('jaune')
        before = page.locator('[data-folder-panel="jaune"] .dj-row').count()
        api.post(f'/api/launches/{lid}/documents', data={'folder': 'jaune', 'title': f'Dépôt concurrent {tag}', 'doc_type': 'Autre'},
                 files={'file': ('concurrent.pdf', pdf(f'Concurrent {tag}'), 'application/pdf')}).raise_for_status()
        # Chromium automatisé ne masque jamais un onglet (ni changement d'onglet ni fenêtre réduite) :
        # l'événement du navigateur est simulé (aucune fonction de l'application n'est appelée),
        # avec une vraie absence de 15,5 s.
        hide = "visible => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => !visible}); document.dispatchEvent(new Event('visibilitychange')); }"
        page.evaluate(hide, False)
        page.wait_for_timeout(15500)
        page.evaluate(hide, True)
        expect(page.locator('[data-folder-panel="jaune"] .dj-row', has_text=f'Dépôt concurrent {tag}')).to_be_visible()
        assert page.locator('[data-folder-panel="jaune"] .dj-row').count() == before + 1
        expect(page.locator('h1')).to_have_text('Sous-dossier jaune')           # même écran conservé
        checks.append('Dépôt concurrent d’un autre compte : visible au retour sur l’onglet, sans F5 ni changement d’écran')

        # Navigation pendant une actualisation : le choix de l'utilisateur n'est pas écrasé.
        page.route('**/api/launches/*/completeness', lambda route: (time.sleep(1.2), route.continue_()))
        page.click('[data-dj-folder="bleu"]')
        open_document(copy['id'])
        page.click('#ops-document-delete'); page.click('#ops-delete-form [type=submit]')
        expect(page.locator('body[aria-busy="true"]')).to_have_count(1)
        page.click('#dj-folders-back')                                          # pendant l'actualisation
        expect(page.locator('body[aria-busy="true"]')).to_have_count(0, timeout=15000)
        page.unroute('**/api/launches/*/completeness')
        expect(page.locator('button.dj-folder')).to_have_count(4)
        assert copy['id'] not in [d['id'] for d in documents('bleu')]
        checks.append('Clic « Tous les sous-dossiers » pendant une actualisation : pris en compte, non écrasé par la réponse plus ancienne')
        # ------------------------------------------------------------ 3. Documents complémentaires facultatifs
        open_folder('rose')
        section = page.locator('[data-folder-panel="rose"] .dj-optional-docs')
        expect(section).to_contain_text('Documents complémentaires facultatifs')
        expect(section.locator('#dj-optional-form')).to_be_visible()                      # visible même sans case
        page.click('#dj-folders-back')
        missing_before = page.locator('.dj-tally-item.is-missing strong').inner_text()
        open_folder('rose')
        page.fill('#dj-optional-title', 'Photos du prototype'); page.fill('#dj-optional-description', 'Vues face et dos')
        page.click('#dj-optional-form button[value="now"]')
        expect(page.get_by_role('dialog', name='Déposer · Photos du prototype')).to_be_visible()
        page.locator('#ops-file').set_input_files([{'name': 'prototype-face.pdf', 'mimeType': 'application/pdf', 'buffer': pdf(f'Prototype face {tag}')},
                                                   {'name': 'prototype-dos.pdf', 'mimeType': 'application/pdf', 'buffer': pdf(f'Prototype dos {tag}')}])
        for _ in range(2):
            expect(page.locator('#ops-analysis')).to_contain_text('Document complémentaire facultatif')
            expect(page.locator('#du-confirm-type')).to_have_count(0)
            if page.locator('#du-relationship-action').count():
                page.select_option('#du-relationship-action', 'new_document')
            with page.expect_response(lambda r: r.url.endswith('/publish')) as published:
                page.click('#ops-upload-form [type=submit]')
            assert published.value.status == 201 and published.value.json()['doc_type'] == 'Document complémentaire'
        expect(page.locator('#du-files')).to_contain_text('Déposé · V1')
        page.click('#cancel-modal')
        expect(page.locator('body[aria-busy="true"]')).to_have_count(0)
        case = page.locator('.dj-optional-case', has_text='Photos du prototype')
        expect(case.locator('.dj-row')).to_have_count(2)                                # sans actualisation manuelle
        expect(case).to_contain_text('Vues face et dos')
        page.fill('#dj-optional-title', 'Échange atelier'); page.click('#dj-optional-form button[value="later"]')
        empty = page.locator('.dj-optional-case', has_text='Échange atelier')
        expect(empty).to_contain_text('Aucun document pour l’instant')
        page.screenshot(path=str(out / '05-documents-complementaires.png'), full_page=True)
        page.click('#dj-folders-back')
        assert page.locator('.dj-tally-item.is-missing strong').inner_text() == missing_before
        open_folder('rose')
        checks.append('Rose : section permanente, case créée puis deux documents déposés ; case vide « Échange atelier » ; compteur de pièces manquantes inchangé')
        empty.locator('[data-optional-edit]').click()
        page.fill('#dj-optional-edit-title', 'Échanges avec l’atelier'); page.click('#dj-optional-edit-form [type=submit]')
        expect(page.locator('.dj-optional-case', has_text='Échanges avec l’atelier')).to_be_visible()
        page.locator('.dj-optional-case', has_text='Échanges avec l’atelier').locator('[data-optional-delete]').click()
        page.click('#dj-optional-delete-form [type=submit]')
        expect(page.locator('.dj-optional-case', has_text='Échanges avec l’atelier')).to_have_count(0)
        expect(case.locator('[data-optional-delete]')).to_have_count(0)                # case non vide : non supprimable
        checks.append('Case renommée puis supprimée (vide) ; une case contenant des documents ne propose pas la suppression')
        case.locator('[data-history]').first.click()
        expect(page.locator('.modal .dv-layout')).to_be_visible()
        expect(page.locator('.modal')).to_contain_text('Document complémentaire')
        expect(page.locator('.modal #ops-version-upload')).to_be_visible()
        page.locator('#close-modal').click()
        checks.append('Document complémentaire : visionneuse, versions et actions de tout document')
        open_folder('bleu')
        page.fill('#dj-optional-title', 'Certificat d’origine (copie)'); page.click('#dj-optional-form button[value="later"]')
        expect(page.locator('.dj-optional-case', has_text='Certificat d’origine')).to_be_visible()
        restart()
        page.reload(); page.wait_for_load_state('networkidle')
        open_order(f'FIA-{tag}'); open_folder('rose')
        expect(page.locator('.dj-optional-case', has_text='Photos du prototype').locator('.dj-row')).to_have_count(2)
        checks.append('Persistance après redémarrage du serveur : cases et documents complémentaires conservés')
        page.click('#logout') if page.locator('#logout').count() else page.click('[data-fx-exit], .fx-exit')

        # ------------------------------------------------------------ 4. Recherche du technicien
        context.clear_cookies()
        login('tech.fiabilite@example.test', tech_pw)
        page.click('[data-view="launches"]')
        expect(page.locator('#ts-launches')).to_be_visible()
        page.fill('#ts-launches-q', 'atelier sud'); page.click('#ts-launches [type=submit]')
        results = page.locator('#ts-launches-results')
        expect(results).to_contain_text(f'FIA-{tag}'); expect(results).not_to_contain_text(f'VES-{tag}')
        expect(results.locator('.acc-folder-chip')).to_have_count(2)            # jaune et bleu uniquement
        page.screenshot(path=str(out / '03-recherche-technicien.png'))
        page.fill('#ts-launches-q', f'confidentiel {tag}'); page.click('#ts-launches [type=submit]')
        expect(results).to_contain_text('Aucune commande ni aucun document autorisé')
        page.fill('#ts-launches-q', f'SEC-{tag}'); page.click('#ts-launches [type=submit]')
        expect(results).to_contain_text('Aucune commande')
        page.fill('#ts-launches-q', ''); page.select_option('#ts-launches-folder', 'vert')
        expect(results).to_contain_text(f'VES-{tag}'); expect(results).not_to_contain_text(f'FIA-{tag}')
        page.click('#ts-launches [data-ts-reset]')
        expect(results).to_be_hidden(); expect(page.locator('#ops-launch-results')).to_be_visible()
        checks.append('Mes commandes : recherche par atelier (casse ignorée), aucun résultat sur une pièce ou une commande non autorisée, filtre « Sous-dossier vert » sans texte, réinitialisation')
        page.fill('#ts-launches-q', f'OF-{tag}'); page.select_option('#ts-launches-folder', 'bleu')
        expect(results).to_contain_text(f'FIA-{tag}')
        results.locator('[data-ts-open]').first.click()
        expect(page.locator('[data-folder-panel="bleu"]')).to_be_visible()
        expect(page.locator('h1')).to_have_text('Sous-dossier bleu')
        checks.append('Résultat avec sous-dossier sélectionné : ouverture directe du sous-dossier bleu autorisé')
        bleu_section = page.locator('[data-folder-panel="bleu"] .dj-optional-docs')
        expect(bleu_section).to_contain_text('Certificat d’origine')
        expect(bleu_section.locator('#dj-optional-form')).to_have_count(0)
        expect(bleu_section.locator('[data-optional-upload], [data-optional-edit], [data-optional-delete]')).to_have_count(0)
        assert all(f['optional_cases'] == [] for f in page.context.request.get(f'/api/launches/{lid}').json()['folders'] if f['slug'] == 'rose')
        page.click('[data-dj-folder="jaune"]')
        expect(page.locator('[data-folder-panel="jaune"] #dj-optional-form')).to_be_visible()
        checks.append('Technicien : case du bleu en lecture seule, aucune case du rose non attribué, création possible dans le jaune (dépôt autorisé)')
        page.click('[data-acc-view="myfolders"]')
        expect(page.locator('#ts-folders')).to_be_visible()
        page.fill('#ts-folders-q', 'gris anthracite'); page.click('#ts-folders [type=submit]')
        expect(page.locator('#ts-folders-results')).to_contain_text(f'FIA-{tag}')
        page.locator('#ts-folders-results [data-ts-open]').first.click()
        expect(page.locator('#ops-launch-summary')).to_be_visible()
        assert page.locator('h1').inner_text() in ('Sous-dossier jaune', 'Sous-dossier bleu')
        page.screenshot(path=str(out / '04-mes-sous-dossiers.png'))
        checks.append('Mes sous-dossiers : recherche par couleur, ouverture d’un sous-dossier réellement accessible')
        assert page.context.request.get(f"/api/launches/{secret['id']}").status in (403, 404)
        checks.append('Commande non attribuée : refusée par l’API (aucun contournement par l’URL)')

        # Refus attendus : la commande non attribuée (vérification de contournement) et, côté technicien,
        # les modules secondaires que son rôle ne couvre pas (signalés, sans bloquer la commande).
        expected = lambda status, url: (url.endswith(f"/api/launches/{secret['id']}") and status in (403, 404)) or (
            status == 403 and any(url.endswith(m) for m in ('/supplier-requests', '/client-publications', '/approval-overview', '/excel-inspections', '/materials')))
        unexpected = [(status, url) for status, url in refused if not expected(status, url)]
        (out / 'refus-http.json').write_text(json.dumps(refused, indent=1))
        assert not errors, errors
        assert not unexpected, unexpected
        checks.append(f'Aucune erreur JavaScript ni requête en échec inattendue ({len(refused)} refus de droits attendus, détaillés dans refus-http.json)')
        browser.close()
    return checks


if __name__ == '__main__':
    main()

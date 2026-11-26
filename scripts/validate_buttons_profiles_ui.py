"""Recette Chromium : boutons et requêtes par profil (clics réels).

    python scripts/validate_buttons_profiles_ui.py --output data/buttons-validation

Profils : administrateur, technicien lecture seule, technicien avec dépôt, responsable complet,
technicien à habilitations personnalisées. Pour chacun : ouverture de commande et des sous-dossiers
autorisés, ouverture de chaque document (visionneuse), Télécharger, Comparer, Commenter, Ajouter une
version, Déposer, Valider, onglets Contrôles / Communication / Historique, recherche et Filtrer ;
pour l'administrateur : historique global, Modifier la fiche, Enregistrer les habilitations,
corbeille. Échec si une action échoue, si une erreur JavaScript survient ou si une requête API
répond en erreur. Base temporaire, données de démonstration, comptes example.test.
"""
import argparse, json, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'buttons-validation'


def boot():
    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-boutons-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    __import__('recette_db').use_isolated_database()
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    from app.seed_operations_demo import seed
    import app.main  # noqa
    migrate()
    pw = secrets.token_urlsafe(18) + 'Aa1!'
    with SessionLocal() as db:
        u = User(name='Chef Boutons', email='chef.boutons@example.test', password_hash=hash_password(pw), roles=[Role(name='Administrateur')])
        db.add(u); db.commit(); ids = seed(db, u)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    srv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=os.environ.copy(),
                           stdout=(OUT / 'server.log').open('w'), stderr=subprocess.STDOUT)
    import httpx
    for _ in range(150):
        try:
            if httpx.get(f'http://127.0.0.1:{port}/api/health').status_code == 200: break
        except httpx.TransportError: time.sleep(.1)
    return srv, f'http://127.0.0.1:{port}', pw, ids


def make_user(base, admin_pw, name, email, assignments):
    import httpx
    H = {'X-Framatex-Request': '1'}
    with httpx.Client(base_url=base, headers=H) as c:
        c.post('/api/auth/login', json={'email': 'chef.boutons@example.test', 'password': admin_pw}).raise_for_status()
        r = c.post('/api/admin/collaborators', json={'name': name, 'email': email, 'job_title': 'Technicien'}); r.raise_for_status()
        body = r.json(); uid = body['collaborator']['id']
        for lid, folders in assignments.items():
            c.put(f'/api/admin/collaborators/{uid}/assignments/{lid}', json={'folders': folders}).raise_for_status()
    pw = secrets.token_urlsafe(16) + 'Aa1!'
    with httpx.Client(base_url=base, headers=H) as t:
        t.post('/api/auth/login', json={'email': email, 'password': body['temporary_password']}).raise_for_status()
        t.post('/api/account/password', json={'current_password': body['temporary_password'], 'new_password': pw}).raise_for_status()
    return pw



def pdf(text):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72, 90), text, fontsize=14); return d.tobytes()


def main():
    global OUT
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, default=OUT)
    OUT = parser.parse_args().output.resolve(); OUT.mkdir(parents=True, exist_ok=True)
    srv, base, pw, ids = boot()
    from playwright.sync_api import sync_playwright, expect
    log, errors, timings = [], [], []
    lids = list(ids.values())
    profiles = [('chef.boutons@example.test', pw)]
    profiles.append(('tech.lecture@example.test', make_user(base, pw, 'Tech Lecture', 'tech.lecture@example.test', {lids[0]: {'jaune': ['document.read']}})))
    profiles.append(('tech.depot@example.test', make_user(base, pw, 'Tech Depot', 'tech.depot@example.test', {lids[0]: {'jaune': ['document.read', 'document.write', 'document.version'], 'rose': ['document.read', 'document.write']}})))
    profiles.append(('tech.resp@example.test', make_user(base, pw, 'Tech Resp', 'tech.resp@example.test', {lids[0]: {s: ['document.read', 'document.download', 'document.write', 'document.version', 'document.comment', 'controls.read', 'impact.review', 'value.write', 'quality.review', 'document.review'] for s in ('jaune', 'rose', 'bleu', 'vert')}})))
    profiles.append(('tech.perso@example.test', make_user(base, pw, 'Tech Perso', 'tech.perso@example.test', {lids[0]: {'bleu': ['document.read', 'controls.read', 'document.download'], 'jaune': ['document.read', 'document.comment']}, lids[1]: {'vert': ['document.read']}})))
    try:
        with sync_playwright() as p:
            from windows_runtime import browser_executable
            browser = p.chromium.launch(executable_path=browser_executable())
            for email, password in profiles:
                who = email.split('@')[0]
                ctx = browser.new_context(base_url=base, viewport={'width': 1440, 'height': 900}, locale='fr-FR', accept_downloads=True)
                page = ctx.new_page()
                starts = {}
                page.on('pageerror', lambda e, w=who: errors.append((w, 'pageerror', str(e)[:300])))
                page.on('console', lambda m, w=who: errors.append((w, 'console', m.text[:300])) if m.type == 'error' and '401' not in m.text else None)
                page.on('request', lambda r: starts.__setitem__(r, time.perf_counter()))
                def done(r, w=who):
                    if r.request in starts:
                        timings.append((w, round((time.perf_counter() - starts.pop(r.request)) * 1000), r.request.method, r.url.split(':', 2)[2][5:][:90]))
                    if r.status >= 400 and '/api/' in r.url and not r.url.endswith('/auth/me'):
                        errors.append((w, r.status, r.request.method + ' ' + r.url.split(':', 2)[2][5:]))
                page.on('response', done)
                page.on('requestfailed', lambda r, w=who: errors.append((w, 'failed', r.method + ' ' + r.url + ' ' + str(r.failure))))
                def step(name, fn):
                    t0 = time.perf_counter()
                    try:
                        fn(); log.append(f'OK   [{who}] {name} ({round((time.perf_counter()-t0)*1000)} ms)')
                    except Exception as exc:
                        log.append(f'FAIL [{who}] {name} : {str(exc).splitlines()[0][:200]}')
                        page.screenshot(path=str(OUT / f'fail-{who}-{len(log)}.png'))
                        if page.locator('.modal').count(): page.keyboard.press('Escape')
                    toast = page.locator('#toast.visible')
                    if toast.count():
                        log.append(f'      toast: {toast.inner_text()[:150]}')
                page.goto('/espace-framatex'); page.fill('#email', email); page.fill('#password', password)
                page.click('#login-form [type=submit]'); page.wait_for_load_state('networkidle')

                def open_first():
                    page.click('[data-view="launches"]'); page.wait_for_load_state('networkidle')
                    page.locator('[data-ops-target]').first.click()
                    expect(page.locator('#ops-launch-summary')).to_be_visible(timeout=15000)
                step('ouvrir une commande', open_first)
                folders = [f for f in ('jaune', 'rose', 'bleu', 'vert') if page.locator(f'button.dj-folder[data-folder="{f}"]').count()]
                log.append(f'      sous-dossiers ouvrables : {folders}')
                for slug in folders:
                    def open_folder(slug=slug):
                        if not page.locator(f'button.dj-folder[data-folder="{slug}"]').count():
                            page.click('#dj-folders-back')
                        page.click(f'button.dj-folder[data-folder="{slug}"]')
                        expect(page.locator(f'[data-folder-panel="{slug}"]')).to_be_visible()
                    step(f'ouvrir sous-dossier {slug}', open_folder)
                    docs = page.locator(f'[data-folder-panel="{slug}"] [data-history]')
                    for k in range(min(docs.count(), 3)):
                        def open_doc(k=k):
                            page.locator(f'[data-folder-panel="{slug}"] [data-history]').nth(k).click()
                            expect(page.locator('.modal .dv-layout')).to_be_visible(timeout=10000)
                            expect(page.locator('.modal .dv-stage .fx-loading')).to_have_count(0, timeout=10000)
                            stage = page.locator('.modal .dv-stage').inner_text()[:80]
                            assert 'indisponible' not in stage, stage
                        step(f'{slug}: ouvrir document {k}', open_doc)
                        if page.locator('#ops-doc-download').count():
                            def dl():
                                with page.expect_download(timeout=10000) as d:
                                    page.click('#ops-doc-download')
                                assert d.value.suggested_filename
                            step(f'{slug}: télécharger', dl)
                        if page.locator('#ops-doc-compare').count():
                            step(f'{slug}: comparer', lambda: (page.click('#ops-doc-compare'), expect(page.locator('#ops-version-diff h3')).to_be_visible()))
                        if page.locator('#ops-comment-form').count():
                            def comment():
                                page.fill('#ops-comment', 'Commentaire de recette'); page.click('#ops-comment-form [type=submit]')
                                expect(page.locator('.modal .ops-comment', has_text='Commentaire de recette').first).to_be_visible()
                            step(f'{slug}: commenter', comment)
                        if page.locator('#ops-version-upload').count():
                            def version():
                                page.click('#ops-version-upload')
                                page.locator('#ops-file').set_input_files({'name': 'v.pdf', 'mimeType': 'application/pdf', 'buffer': pdf(f'Version {who} {time.time()}')})
                                expect(page.locator('#ops-analysis')).not_to_be_empty(timeout=15000)
                                if page.locator('#du-relationship-action').count():
                                    values = page.locator('#du-relationship-action option').evaluate_all('o => o.map(x => x.value)')
                                    page.select_option('#du-relationship-action', 'new_version' if 'new_version' in values else 'new_document')
                                if page.locator('#du-confirm-type').count(): page.check('#du-confirm-type')
                                page.click('#ops-upload-form [type=submit]')
                                expect(page.locator('#ops-upload-form')).to_have_count(0, timeout=15000)
                            step(f'{slug}: ajouter une version', version)
                        if page.locator('.modal').count(): page.keyboard.press('Escape')
                    if page.locator('#upload-doc').count():
                        def deposit(slug=slug):
                            page.click('#upload-doc')
                            page.fill('#ops-title', f'Pièce {who} {slug}')
                            page.locator('#ops-file').set_input_files({'name': f'{slug}.pdf', 'mimeType': 'application/pdf', 'buffer': pdf(f'Dépôt {who} {slug} {time.time()}')})
                            expect(page.locator('#ops-analysis')).not_to_be_empty(timeout=15000)
                            if page.locator('#ops-type').count() and not page.locator('#ops-type').input_value(): page.fill('#ops-type', 'Autre')
                            if page.locator('#du-relationship-action').count(): page.select_option('#du-relationship-action', 'new_document')
                            if page.locator('#du-confirm-type').count(): page.check('#du-confirm-type')
                            page.click('#ops-upload-form [type=submit]')
                            expect(page.locator('#ops-upload-form')).to_have_count(0, timeout=15000)
                            expect(page.locator('.dj-row', has_text=f'Pièce {who} {slug}')).to_be_visible()
                        step(f'{slug}: déposer', deposit)
                    validates = page.locator(f'[data-folder-panel="{slug}"] [data-complete-validate]')
                    if validates.count():
                        def validate():
                            validates.first.click(); page.wait_for_timeout(500)
                            if page.locator('.modal [type=submit]').count(): page.locator('.modal [type=submit]').first.click()
                            page.wait_for_load_state('networkidle')
                        step(f'{slug}: valider', validate)
                for tab in ('controles', 'communication', 'historique'):
                    def go_tab(tab=tab):
                        if page.locator('#dj-folders-back').count(): page.click('#dj-folders-back')
                        page.click(f'[data-dj-tab="{tab}"]')
                        expect(page.locator(f'#dj-panel-{tab}')).to_be_visible()
                        for j in range(page.locator(f'#dj-panel-{tab} [data-dj-module]').count()):
                            page.locator(f'#dj-panel-{tab} [data-dj-module]').nth(j).click()
                    step(f'onglet {tab}', go_tab)
                def search():
                    page.click('[data-view="launches"]'); page.wait_for_load_state('networkidle')
                    page.fill('#q', 'FR-DEMO'); page.click('#ops-launch-filters button[type=submit]'); page.wait_for_load_state('networkidle')
                    assert page.locator('[data-ops-target]').count() >= 1
                step('recherche / filtrer commandes', search)
                if email.startswith('chef'):
                    def history():
                        page.click('[data-ops-view="audit"]') if page.locator('[data-ops-view="audit"]').count() else page.click('[data-view="audit"]')
                        expect(page.locator('#ops-audit-form')).to_be_visible(); page.click('#ops-audit-form [type=submit]')
                        expect(page.locator('#ops-audit-results .hist-list, #ops-audit-results .ops-empty').first).to_be_visible()
                    step('historique global + filtrer', history)
                    def sheet():
                        open_first(); page.click('#fx-sheet-edit') if page.locator('#fx-sheet-edit').count() else page.get_by_role('button', name='Modifier la fiche').click()
                        page.locator('.modal [type=submit]').click(); page.wait_for_load_state('networkidle')
                    step('modifier la fiche', sheet)
                    def rights():
                        open_first(); page.click('#acc-assign'); expect(page.locator('.acc-matrix')).to_be_visible(); page.click('#acc-matrix-save')
                        expect(page.locator('.acc-matrix')).to_have_count(0)
                    step('enregistrer les habilitations', rights)
                    def trash():
                        page.click('[data-ops-view="trash"]'); page.wait_for_load_state('networkidle')
                    step('corbeille', trash)
                ctx.close()
            browser.close()
    finally:
        srv.terminate()
    (OUT / 'journal.txt').write_text('\n'.join(log))
    failures = [line for line in log if line.startswith('FAIL')]
    slow = sorted(timings, key=lambda t: -t[1])[:10]
    (OUT / 'results.json').write_text(json.dumps({'actions': sum(l.startswith('OK') for l in log), 'failures': failures,
                                                  'errors': errors, 'slowest_ms': slow}, ensure_ascii=False, indent=1))
    print('\n'.join(l for l in log if not l.startswith('      toast')))
    assert not failures, failures
    assert not errors, errors
    print(f"{sum(l.startswith('OK') for l in log)} actions réussies, 0 erreur JavaScript, 0 requête API en échec ; requête la plus lente : {slow[0][1]} ms")

if __name__ == '__main__':
    main()

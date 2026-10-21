"""Real click-through acceptance, disposable DB, no real user data.

    python scripts/demo_browser_full.py --output data/demo-browser

Same complete suite as demo_full_platform.py (API + Chromium + runtime T+60).
No browser dependency/launch failure is converted into a successful skipped run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets


def nav(page, view):
    if page.locator('#close-modal').count():
        page.locator('#close-modal').click()
    if page.viewport_size['width'] <= 820 and not page.locator('.drawer-open').count():
        page.locator('.ops-drawer-toggle').click()
    old_main = page.locator('main').element_handle()
    page.locator(f'.sidebar [data-ops-view="{view}"], .sidebar [data-view="{view}"]').first.click()
    # Same-view navigation leaves the *old* heading visible during fetch. A
    # previously reached networkidle state is not a render barrier: require the
    # old main node to be detached before interacting with the next generation.
    old_main.wait_for_element_state('hidden', timeout=15000)
    expected = {'home': 'Tableau de bord', 'launches': 'Commandes et lancements', 'search': 'Recherche documentaire',
                'audit': 'Historique et audit', 'experience': 'Mémoire d’expérience interne', 'clients': 'Clients et demandes'}
    if view in expected:
        from playwright.sync_api import expect
        expect(page.locator('.ops-heading h1')).to_have_text(expected[view])


def internal_journey(qa, browser, base, password, ids, captures):
    from playwright.sync_api import expect
    from demo_full_platform import Browser, internal_login
    import qa_platform_review as files
    view = Browser(browser, base, 1440, captures)
    page = view.page
    internal_login(view, 'recette@framatex.test', password)

    def run(label, fn):
        before = len(qa.results)
        qa.run('Navigateur FRAMATEX', label, fn)
        if not qa.results[-1]['ok']:
            page.screenshot(path=str(captures / f'echec-interne-{before}.png'), full_page=True)
            (captures / f'echec-interne-{before}.html').write_text(page.content(), encoding='utf-8')

    def open_folder(launch_id):
        nav(page, 'launches')
        # KPI clicks intentionally persist their completion filter. Explicitly
        # return to all dossiers rather than silently expecting an excluded row.
        page.select_option('#ops-launch-filters #completion', '')
        page.locator('#ops-launch-filters button[type=submit]').click()
        ref = view.context.request.get(base + f'/api/launches/{launch_id}').json()['order_ref']
        page.locator('#ops-launch-results tr', has_text=ref).locator('[data-ops-target]').click()
        expect(page.locator('#ops-launch-summary')).to_contain_text(ref)
        expect(page.locator('.folder-card')).to_have_count(4)

    def upload(name, blob, title, kind, analyze=False):
        page.locator('#upload-doc').click()
        page.locator('#ops-file').set_input_files({'name': name, 'mimeType': 'application/octet-stream', 'buffer': blob})
        page.fill('#ops-title', title); page.fill('#ops-type', kind)
        page.fill('#ops-upload-comment', 'Commentaire interne recette navigateur — ne jamais publier.')
        if analyze:
            page.locator('#ops-analyze').click()
            expect(page.locator('#ops-analysis')).to_contain_text('Calcul du besoin', timeout=20000)
        page.locator('#ops-upload-form button[type=submit]').click()
        expect(page.locator('.detail-layout')).to_contain_text(title, timeout=15000)
        row = page.locator('.detail-layout tbody tr', has_text=title)
        row.locator('[data-history]').click()
        expect(page.locator('.modal')).to_contain_text(hashlib.sha256(blob).hexdigest())

    def dashboard():
        nav(page, 'home')
        data = view.context.request.get(base + '/api/workspace/dashboard').json()
        for key, value in data['kpis'].items():
            element = page.locator(f'[data-ops-kpi="{key}"] strong')
            if element.count():
                expect(element).to_have_text(str(value))
        for section in ('#ops-priorities', '#ops-missing', '#ops-concerns'):
            nav(page, 'home')
            total = page.locator(section + ' [data-ops-target]').count()
            assert total > 0, section
            for index in range(total):
                if index:
                    nav(page, 'home')
                button = page.locator(section + ' [data-ops-target]').nth(index)
                expect(button).to_be_visible()
                target = json.loads(button.get_attribute('data-ops-target'))
                expected = view.context.request.get(base + f'/api/launches/{target["launch_id"]}').json()
                button.click()
                expect(page.locator('#ops-launch-summary')).to_contain_text(expected['order_ref'], timeout=15000)
                if target.get('folder'):
                    expect(page.locator(f'.folder-card.selected[data-folder="{target["folder"]}"]')).to_be_visible()
                page.locator('#close-modal').click() if page.locator('#close-modal').count() else None
        for key in ('active_launches', 'complete_launches', 'incomplete_launches', 'pending_documents'):
            nav(page, 'home'); page.locator(f'[data-ops-kpi="{key}"]').click()
            expect(page.locator('main')).not_to_contain_text('Chargement de l’espace documentaire')
        open_folder(ids['B'])
        for slug in ('jaune', 'rose', 'bleu', 'vert', 'jaune'):
            page.locator(f'.folder-card[data-folder="{slug}"]').click()
            expect(page.locator(f'.folder-card.selected[data-folder="{slug}"]')).to_be_visible()
        view.check_page('recette-dashboard-et-dossiers')
    run('KPI réels, actions prioritaires/manquants/alertes cliquables et quatre sous-dossiers', dashboard)

    title = 'Fiche emploi navigateur ' + secrets.token_hex(3)
    def document_versions():
        open_folder(ids['B'])
        upload('fiche-v1.txt', b'Fiche emploi navigateur version 1', title, 'Fiche d’emploi')
        for number in (2, 3):
            page.locator('#ops-new-version').set_input_files({'name': f'fiche-v{number}.txt', 'mimeType': 'text/plain', 'buffer': f'Fiche emploi navigateur version {number}'.encode()})
            page.fill('#ops-version-comment', f'Commentaire de révision V{number}')
            page.locator('#ops-version-form button[type=submit]').click()
            expect(page.locator('.modal')).to_contain_text(f'Commentaires internes · V{number}')
        page.fill('#ops-comment', 'Note privée finale de la recette navigateur.')
        page.locator('#ops-comment-form button[type=submit]').click()
        expect(page.locator('.modal')).to_contain_text('Note privée finale')
        expect(page.locator('[data-ops-version]')).to_have_count(3)
        page.locator('[data-ops-version]').last.click()
        expect(page.locator('.modal')).to_contain_text('Commentaires internes · V1')
        with page.expect_download() as event:
            page.locator('#ops-doc-download').click()
        assert Path(event.value.path()).read_bytes() == b'Fiche emploi navigateur version 1'
        page.locator('#close-modal').click()
        review = page.locator('.workflow-review-table tr', has_text=title)
        review.locator('[data-document-review]').click()
        page.locator('#decision-status').select_option('approved')
        page.fill('#decision-comment', 'Version 3 vérifiée humainement pendant la recette.')
        page.locator('#decision-form button[type=submit]').click()
        expect(page.locator('.workflow-review-table tr', has_text=title)).to_contain_text('Approuvé')
        page.locator('[data-impact-review]').first.click()
        page.select_option('#impact-status', 'acknowledged')
        page.fill('#impact-note', 'Calcul du besoin et fiche de prix examinés par le responsable.')
        page.locator('#impact-form button[type=submit]').click()
        expect(page.locator('.workflow-root')).to_contain_text('Pris en compte')
        view.check_page('recette-documents-versions')
    run('Dépôt, SHA-256, V1/V2/V3, commentaire, téléchargement V1, validation et impact par clics', document_versions)

    def quality_excel():
        open_folder(ids['E'])
        # The API recipe deliberately leaves E with incompatible units. Produce
        # a new comparable source version via the UI; never overwrite its datum
        # or fake an available decision on a unit_mismatch row.
        report = view.context.request.get(base + f'/api/launches/{ids["E"]}/quality').json()
        rule = next(row for row in report['rows'] if row['pair'])
        source = rule['pair'][0]
        page.locator(f'.detail-layout [data-history="{source["document_id"]}"]').click()
        page.locator('#ops-new-version').set_input_files({'name': 'provisoire-comparable.txt', 'mimeType': 'text/plain', 'buffer': b'Quantite : 1800 pieces, releve navigateur'})
        with page.expect_response(lambda response: response.request.method == 'POST' and '/versions' in response.url) as updated:
            page.locator('#ops-version-form button[type=submit]').click()
        version = updated.value.json()['latest']
        expect(page.locator('.modal')).to_contain_text(f'Commentaires internes · V{version["number"]}')
        page.locator('#close-modal').click()
        page.locator('#quality-add-data').click()
        page.select_option('#qd-version', version['id'])
        page.select_option('#qd-field', rule['field_key'])
        page.fill('#qd-value', '1800'); page.fill('#qd-unit', 'pièce')
        page.locator('#quality-data-form button[type=submit]').click()
        page.locator('[data-quality-decision]').first.click()
        page.select_option('#qdec-type', 'to_correct')
        page.fill('#qdec-note', 'Écart examiné dans le navigateur, correction demandée au responsable.')
        page.locator('#qdec-form button[type=submit]').click()
        expect(page.locator('.quality-root')).to_contain_text('Correction demandée')
        title = 'Calcul Excel navigateur'
        cells = {'A1': 10, 'B1': '=A1*2', 'B2': '=SUM(B1:B1)'}
        upload('besoin.xlsx', files.xlsx_bytes(cells), title, 'Calcul du besoin')
        for number, values in enumerate(({**cells, 'B1': '=A1*3'}, {**cells, 'B1': 30}, {**cells, 'B2': '=SUM(#REF!)'}), 2):
            page.locator('#ops-new-version').set_input_files({'name': 'besoin.xlsx', 'mimeType': 'application/octet-stream', 'buffer': files.xlsx_bytes(values)})
            page.locator('#ops-version-form button[type=submit]').click()
            expect(page.locator('.modal')).to_contain_text(f'Commentaires internes · V{number}')
        page.locator('#close-modal').click()
        expect(page.locator('.quality-root')).to_contain_text('#REF!')
        view.check_page('recette-coherence-excel')
    run('Cohérence : décision humaine ; Excel initial, formule changée, constante et #REF! déposés via interface', quality_excel)

    def ocr_and_eml():
        open_folder(ids['B'])
        image = files.image_bytes('PNG', 'CALCUL DU BESOIN\nQuantite : 1800 pieces')
        before = view.context.request.get(base + f'/api/launches/{ids["B"]}').json()
        page.locator('#intake-open').click()
        page.locator('#intake-file').set_input_files({'name': 'calcul.png', 'mimeType': 'image/png', 'buffer': image})
        page.locator('#intake-file-form button[type=submit]').click()
        expect(page.locator('#intake-result')).to_contain_text('image_ocr', timeout=20000)
        expect(page.locator('#intake-result')).to_contain_text('1800')
        after = view.context.request.get(base + f'/api/launches/{ids["B"]}').json()
        assert sum(len(f['documents']) for f in before['folders']) == sum(len(f['documents']) for f in after['folders'])
        page.fill('#intake-title', 'Calcul OCR confirmé par le navigateur')
        page.locator('#intake-confirm-form button[type=submit]').click()
        expect(page.locator('.detail-layout')).to_contain_text('Calcul OCR confirmé par le navigateur')
        page.locator('.detail-layout tr', has_text='Calcul OCR confirmé par le navigateur').locator('[data-history]').click()
        page.locator('#ops-doc-intake').click()
        expect(page.locator('[data-intake-confirm="quantite"]')).to_be_visible(timeout=20000)
        page.locator('[data-intake-confirm="quantite"]').click()
        expect(page.locator('.modal')).to_contain_text('quantite : 1800')
        page.locator('#close-modal').click()
        page.locator('#mail-import').click()
        message_bytes = files.eml_bytes().replace(b'Nous confirmons la livraison du lot pour le', b'Nous livrerons le lot le')
        page.locator('#mail-upload-file').set_input_files({'name': 'confirmation-ui.eml', 'mimeType': 'message/rfc822', 'buffer': message_bytes})
        page.locator('#mail-upload-form button[type=submit]').click()
        expect(page.locator('.mail-section')).to_contain_text('Confirmation delai lot 0143')
        message = page.locator('.mail-section .mail-item', has_text='Confirmation delai lot 0143').first
        message.locator('[data-mail-show]').click()
        expect(page.locator('.modal')).to_contain_text('atelier@exemple.test')
        expect(page.locator('.modal')).to_contain_text('Tue, 20 Oct 2026')
        page.locator('#mail-close').click()
        message.locator('[data-mail-suggest]').click()
        page.locator('[data-mail-accept]').first.click()
        page.locator('#mail-commit-form button[type=submit]').click()
        expect(page.locator('.mail-section')).to_contain_text('atelier@exemple.test')
        view.check_page('recette-ocr-email')
    run('OCR image, absence de dépôt automatique, confirmation classement/champ, EML sujet/expéditeur/date et engagement', ocr_and_eml)

    def search_audit_memory():
        nav(page, 'search')
        page.fill('#ops-search-form #q', title)
        page.locator('#ops-search-form button[type=submit]').click()
        expect(page.locator('#ops-search-results')).to_contain_text(title)
        page.locator('#ops-search-results [data-ops-target]').first.click()
        expect(page.locator('.modal')).to_contain_text(title)
        page.locator('#close-modal').click()
        page.locator('#ops-add-note').click()
        page.select_option('#ops-party-type', 'atelier')
        page.fill('#ops-party-name', 'Atelier recette navigateur')
        page.fill('#ops-note', 'Retour interne confidentiel saisi via les écrans, jamais transmis au client.')
        page.locator('#ops-note-form button[type=submit]').click()
        expect(page.locator('#ops-notes')).to_contain_text('Retour interne confidentiel')
        nav(page, 'experience')
        page.fill('#ops-experience-form #q', 'Atelier recette navigateur')
        page.locator('#ops-experience-form button[type=submit]').click()
        expect(page.locator('#ops-experience-results')).to_contain_text('Retour interne confidentiel')
        page.locator('#ops-experience-results [data-ops-target]').first.click()
        expect(page.locator('#ops-launch-summary')).to_be_visible()
        nav(page, 'audit')
        page.fill('#ops-audit-form #action', 'document.version.add')
        page.locator('#ops-audit-form button[type=submit]').click()
        expect(page.locator('#ops-audit-results')).to_contain_text('Nouvelle version')
        view.check_page('recette-audit')
    run('Recherche ouvrant la bonne version, mémoire atelier et audit filtré par action, via formulaires', search_audit_memory)
    qa.check('Navigateur FRAMATEX', 'Aucune erreur JS sur les parcours fonctionnels', not view.errors, view.errors)
    view.close()


def workflow_journey(qa, browser, base, password, captures):
    # Reuse the full, already shipped A/B document workflow without weakening it.
    # Separate contexts prevent cookie mixing. This includes actual file upload,
    # correction, V2, acceptance, share/download/revoke and suspended account UI.
    import validate_client_workflow_ui as workflow
    qa.run('Navigateur Client', 'Cycle documentaire complet A/B, correction V2, partage/retrait et compte suspendu (15 étapes)',
           lambda: workflow.run_browser(captures, base, 'recette@framatex.test', password, {}, browser=browser))


def failure_journey(qa, browser, base):
    """Independently reproduce the infinite loader; then prove recovery by click.
    Expected failures are kept in separate contexts, never ignored on real paths.
    """
    from playwright.sync_api import expect
    for kind in ('api_hung', 'api_500', 'script_mime', 'script_missing'):
        def check(kind=kind):
            context = browser.new_context()
            page = context.new_page()
            held = []
            try:
                if kind == 'api_hung':
                    page.route('**/api/auth/me', lambda route: held.append(route))  # intentionally unresolved
                elif kind == 'api_500':
                    page.route('**/api/auth/me', lambda route: route.fulfill(status=500, content_type='application/json', body='{}'))
                elif kind == 'script_mime':
                    page.route('**/assets/app.js*', lambda route: route.fulfill(content_type='text/plain', body="throw new Error('must not execute')"))
                else:
                    page.route('**/assets/app.js*', lambda route: route.abort('failed'))
                page.goto(base + '/espace-framatex', wait_until='domcontentloaded')
                expect(page.locator('#boot-retry')).to_be_visible(timeout=13000)
                expect(page.locator('#app')).to_contain_text('Impossible de joindre le serveur FRAMATEX.')
                assert 'Chargement de l’espace documentaire' not in page.locator('#app').inner_text()
                for route in held:
                    route.abort('timedout')
                held.clear()
                page.unroute_all(behavior='wait')
                page.locator('#boot-retry').click()
                expect(page.locator('#login-form')).to_be_visible(timeout=15000)
            finally:
                for route in held:
                    try:
                        route.abort('timedout')
                    except Exception:
                        pass
                page.unroute_all(behavior='ignoreErrors')
                context.close()
        qa.run('Navigateur résilience', kind + ' : écran borné et bouton Réessayer fonctionnel', check)


def run_browser_suite(qa, ctx, captures):
    from playwright.sync_api import sync_playwright
    from windows_runtime import browser_executable
    from demo_full_platform import full_journey, width_tour
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_executable(), headless=True)
        try:
            email, secret = full_journey(qa, browser, ctx.base, ctx.password, captures)
            internal_journey(qa, browser, ctx.base, ctx.password, ctx.ids, captures)
            workflow_journey(qa, browser, ctx.base, ctx.password, captures)
            width_tour(qa, browser, ctx.base, ctx.password, email, secret, captures)
            failure_journey(qa, browser, ctx.base)
        finally:
            browser.close()


if __name__ == '__main__':
    from demo_full_platform import main
    main()

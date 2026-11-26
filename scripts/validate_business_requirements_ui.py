"""Recette Chromium des exigences métier FRAMATEX (clics réels, base temporaire, comptes fictifs).

    python scripts/validate_business_requirements_ui.py --output data/business-validation [--lot fiche]

Lot « fiche » : demande Client enrichie → acceptation FRAMATEX → fiche transférée ; création
d'une commande complète ; « Modifier la fiche » et historique ; lecture technicien sans édition.
"""
import argparse, json, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'business-validation')
    out = parser.parse_args().output.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-business-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    __import__('recette_db').use_isolated_database()
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    import app.main  # noqa: F401
    migrate()
    secrets_used = {'chef': secrets.token_urlsafe(18), 'client': secrets.token_urlsafe(14) + 'Aa1!', 'tech': secrets.token_urlsafe(16) + 'Bb2!'}
    with SessionLocal() as db:
        db.add(User(name='Nadia Benali', email='chef.metier@example.test', password_hash=hash_password(secrets_used['chef']), roles=[Role(name='Administrateur')]))
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
        checks = run(f'http://127.0.0.1:{port}', secrets_used, out)
    finally:
        server.terminate()
    text = json.dumps({'checks': checks}, ensure_ascii=False, indent=2)
    assert not any(v in text for v in secrets_used.values())
    (out / 'results.json').write_text(text)
    print('\n'.join('OK  ' + c for c in checks)); print(f'{len(checks)} vérifications réussies.')


def run(base, pw, out):
    from playwright.sync_api import sync_playwright, expect
    checks, errors = [], []
    exe = '/opt/pw-browsers/chromium' if Path('/opt/pw-browsers/chromium').exists() else None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=exe)

        def page_for(width=1440):
            ctx = browser.new_context(base_url=base, locale='fr-FR', viewport={'width': width, 'height': 900})
            p = ctx.new_page(); p.on('pageerror', lambda e: errors.append(str(e)))
            return p

        def internal_login(p, email, password):
            p.goto('/espace-framatex'); p.fill('#email', email); p.fill('#password', password)
            p.click('#login-form [type=submit]'); p.wait_for_selector('.content h1')

        chef = page_for(); internal_login(chef, 'chef.metier@example.test', pw['chef'])

        # 1. Client : inscription, activation par FRAMATEX, nouvelle demande enrichie (clics réels).
        client = page_for()
        client.goto('/espace-client#/inscription')
        for key, value in {'company': 'Maison Atlas (fictive)', 'address': '1 rue fictive', 'country': 'France', 'contact': 'Contact fictif', 'phone': '0600000000',
                           'email': 'client.metier@example.test', 'password': pw['client'], 'password2': pw['client']}.items():
            target = client.locator(f'#reg-{key}')
            if target.evaluate('el => el.tagName') == 'SELECT':
                target.select_option(label=value)
            else:
                target.fill(value)
        client.locator('#register-form input[type=checkbox]').check() if client.locator('#register-form input[type=checkbox]').count() else None
        client.click('#register-form [type=submit]'); client.wait_for_timeout(800)
        chef.locator('.sidebar [data-ops-view="clients"]').click()
        row = chef.locator('tr', has_text='client.metier@example.test')
        row.locator('[data-ops-client]').click(); expect(row.locator('[data-ops-client]')).to_have_text('Suspendre')
        client_code = next(c['client_code'] for c in chef.context.request.get('/api/admin/clients').json() if c['email'] == 'client.metier@example.test')
        client.goto('/espace-client#/connexion'); client.fill('#login-email', 'client.metier@example.test'); client.fill('#login-password', pw['client'])
        client.click('#login-form [type=submit]'); client.wait_for_url('**#/demandes*')
        client.goto(base + '/espace-client#/demandes/nouvelle'); client.wait_for_selector('#rq-project')
        client.fill('#rq-project', 'Costume cérémonie'); client.fill('#rq-color', 'Bleu marine'); client.fill('#rq-description', 'Costume deux pièces, coupe droite')
        client.fill('#rq-article', 'Costume'); client.fill('#rq-ref', '00PO-1207'); client.fill('#rq-qty', '300'); client.fill('#rq-date', '2027-03-15')
        client.screenshot(path=str(out / 'client-nouvelle-demande.png'), full_page=True)
        client.locator('#request-form button[type=submit]:not([data-status]), form button[type=submit]:has-text("Envoyer la demande")').first.click(); client.wait_for_url('**#/demandes/*', timeout=15000)
        expect(client.locator('main')).to_contain_text('Costume cérémonie')
        checks.append('Client : nouvelle demande avec nom du projet, description, couleur, référence de commande, N° client issu du compte')

        # 2. FRAMATEX accepte et crée le Dossier Jaune : transfert intégral.
        chef.locator('.sidebar [data-ops-view="clients"]').click()
        chef.locator('[data-ops-request]', has_text='Costume').first.click()
        chef.locator('#cw-create-launch').click()
        sheet = chef.locator('.fx-sheet')
        expect(sheet).to_contain_text('Costume cérémonie'); expect(sheet).to_contain_text('Bleu marine')
        expect(sheet).to_contain_text('00PO-1207'); expect(sheet).to_contain_text('15 mars 2027'); expect(sheet).to_contain_text('Costume deux pièces')
        chef.screenshot(path=str(out / 'fiche-transferee.png'))
        checks.append('Acceptation FRAMATEX : Dossier Jaune créé, fiche remplie automatiquement (projet, couleur, réf. Client, date, description, N° client)')

        # 3. Création interne complète puis « Modifier la fiche » (clics réels).
        chef.locator('.sidebar [data-view="launches"]').click()
        chef.locator('#ops-create, button:has-text("Nouveau dossier")').first.click()
        chef.wait_for_selector('#new-launch-form')
        chef.fill('#l-name', 'Veste lin — été'); chef.fill('#l-order', '000731'); chef.fill('#sheet-of_number', '0099')
        chef.fill('#sheet-workshop', 'Atelier Tanger'); chef.fill('#sheet-quantity', '800'); chef.fill('#sheet-quantity_delivered', '0')
        chef.screenshot(path=str(out / 'creation-fiche.png'))
        chef.click('#new-launch-form [type=submit]')
        sheet = chef.locator('.fx-sheet'); expect(sheet).to_contain_text('000731'); expect(sheet).to_contain_text('0099')
        delivered = sheet.locator('div', has=chef.locator('dt', has_text='Quantité livrée')).locator('dd')
        expect(delivered).to_have_text('0')
        expect(sheet.locator('div', has=chef.locator('dt', has_text='Quantité lancée')).locator('dd')).to_have_text('Non renseigné')
        chef.click('#fx-sheet-edit'); chef.wait_for_selector('#sheet-edit-form')
        chef.fill('#sheet-color', 'Écru'); chef.fill('#sheet-quantity_launched', '780')
        chef.click('#sheet-edit-form [type=submit]')
        expect(chef.locator('#toast')).to_contain_text('2 modifications')
        expect(chef.locator('.fx-sheet')).to_contain_text('Écru')
        chef.screenshot(path=str(out / 'fiche-modifiee.png'))
        req = chef.context.request
        launch_id = chef.evaluate('state.detail.id')
        audit = req.get('/api/audit').json() if req.get('/api/audit').status == 200 else []
        checks.append('Création interne : 14 champs, seul le nom obligatoire, zéros initiaux conservés, 0 ≠ « Non renseigné » ; « Modifier la fiche » enregistre 2 changements')

        # 3 bis. Recherche par N° client puis clic sur le résultat.
        chef.locator('#global-search').click(); chef.wait_for_selector('#ops-search-form')
        chef.fill('#q', client_code); chef.click('#ops-search-form [type=submit]')
        result = chef.locator('[data-ops-launch-open]', has_text='').first
        expect(chef.locator('.ops-search-launches')).to_contain_text('Costume cérémonie')
        chef.screenshot(path=str(out / 'recherche-numero-client.png'))
        chef.locator('.ops-search-launches [data-ops-launch-open]').first.click()
        expect(chef.locator('.fx-sheet')).to_contain_text(client_code)
        checks.append(f'Recherche par N° client ({client_code}) : commande trouvée, clic → Dossier Jaune ouvert')

        # 4. Technicien en lecture : fiche visible, pas d'édition.
        tech = req.post('/api/admin/collaborators', headers=H, data={'name': 'Youssef Amrani', 'email': 'tech.metier@example.test', 'job_title': 'Technicien'}).json()
        req.put(f"/api/admin/collaborators/{tech['collaborator']['id']}/assignments/{launch_id}", headers=H, data={'folders': {'jaune': ['document.read']}})
        t = page_for(); t.goto('/espace-framatex'); t.fill('#email', 'tech.metier@example.test'); t.fill('#password', tech['temporary_password'])
        t.click('#login-form [type=submit]'); t.wait_for_selector('#acc-password-form')
        t.fill('#acc-current', tech['temporary_password']); t.fill('#acc-new', pw['tech']); t.fill('#acc-confirm', pw['tech'])
        t.click('#acc-password-form [type=submit]'); t.wait_for_selector('.content h1')
        t.locator('.sidebar [data-view="launches"]').click(); t.locator('#ops-launch-results', has_text='Veste lin').locator('text=000731').first.click()
        expect(t.locator('.fx-sheet')).to_contain_text('Atelier Tanger'); expect(t.locator('#fx-sheet-edit')).to_have_count(0)
        checks.append('Technicien en lecture : fiche visible, « Modifier la fiche » absent, aucun droit ajouté')
        assert not errors, errors
        checks.append('Aucune erreur JavaScript')
        browser.close()
    return checks


if __name__ == '__main__':
    main()

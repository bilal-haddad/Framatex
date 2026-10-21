"""Scénario Client ↔ FRAMATEX complet, base et comptes de recette éphémères.

python scripts/validate_client_workflow_ui.py --output /workspace/artifacts/client-workflow
Réutilise le démarrage/arrêt isolé du runner de recette existant.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import validate_internal_ui as harness


def run_browser(output, base_url, email, password, ids):
    from playwright.sync_api import expect, sync_playwright
    report = {'status': 'running', 'tested_at': datetime.now(timezone.utc).isoformat(),
              'run_id': secrets.token_hex(8), 'checks': [], 'screenshots': [], 'errors': [],
              'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=harness.ROOT, text=True).strip(),
              'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=harness.ROOT, text=True).strip())}
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    headers = {'X-Framatex-Request': '1'}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('google-chrome'),
                                    headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        internal = browser.new_context(base_url=base_url, locale='fr-FR', timezone_id='Africa/Casablanca')
        client_a = browser.new_context(base_url=base_url, locale='fr-FR', timezone_id='Africa/Casablanca')
        client_b = browser.new_context(base_url=base_url, locale='fr-FR', timezone_id='Africa/Casablanca')
        admin, client = internal.new_page(), client_a.new_page()
        for page in (admin, client):
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
        admin.set_viewport_size({'width': 1440, 'height': 1000})
        client.set_viewport_size({'width': 1440, 'height': 1000})

        def check(label):
            report['checks'].append(label)
            print(label + ' : OK', flush=True)

        def capture(page, label):
            page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            filename = label + '.png'
            page.screenshot(path=str(output / filename), full_page=True, animations='disabled')
            report['screenshots'].append(filename)

        admin.goto('/espace-framatex')
        admin.locator('#email').fill(email)
        admin.locator('#password').fill(password)
        admin.locator('#login-form button[type=submit]').click()
        expect(admin.locator('.ops-heading h1')).to_have_text('Tableau de bord')
        client.goto('/espace-client#/inscription')
        for key, value in {'company': 'Entreprise Client A', 'address': '1 adresse fictive', 'contact': 'Contact Client A',
                           'phone': '0600000000', 'email': 'workflow-a@example.test',
                           'password': password, 'password2': password}.items():
            client.locator('#reg-' + key).fill(value)
        client.locator('#reg-country').select_option('Maroc')
        client.locator('#register-form button[type=submit]').click()
        expect(client.locator('h1')).to_contain_text('Votre demande de compte a bien été enregistrée')
        account_a = next(c for c in internal.request.get('/api/admin/clients').json() if c['email'] == 'workflow-a@example.test')
        client.goto('/espace-client#/connexion')
        client.locator('#login-email').fill(account_a['email']); client.locator('#login-password').fill(password)
        client.locator('#login-form button[type=submit]').click()
        expect(client.locator('h1')).to_contain_text('en attente de validation')
        admin.evaluate("navigate('clients')")
        admin.locator(f'[data-ops-client="{account_a["id"]}"]').click()
        expect(admin.locator(f'[data-ops-client="{account_a["id"]}"]')).to_have_text('Suspendre')
        client.goto('/espace-client#/connexion')
        client.locator('#login-email').fill(account_a['email']); client.locator('#login-password').fill(password)
        client.locator('#login-form button[type=submit]').click()
        expect(client.locator('h1')).to_have_text('Mes demandes')
        check('Inscription, message pending et activation via comptes internes existants')

        client.goto('/espace-client#/demandes/nouvelle')
        client.locator('#rq-article').fill('Chemise Oxford workflow final')
        client.locator('#rq-qty').fill('1200'); client.locator('#rq-date').fill('2027-02-01')
        client.locator('#request-form button[type=submit]').filter(has_text='Envoyer la demande').click()
        expect(client.locator('h1')).to_have_text('Chemise Oxford workflow final')
        expect(client.locator('.side-status')).to_have_text('Envoyée')
        order_id = client.evaluate('location.hash.split("/").at(-1)')
        admin.evaluate("navigate('clients')")
        admin.locator(f'[data-ops-request="{order_id}"]').click()
        admin.locator('#cw-order-status').select_option('under_review')
        admin.locator('#cw-order-status-form button[type=submit]').click()
        expect(admin.locator('#cw-order-status-form')).to_be_visible()
        assert client_a.request.get('/api/client/order-requests/' + order_id).json()['status'] == 'under_review'
        check('1–2 : création de demande puis étude FRAMATEX')

        admin.locator('#cw-ask-document').click()
        admin.locator('#cw-title').fill('Dossier technique')
        admin.locator('#cw-description').fill('Préciser la référence tissu et les tailles du modèle.')
        admin.locator('#cw-ask-form button[type=submit]').click()
        expect(admin.locator('.modal')).to_contain_text('Dossier technique')
        item = internal.request.get(f'/api/admin/clients/{account_a["id"]}/document-requests',
                    params={'order_request_id': order_id}).json()[0]
        client.goto('/espace-client#/documents-demandes')
        client.locator(f'a[href="#/documents-demandes/{item["id"]}"]').first.click()
        expect(client.locator('#requested-detail')).to_contain_text('À déposer')
        client.locator('#requested-file').set_input_files({'name': 'technique-v1.txt', 'mimeType': 'text/plain', 'buffer': b'Technique version 1'})
        client.locator('#requested-upload-form button[type=submit]').click()
        expect(client.locator('#requested-detail .card-head .badge')).to_have_text('Déposé')
        check('3–5 : demande documentaire visible et dépôt V1 par le Client A')

        admin.evaluate('(id)=>operationsClientRequest(id)', order_id)
        admin.locator(f'[data-client-doc-decision="{item["id"]}"][data-status="under_review"]').click()
        admin.locator('#cw-review-form button[type=submit]').click()
        expect(admin.locator('.modal')).to_contain_text('En vérification')
        admin.locator(f'[data-client-doc-decision="{item["id"]}"][data-status="correction_required"]').click()
        admin.locator('#cw-message').fill('Merci de préciser la composition et la référence matière.')
        admin.locator('#cw-review-form button[type=submit]').click()
        expect(admin.locator('.modal')).to_contain_text('À corriger')
        client.reload()
        expect(client.locator('#requested-detail')).to_contain_text('Merci de préciser la composition')
        client.locator('#requested-file').set_input_files({'name': 'technique-v2.txt', 'mimeType': 'text/plain', 'buffer': b'Technique version 2 corrigee'})
        client.locator('#requested-upload-form button[type=submit]').click()
        expect(client.locator('#requested-detail .card-head .badge')).to_have_text('Déposé')
        admin.evaluate('(id)=>operationsClientRequest(id)', order_id)
        admin.locator(f'[data-client-doc-decision="{item["id"]}"][data-status="accepted"]').click()
        admin.locator('#cw-message').fill('Dossier technique accepté pour cette version.')
        admin.locator('#cw-review-form button[type=submit]').click()
        expect(admin.locator('.modal')).to_contain_text('Accepté')
        admin.locator('#cw-order-status').select_option('accepted')
        admin.locator('#cw-order-status-form button[type=submit]').click()
        expect(admin.locator('.modal')).to_contain_text('Statut de la demande : Acceptée')
        client.reload()
        expect(client.locator('#requested-detail .card-head .badge')).to_have_text('Accepté')
        expect(client.locator('#requested-upload-form')).to_have_count(0)
        body = client_a.request.get('/api/client/document-requests/' + item['id']).json()
        assert [v['number'] for v in body['document']['versions']] == [1, 2]
        assert client_a.request.get(f'/api/client/document-requests/{item["id"]}/versions/1/download').body() == b'Technique version 1'
        capture(client, 'client-document-accepte-1440')
        capture(admin, 'framatex-workflow-1440')
        check('6–10 : vérification, correction motivée, V2 et acceptation par FRAMATEX')

        # Préparation d'une vraie version commerciale approuvée, puis partage via l'interface.
        launch = internal.request.post('/api/launches', headers=headers,
                    data={'name': 'Lancement commercial workflow', 'client_name': 'Entreprise Client A'}).json()
        doc = internal.request.post(f'/api/launches/{launch["id"]}/documents', headers=headers,
                    multipart={'folder': 'jaune', 'title': 'Confirmation de commande', 'doc_type': 'Confirmation de commande',
                    'file': {'name': 'confirmation.txt', 'mimeType': 'text/plain', 'buffer': b'Confirmation commerciale autorisee'}}).json()
        assert internal.request.post(f'/api/documents/{doc["id"]}/reviews', headers=headers,
                    data={'decision': 'approved', 'comment': 'Version destinée explicitement au client.'}).ok
        assert internal.request.post(f'/api/document-versions/{doc["latest"]["id"]}/comments', headers=headers,
                    data={'body': 'COMMENTAIRE-INTERNE-JAMAIS-PUBLIE'}).ok
        admin.locator('#cw-share-document').click()
        admin.locator('#cw-version').select_option(doc['latest']['id'])
        admin.locator('#cw-share-reason').fill('Version commerciale approuvée pour le compte Client A.')
        admin.locator('#cw-share-form button[type=submit]').click()
        expect(admin.locator('[data-client-share-revoke]')).to_be_visible()
        share = next(s for s in client_a.request.get('/api/client/shared-documents').json() if s['title'] == 'Confirmation de commande')
        assert 'COMMENTAIRE-INTERNE-JAMAIS-PUBLIE' not in json.dumps(share)
        client.goto('/espace-client#/documents-transmis')
        with client.expect_download() as downloading:
            client.locator(f'[data-shared-download="{share["id"]}"]').click()
        download = downloading.value
        download.save_as(output / 'confirmation-client.txt')
        assert (output / 'confirmation-client.txt').read_bytes() == b'Confirmation commerciale autorisee'
        capture(client, 'client-documents-transmis-1440')
        for width in (1024, 820, 390):
            client.set_viewport_size({'width': width, 'height': 844})
            capture(client, f'client-documents-transmis-{width}')
        check('11–12 : publication explicite d’une version autorisée et téléchargement client réel')

        account_b = client_b.request.post('/api/client/register', headers=headers, data={
            'raison_sociale': 'Entreprise Client B', 'nom_contact': 'Contact Client B', 'email': 'workflow-b@example.test',
            'telephone': '0600000000', 'adresse': 'Adresse fictive', 'pays': 'Maroc', 'password': password}).json()
        assert internal.request.patch(f'/api/admin/clients/{account_b["id"]}/status', headers=headers, data={'status': 'active'}).ok
        assert client_b.request.post('/api/client/login', headers=headers, data={'email': account_b['email'], 'password': password}).ok
        assert client_b.request.get('/api/client/order-requests/' + order_id).status == 404
        assert client_b.request.get('/api/client/document-requests/' + item['id']).status == 404
        assert client_b.request.get('/api/client/shared-documents/' + share['id'] + '/download').status == 404
        assert client_b.request.get('/api/client/document-requests').json() == []
        assert client_b.request.get('/api/client/shared-documents').json() == []
        assert client_a.request.get('/api/admin/audit').status == 401
        assert client_a.request.get(f'/api/documents/{doc["id"]}/versions/1/download').status == 401
        check('13 : isolation des demandes, pièces, publications et audit entre Client A / Client B')

        admin.locator(f'[data-client-share-revoke="{share["id"]}"]').click()
        admin.locator('#cw-revoke-reason').fill('Retrait explicite de la transmission pendant la recette.')
        admin.locator('#cw-revoke-form button[type=submit]').click()
        expect(admin.locator('.modal')).to_contain_text('Retiré')
        assert client_a.request.get('/api/client/shared-documents/' + share['id'] + '/download').status == 404
        assert internal.request.get(f'/api/documents/{doc["id"]}/versions/1/download').body() == b'Confirmation commerciale autorisee'
        client.reload(); expect(client.locator('#shared-body')).to_contain_text('Aucun document transmis')
        check('14–15 : retrait effectif du partage sans suppression de la version interne')

        assert internal.request.patch(f'/api/admin/clients/{account_a["id"]}/status', headers=headers, data={'status': 'suspended'}).ok
        client.goto('/espace-client#/compte')
        expect(client.locator('h1')).to_contain_text('Votre compte a été suspendu. Contactez FRAMATEX.')
        for path in ('/', '/espace-client', '/espace-framatex', '/api/health'):
            assert internal.request.get(path).ok
        assert not report['errors'], report['errors']
        check('Message suspended distinct, pages intégrées conservées et aucune erreur JavaScript')
        browser.close()
    report['status'] = 'passed'
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('Scénario complet validé.', flush=True)


if __name__ == '__main__':
    harness.run_browser = run_browser
    harness.main()

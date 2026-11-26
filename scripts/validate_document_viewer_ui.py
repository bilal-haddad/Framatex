"""Recette Chromium de la visionneuse documentaire (clics réels sur l'interface).

    python scripts/validate_document_viewer_ui.py --output data/viewer-validation

Préparation par l'API (commande fictive, PDF de 2 pages, classeur, Word, email, V2 du PDF) ;
consultation entièrement par clics : ouvrir, pages, zoom, recherche, feuilles, formules,
ancienne version depuis l'historique, plein écran, consultation sans téléchargement.
"""
import argparse, io, os, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'viewer-validation')
    out = parser.parse_args().output.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-viewer-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    __import__('recette_db').use_isolated_database()
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    import app.main  # noqa: F401
    migrate()
    pw = secrets.token_urlsafe(18)
    with SessionLocal() as db:
        db.add(User(name='Nadia Benali', email='chef.visionneuse@example.test', password_hash=hash_password(pw), roles=[Role(name='Administrateur')])); db.commit()
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
        checks = run(f'http://127.0.0.1:{port}', pw, out)
    finally:
        server.terminate()
    print('\n'.join('OK  ' + c for c in checks)); print(f'{len(checks)} vérifications réussies.')


def files():
    import fitz
    from docx import Document as Docx
    from openpyxl import Workbook
    def pdf(lines):
        d = fitz.open()
        for t in lines:
            d.new_page().insert_text((72, 90), t, fontsize=16)
        return d.tobytes()
    wb = Workbook(); ws = wb.active; ws.title = 'Besoin'; ws.append(['Article', 'Quantité', 'Prix', 'Total']); ws.append(['Costume', 120, 85.5, '=B2*C2'])
    for i in range(3, 400): ws.append([f'Ligne {i}', i, 1, f'=B{i}*C{i}'])
    wb.create_sheet('Notes')['A1'] = 'Coloris : Écru'
    xl = io.BytesIO(); wb.save(xl)
    d = Docx(); d.add_heading('Fiche technique costume', 1); d.add_paragraph('Tissu : laine 100 %, doublure satin.')
    word = io.BytesIO(); d.save(word)
    return {'v1': pdf(['Fiche costume V1 : tissu laine', 'Doublure satin bleu nuit']), 'v2': pdf(['Fiche costume V2 : tissu laine froide', 'Doublure satin gris']),
            'xlsx': xl.getvalue(), 'docx': word.getvalue()}


def run(base, pw, out):
    from playwright.sync_api import sync_playwright, expect
    checks, errors = [], []
    data = files()
    exe = '/opt/pw-browsers/chromium' if Path('/opt/pw-browsers/chromium').exists() else None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=exe)
        page = browser.new_page(base_url=base, viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('/espace-framatex'); page.fill('#email', 'chef.visionneuse@example.test'); page.fill('#password', pw)
        page.click('#login-form [type=submit]'); page.wait_for_selector('.content h1')
        req = page.context.request
        lid = req.post('/api/order-sheets', headers=H, data={'name': 'Costume visionneuse', 'order_ref': '000512'}).json()['id']
        def up(name, blob):
            r = req.post(f'/api/launches/{lid}/documents', headers=H, multipart={'folder': 'jaune', 'title': name, 'doc_type': 'Autre',
                         'file': {'name': name, 'mimeType': 'application/octet-stream', 'buffer': blob}})
            assert r.status == 201, r.text(); return r.json()
        pdf = up('fiche-costume.pdf', data['v1']); up('besoin.xlsx', data['xlsx']); up('fiche.docx', data['docx'])
        assert req.post(f"/api/documents/{pdf['id']}/versions", headers=H, multipart={'file': {'name': 'fiche-costume.pdf', 'mimeType': 'application/pdf', 'buffer': data['v2']}}).status == 201

        # Navigation par clics jusqu'au sous-dossier jaune.
        page.locator('.sidebar [data-view="launches"]').click()
        page.locator('#ops-launch-results').get_by_text('000512').first.click()
        page.locator('.dj-folder[data-folder="jaune"]').click()

        def open_doc(title):
            page.locator('tr', has_text=title).get_by_role('button', name='Ouvrir').first.click()
            page.wait_for_selector('.dv-modal .dv-head')

        # PDF : pages, zoom, recherche, plein écran.
        open_doc('fiche-costume.pdf')
        expect(page.locator('.dv-head')).to_contain_text('Version 2')
        img = page.locator('.dv-pdf'); page.wait_for_function("document.querySelector('.dv-pdf').naturalWidth > 0")
        page.click('[data-dv="next"]'); expect(page.locator('[data-dv-page]')).to_have_value('2')
        page.click('[data-dv="in"]'); expect(page.locator('[data-dv-zoom]')).to_have_text('160 %')
        page.fill('[data-dv-search] input', 'satin gris'); page.press('[data-dv-search] input', 'Enter')
        expect(page.locator('[data-dv-hits]')).to_contain_text('p. 2'); expect(page.locator('.dv-marks i').first).to_be_visible()
        page.screenshot(path=str(out / 'visionneuse-pdf.png'))
        checks.append('PDF : véritable page rendue, page suivante, zoom 160 %, recherche « satin gris » surlignée en page 2')
        # Ancienne version depuis l'historique : contenu de V1, pas de V2.
        page.locator('.dv-side [data-ops-version]').last.click()
        page.wait_for_selector('.dv-modal .dv-head')
        expect(page.locator('.dv-head')).to_contain_text('Version 1')
        page.fill('[data-dv-search] input', 'bleu nuit'); page.press('[data-dv-search] input', 'Enter')
        expect(page.locator('[data-dv-hits]')).to_contain_text('p. 2')
        checks.append('Historique : V1 sélectionnée → contenu réel de V1 (« bleu nuit »), non la dernière version')
        page.locator('#close-modal').click()

        # Excel : feuilles, cellules, formules, lignes supplémentaires.
        open_doc('besoin.xlsx')
        expect(page.locator('.dv-sheets button')).to_have_count(2)
        expect(page.locator('.dv-grid')).to_contain_text('Costume')
        page.check('[data-dv-formulas]'); expect(page.locator('.dv-grid td.has-f').first).to_have_text('=B2*C2')
        page.click('[data-dv-next]'); expect(page.locator('.dv-grid tbody tr')).to_have_count(399)
        page.locator('.dv-sheets button', has_text='Notes').click(); expect(page.locator('.dv-grid')).to_contain_text('Coloris : Écru')
        page.screenshot(path=str(out / 'visionneuse-excel.png'))
        checks.append('Excel : deux feuilles, cellules, formules (=B2*C2), 399 lignes par pages de 200, feuille « Notes »')
        page.locator('#close-modal').click()

        # Word.
        open_doc('fiche.docx')
        expect(page.locator('.dv-doc h1')).to_have_text('Fiche technique costume'); expect(page.locator('.dv-notice')).to_be_visible()
        page.screenshot(path=str(out / 'visionneuse-word.png'))
        checks.append('Word : titres et texte rendus localement, limite de fidélité signalée')
        page.locator('#close-modal').click()

        # Historique : avant/après, ouverture d'une version, document supprimé → corbeille, onglet commande.
        assert req.patch(f'/api/launches/{lid}/sheet', headers=H, data={'color': 'Gris perle'}).status == 200
        word_id = next(d['id'] for f in req.get(f'/api/launches/{lid}').json()['folders'] for d in f['documents'] if d['title'] == 'fiche.docx')
        assert req.fetch(f'/api/documents/{word_id}', method='DELETE', headers={**H, 'Content-Type': 'application/json'},
                         data='{"reason": "Doublon de la fiche PDF"}').status == 204
        page.locator('.sidebar [data-view="audit"], .sidebar [data-ops-view="audit"]').first.click()
        page.wait_for_selector('#ops-audit-form')
        page.select_option('#launch_id', lid); page.click('#ops-audit-form [type=submit]')
        sheet_row = page.locator('.hist-row', has_text='Fiche commande modifiée').first
        sheet_row.locator('summary').click()
        expect(sheet_row.locator('.hist-changes table')).to_contain_text('Couleur')
        expect(sheet_row.locator('.hist-changes table')).to_contain_text('Gris perle')
        deleted = page.locator('.hist-row', has_text='Suppression de document').first
        expect(deleted).to_contain_text('Motif : Doublon de la fiche PDF')
        page.screenshot(path=str(out / 'historique-global.png'))
        upload_row = page.locator('.hist-row', has_text='Dépôt de document').filter(has_text='fiche-costume.pdf').first
        upload_row.locator('[data-hist-doc]').click()
        page.wait_for_selector('.dv-modal .dv-head'); expect(page.locator('.dv-head')).to_contain_text('Version 1')
        expect(page.locator('.hist-doc')).to_contain_text('Nouvelle version')
        checks.append('Historique global : avant/après de la fiche, motif de suppression ; « Ouvrir V1 » → visionneuse sur V1 ; historique du document')
        page.locator('#close-modal').click()
        page.locator('.sidebar [data-view="audit"], .sidebar [data-ops-view="audit"]').first.click()
        page.wait_for_selector('#ops-audit-form'); page.select_option('#launch_id', lid); page.click('#ops-audit-form [type=submit]')
        page.locator('.hist-row', has_text='Suppression de document').first.locator('[data-hist-trash]').click()
        expect(page.locator('.ops-heading h1')).to_have_text('Corbeille documentaire')
        checks.append('Document supprimé : pas de réouverture depuis l’historique, lien vers la corbeille (administrateur)')
        page.locator('.sidebar [data-view="launches"]').click()
        page.locator('#ops-launch-results').get_by_text('000512').first.click()
        page.locator('#dj-tab-historique').click()
        expect(page.locator('.hist-list').first).to_contain_text('Fiche commande modifiée')
        checks.append('Historique de la commande (onglet Historique) : même présentation détaillée')
        assert not errors, errors
        checks.append('Aucune erreur JavaScript')
        browser.close()
    return checks


if __name__ == '__main__':
    main()

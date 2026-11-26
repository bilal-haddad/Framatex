"""Fabrique une base SQLite fictive couvrant toutes les fonctions (recette de migration).

    python scripts/make_migration_fixture.py --dest data/migration-fixture

Rejoue les parcours API de la revue QA (commandes, documents, versions, OCR, Client, partages,
matières, emails, circuits, habilitations…), ajoute documents complémentaires, corbeille,
vérification de conservation, suppression définitive et clés d'idempotence, puis copie la base et
les fichiers (aucune donnée réelle ; comptes example.test / framatex.test fictifs).
"""
import argparse, json, shutil, sqlite3, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--dest', type=Path, required=True)
    dest = parser.parse_args().dest.resolve()
    if dest.exists():
        sys.exit('Le dossier de destination doit être absent (aucun écrasement).')
    import httpx
    import qa_platform_review as recette
    qa = recette.QA()
    with recette.platform_server(qa) as ctx:
        recette.run_checks(qa, ctx.base, ctx.password, ctx.ids, ctx.tmp)
        H = {'X-Framatex-Request': '1'}
        with httpx.Client(base_url=ctx.base, headers=H, timeout=60) as c:
            c.post('/api/auth/login', json={'email': 'recette@framatex.test', 'password': ctx.password}).raise_for_status()
            lid = c.post('/api/order-sheets', headers={**H, 'Idempotency-Key': uuid.uuid4().hex}, json={
                'name': 'Fixture migration', 'order_ref': '000417', 'client_name': 'Client zéro initial', 'workshop': 'Atelier Été',
                'color': 'Écru', 'of_number': '0042', 'quantity': 1200, 'invoice_ref': 'FAC-00017', 'description': None}).json()['id']
            c.post(f'/api/launches/{lid}/completeness/standard').raise_for_status()
            case = c.post(f'/api/launches/{lid}/optional-cases', json={'folder': 'rose', 'title': 'Photos prototype', 'description': 'Vues'}).json()
            c.post(f'/api/launches/{lid}/optional-cases', json={'folder': 'bleu', 'title': 'Case vide'}).raise_for_status()
            up = lambda folder, name, data, **extra: c.post(f'/api/launches/{lid}/documents', data={'folder': folder, 'title': name, 'doc_type': 'Autre', **extra},
                                                            files={'file': (name, data, 'text/plain')}).json()
            up('rose', 'photo-face.txt', b'Photo face fixture', optional_case_id=case['id'])
            gone = up('jaune', 'erreur.txt', b'Depot errone fixture')
            trashed = up('jaune', 'corbeille.txt', b'Document en corbeille fixture')
            for doc in (gone, trashed):
                c.request('DELETE', f"/api/documents/{doc['id']}", headers={**H, 'Content-Type': 'application/json'}, content=b'{"reason":"fixture"}')
            c.post(f"/api/admin/document-trash/documents/{gone['id']}/purge", json={'confirmation': 'SUPPRIMER', 'reason': 'Fixture de migration'}).raise_for_status()
            odd = c.post(f'/api/launches/{lid}/documents', data={'folder': 'vert', 'title': 'Divers', 'doc_type': 'Type maison'},
                         files={'file': ('divers.txt', b'Type maison fixture', 'text/plain')}).json()
            c.request('DELETE', f"/api/documents/{odd['id']}", headers={**H, 'Content-Type': 'application/json'}, content=b'{"reason":"fixture"}')
            c.post(f"/api/admin/document-trash/documents/{odd['id']}/retention-clearance", json={'reason': 'Vérification de conservation fixture'}).raise_for_status()
        data_dir = Path(ctx.tmp)
        dest.mkdir(parents=True)
        with sqlite3.connect(str(data_dir / 'framat.db')) as source, sqlite3.connect(str(dest / 'framat.db')) as copy:
            source.backup(copy)
        for folder in ('files', 'client_order_files'):
            if (data_dir / folder).is_dir():
                shutil.copytree(data_dir / folder, dest / folder)
    with sqlite3.connect(str(dest / 'framat.db')) as db:
        counts = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for (t,) in
                  db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'document_content_fts_%'")}
    print(json.dumps({'dest': str(dest), 'non_empty_tables': sum(1 for v in counts.values() if v), 'rows': sum(counts.values())}, indent=1))


if __name__ == '__main__':
    main()

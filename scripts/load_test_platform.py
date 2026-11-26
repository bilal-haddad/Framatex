"""Test de charge progressif (1, 5, 10, 20 utilisateurs simulés) sur un serveur réel et une base temporaire.

    python scripts/load_test_platform.py --levels 1,5,10,20 --output data/load-test

Chaque utilisateur (compte administrateur fictif distinct, session propre) exécute en parallèle :
création de commande, ouverture, recherche, dépôt PDF et Excel, aperçu PDF et Excel, modification
de fiche, suppression puis restauration. Mesures : temps de réponse (médiane, p95, max) par
opération, erreurs, requêtes par seconde, verrous SQLite (« database is locked ») et doublons.
"""
import argparse, io, json, os, secrets, socket, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}


def files():
    import fitz
    from openpyxl import Workbook
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 90), f'Fiche de charge page {i + 1}', fontsize=14)
    wb = Workbook(); ws = wb.active
    for i in range(200):
        ws.append([f'Ligne {i}', i, f'=B{i + 1}*2'])
    buf = io.BytesIO(); wb.save(buf)
    return d.tobytes(), buf.getvalue()


def scenario(base, email, password, pdf, xlsx, record, user_index):
    import httpx
    with httpx.Client(base_url=base, headers=H, timeout=60) as c:
        def step(name, method, url, **kw):
            t0 = time.perf_counter()
            try:
                r = c.request(method, url, **kw)
                ok, status, body = r.status_code < 400, r.status_code, r.text[:200]
            except httpx.HTTPError as exc:
                ok, status, body, r = False, 0, str(exc)[:200], None
            record(name, time.perf_counter() - t0, ok, status, body)
            return r if ok else None
        if not step('connexion', 'POST', '/api/auth/login', json={'email': email, 'password': password}):
            return
        launch = step('création commande', 'POST', '/api/order-sheets', json={'name': f'Charge U{user_index} {secrets.token_hex(3)}', 'order_ref': f'00{user_index:03d}'})
        if not launch:
            return
        lid = launch.json()['id']
        step('ouverture commande', 'GET', f'/api/launches/{lid}')
        step('recherche', 'GET', '/api/workspace/search', params={'q': f'00{user_index:03d}'})
        doc = step('dépôt PDF', 'POST', f'/api/launches/{lid}/documents', data={'folder': 'jaune', 'title': 'fiche.pdf', 'doc_type': 'Autre'},
                   files={'file': ('fiche.pdf', pdf, 'application/pdf')})
        xl = step('dépôt Excel', 'POST', f'/api/launches/{lid}/documents', data={'folder': 'jaune', 'title': 'besoin.xlsx', 'doc_type': 'Autre'},
                  files={'file': ('besoin.xlsx', xlsx, 'application/octet-stream')})
        if doc:
            step('aperçu PDF (page)', 'GET', f"/api/document-versions/{doc.json()['latest']['id']}/preview/page/1")
        if xl:
            step('aperçu Excel (feuille)', 'GET', f"/api/document-versions/{xl.json()['latest']['id']}/preview/sheet", params={'sheet': 'Sheet'})
        step('modification fiche', 'PATCH', f'/api/launches/{lid}/sheet', json={'color': 'Bleu', 'quantity': 100 + user_index})
        if doc:
            did = doc.json()['id']
            step('suppression', 'DELETE', f'/api/documents/{did}', headers={**H, 'Content-Type': 'application/json'}, content=b'{"reason":"charge"}')
            step('restauration', 'POST', f'/api/admin/document-trash/documents/{did}/restore')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--levels', default='1,5,10,20')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'load-test')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    levels = [int(x) for x in args.levels.split(',')]
    sys.path.insert(0, str(ROOT))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-load-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    __import__('recette_db').use_isolated_database()
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    import app.main  # noqa: F401
    migrate()
    pw = secrets.token_urlsafe(16)
    accounts = []
    with SessionLocal() as db:
        role = Role(name='Administrateur'); db.add(role)
        for i in range(max(levels)):
            email = f'charge{i}@example.test'
            db.add(User(name=f'Utilisateur charge {i}', email=email, password_hash=hash_password(pw), roles=[role])); accounts.append(email)
        db.commit()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=os.environ.copy(),
                              stdout=(out / 'server.log').open('w'), stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{port}'
    import httpx
    for _ in range(150):
        try:
            if httpx.get(base + '/api/health').status_code == 200: break
        except httpx.TransportError:
            time.sleep(.1)
    pdf, xlsx = files()
    report = []
    try:
        for level in levels:
            samples, lock = [], threading.Lock()
            def record(name, seconds, ok, status, body):
                with lock:
                    samples.append((name, seconds, ok, status, body))
            threads = [threading.Thread(target=scenario, args=(base, accounts[i], pw, pdf, xlsx, record, i)) for i in range(level)]
            t0 = time.perf_counter()
            for t in threads: t.start()
            for t in threads: t.join()
            wall = time.perf_counter() - t0
            ops = {}
            for name, seconds, ok, status, body in samples:
                ops.setdefault(name, []).append((seconds, ok, status, body))
            errors = [(n, s, b) for n, _, ok, s, b in samples if not ok]
            row = {'users': level, 'requests': len(samples), 'wall_s': round(wall, 2), 'rps': round(len(samples) / wall, 1),
                   'errors': len(errors), 'sqlite_locked': sum('locked' in b for _, _, b in errors),
                   'error_samples': errors[:5],
                   'operations': {name: {'n': len(v), 'median_ms': round(statistics.median(x[0] for x in v) * 1000),
                                         'p95_ms': round(sorted(x[0] for x in v)[max(0, int(len(v) * .95) - 1)] * 1000),
                                         'max_ms': round(max(x[0] for x in v) * 1000), 'errors': sum(not x[1] for x in v)}
                                  for name, v in ops.items()}}
            report.append(row)
            print(f"{level:>2} utilisateur(s) : {row['requests']} requêtes en {row['wall_s']} s · {row['rps']} req/s · erreurs {row['errors']} (verrous SQLite {row['sqlite_locked']})")
            for name, m in row['operations'].items():
                print(f"     {name:<24} médiane {m['median_ms']:>5} ms · p95 {m['p95_ms']:>5} ms · max {m['max_ms']:>5} ms · erreurs {m['errors']}")
            for e in errors[:3]:
                print('     ERREUR', e)
        # Intégrité : aucune commande dupliquée ni perdue.
        with SessionLocal() as db:
            from sqlalchemy import func, select
            from app.models import Launch
            names = db.execute(select(Launch.name, func.count()).group_by(Launch.name).having(func.count() > 1)).all()
            report.append({'duplicate_launch_names': len(names), 'launches': db.scalar(select(func.count()).select_from(Launch))})
            print(f"Intégrité : {report[-1]['launches']} commandes, {len(names)} doublon(s) de nom.")
    finally:
        server.terminate()
    (out / 'load-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

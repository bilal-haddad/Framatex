"""Banc de mesure des endpoints sur un jeu de données volumineux (base temporaire, données fictives).

    python scripts/benchmark_endpoints.py --launches 200 --docs 15 --events 50000 --output data/benchmark

Crée N commandes (checklist standard), D documents par commande (fichiers texte fictifs, versions,
types variés) et E événements d'audit, démarre Uvicorn, puis mesure (médiane et p95 sur 15 appels)
les requêtes d'ouverture d'une commande, de liste, de recherche, de tableau de bord et d'historique.
Écrit `benchmark.json`. Option --profile : profil pyinstrument des requêtes les plus lentes.
"""
import argparse, hashlib, json, os, random, secrets, socket, statistics, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}
TYPES = ['Commande client', 'Fiche technique', 'Bon de livraison', 'Facture', 'Pièce douanière', 'Excel BE', 'Email', 'Autre']
FOLDERS = ['jaune', 'jaune', 'rose', 'bleu', 'vert']


def seed(base, pw, launches, docs, events):
    import httpx
    from app.core import SessionLocal
    from app.main import STORAGE
    from app.models import AuditEvent, Document, DocumentVersion, Folder, User
    c = httpx.Client(base_url=base, headers=H, timeout=120)
    c.post('/api/auth/login', json={'email': 'chef.bench@example.test', 'password': pw}).raise_for_status()
    ids = []
    for i in range(launches):
        r = c.post('/api/order-sheets', json={'name': f'Commande banc {i}', 'order_ref': f'BENCH-{i:05d}', 'client_name': f'Client {i % 23}',
                                               'workshop': f'Atelier {i % 7}', 'color': random.choice(['Bleu', 'Noir', 'Gris']), 'of_number': f'OF-{i:05d}'})
        r.raise_for_status(); ids.append(r.json()['id'])
        c.post(f'/api/launches/{ids[-1]}/completeness/standard').raise_for_status()
    rnd = random.Random(7)
    with SessionLocal() as db:
        admin = db.query(User).filter_by(email='chef.bench@example.test').one()
        folders = {(f.launch_id, f.slug): f.id for f in db.query(Folder)}
        for lid in ids:
            for k in range(docs):
                slug = rnd.choice(FOLDERS)
                doc = Document(folder_id=folders[(lid, slug)], title=f'Pièce {k} {lid[:6]}', doc_type=rnd.choice(TYPES), created_by=admin.id)
                db.add(doc); db.flush()
                for n in range(1, rnd.choice([1, 1, 1, 2, 3]) + 1):
                    blob = f'{lid} {k} {n} {rnd.random()}'.encode()
                    disk = secrets.token_hex(24); (STORAGE / disk).write_bytes(blob)
                    db.add(DocumentVersion(document_id=doc.id, number=n, original_name=f'piece-{k}-v{n}.txt', disk_name=disk, size=len(blob),
                                           sha256=hashlib.sha256(blob).hexdigest(), content_type='text/plain', uploaded_by=admin.id))
                    db.add(AuditEvent(actor_id=admin.id, action='document.upload', target_type='document', target_id=doc.id,
                                      detail=json.dumps({'launch': lid, 'folder': slug})))
            db.commit()
        for i in range(events):
            db.add(AuditEvent(actor_id=admin.id, action='launch.operations.update', target_type='launch', target_id=ids[i % len(ids)],
                              detail=json.dumps({'fields': ['article']})))
            if i % 5000 == 4999:
                db.commit()
        db.commit()
    return ids


def measure(base, pw, ids, rounds=15):
    import httpx
    c = httpx.Client(base_url=base, headers=H, timeout=120)
    c.post('/api/auth/login', json={'email': 'chef.bench@example.test', 'password': pw}).raise_for_status()
    lid = ids[len(ids) // 2]
    doc = next(d for f in c.get(f'/api/launches/{lid}').json()['folders'] for d in f['documents'])
    urls = {
        'auth/me': '/api/auth/me', 'launch detail': f'/api/launches/{lid}', 'completeness': f'/api/launches/{lid}/completeness',
        'operations': f'/api/launches/{lid}/operations', 'duplicates': f'/api/launches/{lid}/duplicates',
        'activity (commande)': f'/api/workspace/activity?launch_id={lid}&limit=40', 'reviews': f'/api/launches/{lid}/reviews',
        'quality': f'/api/launches/{lid}/quality', 'approval-overview': f'/api/launches/{lid}/approval-overview',
        'dependency-graph': f'/api/launches/{lid}/dependency-graph', 'materials': f'/api/launches/{lid}/materials',
        'workspace/launches (liste)': '/api/workspace/launches', 'search q=BENCH-0001': '/api/workspace/search?q=BENCH-0001',
        'search q=pièce': '/api/workspace/search?q=pi%C3%A8ce', 'dashboard général': '/api/workspace/dashboard',
        'dashboard commande': f'/api/launches/{lid}/dashboard', 'activity (globale)': '/api/workspace/activity?limit=50',
        'trash': '/api/admin/document-trash', 'my-launches': '/api/workspace/my-launches?q=atelier',
        'document preview': f"/api/document-versions/{doc['latest']['id']}/preview",
    }
    if os.getenv('BENCH_EXTRA_URLS'):
        urls.update(json.loads(os.getenv('BENCH_EXTRA_URLS').replace('{lid}', lid)))
    results = {}
    for name, url in urls.items():
        times, status = [], None
        for _ in range(rounds):
            t0 = time.perf_counter(); r = c.get(url); times.append((time.perf_counter() - t0) * 1000); status = r.status_code
        times.sort()
        results[name] = {'status': status, 'median_ms': round(statistics.median(times), 1), 'p95_ms': round(times[int(len(times) * .95) - 1], 1),
                         'bytes': len(r.content)}
        print(f'{name:<28} {status}  médiane {results[name]["median_ms"]:>8} ms  p95 {results[name]["p95_ms"]:>8} ms  {len(r.content)//1024:>5} Ko', flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launches', type=int, default=200)
    parser.add_argument('--docs', type=int, default=15)
    parser.add_argument('--events', type=int, default=50000)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'benchmark')
    parser.add_argument('--data-dir', type=Path, help='réutiliser une base déjà préparée')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix='framat-bench-'))
    fresh = not (data_dir / 'framat.db').exists()
    os.environ.update(FRAMATEX_DATA_DIR=str(data_dir), FRAMATEX_SECRET_KEY=os.getenv('FRAMATEX_SECRET_KEY') or secrets.token_urlsafe(32))
    # Base : DATABASE_URL si elle désigne PostgreSQL (base dédiée et vide), sinon SQLite temporaire.
    if not os.getenv('DATABASE_URL', '').startswith(('postgresql', 'postgres')):
        __import__('recette_db').use_isolated_database()
    from app.core import SessionLocal, hash_password
    from app.migrate import migrate
    from app.models import Role, User
    import app.main  # noqa: F401
    migrate()
    pw_file = data_dir / '.bench-password'
    if fresh:
        pw = secrets.token_urlsafe(18); pw_file.write_text(pw)
        with SessionLocal() as db:
            db.add(User(name='Chef Banc', email='chef.bench@example.test', password_hash=hash_password(pw), roles=[Role(name='Administrateur')])); db.commit()
    pw = pw_file.read_text()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=ROOT, env=os.environ.copy(),
                              stdout=(out / 'server.log').open('w'), stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{port}'
    try:
        import httpx
        for _ in range(300):
            try:
                if httpx.get(base + '/api/health').status_code == 200: break
            except httpx.TransportError:
                time.sleep(.1)
        t0 = time.perf_counter()
        if fresh:
            ids = seed(base, pw, args.launches, args.docs, args.events)
            (data_dir / '.bench-ids.json').write_text(json.dumps(ids))
            print(f'Jeu de données : {args.launches} commandes, ~{args.launches * args.docs} documents, {args.events} événements ({time.perf_counter() - t0:.0f} s)')
        ids = json.loads((data_dir / '.bench-ids.json').read_text())
        results = measure(base, pw, ids)
        (out / 'benchmark.json').write_text(json.dumps({'data_dir': str(data_dir), 'launches': len(ids), 'results': results}, ensure_ascii=False, indent=1))
    finally:
        server.terminate()


if __name__ == '__main__':
    main()

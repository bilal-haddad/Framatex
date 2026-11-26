"""Test de charge avancé (base temporaire, données fictives, serveur local uniquement).

    python scripts/load_test_enterprise.py --levels 20,30,50,75,100 --sustain 50:120 --output data/load-enterprise
    python scripts/load_test_enterprise.py --open full ...   # ouverture « 22 requêtes » (version précédente)

Chaque utilisateur simulé (compte administrateur fictif, session propre, connecté une fois) enchaîne :
liste des commandes, création (clé d'idempotence), ouverture, modification de fiche, dépôts PDF
(dépôt guidé : analyse et OCR), Excel et Word, aperçus PDF et Excel, recherche, validation
(décision documentaire), historique, suppression et restauration, modification d'habilitations,
tableau de bord. Paliers progressifs (tous les utilisateurs démarrent ensemble : pic), puis charge
soutenue. Mesures : débit, moyenne, médiane, p95, p99, erreurs, CPU et mémoire du serveur, verrous
SQLite, intégrité (commandes, doublons, documents, événements d'audit). Arrêt de la montée si le taux
d'erreur dépasse 5 %, si le p95 dépasse 30 s ou si la mémoire disponible devient insuffisante.
"""
import argparse, io, json, os, secrets, socket, statistics, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {'X-Framatex-Request': '1'}
OPEN_CORE = ['/api/auth/me', '/api/launches/{id}', '/api/launches/{id}/completeness', '/api/launches/{id}/reviews',
             '/api/launches/{id}/operations', '/api/launches/{id}/duplicates']
OPEN_FULL = OPEN_CORE + ['/api/launches/{id}/values', '/api/launches/{id}/impacts', '/api/business-value-fields', '/api/launches/{id}/quality',
                         '/api/launches/{id}/excel-inspections', '/api/launches/{id}/specifications', '/api/launches/{id}/emails',
                         '/api/launches/{id}/dependency-graph', '/api/launches/{id}/impact-simulations', '/api/launches/{id}/orli-reconciliation',
                         '/api/launches/{id}/materials', '/api/launches/{id}/approval-overview', '/api/launches/{id}/client-publications',
                         '/api/launches/{id}/supplier-requests', '/api/launches/{id}/experience-notes', '/api/workspace/activity?launch_id={id}&limit=40']


def files():
    import fitz
    from docx import Document as Docx
    from openpyxl import Workbook
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 90), f'Fiche technique de charge page {i + 1}\nReference commande : CHARGE', fontsize=12)
    wb = Workbook(); ws = wb.active
    for i in range(200):
        ws.append([f'Ligne {i}', i, f'=B{i + 1}*2'])
    xl = io.BytesIO(); wb.save(xl)
    doc = Docx(); doc.add_heading('Fiche d’emploi', 1); doc.add_paragraph('Quantité : 1 200 pièces')
    wd = io.BytesIO(); doc.save(wd)
    return d.tobytes(), xl.getvalue(), wd.getvalue()


class Recorder:
    def __init__(self):
        self.lock = threading.Lock(); self.samples = []

    def add(self, name, seconds, ok, status, body):
        with self.lock:
            self.samples.append((name, seconds, ok, status, body, time.time()))


def scenario(base, email, password, blobs, rec, idx, open_urls, tech_id, deadline=None):
    import httpx
    pdf, xlsx, docx = blobs
    with httpx.Client(base_url=base, headers=H, timeout=120) as c:
        def step(name, method, url, **kw):
            t0 = time.perf_counter()
            try:
                r = c.request(method, url, **kw)
                ok, status, body = r.status_code < 400, r.status_code, (r.text[:200] if r.status_code >= 400 else '')
            except httpx.HTTPError as exc:
                ok, status, body, r = False, 0, f'{exc.__class__.__name__}: {exc}'[:200], None
            rec.add(name, time.perf_counter() - t0, ok, status, body)
            return r if ok else None
        if not step('connexion', 'POST', '/api/auth/login', json={'email': email, 'password': password}):
            return
        loops = 0
        while True:
            loops += 1
            tag = f'U{idx}-{loops}-{secrets.token_hex(2)}'
            step('liste commandes', 'GET', '/api/workspace/launches', params={'limit': 51})
            created = step('création commande', 'POST', '/api/order-sheets', json={'name': f'Charge {tag}', 'order_ref': f'CH-{tag}'},
                           headers={**H, 'Idempotency-Key': uuid.uuid4().hex})
            if not created:
                return
            lid = created.json()['id']
            t0 = time.perf_counter(); ok = True
            for url in open_urls:
                r = c.get(url.replace('{id}', lid)); ok = ok and r.status_code < 400
            rec.add(f'ouverture commande ({len(open_urls)} req.)', time.perf_counter() - t0, ok, 200 if ok else 500, '')
            step('modification fiche', 'PATCH', f'/api/launches/{lid}/sheet', json={'color': 'Bleu', 'quantity': 100 + idx})
            staged = step('dépôt PDF (analyse/OCR)', 'POST', f'/api/launches/{lid}/document-uploads', data={'folder': 'jaune'},
                          files={'file': ('fiche.pdf', pdf, 'application/pdf')})
            doc = None
            if staged:
                s = staged.json(); rel = s['analysis'].get('relationships') or []
                doc = step('publication PDF', 'POST', f"/api/launches/{lid}/document-uploads/{s['id']}/publish", json={
                    'folder': 'jaune', 'doc_type': 'Fiche technique', 'title': 'Fiche technique', 'confirm_type': True,
                    **({'relationship_action': 'new_document', 'relationship_candidate_version_id': rel[0]['candidate_version_id']} if rel else {})})
            xl = step('dépôt Excel', 'POST', f'/api/launches/{lid}/documents', data={'folder': 'jaune', 'title': 'besoin.xlsx', 'doc_type': 'Excel BE'},
                      files={'file': ('besoin.xlsx', xlsx, 'application/octet-stream')})
            step('dépôt Word', 'POST', f'/api/launches/{lid}/documents', data={'folder': 'jaune', 'title': 'emploi.docx', 'doc_type': 'Autre'},
                 files={'file': ('emploi.docx', docx, 'application/octet-stream')})
            if doc:
                d = doc.json()
                step('aperçu PDF', 'GET', f"/api/document-versions/{d['latest']['id']}/preview/page/1")
                step('validation (décision)', 'POST', f"/api/documents/{d['id']}/reviews", json={'decision': 'approved', 'comment': ''})
            if xl:
                step('aperçu Excel', 'GET', f"/api/document-versions/{xl.json()['latest']['id']}/preview/sheet", params={'sheet': 'Sheet'})
            step('recherche', 'GET', '/api/workspace/search', params={'q': f'CH-{tag}'})
            step('historique commande', 'GET', '/api/workspace/activity', params={'launch_id': lid, 'limit': 40})
            if xl:
                did = xl.json()['id']
                step('suppression', 'DELETE', f'/api/documents/{did}', headers={**H, 'Content-Type': 'application/json'}, content=b'{"reason":"charge"}')
                step('restauration', 'POST', f'/api/admin/document-trash/documents/{did}/restore')
            step('habilitations', 'PUT', f'/api/admin/collaborators/{tech_id}/assignments/{lid}', json={'folders': {'jaune': ['document.read']}})
            if loops == 1:
                step('tableau de bord', 'GET', '/api/workspace/dashboard')
            if deadline is None or time.time() >= deadline:
                return


def stats(samples, wall):
    if not samples:
        return {}
    durations = sorted(s[1] for s in samples)
    pct = lambda p: round(durations[min(len(durations) - 1, max(0, int(len(durations) * p) - 1))] * 1000)
    errors = [s for s in samples if not s[2]]
    ops = {}
    for name, sec, ok, status, body, _ in samples:
        ops.setdefault(name, []).append((sec, ok))
    return {'requests': len(samples), 'wall_s': round(wall, 1), 'rps': round(len(samples) / wall, 1),
            'mean_ms': round(statistics.mean(durations) * 1000), 'median_ms': round(statistics.median(durations) * 1000),
            'p95_ms': pct(.95), 'p99_ms': pct(.99), 'max_ms': round(durations[-1] * 1000), 'errors': len(errors),
            'error_rate': round(100 * len(errors) / len(samples), 2),
            'sqlite_locked': sum('locked' in s[4] for s in errors), 'timeouts': sum('Timeout' in s[4] for s in errors),
            'error_samples': sorted({(s[0], s[3], s[4][:120]) for s in errors})[:6],
            'operations': {n: {'n': len(v), 'median_ms': round(statistics.median(x[0] for x in v) * 1000),
                               'p95_ms': round(sorted(x[0] for x in v)[max(0, int(len(v) * .95) - 1)] * 1000),
                               'p99_ms': round(sorted(x[0] for x in v)[max(0, int(len(v) * .99) - 1)] * 1000),
                               'errors': sum(not x[1] for x in v)} for n, v in ops.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--levels', default='20,30,50,75,100')
    parser.add_argument('--sustain', default='50:120', help='utilisateurs:secondes (vide pour ignorer)')
    parser.add_argument('--open', choices=['core', 'full'], default='core')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'load-enterprise')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    levels = [int(x) for x in args.levels.split(',') if x]
    sustain = tuple(int(x) for x in args.sustain.split(':')) if args.sustain else None
    sys.path.insert(0, str(ROOT))
    os.environ.update(FRAMATEX_DATA_DIR=tempfile.mkdtemp(prefix='framat-charge-'), FRAMATEX_SECRET_KEY=secrets.token_urlsafe(32))
    # Base : DATABASE_URL si elle désigne PostgreSQL (base dédiée et vide), sinon SQLite temporaire.
    if not os.getenv('DATABASE_URL', '').startswith(('postgresql', 'postgres')):
        __import__('recette_db').use_isolated_database()
    import psutil
    from app.core import SessionLocal, hash_password
    from app.models import Role, User
    from app.migrate import migrate
    import app.main  # noqa: F401
    migrate()
    pw = secrets.token_urlsafe(16)
    n_accounts = max(levels + ([sustain[0]] if sustain else []))
    accounts = []
    with SessionLocal() as db:
        role = Role(name='Administrateur'); db.add(role)
        for i in range(n_accounts):
            email = f'charge{i}@example.test'
            db.add(User(name=f'Utilisateur charge {i}', email=email, password_hash=hash_password(pw), roles=[role])); accounts.append(email)
        db.commit()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    cmd = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)] + (['--workers', str(args.workers)] if args.workers > 1 else [])
    server = subprocess.Popen(cmd, cwd=ROOT, env=os.environ.copy(), stdout=(out / 'server.log').open('w'), stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{port}'
    import httpx
    for _ in range(300):
        try:
            if httpx.get(base + '/api/health').status_code == 200: break
        except httpx.TransportError:
            time.sleep(.1)
    with httpx.Client(base_url=base, headers=H) as admin:
        admin.post('/api/auth/login', json={'email': accounts[0], 'password': pw}).raise_for_status()
        tech_id = admin.post('/api/admin/collaborators', json={'name': 'Technicien charge', 'email': 'tech.charge@example.test'}).json()['collaborator']['id']
    blobs = files()
    open_urls = OPEN_CORE if args.open == 'core' else OPEN_FULL
    proc = psutil.Process(server.pid)
    report = {'config': {'levels': levels, 'sustain': sustain, 'open_requests': len(open_urls), 'workers': args.workers,
                         'cpus': psutil.cpu_count(), 'memory_mb': round(psutil.virtual_memory().total / 2**20)}, 'phases': []}

    def run_phase(label, users, duration=None):
        rec = Recorder(); usage = []; stop = threading.Event()
        def sample():
            known = {}                                         # objets Process conservés : mesure CPU cumulative correcte
            def current():
                for p in [proc] + proc.children(recursive=True):
                    if p.pid not in known:
                        known[p.pid] = p; p.cpu_percent(None)
                return [p for p in known.values() if p.is_running()]
            current()
            while not stop.wait(1):
                try:
                    procs = current()
                    usage.append((sum(p.cpu_percent(None) for p in procs), sum(p.memory_info().rss for p in procs) / 2**20,
                                  psutil.virtual_memory().available / 2**20))
                except psutil.Error:
                    pass
        sampler = threading.Thread(target=sample, daemon=True); sampler.start()
        deadline = time.time() + duration if duration else None
        threads = [threading.Thread(target=scenario, args=(base, accounts[i], pw, blobs, rec, i, open_urls, tech_id, deadline)) for i in range(users)]
        t0 = time.perf_counter()
        for t in threads: t.start()                            # démarrage simultané : pic de requêtes
        for t in threads: t.join()
        wall = time.perf_counter() - t0
        stop.set(); sampler.join()
        row = {'phase': label, 'users': users, **stats(rec.samples, wall),
               'cpu_percent_mean': round(statistics.mean(u[0] for u in usage), 0) if usage else None,
               'cpu_percent_max': round(max(u[0] for u in usage), 0) if usage else None,
               'rss_mb_max': round(max(u[1] for u in usage)) if usage else None,
               'available_mb_min': round(min(u[2] for u in usage)) if usage else None}
        report['phases'].append(row)
        print(f"{label:<22} {users:>3} utilisateurs : {row['requests']} requêtes en {row['wall_s']} s · {row['rps']} req/s · "
              f"moy {row['mean_ms']} · méd {row['median_ms']} · p95 {row['p95_ms']} · p99 {row['p99_ms']} ms · erreurs {row['errors']} "
              f"({row['error_rate']} %) · verrous {row['sqlite_locked']} · CPU moy {row['cpu_percent_mean']} % · RSS max {row['rss_mb_max']} Mo", flush=True)
        for e in row['error_samples'][:3]:
            print('     ERREUR', e, flush=True)
        return row
    try:
        for users in levels:
            row = run_phase('palier', users)
            if row['error_rate'] > 5 or row['p95_ms'] > 30000 or (row['available_mb_min'] or 1e9) < 1024:
                report['stopped_at'] = users
                print(f'Montée en charge arrêtée à {users} utilisateurs (seuil d’erreurs, de latence ou de mémoire atteint).')
                break
        if sustain and 'stopped_at' not in report:
            run_phase(f'charge soutenue {sustain[1]} s', sustain[0], duration=sustain[1])
        with SessionLocal() as db:
            from sqlalchemy import func, select
            from app.models import AuditEvent, Document, Launch
            dup = db.execute(select(Launch.name, func.count()).group_by(Launch.name).having(func.count() > 1)).all()
            created_ok = sum(p['operations'].get('création commande', {}).get('n', 0) - p['operations'].get('création commande', {}).get('errors', 0) for p in report['phases'])
            launches = db.scalar(select(func.count()).select_from(Launch))
            audit_creates = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == 'launch.create'))
            report['integrity'] = {'launches_in_db': launches, 'creations_acknowledged': created_ok, 'audit_launch_create': audit_creates,
                                   'duplicate_names': len(dup), 'documents': db.scalar(select(func.count()).select_from(Document))}
            print('Intégrité :', report['integrity'])
    finally:
        server.terminate()
    (out / 'load-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()

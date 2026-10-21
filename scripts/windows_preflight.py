"""Contrôles préalables au démarrage local, appelés par scripts/start_windows.ps1.

    python scripts/windows_preflight.py deps                 # dépendances importables
    python scripts/windows_preflight.py code                 # syntaxe Python de app/ et scripts/
    python scripts/windows_preflight.py db                   # data, verrou SQLite, sauvegarde, migrations
    python scripts/windows_preflight.py accounts [--email E] # comptes internes et Client
    python scripts/windows_preflight.py create-admin --email E   # mot de passe lu dans FRAMATEX_SECRET_INPUT
    python scripts/windows_preflight.py seed --email E       # dossiers de démonstration A–E (idempotent)

Aucune donnée n'est supprimée. La sauvegarde utilise l'API de sauvegarde SQLite
(copie cohérente même si la base est ouverte ailleurs). Aucun mot de passe n'est
lu en argument, affiché ou écrit : create-admin le reçoit dans une variable
d'environnement propre à ce processus, retirée dès la lecture.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# module importable -> paquet pip (requirements.txt)
MODULES = {
    'fastapi': 'fastapi', 'uvicorn': 'uvicorn', 'sqlalchemy': 'sqlalchemy',
    'python_multipart|multipart': 'python-multipart', 'argon2': 'argon2-cffi', 'jwt': 'PyJWT',
    'pydantic': 'pydantic', 'openpyxl': 'openpyxl', 'pypdf': 'pypdf', 'docx': 'python-docx',
    'PIL': 'Pillow', 'pytesseract': 'pytesseract', 'fitz': 'PyMuPDF', 'qrcode': 'qrcode',
}


def ok(text):
    print(f'  [OK]   {text}', flush=True)


def warn(text):
    print(f'  [!]    {text}', flush=True)


def check_deps() -> int:
    if sys.version_info < (3, 11):
        warn(f'Python {sys.version.split()[0]} : la plateforme demande Python 3.11 ou plus récent')
        return 1
    missing = [package for modules, package in MODULES.items()
               if not any(importlib.util.find_spec(name) for name in modules.split('|'))]
    if missing:
        warn('Dépendances manquantes : ' + ', '.join(missing))
        return 1
    ok(f'Python {sys.version.split()[0]} ({sys.executable}) : toutes les dépendances sont importables')
    return 0


def check_db() -> int:
    sys.path.insert(0, str(ROOT))
    from app.core import DATA_DIR, engine  # crée data/ et la clé de session si besoin, comme le serveur

    probe = DATA_DIR / f'.ecriture-test-{os.getpid()}'
    try:
        probe.write_text('ok')
        probe.unlink()
    except OSError as exc:
        warn(f'Dossier {DATA_DIR} non accessible en écriture : {exc}')
        return 3
    ok(f'Dossier de données accessible en écriture : {DATA_DIR}')
    free = shutil.disk_usage(DATA_DIR).free
    if free < 200 * 1024 * 1024:
        warn(f'Espace disque faible : {free // (1024 * 1024)} Mo libres')

    if engine.dialect.name != 'sqlite':
        ok(f'Base {engine.dialect.name} : contrôles SQLite non applicables')
        return 0
    database = Path(engine.url.database)
    if database.exists() and database.stat().st_size:
        for suffix in ('-journal', '-wal'):
            if database.with_name(database.name + suffix).exists():
                print(f'  [..]   Fichier {database.name}{suffix} présent : SQLite le traitera à l’ouverture (ne pas le supprimer)')
        try:
            with sqlite3.connect(str(database), timeout=3) as conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.rollback()
                result = conn.execute('PRAGMA quick_check').fetchone()[0]
        except sqlite3.OperationalError as exc:
            warn(f'Base {database} verrouillée ou illisible ({exc}). Fermez le programme qui l’utilise '
                 '(ancien serveur, DB Browser for SQLite, synchronisation de fichiers) puis relancez.')
            return 2
        if result != 'ok':
            warn(f'Contrôle d’intégrité SQLite : {result}')
        else:
            ok(f'Base SQLite libre et cohérente : {database}')
        backups = DATA_DIR / 'backups'
        backups.mkdir(exist_ok=True)
        target = backups / f'{database.stem}-{datetime.now():%Y%m%d}.db'
        if target.exists():
            ok(f'Sauvegarde du jour déjà présente : {target}')
        else:
            with sqlite3.connect(str(database), timeout=3) as source, sqlite3.connect(str(target)) as copy:
                source.backup(copy)
            ok(f'Sauvegarde de la base avant démarrage : {target}')
    else:
        ok(f'Nouvelle base : elle sera créée dans {database}')

    from sqlalchemy import inspect, text
    from app.migrate import REVISIONS, migrate
    with engine.connect() as conn:
        done = set()
        if 'schema_migrations' in inspect(conn).get_table_names():
            done = {v for v, in conn.execute(text('SELECT version FROM schema_migrations'))}
    pending = [revision for revision in REVISIONS if revision not in done]
    try:
        migrate()
    except Exception as exc:  # message lisible pour le lanceur, sans trace Python
        warn(f'Migration impossible : {type(exc).__name__}: {exc}')
        return 4
    ok(f'Migrations à jour ({len(REVISIONS)} révisions' + (f', {len(pending)} appliquée(s) maintenant)' if pending else ')'))
    return 0


def check_code() -> int:
    import compileall
    import io
    from contextlib import redirect_stdout
    report = io.StringIO()
    with redirect_stdout(report):
        good = all(compileall.compile_dir(str(ROOT / folder), quiet=1, force=False)
                   for folder in ('app', 'scripts'))
    if not good:
        warn('Erreur de syntaxe Python :\n' + report.getvalue().strip())
        return 1
    ok('Code Python de app/ et scripts/ : syntaxe valide')
    return 0


def _session():
    sys.path.insert(0, str(ROOT))
    from app.core import SessionLocal
    return SessionLocal()


def check_accounts(email: str | None) -> int:
    from sqlalchemy import func, select
    with _session() as db:
        from app.client_models import ClientAccount
        from app.models import Role, User
        users = db.scalars(select(User)).all()
        admins = [u for u in users if u.active and any(r.name == 'Administrateur' for r in u.roles)]
        clients = dict(db.execute(select(ClientAccount.status, func.count()).group_by(ClientAccount.status)).all())
        ok(f"Comptes internes : {sum(u.active for u in users)} actif(s) dont {len(admins)} administrateur(s) ; "
           f"comptes Client : {clients.get('active', 0)} actif(s), {clients.get('pending', 0)} en attente, "
           f"{clients.get('suspended', 0)} suspendu(s)")
        if email:
            target = next((u for u in users if u.email == email.strip().lower()), None)
            if not target:
                print(f'  [..]   Compte {email} absent', flush=True)
                return 10
            if target not in admins:
                warn(f'Le compte {email} existe mais n’est pas un administrateur actif')
                return 11
            ok(f'Compte administrateur {email} présent et actif')
            return 0
        return 0 if admins else 12


def create_admin(email: str) -> int:
    secret = os.environ.pop('FRAMATEX_SECRET_INPUT', '')
    if not 12 <= len(secret) <= 256:
        warn('Mot de passe refusé : 12 à 256 caractères requis')
        return 1
    if '@' not in email:
        warn('Adresse email invalide')
        return 1
    from sqlalchemy import select
    with _session() as db:
        from app.core import hash_password
        from app.models import Role, User
        email = email.strip().lower()
        if db.scalar(select(User).where(User.email == email)):
            warn(f'Le compte {email} existe déjà : aucun changement')
            return 1
        role = db.scalar(select(Role).where(Role.name == 'Administrateur')) or Role(name='Administrateur')
        db.add(User(email=email, name='Administrateur de test', password_hash=hash_password(secret), roles=[role]))
        db.commit()
    del secret
    ok(f'Compte administrateur {email} créé (mot de passe non enregistré en clair)')
    return 0


def seed_demo(email: str) -> int:
    from sqlalchemy import select
    with _session() as db:
        from app.models import Launch, User
        from app.seed_operations_demo import SCENARIOS, seed
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user:
            warn(f'Compte {email} introuvable : démonstration non chargée')
            return 1
        refs = [reference for reference, *_ in SCENARIOS.values()]
        before = set(db.scalars(select(Launch.order_ref).where(Launch.order_ref.in_(refs))))
        seed(db, user)
        db.commit()
    created = len(refs) - len(before)
    ok(f'Dossiers de démonstration A–E disponibles : {created} créé(s), {len(before)} déjà présent(s), aucun doublon')
    return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Contrôles préalables FRAMATEX')
    parser.add_argument('command', choices=('deps', 'code', 'db', 'accounts', 'create-admin', 'seed'))
    parser.add_argument('--email')
    args = parser.parse_args()
    if args.command in ('create-admin', 'seed') and not args.email:
        parser.error('--email est requis')
    handlers = {'deps': check_deps, 'code': check_code, 'db': check_db,
                'accounts': lambda: check_accounts(args.email),
                'create-admin': lambda: create_admin(args.email), 'seed': lambda: seed_demo(args.email)}
    sys.exit(handlers[args.command]())

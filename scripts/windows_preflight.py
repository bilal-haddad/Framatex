"""Contrôles préalables au démarrage local, appelés par scripts/start_windows.ps1.

    python scripts/windows_preflight.py deps   # dépendances importables
    python scripts/windows_preflight.py db     # dossier data, verrou SQLite, sauvegarde, migration

Aucune donnée n'est supprimée. La sauvegarde utilise l'API de sauvegarde SQLite
(copie cohérente même si la base est ouverte ailleurs).
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


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'deps'
    sys.exit({'deps': check_deps, 'db': check_db}[command]())

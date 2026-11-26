"""Administration de la base FRAMATEX (moteur choisi par DATABASE_URL).

    python -m app.db status      révision appliquée et attendue
    python -m app.db upgrade     applique les migrations (un seul processus à la fois)
    python -m app.db downgrade <révision>   retour arrière PostgreSQL (après sauvegarde !)
    python -m app.db check       base joignable, schéma à jour, extensions de recherche présentes
"""
import sys

from sqlalchemy import text

from .core import engine
from .migrate import migrate


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:]) or ['status']
    command = args[0]
    postgres = engine.dialect.name == 'postgresql'
    if command == 'upgrade':
        print('Révision :', migrate()[-1]); return 0
    if command == 'downgrade':
        if not postgres or len(args) < 2:
            print('Retour arrière disponible pour PostgreSQL uniquement : python -m app.db downgrade <révision>'); return 2
        from alembic import command as alembic_command
        from .migrate import _alembic_config
        alembic_command.downgrade(_alembic_config(), args[1]); print('Révision ramenée à', args[1]); return 0
    if postgres:
        from .migrate import postgresql_heads
        current, head = postgresql_heads()
        print(f'Moteur : PostgreSQL ({engine.url.host}:{engine.url.port}/{engine.url.database}) · révision {current} · attendue {head}')
        if command == 'check':
            with engine.connect() as conn:
                extensions = set(conn.execute(text('SELECT extname FROM pg_extension')).scalars())
            missing = {'unaccent', 'pg_trgm'} - extensions
            ok = current == head and not missing
            print('Extensions manquantes :', ', '.join(sorted(missing)) if missing else 'aucune')
            print('Vérification :', 'OK' if ok else 'ÉCHEC'); return 0 if ok else 1
        return 0 if current == head else 1
    with engine.connect() as conn:
        done = set(conn.execute(text('SELECT version FROM schema_migrations')).scalars()) if engine.dialect.has_table(conn, 'schema_migrations') else set()
    from .migrate import REVISIONS
    print(f'Moteur : SQLite ({engine.url.database}) · révisions appliquées {len(done)}/{len(REVISIONS)}')
    return 0 if set(REVISIONS) <= done else 1


if __name__ == '__main__':
    sys.exit(main())

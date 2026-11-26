"""Base de recette isolée : SQLite temporaire (défaut) ou base PostgreSQL neuve et jetable.

Si FRAMATEX_RECETTE_DATABASE_URL désigne un serveur PostgreSQL (rôle autorisé à créer des bases,
mot de passe via PGPASSWORD), chaque recette crée une base vide dédiée, y applique les migrations
au démarrage (FRAMATEX_AUTO_MIGRATE=1, comme le migrateur SQLite) et la supprime à la fin.
Sinon DATABASE_URL est retirée : la recette utilise SQLite dans son dossier temporaire (inchangé).
"""
import atexit
import os
import uuid


def use_isolated_database(env=None):
    env = os.environ if env is None else env
    base = os.getenv("FRAMATEX_RECETTE_DATABASE_URL", "")
    if not base.startswith(("postgresql", "postgres")):
        env.pop("DATABASE_URL", None)
        if env is not os.environ:
            os.environ.pop("DATABASE_URL", None)
        return None
    import psycopg
    admin = base.replace("postgresql+psycopg://", "postgresql://", 1)
    name = f"framatex_recette_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING \'UTF8\'')
    url = base.rsplit("/", 1)[0] + "/" + name
    for target in {id(env): env, id(os.environ): os.environ}.values():
        target["DATABASE_URL"] = url
        target["FRAMATEX_AUTO_MIGRATE"] = "1"

    def drop():
        try:
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except psycopg.Error:
            pass
    atexit.register(drop)
    return url

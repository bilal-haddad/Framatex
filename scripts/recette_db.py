"""Base PostgreSQL neuve et jetable pour chaque recette.

FRAMATEX_RECETTE_DATABASE_URL doit désigner une base de maintenance PostgreSQL. Il n'existe plus de
repli automatique SQLite : une recette mal configurée échoue avant de créer la moindre donnée.
"""
import atexit
import os
import uuid


def use_isolated_database(env=None):
    env = os.environ if env is None else env
    # Exception strictement réservée au générateur de fixture d'import historique.
    # Les recettes courantes n'activent jamais ces deux drapeaux et restent PostgreSQL-only.
    if (env.get("FRAMATEX_BUILD_LEGACY_FIXTURE") == "1" and
            env.get("FRAMATEX_LEGACY_SQLITE_MODE") == "1"):
        from pathlib import Path
        url = "sqlite:///" + str(Path(env["FRAMATEX_DATA_DIR"]) / "framat.db")
        for target in {id(env): env, id(os.environ): os.environ}.values():
            target["DATABASE_URL"] = url
            target["FRAMATEX_LEGACY_SQLITE_MODE"] = "1"
            target["FRAMATEX_BUILD_LEGACY_FIXTURE"] = "1"
        return url
    base = os.getenv("FRAMATEX_RECETTE_DATABASE_URL", "")
    if not base.startswith(("postgresql", "postgres")):
        raise RuntimeError("FRAMATEX_RECETTE_DATABASE_URL PostgreSQL est obligatoire pour les recettes.")
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

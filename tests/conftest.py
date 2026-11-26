"""Configuration commune des tests.

Les tests s'exécutent sur SQLite par défaut (base temporaire). Pour les exécuter sur PostgreSQL :
    DATABASE_URL=postgresql+psycopg://framatex@127.0.0.1:5432/framatex_test PGPASSWORD=… pytest
(la base doit être vide : le schéma y est créé par les migrations Alembic au début de la session).
"""
import os
import secrets
import tempfile

os.environ.setdefault("FRAMATEX_DATA_DIR", tempfile.mkdtemp(prefix="framat-test-"))
os.environ.setdefault("FRAMATEX_SECRET_KEY", "test-secret-" * 6)
os.environ.setdefault("FRAMATEX_ACCESS_LOG", "0")


POSTGRES = os.environ.get("DATABASE_URL", "").startswith(("postgresql", "postgres"))
if POSTGRES:
    # Les tests recréent librement la base (drop_all / create_all) puis démarrent l'application, comme
    # SQLite le permet. Sous PostgreSQL, la version Alembic et l'index de recherche suivent ces
    # opérations ; le démarrage applique alors les migrations manquantes (comme le migrateur SQLite).
    os.environ.setdefault("FRAMATEX_AUTO_MIGRATE", "1")


def _install_postgres_listeners():
    from sqlalchemy import event, inspect, text
    from app.core import Base

    @event.listens_for(Base.metadata, "after_drop")
    def _after_drop(target, connection, **kw):
        if connection.dialect.name != "postgresql":
            return
        connection.execute(text("DROP TABLE IF EXISTS document_search_index"))
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    @event.listens_for(Base.metadata, "after_create")
    def _after_create(target, connection, **kw):
        if connection.dialect.name != "postgresql" or "alembic_version" in inspect(connection).get_table_names():
            return
        from alembic import command
        from app.migrate import _alembic_config
        config = _alembic_config()
        config.attributes["connection"] = connection
        command.stamp(config, "0019")              # tables créées par create_all
        command.upgrade(config, "head")            # objets de recherche (0020)


def pytest_sessionstart(session):
    if POSTGRES:
        import app.all_models  # noqa: F401
        from app.migrate import migrate
        _install_postgres_listeners()
        migrate()


def pytest_report_header(config):
    url = os.environ.get("DATABASE_URL", "")
    return f"base de test : {'PostgreSQL' if url.startswith(('postgresql', 'postgres')) else 'SQLite (temporaire)'}"


def reset_database():
    """Base vide puis schéma à jour, selon le moteur (SQLite : le démarrage de l'application recrée le
    schéma ; PostgreSQL : migrations Alembic explicites, comme en exploitation)."""
    from sqlalchemy import text
    from app.core import Base, engine
    Base.metadata.drop_all(engine)
    if engine.dialect.name == "postgresql":
        from app.migrate import migrate
        migrate()

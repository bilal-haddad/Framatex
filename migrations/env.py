"""Environnement Alembic : PostgreSQL uniquement, adresse lue dans DATABASE_URL (jamais dans un fichier)."""
from alembic import context

import app.all_models  # noqa: F401  (enregistre toutes les tables dans les métadonnées)
from app.core import Base, engine

if engine.dialect.name != "postgresql":
    raise SystemExit("Alembic gère la base PostgreSQL ; SQLite garde son migrateur historique (app/migrate.py).")

target_metadata = Base.metadata
# Objets gérés par des révisions écrites à la main (recherche plein texte) : ignorés par la comparaison.
MANUAL_OBJECTS = {"document_search_index", "ix_document_search_index_vector"}


def include_object(obj, name, type_, reflected, compare_to):
    return name not in MANUAL_OBJECTS


def _configure(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      transaction_per_migration=True, include_object=include_object)


if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:                        # connexion fournie : verrou consultatif détenu par l'appelant
        _configure(supplied)
        with context.begin_transaction():
            context.run_migrations()
    else:
        with engine.connect() as connection:
            _configure(connection)
            with context.begin_transaction():
                context.run_migrations()

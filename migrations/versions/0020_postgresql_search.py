"""Recherche plein texte PostgreSQL (remplace l'index FTS5 de SQLite)

Révision : 0020
Précédente : 0019

- unaccent (fonction enveloppe IMMUTABLE, indexable) : recherche insensible aux accents ;
- pg_trgm : disponible pour des recherches approchées ultérieures ;
- table document_search_index : texte analysé (OCR compris), titre et références métier de chaque
  version, vecteur tsvector généré (configuration « simple » : codes et références non racinisés)
  et index GIN. Les droits sont appliqués par l'application avant toute restitution.
"""
from alembic import op
import sqlalchemy as sa

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""CREATE OR REPLACE FUNCTION framatex_unaccent(text) RETURNS text
                  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
                  AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$""")
    op.create_table(
        'document_search_index',
        # Sans clé étrangère, comme l'index FTS5 SQLite : index dérivé, reconstruisible, purgé explicitement ;
        # les résultats sont toujours rejoints aux versions actives et autorisées.
        sa.Column('version_id', sa.String(36), primary_key=True),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('title', sa.Text(), nullable=False, server_default=''),
        sa.Column('references', sa.Text(), nullable=False, server_default=''),
    )
    op.execute("""ALTER TABLE document_search_index ADD COLUMN search_vector tsvector
                  GENERATED ALWAYS AS (to_tsvector('simple', framatex_unaccent(lower(
                      title || ' ' || "references" || ' ' || content)))) STORED""")
    op.execute("CREATE INDEX ix_document_search_index_vector ON document_search_index USING gin (search_vector)")


def downgrade():
    op.drop_table('document_search_index')
    op.execute("DROP FUNCTION IF EXISTS framatex_unaccent(text)")

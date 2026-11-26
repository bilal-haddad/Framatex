"""Versioned, repeatable SQLite migrations for Framatex MVP.

Usage: python -m app.migrate status | upgrade
The CLI backs up an existing file before applying schema changes. Production
migration requires a maintenance window and independent backup verification.
"""
from __future__ import annotations
import argparse
import sqlite3
import shutil
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import inspect, text, Table, Column, String
from .core import Base, engine

# Import every registered model before inspecting metadata.
from . import models, completeness_models, workflow_models, quality_models, intake_models  # noqa: F401
from . import spec_models, mail_models, impact_sim_models, orli_models, material_models # noqa: F401
from . import approval_models, sharing_models, pilot_models # noqa: F401
from . import client_models # noqa: F401
from . import internal_models # noqa: F401
from . import client_workflow_models # noqa: F401
from . import document_intake_models # noqa: F401
from . import document_intelligence_models # noqa: F401
from . import access_models # noqa: F401  (0013_access_management)

# Include the migration ledger in SQLAlchemy metadata so test databases that
# reset Base.metadata also reset this ledger; production upgrades remain explicit.
MIGRATION_TABLE = Table('schema_migrations', Base.metadata,
                        Column('version', String(80), primary_key=True),
                        Column('applied_at', String(50), nullable=False), extend_existing=True)

REVISIONS = ('0001_baseline', '0002_launch_scope', '0003_pilot_reports', '0004_client_space',
             '0005_internal_operations', '0006_client_workflow', '0007_client_order_launch',
             '0008_optional_rules', '0009_visible_checklist_duplicates', '0010_document_intake',
             '0011_business_memory', '0012_document_intelligence', '0012b_document_search',
             '0013_access_management', '0014_business_memory_folder_access',
             '0015_document_soft_deletion', '0016_order_sheet', '0017_optional_documents', '0018_document_purge')


def _versions(conn):
    conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(80) PRIMARY KEY, applied_at VARCHAR(50) NOT NULL)'))
    return {v for v, in conn.execute(text('SELECT version FROM schema_migrations'))}


def migrate():
    if engine.dialect.name != 'sqlite':
        raise RuntimeError('Le migrateur MVP gère SQLite seulement. Ne pas démarrer sur une base PostgreSQL sans migrations spécifiques.')
    # Back up the real SQLite database before any legacy ALTER TABLE.
    with engine.connect() as probe:
        tables = set(inspect(probe).get_table_names())
        legacy = ('launches' in tables and
                  'restricted' not in {c['name'] for c in inspect(probe).get_columns('launches')})
        has_migrations = 'schema_migrations' in tables
        pending = has_migrations and set(REVISIONS).difference({
            v for v, in probe.execute(text('SELECT version FROM schema_migrations'))})
    if legacy or pending:
        saved = backup_sqlite()
        if saved:
            print('Sauvegarde automatique avant migration :', saved)
    with engine.begin() as conn:
        done = _versions(conn)
        unknown = done.difference(REVISIONS)
        if unknown:
            raise RuntimeError(f'Révisions non reconnues: {sorted(unknown)}')
        if '0001_baseline' not in done:
            existing = set(inspect(conn).get_table_names())
            if 'launches' in existing:
                expected = {'users','roles','launches','folders','documents','document_versions'}
                if not expected.issubset(existing):
                    raise RuntimeError('Schéma existant partiel : migration interrompue pour éviter une perte de données')
                # Old 0.14 installations must contain the complete pre-0.15 schema.
                later_tables = {'schema_migrations', 'launch_members', 'pilot_reports',
                                'client_accounts', 'client_order_requests',
                                'client_order_documents', 'client_order_document_versions',
                                'launch_operations', 'internal_document_comments', 'internal_experience_notes',
                                'client_document_requests', 'client_document_request_events', 'client_shared_documents',
                                'client_order_launches', 'document_duplicate_reviews',
                                'pending_document_uploads', 'document_identifications',
                                'business_partners', 'business_partner_aliases', 'launch_partners',
                                'internal_experience_decisions', 'collaborator_profiles',
                                'launch_assignments', 'legacy_access_proposals', 'optional_document_cases', 'storage_purge_queue', 'retention_clearances'}
                missing = (set(Base.metadata.tables) - later_tables) - existing
                if missing:
                    raise RuntimeError('Base antérieure incomplète : tables manquantes : ' + ', '.join(sorted(missing)))
            else:
                # A new installation initializes its full contemporary schema.
                Base.metadata.create_all(bind=conn)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                        {'v':'0001_baseline','d':datetime.now(timezone.utc).isoformat()})
        if '0002_launch_scope' not in done:
            cols = {c['name'] for c in inspect(conn).get_columns('launches')}
            if 'restricted' not in cols:
                conn.execute(text('ALTER TABLE launches ADD COLUMN restricted BOOLEAN NOT NULL DEFAULT 0'))
            conn.execute(text("""CREATE TABLE IF NOT EXISTS launch_members (
              id VARCHAR(36) PRIMARY KEY,
              launch_id VARCHAR(36) NOT NULL REFERENCES launches(id),
              user_id VARCHAR(36) NOT NULL REFERENCES users(id),
              granted_by VARCHAR(36) NOT NULL REFERENCES users(id),
              created_at DATETIME NOT NULL,
              CONSTRAINT uq_launch_member UNIQUE(launch_id,user_id)
            )"""))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_launch_members_launch_id ON launch_members (launch_id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_launch_members_user_id ON launch_members (user_id)'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                        {'v':'0002_launch_scope','d':datetime.now(timezone.utc).isoformat()})
        if '0003_pilot_reports' not in done:
            Base.metadata.tables['pilot_reports'].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0003_pilot_reports','d':datetime.now(timezone.utc).isoformat()})
        if '0004_client_space' not in done:
            for table_name in ('client_accounts', 'client_order_requests',
                               'client_order_documents', 'client_order_document_versions'):
                Base.metadata.tables[table_name].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0004_client_space','d':datetime.now(timezone.utc).isoformat()})
        if '0005_internal_operations' not in done:
            for table_name in ('launch_operations', 'internal_document_comments', 'internal_experience_notes'):
                Base.metadata.tables[table_name].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0005_internal_operations','d':datetime.now(timezone.utc).isoformat()})
        if '0006_client_workflow' not in done:
            for table_name in ('client_document_requests', 'client_document_request_events', 'client_shared_documents'):
                Base.metadata.tables[table_name].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0006_client_workflow','d':datetime.now(timezone.utc).isoformat()})
        if '0007_client_order_launch' not in done:
            # Additif : lien demande Client -> Dossier Jaune ; aucune table existante modifiée.
            Base.metadata.tables['client_order_launches'].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0007_client_order_launch','d':datetime.now(timezone.utc).isoformat()})
        if '0008_optional_rules' not in done:
            # Additif : une règle peut être facultative ; toutes les règles existantes restent obligatoires.
            if 'required' not in {c['name'] for c in inspect(conn).get_columns('completeness_rules')}:
                conn.execute(text('ALTER TABLE completeness_rules ADD COLUMN required BOOLEAN NOT NULL DEFAULT 1'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0008_optional_rules','d':datetime.now(timezone.utc).isoformat()})
        if '0009_visible_checklist_duplicates' not in done:
            # Additif : décisions sur les doublons ; et checklist standard entièrement visible
            # et exigible dès la création du Dossier Jaune (règles obligatoires du profil standard).
            Base.metadata.tables['document_duplicate_reviews'].create(bind=conn, checkfirst=True)
            conn.execute(text("UPDATE completeness_rules SET due_phase = 'preparation' WHERE required = 1 AND profile_id IN "
                              "(SELECT id FROM completeness_profiles WHERE name = 'Dossier Jaune FRAMATEX standard')"))
            # La réception matière est contrôlée avant d'être comptée présente.
            conn.execute(text("UPDATE completeness_rules SET requires_validation = 1 WHERE title = 'Document de réception matière' AND profile_id IN "
                              "(SELECT id FROM completeness_profiles WHERE name = 'Dossier Jaune FRAMATEX standard')"))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0009_visible_checklist_duplicates','d':datetime.now(timezone.utc).isoformat()})
        if '0010_document_intake' not in done:
            for name in ('pending_document_uploads', 'document_identifications'):
                Base.metadata.tables[name].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0010_document_intake','d':datetime.now(timezone.utc).isoformat()})
        if '0011_business_memory' not in done:
            for name in ('business_partners', 'business_partner_aliases', 'launch_partners'):
                Base.metadata.tables[name].create(bind=conn, checkfirst=True)
            columns = {c['name']: c for c in inspect(conn).get_columns('internal_experience_notes')}
            if columns['launch_id']['nullable'] is False:
                # SQLite cannot relax NOT NULL in place. This table has no incoming FK in
                # the historical schema; copy every row and preserve its primary key.
                conn.execute(text('''CREATE TABLE internal_experience_notes_new (
                    id VARCHAR(36) PRIMARY KEY, launch_id VARCHAR(36) REFERENCES launches(id),
                    party_type VARCHAR(20) NOT NULL, party_name VARCHAR(150) NOT NULL,
                    category VARCHAR(30) NOT NULL, body TEXT NOT NULL,
                    author_id VARCHAR(36) NOT NULL REFERENCES users(id), created_at DATETIME NOT NULL)'''))
                conn.execute(text('''INSERT INTO internal_experience_notes_new
                    SELECT id, launch_id, party_type, party_name, category, body, author_id, created_at
                    FROM internal_experience_notes'''))
                conn.execute(text('DROP TABLE internal_experience_notes'))
                conn.execute(text('ALTER TABLE internal_experience_notes_new RENAME TO internal_experience_notes'))
            columns = {c['name'] for c in inspect(conn).get_columns('internal_experience_notes')}
            for name, spec in (
                ('partner_id', 'VARCHAR(36) REFERENCES business_partners(id)'),
                ('event_date', 'DATE'),
                ('importance', "VARCHAR(20) NOT NULL DEFAULT 'information'"),
                ('status', "VARCHAR(20) NOT NULL DEFAULT 'open'"),
                ('recommendation', 'TEXT'),
                ('evidence_version_id', 'VARCHAR(36) REFERENCES document_versions(id)'),
                ('updated_at', 'DATETIME'),
            ):
                if name not in columns:
                    conn.execute(text(f'ALTER TABLE internal_experience_notes ADD COLUMN {name} {spec}'))
            conn.execute(text('UPDATE internal_experience_notes SET updated_at = created_at WHERE updated_at IS NULL'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_internal_experience_notes_launch_id ON internal_experience_notes (launch_id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_internal_experience_notes_party_type ON internal_experience_notes (party_type)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_internal_experience_notes_party_name ON internal_experience_notes (party_name)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_internal_experience_notes_partner_id ON internal_experience_notes (partner_id)'))
            Base.metadata.tables['internal_experience_decisions'].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0011_business_memory','d':datetime.now(timezone.utc).isoformat()})
        if '0012_document_intelligence' not in done:
            Base.metadata.tables['document_relationship_decisions'].create(bind=conn, checkfirst=True)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0012_document_intelligence','d':datetime.now(timezone.utc).isoformat()})
        if '0012b_document_search' not in done:
            conn.execute(text('''CREATE VIRTUAL TABLE IF NOT EXISTS document_content_fts
                USING fts5(version_id UNINDEXED, content, title, "references", tokenize='unicode61')'''))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0012b_document_search','d':datetime.now(timezone.utc).isoformat()})
        if '0013_access_management' not in done:
            # Habilitations par commande : voir app/access_migration.py (aucun droit ouvert automatiquement).
            from .access_migration import migrate_0013
            migrate_0013(conn, Base.metadata)
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0013_access_management','d':datetime.now(timezone.utc).isoformat()})
        if '0014_business_memory_folder_access' not in done:
            # Additive and deliberately nullable: historical notes cannot be
            # inferred reliably and therefore remain chef-only until classified.
            columns = {c['name'] for c in inspect(conn).get_columns('internal_experience_notes')}
            if 'folder_slug' not in columns:
                conn.execute(text('ALTER TABLE internal_experience_notes ADD COLUMN folder_slug VARCHAR(12)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_internal_experience_notes_folder_slug '
                              'ON internal_experience_notes (folder_slug)'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0014_business_memory_folder_access','d':datetime.now(timezone.utc).isoformat()})
        if '0015_document_soft_deletion' not in done:
            # Additive logical deletion: historical files and versions remain intact.
            for table, columns in {
                'documents': (('deleted_at', 'DATETIME'), ('deleted_by', 'VARCHAR(36) REFERENCES users(id)'), ('deletion_reason', 'TEXT')),
                'document_versions': (('deleted_at', 'DATETIME'), ('deleted_by', 'VARCHAR(36) REFERENCES users(id)'), ('deletion_reason', 'TEXT')),
            }.items():
                existing = {c['name'] for c in inspect(conn).get_columns(table)}
                for name, spec in columns:
                    if name not in existing:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {spec}'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_documents_deleted_at ON documents (deleted_at)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_document_versions_deleted_at ON document_versions (deleted_at)'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0015_document_soft_deletion','d':datetime.now(timezone.utc).isoformat()})
        if '0016_order_sheet' not in done:
            # Fiche commande complète et demandes Client enrichies : colonnes additives, NULL = non renseigné.
            for table, columns in {
                'launch_operations': (('description', 'TEXT'), ('workshop', 'VARCHAR(150)'), ('color', 'VARCHAR(80)'),
                                      ('of_number', 'VARCHAR(60)'), ('quantity_launched', 'INTEGER'), ('quantity_delivered', 'INTEGER'),
                                      ('invoice_ref', 'VARCHAR(100)'), ('desired_date', 'DATE'), ('client_order_ref', 'VARCHAR(100)'),
                                      ('client_account_id', 'VARCHAR(36) REFERENCES client_accounts(id)')),
                'client_order_requests': (('project_name', 'VARCHAR(180)'), ('description', 'TEXT'), ('color', 'VARCHAR(80)')),
            }.items():
                existing = {c['name'] for c in inspect(conn).get_columns(table)}
                for name, spec in columns:
                    if name not in existing:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {spec}'))
            for name, table, column in (('ix_launch_operations_workshop', 'launch_operations', 'workshop'),
                                        ('ix_launch_operations_color', 'launch_operations', 'color'),
                                        ('ix_launch_operations_of_number', 'launch_operations', 'of_number'),
                                        ('ix_launch_operations_invoice_ref', 'launch_operations', 'invoice_ref'),
                                        ('ix_launch_operations_client_order_ref', 'launch_operations', 'client_order_ref'),
                                        ('ix_launch_operations_client_account_id', 'launch_operations', 'client_account_id'),
                                        ('ix_launches_order_ref', 'launches', 'order_ref'),
                                        ('ix_launches_client_name', 'launches', 'client_name')):
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0016_order_sheet','d':datetime.now(timezone.utc).isoformat()})
        if '0017_optional_documents' not in done:
            # Documents complémentaires facultatifs : table des cases et rattachement additif des documents.
            conn.execute(text("""CREATE TABLE IF NOT EXISTS optional_document_cases (
              id VARCHAR(36) PRIMARY KEY,
              launch_id VARCHAR(36) NOT NULL REFERENCES launches(id),
              folder_slug VARCHAR(12) NOT NULL,
              title VARCHAR(160) NOT NULL,
              description TEXT,
              created_by VARCHAR(36) NOT NULL REFERENCES users(id),
              created_at DATETIME NOT NULL,
              updated_at DATETIME,
              deleted_at DATETIME,
              deleted_by VARCHAR(36) REFERENCES users(id))"""))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_optional_document_cases_launch_folder ON optional_document_cases (launch_id, folder_slug)'))
            if 'optional_case_id' not in {c['name'] for c in inspect(conn).get_columns('documents')}:
                conn.execute(text('ALTER TABLE documents ADD COLUMN optional_case_id VARCHAR(36) REFERENCES optional_document_cases(id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_documents_optional_case_id ON documents (optional_case_id)'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0017_optional_documents','d':datetime.now(timezone.utc).isoformat()})
        if '0018_document_purge' not in done:
            # Suppression définitive : file d'effacement des fichiers et vérifications de conservation.
            conn.execute(text("""CREATE TABLE IF NOT EXISTS storage_purge_queue (
              id VARCHAR(36) PRIMARY KEY, disk_name VARCHAR(80) NOT NULL, created_at DATETIME NOT NULL,
              done_at DATETIME, outcome VARCHAR(40))"""))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_storage_purge_queue_disk_name ON storage_purge_queue (disk_name)'))
            conn.execute(text("""CREATE TABLE IF NOT EXISTS retention_clearances (
              id VARCHAR(36) PRIMARY KEY, document_id VARCHAR(36) NOT NULL, version_id VARCHAR(36),
              reason TEXT NOT NULL, cleared_by VARCHAR(36) NOT NULL REFERENCES users(id), cleared_at DATETIME NOT NULL)"""))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_retention_clearances_document_id ON retention_clearances (document_id)'))
            # Index de performance mesurés (P0 optimisation) : versions par document, audit par cible et par date.
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_document_versions_document_id ON document_versions (document_id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_document_versions_sha256 ON document_versions (sha256)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_audit_events_target_id ON audit_events (target_id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_audit_events_occurred_at ON audit_events (occurred_at)'))
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v, :d)'),
                         {'v':'0018_document_purge','d':datetime.now(timezone.utc).isoformat()})
        # Defensive consistency check: pre-0.15 historical tables stay untouched.
        cols = {c['name'] for c in inspect(conn).get_columns('launches')}
        if 'restricted' not in cols or 'launch_members' not in inspect(conn).get_table_names():
            raise RuntimeError('Schéma de portée incohérent')
    return REVISIONS


def backup_sqlite():
    url = engine.url
    if url.database in (None, ':memory:'):
        return None
    src = Path(url.database)
    if not src.exists() or src.stat().st_size == 0:
        return None
    dest = src.with_name(f'{src.name}.backup-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}')
    with sqlite3.connect(str(src)) as origin, sqlite3.connect(str(dest)) as backup:
        origin.backup(backup)
    return dest


def main():
    p = argparse.ArgumentParser(description='Migrations SQLite Framatex')
    p.add_argument('command', choices=('status','upgrade'), nargs='?', default='status')
    args = p.parse_args()
    if args.command == 'status':
        with engine.connect() as conn:
            if 'schema_migrations' not in inspect(conn).get_table_names():
                print('Base sans version : migration nécessaire')
            else:
                print('Révisions appliquées :',', '.join(r for r, in conn.execute(text('SELECT version FROM schema_migrations ORDER BY version'))))
        return
    print('Schéma à jour :', ', '.join(migrate()))


if __name__ == '__main__':
    main()

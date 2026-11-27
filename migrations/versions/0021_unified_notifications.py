"""Centre de notifications unifié interne et Client.

Révision : 0021
Précédente : 0020
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "unified_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipient_type", sa.String(12), nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=False),
        sa.Column("event_key", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(12), nullable=False, server_default="normal"),
        sa.Column("action_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("action_label", sa.String(120), nullable=False, server_default=""),
        sa.Column("target_kind", sa.String(50), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("launch_id", sa.String(36), sa.ForeignKey("launches.id"), nullable=True),
        sa.Column("folder_slug", sa.String(10), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("recipient_type IN ('internal','client')", name="ck_unified_notification_recipient_type"),
        sa.CheckConstraint("priority IN ('low','normal','high','urgent')", name="ck_unified_notification_priority"),
        sa.UniqueConstraint("recipient_type", "recipient_id", "event_key", name="uq_unified_notification_recipient_event"),
    )
    op.create_index("ix_unified_notifications_recipient", "unified_notifications",
                    ["recipient_type", "recipient_id", "created_at"])
    op.create_index("ix_unified_notifications_actions", "unified_notifications",
                    ["recipient_type", "recipient_id", "action_required", "resolved_at"])
    op.create_index(op.f("ix_unified_notifications_launch_id"), "unified_notifications", ["launch_id"])
    # Historique 0.13 conservé sans doublon. Les événements de validation et d'impact
    # deviennent des actions ; les dates et états de lecture originaux sont préservés.
    op.execute("""
        INSERT INTO unified_notifications
          (id, recipient_type, recipient_id, event_key, kind, title, message, priority,
           action_required, action_label, target_kind, target_id, launch_id, folder_slug,
           metadata_json, created_at, updated_at, read_at)
        SELECT id, 'internal', recipient_id, event_key, kind, title, message,
               CASE WHEN kind IN ('approval','impact','quality_recheck') THEN 'high' ELSE 'normal' END,
               kind IN ('approval','impact','quality_recheck'), 'Ouvrir le dossier', 'launch', launch_id,
               launch_id, folder_slug, '{}', created_at, created_at, read_at
        FROM internal_notifications
        ON CONFLICT (recipient_type, recipient_id, event_key) DO NOTHING
    """)
    # Les demandes historiques encore à traiter restent visibles sans recréer de
    # commande. En particulier, une demande acceptée sans lien ClientOrderLaunch
    # reçoit l'action de rattrapage « créer le Dossier Jaune ».
    op.execute("""
        INSERT INTO unified_notifications
          (id, recipient_type, recipient_id, event_key, kind, title, message, priority,
           action_required, action_label, target_kind, target_id, metadata_json,
           created_at, updated_at)
        SELECT 'N' || substr(md5(u.id || ':' || r.id), 1, 35),
               'internal', u.id, 'client-order:' || r.id, 'client_order',
               CASE WHEN r.status = 'accepted'
                    THEN 'Demande acceptée — Dossier Jaune à créer'
                    ELSE 'Demande de commande à traiter' END,
               c.raison_sociale || ' · client ' || c.client_code || ' · demande ' || r.request_number ||
                 ' · ' || coalesce(r.project_name, 'Projet non nommé') || ' · ' || r.article ||
                 ' · ' || r.quantite::text || ' pièces',
               'high', true,
               CASE WHEN r.status = 'accepted' THEN 'Créer le Dossier Jaune' ELSE 'Examiner la demande' END,
               'client_order_request', r.id, '{}', r.created_at, r.updated_at
        FROM client_order_requests r
        JOIN client_accounts c ON c.id = r.client_id
        CROSS JOIN (
          SELECT DISTINCT users.id
          FROM users JOIN user_roles ur ON ur.user_id = users.id
          JOIN roles ro ON ro.id = ur.role_id
          WHERE users.active = true AND lower(ro.name) IN ('chef', 'administrateur', 'admin')
        ) u
        LEFT JOIN client_order_launches l ON l.order_request_id = r.id
        WHERE r.status IN ('submitted', 'under_review', 'accepted')
          AND (r.status <> 'accepted' OR l.order_request_id IS NULL)
        ON CONFLICT (recipient_type, recipient_id, event_key) DO NOTHING
    """)


def downgrade():
    op.drop_table("unified_notifications")


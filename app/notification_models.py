"""Centre persistant de notifications, commun aux comptes internes et Client."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .core import Base, utcnow
from .models import uid


class UnifiedNotification(Base):
    __tablename__ = "unified_notifications"
    __table_args__ = (
        CheckConstraint("recipient_type IN ('internal','client')", name="ck_unified_notification_recipient_type"),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="ck_unified_notification_priority"),
        UniqueConstraint("recipient_type", "recipient_id", "event_key", name="uq_unified_notification_recipient_event"),
        Index("ix_unified_notifications_recipient", "recipient_type", "recipient_id", "created_at"),
        Index("ix_unified_notifications_actions", "recipient_type", "recipient_id", "action_required", "resolved_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    recipient_type: Mapped[str] = mapped_column(String(12))
    # Destinataire polymorphe : users.id ou client_accounts.id selon recipient_type.
    recipient_id: Mapped[str] = mapped_column(String(36))
    event_key: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(220))
    message: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(12), default="normal")
    action_required: Mapped[bool] = mapped_column(Boolean, default=False)
    action_label: Mapped[str] = mapped_column(String(120), default="")
    target_kind: Mapped[str] = mapped_column(String(50), default="")
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    launch_id: Mapped[str | None] = mapped_column(ForeignKey("launches.id"), nullable=True, index=True)
    folder_slug: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


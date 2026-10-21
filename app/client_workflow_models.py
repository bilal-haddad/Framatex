"""Workflows Client réels, sans lien automatique avec les documents internes."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from .core import Base, utcnow
from .models import uid


class ClientDocumentRequest(Base):
    __tablename__ = "client_document_requests"
    __table_args__ = (CheckConstraint(
        "status IN ('requested','uploaded','under_review','accepted','correction_required')",
        name="ck_client_document_request_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey("client_accounts.id"), index=True)
    order_request_id: Mapped[str] = mapped_column(ForeignKey("client_order_requests.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="requested", index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("client_order_documents.id"), nullable=True, unique=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": revision}


class ClientDocumentRequestEvent(Base):
    """Historique métier adressé au client ; ce n'est pas le journal d'audit interne."""
    __tablename__ = "client_document_request_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_request_id: Mapped[str] = mapped_column(ForeignKey("client_document_requests.id"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    version_id: Mapped[str | None] = mapped_column(ForeignKey("client_order_document_versions.id"), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    actor_type: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClientSharedDocument(Base):
    __tablename__ = "client_shared_documents"
    __table_args__ = (
        CheckConstraint("status IN ('published','revoked')", name="ck_client_shared_document_status"),
        Index("uq_client_shared_active_version", "client_id", "document_version_id", unique=True,
              sqlite_where=text("status = 'published'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey("client_accounts.id"), index=True)
    order_request_id: Mapped[str | None] = mapped_column(ForeignKey("client_order_requests.id"), nullable=True, index=True)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    status: Mapped[str] = mapped_column(String(20), default="published", index=True)
    reason: Mapped[str] = mapped_column(Text)
    published_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClientOrderLaunch(Base):
    """Lien permanent entre une demande Client et le Dossier Jaune ouvert pour elle.

    La clé primaire sur la demande et l'unicité du lancement empêchent toute
    création en double, y compris en cas de double clic ou de requêtes concurrentes.
    """
    __tablename__ = "client_order_launches"

    order_request_id: Mapped[str] = mapped_column(ForeignKey("client_order_requests.id"), primary_key=True)
    launch_id: Mapped[str] = mapped_column(ForeignKey("launches.id"), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

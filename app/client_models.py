from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core import Base, utcnow
from .models import uid


class ClientAccount(Base):
    __tablename__ = "client_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    client_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    raison_sociale: Mapped[str] = mapped_column(String(180))
    nom_contact: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    telephone: Mapped[str] = mapped_column(String(40))
    adresse: Mapped[str] = mapped_column(Text)
    pays: Mapped[str] = mapped_column(String(100))
    identifiant_fiscal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    order_requests: Mapped[list[ClientOrderRequest]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class ClientOrderRequest(Base):
    __tablename__ = "client_order_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey("client_accounts.id"), index=True)
    request_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    article: Mapped[str] = mapped_column(String(180))
    quantite: Mapped[int] = mapped_column(Integer)
    date_souhaitee: Mapped[date] = mapped_column(Date)
    reference_client: Mapped[str | None] = mapped_column(String(100), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    client: Mapped[ClientAccount] = relationship(back_populates="order_requests")
    documents: Mapped[list[ClientOrderDocument]] = relationship(
        back_populates="order_request", cascade="all, delete-orphan"
    )


class ClientOrderDocument(Base):
    __tablename__ = "client_order_documents"
    __table_args__ = (UniqueConstraint("order_request_id", "title", name="uq_client_order_document_title"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_request_id: Mapped[str] = mapped_column(ForeignKey("client_order_requests.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    order_request: Mapped[ClientOrderRequest] = relationship(back_populates="documents")
    versions: Mapped[list[ClientOrderDocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="ClientOrderDocumentVersion.number"
    )


class ClientOrderDocumentVersion(Base):
    __tablename__ = "client_order_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "number", name="uq_client_order_document_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("client_order_documents.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    original_name: Mapped[str] = mapped_column(String(250))
    disk_name: Mapped[str] = mapped_column(String(80), unique=True)
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by_client_id: Mapped[str] = mapped_column(ForeignKey("client_accounts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    document: Mapped[ClientOrderDocument] = relationship(back_populates="versions")

"""Informations de pilotage et collaboration strictement internes."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .core import Base, utcnow
from .models import uid


class LaunchOperations(Base):
    __tablename__ = "launch_operations"
    launch_id: Mapped[str] = mapped_column(ForeignKey("launches.id"), primary_key=True)
    article: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provisional_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    definitive_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    responsible_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InternalComment(Base):
    __tablename__ = "internal_document_comments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperienceNote(Base):
    __tablename__ = "internal_experience_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    launch_id: Mapped[str] = mapped_column(ForeignKey("launches.id"), index=True)
    party_type: Mapped[str] = mapped_column(String(20), index=True)
    party_name: Mapped[str] = mapped_column(String(150), index=True)
    category: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

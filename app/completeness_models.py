"""Complétude documentaire contextuelle, sans altérer les tables du MVP 0.1."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .core import Base, utcnow
from .models import uid


class CompletenessProfile(Base):
    __tablename__ = "completeness_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rules: Mapped[list[RequirementRule]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class RequirementRule(Base):
    __tablename__ = "completeness_rules"
    __table_args__ = (UniqueConstraint("profile_id", "folder_slug", "document_type", name="uq_profile_folder_document_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("completeness_profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    folder_slug: Mapped[str] = mapped_column(String(10))
    document_type: Mapped[str] = mapped_column(String(100))
    due_phase: Mapped[str] = mapped_column(String(30))
    requires_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Pièce facultative (emails, avoir si nécessaire) : affichée dans la checklist,
    # jamais comptée manquante ; absente, elle reste « Non exigible ».
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    guidance: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[CompletenessProfile] = relationship(back_populates="rules")


class LaunchCompleteness(Base):
    __tablename__ = "launch_completeness"
    launch_id: Mapped[str] = mapped_column(ForeignKey("launches.id"), primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("completeness_profiles.id"), nullable=True)
    phase: Mapped[str] = mapped_column(String(30), default="preparation")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RequirementValidation(Base):
    __tablename__ = "requirement_validations"
    __table_args__ = (UniqueConstraint("rule_id", "document_version_id", name="uq_rule_version_validation"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("completeness_rules.id"), index=True)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    launch_id: Mapped[str] = mapped_column(ForeignKey("launches.id"), index=True)
    validated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RequirementException(Base):
    __tablename__ = "requirement_exceptions"
    __table_args__ = (UniqueConstraint("launch_id", "rule_id", name="uq_launch_rule_exception"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    launch_id: Mapped[str] = mapped_column(ForeignKey("launches.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("completeness_rules.id"), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    recorded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

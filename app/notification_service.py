"""Émission idempotente, résolution et filtrage du centre de notifications."""
from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .core import utcnow
from .models import Launch, User, uid
from .notification_models import UnifiedNotification


PRIORITIES = {"low", "normal", "high", "urgent"}


def upsert_notification(db: Session, *, recipient_type: str, recipient_id: str, event_key: str,
                        kind: str, title: str, message: str = "", priority: str = "normal",
                        action_required: bool = False, action_label: str = "",
                        target_kind: str = "", target_id: str | None = None,
                        launch_id: str | None = None, folder: str | None = None,
                        metadata: dict | None = None) -> None:
    """Une ligne par événement métier et destinataire ; une évolution met à jour la même action."""
    if recipient_type not in {"internal", "client"}:
        raise ValueError("Type de destinataire invalide")
    if priority not in PRIORITIES:
        raise ValueError("Priorité invalide")
    now = utcnow()
    values = dict(id=uid(), recipient_type=recipient_type, recipient_id=recipient_id,
                  event_key=event_key[:180], kind=kind[:50], title=title[:220], message=message,
                  priority=priority, action_required=action_required, action_label=action_label[:120],
                  target_kind=target_kind[:50], target_id=target_id, launch_id=launch_id,
                  folder_slug=folder, metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
                  created_at=now, updated_at=now)
    excluded = insert(UnifiedNotification).excluded
    statement = insert(UnifiedNotification).values(**values).on_conflict_do_update(
        constraint="uq_unified_notification_recipient_event",
        set_={"kind": excluded.kind, "title": excluded.title, "message": excluded.message,
              "priority": excluded.priority, "action_required": excluded.action_required,
              "action_label": excluded.action_label, "target_kind": excluded.target_kind,
              "target_id": excluded.target_id, "launch_id": excluded.launch_id,
              "folder_slug": excluded.folder_slug, "metadata_json": excluded.metadata_json,
              "updated_at": now, "read_at": None, "resolved_at": None, "archived_at": None})
    db.execute(statement)


def resolve_event(db: Session, *, recipient_type: str, event_key: str,
                  recipient_ids: Iterable[str] | None = None) -> int:
    query = update(UnifiedNotification).where(
        UnifiedNotification.recipient_type == recipient_type,
        UnifiedNotification.event_key == event_key,
        UnifiedNotification.resolved_at.is_(None),
    )
    ids = list(recipient_ids or [])
    if ids:
        query = query.where(UnifiedNotification.recipient_id.in_(ids))
    result = db.execute(query.values(resolved_at=utcnow(), action_required=False, updated_at=utcnow()))
    return result.rowcount or 0


def admin_ids(db: Session) -> list[str]:
    from .access_control import is_admin
    return [user.id for user in db.scalars(select(User).where(User.active.is_(True))).unique().all()
            if is_admin(user)]


def emit_admins(db: Session, **notification) -> None:
    for user_id in admin_ids(db):
        upsert_notification(db, recipient_type="internal", recipient_id=user_id, **notification)


def notification_visible_to_internal(db: Session, user: User, item: UnifiedNotification) -> bool:
    if item.recipient_type != "internal" or item.recipient_id != user.id:
        return False
    if not item.launch_id:
        return True
    from .access import accessible
    from .access_control import can, launch_scope
    launch = db.get(Launch, item.launch_id)
    if not launch or not accessible(db, user, launch):
        return False
    with launch_scope(item.launch_id):
        if not can(user, "launch.read", launch_id=item.launch_id):
            return False
        return not item.folder_slug or can(user, "document.read", item.folder_slug, item.launch_id)


def notification_out(db: Session, item: UnifiedNotification) -> dict:
    launch = db.get(Launch, item.launch_id) if item.launch_id else None
    lifecycle = "archived" if item.archived_at else "resolved" if item.resolved_at else "unread" if not item.read_at else "read"
    return {
        "id": item.id, "event_key": item.event_key, "kind": item.kind,
        "title": item.title, "message": item.message, "priority": item.priority,
        "lifecycle": lifecycle, "action_required": bool(item.action_required and not item.resolved_at),
        "action_label": item.action_label, "target_kind": item.target_kind,
        "target_id": item.target_id, "launch_id": item.launch_id,
        "launch_name": launch.name if launch else None,
        "order_ref": launch.order_ref if launch else None, "folder": item.folder_slug,
        "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
        "read_at": item.read_at.isoformat() if item.read_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        "metadata": json.loads(item.metadata_json or "{}"),
    }


def list_for_recipient(db: Session, recipient_type: str, recipient_id: str, *, limit: int = 250):
    return db.scalars(select(UnifiedNotification).where(
        UnifiedNotification.recipient_type == recipient_type,
        UnifiedNotification.recipient_id == recipient_id,
    ).order_by(UnifiedNotification.updated_at.desc()).limit(limit)).all()


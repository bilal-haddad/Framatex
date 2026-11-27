"""API centralisée des notifications internes et Client."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .client_models import ClientAccount
from .client_routes import get_current_client
from .core import get_current_user, get_db, utcnow
from .models import User
from .notification_models import UnifiedNotification
from .notification_service import (list_for_recipient, notification_out,
                                   notification_visible_to_internal)

router = APIRouter(tags=["Notifications centralisées"])


def collection(db, recipient_type, recipient_id, visible=lambda item: True):
    rows = [item for item in list_for_recipient(db, recipient_type, recipient_id) if visible(item)]
    visible_rows = [item for item in rows if item.archived_at is None]
    return {"items": [notification_out(db, item) for item in rows],
            "unread": sum(item.read_at is None and item.archived_at is None for item in rows),
            "actions": sum(item.action_required and item.resolved_at is None and item.archived_at is None for item in rows),
            "total": len(rows), "visible": len(visible_rows)}


def owned(db, notification_id, recipient_type, recipient_id):
    item = db.get(UnifiedNotification, notification_id)
    if not item or item.recipient_type != recipient_type or item.recipient_id != recipient_id:
        raise HTTPException(404, "Notification introuvable")
    return item


@router.get("/api/notifications")
def internal_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return collection(db, "internal", user.id, lambda item: notification_visible_to_internal(db, user, item))


@router.post("/api/notifications/{notification_id}/read")
def read_internal(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = owned(db, notification_id, "internal", user.id)
    if not notification_visible_to_internal(db, user, item):
        raise HTTPException(404, "Notification introuvable")
    if item.read_at is None:
        item.read_at = utcnow(); db.commit()
    return notification_out(db, item)


@router.post("/api/notifications/{notification_id}/archive")
def archive_internal(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = owned(db, notification_id, "internal", user.id)
    if item.action_required and item.resolved_at is None:
        raise HTTPException(409, "Cette action doit être résolue avant archivage")
    item.archived_at = item.archived_at or utcnow(); item.read_at = item.read_at or utcnow(); db.commit()
    return notification_out(db, item)


@router.get("/api/client/notifications")
def client_notifications(client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    return collection(db, "client", client.id)


@router.post("/api/client/notifications/{notification_id}/read")
def read_client(notification_id: str, client: ClientAccount = Depends(get_current_client),
                db: Session = Depends(get_db)):
    item = owned(db, notification_id, "client", client.id)
    if item.read_at is None:
        item.read_at = utcnow(); db.commit()
    return notification_out(db, item)


@router.post("/api/client/notifications/{notification_id}/archive")
def archive_client(notification_id: str, client: ClientAccount = Depends(get_current_client),
                   db: Session = Depends(get_db)):
    item = owned(db, notification_id, "client", client.id)
    if item.action_required and item.resolved_at is None:
        raise HTTPException(409, "Cette action doit être résolue avant archivage")
    item.archived_at = item.archived_at or utcnow(); item.read_at = item.read_at or utcnow(); db.commit()
    return notification_out(db, item)


"""Transitions explicites, historique client et politique de partage à version fixe."""
from __future__ import annotations

from datetime import timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from .access import must_access
from .client_models import ClientAccount, ClientOrderDocument, ClientOrderDocumentVersion, ClientOrderRequest
from .client_routes import add_audit, document_out, order_out
from .client_workflow_models import ClientDocumentRequest, ClientDocumentRequestEvent, ClientOrderLaunch, ClientSharedDocument
from .core import utcnow
from .models import DocumentVersion, User

ORDER_TRANSITIONS = {"draft": {"submitted"}, "submitted": {"under_review", "accepted", "rejected"},
                     "under_review": {"accepted", "rejected"}, "accepted": set(), "rejected": set()}
DOCUMENT_TRANSITIONS = {"requested": set(), "uploaded": {"under_review", "accepted", "correction_required"},
                        "under_review": {"accepted", "correction_required"},
                        "accepted": set(), "correction_required": set()}


def timestamp(value):
    # SQLite restitue des datetimes sans fuseau ; les dates stockées sont UTC.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat() if value else None


def internal_user(user):
    from .main import admin_only
    admin_only(user)
    return user


def get_order(db, order_id):
    item = db.get(ClientOrderRequest, order_id)
    if not item:
        raise HTTPException(404, "Demande client introuvable")
    return item


def transition_order(db, order, status, actor_id):
    old = order.status
    if status == old:
        return order_out(order)
    if status not in ORDER_TRANSITIONS.get(old, set()):
        raise HTTPException(409, "Transition de demande non autorisée")
    changed = db.execute(update(ClientOrderRequest).where(ClientOrderRequest.id == order.id,
        ClientOrderRequest.status == old).values(status=status, updated_at=utcnow()),
        execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Demande modifiée entre-temps ; actualisez")
    add_audit(db, actor_id, "client.order_request.status_changed", "client_order_request", order.id,
              {"client_id": order.client_id, "previous": old, "status": status})
    db.commit()
    db.refresh(order)
    return order_out(order)


def order_launch_out(db, order):
    """Dossier Jaune ouvert pour une demande Client, ou None."""
    link = db.get(ClientOrderLaunch, order.id)
    if not link:
        return None
    from .models import Launch
    launch = db.get(Launch, link.launch_id)
    return {"id": launch.id, "name": launch.name, "order_ref": launch.order_ref,
            "linked_at": timestamp(link.created_at)} if launch else None


def launch_order_out(db, launch_id):
    """Demande Client à l'origine d'un Dossier Jaune, ou None."""
    link = db.scalar(select(ClientOrderLaunch).where(ClientOrderLaunch.launch_id == launch_id))
    order = db.get(ClientOrderRequest, link.order_request_id) if link else None
    if not order:
        return None
    return {"id": order.id, "request_number": order.request_number, "client": order.client.raison_sociale,
            "article": order.article, "quantite": order.quantite,
            "date_souhaitee": order.date_souhaitee.isoformat() if order.date_souhaitee else None,
            "reference_client": order.reference_client, "status": order.status}


def get_document_request(db, request_id, client=None):
    query = select(ClientDocumentRequest).where(ClientDocumentRequest.id == request_id)
    if client:
        query = query.where(ClientDocumentRequest.client_id == client.id)
    item = db.scalar(query)
    if not item:
        raise HTTPException(404, "Demande documentaire introuvable")
    return item


def request_event(db, item, previous, actor_id, actor_type, *, version=None, message=""):
    event = ClientDocumentRequestEvent(document_request_id=item.id, previous_status=previous,
        status=item.status, actor_id=actor_id, actor_type=actor_type,
        version_id=version.id if version else None, message=message.strip())
    db.add(event)
    try:
        db.flush()
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise HTTPException(409, "Demande modifiée entre-temps ; actualisez")
    add_audit(db, actor_id, "client.document_request." + item.status, "client_document_request", item.id,
              {"client_id": item.client_id, "order_request_id": item.order_request_id,
               "previous": previous, "status": item.status, "event_id": event.id,
               "version_id": version.id if version else None,
               "sha256": version.sha256 if version else None})


def request_out(db, item):
    order = get_order(db, item.order_request_id)
    author = db.get(User, item.requested_by)
    document = db.get(ClientOrderDocument, item.document_id) if item.document_id else None
    events = []
    for event in db.scalars(select(ClientDocumentRequestEvent).where(
            ClientDocumentRequestEvent.document_request_id == item.id)
            .order_by(ClientDocumentRequestEvent.occurred_at, ClientDocumentRequestEvent.id)):
        actor = db.get(User if event.actor_type == "internal" else ClientAccount, event.actor_id)
        # actor_type est interne au backend, jamais un nom de rôle ou un email.
        version = db.get(ClientOrderDocumentVersion, event.version_id) if event.version_id else None
        events.append({"id": event.id, "previous_status": event.previous_status, "status": event.status,
                       "actor": actor.name if event.actor_type == "internal" and actor else
                           actor.nom_contact if actor else "FRAMATEX",
                       "actor_type": event.actor_type, "version": version.number if version else None,
                       "message": event.message, "occurred_at": timestamp(event.occurred_at)})
    return {"id": item.id, "order_request_id": item.order_request_id, "request_number": order.request_number,
            "title": item.title, "description": item.description, "status": item.status,
            "requested_by": author.name if author else "FRAMATEX",
            "requested_at": timestamp(item.requested_at), "updated_at": timestamp(item.updated_at),
            "accepted_at": timestamp(item.accepted_at),
            "document": document_out(document) if document else None, "history": events}


def commit_workflow(db):
    try:
        db.commit()
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise HTTPException(409, "Document modifié entre-temps ; actualisez avant de poursuivre")


def safe_source(db, version):
    from .sharing_routes import PUBLIC_DOC_TYPES, SENSITIVE, norm, is_approved
    doc = version.document
    allowed = PUBLIC_DOC_TYPES | {"confirmation de commande", "devis client", "document commercial client"}
    try:
        return (doc.folder.slug in {"jaune", "rose"} and norm(doc.doc_type) in allowed
                and not SENSITIVE.search(norm(f"{doc.title} {doc.doc_type} {version.original_name}"))
                and is_approved(db, version, doc))
    except HTTPException:
        return False


def authorized_source(db, user, version_id):
    from .main import must
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(404, "Version interne introuvable")
    must(user, "launch.read")
    must_access(db, user, version.document.folder.launch_id)
    must(user, "document.read", version.document.folder.slug)
    return version


def shared_out(db, item, *, internal=False):
    version = db.get(DocumentVersion, item.document_version_id)
    result = {"id": item.id, "title": item.title, "order_request_id": item.order_request_id,
              "version": version.number, "original_name": version.original_name, "size": version.size,
              "sha256": version.sha256, "published_at": timestamp(item.published_at)}
    if internal:
        publisher = db.get(User, item.published_by)
        revoker = db.get(User, item.revoked_by) if item.revoked_by else None
        result.update(status=item.status, reason=item.reason, document_version_id=version.id,
                      document_title=version.document.title,
                      published_by=publisher.name if publisher else "FRAMATEX",
                      revoked_by=revoker.name if revoker else None,
                      effective=item.status == "published" and bool(safe_source(db, version)),
                      revoked_at=timestamp(item.revoked_at),
                      revoked_reason=item.revoked_reason)
    return result

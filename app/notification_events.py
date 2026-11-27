"""Traduction des événements métier en notifications, sans dépendance à Outlook."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access_models import LaunchAssignment
from .client_models import ClientAccount, ClientOrderRequest
from .client_workflow_models import ClientOrderLaunch
from .models import Launch, User
from .notification_service import emit_admins, resolve_event, upsert_notification


def account_registered(db: Session, client: ClientAccount):
    emit_admins(db, event_key=f"client-account:{client.id}", kind="client_registration",
                title="Nouvelle inscription Client", message=f"{client.raison_sociale} · {client.client_code}",
                priority="normal", action_required=True, action_label="Examiner le compte",
                target_kind="client_account", target_id=client.id,
                metadata={"client_code": client.client_code, "company": client.raison_sociale})


def account_status_changed(db: Session, client: ClientAccount, status: str):
    if status == "active":
        resolve_event(db, recipient_type="internal", event_key=f"client-account:{client.id}")
        upsert_notification(db, recipient_type="client", recipient_id=client.id,
            event_key=f"client-account-activated:{client.id}", kind="account_activated",
            title="Votre compte FRAMATEX est activé", message="Vous pouvez envoyer vos demandes de commande.",
            priority="normal", target_kind="client_account", target_id=client.id)


def order_status_changed(db: Session, order: ClientOrderRequest, status: str, message: str = ""):
    client = db.get(ClientAccount, order.client_id)
    key = f"client-order:{order.id}"
    details = (f"{client.raison_sociale} · client {client.client_code} · demande {order.request_number} · "
               f"{order.project_name or 'Projet non nommé'} · {order.article} · {order.quantite} pièces · "
               f"souhaitée le {order.date_souhaitee.isoformat()} · reçue le {order.created_at.isoformat()}")
    if status == "submitted":
        emit_admins(db, event_key=key, kind="client_order", title="Nouvelle demande de commande",
                    message=details, priority="high", action_required=True,
                    action_label="Examiner la demande", target_kind="client_order_request", target_id=order.id,
                    metadata={"request_number": order.request_number, "client_code": client.client_code})
        upsert_notification(db, recipient_type="client", recipient_id=client.id,
            event_key=f"client-order-received:{order.id}", kind="order_received",
            title=f"Demande {order.request_number} reçue", message="FRAMATEX va examiner votre demande.",
            priority="normal", target_kind="client_order_request", target_id=order.id)
    elif status == "under_review":
        emit_admins(db, event_key=key, kind="client_order", title="Demande de commande en étude",
                    message=details, priority="high", action_required=True,
                    action_label="Poursuivre le traitement", target_kind="client_order_request", target_id=order.id)
    elif status == "accepted":
        emit_admins(db, event_key=key, kind="client_order", title="Demande acceptée — Dossier Jaune à créer",
                    message=details, priority="high", action_required=True,
                    action_label="Créer le Dossier Jaune", target_kind="client_order_request", target_id=order.id)
        upsert_notification(db, recipient_type="client", recipient_id=client.id,
            event_key=f"client-order-decision:{order.id}", kind="order_accepted",
            title=f"Demande {order.request_number} acceptée", message="Votre Dossier Jaune va être préparé.",
            priority="normal", target_kind="client_order_request", target_id=order.id)
    elif status == "rejected":
        resolve_event(db, recipient_type="internal", event_key=key)
        upsert_notification(db, recipient_type="client", recipient_id=client.id,
            event_key=f"client-order-decision:{order.id}", kind="order_rejected",
            title=f"Demande {order.request_number} refusée",
            message=message.strip() or "Votre demande n’a pas été retenue par FRAMATEX.",
            priority="high", target_kind="client_order_request", target_id=order.id)


def launch_created_from_order(db: Session, order: ClientOrderRequest, launch: Launch):
    client = db.get(ClientAccount, order.client_id)
    emit_admins(db, event_key=f"client-order:{order.id}", kind="assignment_pending",
                title="Commande acceptée — technicien à affecter",
                message=f"{launch.order_ref or launch.name} · {client.raison_sociale} · quatre sous-dossiers à couvrir.",
                priority="high", action_required=True, action_label="Affecter les techniciens",
                target_kind="launch_assignments", target_id=launch.id, launch_id=launch.id)
    upsert_notification(db, recipient_type="client", recipient_id=client.id,
        event_key=f"client-order-decision:{order.id}", kind="order_accepted",
        title=f"Demande {order.request_number} acceptée",
        message=f"Le Dossier Jaune {launch.order_ref or launch.name} a été créé.",
        priority="normal", target_kind="client_order_request", target_id=order.id)


def assignments_changed(db: Session, launch: Launch, user: User, folders: dict, *, first: bool):
    names = ", ".join(slug.upper() for slug in ("jaune", "rose", "bleu", "vert") if slug in folders)
    upsert_notification(db, recipient_type="internal", recipient_id=user.id,
        event_key=f"assignment:{launch.id}:{user.id}", kind="assignment" if first else "access_changed",
        title=("Nouvelle commande attribuée" if first else "Habilitations modifiées") +
              f" : {launch.order_ref or launch.name}",
        message=f"Sous-dossiers autorisés : {names or 'aucun'}.", priority="high",
        action_required=False, action_label="Ouvrir la commande",
        target_kind="launch", target_id=launch.id, launch_id=launch.id,
        folder=next(iter(folders), None))


def sync_assignment_action(db: Session, launch: Launch):
    link = db.scalar(select(ClientOrderLaunch).where(ClientOrderLaunch.launch_id == launch.id))
    if not link:
        return
    covered = set(db.scalars(select(LaunchAssignment.folder_slug).where(
        LaunchAssignment.launch_id == launch.id)).all())
    key = f"client-order:{link.order_request_id}"
    if {"jaune", "rose", "bleu", "vert"} <= covered:
        resolve_event(db, recipient_type="internal", event_key=key)
    else:
        order = db.get(ClientOrderRequest, link.order_request_id)
        client = db.get(ClientAccount, order.client_id)
        emit_admins(db, event_key=key, kind="assignment_pending",
                    title="Commande acceptée — technicien à affecter",
                    message=f"{launch.order_ref or launch.name} · {client.raison_sociale} · couverture "
                            f"{len(covered)}/4 sous-dossiers.", priority="high", action_required=True,
                    action_label="Compléter les affectations", target_kind="launch_assignments",
                    target_id=launch.id, launch_id=launch.id)


def client_document_event(db: Session, *, client_id: str, request_id: str, order_id: str,
                          title: str, status: str, message: str = ""):
    key = f"client-document:{request_id}"
    if status in {"requested", "correction_required"}:
        upsert_notification(db, recipient_type="client", recipient_id=client_id, event_key=key,
            kind="document_" + status,
            title="Document complémentaire demandé" if status == "requested" else "Correction demandée",
            message=message or title, priority="high", action_required=True,
            action_label="Déposer le document", target_kind="client_document_request", target_id=request_id)
    elif status == "accepted":
        resolve_event(db, recipient_type="client", event_key=key, recipient_ids=[client_id])
        upsert_notification(db, recipient_type="client", recipient_id=client_id,
            event_key=f"client-document-accepted:{request_id}", kind="document_accepted",
            title="Document accepté", message=title, priority="normal",
            target_kind="client_document_request", target_id=request_id)


def client_document_uploaded(db: Session, *, request_id: str, order_id: str, title: str):
    emit_admins(db, event_key=f"client-document-review:{request_id}", kind="document_validation",
                title="Document client à vérifier", message=title, priority="high",
                action_required=True, action_label="Vérifier le document",
                target_kind="client_document_request", target_id=request_id,
                metadata={"order_request_id": order_id})


def resolve_client_document_review(db: Session, request_id: str):
    resolve_event(db, recipient_type="internal", event_key=f"client-document-review:{request_id}")


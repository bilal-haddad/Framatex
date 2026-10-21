"""Demandes métier, pièces attendues et partage explicite vers un compte Client."""
from __future__ import annotations

from typing import Literal
import os

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .client_models import ClientAccount, ClientOrderDocument, ClientOrderDocumentVersion, ClientOrderRequest
from .client_routes import (CLIENT_STORAGE, add_audit, get_current_client, order_out, own_order,
                            store_client_upload)
from .client_workflow import (DOCUMENT_TRANSITIONS, authorized_source, commit_workflow, get_document_request,
                              get_order, internal_user, order_launch_out, request_event, request_out, safe_source,
                              shared_out, transition_order)
from .client_workflow_models import ClientDocumentRequest, ClientOrderLaunch, ClientSharedDocument
from .core import get_current_user, get_db, utcnow
from .internal_models import LaunchOperations
from .models import DocumentVersion, Folder, Launch, User

router = APIRouter(tags=["Workflow Client"])


class ClientOrderStatus(BaseModel):
    status: Literal["draft", "submitted"]


class InternalOrderStatus(BaseModel):
    status: Literal["under_review", "accepted", "rejected"]


class DocumentRequestInput(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Titre requis")
        return value.strip()


class DocumentDecision(BaseModel):
    status: Literal["under_review", "accepted", "correction_required"]
    version_id: str = Field(min_length=36, max_length=36)
    message: str = Field(default="", max_length=2000)


class ShareInput(BaseModel):
    document_version_id: str
    order_request_id: str | None = None
    title: str | None = Field(default=None, max_length=220)
    reason: str = Field(min_length=12, max_length=1200)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value):
        if len(value.strip()) < 12:
            raise ValueError("Motif de 12 caractères minimum requis")
        return value.strip()


class RevokeInput(BaseModel):
    reason: str = Field(min_length=12, max_length=1200)
    _reason = field_validator("reason")(ShareInput.reason_not_blank.__func__)


@router.patch("/api/client/order-requests/{order_id}/status")
def client_order_status(order_id: str, payload: ClientOrderStatus,
                        client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    order = own_order(db, client, order_id)
    if order.status not in {"draft", "submitted"}:
        raise HTTPException(409, "Cette demande est déjà prise en charge par FRAMATEX")
    return transition_order(db, order, payload.status, client.id)


@router.patch("/api/admin/client-order-requests/{order_id}/status")
def internal_order_status(order_id: str, payload: InternalOrderStatus,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    return transition_order(db, get_order(db, order_id), payload.status, user.id)


@router.post("/api/admin/client-order-requests/{order_id}/launch")
def open_launch_for_order(order_id: str, response: Response,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Accepte la demande si nécessaire et ouvre son Dossier Jaune, une seule fois."""
    from .main import FOLDERS, audit, must
    internal_user(user)
    must(user, "launch.create")
    order = get_order(db, order_id)
    existing = order_launch_out(db, order)
    if existing:
        return {"created": False, "launch": existing, "order": order_out(order)}
    previous = order.status
    if previous not in {"submitted", "under_review", "accepted"}:
        raise HTTPException(409, "Seule une demande envoyée, en étude ou acceptée peut ouvrir un Dossier Jaune")
    if previous != "accepted":
        changed = db.execute(update(ClientOrderRequest).where(ClientOrderRequest.id == order.id,
            ClientOrderRequest.status == previous).values(status="accepted", updated_at=utcnow()),
            execution_options={"synchronize_session": False})
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Demande modifiée entre-temps ; actualisez")
        add_audit(db, user.id, "client.order_request.status_changed", "client_order_request", order.id,
                  {"client_id": order.client_id, "previous": previous, "status": "accepted"})
    client = order.client
    launch = Launch(name=f"{order.article} · {client.raison_sociale}"[:180], client_name=client.raison_sociale[:150],
                    order_ref=order.request_number, created_by=user.id,
                    restricted=os.getenv("FRAMATEX_RESTRICT_NEW_LAUNCHES", "0") == "1")
    db.add(launch)
    db.flush()
    for slug, label in FOLDERS:
        db.add(Folder(launch_id=launch.id, slug=slug, label=label))
    db.add(LaunchOperations(launch_id=launch.id, article=order.article[:180], quantity=order.quantite,
                            responsible_id=user.id))
    db.add(ClientOrderLaunch(order_request_id=order.id, launch_id=launch.id, created_by=user.id))
    audit(db, user, "launch.create", "launch", launch.id,
          {"name": launch.name, "orli": None, "client_order_request": order.request_number})
    add_audit(db, user.id, "client.order_request.launch_created", "client_order_request", order.id,
              {"client_id": order.client_id, "launch_id": launch.id, "request_number": order.request_number})
    try:
        db.commit()
    except IntegrityError:
        # Requête concurrente : le lien unique garantit qu'un seul dossier existe.
        db.rollback()
        existing = order_launch_out(db, order)
        if existing:
            return {"created": False, "launch": existing, "order": order_out(order)}
        raise HTTPException(409, "Création concurrente ; actualisez")
    db.refresh(order)
    response.status_code = 201
    return {"created": True, "launch": order_launch_out(db, order), "order": order_out(order)}


@router.post("/api/admin/client-order-requests/{order_id}/document-requests", status_code=201)
def ask_document(order_id: str, payload: DocumentRequestInput,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    order = get_order(db, order_id)
    item = ClientDocumentRequest(client_id=order.client_id, order_request_id=order.id,
        title=payload.title, description=payload.description.strip(), requested_by=user.id, status="requested")
    db.add(item)
    db.flush()
    request_event(db, item, None, user.id, "internal")
    commit_workflow(db)
    return request_out(db, item)


@router.get("/api/admin/clients/{client_id}/document-requests")
def internal_document_requests(client_id: str, order_request_id: str | None = None,
                               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    if not db.get(ClientAccount, client_id):
        raise HTTPException(404, "Compte client introuvable")
    query = select(ClientDocumentRequest).where(ClientDocumentRequest.client_id == client_id)
    if order_request_id:
        query = query.where(ClientDocumentRequest.order_request_id == order_request_id)
    return [request_out(db, item) for item in db.scalars(query.order_by(ClientDocumentRequest.requested_at.desc()))]


@router.get("/api/admin/client-document-requests/{request_id}")
def internal_document_request(request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    return request_out(db, get_document_request(db, request_id))


@router.patch("/api/admin/client-document-requests/{request_id}/status")
def review_document(request_id: str, payload: DocumentDecision,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    item = get_document_request(db, request_id)
    document = db.get(ClientOrderDocument, item.document_id) if item.document_id else None
    version = max(document.versions, key=lambda v: v.number) if document and document.versions else None
    if not version or payload.version_id != version.id:
        raise HTTPException(409, "Examinez la version déposée courante avant de décider")
    if payload.status == item.status:
        return request_out(db, item)
    if payload.status not in DOCUMENT_TRANSITIONS.get(item.status, set()):
        raise HTTPException(409, "Transition documentaire non autorisée")
    if payload.status == "correction_required" and len(payload.message.strip()) < 3:
        raise HTTPException(422, "Précisez la correction attendue dans le message au client")
    previous = item.status
    item.status = payload.status
    item.updated_at = utcnow()
    item.accepted_at = utcnow() if payload.status == "accepted" else None
    request_event(db, item, previous, user.id, "internal", version=version, message=payload.message)
    commit_workflow(db)
    return request_out(db, item)


@router.get("/api/client/document-requests")
def document_requests(order_request_id: str | None = None,
                       client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    query = select(ClientDocumentRequest).where(ClientDocumentRequest.client_id == client.id)
    if order_request_id:
        own_order(db, client, order_request_id)
        query = query.where(ClientDocumentRequest.order_request_id == order_request_id)
    return [request_out(db, item) for item in db.scalars(query.order_by(ClientDocumentRequest.requested_at.desc()))]


@router.get("/api/client/document-requests/{request_id}")
def document_request(request_id: str, client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    return request_out(db, get_document_request(db, request_id, client))


@router.post("/api/client/document-requests/{request_id}/upload", status_code=201)
async def upload_requested(request_id: str, file: UploadFile = File(...),
                            client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    item = get_document_request(db, request_id, client)
    if item.status not in {"requested", "correction_required"}:
        raise HTTPException(409, "Un dépôt est possible seulement pour une pièce demandée ou à corriger")
    original, disk_name, size, digest, content_type = await store_client_upload(file)
    try:
        document = db.get(ClientOrderDocument, item.document_id) if item.document_id else None
        if not document:
            document = ClientOrderDocument(order_request_id=item.order_request_id,
                title=f"{item.title[:180]} · demande {item.id[:8]}")
            db.add(document)
            db.flush()
            item.document_id = document.id
        version = ClientOrderDocumentVersion(document_id=document.id,
            number=max((v.number for v in document.versions), default=0) + 1,
            original_name=original, disk_name=disk_name, content_type=content_type,
            size=size, sha256=digest, uploaded_by_client_id=client.id)
        db.add(version)
        db.flush()
        previous = item.status
        item.status = "uploaded"
        item.updated_at = utcnow()
        item.accepted_at = None
        request_event(db, item, previous, client.id, "client", version=version)
        commit_workflow(db)
    except (IntegrityError, StaleDataError):
        db.rollback()
        (CLIENT_STORAGE / disk_name).unlink(missing_ok=True)
        raise HTTPException(409, "Dépôt concurrent ; actualisez la demande documentaire")
    except Exception:
        db.rollback()
        (CLIENT_STORAGE / disk_name).unlink(missing_ok=True)
        raise
    db.expire(document, ["versions"])
    return request_out(db, item)


def requested_version(db, item, number):
    version = db.scalar(select(ClientOrderDocumentVersion).where(
        ClientOrderDocumentVersion.document_id == item.document_id,
        ClientOrderDocumentVersion.number == number))
    if not version:
        raise HTTPException(404, "Version client introuvable")
    path = CLIENT_STORAGE / version.disk_name
    if not path.is_file():
        raise HTTPException(503, "Fichier client indisponible")
    return version, path


def requested_download(db, item, number, actor_id):
    version, path = requested_version(db, item, number)
    add_audit(db, actor_id, "client.document_request.download", "client_document_request", item.id,
              {"version_id": version.id, "version": version.number})
    db.commit()
    return FileResponse(path, filename=version.original_name, media_type="application/octet-stream")


@router.get("/api/client/document-requests/{request_id}/versions/{number}/download")
def download_requested(request_id: str, number: int,
                        client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    return requested_download(db, get_document_request(db, request_id, client), number, client.id)


@router.get("/api/admin/client-document-requests/{request_id}/versions/{number}/download")
def internal_requested_download(request_id: str, number: int,
                                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    return requested_download(db, get_document_request(db, request_id), number, user.id)


@router.get("/api/admin/client-share-candidates")
def share_candidates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    output = []
    for version in db.scalars(select(DocumentVersion).order_by(DocumentVersion.created_at.desc())):
        authorized_source(db, user, version.id)
        if safe_source(db, version):
            output.append({"version_id": version.id, "title": version.document.title,
                           "document_type": version.document.doc_type, "version": version.number,
                           "launch_name": version.document.folder.launch.name})
    return output


@router.get("/api/admin/clients/{client_id}/shared-documents")
def internal_shared(client_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    if not db.get(ClientAccount, client_id):
        raise HTTPException(404, "Compte client introuvable")
    rows = db.scalars(select(ClientSharedDocument).where(ClientSharedDocument.client_id == client_id)
                       .order_by(ClientSharedDocument.published_at.desc()))
    return [shared_out(db, item, internal=True) for item in rows]


@router.post("/api/admin/clients/{client_id}/shared-documents", status_code=201)
def share_document(client_id: str, payload: ShareInput,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    if not db.get(ClientAccount, client_id):
        raise HTTPException(404, "Compte client introuvable")
    if payload.order_request_id and get_order(db, payload.order_request_id).client_id != client_id:
        raise HTTPException(422, "La demande ne relève pas de ce client")
    version = authorized_source(db, user, payload.document_version_id)
    if not safe_source(db, version):
        raise HTTPException(422, "Version non autorisée : type admissible et approbation explicite requis")
    from .paper_routes import _verify_file
    if _verify_file(version)["status"] != "intact":
        raise HTTPException(409, "Intégrité du fichier non confirmée ; partage refusé")
    item = ClientSharedDocument(client_id=client_id, order_request_id=payload.order_request_id,
        document_version_id=version.id, title=(payload.title or "").strip() or version.document.title,
        reason=payload.reason, published_by=user.id, status="published")
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Cette version est déjà partagée avec ce client")
    add_audit(db, user.id, "client.shared_document.published", "client_shared_document", item.id,
              {"client_id": client_id, "version_id": version.id, "launch": version.document.folder.launch_id})
    db.commit()
    return shared_out(db, item, internal=True)


@router.post("/api/admin/client-shared-documents/{share_id}/revoke")
def revoke_share(share_id: str, payload: RevokeInput,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    internal_user(user)
    item = db.get(ClientSharedDocument, share_id)
    if not item:
        raise HTTPException(404, "Partage introuvable")
    if item.status == "revoked":
        return shared_out(db, item, internal=True)
    version = authorized_source(db, user, item.document_version_id)
    item.status = "revoked"
    item.revoked_by, item.revoked_at, item.revoked_reason = user.id, utcnow(), payload.reason.strip()
    add_audit(db, user.id, "client.shared_document.revoked", "client_shared_document", item.id,
              {"client_id": item.client_id, "version_id": version.id, "launch": version.document.folder.launch_id})
    db.commit()
    return shared_out(db, item, internal=True)


@router.get("/api/client/shared-documents")
def shared_documents(client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    rows = db.scalars(select(ClientSharedDocument).where(ClientSharedDocument.client_id == client.id,
        ClientSharedDocument.status == "published").order_by(ClientSharedDocument.published_at.desc()))
    return [shared_out(db, item) for item in rows if safe_source(db, db.get(DocumentVersion, item.document_version_id))]


@router.get("/api/client/shared-documents/{share_id}/download")
def download_shared(share_id: str, client: ClientAccount = Depends(get_current_client), db: Session = Depends(get_db)):
    item = db.scalar(select(ClientSharedDocument).where(ClientSharedDocument.id == share_id,
        ClientSharedDocument.client_id == client.id, ClientSharedDocument.status == "published"))
    if not item:
        raise HTTPException(404, "Document partagé introuvable")
    version = db.get(DocumentVersion, item.document_version_id)
    if not safe_source(db, version):
        raise HTTPException(404, "Document partagé introuvable")
    from .main import STORAGE
    from .paper_routes import _verify_file
    if _verify_file(version)["status"] != "intact":
        raise HTTPException(503, "Fichier partagé indisponible ou intégrité non confirmée")
    add_audit(db, client.id, "client.shared_document.download", "client_shared_document", item.id,
              {"version_id": version.id})
    db.commit()
    return FileResponse(STORAGE / version.disk_name, filename=version.original_name, media_type="application/octet-stream")

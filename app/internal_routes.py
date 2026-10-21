"""Espace FRAMATEX : pilotage, recherche et collaboration authentifiés."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import accessible, must_access
from .core import get_current_user, get_db, utcnow
from .internal_models import ExperienceNote, InternalComment, LaunchOperations
from .internal_service import (DOCUMENT_TYPES, FOLDER_LABELS, activity, document_state,
                               launch_summary, visible_launches)
from .models import Document, DocumentVersion, User

router = APIRouter(tags=["Espace FRAMATEX"])


def guards():
    from .main import must, permitted, audit, admin_only
    return must, permitted, audit, admin_only


class OperationsPayload(BaseModel):
    article: str | None = Field(default=None, max_length=180)
    quantity: int | None = Field(default=None, gt=0, le=10_000_000)
    provisional_ref: str | None = Field(default=None, max_length=100)
    definitive_ref: str | None = Field(default=None, max_length=100)
    responsible_id: str | None = None


class CommentPayload(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Commentaire vide")
        return value.strip()


class ExperiencePayload(CommentPayload):
    party_type: Literal["client", "fournisseur", "atelier"]
    party_name: str = Field(min_length=2, max_length=150)
    category: Literal["incident", "qualite", "retard", "documentaire", "retour"] = "retour"


@router.get("/api/workspace/document-types")
def document_types(user: User = Depends(get_current_user)):
    must, permitted, _, _ = guards()
    must(user, "launch.read")
    return {slug: {"label": FOLDER_LABELS[slug], "types": types}
            for slug, types in DOCUMENT_TYPES.items() if permitted(user, "document.read", slug)}


@router.get("/api/workspace/collaborators")
def collaborators(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "launch.update")
    return [{"id": row.id, "name": row.name} for row in db.scalars(
        select(User).where(User.active.is_(True)).order_by(User.name))]


@router.get("/api/launches/{launch_id}/operations")
def operations(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "launch.read")
    from .client_workflow import launch_order_out
    return {**launch_summary(db, user, must_access(db, user, launch_id)),
            "client_request": launch_order_out(db, launch_id)}


@router.patch("/api/launches/{launch_id}/operations")
def save_operations(launch_id: str, payload: OperationsPayload,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, audit, _ = guards()
    must(user, "launch.read")
    must(user, "launch.update")
    launch = must_access(db, user, launch_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("responsible_id"):
        responsible = db.get(User, values["responsible_id"])
        if not responsible or not responsible.active or not accessible(db, responsible, launch):
            raise HTTPException(422, "Responsable inactif ou sans accès au lancement")
    item = db.get(LaunchOperations, launch_id)
    if not item:
        item = LaunchOperations(launch_id=launch_id)
        db.add(item)
    for key, value in values.items():
        setattr(item, key, value.strip() or None if isinstance(value, str) else value)
    launch.updated_at = utcnow()
    audit(db, user, "launch.operations.update", "launch", launch_id, {"fields": list(values)})
    db.commit()
    return launch_summary(db, user, launch)


@router.get("/api/workspace/launches")
def launches(q: str = "", client: str = "", article: str = "", status: str = "",
             completion: str = "", with_alert: bool = False, date_from: date | None = None,
             date_to: date | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "launch.read")
    rows = [launch_summary(db, user, row) for row in visible_launches(db, user)]
    def matches(row):
        searchable = " ".join(str(row.get(k) or "") for k in (
            "name", "client_name", "order_ref", "orli_ref", "article", "provisional_ref", "definitive_ref"))
        updated = date.fromisoformat(row["last_activity"][:10])
        return (q.casefold() in searchable.casefold()
                and client.casefold() in (row["client_name"] or "").casefold()
                and article.casefold() in (row["article"] or row["name"]).casefold()
                and (not status or status == row["status"])
                and (not completion or completion == row["completion"]["state"])
                and (not with_alert or row["alerts"] > 0)
                and (not date_from or updated >= date_from) and (not date_to or updated <= date_to))
    return [row for row in rows if matches(row)]


class DuplicateReviewPayload(BaseModel):
    sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=8, max_length=1000)


@router.get("/api/launches/{launch_id}/duplicates")
def launch_duplicates(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "launch.read")
    from .duplicates import duplicate_groups
    return duplicate_groups(db, user, must_access(db, user, launch_id))


@router.post("/api/launches/{launch_id}/duplicates/review", status_code=201)
def review_duplicate(launch_id: str, payload: DuplicateReviewPayload,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Conserver volontairement des pièces identiques : motif obligatoire, décision auditée."""
    import json
    from .completeness_models import DuplicateReview
    from .duplicates import duplicate_groups
    must, _, audit, _ = guards()
    must(user, "launch.read")
    launch = must_access(db, user, launch_id)
    group = next((g for g in duplicate_groups(db, user, launch) if g["sha256"] == payload.sha256), None)
    if not group:
        raise HTTPException(404, "Aucun doublon pour cette empreinte dans ce dossier")
    for folder in {d["folder"] for d in group["documents"]}:
        must(user, "document.review", folder)
    db.add(DuplicateReview(launch_id=launch.id, sha256=payload.sha256, reason=payload.reason.strip(),
                           version_ids=json.dumps([d["version_id"] for d in group["documents"]]), decided_by=user.id))
    audit(db, user, "document.duplicate.review", "launch", launch.id,
          {"sha256": payload.sha256, "documents": [d["document_id"] for d in group["documents"]],
           "reason": payload.reason.strip()})
    db.commit()
    return duplicate_groups(db, user, launch)


@router.get("/api/workspace/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "launch.read")
    from .workspace_routes import priorities
    launches = visible_launches(db, user)
    summaries = [launch_summary(db, user, launch) for launch in launches]
    active = [row for row in summaries if row["status"] != "Clôturé"]
    pending = sum(f.get("pending_validation", 0) for row in active for f in row["folders"])
    missing = [{"launch_id": row["id"], "launch_name": row["name"], "order_ref": row["order_ref"],
                "client_name": row["client_name"], "article": row["article"],
                "folder": f["slug"], **requirement}
               for row in active for f in row["folders"] for requirement in f.get("requirements", [])
               if requirement["status"] == "missing"]
    # Pièces en validation et doublons non examinés : mêmes champs que les manquants.
    pending_items = [{"launch_id": row["id"], "launch_name": row["name"], "order_ref": row["order_ref"],
                      "client_name": row["client_name"], "article": row["article"], "folder": f["slug"],
                      "document_id": requirement["documents"][0]["id"] if requirement["documents"] else None,
                      **requirement}
                     for row in active for f in row["folders"] for requirement in f.get("requirements", [])
                     if requirement["status"] == "pending_validation"]
    from .duplicates import duplicate_groups
    duplicate_items = []
    for launch, row in zip(launches, summaries):
        if row["status"] == "Clôturé":
            continue
        for group in duplicate_groups(db, user, launch):
            if group["reviewed"]:
                continue
            latest = group["documents"][-1]
            duplicate_items.append({"launch_id": row["id"], "launch_name": row["name"], "order_ref": row["order_ref"],
                                    "client_name": row["client_name"], "article": row["article"],
                                    "folder": latest["folder"], "title": latest["title"],
                                    "document_id": latest["document_id"], "sha256": group["sha256"],
                                    "status": "duplicate", "documents": group["documents"]})
    priority_report = priorities(user, db)
    return {"kpis": {"active_launches": len(active),
                     "complete_launches": sum(r["completion"]["state"] == "complete" for r in active),
                     "incomplete_launches": sum(r["completion"]["state"] == "incomplete" for r in active),
                     "missing_documents": len(missing), "pending_documents": pending,
                     "alerts": sum(r["alerts"] for r in active),
                     "inconsistencies": sum(len(r["inconsistencies"]) for r in active),
                     "unacknowledged_changes": sum(r["unacknowledged_changes"] for r in active),
                     "duplicate_documents": len(duplicate_items),
                     "unconfigured_launches": sum(r["completion"]["state"] == "unconfigured" for r in active),
                     "partial_launches": sum(r["completion"]["state"] == "partial" for r in active)},
            "launches": summaries, "missing_documents": missing, "priorities": priority_report,
            "pending_validation_documents": pending_items, "duplicate_documents": duplicate_items,
            "activity": activity(db, user, limit=12)["items"]}


def readable_version(db, user, version_id):
    must, _, _, _ = guards()
    must(user, "launch.read")
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(404, "Version introuvable")
    doc = version.document
    must_access(db, user, doc.folder.launch_id)
    must(user, "document.read", doc.folder.slug)
    return version


def comment_out(db, item):
    author = db.get(User, item.author_id)
    return {"id": item.id, "version_id": item.document_version_id, "body": item.body,
            "author_id": item.author_id, "author": author.name if author else "Utilisateur",
            "created_at": item.created_at.isoformat()}


def append_comment(db, user, version, body):
    _, _, audit, _ = guards()
    item = InternalComment(document_version_id=version.id, author_id=user.id, body=body.strip())
    db.add(item)
    db.flush()
    audit(db, user, "document.comment", "document_version", version.id, {"comment_id": item.id})
    return item


@router.get("/api/document-versions/{version_id}/comments")
def comments(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    readable_version(db, user, version_id)
    return [comment_out(db, row) for row in db.scalars(select(InternalComment).where(
        InternalComment.document_version_id == version_id).order_by(InternalComment.created_at))]


@router.post("/api/document-versions/{version_id}/comments", status_code=201)
def post_comment(version_id: str, payload: CommentPayload,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    version = readable_version(db, user, version_id)
    must(user, "document.write", version.document.folder.slug)
    item = append_comment(db, user, version, payload.body)
    version.document.folder.launch.updated_at = utcnow()
    db.commit()
    return comment_out(db, item)


@router.get("/api/workspace/search")
def search(q: str = "", folder: str = "", doc_type: str = "", launch_id: str = "",
           date_from: date | None = None, date_to: date | None = None,
           limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, permitted, _, _ = guards()
    must(user, "launch.read")
    launch_rows = {row.id: row for row in visible_launches(db, user)}
    results = []
    query = select(DocumentVersion).join(Document).order_by(DocumentVersion.created_at.desc())
    for version in db.scalars(query):
        document = version.document
        launch = launch_rows.get(document.folder.launch_id)
        if not launch or not permitted(user, "document.read", document.folder.slug):
            continue
        if folder and folder != document.folder.slug or launch_id and launch_id != launch.id:
            continue
        if doc_type and doc_type.casefold() not in document.doc_type.casefold():
            continue
        day = version.created_at.date()
        if date_from and day < date_from or date_to and day > date_to:
            continue
        ops = db.get(LaunchOperations, launch.id)
        text = " ".join(str(value or "") for value in (launch.name, launch.order_ref, launch.orli_ref,
                       launch.client_name, ops.article if ops else "", ops.provisional_ref if ops else "",
                       ops.definitive_ref if ops else "", document.title, document.doc_type,
                       version.original_name, version.sha256))
        if q.casefold() not in text.casefold():
            continue
        uploader = db.get(User, version.uploaded_by)
        results.append({"launch_id": launch.id, "launch_name": launch.name, "order_ref": launch.order_ref,
                        "client_name": launch.client_name, "document_id": document.id, "title": document.title,
                        "doc_type": document.doc_type, "folder": document.folder.slug,
                        "version_id": version.id, "version": version.number,
                        "is_current": version.number == max(v.number for v in document.versions),
                        "original_name": version.original_name, "size": version.size, "sha256": version.sha256,
                        "created_at": version.created_at.isoformat(), "uploader": uploader.name if uploader else None,
                        "status": document_state(db, document, version)})
    return {"total": len(results), "items": results[offset:offset + limit], "offset": offset, "limit": limit}


@router.get("/api/workspace/activity")
def audit_activity(launch_id: str | None = None, document_id: str | None = None,
                   actor_id: str | None = None, action: str | None = None,
                   date_from: date | None = None, date_to: date | None = None,
                   limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "audit.read")
    must(user, "launch.read")
    return activity(db, user, launch_id=launch_id, document_id=document_id, actor_id=actor_id,
                    action_filter=action, date_from=date_from,
                    date_to=date_to + timedelta(days=1) if date_to else None,
                    limit=limit, offset=offset, include_global=True)


@router.get("/api/launches/{launch_id}/experience-notes")
def notes(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, _, _ = guards()
    must(user, "launch.read")
    must_access(db, user, launch_id)
    must(user, "document.read", "jaune")
    return [note_out(db, row) for row in db.scalars(select(ExperienceNote).where(
        ExperienceNote.launch_id == launch_id).order_by(ExperienceNote.created_at.desc()))]


def note_out(db, row):
    author = db.get(User, row.author_id)
    return {"id": row.id, "launch_id": row.launch_id, "party_type": row.party_type,
            "party_name": row.party_name, "category": row.category, "body": row.body,
            "author": author.name if author else "Utilisateur", "created_at": row.created_at.isoformat()}


@router.post("/api/launches/{launch_id}/experience-notes", status_code=201)
def create_note(launch_id: str, payload: ExperiencePayload,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must, _, audit, _ = guards()
    must(user, "launch.read")
    launch = must_access(db, user, launch_id)
    must(user, "document.read", "jaune")
    must(user, "document.write", "jaune")
    if not payload.party_name.strip():
        raise HTTPException(422, "Nom requis")
    row = ExperienceNote(launch_id=launch_id, author_id=user.id,
                         **payload.model_dump(exclude={"party_name"}), party_name=payload.party_name.strip())
    db.add(row)
    db.flush()
    # Ne pas recopier le texte sensible dans une vue d'audit agrégée.
    audit(db, user, "experience.note.create", "launch", launch_id, {"note_id": row.id})
    launch.updated_at = utcnow()
    db.commit()
    return note_out(db, row)


@router.get("/api/workspace/experience")
def experience(party_type: str = "", q: str = "", user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    must, permitted, _, _ = guards()
    must(user, "launch.read")
    must(user, "document.read", "jaune")
    allowed = {launch.id for launch in visible_launches(db, user)}
    return [note_out(db, row) for row in db.scalars(select(ExperienceNote).order_by(ExperienceNote.created_at.desc()))
            if row.launch_id in allowed and (not party_type or row.party_type == party_type)
            and q.casefold() in (row.party_name + " " + row.body).casefold()]


@router.get("/api/admin/client-order-requests")
def client_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, _, _, admin_only = guards()
    admin_only(user)
    from .client_models import ClientOrderRequest
    from .client_routes import order_out, client_out
    return [{**order_out(row), "client": client_out(row.client)} for row in db.scalars(
        select(ClientOrderRequest).order_by(ClientOrderRequest.created_at.desc()))]


@router.get("/api/admin/client-order-requests/{request_id}")
def client_request(request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, _, _, admin_only = guards()
    admin_only(user)
    from .client_models import ClientOrderRequest
    from .client_routes import order_out, client_out
    row = db.get(ClientOrderRequest, request_id)
    if not row:
        raise HTTPException(404, "Demande client introuvable")
    from .client_workflow import order_launch_out
    return {**order_out(row, include_documents=True), "client": client_out(row.client),
            "launch": order_launch_out(db, row)}


@router.get("/api/admin/client-order-requests/{request_id}/documents/{document_id}/versions/{number}/download")
def client_attachment(request_id: str, document_id: str, number: int,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, _, audit, admin_only = guards()
    admin_only(user)
    from .client_models import ClientOrderDocument, ClientOrderDocumentVersion
    from .client_routes import CLIENT_STORAGE
    version = db.scalar(select(ClientOrderDocumentVersion).join(ClientOrderDocument).where(
        ClientOrderDocument.order_request_id == request_id, ClientOrderDocument.id == document_id,
        ClientOrderDocumentVersion.number == number))
    if not version:
        raise HTTPException(404, "Pièce client introuvable")
    path = CLIENT_STORAGE / version.disk_name
    if not path.is_file():
        raise HTTPException(503, "Fichier client indisponible")
    audit(db, user, "client.attachment.internal_download", "client_order_document", document_id,
          {"request_id": request_id, "version": number})
    db.commit()
    return FileResponse(path, filename=version.original_name, media_type="application/octet-stream")

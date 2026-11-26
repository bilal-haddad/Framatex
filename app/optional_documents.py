"""Documents complémentaires facultatifs : cases nommées propres à une commande et à un sous-dossier.

Trois catégories restent distinctes : pièces standard obligatoires et pièces standard facultatives
(checklist, 22 exigences inchangées), et pièces complémentaires personnalisées (ce module). Une case
vide n'est jamais signalée comme manquante et n'entre pas dans le dénominateur de complétude ; un
document complémentaire porte le type « Document complémentaire » et ne satisfait donc aucune
exigence standard sans un reclassement explicite. Ses documents sont des documents ordinaires :
versions, OCR, visionneuse, SHA-256, doublons, historique et droits du sous-dossier s'appliquent.

Droits (vérifiés pour la commande et le sous-dossier de la case) : consulter = document.read ;
créer ou renommer une case = document.write ; supprimer une case vide = administration,
validation (document.review) ou son auteur s'il peut déposer.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .core import get_current_user, get_db, utcnow
from .models import Document, Folder, OptionalDocumentCase, User

router = APIRouter(tags=["Documents complémentaires"])
OPTIONAL_TYPE = "Document complémentaire"


class CaseCreate(BaseModel):
    folder: Literal["jaune", "rose", "bleu", "vert"]
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)


class CaseUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)


def _can(user, action, case_or_folder, launch_id):
    from .access_control import can
    return can(user, action, case_or_folder, launch_id)


def active_cases(db: Session, launch_id: str) -> list[OptionalDocumentCase]:
    return db.scalars(select(OptionalDocumentCase).where(
        OptionalDocumentCase.launch_id == launch_id, OptionalDocumentCase.deleted_at.is_(None))
        .order_by(OptionalDocumentCase.created_at, OptionalDocumentCase.id)).all()


def case_documents(db: Session, case: OptionalDocumentCase) -> list[Document]:
    from .active_documents import is_active
    return [doc for doc in db.scalars(select(Document).where(Document.optional_case_id == case.id)) if is_active(doc)]


def case_out(db: Session, user: User, case: OptionalDocumentCase, documents=None) -> dict:
    from .access_control import is_admin
    documents = case_documents(db, case) if documents is None else documents
    author = db.get(User, case.created_by)
    may_manage = _can(user, "document.write", case.folder_slug, case.launch_id)
    return {"id": case.id, "folder": case.folder_slug, "title": case.title, "description": case.description,
            "created_by": author.name if author else None, "created_at": case.created_at.isoformat(),
            "document_ids": [doc.id for doc in documents], "can_edit": may_manage,
            "can_delete": not documents and (is_admin(user) or _can(user, "document.review", case.folder_slug, case.launch_id)
                                             or (case.created_by == user.id and may_manage))}


def folder_cases(db: Session, user: User, launch_id: str) -> dict[str, list[dict]]:
    """Cases par sous-dossier consultable (aucune case d'un sous-dossier non autorisé)."""
    by_folder: dict[str, list[dict]] = {}
    for case in active_cases(db, launch_id):
        if _can(user, "document.read", case.folder_slug, launch_id):
            by_folder.setdefault(case.folder_slug, []).append(case_out(db, user, case))
    return by_folder


def require_case(db: Session, user: User, case_id: str, action: str) -> OptionalDocumentCase:
    from .access import must_access
    case = db.get(OptionalDocumentCase, case_id)
    if not case or case.deleted_at is not None:
        raise HTTPException(404, "Case introuvable")
    must_access(db, user, case.launch_id)
    if not _can(user, "document.read", case.folder_slug, case.launch_id):
        raise HTTPException(404, "Case introuvable")              # sous-dossier non autorisé : rien n'est révélé
    if not _can(user, action, case.folder_slug, case.launch_id):
        raise HTTPException(403, "Accès interdit : habilitation insuffisante")
    return case


def _same_title(db, launch_id, folder, title, exclude=None):
    query = select(OptionalDocumentCase.id).where(
        OptionalDocumentCase.launch_id == launch_id, OptionalDocumentCase.folder_slug == folder,
        OptionalDocumentCase.deleted_at.is_(None), func.lower(OptionalDocumentCase.title) == title.lower())
    if exclude:
        query = query.where(OptionalDocumentCase.id != exclude)
    return db.scalar(query.limit(1))


def _touch(db, launch_id):
    from .models import Launch
    launch = db.get(Launch, launch_id)
    if launch:
        launch.updated_at = utcnow()


@router.post("/api/launches/{launch_id}/optional-cases", status_code=201)
def create_case(launch_id: str, payload: CaseCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .access import must_access
    from .main import audit
    must_access(db, user, launch_id)
    if not _can(user, "document.read", payload.folder, launch_id) or not _can(user, "document.write", payload.folder, launch_id):
        raise HTTPException(403, "Accès interdit : habilitation insuffisante")
    if not db.scalar(select(Folder.id).where(Folder.launch_id == launch_id, Folder.slug == payload.folder)):
        raise HTTPException(404, "Sous-dossier introuvable")
    title, description = " ".join(payload.title.split()), payload.description.strip()
    if not title:
        raise HTTPException(422, "Nommez la case du document complémentaire")
    if _same_title(db, launch_id, payload.folder, title):
        raise HTTPException(409, "Une case porte déjà ce nom dans ce sous-dossier")
    case = OptionalDocumentCase(launch_id=launch_id, folder_slug=payload.folder, title=title,
                                description=description or None, created_by=user.id)
    db.add(case)
    db.flush()
    audit(db, user, "optional_case.create", "optional_document_case", case.id,
          {"launch": launch_id, "folder": payload.folder, "title": title, "description": description or None})
    _touch(db, launch_id)
    db.commit()
    return case_out(db, user, case, [])


@router.patch("/api/optional-cases/{case_id}")
def update_case(case_id: str, payload: CaseUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import audit
    case = require_case(db, user, case_id, "document.write")
    title, description = " ".join(payload.title.split()), payload.description.strip() or None
    if not title:
        raise HTTPException(422, "Nommez la case du document complémentaire")
    if _same_title(db, case.launch_id, case.folder_slug, title, exclude=case.id):
        raise HTTPException(409, "Une case porte déjà ce nom dans ce sous-dossier")
    changes = {key: {"before": before, "after": after} for key, before, after in
               (("title", case.title, title), ("description", case.description, description)) if before != after}
    if changes:
        case.title, case.description, case.updated_at = title, description, utcnow()
        audit(db, user, "optional_case.update", "optional_document_case", case.id,
              {"launch": case.launch_id, "folder": case.folder_slug, "changes": changes})
        _touch(db, case.launch_id)
        db.commit()
    return case_out(db, user, case)


@router.delete("/api/optional-cases/{case_id}", status_code=204)
def delete_case(case_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import audit
    case = require_case(db, user, case_id, "document.read")
    if not case_out(db, user, case)["can_delete"]:
        if case_documents(db, case):
            raise HTTPException(409, "Supprimez d’abord les documents de cette case (ils restent restaurables depuis la corbeille)")
        raise HTTPException(403, "Suppression interdite pour cette case")
    case.deleted_at, case.deleted_by = utcnow(), user.id
    audit(db, user, "optional_case.delete", "optional_document_case", case.id,
          {"launch": case.launch_id, "folder": case.folder_slug, "title": case.title})
    _touch(db, case.launch_id)
    db.commit()


def attach(db: Session, user: User, launch_id: str, folder: str, case_id: str | None):
    """Case de destination d'un dépôt (contrôlée : même commande, même sous-dossier, droit de dépôt)."""
    if not case_id:
        return None
    case = db.get(OptionalDocumentCase, case_id)
    if not case or case.deleted_at is not None or case.launch_id != launch_id or case.folder_slug != folder:
        raise HTTPException(404, "Case de document complémentaire introuvable dans ce sous-dossier")
    if not _can(user, "document.write", folder, launch_id):
        raise HTTPException(403, "Accès interdit : habilitation insuffisante")
    return case


def restore_case_of(db: Session, user: User, document: Document):
    """Restauration d'un document dont la case avait été supprimée : la case revient avec lui."""
    from .main import audit
    case = db.get(OptionalDocumentCase, document.optional_case_id) if document.optional_case_id else None
    if case and case.deleted_at is not None:
        case.deleted_at = case.deleted_by = None
        audit(db, user, "optional_case.restore", "optional_document_case", case.id,
              {"launch": case.launch_id, "folder": case.folder_slug, "title": case.title, "document": document.id})

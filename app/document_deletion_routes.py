"""Logical document deletion with server-side authorization and administrator trash."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .approval_models import ApprovalRun
from .completeness_models import RequirementValidation
from .core import get_current_user, get_db, utcnow
from .models import Document, DocumentVersion, User
from .workflow import latest_review

router = APIRouter(tags=['Document deletion'])


class DeletionPayload(BaseModel):
    reason: str = Field(default='', max_length=1800)


def _deps():
    from .main import audit, is_admin
    from .access_control import can
    return audit, is_admin, can


def _active_versions(document: Document):
    return [version for version in document.versions if version.deleted_at is None]


def _validated(db: Session, version: DocumentVersion) -> bool:
    if db.scalar(select(RequirementValidation.id).where(
            RequirementValidation.document_version_id == version.id).limit(1)):
        return True
    if db.scalar(select(ApprovalRun.id).where(
            ApprovalRun.document_version_id == version.id, ApprovalRun.status == 'approved').limit(1)):
        return True
    decision = latest_review(db, version.id)
    return bool(decision and decision.decision == 'approved')


def _may_delete_version(db: Session, user: User, version: DocumentVersion) -> bool:
    audit, is_admin, can = _deps()
    document, launch_id, folder = version.document, version.document.folder.launch_id, version.document.folder.slug
    if not can(user, 'document.read', folder, launch_id):
        return False
    if is_admin(user) or can(user, 'document.review', folder, launch_id):
        return True
    return (version.uploaded_by == user.id and not _validated(db, version)
            and can(user, 'document.write', folder, launch_id))


def _may_delete_document(db: Session, user: User, document: Document) -> bool:
    audit, is_admin, can = _deps()
    if not can(user, 'document.read', document.folder.slug, document.folder.launch_id):
        return False
    if is_admin(user) or can(user, 'document.review', document.folder.slug, document.folder.launch_id):
        return True
    versions = _active_versions(document)
    return bool(versions and document.created_by == user.id
                and all(version.uploaded_by == user.id and not _validated(db, version) for version in versions)
                and can(user, 'document.write', document.folder.slug, document.folder.launch_id))


def _visible_document(document: Document):
    return document.deleted_at is None


def _update_after_change(db: Session, document: Document, version: DocumentVersion | None = None):
    """Keep downstream views conservative: deleted sources stop contributing immediately."""
    document.folder.launch.updated_at = utcnow()
    if version is not None:
        from .quality import notify_quality_rechecks
        notify_quality_rechecks(db, document, version)


@router.delete('/api/documents/{document_id}', status_code=204)
def delete_document(document_id: str, payload: DeletionPayload | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document or not _visible_document(document):
        raise HTTPException(404, 'Document introuvable')
    if not _may_delete_document(db, user, document):
        raise HTTPException(403, 'Suppression interdite pour ce document')
    document.deleted_at, document.deleted_by = utcnow(), user.id
    document.deletion_reason = (payload.reason if payload else '').strip() or None
    audit, _, _ = _deps()
    audit(db, user, 'document.delete', 'document', document.id,
          {'reason': document.deletion_reason, 'versions': [version.number for version in _active_versions(document)]})
    _update_after_change(db, document, max(_active_versions(document), key=lambda item: item.number, default=None))
    db.commit()


@router.delete('/api/document-versions/{version_id}', status_code=204)
def delete_document_version(version_id: str, payload: DeletionPayload | None = None,
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = db.get(DocumentVersion, version_id)
    if not version or version.deleted_at is not None or version.document.deleted_at is not None:
        raise HTTPException(404, 'Version introuvable')
    if not _may_delete_version(db, user, version):
        raise HTTPException(403, 'Suppression interdite pour cette version')
    version.deleted_at, version.deleted_by = utcnow(), user.id
    version.deletion_reason = (payload.reason if payload else '').strip() or None
    audit, _, _ = _deps()
    audit(db, user, 'document.version.delete', 'document_version', version.id,
          {'document_id': version.document_id, 'version': version.number, 'reason': version.deletion_reason})
    _update_after_change(db, version.document, version)
    db.commit()


def _trash_rows(db: Session, user):
    """Corbeille : une ligne par document supprimé, une ligne par version supprimée d'un document actif."""
    from .document_purge import check
    from .models import Document as Doc, Folder, Launch
    names = {}
    def who(uid):
        if uid and uid not in names:
            person = db.get(User, uid); names[uid] = person.name if person else None
        return names.get(uid)
    rows = []
    deleted_docs = db.scalars(select(Doc).where(Doc.deleted_at.is_not(None)).order_by(Doc.deleted_at.desc())).all()
    loose = db.scalars(select(DocumentVersion).join(Doc).where(Doc.deleted_at.is_(None), DocumentVersion.deleted_at.is_not(None))
                       .order_by(DocumentVersion.deleted_at.desc())).all()
    for kind, document, versions in [('document', d, list(d.versions)) for d in deleted_docs] + [('version', v.document, [v]) for v in loose]:
        latest = max(versions, key=lambda item: item.number) if versions else None
        launch = document.folder.launch
        marker = document if kind == 'document' else versions[0]
        verdict = check(db, document, versions)
        rows.append({'kind': kind, 'document_id': document.id, 'version_id': latest.id if latest else None,
                     'title': document.title, 'original_name': latest.original_name if latest else None,
                     'doc_type': document.doc_type, 'folder': document.folder.slug,
                     'launch_id': launch.id, 'launch_name': launch.name, 'order_ref': launch.order_ref,
                     'version': latest.number if latest else None, 'versions': sorted(v.number for v in versions),
                     'size': sum(v.size for v in versions), 'deleted_at': marker.deleted_at.isoformat(),
                     'deleted_by': who(marker.deleted_by), 'reason': marker.deletion_reason,
                     'purge': verdict})
    return sorted(rows, key=lambda row: row['deleted_at'], reverse=True)


@router.get('/api/admin/document-trash')
def document_trash(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit, is_admin, _ = _deps()
    if not is_admin(user):
        raise HTTPException(403, "Fonction réservée à l'administration")
    return {'items': _trash_rows(db, user)}


@router.post('/api/admin/document-trash/documents/{document_id}/restore')
def restore_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit, is_admin, _ = _deps()
    if not is_admin(user):
        raise HTTPException(403, "Fonction réservée à l'administration")
    document = db.get(Document, document_id)
    if not document or document.deleted_at is None:
        raise HTTPException(404, 'Document supprimé introuvable')
    document.deleted_at = document.deleted_by = document.deletion_reason = None
    audit(db, user, 'document.restore', 'document', document.id, {})
    from .optional_documents import restore_case_of
    restore_case_of(db, user, document)
    _update_after_change(db, document, max(_active_versions(document), key=lambda item: item.number, default=None))
    db.commit()
    return {'restored': 'document', 'id': document.id}


@router.post('/api/admin/document-trash/versions/{version_id}/restore')
def restore_version(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit, is_admin, _ = _deps()
    if not is_admin(user):
        raise HTTPException(403, "Fonction réservée à l'administration")
    version = db.get(DocumentVersion, version_id)
    if not version or version.deleted_at is None or version.document.deleted_at is not None:
        raise HTTPException(404, 'Version supprimée introuvable')
    version.deleted_at = version.deleted_by = version.deletion_reason = None
    audit(db, user, 'document.version.restore', 'document_version', version.id,
          {'document_id': version.document_id, 'version': version.number})
    _update_after_change(db, version.document, version)
    db.commit()
    return {'restored': 'version', 'id': version.id}

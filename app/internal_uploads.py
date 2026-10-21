"""Détection de doublons limitée aux pièces autorisées du même sous-dossier."""
from sqlalchemy import select
from .models import Document, DocumentVersion, Folder


def duplicates(db, user, launch_id, folder_slug, digest, exclude_id=None):
    from .main import permitted
    if not permitted(user, "document.read", folder_slug):
        return []
    query = (select(DocumentVersion).join(Document).join(Folder)
             .where(Folder.launch_id == launch_id, Folder.slug == folder_slug,
                    DocumentVersion.sha256 == digest))
    if exclude_id:
        query = query.where(Document.id != exclude_id)
    return [{"document_id": v.document_id, "title": v.document.title,
             "version": v.number, "sha256": v.sha256} for v in db.scalars(query)]

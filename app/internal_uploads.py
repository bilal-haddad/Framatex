"""Détection de doublons limitée aux pièces autorisées du même sous-dossier.

Seuls les documents actifs comptent. Un doublon courant = même empreinte que la version courante
d'un autre document actif ; une version antérieure non supprimée est signalée à part comme
correspondance historique ; documents et versions supprimés sont toujours ignorés."""
from sqlalchemy import select
from .active_documents import current_version
from .models import Document, DocumentVersion, Folder


def duplicates(db, user, launch_id, folder_slug, digest, exclude_id=None, historical=False):
    from .main import permitted
    if not permitted(user, "document.read", folder_slug):
        return []
    query = (select(DocumentVersion).join(Document).join(Folder)
             .where(Folder.launch_id == launch_id, Folder.slug == folder_slug,
                    DocumentVersion.sha256 == digest,
                    Document.deleted_at.is_(None), DocumentVersion.deleted_at.is_(None)))
    if exclude_id:
        query = query.where(Document.id != exclude_id)
    rows = []
    for v in db.scalars(query):
        current = current_version(v.document)
        is_current = current is not None and current.id == v.id
        if is_current != historical:
            rows.append({"document_id": v.document_id, "title": v.document.title,
                         "version": v.number, "sha256": v.sha256, "historical": not is_current})
    return rows

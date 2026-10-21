"""Doublons : un même contenu (SHA-256) dans plusieurs documents d'un même Dossier Jaune.

Seules les versions courantes des sous-dossiers lisibles par l'utilisateur sont
comparées : un document identique placé dans un sous-dossier non autorisé n'est
jamais révélé. Un doublon examiné et conservé (motif obligatoire) n'est plus
signalé, tant qu'aucune nouvelle pièce identique ne s'ajoute au groupe.
"""
from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select

from .completeness_models import DuplicateReview
from .models import User


def duplicate_groups(db, user, launch):
    from .main import permitted
    by_digest = defaultdict(list)
    for folder in launch.folders:
        if not permitted(user, "document.read", folder.slug):
            continue
        for document in folder.documents:
            if document.versions:
                current = max(document.versions, key=lambda v: v.number)
                by_digest[current.sha256].append((folder.slug, document, current))
    reviews = {}
    for review in db.scalars(select(DuplicateReview).where(DuplicateReview.launch_id == launch.id)
                             .order_by(DuplicateReview.decided_at)):
        reviews[review.sha256] = review          # la dernière décision fait foi
    groups = []
    for digest, items in by_digest.items():
        if len(items) < 2:
            continue
        review = reviews.get(digest)
        reviewed = bool(review and {v.id for _, _, v in items} <= set(json.loads(review.version_ids)))
        author = db.get(User, review.decided_by) if reviewed else None
        groups.append({
            "sha256": digest, "reviewed": reviewed,
            "review": {"reason": review.reason, "by": author.name if author else None,
                       "at": review.decided_at.isoformat()} if reviewed else None,
            "documents": [{"document_id": d.id, "title": d.title, "doc_type": d.doc_type, "folder": slug,
                           "version": v.number, "version_id": v.id, "original_name": v.original_name,
                           "created_at": v.created_at.isoformat()}
                          for slug, d, v in sorted(items, key=lambda item: item[2].created_at)],
        })
    return sorted(groups, key=lambda g: g["documents"][-1]["created_at"], reverse=True)

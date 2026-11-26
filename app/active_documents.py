"""Documents et versions actifs : une seule règle pour tous les contrôles (doublons, rapprochements,
compteurs, alertes). Un document supprimé, ou dont toutes les versions sont supprimées, est inactif ;
une version supprimée ne compte jamais. Les traces d'audit ne sont pas concernées."""
from __future__ import annotations


def active_versions(document) -> list:
    if document is None or document.deleted_at is not None:
        return []
    return [version for version in document.versions if version.deleted_at is None]


def current_version(document):
    """Version courante = plus haute version non supprimée d'un document non supprimé (ou None)."""
    return max(active_versions(document), key=lambda version: version.number, default=None)


def is_active(document) -> bool:
    return current_version(document) is not None

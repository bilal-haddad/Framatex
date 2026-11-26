"""Suppression définitive (administrateur uniquement) de documents et de versions déjà en corbeille.

Règles :
- seule l'administration peut détruire ; les autres rôles gardent la suppression logique ;
- seul un élément déjà placé dans la corbeille peut être détruit ;
- refus tant qu'une dépendance métier subsiste (circuit, partage ou publication Client, valeur
  métier, exigence Client, mouvement matière, email archivé, validation, décision, etc.) ;
- refus tant que l'obligation de conservation est connue et en cours, ou inconnue, sans vérification
  administrative enregistrée (`RetentionClearance`) ;
- les données dérivées (identification, OCR, index plein texte, inspections, rapprochements,
  commentaires) sont effacées avec la version ; la trace minimale reste dans l'audit ;
- le fichier physique n'est effacé qu'après la validation en base, via une file reprise au
  démarrage, et jamais s'il est encore référencé ailleurs.

Les sauvegardes déjà réalisées ne sont pas modifiées : voir docs/PRODUCTION_ARCHITECTURE.md.
"""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from .core import DATA_DIR, get_current_user, get_db, utcnow
from .models import Document, DocumentVersion, RetentionClearance, StoragePurge, User

router = APIRouter(tags=["Suppression définitive"])
CONFIRMATION = "SUPPRIMER"

# Politique de conservation par défaut (années) — à faire valider par FRAMATEX et son conseil.
# 0 = aucune obligation connue ; type absent = obligation inconnue (vérification administrative requise).
# Surcharge possible : FRAMATEX_DATA_DIR/retention-policy.json {"Type": années, ...}.
DEFAULT_RETENTION = {
    **{kind: 10 for kind in ("Facture", "Facture FRAMATEX", "Document facturation", "Justificatif facturation",
                              "Avoir / correction de facture", "Pièce de facturation associée", "Pièce douanière",
                              "Déclaration douanière", "Justificatif import/export", "Documents import / export",
                              "Justificatif de dédouanement", "Document transit", "Document transport",
                              "Commande client", "Bon de livraison", "Bon / note de réception", "Bon de réception")},
    **{kind: 0 for kind in ("Autre", "Document complémentaire", "Email", "Emails techniques", "Emails réception / logistique",
                             "Test tissu", "Tests tissu", "Excel BE", "Étude BE / Excel", "Fiche technique",
                             "Dossier technique client", "Fiche d’emploi", "Calcul du besoin", "Fiche de prix",
                             "Lancement provisoire", "Lancement définitif", "Document réception", "Document de réception matière")},
}


def retention_policy() -> dict[str, int]:
    policy = dict(DEFAULT_RETENTION)
    path = Path(os.getenv("FRAMATEX_RETENTION_POLICY", DATA_DIR / "retention-policy.json"))
    if path.is_file():
        try:
            policy.update({str(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()})
        except (ValueError, TypeError, OSError) as exc:            # politique illisible : rien n'est détruit
            raise HTTPException(503, f"Politique de conservation illisible : {exc}") from exc
    return policy


# Dépendances métier : (table, colonne, libellé). Une seule ligne suffit à bloquer la destruction.
BLOCKING = [
    ("approval_runs", "document_version_id", "circuit de validation"),
    ("client_publications", "document_version_id", "publication Client"),
    ("client_shared_documents", "document_version_id", "document partagé avec un Client"),
    ("business_value_revisions", "source_version_id", "valeur métier confirmée"),
    ("client_requirements", "source_version_id", "exigence Client (source)"),
    ("client_requirements", "evidence_version_id", "exigence Client (preuve)"),
    ("specification_ambiguities", "source_version_id", "ambiguïté de cahier des charges"),
    ("specification_ambiguities", "clarification_version_id", "clarification de cahier des charges"),
    ("material_movements", "source_version_id", "mouvement matière"),
    ("material_plan_revisions", "source_version_id", "plan matière"),
    ("archived_emails", "document_version_id", "email archivé"),
    ("supplier_document_requests", "response_version_id", "réponse fournisseur"),
    ("requirement_validations", "document_version_id", "validation de complétude"),
    ("document_reviews", "document_version_id", "décision documentaire"),
    ("confirmed_extracted_fields", "document_version_id", "valeur extraite confirmée"),
    ("document_data", "document_version_id", "donnée qualité saisie"),
    ("internal_experience_notes", "evidence_version_id", "preuve de mémoire métier"),
]
# Données dérivées, effacées avec la version.
DERIVED = [("document_identifications", "version_id"), ("excel_inspections", "document_version_id"),
           ("document_relationship_decisions", "uploaded_version_id"), ("internal_document_comments", "document_version_id")]
NULLABLE_LINKS = [("excel_inspections", "baseline_version_id"), ("document_relationship_decisions", "candidate_version_id")]


class PurgePayload(BaseModel):
    confirmation: str = Field(max_length=40)
    reason: str = Field(min_length=8, max_length=1800)


class ClearancePayload(BaseModel):
    reason: str = Field(min_length=12, max_length=1800)


def _admin(user):
    from .access_control import is_admin
    if not is_admin(user):
        raise HTTPException(403, "Suppression définitive réservée à l'administration")


def _target(db, kind, item_id):
    """(document, versions à détruire) d'un élément en corbeille."""
    if kind == "documents":
        document = db.get(Document, item_id)
        if not document or document.deleted_at is None:
            raise HTTPException(404, "Document absent de la corbeille")
        return document, list(document.versions)
    version = db.get(DocumentVersion, item_id)
    if not version or version.deleted_at is None or version.document.deleted_at is not None:
        raise HTTPException(404, "Version absente de la corbeille")
    return version.document, [version]


def _existing_tables(db) -> set[str]:
    from sqlalchemy import inspect
    return set(inspect(db.connection()).get_table_names())        # SQLite et PostgreSQL


def blockers(db, versions) -> list[str]:
    ids = [v.id for v in versions]
    if not ids:
        return []
    tables, found = _existing_tables(db), []
    marks = ", ".join(f":v{i}" for i in range(len(ids)))
    params = {f"v{i}": vid for i, vid in enumerate(ids)}
    for table, column, label in BLOCKING:
        if table in tables and db.execute(text(f"SELECT 1 FROM {table} WHERE {column} IN ({marks}) LIMIT 1"), params).first():
            found.append(label)
    # Une version de référence d'une autre version (inspection Excel) n'est pas bloquante : le lien est retiré.
    return sorted(set(found))


def retention(db, document, versions) -> dict:
    """État de conservation : free | cleared | protected | unknown (les deux derniers bloquent)."""
    years = retention_policy().get(document.doc_type)
    cleared = db.scalar(select(RetentionClearance).where(RetentionClearance.document_id == document.id,
        (RetentionClearance.version_id.is_(None)) | (RetentionClearance.version_id.in_([v.id for v in versions])))
        .order_by(RetentionClearance.cleared_at.desc()).limit(1))
    if cleared:
        return {"status": "cleared", "years": years, "reason": cleared.reason, "at": cleared.cleared_at.isoformat()}
    if years == 0:
        return {"status": "free", "years": 0}
    if years is None:
        return {"status": "unknown", "years": None,
                "message": f"Obligation de conservation inconnue pour le type « {document.doc_type} » : vérification administrative requise."}
    oldest = min(v.created_at for v in versions)
    until = oldest + timedelta(days=365 * years)
    if until.replace(tzinfo=None) > utcnow().replace(tzinfo=None):
        return {"status": "protected", "years": years, "until": until.date().isoformat(),
                "message": f"Type « {document.doc_type} » soumis à conservation ({years} ans, jusqu'au {until.date().isoformat()})."}
    return {"status": "free", "years": years}


def check(db, document, versions) -> dict:
    found = blockers(db, versions)
    keep = retention(db, document, versions)
    return {"blockers": found, "retention": keep,
            "allowed": not found and keep["status"] in ("free", "cleared")}


@router.get("/api/admin/document-trash/{kind}/{item_id}/purge-check")
def purge_check(kind: str, item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _admin(user)
    if kind not in ("documents", "versions"):
        raise HTTPException(404, "Élément inconnu")
    document, versions = _target(db, kind, item_id)
    return check(db, document, versions)


@router.post("/api/admin/document-trash/{kind}/{item_id}/retention-clearance", status_code=201)
def clear_retention(kind: str, item_id: str, payload: ClearancePayload,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Vérification administrative : l'élément n'est soumis à aucune obligation de conservation
    (dépôt erroné, doublon, document hors périmètre…). Motif obligatoire, tracé dans l'audit."""
    from .main import audit
    _admin(user)
    if kind not in ("documents", "versions"):
        raise HTTPException(404, "Élément inconnu")
    document, versions = _target(db, kind, item_id)
    clearance = RetentionClearance(document_id=document.id, version_id=None if kind == "documents" else versions[0].id,
                                   reason=payload.reason.strip(), cleared_by=user.id)
    db.add(clearance)
    audit(db, user, "document.retention.clear", "document", document.id,
          {"launch": document.folder.launch_id, "folder": document.folder.slug, "doc_type": document.doc_type,
           "version_id": None if kind == "documents" else versions[0].id, "reason": clearance.reason,
           "policy_years": retention_policy().get(document.doc_type)})
    db.commit()
    return check(db, document, versions)


@router.post("/api/admin/document-trash/{kind}/{item_id}/purge")
def purge(kind: str, item_id: str, payload: PurgePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import audit
    _admin(user)
    if kind not in ("documents", "versions"):
        raise HTTPException(404, "Élément inconnu")
    if payload.confirmation.strip().upper() != CONFIRMATION:
        raise HTTPException(422, f"Saisissez « {CONFIRMATION} » pour confirmer la suppression définitive")
    document, versions = _target(db, kind, item_id)
    verdict = check(db, document, versions)
    if verdict["blockers"]:
        raise HTTPException(409, "Destruction refusée : élément encore utilisé (" + ", ".join(verdict["blockers"]) + ")")
    if not verdict["allowed"]:
        raise HTTPException(409, verdict["retention"].get("message") or "Destruction refusée : conservation documentaire à vérifier")
    launch_id, folder, doc_type = document.folder.launch_id, document.folder.slug, document.doc_type
    ids = [v.id for v in versions]
    trace = {"launch": launch_id, "folder": folder, "doc_type": doc_type, "scope": "document" if kind == "documents" else "version",
             "document_id": document.id, "versions": sorted(v.number for v in versions),
             "sha256": [v.sha256 for v in versions], "bytes": sum(v.size for v in versions),
             "deleted_by": (document.deleted_by if kind == "documents" else versions[0].deleted_by),
             "reason": payload.reason.strip(), "retention": verdict["retention"]["status"]}
    disks = {v.disk_name for v in versions}
    tables = _existing_tables(db)
    for table, column in NULLABLE_LINKS:
        if table in tables:
            for vid in ids:
                db.execute(text(f"UPDATE {table} SET {column} = NULL WHERE {column} = :v"), {"v": vid})
    for table, column in DERIVED:
        if table in tables:
            for vid in ids:
                db.execute(text(f"DELETE FROM {table} WHERE {column} = :v"), {"v": vid})
    if tables & {"document_content_fts", "document_search_index"}:
        from .document_search import remove_version
        for vid in ids:
            remove_version(db, vid)
    db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(ids)))
    if kind == "documents":
        db.execute(delete(Document).where(Document.id == document.id))
    # Fichier physique : effacé après validation, et seulement s'il n'est plus référencé.
    for disk in disks:
        db.add(StoragePurge(disk_name=disk))
    audit(db, user, "document.purge", "document", document.id, trace)
    from .models import Launch
    launch = db.get(Launch, launch_id)
    if launch:
        launch.updated_at = utcnow()
    db.commit()
    process_purge_queue(db)
    return {"purged": trace["scope"], "document_id": document.id, "versions": trace["versions"]}


def process_purge_queue(db=None) -> dict:
    """Efface les fichiers en attente qui ne sont plus référencés (appelé après chaque purge et au démarrage)."""
    from .core import SessionLocal
    from .main import STORAGE
    own = db is None
    db = db or SessionLocal()
    done = kept = 0
    try:
        for item in db.scalars(select(StoragePurge).where(StoragePurge.done_at.is_(None))).all():
            still_used = db.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.disk_name == item.disk_name))
            if still_used:
                item.outcome, kept = "conservé (encore référencé)", kept + 1
            else:
                path = STORAGE / item.disk_name
                try:
                    path.unlink(missing_ok=True)
                    item.outcome, done = "effacé", done + 1
                except OSError as exc:                     # fichier verrouillé (Windows) : nouvelle tentative au démarrage
                    item.outcome = f"échec : {exc.__class__.__name__}"[:40]
                    continue
            item.done_at = utcnow()
        db.commit()
    finally:
        if own:
            db.close()
    return {"erased": done, "kept": kept}

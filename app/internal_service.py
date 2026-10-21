"""Synthèses calculées depuis les moteurs existants, après filtrage des droits."""
from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from .access import accessible, visible
from .approval_models import ApprovalRun
from .completeness import evaluate
from .internal_models import InternalComment, LaunchOperations
from .models import AuditEvent, Document, DocumentVersion, Folder, Launch, User
from .workflow import latest_review
from .workflow_models import BusinessValueRevision, ImpactAlert, ImpactRule

FOLDER_LABELS = {"jaune": "JAUNE / TECHNIQUE", "rose": "ROSE / RÉCEPTION",
                 "bleu": "BLEU / DÉDOUANEMENT", "vert": "VERT / FACTURES"}
DOCUMENT_TYPES = {
    "jaune": ["Dossier technique client", "Commande client", "Lancement provisoire",
              "Lancement définitif", "Fiche d’emploi", "Calcul du besoin", "Fiche de prix",
              "Tests tissu", "Excel BE", "Email", "Autre"],
    "rose": ["Bon de livraison", "Bon de réception", "Document réception", "Email", "Autre"],
    "bleu": ["Pièce douanière", "Justificatif import/export", "Document transit", "Document transport",
             "Justificatif de dédouanement", "Autre"],
    "vert": ["Facture", "Document facturation", "Justificatif facturation", "Avoir / correction de facture", "Autre"],
}


def document_state(db: Session, document: Document, version=None):
    version = version or (max(document.versions, key=lambda v: v.number) if document.versions else None)
    if not version:
        return "to_review"
    run = db.scalar(select(ApprovalRun).where(ApprovalRun.document_version_id == version.id)
                    .order_by(ApprovalRun.started_at.desc()).limit(1))
    if run:
        return {"approved": "approved", "rejected": "rejected", "changes_requested": "changes_requested"}.get(run.status, "to_review")
    review = latest_review(db, version.id)
    return review.decision if review else "to_review"


def completion_summary(report):
    due = [row for row in report["rows"] if row["due"]]
    present = sum(row["status"] == "present" for row in due)
    # Une dérogation reste distincte d'une pièce présente, même à 0 document manquant.
    complete = (bool(due) and all(row["status"] == "present" for row in due))
    state = ("unconfigured" if not report["configured"] else "partial" if report["partial_visibility"]
             else "not_due" if not due else "complete" if complete else "incomplete")
    return {"state": state, "counts": report["counts"], "due_count": len(due),
            "present_due": present, "percent": round(100 * present / len(due)) if due else None,
            "partial_visibility": report["partial_visibility"]}


def visible_launches(db, user):
    return visible(db, user, db.scalars(select(Launch).order_by(Launch.updated_at.desc())).all())


def launch_summary(db, user, launch):
    from .main import launch_out, permitted
    from .quality_routes import quality_report
    report = evaluate(db, launch, user, permitted)
    quality = quality_report(launch.id, user, db)
    concerns = [r for r in quality["rows"] if r["status"] in {"difference", "unit_mismatch", "ambiguous"}
                and (not r.get("decision") or r["decision"]["status"] == "to_correct")]
    impacts = []
    for alert in db.scalars(select(ImpactAlert).where(ImpactAlert.launch_id == launch.id,
                        ImpactAlert.status.in_(["to_review", "action_required"]))):
        rule = db.get(ImpactRule, alert.rule_id)
        if rule and all(permitted(user, "document.read", f) for f in (rule.source_folder, rule.target_folder)):
            impacts.append((alert, rule))
    operations = db.get(LaunchOperations, launch.id)
    responsible = db.get(User, operations.responsible_id) if operations and operations.responsible_id else None
    folders = []
    activity_targets = [launch.id]
    timestamps = [launch.updated_at.isoformat()]
    if operations:
        timestamps.append(operations.updated_at.isoformat())
    for folder in launch.folders:
        if not permitted(user, "document.read", folder.slug):
            folders.append({"slug": folder.slug, "label": FOLDER_LABELS[folder.slug], "can_read": False})
            continue
        rows = [r for r in report["rows"] if r["folder"] == folder.slug]
        docs = folder.documents
        pending_ids = {d["id"] for row in rows if row["status"] == "pending_validation" for d in row["documents"]}
        for doc in docs:
            if not doc.versions:
                continue
            current = max(doc.versions, key=lambda v: v.number)
            if db.scalar(select(ApprovalRun.id).where(ApprovalRun.document_version_id == current.id,
                                                      ApprovalRun.status == "pending").limit(1)):
                pending_ids.add(doc.id)
        folder_summary = completion_summary({**report, "rows": rows, "counts": {
            k: sum(r["status"] == k for r in rows) for k in report["counts"]}, "partial_visibility": False,
            "configured": bool(rows)})
        folders.append({"slug": folder.slug, "label": FOLDER_LABELS[folder.slug], "can_read": True,
                        "can_write": permitted(user, "document.write", folder.slug),
                        "documents": len(docs), "completion": folder_summary,
                        "pending_validation": len(pending_ids),
                        "alerts": sum(rule.target_folder == folder.slug for _, rule in impacts)
                                  + sum(folder.slug in r["folders"] for r in concerns),
                        "requirements": rows})
        for doc in docs:
            activity_targets.append(doc.id)
            activity_targets.extend(v.id for v in doc.versions)
            timestamps.extend(v.created_at.isoformat() for v in doc.versions)
    activity_targets.extend(alert.id for alert, _ in impacts)
    last_event = db.scalar(select(AuditEvent).where(AuditEvent.target_id.in_(activity_targets))
                          .order_by(AuditEvent.occurred_at.desc()).limit(1))
    if last_event:
        timestamps.append(last_event.occurred_at.isoformat())
    return {**launch_out(launch), "article": operations.article if operations else None,
            "quantity": operations.quantity if operations else None,
            "provisional_ref": operations.provisional_ref if operations else None,
            "definitive_ref": operations.definitive_ref if operations else None,
            "responsible_id": responsible.id if responsible else None,
            "responsible": responsible.name if responsible else None,
            "completion": completion_summary(report), "folders": folders,
            "alerts": len(impacts) + len(concerns), "unacknowledged_changes": len(impacts),
            "inconsistencies": concerns, "last_activity": max(timestamps)}


def extra_actions(db, user, launches):
    from .main import permitted
    from .quality_routes import quality_report, list_excel_inspections
    items = []
    for launch in launches:
        if launch.status == "Clôturé":
            continue
        for row in quality_report(launch.id, user, db)["rows"]:
            if row["status"] not in {"difference", "unit_mismatch", "ambiguous"}:
                continue
            if row.get("decision", {}).get("status") == "justified":
                continue
            pair = row["pair"][0] if row["pair"] else {}
            items.append(action(launch, "quality:" + row["rule_id"], "Incohérence : " + row["name"],
                                row["reason"], "quality", pair.get("folder", row["folders"][0]),
                                pair.get("document_id"), pair.get("version_id")))
        for folder in launch.folders:
            if not permitted(user, "document.read", folder.slug):
                continue
            for doc in folder.documents:
                if not doc.versions:
                    continue
                current = max(doc.versions, key=lambda v: v.number)
                pending_run = db.scalar(select(ApprovalRun).where(ApprovalRun.document_version_id == current.id,
                        ApprovalRun.status == "pending").limit(1))
                if pending_run:
                    items.append(action(launch, "approval:" + pending_run.id, "Circuit à valider : " + doc.title,
                                        "Étape de validation en attente", "approvals", folder.slug, doc.id, current.id))
                if document_state(db, doc) in {"rejected", "changes_requested"}:
                    items.append(action(launch, "correction:" + doc.id, "Document à corriger : " + doc.title,
                                        "Décision sur la version courante", "workflow", folder.slug, doc.id, current.id))
        for row in list_excel_inspections(launch.id, user, db):
            inspection = row["inspection"]
            if inspection and any(f["type"] != "inspection_limit" for f in inspection["findings"]):
                # Une ancienne anomalie reste historique, pas une alerte sur la version actuelle.
                doc = db.get(Document, row["document_id"])
                if max(v.number for v in doc.versions) != row["version"]:
                    continue
                items.append(action(launch, "excel:" + row["version_id"], "Excel à vérifier : " + row["document_title"],
                                    "Inspection statique ; examen humain requis", "quality", row["folder"],
                                    row["document_id"], row["version_id"]))
    return items


def action(launch, key, title, description, area, folder=None, document_id=None, version_id=None):
    return {"id": key, "launch_id": launch.id, "launch_name": launch.name, "kind": key.split(":")[0],
            "title": title, "description": description, "rank": 1, "priority": "high",
            "priority_reason": "Vérification documentaire ou métier requise", "area": area,
            "action": "open_launch", "deadline": None, "folder": folder,
            "document_id": document_id, "version_id": version_id}


def resolve_event(db, event):
    """Résout la portée d'une opération avant d'en exposer le moindre détail."""
    try:
        detail = json.loads(event.detail)
    except (TypeError, ValueError):
        detail = {}
    doc = version = launch = None
    if event.target_type == "launch":
        launch = db.get(Launch, event.target_id)
    elif event.target_type == "document":
        doc = db.get(Document, event.target_id)
    elif event.target_type == "document_version":
        version = db.get(DocumentVersion, event.target_id)
        doc = version.document if version else None
    if doc:
        launch = doc.folder.launch
    if not launch and (detail.get("launch") or detail.get("launch_id")):
        launch = db.get(Launch, detail.get("launch") or detail.get("launch_id"))
    return launch, doc, version, detail


def activity(db, user, *, launch_id=None, document_id=None, actor_id=None, action_filter=None,
             date_from=None, date_to=None, limit=100, offset=0, include_global=False):
    from .main import is_admin, permitted
    query = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if action_filter:
        query = query.where(AuditEvent.action == action_filter)
    if date_from:
        query = query.where(AuditEvent.occurred_at >= date_from)
    if date_to:
        query = query.where(AuditEvent.occurred_at < date_to)
    output = []
    for event in db.scalars(query):
        launch, doc, version, detail = resolve_event(db, event)
        if not launch:
            if not (include_global and is_admin(user)) or launch_id or document_id:
                continue
        else:
            if not accessible(db, user, launch):
                continue
            if doc and not permitted(user, "document.read", doc.folder.slug):
                continue
            # Une opération sur deux sous-dossiers n'est visible que si les deux le sont.
            if not doc and not all(permitted(user, "document.read", slug) for slug in FOLDER_LABELS):
                continue
            if launch_id and launch.id != launch_id:
                continue
            if document_id and (not doc or doc.id != document_id):
                continue
        actor = db.get(User, event.actor_id) if event.actor_id else None
        output.append({"id": event.id, "action": event.action, "actor_id": event.actor_id,
                       "actor": actor.name if actor else "Compte client" if event.action.startswith("client.") else "Système",
                       "target_type": event.target_type, "target_id": event.target_id, "detail": detail,
                       "launch_id": launch.id if launch else None, "launch_name": launch.name if launch else None,
                       "document_id": doc.id if doc else None, "document_title": doc.title if doc else None,
                       "folder": doc.folder.slug if doc else None,
                       "version_id": version.id if version else None, "occurred_at": event.occurred_at.isoformat()})
    return {"total": len(output), "items": output[offset:offset + limit], "limit": limit, "offset": offset}

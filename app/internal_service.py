"""Synthèses calculées depuis les moteurs existants, après filtrage des droits."""
from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from .active_documents import active_versions, current_version
from .access import accessible, visible
from .approval_models import ApprovalRun
from .completeness import evaluate
from .internal_models import InternalComment, LaunchOperations
from .models import AuditEvent, Document, DocumentVersion, Folder, Launch, User
from .workflow import latest_review
from .workflow_models import BusinessValueRevision, ImpactAlert, ImpactRule

FOLDER_LABELS = {"jaune": "SOUS-DOSSIER JAUNE", "rose": "SOUS-DOSSIER ROSE",
                 "bleu": "SOUS-DOSSIER BLEU", "vert": "SOUS-DOSSIER VERT"}
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
    version = version or current_version(document)
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


def launch_summary(db, user, launch, cache=None, light=False):
    """Synthèse d'une commande. `cache` : évaluations de complétude déjà calculées pour ce même
    utilisateur dans ce même calcul (réutilisées par les priorités). `light` : sans les lignes
    d'exigences par sous-dossier (listes et tableau de bord, qui ne les affichent pas)."""
    # Habilitations par commande : tous les contrôles de sous-dossier portent sur cette commande.
    from .access_control import launch_scope
    with launch_scope(launch.id):
        summary = _launch_summary(db, user, launch, cache)
    if light:
        summary["folders"] = [{k: v for k, v in folder.items() if k != "requirements"} for folder in summary["folders"]]
    return summary


def _launch_summary(db, user, launch, cache=None):
    from .main import launch_out, permitted
    from .quality_routes import quality_report
    report = cache.get(launch.id) if cache is not None and launch.id in cache else evaluate(db, launch, user, permitted)
    if cache is not None:
        cache[launch.id] = report
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
    # Documents de la commande et leurs versions en deux requêtes (au lieu d'une par document).
    from sqlalchemy.orm import selectinload
    all_docs = db.scalars(select(Document).join(Folder).options(selectinload(Document.versions))
                          .where(Folder.launch_id == launch.id)).all()
    docs_by_folder = {}
    for doc in all_docs:
        docs_by_folder.setdefault(doc.folder_id, []).append(doc)
    currents = {doc.id: current_version(doc) for doc in all_docs}
    current_ids = [v.id for v in currents.values() if v is not None]
    pending_runs = set(db.scalars(select(ApprovalRun.document_version_id).where(
        ApprovalRun.document_version_id.in_(current_ids), ApprovalRun.status == "pending"))) if current_ids else set()
    for folder in launch.folders:
        if not permitted(user, "document.read", folder.slug):
            folders.append({"slug": folder.slug, "label": FOLDER_LABELS[folder.slug], "can_read": False})
            continue
        rows = [r for r in report["rows"] if r["folder"] == folder.slug]
        docs = docs_by_folder.get(folder.id, [])
        pending_ids = {d["id"] for row in rows if row["status"] == "pending_validation" for d in row["documents"]}
        for doc in docs:
            current = currents[doc.id]
            if current is not None and current.id in pending_runs:
                pending_ids.add(doc.id)
        folder_summary = completion_summary({**report, "rows": rows, "counts": {
            k: sum(r["status"] == k for r in rows) for k in report["counts"]}, "partial_visibility": False,
            "configured": bool(rows)})
        folders.append({"slug": folder.slug, "label": FOLDER_LABELS[folder.slug], "can_read": True,
                        "can_write": permitted(user, "document.write", folder.slug),
                        "documents": sum(currents[doc.id] is not None for doc in docs), "completion": folder_summary,
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
            "completion": completion_summary(report), "phase": report["phase"],
            "profile_name": report["profile_name"], "folders": folders,
            "alerts": len(impacts) + len(concerns), "unacknowledged_changes": len(impacts),
            "inconsistencies": concerns, "last_activity": max(timestamps)}


def extra_actions(db, user, launches):
    from .access_control import launch_scope
    items = []
    for launch in launches:
        with launch_scope(launch.id):
            items.extend(_extra_actions(db, user, [launch]))
    return items


def _extra_actions(db, user, launches):
    from .main import permitted
    from .quality_routes import quality_report, list_excel_inspections
    items = []
    for launch in launches:
        if launch.status == "Clôturé":
            continue
        for row in quality_report(launch.id, user, db)["rows"]:
            if row["status"] not in {"difference", "unit_mismatch", "ambiguous"}:
                continue
            if (row.get("decision") or {}).get("status") == "justified":
                continue
            pair = row["pair"][0] if row["pair"] else {}
            items.append(action(launch, "quality:" + row["rule_id"], "Incohérence : " + row["name"],
                                row["reason"], "quality", pair.get("folder", row["folders"][0]),
                                pair.get("document_id"), pair.get("version_id")))
        # Documents, versions, circuits et décisions lus en quelques requêtes pour toute la commande.
        from sqlalchemy.orm import selectinload
        from .workflow_models import DocumentReview
        readable = [f for f in launch.folders if permitted(user, "document.read", f.slug)]
        docs = db.scalars(select(Document).options(selectinload(Document.versions)).where(
            Document.folder_id.in_([f.id for f in readable]))).all() if readable else []
        currents = {doc.id: current_version(doc) for doc in docs}
        ids = [v.id for v in currents.values() if v is not None]
        runs, reviews = {}, {}
        if ids:
            for run in db.scalars(select(ApprovalRun).where(ApprovalRun.document_version_id.in_(ids)).order_by(ApprovalRun.started_at)):
                runs.setdefault(run.document_version_id, []).append(run)           # ordre chronologique
            for review in db.scalars(select(DocumentReview).where(DocumentReview.document_version_id.in_(ids))
                                     .order_by(DocumentReview.reviewed_at, DocumentReview.id)):
                reviews[review.document_version_id] = review                        # la plus récente l'emporte
        slugs = {f.id: f.slug for f in readable}
        for doc in docs:
            folder_slug = slugs[doc.folder_id]
            current = currents[doc.id]
            if current is None:
                continue
            version_runs = runs.get(current.id, [])
            pending_run = next((run for run in version_runs if run.status == "pending"), None)
            if pending_run:
                items.append(action(launch, "approval:" + pending_run.id, "Circuit à valider : " + doc.title,
                                    "Étape de validation en attente", "approvals", folder_slug, doc.id, current.id))
            last_run = version_runs[-1] if version_runs else None
            state = ({"approved": "approved", "rejected": "rejected", "changes_requested": "changes_requested"}.get(last_run.status, "to_review")
                     if last_run else (reviews[current.id].decision if current.id in reviews else "to_review"))
            if state in {"rejected", "changes_requested"}:
                items.append(action(launch, "correction:" + doc.id, "Document à corriger : " + doc.title,
                                    "Décision sur la version courante", "workflow", folder_slug, doc.id, current.id))
        for row in list_excel_inspections(launch.id, user, db):
            inspection = row["inspection"]
            if inspection and any(f["type"] != "inspection_limit" for f in inspection["findings"]):
                # Une ancienne anomalie reste historique, pas une alerte sur la version actuelle.
                doc = db.get(Document, row["document_id"])
                current = current_version(doc)
                if current is None or current.number != row["version"]:
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
    if not doc and isinstance(detail.get("version_id"), str):
        # Partages Client et autres événements portant la version concernée dans leur détail.
        version = db.get(DocumentVersion, detail["version_id"])
        doc = version.document if version else None
    if doc:
        launch = doc.folder.launch
    if not launch and (detail.get("launch") or detail.get("launch_id")):
        launch = db.get(Launch, detail.get("launch") or detail.get("launch_id"))
    return launch, doc, version, detail


def history_details(event, doc, version, detail):
    """Champs lisibles d'un événement : version, fichier, avant/après, motif (None = non enregistré)."""
    from .order_sheet import LABELS
    number = version.number if version else detail.get("version") if isinstance(detail.get("version"), int) else None
    if number is None and event.action == "document.upload":
        number = 1                                    # un dépôt crée toujours la V1 du document
    if not version and doc and number:
        version = next((v for v in doc.versions if v.number == number), None)
    changes = []
    if isinstance(detail.get("changes"), dict):
        changes = [{"field": key, "label": LABELS.get(key, key), "before": value.get("before"), "after": value.get("after")}
                   for key, value in detail["changes"].items() if isinstance(value, dict)]
    elif event.action.startswith("access.assignment") and ("before" in detail or "after" in detail):
        changes = [{"field": "rights", "label": f"Droits · sous-dossier {detail.get('folder', '?')}",
                    "before": detail.get("before"), "after": detail.get("after")}]
    return {"doc_type": doc.doc_type if doc else None, "doc_deleted": bool(doc and doc.deleted_at),
            "version_number": number, "version_deleted": bool(version and version.deleted_at),
            "history_version_id": version.id if version else None,
            "original_name": version.original_name if version else (
                max(doc.versions, key=lambda v: v.number).original_name if doc and doc.versions else None),
            "versions": detail.get("versions") if isinstance(detail.get("versions"), list) else None,
            "changes": changes, "reason": detail.get("reason") or detail.get("note") or None}


def activity(db, user, *, launch_id=None, document_id=None, actor_id=None, action_filter=None,
             date_from=None, date_to=None, limit=100, offset=0, include_global=False, exact_total=None):
    """Événements visibles, du plus récent au plus ancien.

    Avec un filtre de commande ou de document, le préfiltre SQL rend le parcours court : le total est
    exact. Sans ce filtre (historique global, tableau de bord), le parcours s'arrête dès que la page
    demandée est remplie : `total` vaut alors None et `has_more` indique s'il reste des événements."""
    if exact_total is None:
        exact_total = bool(launch_id or document_id)
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
    if launch_id or document_id:
        # Préfiltre SQL (sur-ensemble) : seuls les événements pouvant concerner cette commande ou ce
        # document sont résolus ; la portée et les droits restent vérifiés un par un ci-dessous.
        from sqlalchemy import or_
        from .models import Folder, OptionalDocumentCase
        if document_id:
            doc_ids = [document_id]
        else:
            doc_ids = list(db.scalars(select(Document.id).join(Folder).where(Folder.launch_id == launch_id)))
        version_ids = list(db.scalars(select(DocumentVersion.id).where(DocumentVersion.document_id.in_(doc_ids)))) if doc_ids else []
        targets = {*doc_ids, *version_ids}
        clauses = [AuditEvent.detail.like('%"version_id"%')]
        if launch_id:
            targets.add(launch_id)
            targets.update(db.scalars(select(OptionalDocumentCase.id).where(OptionalDocumentCase.launch_id == launch_id)))
            clauses.append(AuditEvent.detail.like(f'%{launch_id}%'))
        ids = list(targets)
        clauses += [AuditEvent.target_id.in_(ids[i:i + 500]) for i in range(0, len(ids), 500)]
        query = query.where(or_(*clauses))
    output = []
    stop_at = None if exact_total else offset + limit + 1
    for event in db.scalars(query.execution_options(yield_per=200)):
        if stop_at is not None and len(output) >= stop_at:
            break
        launch, doc, version, detail = resolve_event(db, event)
        if not launch:
            if not (include_global and is_admin(user)) or launch_id or document_id:
                continue
        else:
            from .access_control import launch_scope
            # Case de documents complémentaires : portée = son seul sous-dossier.
            case_folder = detail.get("folder") if event.target_type == "optional_document_case" and detail.get("folder") in FOLDER_LABELS else None
            with launch_scope(launch.id):
                hidden = (not accessible(db, user, launch)
                          or (doc and not permitted(user, "document.read", doc.folder.slug))
                          or (case_folder and not permitted(user, "document.read", case_folder))
                          # Une opération sur deux sous-dossiers n'est visible que si les deux le sont.
                          or (not doc and not case_folder and not all(permitted(user, "document.read", slug) for slug in FOLDER_LABELS)))
            if hidden:
                continue
            if launch_id and launch.id != launch_id:
                continue
            if document_id and (not doc or doc.id != document_id):
                continue
        # Les changements d'habilitations ne sont détaillés qu'aux administrateurs.
        if event.action.startswith("access.") and not is_admin(user):
            continue
        actor = db.get(User, event.actor_id) if event.actor_id else None
        extra = history_details(event, doc, version, detail)
        output.append({**extra, "id": event.id, "action": event.action, "actor_id": event.actor_id,
                       "actor": actor.name if actor else "Compte client" if event.action.startswith("client.") else "Système",
                       "target_type": event.target_type, "target_id": event.target_id, "detail": detail,
                       "launch_id": launch.id if launch else None, "launch_name": launch.name if launch else None,
                       "document_id": doc.id if doc else None, "document_title": doc.title if doc else None,
                       "folder": doc.folder.slug if doc else (detail.get("folder") if event.target_type == "optional_document_case" else None),
                       "version_id": version.id if version else None, "occurred_at": event.occurred_at.isoformat()})
    complete = stop_at is None or len(output) < stop_at
    return {"total": len(output) if complete else None, "has_more": len(output) > offset + limit,
            "items": output[offset:offset + limit], "limit": limit, "offset": offset}

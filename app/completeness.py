"""Évalue les exigences selon leur exigibilité, la version courante et les droits."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document, Folder, Launch
from .workflow import latest_review
from .document_intake_models import DocumentIdentification
from .completeness_models import (CompletenessProfile, LaunchCompleteness,
    RequirementRule, RequirementValidation, RequirementException)

# Étapes provisoires configurées pour la démonstration ; vocabulaire à valider par Framatex.
PHASES = [
    ("preparation", "Préparation"),
    ("approvisionnement", "Approvisionnement"),
    ("fabrication", "Fabrication"),
    ("expedition", "Expédition"),
    ("cloture", "Clôture"),
]
PHASE_RANK = {code: position for position, (code, _) in enumerate(PHASES)}


def evaluate(db: Session, launch: Launch, user, permitted):
    """Ne renvoie aucune règle d'un sous-dossier que l'utilisateur ne peut lire."""
    # Habilitations par commande : les droits de sous-dossier s'évaluent sur cette commande.
    from .access_control import launch_scope
    with launch_scope(launch.id):
        return _evaluate(db, launch, user, permitted)


def _evaluate(db: Session, launch: Launch, user, permitted):
    context = db.get(LaunchCompleteness, launch.id)
    phase = context.phase if context else "preparation"
    profile = db.get(CompletenessProfile, context.profile_id) if context and context.profile_id else None
    rules = [] if not profile else sorted((r for r in profile.rules if r.active),
                                          key=lambda r: (PHASE_RANK[r.due_phase], r.folder_slug, r.title.casefold()))
    visible = [r for r in rules if permitted(user, "document.read", r.folder_slug)]
    rows = []
    # Lectures groupées (une requête par nature d'information, et non plus par exigence ni par
    # version) : documents actifs et leurs versions, identifications, validations, décisions,
    # dérogations. Résultat identique à l'évaluation exigence par exigence.
    from sqlalchemy.orm import selectinload
    from .workflow_models import DocumentReview
    wanted = {(r.folder_slug, r.document_type) for r in visible}
    by_kind = {}
    if wanted:
        for document in db.scalars(select(Document).join(Folder).options(selectinload(Document.versions), selectinload(Document.folder)).where(
                Folder.launch_id == launch.id, Document.deleted_at.is_(None),
                Document.doc_type.in_({kind for _, kind in wanted}))).all():
            by_kind.setdefault((document.folder.slug, document.doc_type), []).append(document)
    current = {}
    for documents in by_kind.values():
        for document in documents:
            versions = [version for version in document.versions if version.deleted_at is None]
            if versions:
                current[document.id] = max(versions, key=lambda v: v.number)
    version_ids = [version.id for version in current.values()]
    identifications_all = {item.version_id: item for item in db.scalars(select(DocumentIdentification).where(
        DocumentIdentification.version_id.in_(version_ids)))} if version_ids else {}
    validations_all = {}
    for item in db.scalars(select(RequirementValidation).where(RequirementValidation.launch_id == launch.id)):
        validations_all.setdefault(item.rule_id, set()).add(item.document_version_id)
    latest_decision = {}
    if version_ids:
        for review in db.scalars(select(DocumentReview).where(DocumentReview.document_version_id.in_(version_ids))
                                 .order_by(DocumentReview.reviewed_at, DocumentReview.id)):
            latest_decision[review.document_version_id] = review          # la plus récente l'emporte
    exceptions_all = {}
    for item in db.scalars(select(RequirementException).where(RequirementException.launch_id == launch.id,
                                                               RequirementException.active.is_(True))):
        exceptions_all.setdefault(item.rule_id, item)
    for rule in visible:
        candidates = [(document, current[document.id]) for document in by_kind.get((rule.folder_slug, rule.document_type), [])
                      if document.id in current]
        # Une validation d'une version ancienne ne valide jamais la version courante.
        identifications = {version.id: identifications_all.get(version.id) for _, version in candidates}
        conforming = [(doc, version) for doc, version in candidates
                      if not identifications[version.id] or identifications[version.id].status in {'matched', 'confirmed'}]
        validated = set()
        if candidates and rule.requires_validation:
            version_ids_rule = {version.id for _, version in candidates}
            validated = validations_all.get(rule.id, set()) & version_ids_rule
            # Les décisions documentaires 0.3 ont priorité sur les validations 0.2
            # lorsqu'elles portent sur la même version courante.
            for _, current_version in candidates:
                decision = latest_decision.get(current_version.id)
                if decision:
                    if decision.decision == 'approved':
                        validated.add(current_version.id)
                    else:
                        validated.discard(current_version.id)
        exception = exceptions_all.get(rule.id)
        due = rule.required and PHASE_RANK[phase] >= PHASE_RANK[rule.due_phase]
        if conforming and (not rule.requires_validation or any(v.id in validated for _, v in conforming)):
            status = "present"
        elif conforming:
            status = "pending_validation"
        elif exception and due:
            status = "exception"
        elif any(item and item.status == 'to_verify' for item in identifications.values()):
            status = 'to_verify'
        elif candidates:
            status = 'incompatible'
        elif not due:
            status = "not_due"
        elif exception:
            status = "exception"
        else:
            status = "missing"
        rows.append({
            "id": rule.id, "title": rule.title, "folder": rule.folder_slug,
            "document_type": rule.document_type, "due_phase": rule.due_phase,
            "requires_validation": rule.requires_validation, "required": rule.required,
            "guidance": rule.guidance,
            "due": due, "status": status,
            "exception_reason": exception.reason if exception and status == "exception" else None,
            "documents": [{"id": doc.id, "title": doc.title, "version": version.number, 'version_id': version.id,
                           'identification': identifications[version.id].status if identifications[version.id] else None,
                           "validated": version.id in validated if rule.requires_validation else None}
                          for doc, version in sorted(candidates, key=lambda item: (
                              item[1].id in validated, not identifications[item[1].id] or
                              identifications[item[1].id].status in {'matched', 'confirmed'}), reverse=True)],
            "can_review": permitted(user, "completeness.review", rule.folder_slug)
                           and permitted(user, "document.read", rule.folder_slug),
        })
    counts = {code: sum(row["status"] == code for row in rows)
              for code in ("present", "pending_validation", "missing", "not_due", "exception", 'to_verify', 'incompatible')}
    # Un total nul n'est pas une complétude à 100 %. Une dérogation ne vaut pas présence.
    exigible = sum(row["due"] for row in rows)
    return {
        "launch_id": launch.id, "profile_id": profile.id if profile else None,
        "profile_name": profile.name if profile else None, "phase": phase,
        "phases": [{"code": c, "label": l} for c, l in PHASES],
        "configured": bool(profile and rules), "visible_rules": len(rows),
        "partial_visibility": len(visible) < len(rules), "counts": counts,
        "due_count": exigible, "rows": rows,
        "can_change_context": permitted(user, "launch.update"),
    }

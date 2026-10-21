"""Évalue les exigences selon leur exigibilité, la version courante et les droits."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document, Folder, Launch
from .workflow import latest_review
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
    context = db.get(LaunchCompleteness, launch.id)
    phase = context.phase if context else "preparation"
    profile = db.get(CompletenessProfile, context.profile_id) if context and context.profile_id else None
    rules = [] if not profile else sorted((r for r in profile.rules if r.active),
                                          key=lambda r: (PHASE_RANK[r.due_phase], r.folder_slug, r.title.casefold()))
    visible = [r for r in rules if permitted(user, "document.read", r.folder_slug)]
    rows = []
    for rule in visible:
        matching = db.scalars(select(Document).join(Folder).where(
            Folder.launch_id == launch.id, Folder.slug == rule.folder_slug,
            Document.doc_type == rule.document_type
        )).all()
        candidates = []
        for document in matching:
            if document.versions:
                version = max(document.versions, key=lambda v: v.number)
                candidates.append((document, version))
        # Une validation d'une version ancienne ne valide jamais la version courante.
        validated = set()
        if candidates and rule.requires_validation:
            version_ids = [version.id for _, version in candidates]
            validations = db.scalars(select(RequirementValidation).where(
                RequirementValidation.rule_id == rule.id,
                RequirementValidation.launch_id == launch.id,
                RequirementValidation.document_version_id.in_(version_ids)
            )).all()
            validated = {v.document_version_id for v in validations}
            # Les décisions documentaires 0.3 ont priorité sur les validations 0.2
            # lorsqu'elles portent sur la même version courante.
            for _, current_version in candidates:
                decision = latest_review(db, current_version.id)
                if decision:
                    if decision.decision == 'approved':
                        validated.add(current_version.id)
                    else:
                        validated.discard(current_version.id)
        exception = db.scalar(select(RequirementException).where(
            RequirementException.launch_id == launch.id, RequirementException.rule_id == rule.id,
            RequirementException.active.is_(True)
        ))
        due = rule.required and PHASE_RANK[phase] >= PHASE_RANK[rule.due_phase]
        if candidates and (not rule.requires_validation or any(v.id in validated for _, v in candidates)):
            status = "present"
        elif candidates:
            status = "pending_validation"
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
            "documents": [{"id": doc.id, "title": doc.title, "version": version.number,
                           "validated": version.id in validated if rule.requires_validation else None}
                          for doc, version in candidates],
            "can_review": permitted(user, "completeness.review", rule.folder_slug)
                           and permitted(user, "document.read", rule.folder_slug),
        })
    counts = {code: sum(row["status"] == code for row in rows)
              for code in ("present", "pending_validation", "missing", "not_due", "exception")}
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

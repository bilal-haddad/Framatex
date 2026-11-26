"""API du MVP 0.3 : validations motivées, valeurs sourcées, alertes par règle.

Aucun calcul n'altère les documents, ORLI ou les montants validés.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .active_documents import active_versions, current_version
from .core import get_db, get_current_user, utcnow
from .models import Document, DocumentVersion, Folder, Launch, User
from .workflow_models import DocumentReview, BusinessValueRevision, ImpactRule, ImpactAlert
from .workflow import VALUE_FIELDS, REVIEW_STATES, ALERT_STATES, latest_review, review_status, emit_impacts
# Imported only after main has defined shared guards; avoids two competing auth paths.
from .main import audit, admin_only, get_doc, get_launch, is_admin, must, permitted, SLUGS

router = APIRouter()


class ReviewPayload(BaseModel):
    decision: Literal['approved', 'rejected', 'changes_requested']
    comment: str = Field(default='', max_length=1800)


class ValuePayload(BaseModel):
    key: str
    value: str = Field(min_length=1, max_length=45)
    unit: str = Field(min_length=1, max_length=30)
    source_version_id: str
    reason: str = Field(default='', max_length=1800)


class ImpactRulePayload(BaseModel):
    name: str = Field(min_length=3, max_length=130)
    source_kind: Literal['value', 'document']
    source_key: str = Field(min_length=2, max_length=100)
    source_folder: str
    target_folder: str
    instruction: str = Field(min_length=12, max_length=1600)


class RulePatch(BaseModel):
    active: bool


class AlertDecision(BaseModel):
    status: Literal['acknowledged', 'action_required', 'not_applicable']
    note: str = Field(min_length=12, max_length=1500)


def get_source(db: Session, launch_id: str, version_id: str):
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(404, 'Version source introuvable')
    doc = db.get(Document, version.document_id)
    if not doc or doc.folder.launch_id != launch_id:
        raise HTTPException(422, 'La version ne relève pas de ce lancement')
    if version is not current_version(doc):
        raise HTTPException(409, 'Choisissez la version courante du document source')
    return version, doc


def review_out(db: Session, review: DocumentReview, *, document: Document | None = None):
    version = db.get(DocumentVersion, review.document_version_id)
    doc = document or db.get(Document, version.document_id)
    return {'id': review.id, 'document_id': doc.id, 'document_title': doc.title,
            'folder': doc.folder.slug, 'version': version.number,
            'version_id': version.id, 'decision': review.decision,
            'comment': review.comment, 'reviewed_by': review.reviewed_by,
            'reviewed_at': review.reviewed_at.isoformat()}


@router.get('/api/launches/{launch_id}/reviews')
def list_reviews(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, 'launch.read')
    get_launch(db, launch_id)
    documents = db.scalars(select(Document).join(Folder).where(Folder.launch_id == launch_id)).all()
    results = []
    for doc in documents:
        version = current_version(doc)
        if not permitted(user, 'document.read', doc.folder.slug) or version is None:
            continue
        current = latest_review(db, version.id)
        history = []
        for v in sorted(active_versions(doc), key=lambda x: x.number, reverse=True):
            decisions = db.scalars(select(DocumentReview).where(DocumentReview.document_version_id == v.id)
                .order_by(DocumentReview.reviewed_at.desc())).all()
            history.extend(review_out(db, r, document=doc) for r in decisions)
        results.append({'document_id': doc.id, 'document_title': doc.title,
                        'folder': doc.folder.slug, 'version': version.number,
                        'status': current.decision if current else 'to_review',
                        'last_comment': current.comment if current else '',
                        'can_review': permitted(user, 'document.review', doc.folder.slug),
                        'history': history})
    return results


@router.post('/api/documents/{doc_id}/reviews', status_code=201)
def decide_document(doc_id: str, payload: ReviewPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = get_doc(db, doc_id)
    must(user, 'launch.read')
    must(user, 'document.read', doc.folder.slug)
    must(user, 'document.review', doc.folder.slug)
    if current_version(doc) is None:
        raise HTTPException(422, 'Le document est vide')
    if payload.decision != 'approved' and len(payload.comment.strip()) < 12:
        raise HTTPException(422, 'La décision doit être motivée (12 caractères minimum)')
    # Un circuit configuré ne peut pas être contourné par l'approbation simple.
    from .approval_routes import applicable_template
    version = current_version(doc)
    from .approval_models import ApprovalRun
    if applicable_template(db, doc) or db.scalar(select(ApprovalRun.id).where(
            ApprovalRun.document_version_id == version.id)):
        raise HTTPException(409, 'Ce document relève d’un circuit de validation configuré')
    review = DocumentReview(document_version_id=version.id, decision=payload.decision,
                            comment=payload.comment.strip(), reviewed_by=user.id)
    db.add(review)
    db.flush()
    audit(db, user, 'document.review', 'document_version', version.id,
          {'decision': payload.decision, 'document': doc.id, 'review_id': review.id})
    db.commit()
    return review_out(db, review, document=doc)


def latest_values(db: Session, launch_id: str):
    rows = db.scalars(select(BusinessValueRevision).where(BusinessValueRevision.launch_id == launch_id)
                     .order_by(BusinessValueRevision.revision.desc())).all()
    groups = {}
    for row in rows:
        groups.setdefault(row.key, []).append(row)
    return groups


def value_out(db: Session, revision: BusinessValueRevision):
    ver = db.get(DocumentVersion, revision.source_version_id)
    doc = db.get(Document, ver.document_id)
    return {'id': revision.id, 'key': revision.key, 'label': VALUE_FIELDS[revision.key][0],
            'value': revision.value_text, 'unit': revision.unit, 'revision': revision.revision,
            'source_version_id': ver.id, 'document_id': doc.id, 'source_title': doc.title,
            'source_version': ver.number, 'source_is_current': ver is current_version(doc),
            'folder': doc.folder.slug, 'reason': revision.reason,
            'recorded_at': revision.recorded_at.isoformat(), 'recorded_by': revision.recorded_by}


@router.get('/api/business-value-fields')
def value_fields(user: User = Depends(get_current_user)):
    must(user, 'launch.read')
    return [{'key': k, 'label': label, 'suggested_unit': unit} for k, (label, unit) in VALUE_FIELDS.items()]


@router.get('/api/launches/{launch_id}/values')
def list_values(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, 'launch.read')
    get_launch(db, launch_id)
    groups = latest_values(db, launch_id)
    output = []
    for key, revisions in groups.items():
        # La provenance de CHAQUE révision reste filtrée par permissions.
        visible = []
        for row in revisions:
            doc = db.get(Document, db.get(DocumentVersion, row.source_version_id).document_id)
            if permitted(user, 'document.read', doc.folder.slug):
                visible.append(value_out(db, row))
        if visible:
            output.append({'key': key, 'label': VALUE_FIELDS[key][0], 'current': visible[0],
                           'history': visible, 'partial_history': len(visible) < len(revisions)})
    return output


@router.post('/api/launches/{launch_id}/values', status_code=201)
def record_value(launch_id: str, payload: ValuePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, 'launch.read')
    get_launch(db, launch_id)
    if payload.key not in VALUE_FIELDS:
        raise HTTPException(422, 'Champ métier inconnu')
    try:
        number = Decimal(payload.value.replace(',', '.').strip())
    except InvalidOperation:
        raise HTTPException(422, 'Valeur numérique invalide')
    if not number.is_finite() or number < 0 or number > 999999999 or number.as_tuple().exponent < -4:
        raise HTTPException(422, 'Valeur hors limites (4 décimales maximum)')
    unit = payload.unit.strip()
    if not unit:
        raise HTTPException(422, 'Unité requise')
    version, doc = get_source(db, launch_id, payload.source_version_id)
    must(user, 'document.read', doc.folder.slug)
    must(user, 'value.write', doc.folder.slug)
    revisions = latest_values(db, launch_id).get(payload.key, [])
    previous = revisions[0] if revisions else None
    if previous:
        old_doc = db.get(Document, db.get(DocumentVersion, previous.source_version_id).document_id)
        if old_doc.folder.slug != doc.folder.slug:
            raise HTTPException(409, 'Une même valeur métier doit rester dans son sous-dossier source')
        if previous.unit != unit:
            raise HTTPException(409, 'Unité différente : conversion et contrôle métier nécessaires')
    normalized = format(number, 'f')
    if previous and Decimal(previous.value_text) == number:
        raise HTTPException(409, 'Valeur identique à la révision actuelle')
    if previous and len(payload.reason.strip()) < 12:
        raise HTTPException(422, 'Justifiez cette modification (12 caractères minimum)')
    revision = BusinessValueRevision(launch_id=launch_id, key=payload.key, revision=(previous.revision+1 if previous else 1),
                                     value_text=normalized, unit=unit, source_version_id=version.id,
                                     reason=payload.reason.strip(), recorded_by=user.id)
    db.add(revision)
    db.flush()
    if previous:
        emit_impacts(db, launch_id=launch_id, source_kind='value', source_key=payload.key,
                     source_folder=doc.folder.slug, source_ref_id=revision.id,
                     old_value=f'{previous.value_text} {previous.unit}', new_value=f'{normalized} {unit}')
    audit(db, user, 'value.record', 'value_revision', revision.id,
          {'launch': launch_id, 'key': payload.key, 'revision': revision.revision})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Conflit de révision. Actualisez le dossier.')
    return value_out(db, revision)


def rule_out(rule: ImpactRule):
    return {'id': rule.id, 'name': rule.name, 'source_kind': rule.source_kind,
            'source_key': rule.source_key, 'source_folder': rule.source_folder,
            'target_folder': rule.target_folder, 'instruction': rule.instruction,
            'active': rule.active}


@router.get('/api/admin/impact-rules')
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    return [rule_out(r) for r in db.scalars(select(ImpactRule).order_by(ImpactRule.created_at.desc())).all()]


@router.post('/api/admin/impact-rules', status_code=201)
def create_impact_rule(payload: ImpactRulePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    if payload.source_folder not in SLUGS or payload.target_folder not in SLUGS:
        raise HTTPException(422, 'Sous-dossier inconnu')
    if payload.source_kind == 'value' and payload.source_key not in VALUE_FIELDS:
        raise HTTPException(422, 'Champ de valeur inconnu')
    rule = ImpactRule(name=payload.name.strip(), source_kind=payload.source_kind,
                      source_key=payload.source_key.strip(), source_folder=payload.source_folder,
                      target_folder=payload.target_folder, instruction=payload.instruction.strip(), created_by=user.id)
    db.add(rule); db.flush()
    audit(db, user, 'impact.rule.create', 'impact_rule', rule.id, {'name': rule.name})
    db.commit()
    return rule_out(rule)


@router.patch('/api/admin/impact-rules/{rule_id}')
def toggle_impact_rule(rule_id: str, payload: RulePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    rule = db.get(ImpactRule, rule_id)
    if not rule:
        raise HTTPException(404, 'Règle introuvable')
    rule.active = payload.active
    audit(db, user, 'impact.rule.update', 'impact_rule', rule.id, {'active': payload.active})
    db.commit()
    return rule_out(rule)


def alert_visible(user: User, rule: ImpactRule):
    # Une alerte peut contenir des références sensibles provenant du dossier source.
    return all(permitted(user, action, folder)
               for folder in (rule.source_folder, rule.target_folder)
               for action in ('document.read', 'controls.read'))


def alert_out(alert: ImpactAlert, rule: ImpactRule, user: User):
    return {'id': alert.id, 'launch_id': alert.launch_id, 'rule_id': rule.id,
            'rule_name': rule.name, 'instruction': rule.instruction,
            'source_kind': rule.source_kind, 'source_key': rule.source_key,
            'source_folder': rule.source_folder, 'target_folder': rule.target_folder,
            'old_value': alert.old_value, 'new_value': alert.new_value,
            'status': alert.status, 'resolution_note': alert.resolution_note,
            'created_at': alert.created_at.isoformat(),
            'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
            'can_review': permitted(user, 'impact.review', rule.target_folder)}


@router.get('/api/launches/{launch_id}/impacts')
def list_impacts(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, 'launch.read')
    get_launch(db, launch_id)
    alerts = db.scalars(select(ImpactAlert).where(ImpactAlert.launch_id == launch_id)
                        .order_by(ImpactAlert.created_at.desc())).all()
    out = []
    for alert in alerts:
        rule = db.get(ImpactRule, alert.rule_id)
        if rule and alert_visible(user, rule):
            out.append(alert_out(alert, rule, user))
    return out


@router.post('/api/impacts/{alert_id}/decision')
def decide_impact(alert_id: str, payload: AlertDecision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, 'launch.read')
    alert = db.get(ImpactAlert, alert_id)
    if not alert:
        raise HTTPException(404, 'Alerte introuvable')
    rule = db.get(ImpactRule, alert.rule_id)
    if not rule or not alert_visible(user, rule):
        raise HTTPException(403, 'Accès interdit')
    must(user, 'impact.review', rule.target_folder)
    if alert.status in {'acknowledged', 'not_applicable'}:
        raise HTTPException(409, 'Alerte déjà clôturée')
    alert.status = payload.status
    alert.resolution_note = payload.note.strip()
    alert.resolved_by = user.id
    alert.resolved_at = utcnow() if payload.status != 'action_required' else None
    audit(db, user, 'impact.decision', 'impact_alert', alert.id,
          {'status': alert.status, 'rule': rule.id})
    db.commit()
    return alert_out(alert, rule, user)


@router.get('/api/launches/{launch_id}/workflow-summary')
def workflow_summary(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, 'launch.read')
    get_launch(db, launch_id)
    impacts = list_impacts(launch_id, user, db)
    reviews = list_reviews(launch_id, user, db)
    values = list_values(launch_id, user, db)
    return {'reviews_pending': sum(r['status'] in ('to_review','changes_requested','rejected') for r in reviews),
            'alerts_open': sum(a['status'] in ('to_review','action_required') for a in impacts),
            'values_recorded': len(values)}

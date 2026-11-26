"""MVP 0.13 — circuits séquentiels, revue par rôle, notifications internes.

Une approbation vaut uniquement pour une version exacte. L'administrateur configure
les circuits mais ne peut pas se substituer à un valideur dont il n'a pas le rôle.
"""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .active_documents import active_versions, current_version
from .core import get_db, get_current_user, utcnow
from .models import Document, DocumentVersion, Role, User, Launch
from .workflow_models import DocumentReview
from .approval_models import ApprovalTemplate, ApprovalStage, ApprovalRun, ApprovalDecision, InternalNotification
from .internal_notifications import emit_to_role, emit_to_user, permitted_now
from .main import admin_only, audit, get_doc, get_launch, must, permitted

router = APIRouter(tags=['0.13 — Validations et notifications'])


class StageInput(BaseModel):
    name: str = Field(min_length=3, max_length=140)
    reviewer_role_id: str


class TemplateInput(BaseModel):
    name: str = Field(min_length=3, max_length=140)
    folder_slug: Literal['jaune', 'rose', 'bleu', 'vert']
    document_type: str = Field(min_length=2, max_length=100)
    stages: list[StageInput] = Field(min_length=1, max_length=6)


class ActiveInput(BaseModel):
    active: bool


class StageDecisionInput(BaseModel):
    decision: Literal['approved', 'rejected', 'changes_requested']
    comment: str = Field(default='', max_length=1800)


def steps(db: Session, template_id: str):
    return db.scalars(select(ApprovalStage).where(ApprovalStage.template_id == template_id)
                      .order_by(ApprovalStage.position.asc())).all()


def applicable_template(db: Session, doc: Document):
    matches = db.scalars(select(ApprovalTemplate).where(
        ApprovalTemplate.active.is_(True), ApprovalTemplate.folder_slug == doc.folder.slug,
        ApprovalTemplate.document_type == doc.doc_type)).all()
    if len(matches) > 1:
        raise HTTPException(409, 'Plusieurs circuits actifs pour ce type de document')
    return matches[0] if matches else None


def latest_version(doc: Document):
    version = current_version(doc)
    if version is None:
        raise HTTPException(422, 'Aucune version documentaire')
    return version


def can_decide(db: Session, user: User, run: ApprovalRun, doc: Document):
    current = next((s for s in steps(db, run.template_id) if s.position == run.current_position), None)
    version = db.get(DocumentVersion, run.document_version_id)
    if not current or not version or not (permitted(user, 'document.review', doc.folder.slug)
             and permitted(user, 'document.read', doc.folder.slug)
             and permitted(user, 'launch.read')):
        return False
    if not any(role.id == current.reviewer_role_id for role in user.roles):
        return False
    if user.id == version.uploaded_by:  # séparation rédacteur / valideur
        return False
    previous = db.scalars(select(ApprovalDecision).where(ApprovalDecision.run_id == run.id)).all()
    return user.id not in {d.actor_id for d in previous}


def run_out(db: Session, run: ApprovalRun, user: User, doc: Document):
    version = db.get(DocumentVersion, run.document_version_id)
    current_version = latest_version(doc)
    stale = version.id != current_version.id
    stages = steps(db, run.template_id)
    decisions = {d.stage_id: d for d in db.scalars(select(ApprovalDecision)
                 .where(ApprovalDecision.run_id == run.id)).all()}
    template = db.get(ApprovalTemplate, run.template_id)
    return {'id': run.id, 'document_id': doc.id, 'document_title': doc.title, 'folder': doc.folder.slug,
            'version_id': version.id, 'version': version.number, 'template_name': template.name,
            'status': 'stale' if stale else run.status, 'can_decide':
                not stale and run.status == 'pending' and can_decide(db, user, run, doc),
            'current_position': run.current_position, 'started_at': run.started_at.isoformat(),
            'stages': [{'name': s.name, 'position': s.position, 'role_id': s.reviewer_role_id,
                        'role_name': db.get(Role, s.reviewer_role_id).name,
                        'decision': decisions[s.id].decision if s.id in decisions else None,
                        'comment': decisions[s.id].comment if s.id in decisions else None,
                        'decided_at': decisions[s.id].decided_at.isoformat() if s.id in decisions else None}
                       for s in stages]}


@router.get('/api/admin/approval-templates')
def get_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    templates = db.scalars(select(ApprovalTemplate).order_by(ApprovalTemplate.created_at.desc())).all()
    return [{'id': t.id, 'name': t.name, 'folder_slug': t.folder_slug, 'document_type': t.document_type,
             'active': t.active, 'stages': [{'name': s.name, 'role_id': s.reviewer_role_id,
              'role_name': db.get(Role, s.reviewer_role_id).name, 'position': s.position} for s in steps(db,t.id)]}
            for t in templates]


@router.post('/api/admin/approval-templates', status_code=201)
def create_template(payload: TemplateInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    if db.scalar(select(ApprovalTemplate.id).where(ApprovalTemplate.active.is_(True),
                 ApprovalTemplate.folder_slug == payload.folder_slug,
                 ApprovalTemplate.document_type == payload.document_type.strip())):
        raise HTTPException(409, 'Un circuit actif existe déjà pour ce type et ce sous-dossier')
    for stage in payload.stages:
        role = db.get(Role, stage.reviewer_role_id)
        if role is None:
            raise HTTPException(422, 'Un rôle de validation n’existe pas')
        # Exiger des habilitations de base pour éviter les circuits impossibles à valider.
        if role.name != 'Administrateur':
            grants = role.grants
            for action in ('launch.read','document.read','document.review'):
                if not any(g.action == action and (g.folder_slug is None or
                    (action != 'launch.read' and g.folder_slug == payload.folder_slug)) for g in grants):
                    raise HTTPException(422, f'Le rôle {role.name} ne dispose pas du droit {action}')
    t = ApprovalTemplate(name=payload.name.strip(), folder_slug=payload.folder_slug,
                         document_type=payload.document_type.strip(), created_by=user.id)
    db.add(t);db.flush()
    for position, stage in enumerate(payload.stages, 1):
        db.add(ApprovalStage(template_id=t.id, name=stage.name.strip(),
                             reviewer_role_id=stage.reviewer_role_id, position=position))
    audit(db, user, 'approval.template.create', 'approval_template', t.id,
          {'folder': t.folder_slug, 'document_type': t.document_type, 'stages': len(payload.stages)})
    db.commit()
    return {'id': t.id, 'name': t.name, 'active': t.active}


@router.patch('/api/admin/approval-templates/{template_id}')
def toggle_template(template_id: str, payload: ActiveInput,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    template = db.get(ApprovalTemplate, template_id)
    if not template:
        raise HTTPException(404, 'Circuit introuvable')
    if payload.active and db.scalar(select(ApprovalTemplate.id).where(
            ApprovalTemplate.active.is_(True), ApprovalTemplate.id != template.id,
            ApprovalTemplate.folder_slug == template.folder_slug,
            ApprovalTemplate.document_type == template.document_type)):
        raise HTTPException(409, 'Un autre circuit est déjà actif sur cette rubrique')
    template.active = payload.active
    audit(db,user,'approval.template.toggle','approval_template',template.id, {'active':payload.active})
    db.commit()
    return {'id': template.id, 'active': template.active}


@router.get('/api/launches/{launch_id}/approval-overview')
def get_approval_overview(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user,'launch.read')
    launch = get_launch(db, launch_id)
    visible = []
    for folder in launch.folders:
        if not permitted(user,'document.read',folder.slug):
            continue
        for doc in folder.documents:
            if current_version(doc) is None:          # document supprimé : hors circuits actifs
                continue
            version = latest_version(doc)
            template = applicable_template(db, doc)
            runs = db.scalars(select(ApprovalRun).join(DocumentVersion,
                ApprovalRun.document_version_id == DocumentVersion.id)
                .where(DocumentVersion.document_id == doc.id).order_by(ApprovalRun.started_at.desc())).all()
            active = next((r for r in runs if r.document_version_id == version.id), None)
            visible.append({'document_id': doc.id, 'document_title': doc.title, 'folder':folder.slug,
                'version': version.number, 'template': {'id': template.id, 'name': template.name} if template else None,
                'can_start': bool(template and not active and (permitted(user,'document.write',folder.slug)
                                                  or permitted(user,'document.review',folder.slug))),
                'run': run_out(db,active,user,doc) if active else None,
                'previous': [run_out(db,r,user,doc) for r in runs if r.document_version_id != version.id][:2]})
    return {'launch_id': launch_id, 'items':visible}


@router.post('/api/documents/{doc_id}/approval-runs', status_code=201)
def start_run(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = get_doc(db, doc_id)
    must(user,'launch.read');must(user,'document.read',doc.folder.slug)
    if not (permitted(user,'document.write',doc.folder.slug) or permitted(user,'document.review',doc.folder.slug)):
        raise HTTPException(403, 'Autorisation insuffisante pour soumettre une pièce')
    version = latest_version(doc)
    template = applicable_template(db,doc)
    if not template:
        raise HTTPException(422, 'Aucun circuit configuré pour ce type de document')
    if db.scalar(select(ApprovalRun.id).where(ApprovalRun.document_version_id == version.id)):
        raise HTTPException(409,'Un circuit existe déjà pour cette version')
    order = steps(db,template.id)
    if not order:
        raise HTTPException(422,'Aucune étape dans le circuit')
    run = ApprovalRun(template_id=template.id, document_version_id=version.id, started_by=user.id)
    db.add(run);db.flush()
    emit_to_role(db, role_id=order[0].reviewer_role_id, launch_id=doc.folder.launch_id,
        folder=doc.folder.slug, event_key=f'approval:{run.id}:stage:1', kind='approval',
        title='Validation documentaire demandée',
        message=f'{doc.title} · version {version.number} · {order[0].name}',
        exclude_user_id=version.uploaded_by)
    audit(db,user,'approval.run.start','approval_run',run.id,
          {'document':doc.id,'version':version.number,'template':template.id})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Conflit de soumission de cette version')
    return run_out(db,run,user,doc)


@router.post('/api/approval-runs/{run_id}/decisions')
def decide_stage(run_id: str, payload: StageDecisionInput,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = db.get(ApprovalRun,run_id)
    if not run:
        raise HTTPException(404,'Circuit introuvable')
    version = db.get(DocumentVersion,run.document_version_id)
    doc = db.get(Document,version.document_id)
    must(user,'launch.read');must(user,'document.read',doc.folder.slug)
    must(user,'document.review',doc.folder.slug)
    if version.id != latest_version(doc).id:
        raise HTTPException(409,'Une nouvelle version existe : le circuit antérieur est obsolète')
    if run.status != 'pending':
        raise HTTPException(409,'Ce circuit ne peut plus recevoir de décision')
    if not can_decide(db,user,run,doc):
        raise HTTPException(403,'Cette étape requiert un autre rôle ou un autre valideur')
    if payload.decision != 'approved' and len(payload.comment.strip()) < 12:
        raise HTTPException(422,'Un refus ou une demande de correction exige une justification de 12 caractères')
    order = steps(db,run.template_id)
    stage = next(s for s in order if s.position == run.current_position)
    db.add(ApprovalDecision(run_id=run.id, stage_id=stage.id, actor_id=user.id,
                            decision=payload.decision, comment=payload.comment.strip()))
    if payload.decision != 'approved':
        run.status = payload.decision
        run.completed_at = utcnow()
    elif run.current_position == len(order):
        run.status = 'approved'
        run.completed_at = utcnow()
        # Compatibilité avec les tableaux de décisions existants, sans contournement possible.
        db.add(DocumentReview(document_version_id=version.id, decision='approved',
                              comment=f'Circuit {db.get(ApprovalTemplate, run.template_id).name} achevé',
                              reviewed_by=user.id))
    else:
        run.current_position += 1
        following = next(s for s in order if s.position == run.current_position)
        emit_to_role(db, role_id=following.reviewer_role_id, launch_id=doc.folder.launch_id,
            folder=doc.folder.slug, event_key=f'approval:{run.id}:stage:{following.position}',
            kind='approval', title='Votre validation est demandée',
            message=f'{doc.title} · version {version.number} · {following.name}',
            exclude_user_id=version.uploaded_by)
    if run.status != 'pending':
        emit_to_user(db,user_id=run.started_by,launch_id=doc.folder.launch_id,
            folder=doc.folder.slug,event_key=f'approval:{run.id}:final',kind='approval_result',
            title='Décision sur un document',
            message=f'{doc.title} · version {version.number} · {run.status}')
    audit(db,user,'approval.stage.decision','approval_run',run.id,
          {'stage':stage.position,'decision':payload.decision,'document':doc.id,'version':version.number})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Une décision a déjà été enregistrée pour cette étape')
    return run_out(db,run,user,doc)


def notification_out(n: InternalNotification):
    return {'id':n.id,'kind':n.kind,'title':n.title,'message':n.message,
            'launch_id':n.launch_id,'folder':n.folder_slug,
            'created_at':n.created_at.isoformat(),'read_at':n.read_at.isoformat() if n.read_at else None}


def notification_visible(user: User, n: InternalNotification):
    # Évaluée sur la commande de la notification : un retrait de droit la masque immédiatement.
    from .access_control import launch_scope
    with launch_scope(n.launch_id):
        return (permitted_now(user,'launch.read') and permitted_now(user,'document.read',n.folder_slug))


@router.get('/api/notifications')
def notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user,'launch.read')
    records = db.scalars(select(InternalNotification).where(
        InternalNotification.recipient_id == user.id).order_by(InternalNotification.created_at.desc()).limit(250)).all()
    from .access import accessible
    visible = [notification_out(n) for n in records if notification_visible(user,n) and accessible(db,user,db.get(Launch,n.launch_id))]
    return {'items':visible,'unread':sum(n['read_at'] is None for n in visible), 'total':len(visible)}


@router.post('/api/notifications/{notification_id}/read')
def mark_notification(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(InternalNotification,notification_id)
    if not n or n.recipient_id != user.id or not notification_visible(user,n):
        raise HTTPException(404,'Notification introuvable')
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return notification_out(n)

"""Preview a single transfer and publish the same bytes after confirmation."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .active_documents import active_versions, current_version
from .core import get_current_user, get_db
from .document_intake import ALIASES, identification_status, normalized, read_safely
from .document_intake_models import DocumentIdentification, PendingDocumentUpload
from .document_intelligence_models import DocumentRelationshipDecision
from .document_relationships import propose_relationships
from .main import (SLUGS, STORAGE, audit, get_doc, get_launch, must, permitted, persist_document,
                   persist_version, require_active_launch_rule, store_upload)
from .models import Document, DocumentVersion, User
from .upload_limits import limits_mib

router = APIRouter()
EXPIRY = timedelta(hours=2)


class PublishUpload(BaseModel):
    folder: str
    doc_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=220)
    comment: str = Field(default='', max_length=2000)
    justification: str = Field(default='', max_length=1800)
    confirm_type: bool = False
    rule_id: str | None = None
    document_id: str | None = None
    relationship_action: str | None = None
    relationship_candidate_version_id: str | None = None
    relationship_reason: str = Field(default='', max_length=1800)


class VerifyType(BaseModel):
    justification: str = Field(default='', max_length=1800)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clean_expired(db):
    expired = list(db.scalars(delete(PendingDocumentUpload).where(PendingDocumentUpload.expires_at <= now())
                              .returning(PendingDocumentUpload.disk_name)))
    db.commit()
    for name in expired:
        (STORAGE / name).unlink(missing_ok=True)


def destination(db, user, launch_id, folder):
    if folder not in SLUGS:
        raise HTTPException(422, 'Sous-dossier invalide')
    for action in ('launch.read', 'document.read', 'document.write'):
        must(user, action, None if action == 'launch.read' else folder)
    entity = next((item for item in get_launch(db, launch_id).folders if item.slug == folder), None)
    if not entity:
        raise HTTPException(404, 'Sous-dossier introuvable')
    return entity


@router.get('/api/workspace/upload-limits')
def upload_limits(user: User = Depends(get_current_user)):
    must(user, 'launch.read')
    return {'mib': limits_mib()}


@router.post('/api/launches/{launch_id}/document-uploads', status_code=201)
async def stage_document(launch_id: str, folder: str = Form(...), file: UploadFile = File(...),
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    destination(db, user, launch_id, folder)
    clean_expired(db)
    original, disk_name, size, sha, mime = await store_upload(file)
    try:
        analysis = await run_in_threadpool(read_safely, STORAGE / disk_name, original)
        launch = get_launch(db, launch_id)
        analysis['relationships'] = propose_relationships(db, user, launch, sha, analysis)
        staged = PendingDocumentUpload(launch_id=launch_id, user_id=user.id, folder=folder,
                                        original_name=original, disk_name=disk_name, size=size, sha256=sha,
                                        content_type=mime, analysis=analysis, expires_at=now() + EXPIRY)
        db.add(staged)
        db.commit()
    except BaseException:
        db.rollback()
        (STORAGE / disk_name).unlink(missing_ok=True)
        raise
    return {'id': staged.id, 'analysis': public_analysis(user, analysis), 'size': size, 'sha256': sha}


def public_analysis(user, analysis):
    classification = analysis['classification']
    suggestions = [{**item, 'canonical_type': ALIASES.get(normalized(item['doc_type']), item['doc_type'])}
                   for item in classification['suggestions']
                   if permitted(user, 'document.read', item['folder']) and permitted(user, 'document.write', item['folder'])]
    public = {key: value for key, value in analysis.items() if key not in {'comparison_text', 'comparison_lines'}}
    public['relationships'] = [
        {**item, 'can_add_version': permitted(user, 'document.version', item['folder'])}
        for item in analysis.get('relationships', [])
    ]
    return {**public, 'classification': {**classification, 'suggestions': suggestions,
            'decisive': classification['decisive'] and bool(suggestions)
            and suggestions[0]['doc_type'] == classification['suggestions'][0]['doc_type']}}


def staged_upload(db, user, launch_id, upload_id):
    must(user, 'launch.read')
    staged = db.get(PendingDocumentUpload, upload_id)
    if not staged or staged.user_id != user.id or staged.launch_id != launch_id or staged.expires_at <= now():
        raise HTTPException(404, 'Transfert introuvable ou expiré')
    return staged


def claim(db, staged):
    deleted = db.execute(delete(PendingDocumentUpload).where(PendingDocumentUpload.id == staged.id,
                         PendingDocumentUpload.expires_at > now()))
    if deleted.rowcount != 1:
        raise HTTPException(409, 'Ce transfert a déjà été traité ou a expiré')


@router.delete('/api/launches/{launch_id}/document-uploads/{upload_id}', status_code=204)
def cancel_document(launch_id: str, upload_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    staged = staged_upload(db, user, launch_id, upload_id)
    path = STORAGE / staged.disk_name
    claim(db, staged)
    db.commit()
    path.unlink(missing_ok=True)
    return Response(status_code=204)


@router.post('/api/launches/{launch_id}/document-uploads/{upload_id}/publish', status_code=201)
def publish_document(launch_id: str, upload_id: str, payload: PublishUpload,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    staged = staged_upload(db, user, launch_id, upload_id)
    destination(db, user, launch_id, staged.folder)
    entity = destination(db, user, launch_id, payload.folder)
    title, doc_type = payload.title.strip(), payload.doc_type.strip()
    if not title or not doc_type:
        raise HTTPException(422, 'Titre et type documentaire obligatoires')
    if payload.rule_id:
        _, rule = require_active_launch_rule(db, launch_id, payload.rule_id)
        if (rule.folder_slug, rule.document_type) != (payload.folder, doc_type):
            raise HTTPException(422, 'Le classement doit correspondre à la pièce attendue')
    proposals = propose_relationships(db, user, get_launch(db, launch_id), staged.sha256, staged.analysis)
    selected = next((item for item in proposals
                     if item['candidate_version_id'] == payload.relationship_candidate_version_id), None)
    if proposals and not payload.relationship_action:
        raise HTTPException(409, 'Choisissez comment traiter le rapprochement documentaire proposé')
    if payload.relationship_action not in {None, 'new_version', 'new_document', 'keep_duplicate'}:
        raise HTTPException(422, 'Décision de rapprochement invalide')
    relationship_reason = payload.relationship_reason.strip()
    if payload.relationship_action in {'new_version', 'keep_duplicate'} and not selected:
        raise HTTPException(422, 'Sélectionnez le document rapproché')
    if payload.relationship_action == 'keep_duplicate' and len(relationship_reason) < 12:
        raise HTTPException(422, 'Justifiez la conservation du doublon en au moins 12 caractères')
    chosen_document_id = payload.document_id
    if payload.relationship_action == 'new_version':
        chosen_document_id = selected['candidate_document_id']
    elif payload.relationship_action in {'new_document', 'keep_duplicate'}:
        # Ne pas rattacher au document proposé : nouvelle version du document explicitement
        # choisi (« Déposer une nouvelle version »), sinon nouveau document.
        chosen_document_id = payload.document_id
    document = db.get(Document, chosen_document_id) if chosen_document_id else None
    if chosen_document_id and (not document or document.folder_id != entity.id or document.doc_type != doc_type):
        raise HTTPException(404, 'Document introuvable pour ce type et ce sous-dossier')
    if document:
        # Déposer une pièce et créer une version sont deux responsabilités
        # distinctes dans la matrice d'habilitations.
        must(user, 'document.version', document.folder.slug)
    if not (STORAGE / staged.disk_name).is_file():
        raise HTTPException(503, 'Fichier temporaire indisponible')
    analysis = staged.analysis
    status = identification_status(analysis, entity.slug, doc_type)
    justification = payload.justification.strip()
    # The explicit confirmation checkbox, not a free-text motive, records the
    # human classification decision. A reason remains optional in the audit.
    confirmed = payload.confirm_type and status in {'to_verify', 'incompatible'}
    identified = {'analysis': analysis, 'status': 'confirmed' if confirmed else status,
                  'justification': justification or None, 'reviewed_by': user.id if confirmed else None}
    stored = (staged.original_name, staged.disk_name, staged.size, staged.sha256, staged.content_type)
    claim(db, staged)
    try:
        result = (persist_version(db, user, stored, document, payload.comment, identified) if document else
                  persist_document(db, user, stored, entity, title, doc_type, payload.comment, identified))
        if payload.relationship_action:
            latest_id = result['latest']['id']
            evidence = selected['evidence_signature'] if selected else staged.sha256
            kind = selected['kind'] if selected else 'new_document'
            db.add(DocumentRelationshipDecision(
                launch_id=launch_id, uploaded_version_id=latest_id,
                candidate_version_id=selected['candidate_version_id'] if selected else None,
                evidence_signature=evidence, relationship_kind=kind,
                action=payload.relationship_action, reason=relationship_reason, decided_by=user.id))
            audit(db, user, 'document.relationship.decide', 'document_version', latest_id,
                  {'kind': kind, 'action': payload.relationship_action,
                   'candidate_version_id': selected['candidate_version_id'] if selected else None})
        audit(db, user, 'intake.classification.publish', 'document_version', result['latest']['id'],
              {'status': identified['status'], 'justification': justification})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Conflit de dépôt ou de version. Réessayez.') from exc
    return {**result, 'identification': identified['status']}


@router.post('/api/document-versions/{version_id}/identification/confirm')
def verify_type(version_id: str, payload: VerifyType, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(404, 'Version introuvable')
    document = get_doc(db, version.document_id)
    must(user, 'launch.read')
    must(user, 'document.read', document.folder.slug)
    must(user, 'quality.review', document.folder.slug)
    if version is not current_version(document):
        raise HTTPException(409, 'Vérifiez la version courante du document')
    item = db.get(DocumentIdentification, version_id)
    if not item or item.status not in {'to_verify', 'incompatible'}:
        raise HTTPException(409, 'Aucune vérification de type en attente pour cette version')
    justification = payload.justification.strip()
    item.status, item.justification, item.reviewed_by = 'confirmed', justification, user.id
    audit(db, user, 'intake.classification.confirm', 'document_version', version_id, {'justification': justification})
    db.commit()
    return {'status': item.status}

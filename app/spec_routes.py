"""0.7 — matrice des exigences et registre d'ambiguïtés confirmées.

Une extraction suggère ; seuls les humains créent, vérifient et clôturent.
Les preuves et leurs versions exactes restent consultables.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Literal

from .active_documents import active_versions, current_version
from .core import get_current_user, get_db, utcnow
from .models import DocumentVersion, User
from .spec_analysis import analyze_text
from .spec_models import ClientRequirement, SpecificationAmbiguity
from .intake import read_document

router = APIRouter(tags=['0.7 — Exigences et ambiguïtés'])


def _base():
    from .main import audit, get_launch, must, permitted, STORAGE
    return audit, get_launch, must, permitted, STORAGE


def _version(db:Session, version_id:str, launch_id:str, user:User, write=False):
    _, _, must, _, _ = _base()
    version=db.get(DocumentVersion,version_id)
    if not version or version.document.folder.launch_id!=launch_id:
        raise HTTPException(404,'Document ou version introuvable dans ce lancement')
    folder=version.document.folder.slug
    must(user,'document.read',folder)
    if write:must(user,'document.write',folder)
    return version


def _current(version:DocumentVersion):
    current = current_version(version.document)
    return current is not None and version.id == current.id


def _requirement(db:Session, rid:str, lid:str):
    item=db.get(ClientRequirement,rid)
    if not item or item.launch_id!=lid:raise HTTPException(404,'Exigence introuvable')
    return item


def _ambiguity(db:Session, aid:str, lid:str):
    item=db.get(SpecificationAmbiguity,aid)
    if not item or item.launch_id!=lid:raise HTTPException(404,'Ambiguïté introuvable')
    return item


def _item_permissions(db:Session,user:User,launch_id:str,source_id:str,evidence_id:str|None=None):
    _, _, must, _, _ = _base()
    must(user,'launch.read')
    source=_version(db,source_id,launch_id,user)
    proof=_version(db,evidence_id,launch_id,user) if evidence_id else None
    return source,proof


def _req_output(db:Session,x:ClientRequirement,user:User):
    source,evidence=_item_permissions(db,user,x.launch_id,x.source_version_id,x.evidence_version_id)
    source_stale=not _current(source)
    evidence_stale=evidence is not None and not _current(evidence)
    if source_stale:state='source_changed'
    elif not evidence:state='uncovered'
    elif evidence_stale:state='evidence_changed'
    elif x.reviewed_source_version_id==source.id and x.reviewed_evidence_version_id==evidence.id:state='verified'
    else:state='to_verify'
    return {'id':x.id,'title':x.title,'category':x.category,'description':x.description,
            'source_excerpt':x.source_excerpt,'source_version_id':source.id,
            'source_document':source.document.title,'source_document_id':source.document.id,'source_version':source.number,
            'evidence_version_id':evidence.id if evidence else None,
            'evidence_document':evidence.document.title if evidence else None,
            'evidence_version':evidence.number if evidence else None,
            'review_note':x.review_note, 'state':state,
            'created_at':x.created_at.isoformat(),'can_review':_can_review(user,source.document.folder.slug),
            'source_folder':source.document.folder.slug}


def _amb_output(db:Session,x:SpecificationAmbiguity,user:User):
    source,clar=_item_permissions(db,user,x.launch_id,x.source_version_id,x.clarification_version_id)
    return {'id':x.id,'excerpt':x.excerpt,'kind':x.kind,'question':x.question,
            'source_version_id':source.id,'source_document':source.document.title,
            'source_version':source.number,'source_document_id':source.document.id,'source_folder':source.document.folder.slug,
            'status':'source_changed' if not _current(source) else x.status,
            'recorded_status':x.status,'resolution':x.resolution,
            'clarification_version_id':clar.id if clar else None,
            'clarification_document':clar.document.title if clar else None,
            'can_review':_can_ambiguity_review(user,source.document.folder.slug),
            'confirmed_at':x.confirmed_at.isoformat()}


def _can_review(user,folder):
    from .main import permitted
    return permitted(user,'requirement.review',folder)


def _can_ambiguity_review(user,folder):
    from .main import permitted
    return permitted(user,'ambiguity.review',folder)


class RequirementIn(BaseModel):
    source_version_id:str
    title:str=Field(min_length=5,max_length=180)
    category:str=Field(default='Autre',max_length=48)
    description:str=Field(min_length=8,max_length=1200)
    source_excerpt:str=Field(default='',max_length=500)

class EvidenceIn(BaseModel):
    evidence_version_id:str

class VerificationIn(BaseModel):
    note:str=Field(min_length=12,max_length=2000)

class AmbiguityIn(BaseModel):
    source_version_id:str
    excerpt:str=Field(min_length=8,max_length=500)
    kind:str=Field(min_length=3,max_length=48)
    question:str=Field(min_length=8,max_length=500)

class ResolutionIn(BaseModel):
    decision:Literal['resolved','dismissed']
    note:str=Field(min_length=12,max_length=2000)
    clarification_version_id:str|None=None


@router.get('/api/document-versions/{version_id}/spec-suggestions')
def spec_suggestions(version_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _,_,must,_,storage=_base()
    version=db.get(DocumentVersion,version_id)
    if not version:raise HTTPException(404,'Version introuvable')
    must(user,'launch.read')
    folder=version.document.folder.slug
    must(user,'document.read',folder)
    if not _current(version):
        raise HTTPException(409,'Analyser la version courante pour éviter des suggestions obsolètes')
    path=storage/version.disk_name
    if not path.is_file():raise HTTPException(503,'Fichier indisponible')
    read=read_document(path,version.original_name)
    detected=analyze_text(read['text'])
    return {'version_id':version.id,'document':version.document.title,
            'method':read['method'],'warnings':read['warnings'],
            **detected,'human_confirmation_required':True}


@router.get('/api/launches/{launch_id}/specifications')
def list_specifications(launch_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _,get_launch,must,permitted,_=_base()
    must(user,'launch.read')
    get_launch(db,launch_id)
    requirements=[]; ambiguities=[]
    for x in db.scalars(select(ClientRequirement).where(ClientRequirement.launch_id==launch_id).order_by(ClientRequirement.created_at,ClientRequirement.id)).all():
        v=db.get(DocumentVersion,x.source_version_id)
        ev=db.get(DocumentVersion,x.evidence_version_id) if x.evidence_version_id else None
        if not permitted(user,'document.read',v.document.folder.slug) or (ev and not permitted(user,'document.read',ev.document.folder.slug)):
            continue  # Ne pas révéler qu'une preuve existe dans une rubrique restreinte.
        requirements.append(_req_output(db,x,user))
    for x in db.scalars(select(SpecificationAmbiguity).where(SpecificationAmbiguity.launch_id==launch_id).order_by(SpecificationAmbiguity.confirmed_at,SpecificationAmbiguity.id)).all():
        v=db.get(DocumentVersion,x.source_version_id)
        clar=db.get(DocumentVersion,x.clarification_version_id) if x.clarification_version_id else None
        if not permitted(user,'document.read',v.document.folder.slug) or (clar and not permitted(user,'document.read',clar.document.folder.slug)):
            continue
        ambiguities.append(_amb_output(db,x,user))
    return {'requirements':requirements,'ambiguities':ambiguities,
            'coverage':{'visible_total':len(requirements),'verified':sum(x['state']=='verified' for x in requirements),
                        'uncovered':sum(x['state']=='uncovered' for x in requirements),
                        'to_verify':sum(x['state']=='to_verify' for x in requirements),
                        'recheck':sum(x['state'] in ('source_changed','evidence_changed') for x in requirements)},
            'open_ambiguities':sum(x['status'] in ('open','source_changed') for x in ambiguities),
            'scope':'Les chiffres concernent uniquement les éléments auxquels vous avez accès. Aucun contrôle automatique de conformité.'}


@router.post('/api/launches/{launch_id}/requirements',status_code=201)
def create_requirement(launch_id:str,payload:RequirementIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,get_launch,must,_,_=_base()
    must(user,'launch.read');get_launch(db,launch_id)
    source=_version(db,payload.source_version_id,launch_id,user,write=True)
    if not _current(source):raise HTTPException(409,'La version source a été remplacée')
    x=ClientRequirement(launch_id=launch_id,source_version_id=source.id,title=payload.title.strip(),
                        category=payload.category.strip() or 'Autre',description=payload.description.strip(),
                        source_excerpt=payload.source_excerpt.strip(),created_by=user.id)
    db.add(x);db.flush()
    audit(db,user,'spec.requirement.create','requirement',x.id,{'launch':launch_id,'source_version':source.id})
    db.commit();return _req_output(db,x,user)


@router.post('/api/launches/{launch_id}/requirements/{requirement_id}/evidence')
def attach_evidence(launch_id:str,requirement_id:str,payload:EvidenceIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,_,must,_,_=_base()
    x=_requirement(db,requirement_id,launch_id)
    src,_=_item_permissions(db,user,launch_id,x.source_version_id,x.evidence_version_id)
    must(user,'document.write',src.document.folder.slug)
    evidence=_version(db,payload.evidence_version_id,launch_id,user)
    if not _current(src) or not _current(evidence):raise HTTPException(409,'Source ou preuve remplacée : utiliser les versions courantes')
    x.evidence_version_id=evidence.id
    x.review_note='';x.reviewed_by=None;x.reviewed_at=None
    x.reviewed_source_version_id=None;x.reviewed_evidence_version_id=None
    audit(db,user,'spec.evidence.attach','requirement',x.id,{'evidence_version':evidence.id})
    db.commit();return _req_output(db,x,user)


@router.post('/api/launches/{launch_id}/requirements/{requirement_id}/verify')
def verify_requirement(launch_id:str,requirement_id:str,payload:VerificationIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,_,must,_,_=_base()
    x=_requirement(db,requirement_id,launch_id)
    source,proof=_item_permissions(db,user,launch_id,x.source_version_id,x.evidence_version_id)
    must(user,'requirement.review',source.document.folder.slug)
    if not proof:raise HTTPException(409,'Associer une preuve avant vérification')
    if not _current(source) or not _current(proof):raise HTTPException(409,'Source ou preuve remplacée : vérifier les versions courantes')
    x.review_note=payload.note.strip();x.reviewed_by=user.id;x.reviewed_at=utcnow()
    x.reviewed_source_version_id=source.id;x.reviewed_evidence_version_id=proof.id
    audit(db,user,'spec.requirement.verify','requirement',x.id,{'evidence_version':proof.id})
    db.commit();return _req_output(db,x,user)


@router.post('/api/launches/{launch_id}/ambiguities',status_code=201)
def create_ambiguity(launch_id:str,payload:AmbiguityIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,get_launch,must,_,_=_base()
    must(user,'launch.read');get_launch(db,launch_id)
    source=_version(db,payload.source_version_id,launch_id,user,write=True)
    if not _current(source):raise HTTPException(409,'La version source a été remplacée')
    x=SpecificationAmbiguity(launch_id=launch_id,source_version_id=source.id,excerpt=payload.excerpt.strip(),
                             kind=payload.kind.strip(),question=payload.question.strip(),confirmed_by=user.id)
    db.add(x);db.flush()
    audit(db,user,'spec.ambiguity.record','ambiguity',x.id,{'source_version':source.id})
    db.commit();return _amb_output(db,x,user)


@router.post('/api/launches/{launch_id}/ambiguities/{ambiguity_id}/resolve')
def resolve_ambiguity(launch_id:str,ambiguity_id:str,payload:ResolutionIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,_,must,_,_=_base()
    x=_ambiguity(db,ambiguity_id,launch_id)
    src,_=_item_permissions(db,user,launch_id,x.source_version_id,x.clarification_version_id)
    must(user,'ambiguity.review',src.document.folder.slug)
    if not _current(src):raise HTTPException(409,'Version source remplacée : réexaminer la nouvelle version')
    if x.status!='open':raise HTTPException(409,'Point déjà clôturé')
    clarification=None
    if payload.clarification_version_id:
        clarification=_version(db,payload.clarification_version_id,launch_id,user)
        if not _current(clarification):raise HTTPException(409,'Justificatif de clarification obsolète')
    x.status=payload.decision;x.resolution=payload.note.strip();x.clarification_version_id=clarification.id if clarification else None
    x.closed_by=user.id;x.closed_at=utcnow()
    audit(db,user,'spec.ambiguity.resolve','ambiguity',x.id,{'decision':x.status,'clarification_version':x.clarification_version_id})
    db.commit();return _amb_output(db,x,user)


class RefreshRequirementIn(BaseModel):
    new_source_version_id:str
    title:str=Field(min_length=5,max_length=180)
    description:str=Field(min_length=8,max_length=1200)
    source_excerpt:str=Field(default='',max_length=500)

class RefreshAmbiguityIn(BaseModel):
    new_source_version_id:str
    excerpt:str=Field(min_length=8,max_length=500)
    question:str=Field(min_length=8,max_length=500)

@router.post('/api/launches/{launch_id}/requirements/{requirement_id}/refresh-source')
def refresh_requirement_source(launch_id:str,requirement_id:str,payload:RefreshRequirementIn,
                               user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,_,must,_,_=_base()
    item=_requirement(db,requirement_id,launch_id)
    previous,_=_item_permissions(db,user,launch_id,item.source_version_id,item.evidence_version_id)
    must(user,'document.write',previous.document.folder.slug)
    next_version=_version(db,payload.new_source_version_id,launch_id,user,write=True)
    if next_version.document_id != previous.document_id or not _current(next_version):
        raise HTTPException(422,'Choisir la version courante du même document source')
    if previous.id==next_version.id:raise HTTPException(409,'La source est déjà courante')
    old=previous.id
    item.source_version_id=next_version.id
    item.title=payload.title.strip();item.description=payload.description.strip()
    item.source_excerpt=payload.source_excerpt.strip()
    item.review_note='';item.reviewed_by=None;item.reviewed_at=None
    item.reviewed_source_version_id=None;item.reviewed_evidence_version_id=None
    audit(db,user,'spec.requirement.source.refresh','requirement',item.id,
          {'previous_source_version':old,'new_source_version':next_version.id})
    db.commit();return _req_output(db,item,user)

@router.post('/api/launches/{launch_id}/ambiguities/{ambiguity_id}/refresh-source')
def refresh_ambiguity_source(launch_id:str,ambiguity_id:str,payload:RefreshAmbiguityIn,
                             user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    audit,_,must,_,_=_base()
    item=_ambiguity(db,ambiguity_id,launch_id)
    old,_=_item_permissions(db,user,launch_id,item.source_version_id,item.clarification_version_id)
    must(user,'document.write',old.document.folder.slug)
    new=_version(db,payload.new_source_version_id,launch_id,user,write=True)
    if new.document_id!=old.document_id or not _current(new):
        raise HTTPException(422,'Choisir la version courante du même document source')
    if new.id==old.id:raise HTTPException(409,'La source est déjà courante')
    old_id=old.id
    item.source_version_id=new.id;item.excerpt=payload.excerpt.strip();item.question=payload.question.strip()
    item.status='open';item.resolution='';item.clarification_version_id=None
    item.closed_by=None;item.closed_at=None
    audit(db,user,'spec.ambiguity.source.refresh','ambiguity',item.id,
          {'previous_source_version':old_id,'new_source_version':new.id})
    db.commit();return _amb_output(db,item,user)

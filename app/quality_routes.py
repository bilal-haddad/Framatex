"""API 0.4 : cohérence inter-documents et inspection de l'intégrité des formules Excel."""
from __future__ import annotations
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .active_documents import active_versions, current_version
from .core import get_current_user, get_db, utcnow
from .models import Document, DocumentVersion, Folder, User
from .quality_models import DocumentDatum, CrossDocumentRule, QualityDecision, ExcelInspection
from .quality import QUALITY_FIELDS_EXTRA, REFERENCE_KEYS, comparison, analyze_workbook
from .workflow import VALUE_FIELDS
from .main import must, permitted, admin_only, get_doc, get_launch, audit, STORAGE, SLUGS

router=APIRouter()
QUALITY_FIELDS = {**VALUE_FIELDS, **QUALITY_FIELDS_EXTRA}


class DatumIn(BaseModel):
    field_key: str
    value: str = Field(min_length=1,max_length=50)
    unit: str = Field(min_length=1,max_length=30)


class RuleIn(BaseModel):
    name: str = Field(min_length=3,max_length=140)
    field_key: str
    left_doc_type: str = Field(min_length=2,max_length=100)
    right_doc_type: str = Field(min_length=2,max_length=100)
    left_folder: str
    right_folder: str
    tolerance: str = '0'


class QualityDecisionIn(BaseModel):
    signature: str = Field(min_length=64,max_length=64)
    decision: Literal['justified','to_correct','deferred']
    note: str = Field(min_length=12,max_length=1800)


def normalized_decimal(raw:str, *, tolerance=False):
    try:
        v=Decimal(raw.strip().replace(',','.'))
    except (InvalidOperation,ValueError):
        raise HTTPException(422,'Nombre décimal incorrect')
    if not v.is_finite() or abs(v)>Decimal('1e15') or (tolerance and v<0):
        raise HTTPException(422,'Valeur numérique non autorisée')
    return format(v,'f')


def version_doc(db,version_id):
    version=db.get(DocumentVersion,version_id)
    if not version: raise HTTPException(404,'Version introuvable')
    doc=db.get(Document,version.document_id)
    return version,doc


def rule_out(r):
    return {'id':r.id,'name':r.name,'field_key':r.field_key,'left_doc_type':r.left_doc_type,
            'right_doc_type':r.right_doc_type,'left_folder':r.left_folder,'right_folder':r.right_folder,
            'tolerance':r.tolerance_text,'active':r.active}


@router.get('/api/quality/fields')
def fields(user:User=Depends(get_current_user)):
    must(user,'launch.read')
    return [{'key':k,'label':label,'suggested_unit':unit} for k,(label,unit) in QUALITY_FIELDS.items()]


@router.post('/api/document-versions/{version_id}/data',status_code=201)
def save_datum(version_id:str,payload:DatumIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    version,doc=version_doc(db,version_id)
    must(user,'launch.read')
    must(user,'document.read',doc.folder.slug)
    must(user,'value.write',doc.folder.slug)
    if payload.field_key not in QUALITY_FIELDS: raise HTTPException(422,'Champ métier inconnu')
    if version is not current_version(doc):
        raise HTTPException(409,'La valeur doit être saisie sur la version courante')
    if db.scalar(select(DocumentDatum).where(DocumentDatum.document_version_id==version.id,
                                           DocumentDatum.field_key==payload.field_key)):
        raise HTTPException(409,'Valeur déjà consignée : utiliser une nouvelle version documentaire')
    num=payload.value.strip() if payload.field_key in REFERENCE_KEYS else normalized_decimal(payload.value)
    if not num:
        raise HTTPException(422, 'Référence obligatoire')
    item=DocumentDatum(document_version_id=version.id, field_key=payload.field_key,
                       value_text=num,unit='référence' if payload.field_key in REFERENCE_KEYS else payload.unit.strip(),recorded_by=user.id)
    db.add(item);db.flush()
    audit(db,user,'quality.datum.record','document_version',version.id,
          {'field_key':payload.field_key,'datum':item.id})
    db.commit()
    return {'id':item.id,'field_key':item.field_key,'value':item.value_text,'unit':item.unit}


@router.get('/api/launches/{launch_id}/quality')
def quality_report(launch_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    must(user,'launch.read');get_launch(db,launch_id)
    rules=db.scalars(select(CrossDocumentRule).where(CrossDocumentRule.active.is_(True))
                     .order_by(CrossDocumentRule.name)).all()
    rows=[]
    for r in rules:
        # Un contrôle croisé n'est montré que si les deux sous-dossiers sont lisibles ET
        # « Consulter contrôles » y est accordé : aucune fuite d'un dossier non attribué.
        if not all(permitted(user,act,f) for f in (r.left_folder,r.right_folder) for act in ('document.read','controls.read')):
            continue
        item=comparison(db,launch_id,r)
        if item['status']=='difference':
            decision=db.scalar(select(QualityDecision).where(QualityDecision.launch_id==launch_id,
                QualityDecision.rule_id==r.id,QualityDecision.evidence_signature==item['signature'])
                .order_by(QualityDecision.decided_at.desc(),QualityDecision.id.desc()).limit(1))
            if decision:
                item['decision']={'status':decision.decision,'note':decision.note,
                                  'by':db.get(User, decision.decided_by).name,
                                  'date':decision.decided_at.isoformat()}
        item['can_review']=permitted(user,'quality.review',r.left_folder) and permitted(user,'quality.review',r.right_folder)
        rows.append(item)
    return {'rows':rows,'counts':{name:sum(x['status']==name for x in rows) for name in
            ('consistent','difference','unavailable','ambiguous','unit_mismatch')}}


@router.post('/api/launches/{launch_id}/quality/{rule_id}/decisions',status_code=201)
def decide_quality(launch_id:str,rule_id:str,payload:QualityDecisionIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    must(user,'launch.read');get_launch(db,launch_id)
    rule=db.get(CrossDocumentRule,rule_id)
    if not rule or not rule.active: raise HTTPException(404,'Règle inactive ou inexistante')
    for folder in (rule.left_folder,rule.right_folder):
        must(user,'document.read',folder);must(user,'quality.review',folder)
    item=comparison(db,launch_id,rule)
    if item['status']!='difference' or payload.signature!=item['signature']:
        raise HTTPException(409,'Constat changé : actualisez et recommencez')
    accepted=db.scalar(select(QualityDecision).where(QualityDecision.launch_id==launch_id,
        QualityDecision.rule_id==rule_id,QualityDecision.evidence_signature==item['signature'],
        QualityDecision.decision=='justified').limit(1))
    if accepted:
        raise HTTPException(409,'Cet écart a déjà été accepté pour ces sources et cette règle')
    dec=QualityDecision(launch_id=launch_id,rule_id=rule_id,evidence_signature=item['signature'],
                        decision=payload.decision,note=payload.note.strip(),decided_by=user.id)
    db.add(dec);db.flush()
    audit(db,user,'quality.decision','quality_rule',rule_id,{'decision':dec.decision,'launch':launch_id})
    db.commit()
    return {'id':dec.id,'decision':dec.decision,'note':dec.note}


@router.get('/api/admin/quality-rules')
def get_rules(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    admin_only(user)
    return [rule_out(x) for x in db.scalars(select(CrossDocumentRule).order_by(CrossDocumentRule.created_at)).all()]


@router.post('/api/admin/quality-rules',status_code=201)
def add_rule(payload:RuleIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    admin_only(user)
    if payload.field_key not in QUALITY_FIELDS or payload.left_folder not in SLUGS or payload.right_folder not in SLUGS:
        raise HTTPException(422,'Configuration de règle incorrecte')
    if payload.left_doc_type.strip()==payload.right_doc_type.strip() and payload.left_folder==payload.right_folder:
        raise HTTPException(422,'Deux sources documentaires distinctes sont nécessaires')
    item=CrossDocumentRule(name=payload.name.strip(),field_key=payload.field_key,
        left_doc_type=payload.left_doc_type.strip(),right_doc_type=payload.right_doc_type.strip(),
        left_folder=payload.left_folder,right_folder=payload.right_folder,
        tolerance_text=normalized_decimal(payload.tolerance,tolerance=True),created_by=user.id)
    db.add(item);db.flush();audit(db,user,'quality.rule.create','quality_rule',item.id)
    db.commit()
    return rule_out(item)


@router.patch('/api/admin/quality-rules/{rule_id}')
def toggle_rule(rule_id:str,payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    admin_only(user)
    if set(payload)!={'active'} or not isinstance(payload['active'],bool): raise HTTPException(422,'Statut invalide')
    item=db.get(CrossDocumentRule,rule_id)
    if not item:raise HTTPException(404,'Règle introuvable')
    item.active=payload['active'];audit(db,user,'quality.rule.toggle','quality_rule',item.id,{'active':item.active})
    db.commit();return rule_out(item)


def inspection_out(db:Session,item:ExcelInspection):
    v=db.get(DocumentVersion,item.document_version_id)
    return {'id':item.id,'version_id':v.id,'version':v.number,'status':item.status,
            'scanned_cells':item.scanned_cells,'formula_count':item.formula_count,
            'findings':json.loads(item.findings_json),'inspected_at':item.inspected_at.isoformat()}


def auto_inspect_excel(db:Session,version:DocumentVersion, user_id:str):
    """Called during upload. Store first-version baseline and subsequent static findings."""
    if Path(version.original_name).suffix.lower()!='.xlsx': return
    doc=db.get(Document,version.document_id)
    prev=next((v for v in doc.versions if v.number==version.number-1),None)
    baseline=prev if prev and Path(prev.original_name).suffix.lower()=='.xlsx' else None
    result=analyze_workbook(STORAGE/version.disk_name,STORAGE/baseline.disk_name if baseline else None)
    item=ExcelInspection(document_version_id=version.id,baseline_version_id=baseline.id if baseline else None,
         status=result['status'],scanned_cells=result['scanned_cells'],formula_count=result['formula_count'],
         findings_json=json.dumps(result['findings'],ensure_ascii=False),inspected_by=user_id)
    db.add(item)


@router.get('/api/launches/{launch_id}/excel-inspections')
def list_excel_inspections(launch_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    must(user,'launch.read');get_launch(db,launch_id)
    docs=db.scalars(select(Document).join(Folder).where(Folder.launch_id==launch_id)).all()
    rows=[]
    for doc in docs:
        if not (permitted(user,'document.read',doc.folder.slug) and permitted(user,'controls.read',doc.folder.slug)):continue
        for v in active_versions(doc):
            if Path(v.original_name).suffix.lower()!='.xlsx': continue
            inspection=db.scalar(select(ExcelInspection).where(ExcelInspection.document_version_id==v.id))
            rows.append({'document_id':doc.id,'document_title':doc.title,'folder':doc.folder.slug,
                         'version_id':v.id,'version':v.number,
                         'inspection':inspection_out(db,inspection) if inspection else None})
    return sorted(rows,key=lambda x:(x['document_title'],x['version']))

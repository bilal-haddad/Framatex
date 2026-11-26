"""Per-launch access checks for all API entrypoints, including indirect object routes.

A launch is unrestricted until an administrator explicitly enables restricted
mode, to preserve the original MVP's existing data and collaborators on upgrade.
In restricted mode: admin OR creator OR an explicitly assigned member.
Existing role / folder permissions remain mandatory independently.
"""
from __future__ import annotations
import re
import jwt
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import SessionLocal, COOKIE, SECRET_KEY
from .models import User, Launch, LaunchMember, Document, DocumentVersion


def accessible(db: Session, user: User, launch: Launch | None) -> bool:
    """Visibilité d'une commande : délègue au point de contrôle central (app/access_control.py)."""
    from .access_control import launch_accessible
    return launch_accessible(db, user, launch)


def visible(db: Session, user: User, launches: list[Launch]) -> list[Launch]:
    return [l for l in launches if accessible(db, user, l)]


def must_access(db: Session, user: User, launch_id: str) -> Launch:
    launch = db.get(Launch, launch_id)
    if not accessible(db, user, launch):
        # Prevent user enumeration of confidential launch identifiers.
        raise HTTPException(404, "Lancement introuvable")
    return launch


def version_launch(db: Session, version_id: str) -> str | None:
    version = db.get(DocumentVersion, version_id)
    return version.document.folder.launch_id if version else None


def document_launch(db: Session, document_id: str) -> str | None:
    document = db.get(Document, document_id)
    return document.folder.launch_id if document else None


def indirect_launch(db: Session, params: dict) -> str | None:
    if params.get('launch_id'):
        return params['launch_id']
    if params.get('doc_id'):
        return document_launch(db,params['doc_id'])
    if params.get('version_id'):
        return version_launch(db,params['version_id'])
    if params.get('run_id'):
        from .approval_models import ApprovalRun
        row = db.get(ApprovalRun,params['run_id'])
        return version_launch(db,row.document_version_id) if row else None
    if params.get('alert_id'):
        from .workflow_models import ImpactAlert
        row = db.get(ImpactAlert,params['alert_id'])
        return row.launch_id if row else None
    if params.get('notification_id'):
        from .approval_models import InternalNotification
        row = db.get(InternalNotification,params['notification_id'])
        return row.launch_id if row else None
    if params.get('publication_id'):
        from .sharing_models import ClientPublication
        row = db.get(ClientPublication,params['publication_id'])
        return row.launch_id if row else None
    if params.get('request_id'):
        from .sharing_models import SupplierDocumentRequest
        row = db.get(SupplierDocumentRequest,params['request_id'])
        return row.launch_id if row else None
    return None


# Path matching happens in the HTTP middleware, before FastAPI resolves routes.
# It therefore covers endpoints from every module and every supported FastAPI
# release, including indirect document / publication / notification URLs.
SCOPE_PATHS = [
    (re.compile(r'^/api/launches/([^/]+)(?:/|$)'), 'launch_id'),
    (re.compile(r'^/api/documents/([^/]+)(?:/|$)'), 'doc_id'),
    (re.compile(r'^/api/document-versions/([^/]+)(?:/|$)'), 'version_id'),
    (re.compile(r'^/api/approval-runs/([^/]+)(?:/|$)'), 'run_id'),
    (re.compile(r'^/api/impacts/([^/]+)(?:/|$)'), 'alert_id'),
    (re.compile(r'^/api/notifications/([^/]+)(?:/|$)'), 'notification_id'),
    (re.compile(r'^/api/client-publications/([^/]+)(?:/|$)'), 'publication_id'),
    (re.compile(r'^/api/supplier-requests/([^/]+)(?:/|$)'), 'request_id'),
]


def guard_http_request(request: Request):
    """Return a denial response when a URL points at an inaccessible launch.

    Called for every /api/ request by the existing header-checking middleware.
    Endpoints must still enforce role and folder permissions as before.
    """
    params = {}
    for pattern, name in SCOPE_PATHS:
        match = pattern.match(request.url.path)
        if match:
            params[name] = match.group(1)
            break
    if not params:
        return None
    token = request.cookies.get(COOKIE)
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=['HS256']) if token else {}
        subject = None if claims.get('typ') == 'client' else claims.get('sub')
    except (jwt.InvalidTokenError, KeyError):
        subject = None
    if not subject:
        return JSONResponse({'detail':'Connexion nécessaire'},status_code=401)
    with SessionLocal() as db:
        user = db.get(User, subject)
        if not user or not user.active:
            return JSONResponse({'detail':'Connexion nécessaire'},status_code=401)
        target_launch = indirect_launch(db,params)
        if target_launch and not accessible(db,user,db.get(Launch,target_launch)):
            return JSONResponse({'detail':'Lancement introuvable'},status_code=404)
        # Commande de la requête : les droits de sous-dossier sont évalués dans ce contexte.
        request.state.framatex_launch = target_launch
    return None

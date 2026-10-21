from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import tempfile
import zipfile
import csv
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from .core import Base, COOKIE, DATA_DIR, ROOT, engine, get_current_user, get_db, hash_password, check_password, make_token, login_limit_key, login_attempt_allowed, record_login_failure, clear_login_failures, utcnow
from .models import AuditEvent, Document, DocumentVersion, Folder, Launch, LaunchMember, Role, RolePermission, User
from .completeness_models import CompletenessProfile, RequirementRule, LaunchCompleteness, RequirementValidation, RequirementException
from .completeness import PHASES, PHASE_RANK, evaluate
from .workflow_models import DocumentReview, BusinessValueRevision, ImpactRule, ImpactAlert
from .quality_models import DocumentDatum, CrossDocumentRule, QualityDecision, ExcelInspection
from .intake_models import ConfirmedField
from .spec_models import ClientRequirement, SpecificationAmbiguity
from .mail_models import ArchivedEmail, EmailCommitment
from .impact_sim_models import ImpactSimulation
from .orli_models import OrliImportBatch, OrliImportedLaunch, OrliLink
from .material_models import MaterialLine, MaterialPlanRevision, MaterialMovement
from .approval_models import ApprovalTemplate, ApprovalStage, ApprovalRun, ApprovalDecision, InternalNotification
from .sharing_models import ClientPublication, SupplierDocumentRequest
from .workflow import emit_document_impacts, latest_review

FOLDERS = [("jaune", "Technique"), ("rose", "Réception"), ("bleu", "Douane"), ("vert", "Facturation")]
SLUGS = {slug for slug, _ in FOLDERS}
ACTIONS = {"launch.read", "launch.create", "launch.update", "document.read", "document.write", "audit.read", "completeness.review", "document.review", "value.write", "impact.review", "quality.review", "requirement.review", "ambiguity.review", "commitment.review"}
STATUSES = {"À compléter", "En cours", "En validation", "Clôturé"}
MAX_UPLOAD = 20 * 1024 * 1024
STORAGE = DATA_DIR / "files"
STORAGE.mkdir(parents=True, exist_ok=True)
EXTS = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".txt", ".eml", ".csv"}
MIMES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain", ".eml": "message/rfc822", ".csv": "text/csv"}

@asynccontextmanager
async def lifespan(app: FastAPI):
    from .migrate import migrate
    migrate()
    yield

app = FastAPI(title="Framatex · Dossier jaune", version="0.17.0", lifespan=lifespan)

# Sous Windows, mimetypes lit le registre, qui déclare souvent .js (parfois .css)
# en text/plain. Avec X-Content-Type-Options: nosniff, le navigateur refuserait
# alors d'exécuter les scripts et d'appliquer les styles. Les types des fichiers
# servis par /assets sont donc fixés explicitement, quel que soit le poste.
WEB_MIME_TYPES = {
    ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
    ".json": "application/json", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain",
}


def register_web_mime_types() -> None:
    for extension, media_type in WEB_MIME_TYPES.items():
        mimetypes.add_type(media_type, extension)  # initialise mimetypes (registre compris) puis remplace


register_web_mime_types()
app.mount("/assets", StaticFiles(directory=ROOT / "static"), name="assets")

# Pages HTML servies hors /api : landing publique, espace FRAMATEX (application
# interne existante) et point d'entrée provisoire de l'espace Client.
HTML_PAGES = {"/", "/espace-framatex", "/espace-client"}

@app.middleware("http")
async def request_header_guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("X-Framatex-Request") != "1":
            return Response("En-tête de protection manquant", status_code=403)
    if request.url.path.startswith('/api/'):
        from .access import guard_http_request
        # This guard performs synchronous SQLAlchemy/SQLite queries. Never run
        # it on the ASGI event loop: a locked DB must not freeze /api/health,
        # static assets and every browser tab on the same local worker.
        denied = await run_in_threadpool(guard_http_request, request)
        if denied is not None:
            return denied
    return await call_next(request)


@app.middleware("http")
async def response_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if (request.url.path in HTML_PAGES or request.url.path.startswith("/api/")
            or request.url.path.startswith('/assets/') and request.url.path.endswith(('.js', '.mjs', '.css'))):
        response.headers.setdefault("Cache-Control", "no-store")
    if request.url.path in HTML_PAGES:
        response.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; "
            "script-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'")
    return response

def is_admin(user: User) -> bool:
    return any(role.name == "Administrateur" for role in user.roles)


def permitted(user: User, action: str, folder: str | None = None) -> bool:
    if is_admin(user):
        return True
    for role in user.roles:
        for grant in role.grants:
            if grant.action == action and (folder is None and grant.folder_slug is None or folder is not None and grant.folder_slug in (None, folder)):
                return True
    return False


def must(user: User, action: str, folder: str | None = None):
    if not permitted(user, action, folder):
        raise HTTPException(403, "Accès interdit : habilitation insuffisante")


def admin_only(user: User):
    if not is_admin(user):
        raise HTTPException(403, "Fonction réservée à l'administration")


def audit(db: Session, user: User | None, action: str, entity: object, target_id: str, detail: dict | None = None):
    db.add(AuditEvent(actor_id=user.id if user else None, action=action, target_type=str(entity), target_id=target_id, detail=json.dumps(detail or {}, ensure_ascii=False)))


def user_out(u: User):
    return {"id": u.id, "email": u.email, "name": u.name, "active": u.active, "roles": [r.name for r in u.roles], "admin": is_admin(u)}


def launch_out(l: Launch):
    return {"restricted": bool(l.restricted), "id": l.id, "name": l.name, "order_ref": l.order_ref, "client_name": l.client_name, "orli_ref": l.orli_ref, "status": l.status, "created_at": l.created_at.isoformat(), "updated_at": l.updated_at.isoformat()}


def version_out(v: DocumentVersion):
    db = object_session(v)
    uploader = db.get(User, v.uploaded_by) if db else None
    return {"id": v.id, "number": v.number, "original_name": v.original_name, "size": v.size, "sha256": v.sha256, "created_at": v.created_at.isoformat(), "uploaded_by": v.uploaded_by, "uploaded_by_name": uploader.name if uploader else None}


def doc_out(d: Document):
    versions = sorted(d.versions, key=lambda v: v.number)
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "folder": d.folder.slug, "created_at": d.created_at.isoformat(), "versions": [version_out(v) for v in versions], "latest": version_out(versions[-1]) if versions else None}


class LoginPayload(BaseModel):
    email: str
    password: str

class LaunchPayload(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    client_name: str | None = Field(default=None, max_length=150)
    order_ref: str | None = Field(default=None, max_length=100)
    orli_ref: str | None = Field(default=None, max_length=100)

class LaunchPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    client_name: str | None = Field(default=None, max_length=150)
    order_ref: str | None = Field(default=None, max_length=100)
    orli_ref: str | None = Field(default=None, max_length=100)
    status: str | None = None

class Grant(BaseModel):
    action: str
    folder: str | None = None

class RolePayload(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    permissions: list[Grant] = Field(default_factory=list)

class UserPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role_ids: list[str] = Field(default_factory=list)


@app.get("/", include_in_schema=False)
def landing():
    # Page d'accueil publique.
    return FileResponse(ROOT / "static" / "landing" / "index.html")

@app.get("/espace-framatex", include_in_schema=False)
def index():
    # Application interne FRAMATEX (connexion + dossiers jaunes).
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/espace-client", include_in_schema=False)
def client_index():
    # Portail Client (static/client/), relié à /api/client/*.
    return FileResponse(ROOT / "static" / "client" / "index.html")

@app.get("/api/health")
def health():
    result = {"status": "ok", "version": "0.17.0"}
    # Local supervision must prove which instance answered, not merely obtain a
    # 200 from a stale listener. No paths, credentials or session secrets exposed.
    if os.getenv('FRAMATEX_RUNTIME_ID'):
        result.update(pid=os.getpid(), runtime_id=os.environ['FRAMATEX_RUNTIME_ID'])
    return result

@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    key = login_limit_key(ip, payload.email)
    if not login_attempt_allowed(key):
        raise HTTPException(429, "Trop de tentatives : réessayez dans quelques minutes")
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not user.active or not check_password(user.password_hash, payload.password):
        record_login_failure(key)
        raise HTTPException(401, "Identifiants incorrects")
    clear_login_failures(key)
    response.set_cookie(COOKIE, make_token(user.id), max_age=8*3600, httponly=True, secure=os.getenv("FRAMATEX_COOKIE_SECURE") == "1", samesite="strict", path="/")
    audit(db, user, "session.login", "user", user.id)
    db.commit()
    return user_out(user)

@app.post("/api/auth/logout")
def logout(response: Response, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Deleting a cookie alone does not invalidate a copied signed JWT.
    # Record its unique identifier server-side so reuse is denied immediately.
    import jwt
    from .core import SECRET_KEY
    token = request.cookies.get(COOKIE)
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    audit(db, user, "session.logout", "session", payload["jti"])
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    perms = [{"action": g.action, "folder": g.folder_slug} for r in user.roles for g in r.grants]
    return {**user_out(user), "permissions": perms}

@app.get("/api/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    from .access import visible
    launches = visible(db, user, db.scalars(select(Launch)).all())
    documents = db.scalars(select(Document).join(Folder)).all()
    visible_documents = [d for d in documents if d.folder.launch_id in {l.id for l in launches} and permitted(user, "document.read", d.folder.slug)]
    completion = [evaluate(db, l, user, permitted) for l in launches]
    return {"launches": len(launches), "incomplete": sum(l.status == "À compléter" for l in launches),
            "documents": len(visible_documents), "versions": sum(len(d.versions) for d in visible_documents),
            "completeness_actions": sum(c["counts"]["missing"] + c["counts"]["pending_validation"] for c in completion),
            "completeness_unconfigured": sum(not c["configured"] for c in completion),
            "recent": [launch_out(l) for l in sorted(launches, key=lambda l: l.created_at, reverse=True)[:5]]}

@app.get("/api/launches")
def launches(q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    from .access import visible
    rows = visible(db, user, db.scalars(select(Launch).order_by(Launch.created_at.desc())).all())
    term = q.strip().lower()
    if term:
        rows = [l for l in rows if term in " ".join((l.name, l.client_name or "", l.order_ref or "", l.orli_ref or "")).lower()]
    return [launch_out(l) for l in rows]

@app.post("/api/launches", status_code=201)
def create_launch(payload: LaunchPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.create")
    l = Launch(name=payload.name.strip(), client_name=payload.client_name or None, order_ref=payload.order_ref or None, orli_ref=payload.orli_ref or None, restricted=os.getenv("FRAMATEX_RESTRICT_NEW_LAUNCHES", "0") == "1", created_by=user.id)
    db.add(l)
    db.flush()
    for slug, label in FOLDERS:
        db.add(Folder(launch_id=l.id, slug=slug, label=label))
    audit(db, user, "launch.create", "launch", l.id, {"name": l.name, "orli": l.orli_ref})
    db.commit()
    return launch_out(l)


def get_launch(db: Session, launch_id: str) -> Launch:
    l = db.get(Launch, launch_id)
    if not l:
        raise HTTPException(404, "Lancement introuvable")
    return l

@app.get("/api/launches/{launch_id}")
def launch_detail(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    l = get_launch(db, launch_id)
    folders = []
    for slug, label in FOLDERS:
        folder = next((f for f in l.folders if f.slug == slug), None)
        docs = [] if not folder or not permitted(user, "document.read", slug) else [doc_out(d) for d in folder.documents]
        folders.append({"slug": slug, "label": label, "can_read": permitted(user, "document.read", slug), "can_write": permitted(user, "document.write", slug), "documents": docs})
    return {**launch_out(l), "folders": folders, "can_update": permitted(user, "launch.update"), "can_manage_access": is_admin(user)}

@app.patch("/api/launches/{launch_id}")
def update_launch(launch_id: str, payload: LaunchPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.update")
    l = get_launch(db, launch_id)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in STATUSES:
        raise HTTPException(422, "Statut inconnu")
    if "orli_ref" in changes and db.scalar(select(OrliLink).where(OrliLink.launch_id == l.id)):
        current_ref = l.orli_ref or ''
        requested_ref = changes['orli_ref'] or ''
        from .orli_import import normalize_reference
        if normalize_reference(current_ref) != normalize_reference(requested_ref):
            raise HTTPException(409, "Référence rapprochée à ORLI : modification interdite sans procédure de déliaison")
    for field, value in changes.items():
        setattr(l, field, value.strip() if isinstance(value, str) else value)
    audit(db, user, "launch.update", "launch", l.id, {"fields": list(changes.keys())})
    db.commit()
    return launch_out(l)


def get_doc(db: Session, doc_id: str) -> Document:
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document introuvable")
    return d


def verify_file(file_path: Path, extension: str):
    with file_path.open("rb") as f:
        start = f.read(12)
    if start.startswith((b'MZ', b'\x7fELF')):
        raise HTTPException(422, "Exécutable interdit")
    if extension == ".csv":
        try:
            with file_path.open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.reader(stream, strict=True):
                    if len(row) > 500 or any("\x00" in cell for cell in row):
                        raise ValueError("CSV non textuel ou trop large")
        except (UnicodeError, csv.Error, ValueError):
            raise HTTPException(422, "CSV UTF-8 invalide")
    if extension == ".pdf" and not start.startswith(b"%PDF-"):
        raise HTTPException(422, "Ce fichier ne semble pas être un PDF")
    if extension == ".png" and not start.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "Format PNG non reconnu")
    if extension in (".jpg", ".jpeg") and not start.startswith(b"\xff\xd8\xff"):
        raise HTTPException(422, "Format JPEG non reconnu")
    if extension in (".docx", ".xlsx"):
        try:
            with zipfile.ZipFile(file_path) as z:
                infos = z.infolist()
                if len(infos) > 5000 or sum(info.file_size for info in infos) > 100 * 1024 * 1024 or any(info.file_size > 60 * 1024 * 1024 for info in infos):
                    raise ValueError("archive trop volumineuse après décompression")
                names = set(z.namelist())
                expected = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                if "[Content_Types].xml" not in names or expected not in names or z.testzip() is not None:
                    raise ValueError("structure invalide")
        except (zipfile.BadZipFile, ValueError, RuntimeError, OSError):
            raise HTTPException(422, f"Structure {extension} invalide")


async def store_upload(file: UploadFile):
    original_name = Path((file.filename or "").replace("\\", "/")).name[:240]
    suffix = Path(original_name).suffix.lower()
    if not original_name or suffix not in EXTS:
        raise HTTPException(422, "Format non autorisé (PDF, DOCX, XLSX, PNG, JPEG, TXT, EML ou CSV)")
    disk_name = secrets.token_hex(24)
    target = STORAGE / disk_name
    sha = hashlib.sha256()
    total = 0
    try:
        with target.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, "Fichier trop volumineux (20 Mo maximum)")
                sha.update(chunk)
                out.write(chunk)
        if total == 0:
            raise HTTPException(422, "Fichier vide")
        verify_file(target, suffix)
        return original_name, disk_name, total, sha.hexdigest(), MIMES[suffix]
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.post("/api/launches/{launch_id}/documents", status_code=201)
async def upload_document(launch_id: str, folder: str = Form(...), title: str = Form(...), doc_type: str = Form("Autre"), comment: str = Form("", max_length=2000), file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    if folder not in SLUGS:
        raise HTTPException(422, "Sous-dossier invalide")
    must(user, "document.write", folder)
    launch = get_launch(db, launch_id)
    entity = next((f for f in launch.folders if f.slug == folder), None)
    if entity is None or not title.strip() or len(title) > 220 or len(doc_type) > 100:
        raise HTTPException(422, "Métadonnées invalides")
    original, disk_name, size, sha, mime = await store_upload(file)
    try:
        doc = Document(folder_id=entity.id, title=title.strip(), doc_type=doc_type.strip() or "Autre", created_by=user.id)
        db.add(doc)
        db.flush()
        version = DocumentVersion(document_id=doc.id, number=1, original_name=original, disk_name=disk_name, size=size, sha256=sha, content_type=mime, uploaded_by=user.id)
        db.add(version)
        db.flush()
        if comment.strip():
            from .internal_routes import append_comment
            append_comment(db, user, version, comment)
        from .internal_uploads import duplicates
        matches = duplicates(db, user, launch_id, folder, sha, exclude_id=doc.id)
        launch.updated_at = utcnow()
        from .quality_routes import auto_inspect_excel
        auto_inspect_excel(db, version, user.id)
        audit(db, user, "document.upload", "document", doc.id, {"launch": launch_id, "folder": folder, "sha256": sha, "duplicate_count": len(matches)})
        db.commit()
        return {**doc_out(doc), "duplicates": matches}
    except Exception:
        db.rollback()
        (STORAGE / disk_name).unlink(missing_ok=True)
        raise

@app.post("/api/documents/{doc_id}/versions", status_code=201)
async def new_version(doc_id: str, file: UploadFile = File(...), comment: str = Form("", max_length=2000), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_doc(db, doc_id)
    must(user, "document.write", d.folder.slug)
    original, disk_name, size, sha, mime = await store_upload(file)
    try:
        if any(v.sha256 == sha for v in d.versions):
            raise HTTPException(409, "Ce fichier est déjà conservé dans les versions de ce document")
        next_number = max((v.number for v in d.versions), default=0) + 1
        version = DocumentVersion(document_id=d.id, number=next_number, original_name=original, disk_name=disk_name, size=size, sha256=sha, content_type=mime, uploaded_by=user.id)
        d.versions.append(version)
        db.flush()
        if comment.strip():
            from .internal_routes import append_comment
            append_comment(db, user, version, comment)
        d.folder.launch.updated_at = utcnow()
        emit_document_impacts(db, d, version)
        from .quality_routes import auto_inspect_excel
        auto_inspect_excel(db, version, user.id)
        audit(db, user, "document.version.add", "document", d.id, {"version": next_number, "sha256": sha})
        db.commit()
        return doc_out(d)
    except IntegrityError:
        db.rollback()
        (STORAGE / disk_name).unlink(missing_ok=True)
        raise HTTPException(409, "Conflit de version, recommencez le dépôt")
    except Exception:
        db.rollback()
        (STORAGE / disk_name).unlink(missing_ok=True)
        raise

@app.get("/api/documents/{doc_id}/versions/{number}/download")
def download(doc_id: str, number: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = get_doc(db, doc_id)
    must(user, "document.read", doc.folder.slug)
    version = next((v for v in doc.versions if v.number == number), None)
    if not version:
        raise HTTPException(404, "Version introuvable")
    path = STORAGE / version.disk_name
    if not path.is_file():
        raise HTTPException(503, "Fichier indisponible dans le stockage")
    audit(db, user, "document.download", "document", doc.id, {"version": number})
    db.commit()
    return FileResponse(path, filename=version.original_name, content_disposition_type="attachment", media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})

@app.get("/api/admin/roles")
def list_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    return [{"id": r.id, "name": r.name, "permissions": [{"action": g.action, "folder": g.folder_slug} for g in r.grants]} for r in db.scalars(select(Role).order_by(Role.name)).all()]

@app.post("/api/admin/roles", status_code=201)
def create_role(payload: RolePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    if payload.name.strip().lower() == "administrateur":
        raise HTTPException(422, "Ce rôle est réservé au système")
    for p in payload.permissions:
        if p.action not in ACTIONS or p.folder not in (None, *SLUGS) or (p.folder and not (p.action.startswith("document.") or p.action in {"completeness.review", "value.write", "impact.review", "quality.review", "requirement.review", "ambiguity.review", "commitment.review"})):
            raise HTTPException(422, "Permission inconnue")
    role = Role(name=payload.name.strip())
    seen = set()
    for p in payload.permissions:
        if (p.action, p.folder) not in seen:
            role.grants.append(RolePermission(action=p.action, folder_slug=p.folder))
            seen.add((p.action, p.folder))
    db.add(role)
    try:
        db.flush()
        audit(db, user, "role.create", "role", role.id, {"name": role.name})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Nom de rôle déjà utilisé")
    return {"id": role.id, "name": role.name}

@app.get("/api/admin/users")
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    return [user_out(u) for u in db.scalars(select(User).order_by(User.name)).all()]

@app.post("/api/admin/users", status_code=201)
def create_user(payload: UserPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    if "@" not in payload.email:
        raise HTTPException(422, "Email invalide")
    roles = [db.get(Role, id_) for id_ in set(payload.role_ids)]
    if not roles or any(r is None for r in roles):
        raise HTTPException(422, "Indiquez au moins un rôle existant")
    new_user = User(name=payload.name.strip(), email=payload.email.strip().lower(), password_hash=hash_password(payload.password), roles=roles)
    db.add(new_user)
    try:
        db.flush()
        audit(db, user, "user.create", "user", new_user.id, {"roles": [r.name for r in roles]})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Un compte utilise déjà cette adresse")
    return user_out(new_user)

@app.get("/api/admin/audit")
def list_audit(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(100)).all()
    return [{"id": x.id, "action": x.action, "actor_id": x.actor_id, "target_type": x.target_type, "target_id": x.target_id, "detail": json.loads(x.detail), "occurred_at": x.occurred_at.isoformat()} for x in rows]


# ─── Complétude documentaire contextuelle (MVP 0.2) ───────────────

class ProfilePayload(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=1200)

class RequirementPayload(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    folder: str
    document_type: str = Field(min_length=2, max_length=100)
    due_phase: str = "preparation"
    requires_validation: bool = False
    guidance: str = Field(default="", max_length=1600)

class RequirementPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    due_phase: str | None = None
    requires_validation: bool | None = None
    guidance: str | None = Field(default=None, max_length=1600)
    active: bool | None = None

class ContextPayload(BaseModel):
    profile_id: str | None = None
    phase: str = "preparation"

class ValidationPayload(BaseModel):
    document_id: str

class ExceptionPayload(BaseModel):
    reason: str = Field(default="", max_length=2000)
    active: bool = True


def rule_out(r: RequirementRule):
    return {"id": r.id, "title": r.title, "folder": r.folder_slug,
            "document_type": r.document_type, "due_phase": r.due_phase,
            "requires_validation": r.requires_validation, "active": r.active,
            "guidance": r.guidance}


def profile_out(p: CompletenessProfile, include_rules=False):
    data = {"id": p.id, "name": p.name, "description": p.description,
            "active_rules": sum(r.active for r in p.rules)}
    if include_rules:
        data["rules"] = [rule_out(r) for r in sorted(p.rules, key=lambda x: (PHASE_RANK[x.due_phase], x.title))]
    return data


@app.get("/api/completeness/profiles")
def public_profiles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    return [profile_out(p) for p in db.scalars(select(CompletenessProfile).order_by(CompletenessProfile.name)).all()]


@app.get("/api/admin/completeness/profiles")
def admin_profiles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    return [profile_out(p, True) for p in db.scalars(select(CompletenessProfile).order_by(CompletenessProfile.name)).all()]


@app.post("/api/admin/completeness/profiles", status_code=201)
def create_profile(payload: ProfilePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    profile = CompletenessProfile(name=payload.name.strip(), description=payload.description.strip(), created_by=user.id)
    db.add(profile)
    try:
        db.flush()
        audit(db, user, "completeness.profile.create", "completeness_profile", profile.id, {"name": profile.name})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ce nom de profil existe déjà")
    return profile_out(profile, True)


@app.post("/api/admin/completeness/profiles/{profile_id}/rules", status_code=201)
def add_requirement(profile_id: str, payload: RequirementPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    if payload.folder not in SLUGS or payload.due_phase not in PHASE_RANK:
        raise HTTPException(422, "Sous-dossier ou étape invalide")
    profile = db.get(CompletenessProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profil introuvable")
    rule = RequirementRule(profile_id=profile.id, title=payload.title.strip(), folder_slug=payload.folder,
                           document_type=payload.document_type.strip(), due_phase=payload.due_phase,
                           requires_validation=payload.requires_validation, guidance=payload.guidance.strip())
    db.add(rule)
    try:
        db.flush()
        audit(db, user, "completeness.rule.create", "completeness_rule", rule.id,
              {"profile": profile.id, "type": rule.document_type, "due_phase": rule.due_phase})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ce type documentaire existe déjà dans ce sous-dossier et ce profil")
    return rule_out(rule)


@app.patch("/api/admin/completeness/rules/{rule_id}")
def patch_requirement(rule_id: str, payload: RequirementPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only(user)
    rule = db.get(RequirementRule, rule_id)
    if not rule:
        raise HTTPException(404, "Règle introuvable")
    changes = payload.model_dump(exclude_unset=True)
    if "due_phase" in changes and changes["due_phase"] not in PHASE_RANK:
        raise HTTPException(422, "Étape inconnue")
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, "Modifications invalides")
    for field, value in changes.items():
        setattr(rule, field, value.strip() if isinstance(value, str) else value)
    audit(db, user, "completeness.rule.update", "completeness_rule", rule.id, {"changed": changes})
    db.commit()
    return rule_out(rule)


@app.patch("/api/launches/{launch_id}/completeness/context")
def set_completeness_context(launch_id: str, payload: ContextPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.update")
    launch = get_launch(db, launch_id)
    if payload.phase not in PHASE_RANK:
        raise HTTPException(422, "Étape inconnue")
    if payload.profile_id is not None and not db.get(CompletenessProfile, payload.profile_id):
        raise HTTPException(422, "Profil de complétude inconnu")
    context = db.get(LaunchCompleteness, launch.id)
    if not context:
        context = LaunchCompleteness(launch_id=launch.id)
        db.add(context)
    context.profile_id, context.phase = payload.profile_id, payload.phase
    audit(db, user, "completeness.context.update", "launch", launch.id,
          {"profile": payload.profile_id, "phase": payload.phase})
    db.commit()
    return evaluate(db, launch, user, permitted)


@app.get("/api/launches/{launch_id}/completeness")
def get_completeness(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    return evaluate(db, get_launch(db, launch_id), user, permitted)


def require_active_launch_rule(db, launch_id, rule_id):
    launch = get_launch(db, launch_id)
    rule = db.get(RequirementRule, rule_id)
    context = db.get(LaunchCompleteness, launch.id)
    if not rule or not rule.active or not context or context.profile_id != rule.profile_id:
        raise HTTPException(404, "Règle non applicable à ce lancement")
    return launch, rule


@app.post("/api/launches/{launch_id}/completeness/rules/{rule_id}/validate")
def validate_requirement(launch_id: str, rule_id: str, payload: ValidationPayload,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    launch, rule = require_active_launch_rule(db, launch_id, rule_id)
    must(user, "completeness.review", rule.folder_slug)
    must(user, "document.read", rule.folder_slug)
    if not rule.requires_validation:
        raise HTTPException(422, "Cette exigence ne nécessite pas de validation distincte")
    doc = get_doc(db, payload.document_id)
    if doc.folder.launch_id != launch.id or doc.folder.slug != rule.folder_slug or doc.doc_type != rule.document_type:
        raise HTTPException(422, "Document non conforme au type et au lancement de la règle")
    if not doc.versions:
        raise HTTPException(422, "Document sans version")
    version = max(doc.versions, key=lambda v: v.number)
    # Une exigence de complétude ne remplace pas le circuit métier configuré.
    from .approval_routes import applicable_template
    if applicable_template(db, doc):
        from .approval_models import ApprovalRun
        approved = db.scalar(select(ApprovalRun).where(
            ApprovalRun.document_version_id == version.id, ApprovalRun.status == 'approved'))
        if not approved:
            raise HTTPException(409, 'Circuit de validation non achevé pour cette version')
    review_decision = latest_review(db, version.id)
    if review_decision and review_decision.decision in {'rejected', 'changes_requested'}:
        raise HTTPException(409, 'Version refusée ou à reprendre : le contrôle documentaire doit être régularisé')
    existing = db.scalar(select(RequirementValidation).where(
        RequirementValidation.rule_id == rule.id,
        RequirementValidation.document_version_id == version.id
    ))
    if existing:
        raise HTTPException(409, "Cette version a déjà été validée")
    db.add(RequirementValidation(rule_id=rule.id, document_version_id=version.id,
                                 launch_id=launch.id, validated_by=user.id))
    audit(db, user, "completeness.validate", "document_version", version.id,
          {"rule": rule.id, "launch": launch.id, "version": version.number})
    db.commit()
    return evaluate(db, launch, user, permitted)


@app.put("/api/launches/{launch_id}/completeness/rules/{rule_id}/exception")
def set_requirement_exception(launch_id: str, rule_id: str, payload: ExceptionPayload,
                              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    must(user, "launch.read")
    launch, rule = require_active_launch_rule(db, launch_id, rule_id)
    must(user, "completeness.review", rule.folder_slug)
    must(user, "document.read", rule.folder_slug)
    if payload.active and len(payload.reason.strip()) < 12:
        raise HTTPException(422, "Précisez une justification d'au moins 12 caractères")
    exception = db.scalar(select(RequirementException).where(
        RequirementException.launch_id == launch.id, RequirementException.rule_id == rule.id
    ))
    if not exception and payload.active:
        exception = RequirementException(launch_id=launch.id, rule_id=rule.id, recorded_by=user.id)
        db.add(exception)
    if exception:
        exception.active = payload.active
        exception.reason = payload.reason.strip() if payload.active else exception.reason
        exception.recorded_by = user.id
    audit(db, user, "completeness.exception.set", "completeness_rule", rule.id,
          {"launch": launch.id, "active": payload.active, "reason": payload.reason.strip() if payload.active else ""})
    db.commit()
    return evaluate(db, launch, user, permitted)

# Modules 0.3 : enregistrés après les dépendances partagées de main.py.
from .workflow_routes import router as workflow_router
app.include_router(workflow_router)

# Module 0.4 — contrôles à partir des valeurs et fichiers réellement enregistrés.
from .quality_routes import router as quality_router
app.include_router(quality_router)

# Module 0.5 — suggestions sans classement automatique ni intégration ORLI.
from .intake_routes import router as intake_router
app.include_router(intake_router)

# Module 0.6 — QR et passeports, sans contournement des habilitations.
from .paper_routes import router as paper_router
app.include_router(paper_router)

# Module 0.7 — couverture des exigences et registre des ambiguïtés.
from .spec_routes import router as spec_router
app.include_router(spec_router)

# Module 0.8 — Emails .eml et engagements confirmés après lecture.
from .mail_routes import router as mail_router
app.include_router(mail_router)

from .workspace_routes import router as workspace_router
app.include_router(workspace_router)

# 0.10 — graphe métier et estimations non destructives.
from .impact_sim_routes import router as impact_sim_router
app.include_router(impact_sim_router)

# 0.11 — import ORLI read-only, décision de rapprochement explicite.
from .orli_routes import router as orli_router
app.include_router(orli_router)

# 0.12 — matières documentées et rapprochements non destructifs.
from .material_routes import router as material_router
app.include_router(material_router)

# 0.13 — circuits séquentiels de validation et notifications internes.
from .approval_routes import router as approval_router
app.include_router(approval_router)

# 0.14 — Publications client et demandes fournisseurs simulées (accès uniquement interne).
from .sharing_routes import router as sharing_router
app.include_router(sharing_router)


# 0.15 — Gestion des accès d'un lancement par l'administrateur.
from .access_routes import router as access_router
app.include_router(access_router)

# 0.17 — Signalements pilotes anonymisés vis-à-vis des autres collaborateurs.
from .pilot_routes import router as pilot_router
app.include_router(pilot_router)

# Espace Client : comptes, sessions et stockage séparés du dossier jaune.
from .client_routes import router as client_router
app.include_router(client_router)

from .internal_routes import router as internal_router
app.include_router(internal_router)

from .client_workflow_routes import router as client_workflow_router
app.include_router(client_workflow_router)

# Le contrôle global de portée est effectué dans request_header_guard, avant
# le dispatch FastAPI. Aucun routeur historique ne peut l'éviter.

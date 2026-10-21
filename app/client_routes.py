from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .client_models import ClientAccount, ClientOrderDocument, ClientOrderDocumentVersion, ClientOrderRequest
from .core import (DATA_DIR, SECRET_KEY, check_password, get_current_user, get_db,
                   hash_password, login_attempt_allowed, login_limit_key,
                   record_login_failure, clear_login_failures, utcnow)
from .models import AuditEvent, User

router = APIRouter()
CLIENT_COOKIE = "framat_client_session"
CLIENT_STORAGE = DATA_DIR / "client_order_files"
CLIENT_STORAGE.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = 20 * 1024 * 1024
EXTS = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".txt"}
MIMES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain"}


def normalized_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Adresse email invalide")
    return value


class RegisterPayload(BaseModel):
    raison_sociale: str = Field(min_length=2, max_length=180)
    nom_contact: str = Field(min_length=2, max_length=160)
    email: str
    telephone: str = Field(min_length=3, max_length=40)
    adresse: str = Field(min_length=3, max_length=1000)
    pays: str = Field(min_length=2, max_length=100)
    identifiant_fiscal: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=12, max_length=256)

    _email = field_validator("email")(normalized_email)


class ClientLoginPayload(BaseModel):
    email: str
    password: str = Field(max_length=256)
    _email = field_validator("email")(normalized_email)


class StatusPayload(BaseModel):
    status: Literal["active", "suspended"]


class OrderPayload(BaseModel):
    article: str = Field(min_length=2, max_length=180)
    quantite: int = Field(gt=0, le=10_000_000)
    date_souhaitee: date
    reference_client: str | None = Field(default=None, max_length=100)
    commentaire: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "submitted"] = "draft"


def client_token(client_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": client_id, "typ": "client", "iat": now,
                       "exp": now + timedelta(hours=8), "jti": secrets.token_hex(16)},
                      SECRET_KEY, algorithm="HS256")


def get_current_client(request: Request, db: Session = Depends(get_db)) -> ClientAccount:
    token = request.cookies.get(CLIENT_COOKIE)
    if not token:
        raise HTTPException(401, "Connexion client nécessaire")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("typ") != "client" or not isinstance(payload.get("jti"), str):
            raise HTTPException(401, "Session client invalide")
        revoked = db.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "client.session.logout", AuditEvent.target_id == payload["jti"]
        ).limit(1))
        if revoked is not None:
            raise HTTPException(401, "Session client révoquée")
        client = db.get(ClientAccount, payload["sub"])
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(401, "Session client expirée ou invalide")
    if not client or client.status != "active":
        raise HTTPException(403, "Compte client non actif")
    return client


def client_out(client: ClientAccount) -> dict:
    return {"id": client.id, "client_code": client.client_code,
            "raison_sociale": client.raison_sociale, "nom_contact": client.nom_contact,
            "email": client.email, "telephone": client.telephone, "adresse": client.adresse,
            "pays": client.pays, "identifiant_fiscal": client.identifiant_fiscal,
            "status": client.status, "created_at": client.created_at.isoformat(),
            "updated_at": client.updated_at.isoformat()}


def order_out(order: ClientOrderRequest, include_documents: bool = False) -> dict:
    result = {"id": order.id, "request_number": order.request_number,
              "article": order.article, "quantite": order.quantite,
              "date_souhaitee": order.date_souhaitee.isoformat(),
              "reference_client": order.reference_client, "commentaire": order.commentaire,
              "status": order.status, "created_at": order.created_at.isoformat(),
              "updated_at": order.updated_at.isoformat()}
    if include_documents:
        result["documents"] = [document_out(doc) for doc in order.documents]
    return result


def document_out(document: ClientOrderDocument) -> dict:
    return {"id": document.id, "title": document.title, "created_at": document.created_at.isoformat(),
            "versions": [{"id": version.id, "number": version.number,
                          "original_name": version.original_name, "size": version.size,
                          "sha256": version.sha256, "created_at": version.created_at.isoformat()}
                         for version in document.versions]}


def add_audit(db: Session, actor_id: str | None, action: str, target_type: str,
              target_id: str, detail: dict | None = None):
    db.add(AuditEvent(actor_id=actor_id, action=action, target_type=target_type,
                      target_id=target_id, detail=json.dumps(detail or {}, ensure_ascii=False)))


def new_client_code() -> str:
    return f"CL-{secrets.randbelow(1_000_000):06d}"


def new_request_number() -> str:
    return f"DR-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4).upper()}"


@router.post("/api/client/register", status_code=201)
def register(payload: RegisterPayload, db: Session = Depends(get_db)):
    if db.scalar(select(ClientAccount.id).where(func.lower(ClientAccount.email) == payload.email)):
        raise HTTPException(409, "Un compte existe déjà pour cette adresse email")
    client = ClientAccount(client_code=new_client_code(), raison_sociale=payload.raison_sociale.strip(),
                           nom_contact=payload.nom_contact.strip(), email=payload.email,
                           telephone=payload.telephone.strip(), adresse=payload.adresse.strip(),
                           pays=payload.pays.strip(),
                           identifiant_fiscal=(payload.identifiant_fiscal or "").strip() or None,
                           password_hash=hash_password(payload.password), status="pending")
    db.add(client)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Compte client déjà existant")
    add_audit(db, client.id, "client.register", "client_account", client.id)
    db.commit()
    return client_out(client)


@router.post("/api/client/login")
def client_login(payload: ClientLoginPayload, response: Response, request: Request,
                 db: Session = Depends(get_db)):
    key = login_limit_key(request.client.host if request.client else "unknown", "client:" + payload.email)
    if not login_attempt_allowed(key):
        raise HTTPException(429, "Trop de tentatives : réessayez dans quelques minutes")
    client = db.scalar(select(ClientAccount).where(func.lower(ClientAccount.email) == payload.email))
    if not client or not check_password(client.password_hash, payload.password):
        record_login_failure(key)
        raise HTTPException(401, "Identifiants incorrects")
    if client.status != "active":
        record_login_failure(key)
        raise HTTPException(403, "Compte client en attente d'activation ou suspendu")
    clear_login_failures(key)
    response.set_cookie(CLIENT_COOKIE, client_token(client.id), max_age=8 * 3600,
                        httponly=True, secure=os.getenv("FRAMATEX_COOKIE_SECURE") == "1",
                        samesite="strict", path="/api/client")
    add_audit(db, client.id, "client.session.login", "client_account", client.id)
    db.commit()
    return client_out(client)


@router.post("/api/client/logout")
def client_logout(response: Response, request: Request, client: ClientAccount = Depends(get_current_client),
                  db: Session = Depends(get_db)):
    payload = jwt.decode(request.cookies[CLIENT_COOKIE], SECRET_KEY, algorithms=["HS256"])
    add_audit(db, client.id, "client.session.logout", "client_session", payload["jti"])
    db.commit()
    response.delete_cookie(CLIENT_COOKIE, path="/api/client")
    return {"ok": True}


@router.get("/api/client/me")
def client_me(client: ClientAccount = Depends(get_current_client)):
    return client_out(client)


@router.get("/api/admin/clients")
def list_clients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import admin_only
    admin_only(user)
    return [client_out(client) for client in db.scalars(select(ClientAccount).order_by(ClientAccount.created_at)).all()]


@router.patch("/api/admin/clients/{client_id}/status")
def set_client_status(client_id: str, payload: StatusPayload,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import admin_only
    admin_only(user)
    client = db.get(ClientAccount, client_id)
    if not client:
        raise HTTPException(404, "Compte client introuvable")
    previous = client.status
    client.status = payload.status
    client.updated_at = utcnow()
    add_audit(db, user.id, "client.status.update", "client_account", client.id,
              {"previous": previous, "status": payload.status})
    db.commit()
    return client_out(client)


@router.post("/api/client/order-requests", status_code=201)
def create_order_request(payload: OrderPayload, client: ClientAccount = Depends(get_current_client),
                         db: Session = Depends(get_db)):
    order = ClientOrderRequest(client_id=client.id, request_number=new_request_number(),
                               article=payload.article.strip(), quantite=payload.quantite,
                               date_souhaitee=payload.date_souhaitee,
                               reference_client=(payload.reference_client or "").strip() or None,
                               commentaire=(payload.commentaire or "").strip() or None,
                               status=payload.status)
    db.add(order)
    db.flush()
    add_audit(db, client.id, "client.order_request.create", "client_order_request", order.id,
              {"request_number": order.request_number, "status": order.status})
    db.commit()
    return order_out(order)


@router.get("/api/client/order-requests")
def list_order_requests(client: ClientAccount = Depends(get_current_client),
                        db: Session = Depends(get_db)):
    rows = db.scalars(select(ClientOrderRequest).where(ClientOrderRequest.client_id == client.id)
                      .order_by(ClientOrderRequest.created_at.desc())).all()
    return [order_out(row) for row in rows]


def own_order(db: Session, client: ClientAccount, order_id: str) -> ClientOrderRequest:
    order = db.scalar(select(ClientOrderRequest).where(
        ClientOrderRequest.id == order_id, ClientOrderRequest.client_id == client.id))
    if not order:
        raise HTTPException(404, "Demande de commande introuvable")
    return order


@router.get("/api/client/order-requests/{order_id}")
def get_order_request(order_id: str, client: ClientAccount = Depends(get_current_client),
                      db: Session = Depends(get_db)):
    return order_out(own_order(db, client, order_id), include_documents=True)


def verify_file(path: Path, extension: str):
    with path.open("rb") as stream:
        start = stream.read(12)
    if extension == ".pdf" and not start.startswith(b"%PDF-"):
        raise HTTPException(422, "Ce fichier ne semble pas être un PDF")
    if extension == ".png" and not start.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "Format PNG non reconnu")
    if extension in {".jpg", ".jpeg"} and not start.startswith(b"\xff\xd8\xff"):
        raise HTTPException(422, "Format JPEG non reconnu")
    if extension in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                expected = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                if (len(infos) > 5000 or sum(i.file_size for i in infos) > 100 * 1024 * 1024
                        or "[Content_Types].xml" not in archive.namelist()
                        or expected not in archive.namelist() or archive.testzip() is not None):
                    raise ValueError
        except (zipfile.BadZipFile, ValueError, RuntimeError, OSError):
            raise HTTPException(422, f"Structure {extension} invalide")


async def store_client_upload(file: UploadFile):
    original = Path((file.filename or "").replace("\\", "/")).name[:240]
    extension = Path(original).suffix.lower()
    if not original or extension not in EXTS:
        raise HTTPException(422, "Format de document client non autorisé")
    disk_name = secrets.token_hex(24)
    target = CLIENT_STORAGE / disk_name
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("xb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "Fichier trop volumineux (20 Mo maximum)")
                digest.update(chunk)
                output.write(chunk)
        if size == 0:
            raise HTTPException(422, "Fichier vide")
        verify_file(target, extension)
        return original, disk_name, size, digest.hexdigest(), MIMES[extension]
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.post("/api/client/order-requests/{order_id}/documents", status_code=201)
async def upload_order_document(order_id: str, title: str = Form(...), file: UploadFile = File(...),
                                client: ClientAccount = Depends(get_current_client),
                                db: Session = Depends(get_db)):
    order = own_order(db, client, order_id)
    title = title.strip()
    if not title or len(title) > 220:
        raise HTTPException(422, "Titre invalide")
    original, disk_name, size, digest, content_type = await store_client_upload(file)
    try:
        document = db.scalar(select(ClientOrderDocument).where(
            ClientOrderDocument.order_request_id == order.id, ClientOrderDocument.title == title))
        if not document:
            document = ClientOrderDocument(order_request_id=order.id, title=title)
            db.add(document)
            db.flush()
        number = (db.scalar(select(func.max(ClientOrderDocumentVersion.number)).where(
            ClientOrderDocumentVersion.document_id == document.id)) or 0) + 1
        version = ClientOrderDocumentVersion(document_id=document.id, number=number,
                    original_name=original, disk_name=disk_name, content_type=content_type,
                    size=size, sha256=digest, uploaded_by_client_id=client.id)
        db.add(version)
        db.flush()
        add_audit(db, client.id, "client.order_document.upload", "client_order_document", document.id,
                  {"order_request": order.id, "version": number, "sha256": digest})
        db.commit()
        db.refresh(document)
        return document_out(document)
    except Exception:
        db.rollback()
        (CLIENT_STORAGE / disk_name).unlink(missing_ok=True)
        raise


@router.get("/api/client/order-requests/{order_id}/documents/{document_id}/versions/{number}/download")
def download_order_document(order_id: str, document_id: str, number: int,
                            client: ClientAccount = Depends(get_current_client),
                            db: Session = Depends(get_db)):
    own_order(db, client, order_id)
    version = db.scalar(select(ClientOrderDocumentVersion).join(ClientOrderDocument).where(
        ClientOrderDocument.id == document_id,
        ClientOrderDocument.order_request_id == order_id,
        ClientOrderDocumentVersion.number == number))
    if not version:
        raise HTTPException(404, "Version de document introuvable")
    path = CLIENT_STORAGE / version.disk_name
    if not path.is_file():
        raise HTTPException(404, "Fichier client introuvable")
    add_audit(db, client.id, "client.order_document.download", "client_order_document", document_id,
              {"order_request": order_id, "version": number})
    db.commit()
    return FileResponse(path, media_type=version.content_type, filename=version.original_name)

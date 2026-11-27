from __future__ import annotations

import os
import secrets
import time
from threading import Lock
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("FRAMATEX_DATA_DIR", str(ROOT / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
# PostgreSQL est le moteur courant unique. Une indisponibilité ou une configuration
# absente doit être visible : aucun repli silencieux vers un fichier SQLite neuf.
# SQLite reste accepté uniquement pour les outils explicites de lecture/migration
# des anciennes bases et les fixtures historiques isolées.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL PostgreSQL est absente. Démarrez le service PostgreSQL puis "
        "lancez FRAMATEX avec scripts\\start_windows.cmd. Aucun repli SQLite n'est effectué."
    )
if DATABASE_URL.startswith(("postgresql://", "postgres://")):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.split("://", 1)[1]
IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")
if IS_SQLITE and os.getenv("FRAMATEX_LEGACY_SQLITE_MODE") != "1":
    raise RuntimeError(
        "SQLite est réservé aux outils historiques de migration. "
        "Configurez DATABASE_URL vers PostgreSQL pour exécuter FRAMATEX."
    )
if not (IS_SQLITE or IS_POSTGRES):
    raise RuntimeError("DATABASE_URL doit utiliser PostgreSQL (pilote psycopg 3).")


def _engine_options() -> dict:
    timeout = int(os.getenv("FRAMATEX_DB_POOL_TIMEOUT", "30"))
    if IS_SQLITE:
        # Pool dimensionné sur le pool de threads de l'application (40 par défaut) : chaque requête
        # synchrone occupe au plus une connexion.
        return {"connect_args": {"check_same_thread": False, "timeout": 15}, "pool_pre_ping": True,
                "pool_size": int(os.getenv("FRAMATEX_DB_POOL_SIZE", "20")),
                "max_overflow": int(os.getenv("FRAMATEX_DB_MAX_OVERFLOW", "20")), "pool_timeout": timeout}
    if IS_POSTGRES:
        # PostgreSQL : connexions coûteuses côté serveur (≈ 10 Mo chacune) ; pool modéré par processus
        # (processus × (taille + débordement) doit rester sous max_connections). Fuseau UTC, délais
        # bornés : une requête ou une attente de verrou anormale échoue au lieu de bloquer le pool.
        options = (f"-c timezone=UTC -c statement_timeout={int(os.getenv('FRAMATEX_PG_STATEMENT_TIMEOUT_MS', '30000'))}"
                   f" -c lock_timeout={int(os.getenv('FRAMATEX_PG_LOCK_TIMEOUT_MS', '10000'))}"
                   f" -c idle_in_transaction_session_timeout={int(os.getenv('FRAMATEX_PG_IDLE_TX_TIMEOUT_MS', '60000'))}")
        return {"connect_args": {"options": options, "application_name": "framatex"}, "pool_pre_ping": True,
                "pool_size": int(os.getenv("FRAMATEX_DB_POOL_SIZE", "10")),
                "max_overflow": int(os.getenv("FRAMATEX_DB_MAX_OVERFLOW", "10")), "pool_timeout": timeout,
                "pool_recycle": 1800}
    return {"pool_pre_ping": True}


engine = create_engine(DATABASE_URL, **_engine_options())
if DATABASE_URL.startswith("sqlite") and ":memory:" not in DATABASE_URL:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        # Accès simultanés : une écriture concurrente attend la libération du verrou (15 s au plus)
        # au lieu d'échouer aussitôt. Le mode WAL a été mesuré sans gain de débit et écarté : une copie
        # brute de framat.db (sauvegarde manuelle, Windows) pourrait omettre les écritures récentes.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=15000")
        # Plusieurs processus serveur : le journal WAL laisse lire pendant une écriture. Option de
        # production (FRAMATEX_SQLITE_WAL=1) : les sauvegardes doivent alors passer par
        # scripts/backup_framatex.py (API de sauvegarde SQLite), jamais par une copie brute du fichier.
        # Intégrité référentielle appliquée par SQLite (désactivée par défaut historiquement) : option à
        # valider en préproduction avant activation (voir docs/ENTERPRISE_READINESS_AUDIT.md).
        if os.getenv("FRAMATEX_SQLITE_FOREIGN_KEYS") == "1":
            cursor.execute("PRAGMA foreign_keys=ON")
        if os.getenv("FRAMATEX_SQLITE_WAL") == "1":
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db


def secret_key() -> str:
    env = os.getenv("FRAMATEX_SECRET_KEY")
    if env:
        if len(env) < 32:
            raise RuntimeError("FRAMATEX_SECRET_KEY doit contenir au moins 32 caractères")
        return env
    path = DATA_DIR / ".session_secret"
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(secrets.token_urlsafe(48))
    return path.read_text().strip()

SECRET_KEY = secret_key()
PASSWORDS = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2)
COOKIE = "framat_session"

# Local pilot protection against repeated password guesses. This deliberately
# remains process-local; a production multi-worker setup needs a shared store.
_LOGIN_FAILURES: dict[tuple[str, str], list[float]] = {}
_LOGIN_FAILURE_LOCK = Lock()
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 5


def login_limit_key(ip: str, email: str) -> tuple[str, str]:
    # Do not trust X-Forwarded-For unless a trusted proxy is configured.
    return (ip, email.strip().lower()[:254])


def login_attempt_allowed(key: tuple[str, str]) -> bool:
    current = time.monotonic()
    with _LOGIN_FAILURE_LOCK:
        recent = [t for t in _LOGIN_FAILURES.get(key, ()) if t > current - LOGIN_WINDOW_SECONDS]
        if recent:
            _LOGIN_FAILURES[key] = recent
        else:
            _LOGIN_FAILURES.pop(key, None)
        return len(recent) < LOGIN_MAX_FAILURES


def record_login_failure(key: tuple[str, str]):
    current = time.monotonic()
    with _LOGIN_FAILURE_LOCK:
        # Bound the number of tracked pairs to limit memory abuse.
        if len(_LOGIN_FAILURES) > 4000:
            for pair, times in list(_LOGIN_FAILURES.items()):
                if all(t < current - LOGIN_WINDOW_SECONDS for t in times):
                    _LOGIN_FAILURES.pop(pair, None)
        if len(_LOGIN_FAILURES) <= 5000 or key in _LOGIN_FAILURES:
            _LOGIN_FAILURES.setdefault(key, []).append(current)


def clear_login_failures(key: tuple[str, str]):
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURES.pop(key, None)


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise HTTPException(422, "Le mot de passe doit contenir entre 12 et 256 caractères")
    return PASSWORDS.hash(password)


def check_password(digest: str, plain: str) -> bool:
    try:
        return PASSWORDS.verify(digest, plain)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def make_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(hours=8), "jti": secrets.token_hex(16)}, SECRET_KEY, algorithm="HS256")


def utcnow():
    return datetime.now(timezone.utc)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    from .models import User
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Connexion nécessaire")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("typ") == "client":            # jeton de l'espace Client : jamais valable ici
            raise HTTPException(401, "Session expirée ou invalide")
        session_id = payload.get("jti")
        if not isinstance(session_id, str) or len(session_id) != 32:
            raise HTTPException(401, "Session précédente expirée : veuillez vous reconnecter")
        from .models import AuditEvent
        from sqlalchemy import select
        revoked = db.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "session.logout",
            AuditEvent.target_id == session_id).limit(1))
        if revoked is not None:
            raise HTTPException(401, "Session révoquée : veuillez vous reconnecter")
        user = db.get(User, payload["sub"])
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(401, "Session expirée ou invalide")
    if not user or not user.active:
        raise HTTPException(401, "Compte désactivé")
    from .access_models import CollaboratorProfile
    profile = db.get(CollaboratorProfile, user.id)
    if profile is not None:
        valid_after = profile.sessions_valid_after
        if valid_after is not None:
            if valid_after.tzinfo is None:
                valid_after = valid_after.replace(tzinfo=timezone.utc)
            if int(payload.get("iat", 0)) < int(valid_after.timestamp()):
                raise HTTPException(401, "Session révoquée : veuillez vous reconnecter")
        # Mot de passe temporaire : seul son remplacement est possible.
        if profile.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
            raise HTTPException(403, "Changement du mot de passe temporaire obligatoire")
    return user


PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/logout", "/api/account/password"}

"""Collaborateurs et habilitations : API du chef et « Mon compte » du collaborateur.

Toutes les routes /api/admin/* exigent le rôle Administrateur. Aucun mot de
passe n'est stocké ni journalisé en clair : un mot de passe temporaire n'est
renvoyé qu'une seule fois, dans la réponse de création ou de réinitialisation.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .access_control import (ACTION_CATALOG, ACTION_LABELS, FOLDER_NAMES, FOLDERS, PRESETS,
                             access_mode, assignments_for, invalidate, is_admin, normalize_actions)
from .access_models import CollaboratorProfile, LaunchAssignment, LegacyAccessProposal, SCOPE_ASSIGNMENTS
from .core import COOKIE, check_password, get_current_user, get_db, hash_password, make_token, utcnow
from .models import AuditEvent, Launch, Role, User

router = APIRouter(tags=["Collaborateurs et habilitations"])

DEFAULT_ROLE = "Collaborateur"
MIN_PASSWORD = 12
PREF_KEYS = {
    "internal": ("Notifications internes", True),
    "email_future": ("Notifications email (intégration future, aucun envoi aujourd'hui)", False),
    "reminders": ("Rappels", True),
    "important_changes": ("Modifications importantes", True),
    "validation_requests": ("Demandes de validation", True),
    "new_assignments": ("Nouvelles affectations", True),
}


def deps():
    from .main import admin_only, audit
    return admin_only, audit


# --------------------------------------------------------------------------- utilitaires
def temporary_password() -> str:
    # 16 caractères aléatoires (≈ 96 bits) : transmis une seule fois au chef, à changer à la première connexion.
    return secrets.token_urlsafe(12)


def profile_for(db: Session, user: User) -> CollaboratorProfile:
    profile = db.get(CollaboratorProfile, user.id)
    if profile is None:
        profile = CollaboratorProfile(user_id=user.id, access_scope=SCOPE_ASSIGNMENTS, notification_prefs="{}")
        db.add(profile)
        db.flush()
    return profile


def prefs_of(profile: CollaboratorProfile | None) -> dict:
    stored = json.loads(profile.notification_prefs or "{}") if profile else {}
    return {key: bool(stored.get(key, default)) for key, (_, default) in PREF_KEYS.items()}


def default_role(db: Session) -> Role:
    role = db.scalar(select(Role).where(Role.name == DEFAULT_ROLE))
    if role is None:
        role = Role(name=DEFAULT_ROLE)
        db.add(role)
        db.flush()
    return role


def target_user(db: Session, user_id: str) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Collaborateur introuvable")
    return target


def target_launch(db: Session, launch_id: str) -> Launch:
    launch = db.get(Launch, launch_id)
    if launch is None:
        raise HTTPException(404, "Commande introuvable")
    return launch


def launch_label(launch: Launch) -> dict:
    return {"id": launch.id, "name": launch.name, "order_ref": launch.order_ref,
            "client_name": launch.client_name, "status": launch.status}


def rows_by_launch(db: Session, user_id: str) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for row in db.scalars(select(LaunchAssignment).where(LaunchAssignment.user_id == user_id)):
        actions = json.loads(row.actions or "[]")
        if actions:
            result.setdefault(row.launch_id, {})[row.folder_slug] = actions
    return result


def collaborator_out(db: Session, user: User, *, detail: bool = False) -> dict:
    profile = db.get(CollaboratorProfile, user.id)
    assigned = rows_by_launch(db, user.id)
    last = db.scalar(select(func.max(AuditEvent.occurred_at)).where(AuditEvent.actor_id == user.id))
    pending = db.scalar(select(func.count(LegacyAccessProposal.id)).where(
        LegacyAccessProposal.user_id == user.id, LegacyAccessProposal.status == "pending")) or 0
    out = {"id": user.id, "name": user.name, "email": user.email, "active": user.active,
           "admin": is_admin(user), "roles": [r.name for r in user.roles],
           "job_title": profile.job_title if profile else "", "access_mode": access_mode(user, db),
           "must_change_password": bool(profile and profile.must_change_password),
           "launches_count": len(assigned), "folders_count": sum(len(f) for f in assigned.values()),
           "last_activity": last.isoformat() if last else None, "legacy_pending": pending,
           "created_at": user.created_at.isoformat()}
    if detail:
        launches = {l.id: l for l in db.scalars(select(Launch).where(Launch.id.in_(list(assigned)))).all()} if assigned else {}
        out["assignments"] = [{"launch": launch_label(launches[lid]), "folders": folders}
                              for lid, folders in assigned.items() if lid in launches]
        out["preferences"] = prefs_of(profile)
    return out


def validate_folders(folders: dict) -> dict[str, list[str]]:
    if not isinstance(folders, dict):
        raise HTTPException(422, "Affectations invalides")
    clean = {}
    for slug, actions in folders.items():
        if slug not in FOLDERS:
            raise HTTPException(422, f"Sous-dossier inconnu : {slug}")
        normalized = normalize_actions(actions)
        if normalized:
            clean[slug] = normalized
    return clean


def set_assignments(db: Session, actor: User, target: User, launch: Launch,
                    folders: dict[str, list[str]], *, origin: str = "manual") -> int:
    """Remplace les affectations d'un collaborateur sur une commande ; audite chaque changement."""
    _, audit = deps()
    if is_admin(target):
        raise HTTPException(422, "Le chef dispose déjà de tous les accès : aucune affectation nécessaire")
    if not target.active and folders:
        raise HTTPException(422, "Compte désactivé : réactivez-le avant de lui affecter une commande")
    current = {row.folder_slug: row for row in db.scalars(select(LaunchAssignment).where(
        LaunchAssignment.user_id == target.id, LaunchAssignment.launch_id == launch.id))}
    changes = 0
    for slug in FOLDERS:
        wanted = folders.get(slug, [])
        row = current.get(slug)
        before = json.loads(row.actions or "[]") if row else []
        if wanted == before:
            continue
        changes += 1
        detail = {"user_id": target.id, "user": target.email, "launch_id": launch.id, "folder": slug,
                  "before": before, "after": wanted, "origin": origin}
        if not wanted:
            db.delete(row)
            audit(db, actor, "access.assignment.revoke", "launch", launch.id, detail)
        elif row is None:
            db.add(LaunchAssignment(launch_id=launch.id, user_id=target.id, folder_slug=slug,
                                    actions=json.dumps(wanted), granted_by=actor.id))
            audit(db, actor, "access.assignment.grant", "launch", launch.id, detail)
        else:
            row.actions, row.granted_by = json.dumps(wanted), actor.id
            audit(db, actor, "access.assignment.update", "launch", launch.id, detail)
    if changes:
        from .notification_events import assignments_changed, sync_assignment_action
        prefs = prefs_of(db.get(CollaboratorProfile, target.id))
        if prefs.get("internal", True) and prefs.get("new_assignments", True):
            assignments_changed(db, launch, target, folders, first=bool(folders and not current))
        sync_assignment_action(db, launch)
    invalidate()
    return changes


def notify_new_assignment(db: Session, target: User, launch: Launch, folders: dict):
    """Compatibilité : délègue au centre unifié avec une clé métier stable."""
    prefs = prefs_of(db.get(CollaboratorProfile, target.id))
    if not prefs.get("internal", True) or not prefs.get("new_assignments", True):
        return
    from .notification_events import assignments_changed
    assignments_changed(db, launch, target, folders, first=True)


# --------------------------------------------------------------------------- catalogue
@router.get("/api/admin/access/catalog")
def catalog(user: User = Depends(get_current_user)):
    admin_only, _ = deps(); admin_only(user)
    return {"folders": [{"slug": s, "label": FOLDER_NAMES[s]} for s in FOLDERS],
            "actions": [{"key": k, "label": l, "help": h} for k, l, h in ACTION_CATALOG],
            "presets": [{"key": k, **v} for k, v in PRESETS.items()],
            "preferences": [{"key": k, "label": l, "default": d} for k, (l, d) in PREF_KEYS.items()]}


# --------------------------------------------------------------------------- collaborateurs
class CollaboratorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    job_title: str = Field(default="", max_length=120)
    password: str | None = Field(default=None, min_length=MIN_PASSWORD, max_length=256)


class CollaboratorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    job_title: str | None = Field(default=None, max_length=120)
    active: bool | None = None


@router.get("/api/admin/collaborators")
def list_collaborators(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    return [collaborator_out(db, u) for u in db.scalars(select(User).order_by(User.name)).all()]


@router.post("/api/admin/collaborators", status_code=201)
def create_collaborator(payload: CollaboratorCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, audit = deps(); admin_only(user)
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "Email invalide")
    secret = payload.password or temporary_password()
    target = User(name=payload.name.strip(), email=email, password_hash=hash_password(secret), roles=[default_role(db)])
    db.add(target)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Un compte utilise déjà cette adresse")
    db.add(CollaboratorProfile(user_id=target.id, job_title=payload.job_title.strip(), access_scope=SCOPE_ASSIGNMENTS,
                               must_change_password=True, notification_prefs="{}"))
    audit(db, user, "user.create", "user", target.id,
          {"email": email, "job_title": payload.job_title.strip(), "temporary_password": "défini (non journalisé)"})
    db.commit()
    # Mot de passe temporaire renvoyé une seule fois ; jamais relisible ensuite.
    return {"collaborator": collaborator_out(db, target), "temporary_password": secret}


@router.get("/api/admin/collaborators/{user_id}")
def read_collaborator(user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    return collaborator_out(db, target_user(db, user_id), detail=True)


@router.patch("/api/admin/collaborators/{user_id}")
def update_collaborator(user_id: str, payload: CollaboratorPatch, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    admin_only, audit = deps(); admin_only(user)
    target = target_user(db, user_id)
    profile = profile_for(db, target)
    changes = {}
    if payload.name is not None and payload.name.strip() != target.name:
        changes["name"] = [target.name, payload.name.strip()]; target.name = payload.name.strip()
    if payload.email is not None and payload.email.strip().lower() != target.email:
        email = payload.email.strip().lower()
        if "@" not in email:
            raise HTTPException(422, "Email invalide")
        changes["email"] = [target.email, email]; target.email = email
    if payload.job_title is not None and payload.job_title.strip() != profile.job_title:
        changes["job_title"] = [profile.job_title, payload.job_title.strip()]; profile.job_title = payload.job_title.strip()
    if payload.active is not None and payload.active != target.active:
        if target.id == user.id and not payload.active:
            raise HTTPException(422, "Vous ne pouvez pas désactiver votre propre compte")
        if is_admin(target) and not payload.active:
            others = [u for u in db.scalars(select(User).where(User.active.is_(True), User.id != target.id)) if is_admin(u)]
            if not others:
                raise HTTPException(422, "Impossible de désactiver le dernier compte administrateur")
        changes["active"] = [target.active, payload.active]; target.active = payload.active
        if not payload.active:
            profile.sessions_valid_after = utcnow()        # effet immédiat, même pour une session ouverte
    if not changes:
        return collaborator_out(db, target, detail=True)
    action = ("user.deactivate" if changes.get("active") == [True, False] else
              "user.activate" if changes.get("active") == [False, True] else "user.update")
    audit(db, user, action, "user", target.id, changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Un compte utilise déjà cette adresse")
    return collaborator_out(db, target, detail=True)


@router.post("/api/admin/collaborators/{user_id}/reset-password")
def reset_password(user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, audit = deps(); admin_only(user)
    target = target_user(db, user_id)
    if target.id == user.id:
        raise HTTPException(422, "Changez votre propre mot de passe depuis « Mon compte »")
    secret = temporary_password()
    target.password_hash = hash_password(secret)
    profile = profile_for(db, target)
    profile.must_change_password = True
    profile.sessions_valid_after = utcnow()
    audit(db, user, "user.password.reset", "user", target.id, {"sessions_revoked": True})
    db.commit()
    return {"collaborator": collaborator_out(db, target), "temporary_password": secret}


@router.post("/api/admin/collaborators/{user_id}/revoke-sessions")
def revoke_sessions(user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, audit = deps(); admin_only(user)
    target = target_user(db, user_id)
    if target.id == user.id:
        raise HTTPException(422, "Utilisez « Déconnexion » pour votre propre session")
    profile_for(db, target).sessions_valid_after = utcnow()
    audit(db, user, "user.sessions.revoke", "user", target.id, {})
    db.commit()
    return {"ok": True}


@router.get("/api/admin/collaborators/{user_id}/history")
def collaborator_history(user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    target = target_user(db, user_id)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.action.like("user.%") | AuditEvent.action.like("access.%"))
                      .order_by(AuditEvent.occurred_at.desc()).limit(500)).all()
    items = []
    for row in rows:
        detail = json.loads(row.detail or "{}")
        if row.target_id != target.id and detail.get("user_id") != target.id:
            continue
        actor = db.get(User, row.actor_id) if row.actor_id else None
        items.append({"action": row.action, "at": row.occurred_at.isoformat(), "actor": actor.name if actor else None,
                      "target_type": row.target_type, "target_id": row.target_id, "detail": detail})
    return items[:200]


# --------------------------------------------------------------------------- affectations
class FoldersPayload(BaseModel):
    folders: dict[str, list[str]] = Field(default_factory=dict)


class LaunchAssignmentsPayload(BaseModel):
    assignments: list[dict] = Field(default_factory=list)   # [{user_id, folders: {slug: [actions]}}]


class BulkPayload(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=50)
    launch_ids: list[str] = Field(min_length=1, max_length=100)
    folders: dict[str, list[str]]


@router.get("/api/admin/collaborators/{user_id}/assignments")
def collaborator_assignments(user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    target = target_user(db, user_id)
    assigned = rows_by_launch(db, target.id)
    launches = db.scalars(select(Launch).order_by(Launch.updated_at.desc())).all()
    return {"collaborator": collaborator_out(db, target),
            "launches": [{"launch": launch_label(l), "folders": assigned.get(l.id, {})} for l in launches]}


@router.put("/api/admin/collaborators/{user_id}/assignments/{launch_id}")
def put_collaborator_assignment(user_id: str, launch_id: str, payload: FoldersPayload,
                                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    target, launch = target_user(db, user_id), target_launch(db, launch_id)
    set_assignments(db, user, target, launch, validate_folders(payload.folders))
    db.commit()
    return {"launch": launch_label(launch), "folders": rows_by_launch(db, target.id).get(launch.id, {})}


def launch_matrix(db: Session, launch: Launch) -> dict:
    rows = db.scalars(select(LaunchAssignment).where(LaunchAssignment.launch_id == launch.id)).all()
    by_user: dict[str, dict] = {}
    for row in rows:
        actions = json.loads(row.actions or "[]")
        if actions:
            by_user.setdefault(row.user_id, {})[row.folder_slug] = actions
    people = []
    for u in db.scalars(select(User).order_by(User.name)).all():
        if is_admin(u) or (not u.active and u.id not in by_user):
            continue
        profile = db.get(CollaboratorProfile, u.id)
        people.append({"id": u.id, "name": u.name, "email": u.email, "active": u.active,
                       "job_title": profile.job_title if profile else "", "folders": by_user.get(u.id, {})})
    covered = {slug: [p["id"] for p in people if slug in p["folders"]] for slug in FOLDERS}
    return {"launch": launch_label(launch), "collaborators": people, "coverage": covered,
            "managed_by_chef_only": not by_user}


@router.get("/api/admin/launches/{launch_id}/assignments")
def read_launch_assignments(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    return launch_matrix(db, target_launch(db, launch_id))


@router.put("/api/admin/launches/{launch_id}/assignments")
def put_launch_assignments(launch_id: str, payload: LaunchAssignmentsPayload,
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Enregistre la matrice : seuls les collaborateurs envoyés sont modifiés."""
    admin_only, _ = deps(); admin_only(user)
    launch = target_launch(db, launch_id)
    for entry in payload.assignments:
        set_assignments(db, user, target_user(db, str(entry.get("user_id", ""))), launch,
                        validate_folders(entry.get("folders") or {}))
    db.commit()
    return launch_matrix(db, launch)


@router.get("/api/admin/launches/{launch_id}/assignments/copy-from/{source_id}")
def copy_proposal(launch_id: str, source_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Proposition seulement : la matrice de la commande source, à confirmer par le chef."""
    admin_only, _ = deps(); admin_only(user)
    target_launch(db, launch_id)
    source = launch_matrix(db, target_launch(db, source_id))
    return {"source": source["launch"], "proposal": [{"user_id": p["id"], "folders": p["folders"]}
                                                    for p in source["collaborators"] if p["folders"] and p["active"]]}


@router.post("/api/admin/assignments/bulk")
def bulk_assign(payload: BulkPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Affectation collective : ajoute les actions demandées (sans retirer les droits existants)."""
    admin_only, _ = deps(); admin_only(user)
    wanted = validate_folders(payload.folders)
    if not wanted:
        raise HTTPException(422, "Choisissez au moins un sous-dossier et une action")
    changes = 0
    for uid in dict.fromkeys(payload.user_ids):
        target = target_user(db, uid)
        current = rows_by_launch(db, target.id)
        for lid in dict.fromkeys(payload.launch_ids):
            launch = target_launch(db, lid)
            merged = {slug: normalize_actions(current.get(launch.id, {}).get(slug, []) + wanted.get(slug, []))
                      for slug in FOLDERS}
            changes += set_assignments(db, user, target, launch, {k: v for k, v in merged.items() if v}, origin="bulk")
    db.commit()
    return {"changes": changes}


# --------------------------------------------------------------------------- vision globale
@router.get("/api/admin/access/overview")
def overview(launch_id: str = "", user_id: str = "", folder: str = "",
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    users = {u.id: u for u in db.scalars(select(User)).all()}
    collaborators = [u for u in users.values() if not is_admin(u)]
    launches = db.scalars(select(Launch).order_by(Launch.updated_at.desc())).all()
    rows = db.scalars(select(LaunchAssignment)).all()
    matrix: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        if json.loads(row.actions or "[]") and users.get(row.user_id) and users[row.user_id].active:
            matrix.setdefault(row.launch_id, {}).setdefault(row.folder_slug, []).append(row.user_id)
    pending = pending_validations(db)
    table = []
    for l in launches:
        if launch_id and l.id != launch_id:
            continue
        folders = matrix.get(l.id, {})
        if user_id and not any(user_id in ids for ids in folders.values()):
            continue
        cells = {slug: [{"id": uid, "name": users[uid].name} for uid in folders.get(slug, [])] for slug in FOLDERS}
        if folder and not cells[folder]:
            continue
        table.append({"launch": launch_label(l), "folders": cells, "chef_only": not folders,
                      "unassigned_folders": [s for s in FOLDERS if not cells[s]],
                      "pending_validation": pending.get(l.id, {})})
    return {"kpis": {"active_collaborators": sum(u.active for u in collaborators),
                     "inactive_collaborators": sum(not u.active for u in collaborators),
                     "launches": len(launches), "launches_assigned": len(matrix),
                     "launches_chef_only": sum(1 for l in launches if l.id not in matrix),
                     "assigned_folders": sum(len(f) for f in matrix.values()),
                     "unassigned_folders": sum(4 - len(matrix.get(l.id, {})) for l in launches),
                     "legacy_pending": db.scalar(select(func.count(LegacyAccessProposal.id)).where(
                         LegacyAccessProposal.status == "pending")) or 0},
            "by_collaborator": [{"id": u.id, "name": u.name, "active": u.active,
                                 "launches": sum(1 for f in matrix.values() if any(u.id in ids for ids in f.values())),
                                 "folders": sum(1 for f in matrix.values() for ids in f.values() if u.id in ids)}
                                for u in sorted(collaborators, key=lambda x: x.name)],
            "launches": table}


def pending_validations(db: Session) -> dict[str, dict[str, int]]:
    """Pièces en attente de validation par commande et sous-dossier (moteur de complétude existant)."""
    from .completeness import evaluate
    from .main import permitted
    chef = next((u for u in db.scalars(select(User).where(User.active.is_(True))) if is_admin(u)), None)
    if chef is None:
        return {}
    result = {}
    for launch in db.scalars(select(Launch)).all():
        report = evaluate(db, launch, chef, permitted)
        counts = {}
        for row in report["rows"]:
            if row["status"] == "pending_validation":
                counts[row["folder"]] = counts.get(row["folder"], 0) + 1
        if counts:
            result[launch.id] = counts
    return result


# --------------------------------------------------------------------------- droits hérités
@router.get("/api/admin/access/legacy")
def legacy_proposals(status: str = "pending", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    out = []
    for p in db.scalars(select(LegacyAccessProposal).where(LegacyAccessProposal.status == status)
                        .order_by(LegacyAccessProposal.created_at)).all():
        u, l = db.get(User, p.user_id), db.get(Launch, p.launch_id)
        if u and l:
            out.append({"id": p.id, "origin": p.origin, "status": p.status, "folders": json.loads(p.folders or "{}"),
                        "collaborator": {"id": u.id, "name": u.name, "email": u.email, "active": u.active},
                        "launch": launch_label(l)})
    return out


@router.post("/api/admin/access/legacy/{proposal_id}/{decision}")
def decide_legacy(proposal_id: str, decision: str, payload: FoldersPayload | None = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, audit = deps(); admin_only(user)
    if decision not in {"apply", "dismiss"}:
        raise HTTPException(404, "Décision inconnue")
    proposal = db.get(LegacyAccessProposal, proposal_id)
    if proposal is None or proposal.status != "pending":
        raise HTTPException(404, "Proposition introuvable ou déjà traitée")
    if decision == "apply":
        folders = validate_folders(payload.folders if payload and payload.folders else json.loads(proposal.folders or "{}"))
        if not folders:
            raise HTTPException(422, "Aucun sous-dossier à appliquer : choisissez-les ou écartez la proposition")
        set_assignments(db, user, target_user(db, proposal.user_id), target_launch(db, proposal.launch_id), folders, origin="legacy")
    proposal.status = "applied" if decision == "apply" else "dismissed"
    proposal.decided_by, proposal.decided_at = user.id, utcnow()
    audit(db, user, f"access.legacy.{decision}", "launch", proposal.launch_id, {"user_id": proposal.user_id, "proposal": proposal.id})
    db.commit()
    return {"ok": True, "status": proposal.status}


# --------------------------------------------------------------------------- destinataires (préparation emails)
@router.get("/api/admin/access/recipients")
def preview_recipients(launch_id: str, event: str, folders: list[str] = Query(default=[]),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_only, _ = deps(); admin_only(user)
    from .access_notifications import recipients
    target_launch(db, launch_id)
    return recipients(db, launch_id=launch_id, folders=folders or list(FOLDERS), event_type=event)


# --------------------------------------------------------------------------- Mon compte
class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=256)


class PreferencesPayload(BaseModel):
    preferences: dict[str, bool]


@router.get("/api/account")
def my_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.get(CollaboratorProfile, user.id)
    assigned = {} if is_admin(user) else rows_by_launch(db, user.id)
    launches = {l.id: l for l in db.scalars(select(Launch).where(Launch.id.in_(list(assigned)))).all()} if assigned else {}
    return {"id": user.id, "name": user.name, "email": user.email, "admin": is_admin(user),
            "job_title": profile.job_title if profile else "", "access_mode": access_mode(user, db),
            "must_change_password": bool(profile and profile.must_change_password),
            "preferences": prefs_of(profile),
            "preference_labels": {k: l for k, (l, _) in PREF_KEYS.items()},
            "action_labels": ACTION_LABELS,
            "assignments": [{"launch": launch_label(launches[lid]), "folders": folders}
                            for lid, folders in assigned.items() if lid in launches]}


@router.post("/api/account/password")
def change_password(payload: PasswordChange, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from .main import audit
    import os
    if not check_password(user.password_hash, payload.current_password):
        raise HTTPException(422, "Mot de passe actuel incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(422, "Choisissez un mot de passe différent du mot de passe temporaire")
    user.password_hash = hash_password(payload.new_password)
    profile = profile_for(db, user)
    profile.must_change_password = False
    profile.password_changed_at = utcnow()
    # Les autres sessions sont fermées ; la session courante reçoit un nouveau jeton.
    profile.sessions_valid_after = datetime.now(timezone.utc).replace(microsecond=0)
    audit(db, user, "user.password.change", "user", user.id, {"sessions_revoked": True})
    db.commit()
    response.set_cookie(COOKIE, make_token(user.id), max_age=8 * 3600, httponly=True,
                        secure=os.getenv("FRAMATEX_COOKIE_SECURE") == "1", samesite="strict", path="/")
    return {"ok": True}


@router.put("/api/account/preferences")
def update_preferences(payload: PreferencesPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import audit
    profile = profile_for(db, user)
    prefs = prefs_of(profile)
    for key, value in payload.preferences.items():
        if key in PREF_KEYS:
            prefs[key] = bool(value)
    profile.notification_prefs = json.dumps(prefs)
    audit(db, user, "user.preferences.update", "user", user.id, prefs)
    db.commit()
    return {"preferences": prefs}

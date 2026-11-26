"""Fiche commande complète du Dossier Jaune (modèle de la tutrice FRAMATEX).

Réutilise Launch (nom, N° commande FRAMATEX, client) et LaunchOperations (article, quantité
commandée, responsable) ; les autres champs sont des colonnes additives (0016_order_sheet).
Toutes les valeurs sont facultatives sauf le nom : NULL = « non renseigné », jamais zéro.
Le N° client est le client_code du compte Client explicitement rattaché (aucune identité inventée).
Chaque modification est journalisée avec l'ancienne et la nouvelle valeur.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .access import must_access
from .client_models import ClientAccount
from .core import get_current_user, get_db, utcnow
from .internal_models import LaunchOperations
from .models import User

router = APIRouter()

LAUNCH_FIELDS = ("name", "order_ref", "client_name", "orli_ref")
SHEET_FIELDS = ("description", "workshop", "article", "color", "quantity", "of_number", "quantity_launched",
                "quantity_delivered", "invoice_ref", "desired_date", "client_order_ref", "client_account_id")
LABELS = {"name": "Nom de la commande / projet", "description": "Description", "workshop": "Atelier",
          "client_name": "Client", "article": "Article", "order_ref": "N° commande", "color": "Couleur",
          "quantity": "Quantité commandée", "of_number": "N° OF", "quantity_launched": "Quantité lancée",
          "quantity_delivered": "Quantité livrée", "invoice_ref": "Référence / N° facture",
          "client_account_id": "N° client", "desired_date": "Date de livraison souhaitée",
          "client_order_ref": "Référence de commande Client", "orli_ref": "Référence ORLI"}


class SheetIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    order_ref: str | None = Field(default=None, max_length=100)
    client_name: str | None = Field(default=None, max_length=150)
    orli_ref: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    workshop: str | None = Field(default=None, max_length=150)
    article: str | None = Field(default=None, max_length=180)
    color: str | None = Field(default=None, max_length=80)
    quantity: int | None = Field(default=None, gt=0, le=10_000_000)
    of_number: str | None = Field(default=None, max_length=60)
    quantity_launched: int | None = Field(default=None, ge=0, le=10_000_000)
    quantity_delivered: int | None = Field(default=None, ge=0, le=10_000_000)
    invoice_ref: str | None = Field(default=None, max_length=100)
    desired_date: date | None = None
    client_order_ref: str | None = Field(default=None, max_length=100)
    client_account_id: str | None = Field(default=None, max_length=36)


class SheetCreate(SheetIn):
    name: str = Field(min_length=2, max_length=180)


def _deps():
    from .main import audit, must, permitted
    return audit, must, permitted


def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _plain(value):
    return value.isoformat() if isinstance(value, date) else value


def sheet_out(db: Session, user: User, launch) -> dict:
    _, _, permitted = _deps()
    from .access_control import can
    ops = db.get(LaunchOperations, launch.id)
    values = {field: getattr(launch, field) for field in LAUNCH_FIELDS}
    values.update({field: _plain(getattr(ops, field)) if ops else None for field in SHEET_FIELDS})
    account = db.get(ClientAccount, ops.client_account_id) if ops and ops.client_account_id else None
    values["client_account"] = ({"id": account.id, "client_code": account.client_code, "raison_sociale": account.raison_sociale}
                                if account else None)
    return {"launch_id": launch.id, "values": values, "labels": LABELS,
            "can_edit": bool(can(user, "launch.update", None, launch.id))}


def apply_sheet(db: Session, user: User, launch, values: dict) -> dict:
    """Applique les valeurs fournies et renvoie {champ: {before, after}} pour les seuls changements."""
    if values.get("client_account_id"):
        if not db.get(ClientAccount, values["client_account_id"]):
            raise HTTPException(422, "Compte Client introuvable : le N° client doit correspondre à un compte existant")
    ops = db.get(LaunchOperations, launch.id)
    if ops is None:
        ops = LaunchOperations(launch_id=launch.id)
        db.add(ops)
    changes = {}
    for field, raw in values.items():
        value = _clean(raw)
        if field == "name" and not value:
            raise HTTPException(422, "Le nom de la commande est obligatoire")
        target = launch if field in LAUNCH_FIELDS else ops
        before = getattr(target, field)
        if before != value:
            setattr(target, field, value)
            changes[field] = {"before": _plain(before), "after": _plain(value)}
    if changes:
        launch.updated_at = utcnow()
    return changes


@router.get("/api/launches/{launch_id}/sheet")
def read_sheet(launch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, must, _ = _deps()
    must(user, "launch.read")
    return sheet_out(db, user, must_access(db, user, launch_id))


@router.patch("/api/launches/{launch_id}/sheet")
def update_sheet(launch_id: str, payload: SheetIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit, must, _ = _deps()
    must(user, "launch.read")
    launch = must_access(db, user, launch_id)
    must(user, "launch.update")
    changes = apply_sheet(db, user, launch, payload.model_dump(exclude_unset=True))
    if changes:
        audit(db, user, "launch.sheet.update", "launch", launch.id, {"changes": changes})
    db.commit()
    return {**sheet_out(db, user, launch), "changes": changes}


@router.post("/api/order-sheets", status_code=201)
def create_with_sheet(payload: SheetCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                      idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    """Création d'un Dossier Jaune avec sa fiche complète, en une seule transaction (idempotente)."""
    from .idempotency import check_key, commit_or_replay, remember, replay
    audit, must, _ = _deps()
    must(user, "launch.create")
    key = check_key(idempotency_key)
    previous = replay(db, user, "order-sheet.create", key)
    if previous is not None:
        return previous
    import os
    from .main import FOLDERS
    from .models import Folder, Launch
    launch = Launch(name=payload.name.strip(), created_by=user.id,
                    restricted=os.getenv("FRAMATEX_RESTRICT_NEW_LAUNCHES", "0") == "1")
    db.add(launch)
    db.flush()
    for slug, label in FOLDERS:
        db.add(Folder(launch_id=launch.id, slug=slug, label=label))
    values = payload.model_dump(exclude_unset=True)
    changes = apply_sheet(db, user, launch, values)
    audit(db, user, "launch.create", "launch", launch.id, {"name": launch.name, "orli": None,
          "sheet": {field: change["after"] for field, change in changes.items() if field != "name"}})
    from .main import launch_out
    created = launch_out(launch)
    remember(db, user, "order-sheet.create", key, created)
    return commit_or_replay(db, user, "order-sheet.create", key) or created

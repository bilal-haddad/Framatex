"""Idempotence des créations sensibles (en-tête `Idempotency-Key`, facultatif).

Une même clé, pour un même utilisateur et une même opération, renvoie la réponse déjà produite au lieu
de créer un second élément. Deux requêtes simultanées portant la même clé : la seconde échoue sur la
contrainte d'unicité, sa transaction est annulée et la réponse de la première est renvoyée. Les clés
expirent après 24 heures."""
from __future__ import annotations

import json
import re
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .core import utcnow
from .models import IdempotencyKey

KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")
TTL = timedelta(hours=24)


def check_key(key: str | None) -> str | None:
    if key is None or key == "":
        return None
    if not KEY.match(key):
        raise HTTPException(422, "Clé d'idempotence invalide")
    return key


def replay(db, user, scope: str, key: str | None):
    if not key:
        return None
    row = db.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == user.id, IdempotencyKey.scope == scope,
                                                 IdempotencyKey.key == key, IdempotencyKey.created_at >= utcnow() - TTL))
    return json.loads(row.response) if row else None


def remember(db, user, scope: str, key: str | None, response: dict):
    """À appeler avant le commit de la création : la clé et l'élément sont validés ensemble."""
    if key:
        db.add(IdempotencyKey(user_id=user.id, scope=scope, key=key, response=json.dumps(response, default=str)))


def commit_or_replay(db, user, scope: str, key: str | None):
    """Valide la transaction ; en cas de course sur la même clé, renvoie la réponse déjà enregistrée."""
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        previous = replay(db, user, scope, key)
        if previous is None:
            raise HTTPException(409, "Opération déjà en cours de traitement : réessayez dans un instant")
        return previous


def purge_expired(db):
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < utcnow() - TTL))
    db.commit()

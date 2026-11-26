"""Supervision technique (destinée au responsable informatique, jamais affichée dans les écrans métier).

- Identifiant de requête : `X-Request-ID` repris s'il est fourni par le proxy (format sûr), sinon créé ;
  renvoyé dans la réponse et présent dans chaque ligne de journal.
- Journal d'accès structuré (JSON, logger `framatex.access`) : méthode, gabarit de route (jamais la
  chaîne de requête ni de données personnelles), statut, durée, identifiant de processus.
- `/api/health` (existant) : vivant ; `/api/health/ready` : base joignable et à jour, stockage
  accessible et espace disque, file d'effacement, OCR disponible.
- `/metrics` (format Prometheus) : compteurs et histogrammes de durée par route, uniquement si
  `FRAMATEX_METRICS_TOKEN` est défini et présenté en en-tête `Authorization: Bearer …`.
  Les compteurs sont propres à chaque processus (agrégation par Prometheus).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(tags=["Supervision"])
access_log = logging.getLogger("framatex.access")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
_lock = threading.Lock()
_metrics: dict[tuple[str, str, str], list] = {}            # (méthode, route, classe de statut) -> [n, somme, buckets…]


def _route(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or ("/assets" if request.url.path.startswith("/assets/") else "autre")


def _record(method, route, status, seconds):
    key = (method, route, f"{status // 100}xx")
    with _lock:
        row = _metrics.setdefault(key, [0, 0.0] + [0] * len(BUCKETS))
        row[0] += 1; row[1] += seconds
        for index, bound in enumerate(BUCKETS):
            if seconds <= bound:
                row[2 + index] += 1


async def request_observability(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if SAFE_ID.match(incoming) else secrets.token_hex(8)
    request.state.request_id = request_id
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        elapsed = time.perf_counter() - started
        route = _route(request)
        _record(request.method, route, status, elapsed)
        if route != "/assets" and (request.url.path.startswith("/api/") or status >= 500):
            access_log.info(json.dumps({"request_id": request_id, "method": request.method, "route": route,
                                        "status": status, "ms": round(elapsed * 1000, 1), "pid": os.getpid()}))


@router.get("/api/health/ready")
def ready():
    """Prêt à servir : sans chemin, ni secret, ni donnée métier."""
    from sqlalchemy import text
    from .core import SessionLocal
    from .main import STORAGE
    from .migrate import REVISIONS
    checks, ok = {}, True
    try:
        with SessionLocal() as db:
            applied = {row[0] for row in db.execute(text("SELECT version FROM schema_migrations"))}
            checks["database"] = "ok" if set(REVISIONS) <= applied else "migrations en attente"
            pending = db.execute(text("SELECT COUNT(*) FROM storage_purge_queue WHERE done_at IS NULL")).scalar()
            checks["purge_queue_pending"] = pending
    except Exception as exc:                                    # base indisponible ou verrouillée
        checks["database"] = f"indisponible ({exc.__class__.__name__})"
    ok = ok and checks.get("database") == "ok"
    usage = shutil.disk_usage(STORAGE)
    checks["storage_writable"] = os.access(STORAGE, os.W_OK)
    checks["disk_free_percent"] = round(100 * usage.free / usage.total, 1)
    ok = ok and checks["storage_writable"] and checks["disk_free_percent"] >= 5
    checks["ocr"] = "ok" if shutil.which("tesseract") else "indisponible (lecture des PDF texte seulement)"
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    token = os.getenv("FRAMATEX_METRICS_TOKEN", "")
    given = request.headers.get("Authorization", "")
    if not token or not secrets.compare_digest(given, f"Bearer {token}"):
        return PlainTextResponse("Not Found", status_code=404)
    lines = ["# TYPE framatex_http_requests_total counter", "# TYPE framatex_http_request_seconds histogram"]
    with _lock:
        rows = {key: list(value) for key, value in _metrics.items()}
    for (method, route, status), row in sorted(rows.items()):
        labels = f'method="{method}",route="{route}",status="{status}"'
        lines.append(f"framatex_http_requests_total{{{labels}}} {row[0]}")
        for index, bound in enumerate(BUCKETS):
            lines.append(f'framatex_http_request_seconds_bucket{{{labels},le="{bound}"}} {row[2 + index]}')
        lines.append(f'framatex_http_request_seconds_bucket{{{labels},le="+Inf"}} {row[0]}')
        lines.append(f"framatex_http_request_seconds_sum{{{labels}}} {row[1]:.4f}")
        lines.append(f"framatex_http_request_seconds_count{{{labels}}} {row[0]}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

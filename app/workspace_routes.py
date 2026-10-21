"""MVP 0.9 — priorités métier explicables et assistant de navigation à règles fixes.

Pas d'IA générative, de chargement de contenu de fichiers ni d'accès aux données
sans les permissions que le serveur vérifie déjà. Les actions sont des liens internes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import get_db, get_current_user
from .models import DocumentVersion, Launch, User
from .completeness import evaluate
from .workflow_models import ImpactAlert, ImpactRule
from .spec_models import ClientRequirement, SpecificationAmbiguity
from .mail_models import EmailCommitment
from .spec_routes import _req_output, _amb_output

router = APIRouter(tags=["0.9 — Pilotage et aide"])


def deps():
    from .main import must, permitted
    return must, permitted


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in value if not unicodedata.combining(c))


def _source_folder(db: Session, version_id: str | None) -> str | None:
    version = db.get(DocumentVersion, version_id) if version_id else None
    return version.document.folder.slug if version else None


def _add(out: list, launch: Launch, *, kind: str, title: str, description: str, rank: int,
         area: str, action: str, item_id: str, deadline: str | None = None,
         folder: str | None = None, document_id: str | None = None, version_id: str | None = None):
    out.append({"id": f"{kind}:{item_id}", "launch_id": launch.id,
                "launch_name": launch.name, "kind": kind, "title": title,
                "description": description, "rank": rank,
                "priority": ("urgent" if rank == 0 else "high" if rank == 1 else "normal"),
                "priority_reason": ("Échéance dépassée" if rank == 0 else
                    "Vérification documentaire ou métier requise" if rank == 1 else
                    "Action à suivre"),
                "area": area, "action": action, "deadline": deadline,
                "folder": folder, "document_id": document_id, "version_id": version_id})


@router.get("/api/workspace/priorities")
def priorities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Liste consolidée, seulement des éléments dont les sources sont lisibles.

    Priorités déterministes : 0 échéance dépassée, 1 anomalie/action à traiter,
    2 engagement à échéance future proche. Pas de score arbitraire ni d'automatisation.
    """
    must, permitted = deps()
    must(user, "launch.read")
    today = datetime.now(ZoneInfo("Africa/Casablanca")).date()
    horizon = today + timedelta(days=7)
    from .access import visible
    launches = visible(db, user, db.scalars(select(Launch).order_by(Launch.created_at.desc())).all())
    items = []
    visible_launches = [l for l in launches if l.status != "Clôturé"]
    for launch in visible_launches:
        report = evaluate(db, launch, user, permitted)
        for row in report.get("rows", []):
            if row["status"] not in ("missing", "pending_validation"):
                continue
            kind = "missing" if row["status"] == "missing" else "validation"
            _add(items, launch, kind=kind,
                 title=("Pièce manquante : " if kind == "missing" else "Validation à obtenir : ") + row["title"],
                 description=f"Sous-dossier {row['folder'].capitalize()} · {row['document_type']}",
                 rank=1, area="documents", action="open_launch", item_id=row["id"],
                 folder=row["folder"], document_id=row["documents"][0]["id"] if row["documents"] else None)
        alerts = db.scalars(select(ImpactAlert).where(ImpactAlert.launch_id == launch.id,
                                                      ImpactAlert.status.in_(["to_review", "action_required"]))).all()
        for alert in alerts:
            rule = db.get(ImpactRule, alert.rule_id)
            if not rule or not (permitted(user,"document.read",rule.source_folder)
                                and permitted(user,"document.read",rule.target_folder)):
                continue
            _add(items, launch, kind="impact", title="Modification à examiner : " + rule.name,
                 description=rule.instruction[:210], rank=1, area="workflow",
                 action="open_launch", item_id=alert.id, folder=rule.target_folder,
                 version_id=alert.source_ref_id if rule.source_kind == "document" else None)
        for req in db.scalars(select(ClientRequirement).where(ClientRequirement.launch_id == launch.id)).all():
            source_folder = _source_folder(db, req.source_version_id)
            evidence_folder = _source_folder(db, req.evidence_version_id)
            if not source_folder or not permitted(user,"document.read",source_folder):
                continue
            if req.evidence_version_id and (not evidence_folder or not permitted(user,"document.read",evidence_folder)):
                continue
            state = _req_output(db, req, user)["state"]
            if state == "verified":
                continue
            _add(items, launch, kind="requirement", title="Exigence à vérifier : " + req.title,
                 description={"uncovered":"Justificatif absent", "to_verify":"Preuve à examiner",
                              "source_changed":"Document source modifié", "evidence_changed":"Preuve remplacée"}.get(state,"À examiner"),
                 rank=1, area="spec", action="open_launch", item_id=req.id)
        for amb in db.scalars(select(SpecificationAmbiguity).where(SpecificationAmbiguity.launch_id == launch.id)).all():
            source_folder = _source_folder(db, amb.source_version_id)
            clarification_folder = _source_folder(db, amb.clarification_version_id)
            if not source_folder or not permitted(user,"document.read",source_folder):
                continue
            if amb.clarification_version_id and (not clarification_folder or not permitted(user,"document.read",clarification_folder)):
                continue
            state = _amb_output(db,amb,user)["status"]
            if state not in ("open", "source_changed"):
                continue
            _add(items, launch, kind="ambiguity", title="Clarification requise",
                 description=amb.question[:210], rank=1, area="spec", action="open_launch", item_id=amb.id)
        if permitted(user,"document.read","rose"):
            for commitment in db.scalars(select(EmailCommitment).where(
                    EmailCommitment.launch_id == launch.id,
                    EmailCommitment.status.in_(["pending", "postponed"]))).all():
                if not commitment.due_date:
                    continue  # Date inconnue : ne pas inventer d'urgence.
                try:
                    due = datetime.strptime(commitment.due_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if due > horizon:
                    continue
                overdue = due < today
                _add(items, launch, kind="commitment", title=commitment.description[:120],
                     description=f"Engagement {('en retard' if overdue else 'à suivre')} · {commitment.responsible[:100]}",
                     rank=0 if overdue else 2, area="mail", action="open_launch",
                     item_id=commitment.id, deadline=commitment.due_date)
    from .internal_service import extra_actions
    items.extend(extra_actions(db, user, visible_launches))
    items.sort(key=lambda row: (row["rank"], row["deadline"] or "9999-12-31",
                                row["launch_name"].casefold(),row["id"]))
    counts = {"urgent":sum(i["priority"] == "urgent" for i in items),
              "high":sum(i["priority"] == "high" for i in items),
              "normal":sum(i["priority"] == "normal" for i in items)}
    return {"total":len(items), "counts":counts, "items":items[:100],
            "truncated":len(items)>100,"launches_considered":len(visible_launches),
            "method":"Urgent : engagement dépassé ; prioritaire : écart ou vérification ; à suivre : échéance dans 7 jours.",
            "as_of":today.isoformat()}


class GuideRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    launch_id: str | None = Field(default=None, max_length=36)


GUIDES = (
    ("mail", ("email", "courriel", "engagement", "messagerie"), "Emails et engagements",
     "Ouvrez le dossier de lancement, puis la rubrique Emails et engagements. Importez un .eml dans le dossier Rose ; toute proposition d'engagement doit être confirmée.", "document.read", "rose"),
    ("spec", ("exigence", "ambiguite", "clarification", "specification", "client technique"), "Exigences et clarifications",
     "Ouvrez le dossier de lancement, puis Exigences et clarifications. La présence d'une preuve ne vaut pas validation automatique.", "document.read", "jaune"),
    ("workflow", ("validation", "impact", "modification", "historique", "version"), "Versions et décisions",
     "Ouvrez le dossier concerné, puis Versions et décisions pour examiner les changements et leur prise en compte.", "document.read", None),
    ("documents", ("deposer", "depot", "ajouter un document", "facture", "bon de livraison", "qr code", "scanner", "document"), "Dépôt et recherche documentaire",
     "Dans Dossiers jaunes, ouvrez un lancement et choisissez son sous-dossier : Jaune (technique), Rose (réception), Bleu (douane), Vert (facturation). Le QR code ne donne jamais d'accès sans connexion.", "document.read", None),
    ("priorities", ("priorite", "urgence", "tache", "action", "tableau de bord", "retard"), "Actions prioritaires",
     "La vue d'ensemble présente les actions issues des règles documentaires, alertes de modification, exigences, ambiguïtés et échéances d'engagement. Les priorités ne sont pas des décisions automatiques.", "launch.read", None),
    ("launches", ("creer un dossier", "ouvrir un dossier", "lancement", "orli", "commande"), "Dossiers de lancement",
     "Dans Dossiers jaunes, créez un lancement même sans numéro ORLI. Son identifiant interne est indépendant de l'ERP.", "launch.read", None),
    ("admin", ("role", "utilisateur", "permission", "habilitation", "administration"), "Administration",
     "La rubrique Administration permet de gérer les comptes et les rôles ; seuls les administrateurs peuvent y accéder.", "admin", None),
)

@router.post("/api/assistant/guide")
def guide(payload: GuideRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Réponses prévalidées, sans IA et sans lecture du contenu des documents."""
    must, permitted = deps()
    must(user, "launch.read")
    launch = None
    if payload.launch_id:
        from .access import must_access
        launch = must_access(db, user, payload.launch_id)
    phrase = _normalize(payload.question)
    hits = [g for g in GUIDES if any(term in phrase for term in g[1])]
    for area, _, title, answer, permission, folder in hits:
        if permission == "admin":
            from .main import is_admin
            if not is_admin(user):
                continue
        elif folder:
            if not permitted(user, permission, folder):
                continue
        elif permission == "document.read":
            if not any(permitted(user, "document.read", slug) for slug in ("jaune", "rose", "bleu", "vert")):
                continue
        elif not permitted(user, permission):
            continue
        if area == "documents":
            if "facture" in phrase and not permitted(user,"document.read","vert"):
                continue
            if "livraison" in phrase and not permitted(user,"document.read","rose"):
                continue
            if "facture" in phrase and permitted(user,"document.read","vert"):
                answer = "Les factures Framatex sont classées dans le sous-dossier Vert du lancement. Ouvrez ce dossier pour déposer ou retrouver la pièce."
                folder = "vert"
            elif "livraison" in phrase and permitted(user,"document.read","rose"):
                answer = "Un bon de livraison se classe dans le sous-dossier Rose. Vérifiez le lancement avant de confirmer le dépôt."
                folder = "rose"
            elif not any(permitted(user,"document.read",slug) for slug in ("jaune","rose","bleu","vert")):
                continue
        destination = ("home" if area == "priorities" else area if area in ("launches","admin") else "detail" if launch else "launches")
        return {"title":title, "answer":answer, "destination":destination,
                "launch_id":launch.id if launch and destination == "detail" else None,
                "area":area if destination == "detail" else None,
                "folder":folder if folder and permitted(user,"document.read",folder) else None,
                "requires_human_action":True,"source":"Guide de navigation intégré · règles locales"}
    return {"title":"Question à préciser", "answer":"Je n'ai pas de procédure vérifiée pour cette question ou vous n'avez pas accès à la rubrique. Reformulez votre demande ou contactez l'administrateur.",
            "destination":None,"launch_id":None,"area":None,"folder":None,
            "requires_human_action":True,"source":"Guide de navigation intégré · aucune recherche dans vos documents"}

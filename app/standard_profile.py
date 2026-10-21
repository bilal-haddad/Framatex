"""Profil « Dossier Jaune FRAMATEX standard » : checklist documentaire par sous-dossier.

Le profil s'appuie entièrement sur le moteur de complétude existant (règles par
sous-dossier, type documentaire, étape d'exigibilité, validation). Il est créé à
la première utilisation, puis reste modifiable dans Administration ; une règle
désactivée par un administrateur n'est jamais réactivée ici.
Toutes les pièces obligatoires sont exigibles dès la création du dossier : la
checklist complète est visible et lisible immédiatement (Présent, Manquant, En
validation, Exception). Les pièces facultatives ne sont jamais manquantes.
L'étape de la commande reste une information de suivi.
"""
from __future__ import annotations

from sqlalchemy import select

from .completeness_models import CompletenessProfile, LaunchCompleteness, RequirementRule

STANDARD_PROFILE_NAME = "Dossier Jaune FRAMATEX standard"
STANDARD_PROFILE_DESCRIPTION = ("Checklist documentaire par défaut des Dossiers Jaunes : technique, réception, "
                                "dédouanement et factures, selon l'étape de la commande.")

# (sous-dossier, libellé de la checklist, type documentaire, exigible dès, validation requise, obligatoire)
STANDARD_RULES = [
    ("jaune", "Dossier technique client", "Dossier technique client", "preparation", False, True),
    ("jaune", "Commande client", "Commande client", "preparation", False, True),
    ("jaune", "Lancement provisoire", "Lancement provisoire", "preparation", False, True),
    ("jaune", "Lancement définitif", "Lancement définitif", "preparation", False, True),
    ("jaune", "Fiche d’emploi", "Fiche d’emploi", "preparation", True, True),
    ("jaune", "Calcul du besoin", "Calcul du besoin", "preparation", False, True),
    ("jaune", "Fiche de prix", "Fiche de prix", "preparation", True, True),
    ("jaune", "Étude BE / Excel", "Excel BE", "preparation", False, True),
    ("jaune", "Test tissu", "Tests tissu", "preparation", False, True),
    ("jaune", "Emails techniques", "Email", "preparation", False, False),
    ("rose", "Bon de livraison", "Bon de livraison", "preparation", False, True),
    ("rose", "Bon / note de réception", "Bon de réception", "preparation", False, True),
    ("rose", "Document de réception matière", "Document réception", "preparation", True, True),
    ("rose", "Emails réception / logistique", "Email", "preparation", False, False),
    ("bleu", "Déclaration douanière", "Pièce douanière", "preparation", False, True),
    ("bleu", "Documents import / export", "Justificatif import/export", "preparation", False, True),
    ("bleu", "Document transit", "Document transit", "preparation", False, True),
    ("bleu", "Document transport", "Document transport", "preparation", False, True),
    ("bleu", "Justificatif de dédouanement", "Justificatif de dédouanement", "preparation", False, True),
    ("vert", "Facture FRAMATEX", "Facture", "preparation", False, True),
    ("vert", "Pièce de facturation associée", "Document facturation", "preparation", False, True),
    ("vert", "Avoir / correction de facture", "Avoir / correction de facture", "preparation", False, False),
]


def ensure_standard_profile(db, user):
    """Profil standard existant ou créé ; ajoute seulement les règles absentes."""
    profile = db.scalar(select(CompletenessProfile).where(CompletenessProfile.name == STANDARD_PROFILE_NAME))
    if not profile:
        profile = CompletenessProfile(name=STANDARD_PROFILE_NAME, description=STANDARD_PROFILE_DESCRIPTION,
                                      created_by=user.id)
        db.add(profile)
        db.flush()
    present = {(rule.folder_slug, rule.document_type) for rule in profile.rules}
    for folder, title, document_type, phase, validation, required in STANDARD_RULES:
        if (folder, document_type) not in present:
            db.add(RequirementRule(profile_id=profile.id, title=title, folder_slug=folder,
                                   document_type=document_type, due_phase=phase,
                                   requires_validation=validation, required=required))
    db.flush()
    db.refresh(profile)
    return profile


def apply_standard_profile(db, launch, user, phase="preparation", *, reason="automatic"):
    """Applique le profil standard à un dossier sans profil ; ne remplace jamais un profil choisi."""
    from .main import audit
    context = db.get(LaunchCompleteness, launch.id)
    if context and context.profile_id:
        return False
    profile = ensure_standard_profile(db, user)
    if context:
        context.profile_id, context.phase = profile.id, phase
    else:
        db.add(LaunchCompleteness(launch_id=launch.id, profile_id=profile.id, phase=phase))
    audit(db, user, "completeness.context.update", "launch", launch.id,
          {"profile": profile.id, "profile_name": STANDARD_PROFILE_NAME, "phase": phase, "origin": reason})
    return True

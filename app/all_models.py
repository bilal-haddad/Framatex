"""Import de tous les modules de modèles : métadonnées complètes (Alembic, transfert, vérification)."""
from . import (access_models, approval_models, client_models, client_workflow_models, completeness_models,  # noqa: F401
               document_intake_models, document_intelligence_models, impact_sim_models, intake_models, internal_models,
               mail_models, material_models, models, orli_models, pilot_models, quality_models, sharing_models,
               spec_models, workflow_models)
from . import migrate  # noqa: F401  (table schema_migrations : historique des révisions SQLite)

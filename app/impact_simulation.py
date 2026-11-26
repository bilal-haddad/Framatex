"""Graphe explicable et simulation quantitative non destructive du MVP 0.10.

Les résultats sont des estimations arithmétiques *illustratives*, non une simulation
financière complète. Entrées sourcées, Decimal exact et aucune écriture dans ORLI.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .active_documents import active_versions, current_version
from .models import Document, DocumentVersion
from .workflow_models import BusinessValueRevision, ImpactRule

INPUTS = {
    'quantite_lancement': ('Quantité du lancement', 'pièce'),
    'consommation_matiere': ('Consommation de tissu par pièce', 'm/pièce'),
    'cout_matiere_unitaire': ('Coût matière par mètre', 'MAD/m'),
}
CALCULATED = {
    'besoin_calcule': ('Besoin matière théorique', 'm'),
    'cout_matiere_estime': ('Coût matière théorique', 'MAD'),
}
# Les trois relations explicites constituent le graphe calculatoire, sans moteur
# de formules arbitraires ni execution d'expressions stockées en base.
EDGES = [
    ('quantite_lancement','besoin_calcule','Nombre de pièces × consommation unitaire'),
    ('consommation_matiere','besoin_calcule','Nombre de pièces × consommation unitaire'),
    ('besoin_calcule','cout_matiere_estime','Besoin matière × coût au mètre'),
    ('cout_matiere_unitaire','cout_matiere_estime','Besoin matière × coût au mètre'),
]
LIMIT = Decimal('999999999')

def number(value: str | None, *, key: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise HTTPException(422, f'Valeur numérique absente : {key}')
    try:
        num = Decimal(str(value).replace(',', '.').strip())
    except InvalidOperation:
        raise HTTPException(422, f'Valeur numérique invalide : {key}')
    if not num.is_finite() or num < 0 or num > LIMIT or num.as_tuple().exponent < -4:
        raise HTTPException(422, f'Valeur hors limites : {key} (4 décimales au maximum)')
    return num

def fmt(value: Decimal) -> str:
    return format(value, 'f')

def current_inputs(db: Session, launch_id: str):
    """Lire uniquement les révisions courantes, avec provenance et versions."""
    rows = db.scalars(select(BusinessValueRevision).where(
        BusinessValueRevision.launch_id == launch_id,
        BusinessValueRevision.key.in_(INPUTS)).order_by(
        BusinessValueRevision.revision.desc(), BusinessValueRevision.recorded_at.desc())).all()
    data = {}
    for row in rows:
        if row.key in data:
            continue
        version = db.get(DocumentVersion, row.source_version_id)
        document = db.get(Document, version.document_id) if version else None
        if not document or document.folder.launch_id != launch_id or document.folder.slug != 'jaune':
            # Seules les valeurs métier du sous-dossier technique participent.
            # Cela évite de révéler une donnée issue d'une autre rubrique.
            continue
        if row.unit != INPUTS[row.key][1]:
            # Une unité différente ne peut pas être interpolée silencieusement.
            raise HTTPException(409, f'Unité source incompatible : {row.key}')
        data[row.key] = {
            'value': fmt(number(row.value_text, key=row.key)),
            'unit': row.unit,
            'revision': row.revision,
            'source_version_id': row.source_version_id,
            'source_title': document.title,
            'source_folder': document.folder.slug,
            'stale_source': version is not current_version(document),
        }
    return data

def estimate(inputs: dict[str, Decimal]):
    qty = inputs.get('quantite_lancement')
    ratio = inputs.get('consommation_matiere')
    rate = inputs.get('cout_matiere_unitaire')
    needs = qty * ratio if qty is not None and ratio is not None else None
    cost = needs * rate if needs is not None and rate is not None else None
    return {'besoin_calcule': needs, 'cout_matiere_estime': cost}

def calculate(db: Session, launch_id: str, proposed: dict[str, str]):
    if not proposed:
        raise HTTPException(422, 'Précisez au moins une valeur à faire varier')
    if unknown := set(proposed) - set(INPUTS):
        raise HTTPException(422, 'Champ non pris en charge : ' + ', '.join(sorted(unknown)))
    sources = current_inputs(db, launch_id)
    if set(proposed) - sources.keys():
        raise HTTPException(422, 'Enregistrez d’abord les valeurs métier de référence : '+', '.join(sorted(set(proposed)-sources.keys())))
    baseline = {key: number(source['value'], key=key) for key, source in sources.items()}
    scenario = baseline.copy()
    for key, value in proposed.items():
        scenario[key] = number(value, key=key)
    base_results, sim_results = estimate(baseline), estimate(scenario)
    output = []
    for key in CALCULATED:
        before, after = base_results[key], sim_results[key]
        output.append({'key': key, 'label': CALCULATED[key][0], 'unit': CALCULATED[key][1],
                       'baseline': fmt(before) if before is not None else None,
                       'scenario': fmt(after) if after is not None else None,
                       'delta': fmt(after - before) if before is not None and after is not None else None})
    warnings = ['Simulation indicative : hors pertes, rendements, taxes, transport, remises et contraintes contractuelles. Aucun prix ni besoin validé n’est modifié.']
    if any(source['stale_source'] for source in sources.values()):
        warnings.append('Une valeur de référence provient d’une ancienne version documentaire : vérifier sa validité.')
    missing = [key for key in INPUTS if key not in baseline]
    if missing:
        warnings.append('Valeur(s) non renseignée(s) : '+', '.join(missing)+'. Les résultats correspondants ne peuvent pas être calculés.')
    return {'sources': sources, 'inputs': [{'key': key, 'label': INPUTS[key][0], 'unit': INPUTS[key][1],
                  'baseline': fmt(baseline[key]) if key in baseline else None,
                  'scenario': fmt(scenario[key]) if key in scenario else None,
                  'changed': key in proposed and scenario[key] != baseline[key]} for key in INPUTS],
            'outputs': output, 'warnings': warnings, 'changed_keys': sorted(proposed)}

def dependency_graph(db: Session, launch_id: str, can_access_folder):
    if not can_access_folder('jaune'):
        # Aucun nœud technique ou valeur ne doit être révélé en cas d'absence de droit.
        return {'nodes': [], 'edges': [], 'limited': True}
    sources = current_inputs(db, launch_id)
    nodes = [{'id': k, 'label': label, 'kind': 'input', 'unit': unit,
              'available': k in sources, 'value': sources.get(k, {}).get('value'),
              'source_title': sources.get(k, {}).get('source_title'),
              'stale_source': sources.get(k, {}).get('stale_source', False)} for k, (label, unit) in INPUTS.items()]
    results = estimate({k: number(v['value'], key=k) for k,v in sources.items()})
    nodes += [{'id': k,'label': label,'kind':'derived','unit': unit,
               'available': results[k] is not None,
               'value': fmt(results[k]) if results[k] is not None else None} for k,(label,unit) in CALCULATED.items()]
    edges = [{'source': a, 'target': b, 'meaning': meaning, 'kind': 'formula'} for a,b,meaning in EDGES]
    # Reutilise aussi les règles de propagation réellement configurées, sans
    # inventer de dépendance métier entre les documents/équipes.
    for rule in db.scalars(select(ImpactRule).where(ImpactRule.active.is_(True))).all():
        if not (can_access_folder(rule.source_folder) and can_access_folder(rule.target_folder)):
            continue
        if rule.source_kind == 'value' and rule.source_key in INPUTS:
            target_id = f'process:{rule.id}'
            nodes.append({'id': target_id, 'label': rule.name, 'kind': 'process',
                          'folder': rule.target_folder, 'available': True})
            edges.append({'source': rule.source_key, 'target': target_id,
                          'meaning': rule.instruction, 'kind': 'rule'})
    return {'nodes': nodes, 'edges': edges, 'limited': False}

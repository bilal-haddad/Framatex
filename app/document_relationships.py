"""Rapprochements locaux et explicables entre documents d'une même commande."""
from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher

from .document_intake import canonical_type
from .document_intake_models import DocumentIdentification
from .intake import normalized


REFERENCE_FIELDS = {'reference_commande', 'reference_article', 'numero_lancement', 'reference_client'}


def comparison_text(analysis: dict) -> str:
    return normalized(analysis.get('comparison_text') or analysis.get('text_excerpt') or '')[:12000]


def field_map(analysis: dict) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for field in analysis.get('fields', []):
        value = normalized(str(field.get('value', '')))
        if value:
            values.setdefault(str(field.get('key', '')), set()).add(value)
    return values


def document_type(analysis: dict) -> str:
    suggestions = analysis.get('classification', {}).get('suggestions', [])
    return canonical_type(suggestions[0]['doc_type']) if suggestions else ''


def _similarity(left: str, right: str) -> tuple[float, float]:
    if not left or not right:
        return 0.0, 0.0
    sequence = SequenceMatcher(None, left[:12000], right[:12000], autojunk=False).ratio()
    left_tokens, right_tokens = set(left.split()), set(right.split())
    token = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return sequence, token


def _candidate(sha256: str, analysis: dict, document, version, previous: dict) -> dict | None:
    evidence = []
    if version.sha256 == sha256:
        kind = 'exact_duplicate'
        evidence.append('Empreinte SHA-256 identique sur les octets stockés')
        sequence = token = 1.0
        common_references = []
        common_fields = []
    else:
        current_text, previous_text = comparison_text(analysis), comparison_text(previous)
        sequence, token = _similarity(current_text, previous_text)
        current_fields, previous_fields = field_map(analysis), field_map(previous)
        common_fields = sorted(key for key in current_fields.keys() & previous_fields
                               if current_fields[key] & previous_fields[key])
        common_references = sorted(set(common_fields) & REFERENCE_FIELDS)
        conflicting_references = sorted(
            key for key in REFERENCE_FIELDS & current_fields.keys() & previous_fields.keys()
            if not current_fields[key] & previous_fields[key]
        )
        same_type = bool(document_type(analysis) and document_type(analysis) == canonical_type(document.doc_type))
        if same_type:
            evidence.append(f'Type documentaire compatible : {document.doc_type}')
        if common_references:
            evidence.append('Référence(s) identique(s) : ' + ', '.join(common_references))
        if common_fields:
            evidence.append('Champ(s) commun(s) : ' + ', '.join(common_fields[:6]))
        if sequence >= .35 or token >= .35:
            evidence.append(f'Texte normalisé comparable (séquence {sequence:.2f}, vocabulaire {token:.2f})')
        if conflicting_references:
            return None
        if common_references and same_type:
            kind = 'new_version'
        elif sequence >= .82 or token >= .78 or (len(common_fields) >= 2 and same_type):
            kind = 'potential_duplicate'
        else:
            return None
    signature_source = {'candidate': version.id, 'sha256': sha256, 'kind': kind,
                        'sequence': round(sequence, 4), 'token': round(token, 4),
                        'references': common_references, 'fields': common_fields}
    return {
        'kind': kind,
        'candidate_document_id': document.id,
        'candidate_version_id': version.id,
        'candidate_version': version.number,
        'title': document.title,
        'doc_type': document.doc_type,
        'folder': document.folder.slug,
        'evidence': evidence,
        'similarity': {'sequence': round(sequence, 2), 'vocabulary': round(token, 2)},
        'evidence_signature': hashlib.sha256(
            json.dumps(signature_source, sort_keys=True).encode()).hexdigest(),
    }


def propose_relationships(db, user, launch, sha256: str, analysis: dict) -> list[dict]:
    """Ne retourne que les candidats que l'utilisateur est autorisé à lire."""
    from .main import permitted
    from .active_documents import current_version

    proposals = []
    for folder in launch.folders:
        # Un rapprochement révèle l'existence et des caractéristiques d'autres
        # pièces : il relève explicitement de « Consulter les contrôles ».
        if not (permitted(user, 'document.read', folder.slug)
                and permitted(user, 'controls.read', folder.slug)):
            continue
        for document in folder.documents:
            version = current_version(document)      # documents et versions supprimés exclus
            if version is None:
                continue
            identification = db.get(DocumentIdentification, version.id)
            previous = identification.analysis if identification else {}
            item = _candidate(sha256, analysis, document, version, previous)
            if item:
                proposals.append(item)
    rank = {'exact_duplicate': 0, 'new_version': 1, 'potential_duplicate': 2}
    return sorted(proposals, key=lambda item: (rank[item['kind']], -item['similarity']['sequence'], item['title']))[:8]

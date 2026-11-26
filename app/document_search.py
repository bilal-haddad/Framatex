"""Index plein texte local du contenu documentaire déjà analysé (OCR compris).

SQLite : table virtuelle FTS5 `document_content_fts` (migrateur historique).
PostgreSQL : table `document_search_index` (tsvector généré, index GIN, insensible aux accents via
`framatex_unaccent`, révision Alembic 0020) ; recherche par préfixe de chaque mot.
Dans les deux cas, la fonction ne renvoie que des identifiants de versions : les droits (commande,
sous-dossier, éléments supprimés) sont appliqués par l'appelant avant toute restitution.
"""
from __future__ import annotations

import re

from sqlalchemy import text

TOKENS = re.compile(r'[\wÀ-ÿ]{2,}', flags=re.UNICODE)


def _postgres(db) -> bool:
    return db.get_bind().dialect.name == 'postgresql'


def _payload(version, analysis):
    content = (analysis.get('comparison_text') or analysis.get('text_excerpt') or '').strip()
    references = ' '.join(str(field.get('value', '')) for field in analysis.get('fields', [])
                          if field.get('key', '').startswith('reference_') or field.get('key') == 'numero_lancement')
    return {'version_id': version.id, 'content': content,
            'title': f'{version.document.title} {version.original_name}', 'references': references}


def index_document_version(db, version, analysis: dict | None):
    if not analysis:
        return
    values = _payload(version, analysis)
    if _postgres(db):
        db.execute(text('INSERT INTO document_search_index (version_id, content, title, "references") '
                        'VALUES (:version_id, :content, :title, :references) '
                        'ON CONFLICT (version_id) DO UPDATE SET content = EXCLUDED.content, title = EXCLUDED.title, '
                        '"references" = EXCLUDED."references"'), values)
        return
    db.execute(text('DELETE FROM document_content_fts WHERE version_id = :version_id'), {'version_id': version.id})
    db.execute(text('INSERT INTO document_content_fts(version_id, content, title, "references") '
                    'VALUES (:version_id, :content, :title, :references)'), values)


def remove_version(db, version_id: str):
    table = 'document_search_index' if _postgres(db) else 'document_content_fts'
    db.execute(text(f'DELETE FROM {table} WHERE version_id = :v'), {'v': version_id})


def search_content(db, query: str, limit: int = 500) -> dict[str, str]:
    tokens = TOKENS.findall(query)[:12]
    if not tokens:
        return {}
    if _postgres(db):
        # Mots saisis (caractères de mot uniquement : aucune syntaxe tsquery injectable), chacun en préfixe.
        expression = ' & '.join(f'{token.lower()}:*' for token in tokens)
        rows = db.execute(text('''SELECT version_id,
            ts_headline('simple', content, to_tsquery('simple', framatex_unaccent(:query)),
                        'StartSel=[, StopSel=], MaxWords=18, MinWords=6, MaxFragments=1, FragmentDelimiter=" … "') AS excerpt
            FROM document_search_index WHERE search_vector @@ to_tsquery('simple', framatex_unaccent(:query))
            LIMIT :limit'''), {'query': expression, 'limit': limit}).all()
        return {version_id: excerpt for version_id, excerpt in rows}
    expression = ' AND '.join('"' + token.replace('"', '""') + '"' for token in tokens)
    rows = db.execute(text('''SELECT version_id,
        snippet(document_content_fts, 1, '[', ']', ' … ', 18) AS excerpt
        FROM document_content_fts WHERE document_content_fts MATCH :query LIMIT :limit'''),
        {'query': expression, 'limit': limit}).all()
    return {version_id: excerpt for version_id, excerpt in rows}

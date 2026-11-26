"""Bounded document reading and version-level classification decisions."""
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore

from .intake import LIMITS, MAX_ANALYSIS_BYTES, normalized, preview

import os
# Analyses (OCR compris) menées en parallèle : bornées pour préserver les autres utilisateurs.
ANALYZERS = BoundedSemaphore(max(1, int(os.getenv('FRAMATEX_ANALYSIS_CONCURRENCY', '2'))))
ALIASES = {'dossier technique': 'Dossier technique client', 'declaration douaniere': 'Pièce douanière'}


def read_safely(path, filename, *, allow_ocr=True):
    def unavailable(method, message):
        return {'filename': filename, 'method': method, 'warnings': [message], 'text_excerpt': '',
                'extracted_text': '', 'sources': [], 'limitations': [{'code': method, 'message': message}],
                'reading_status': 'impossible', 'sha256': None, 'schema_version': 'document-intelligence/v2',
                'classification': {'suggestions': [], 'decisive': False, 'ambiguous': False,
                                   'needs_confirmation': True}, 'fields': [], 'human_validation_required': True}

    if path.stat().st_size > MAX_ANALYSIS_BYTES:
        return unavailable('size_limit', 'Analyse automatique limitée à 12 Mo. Vérification manuelle requise.')
    if not ANALYZERS.acquire(timeout=5):
        return unavailable('busy', 'Analyse occupée. Réessayez depuis la version ou vérifiez manuellement.')
    try:
        result = subprocess.run([sys.executable, '-m', 'app.document_intake', str(path.resolve()), filename,
                                 'ocr' if allow_ocr else 'text'], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, timeout=LIMITS.document_timeout if allow_ocr else min(15, LIMITS.document_timeout), check=True)
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return unavailable('analysis_timeout', 'Analyse interrompue après le délai de sécurité. Vérification manuelle requise.')
    except (subprocess.SubprocessError, OSError, ValueError):
        return unavailable('analysis_failed', 'Analyse impossible dans le délai imparti. Vérification manuelle requise.')
    finally:
        ANALYZERS.release()


def canonical_type(value):
    key = normalized(value)
    return normalized(ALIASES.get(key, value))


def identification_status(analysis, folder, doc_type):
    classified = analysis['classification']
    if not classified['decisive']:
        return 'to_verify'
    suggestion = classified['suggestions'][0]
    if suggestion['folder'] == folder and canonical_type(suggestion['doc_type']) == canonical_type(doc_type):
        return 'matched'
    return 'incompatible'


def assess_direct(path, filename, folder, doc_type, strict=False):
    from .standard_profile import STANDARD_RULES
    if not strict and (folder, doc_type) not in {(rule[0], rule[2]) for rule in STANDARD_RULES}:
        return None
    # Historical integrations may supply a type verified outside FRAMATEX.
    # Positive evidence of a conflict is never ignored; guided versions always
    # require verification when the reader cannot establish their type.
    if not strict and Path(filename).suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        return None
    analysis = read_safely(path, filename, allow_ocr=strict)
    status = identification_status(analysis, folder, doc_type)
    return {'status': status, 'analysis': analysis} if strict or status in {'matched', 'incompatible'} else None


if __name__ == '__main__':
    if sys.platform != 'win32':
        import resource
        ceiling = LIMITS.max_memory_mib * 1024 * 1024
        _, current_limit = resource.getrlimit(resource.RLIMIT_AS)
        if current_limit != resource.RLIM_INFINITY:
            ceiling = min(ceiling, current_limit)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, current_limit))
    with redirect_stdout(sys.stderr):
        result = preview(Path(sys.argv[1]), sys.argv[2], sys.argv[3] == 'ocr')
    print(json.dumps(result))

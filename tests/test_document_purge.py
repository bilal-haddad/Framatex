"""Suppression définitive depuis la corbeille : administrateur seul, dépendances et conservation vérifiées,
fichier effacé après validation en base, trace minimale dans l'audit."""
import json
import uuid

from tests.test_document_reliability import H, chef, delete, new_version, pdf, technician, upload


def trash(c):
    return c.get('/api/admin/document-trash').json()['items']


def purge(c, kind, item_id, confirmation='SUPPRIMER', reason='Dépôt erroné de recette'):
    return c.post(f'/api/admin/document-trash/{kind}/{item_id}/purge', headers=H, json={'confirmation': confirmation, 'reason': reason})


def stored_path(version_id):
    from app.core import SessionLocal
    from app.main import STORAGE
    from app.models import DocumentVersion
    with SessionLocal() as db:
        return STORAGE / db.get(DocumentVersion, version_id).disk_name


def test_purge_document_and_version_rules():
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Purge {uuid.uuid4().hex[:6]}'}).json()['id']
    same = pdf(f'Contenu {uuid.uuid4().hex}')
    doc = upload(c, lid, 'jaune', 'erreur.pdf', same)
    keep = upload(c, lid, 'rose', 'garde.pdf', pdf(f'Garde {uuid.uuid4().hex}'))
    path = stored_path(doc['latest']['id'])
    assert path.is_file()
    # Hors corbeille : refusé.
    assert purge(c, 'documents', doc['id']).status_code == 404
    delete(c, f"/api/documents/{doc['id']}")
    row = next(r for r in trash(c) if r['document_id'] == doc['id'])
    assert row['kind'] == 'document' and row['original_name'] == 'erreur.pdf' and row['launch_id'] == lid
    assert row['deleted_by'] and row['size'] > 0 and row['purge']['allowed'] is True     # type « Autre » : aucune obligation
    # Confirmation renforcée et droits.
    assert purge(c, 'documents', doc['id'], confirmation='oui').status_code == 422
    tech = technician(c, {lid: {s: ['document.read', 'document.write', 'document.review'] for s in ('jaune', 'rose')}})
    assert purge(tech, 'documents', doc['id']).status_code == 403
    assert tech.get('/api/admin/document-trash').status_code == 403
    r = purge(c, 'documents', doc['id'])
    assert r.status_code == 200, r.text
    assert not path.exists()                                                      # fichier effacé
    assert all(x['document_id'] != doc['id'] for x in trash(c))                   # disparu de la corbeille
    assert c.post(f"/api/admin/document-trash/documents/{doc['id']}/restore", headers=H).status_code == 404
    assert c.get(f"/api/document-versions/{doc['latest']['id']}/preview").status_code == 404
    assert c.get(f"/api/documents/{doc['id']}/versions/1/download").status_code == 404
    assert c.get(f'/api/workspace/search', params={'q': 'erreur'}).json()['total'] == 0
    events = c.get('/api/workspace/activity', params={'launch_id': lid, 'limit': 100}).json()['items']
    purge_event = next(e for e in events if e['action'] == 'document.purge')
    assert purge_event['detail']['versions'] == [1] and purge_event['detail']['doc_type'] == 'Autre'
    assert 'erreur.pdf' not in json.dumps(purge_event['detail'])                  # trace minimale
    # Aucun faux doublon : le même contenu redéposé est neuf ; l'autre document est intact.
    again = upload(c, lid, 'bleu', 'nouveau.pdf', same)
    assert again['duplicates'] == [] and c.get(f'/api/launches/{lid}/duplicates').json() == []
    assert stored_path(keep['latest']['id']).is_file()
    # Version seule.
    v2 = new_version(c, keep['id'], 'garde-v2.pdf', pdf(f'V2 {uuid.uuid4().hex}'))
    v2_path = stored_path(v2['latest']['id'])
    assert purge(c, 'versions', v2['latest']['id']).status_code == 404            # pas en corbeille
    delete(c, f"/api/document-versions/{v2['latest']['id']}")
    assert purge(c, 'versions', v2['latest']['id']).status_code == 200
    assert not v2_path.exists() and stored_path(keep['latest']['id']).is_file()
    listed = next(d for f in c.get(f'/api/launches/{lid}').json()['folders'] for d in f['documents'] if d['id'] == keep['id'])
    assert [v['number'] for v in listed['versions']] == [1]


def test_purge_blocked_by_dependencies_and_retention():
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Conservation {uuid.uuid4().hex[:6]}'}).json()['id']
    # Facture : obligation de conservation connue et en cours.
    invoice = c.post(f'/api/launches/{lid}/documents', headers=H, data={'folder': 'vert', 'title': 'Facture', 'doc_type': 'Facture'},
                     files={'file': ('facture.pdf', pdf(f'Facture {uuid.uuid4().hex}'), 'application/pdf')}).json()
    delete(c, f"/api/documents/{invoice['id']}")
    verdict = next(r for r in trash(c) if r['document_id'] == invoice['id'])['purge']
    assert verdict['retention']['status'] == 'protected' and not verdict['allowed']
    assert purge(c, 'documents', invoice['id']).status_code == 409
    # Type inconnu : vérification administrative requise, puis autorisée.
    odd = c.post(f'/api/launches/{lid}/documents', headers=H, data={'folder': 'jaune', 'title': 'Divers', 'doc_type': 'Type maison'},
                 files={'file': ('divers.pdf', pdf(f'Divers {uuid.uuid4().hex}'), 'application/pdf')}).json()
    delete(c, f"/api/documents/{odd['id']}")
    assert purge(c, 'documents', odd['id']).status_code == 409
    assert c.post(f"/api/admin/document-trash/documents/{odd['id']}/retention-clearance", headers=H, json={'reason': 'court'}).status_code == 422
    cleared = c.post(f"/api/admin/document-trash/documents/{odd['id']}/retention-clearance", headers=H,
                     json={'reason': 'Dépôt erroné, aucune obligation de conservation (vérifié)'})
    assert cleared.status_code == 201 and cleared.json()['allowed']
    assert purge(c, 'documents', odd['id']).status_code == 200
    # Dépendance métier : décision documentaire sur la version.
    reviewed = upload(c, lid, 'jaune', 'revue.pdf', pdf(f'Revue {uuid.uuid4().hex}'))
    assert c.post(f"/api/documents/{reviewed['id']}/reviews", headers=H, json={'decision': 'approved', 'comment': ''}).status_code == 201
    delete(c, f"/api/documents/{reviewed['id']}")
    blocked = purge(c, 'documents', reviewed['id'])
    assert blocked.status_code == 409 and 'décision documentaire' in blocked.json()['detail']
    assert c.post(f"/api/admin/document-trash/documents/{reviewed['id']}/restore", headers=H).status_code == 200   # toujours restaurable


def test_storage_queue_never_erases_a_referenced_file():
    """Reprise après interruption : une ligne en attente n'efface jamais un fichier encore référencé."""
    from app.core import SessionLocal
    from app.document_purge import process_purge_queue
    from app.models import DocumentVersion, StoragePurge
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'File {uuid.uuid4().hex[:6]}'}).json()['id']
    doc = upload(c, lid, 'jaune', 'vivant.pdf', pdf(f'Vivant {uuid.uuid4().hex}'))
    path = stored_path(doc['latest']['id'])
    with SessionLocal() as db:
        db.add(StoragePurge(disk_name=db.get(DocumentVersion, doc['latest']['id']).disk_name)); db.commit()
    process_purge_queue()
    assert path.is_file()

"""Documents complémentaires facultatifs : cases par commande et sous-dossier, hors checklist standard."""
import json
import uuid

from tests.test_document_reliability import H, chef, pdf, stage, technician, upload


def completeness(c, lid):
    report = c.get(f'/api/launches/{lid}/completeness').json()
    return report['counts'], len(report['rows'])


def detail_cases(c, lid):
    return {f['slug']: f['optional_cases'] for f in c.get(f'/api/launches/{lid}').json()['folders']}


def publish_into(c, lid, folder, case_id, name, data, **extra):
    staged = stage(c, lid, folder, name, data)
    body = {'folder': folder, 'doc_type': 'Facture', 'title': name, 'optional_case_id': case_id, **extra}
    rel = staged['analysis'].get('relationships') or []
    if rel:
        body.update(relationship_action='new_document', relationship_candidate_version_id=rel[0]['candidate_version_id'])
    return c.post(f"/api/launches/{lid}/document-uploads/{staged['id']}/publish", headers=H, json=body)


def test_cases_never_missing_and_documents_are_ordinary():
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Complémentaires {uuid.uuid4().hex[:6]}'}).json()['id']
    assert c.post(f'/api/launches/{lid}/completeness/standard', headers=H).status_code in (200, 201)
    counts, rows = completeness(c, lid)
    assert rows == 22                                                        # 22 exigences standard inchangées
    a = c.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'jaune', 'title': 'Photos du prototype', 'description': 'Vues face et dos'})
    b = c.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'jaune', 'title': 'Échange atelier'})
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    assert c.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'jaune', 'title': 'photos du PROTOTYPE'}).status_code == 409
    assert completeness(c, lid) == (counts, rows)                            # case vide : ni manquante ni comptée
    cases = detail_cases(c, lid)
    assert [x['title'] for x in cases['jaune']] == ['Photos du prototype', 'Échange atelier'] and cases['rose'] == []
    # Dépôt dans la case : type complémentaire forcé, classement confirmé, aucune exigence satisfaite.
    r = publish_into(c, lid, 'jaune', a.json()['id'], 'proto-face.pdf', pdf(f'Facture prototype {uuid.uuid4().hex}'))
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc['doc_type'] == 'Document complémentaire' and doc['optional_case_id'] == a.json()['id'] and doc['identification'] in ('confirmed', 'matched')
    assert completeness(c, lid) == (counts, rows)
    second = publish_into(c, lid, 'jaune', a.json()['id'], 'proto-dos.pdf', pdf(f'Dos {uuid.uuid4().hex}')).json()
    assert detail_cases(c, lid)['jaune'][0]['document_ids'] == [doc['id'], second['id']]
    board = c.get(f'/api/launches/{lid}/dashboard').json()
    assert board['kpis'].get('identification_documents', 0) == 0
    # Une pièce complémentaire ne remplace pas une exigence standard.
    rule = c.get(f'/api/launches/{lid}/completeness').json()['rows'][0]
    bad = publish_into(c, lid, rule['folder'], a.json()['id'], 'x.pdf', pdf(f'X {uuid.uuid4().hex}'), rule_id=rule['id'])
    assert bad.status_code in (404, 422)
    # Versions, empreinte et doublons : comme tout document.
    v2 = c.post(f"/api/documents/{doc['id']}/versions", headers=H, files={'file': ('proto-face-v2.pdf', pdf(f'V2 {uuid.uuid4().hex}'), 'application/pdf')})
    assert v2.status_code == 201 and v2.json()['latest']['number'] == 2 and v2.json()['optional_case_id'] == a.json()['id']
    same = pdf(f'Copie {uuid.uuid4().hex}')
    publish_into(c, lid, 'jaune', b.json()['id'], 'copie.pdf', same)
    upload(c, lid, 'rose', 'copie-rose.pdf', same)
    assert len(c.get(f'/api/launches/{lid}/duplicates').json()) == 1
    # Suppression : case non vide refusée ; documents supprimés → case supprimable ; restauration → case revenue.
    assert c.delete(f"/api/optional-cases/{a.json()['id']}", headers=H).status_code == 409
    for d in (doc, second):
        assert c.request('DELETE', f"/api/documents/{d['id']}", headers={**H, 'Content-Type': 'application/json'}, content=b'{}').status_code == 204
    assert detail_cases(c, lid)['jaune'][0]['document_ids'] == [] and detail_cases(c, lid)['jaune'][0]['can_delete']
    assert c.delete(f"/api/optional-cases/{a.json()['id']}", headers=H).status_code == 204
    assert [x['title'] for x in detail_cases(c, lid)['jaune']] == ['Échange atelier']
    assert c.post(f"/api/admin/document-trash/documents/{doc['id']}/restore", headers=H).status_code == 200
    assert [x['title'] for x in detail_cases(c, lid)['jaune']] == ['Photos du prototype', 'Échange atelier']
    renamed = c.patch(f"/api/optional-cases/{a.json()['id']}", headers=H, json={'title': 'Photos prototype validé', 'description': ''})
    assert renamed.status_code == 200 and renamed.json()['title'] == 'Photos prototype validé'
    actions = [row['action'] for row in c.get('/api/workspace/activity', params={'launch_id': lid, 'limit': 200}).json()['items']]
    assert {'optional_case.create', 'optional_case.attach', 'optional_case.delete', 'optional_case.restore', 'optional_case.update'} <= set(actions)


def test_case_rights_by_profile():
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Droits cases {uuid.uuid4().hex[:6]}'}).json()['id']
    rose = c.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'rose', 'title': 'Note confidentielle rose'}).json()
    jaune = c.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'jaune', 'title': 'Croquis'}).json()
    reader = technician(c, {lid: {'jaune': ['document.read']}})
    writer = technician(c, {lid: {'jaune': ['document.read', 'document.write']}})
    cases = detail_cases(reader, lid)
    assert [x['title'] for x in cases['jaune']] == ['Croquis'] and cases['rose'] == []      # rien du rose
    assert cases['jaune'][0]['can_edit'] is False and cases['jaune'][0]['can_delete'] is False
    assert reader.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'jaune', 'title': 'Nouvelle'}).status_code == 403
    assert reader.patch(f"/api/optional-cases/{rose['id']}", headers=H, json={'title': 'X'}).status_code == 404
    assert reader.delete(f"/api/optional-cases/{rose['id']}", headers=H).status_code == 404
    history = reader.get('/api/workspace/activity', params={'launch_id': lid})
    assert history.status_code == 403 or 'confidentielle' not in json.dumps(history.json(), ensure_ascii=False)
    own = writer.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'jaune', 'title': 'Mesures atelier'})
    assert own.status_code == 201 and own.json()['can_delete'] is True
    assert writer.delete(f"/api/optional-cases/{jaune['id']}", headers=H).status_code == 403   # case d'un autre auteur
    r = publish_into(writer, lid, 'jaune', own.json()['id'], 'mesures.pdf', pdf(f'Mesures {uuid.uuid4().hex}'))
    assert r.status_code == 201 and r.json()['optional_case_id'] == own.json()['id']
    assert publish_into(writer, lid, 'jaune', rose['id'], 'x.pdf', pdf(f'X {uuid.uuid4().hex}')).status_code == 404
    assert writer.post(f'/api/launches/{lid}/optional-cases', headers=H, json={'folder': 'rose', 'title': 'Interdit'}).status_code == 403

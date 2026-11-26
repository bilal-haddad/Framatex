"""Fiabilité documentaire : documents et versions supprimés exclus de toute détection de doublons
(alerte au dépôt, groupes, compteurs du tableau de bord, rapprochements), recalcul à la suppression
et à la restauration, correspondance historique distincte d'un doublon courant."""
import json
import uuid

import fitz

from tests.test_order_sheet import H, chef


def pdf(text):
    d = fitz.open(); d.new_page().insert_text((72, 90), text, fontsize=14)
    return d.tobytes()


def upload(c, lid, folder, name, data):
    r = c.post(f'/api/launches/{lid}/documents', headers=H, data={'folder': folder, 'title': name, 'doc_type': 'Autre'},
               files={'file': (name, data, 'application/pdf')})
    assert r.status_code == 201, r.text
    return r.json()


def new_version(c, doc_id, name, data):
    r = c.post(f'/api/documents/{doc_id}/versions', headers=H, data={'comment': 'v'}, files={'file': (name, data, 'application/pdf')})
    assert r.status_code == 201, r.text
    return r.json()


def groups(c, lid):
    return c.get(f'/api/launches/{lid}/duplicates').json()


def dashboard_count(c, lid):
    report = c.get(f'/api/launches/{lid}/dashboard').json()
    return report['counts']['duplicate_documents'] if 'counts' in report else len(report['duplicate_documents'])


def delete(c, url):
    r = c.request('DELETE', url, headers={**H, 'Content-Type': 'application/json'}, content=json.dumps({'reason': 'test'}))
    assert r.status_code == 204, r.text


def test_jaune_rose_bleu_duplicate_lifecycle():
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Doublons {uuid.uuid4().hex[:6]}'}).json()['id']
    same = pdf(f'Fiche identique {uuid.uuid4().hex}')
    # 1-3. Même PDF en Jaune puis en Rose : doublon détecté.
    jaune = upload(c, lid, 'jaune', 'fiche.pdf', same)
    rose = upload(c, lid, 'rose', 'fiche.pdf', same)
    assert len(groups(c, lid)) == 1 and dashboard_count(c, lid) == 1
    # 4-5. Suppression du Jaune : alerte disparue immédiatement (groupes et compteur).
    delete(c, f"/api/documents/{jaune['id']}")
    assert groups(c, lid) == [] and dashboard_count(c, lid) == 0
    # 6-7. Restauration : le doublon réapparaît.
    assert c.post(f"/api/admin/document-trash/documents/{jaune['id']}/restore", headers=H).status_code == 200
    assert len(groups(c, lid)) == 1 and dashboard_count(c, lid) == 1
    # 8-10. Suppression des deux puis nouveau dépôt en Bleu : aucun faux doublon.
    delete(c, f"/api/documents/{jaune['id']}"); delete(c, f"/api/documents/{rose['id']}")
    bleu = upload(c, lid, 'bleu', 'fiche.pdf', same)
    assert bleu['duplicates'] == [] and bleu['historical_matches'] == []
    assert groups(c, lid) == [] and dashboard_count(c, lid) == 0
    # Même sous-dossier : le dépôt identique d'un document supprimé n'est pas signalé.
    again = upload(c, lid, 'jaune', 'fiche.pdf', same)
    assert again['duplicates'] == []
    # Rapprochements au dépôt guidé : aucun candidat supprimé.
    staged = c.post(f'/api/launches/{lid}/document-uploads', headers=H, data={'folder': 'rose'},
                    files={'file': ('fiche.pdf', same, 'application/pdf')}).json()
    ids = {p['candidate_document_id'] for p in staged['analysis']['relationships']}
    assert jaune['id'] not in ids and rose['id'] not in ids and {bleu['id'], again['id']} <= ids


def test_deleted_version_and_historical_match():
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Versions {uuid.uuid4().hex[:6]}'}).json()['id']
    a, b = pdf(f'Version A {uuid.uuid4().hex}'), pdf(f'Version B {uuid.uuid4().hex}')
    doc = upload(c, lid, 'jaune', 'plan.pdf', a)
    v2 = new_version(c, doc['id'], 'plan.pdf', b)
    other = upload(c, lid, 'rose', 'copie.pdf', b)
    assert len(groups(c, lid)) == 1                                   # V2 courante = copie Rose
    # Suppression de la V2 : la V1 redevient courante, plus de doublon avec la copie Rose.
    delete(c, f"/api/document-versions/{v2['latest']['id']}")
    assert groups(c, lid) == [] and dashboard_count(c, lid) == 0
    # Dépôt du contenu V1 dans le même sous-dossier : doublon courant (V1 est désormais courante).
    first = upload(c, lid, 'jaune', 'v1.pdf', a)
    assert [m['document_id'] for m in first['duplicates']] == [doc['id']]
    delete(c, f"/api/documents/{first['id']}")
    # Restauration de la V2 : la V1 devient historique ; un dépôt identique à la V1 est une
    # correspondance historique, pas un doublon courant.
    assert c.post(f"/api/admin/document-trash/versions/{v2['latest']['id']}/restore", headers=H).status_code == 200
    assert len(groups(c, lid)) == 1
    hist = upload(c, lid, 'jaune', 'ancienne.pdf', a)
    assert hist['duplicates'] == [] and [m['version'] for m in hist['historical_matches']] == [1]
    assert all(g['documents'][0]['document_id'] != hist['id'] for g in groups(c, lid))
    # Une version supprimée n'apparaît jamais comme correspondance.
    delete(c, f"/api/document-versions/{v2['latest']['id']}")
    copy_b = upload(c, lid, 'jaune', 'b.pdf', b)
    assert copy_b['duplicates'] == [] and copy_b['historical_matches'] == []
    assert other['id']


def stage(c, lid, folder, name, data):
    r = c.post(f'/api/launches/{lid}/document-uploads', headers=H, data={'folder': folder}, files={'file': (name, data, 'application/pdf')})
    assert r.status_code == 201, r.text
    return r.json()


def test_new_version_of_chosen_document_despite_other_candidate():
    """« Déposer une nouvelle version » de X : un rapprochement proposé avec Y ne crée pas de document séparé."""
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Version X {uuid.uuid4().hex[:6]}'}).json()['id']
    x = upload(c, lid, 'jaune', 'x.pdf', pdf(f'Document X {uuid.uuid4().hex}'))
    shared = pdf(f'Contenu Y {uuid.uuid4().hex}')
    y = upload(c, lid, 'jaune', 'y.pdf', shared)
    staged = stage(c, lid, 'jaune', 'x-v2.pdf', shared)                       # identique à Y
    related = staged['analysis']['relationships'][0]
    assert related['candidate_document_id'] == y['id']
    r = c.post(f"/api/launches/{lid}/document-uploads/{staged['id']}/publish", headers=H, json={
        'folder': 'jaune', 'doc_type': 'Autre', 'title': 'x.pdf', 'document_id': x['id'], 'confirm_type': True,
        'relationship_action': 'new_document', 'relationship_candidate_version_id': related['candidate_version_id']})
    assert r.status_code == 201, r.text
    assert r.json()['id'] == x['id'] and r.json()['latest']['number'] == 2
    docs = [d['id'] for f in c.get(f'/api/launches/{lid}').json()['folders'] for d in f['documents']]
    assert sorted(docs) == sorted([x['id'], y['id']])                           # aucun document créé en plus
    # Sans document choisi, « nouveau document indépendant » crée bien un nouveau document.
    staged = stage(c, lid, 'jaune', 'z.pdf', shared)
    r = c.post(f"/api/launches/{lid}/document-uploads/{staged['id']}/publish", headers=H, json={
        'folder': 'jaune', 'doc_type': 'Autre', 'title': 'z.pdf', 'confirm_type': True, 'relationship_action': 'new_document',
        'relationship_candidate_version_id': staged['analysis']['relationships'][0]['candidate_version_id']})
    assert r.status_code == 201 and r.json()['id'] not in (x['id'], y['id'])


def technician(c, assignments):
    import secrets
    from fastapi.testclient import TestClient
    from app.main import app
    created = c.post('/api/admin/collaborators', headers=H, json={'name': 'Technicien', 'email': f't-{uuid.uuid4().hex[:6]}@example.test'}).json()
    for lid, folders in assignments.items():
        r = c.put(f"/api/admin/collaborators/{created['collaborator']['id']}/assignments/{lid}", headers=H, json={'folders': folders})
        assert r.status_code == 200, r.text
    t = TestClient(app); pw = secrets.token_urlsafe(16) + 'Aa1!'
    t.post('/api/auth/login', headers=H, json={'email': created['collaborator']['email'], 'password': created['temporary_password']})
    t.post('/api/account/password', headers=H, json={'current_password': created['temporary_password'], 'new_password': pw})
    return t


def test_technician_search_and_folder_filter_respect_rights():
    c = chef()
    tag = uuid.uuid4().hex[:6]
    l1 = c.post('/api/order-sheets', headers=H, json={'name': f'Costume {tag}', 'order_ref': f'CMD-{tag}-1', 'workshop': f'Atelier Nord {tag}', 'color': 'Bleu marine', 'of_number': f'OF-{tag}'}).json()['id']
    l2 = c.post('/api/order-sheets', headers=H, json={'name': f'Veste {tag}', 'order_ref': f'CMD-{tag}-2', 'client_name': f'Client {tag}'}).json()['id']
    l3 = c.post('/api/order-sheets', headers=H, json={'name': f'Hors affectation {tag}', 'order_ref': f'CMD-{tag}-3'}).json()['id']
    upload(c, l1, 'jaune', f'Fiche technique {tag}.pdf', pdf(f'Fiche {tag}'))
    upload(c, l1, 'rose', f'Bon secret {tag}.pdf', pdf(f'Bon {tag}'))          # rose non attribué au technicien
    t = technician(c, {l1: {'jaune': ['document.read']}, l2: {'bleu': ['document.read', 'document.write']}})
    def ids(**params):
        r = t.get('/api/workspace/my-launches', params=params)
        assert r.status_code == 200, r.text
        return {row['launch_id']: [f['slug'] for f in row['folders']] for row in r.json()['items']}
    assert ids() == {l1: ['jaune'], l2: ['bleu']}                              # requête vide : toutes mes commandes
    assert ids(folder='bleu') == {l2: ['bleu']} and ids(folder='rose') == {}
    assert ids(q=f'atelier nord {tag}'.upper()) == {l1: ['jaune']}            # atelier, casse ignorée
    assert ids(q='bleu marine') == {l1: ['jaune']} and ids(q=f'of-{tag}') == {l1: ['jaune']}
    assert ids(q=f'client {tag}') == {l2: ['bleu']} and ids(q=f'CMD-{tag}') == {l1: ['jaune'], l2: ['bleu']}
    assert ids(q=f'fiche technique {tag}') == {l1: ['jaune']}                 # référence de document autorisé
    assert ids(q=f'bon secret {tag}') == {}                                     # document d'un sous-dossier non autorisé
    assert ids(q=f'hors affectation {tag}') == {}                               # commande non attribuée
    assert ids(q=f'fiche technique {tag}', folder='bleu') == {}
    assert t.get('/api/workspace/my-launches', params={'folder': 'violet'}).status_code == 422
    # L'ouverture reste contrôlée par le serveur (aucun contournement par l'URL ou l'API).
    assert t.get(f'/api/launches/{l3}').status_code in (403, 404)
    assert c.get('/api/workspace/my-launches', params={'q': f'CMD-{tag}-3'}).json()['total'] == 1


def test_latest_version_carries_delete_right():
    """« Ouvrir » affiche la version courante : elle porte le même droit de suppression que l'historique."""
    c = chef()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Droits {uuid.uuid4().hex[:6]}'}).json()['id']
    doc = upload(c, lid, 'jaune', 'a.pdf', pdf(f'A {uuid.uuid4().hex}'))
    new_version(c, doc['id'], 'a.pdf', pdf(f'B {uuid.uuid4().hex}'))
    listed = next(d for f in c.get(f'/api/launches/{lid}').json()['folders'] for d in f['documents'] if d['id'] == doc['id'])
    assert listed['latest'] == listed['versions'][-1] and listed['latest']['can_delete'] is True

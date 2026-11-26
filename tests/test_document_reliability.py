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

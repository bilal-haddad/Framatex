"""Recherche documentaire (contenu analysé/OCR) : SQLite FTS5 ou PostgreSQL tsvector, mêmes garanties.

Accents ignorés, recherche partielle par préfixe, références métier, et aucune restitution d'un
document d'un sous-dossier non autorisé (les droits sont appliqués avant toute réponse)."""
import uuid

from tests.test_document_reliability import H, chef, stage, technician


def publish(c, lid, folder, name, data):
    staged = stage(c, lid, folder, name, data)
    rel = staged['analysis'].get('relationships') or []
    r = c.post(f"/api/launches/{lid}/document-uploads/{staged['id']}/publish", headers=H, json={
        'folder': folder, 'doc_type': 'Autre', 'title': name, 'confirm_type': True,
        **({'relationship_action': 'new_document', 'relationship_candidate_version_id': rel[0]['candidate_version_id']} if rel else {})})
    assert r.status_code == 201, r.text
    return r.json()


def found(client, q, **params):
    r = client.get('/api/workspace/search', params={'q': q, **params})
    assert r.status_code == 200, r.text
    return {item['document_id'] for item in r.json()['items']}


def test_content_search_accents_prefix_and_rights():
    from tests.test_document_reliability import pdf
    c = chef()
    tag = uuid.uuid4().hex[:6].upper()
    lid = c.post('/api/order-sheets', headers=H, json={'name': f'Recherche {tag}', 'order_ref': f'RCH-{tag}'}).json()['id']
    customs = publish(c, lid, 'bleu', f'scan-{tag}.pdf', pdf(f'Déclaration douanière référence ZQ{tag}991 conteneur Éléphant'))
    other = publish(c, lid, 'jaune', f'note-{tag}.pdf', pdf(f'Fiche atelier sans rapport KX{tag}'))
    assert customs['id'] in found(c, 'declaration douaniere')              # accents ignorés
    assert customs['id'] in found(c, f'zq{tag.lower()}')                    # préfixe d'une référence (partiel)
    assert customs['id'] in found(c, 'ELEPHANT')                            # casse et accents
    assert customs['id'] not in found(c, 'déclaration', folder='jaune')    # filtre de sous-dossier
    assert other['id'] not in found(c, 'declaration')
    reader = technician(c, {lid: {'jaune': ['document.read']}})
    assert customs['id'] not in found(reader, 'declaration douaniere')      # bleu non attribué : rien
    assert other['id'] in found(reader, f'kx{tag.lower()}')

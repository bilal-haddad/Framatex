"""Checklist « Dossier Jaune FRAMATEX standard » : profil automatique et cas métier A–F.

Le profil standard réutilise le moteur de complétude existant ; ces tests vérifient
les états réellement calculés (présent, manquant, en validation, non exigible,
exception) et leur effet sur le tableau de bord des documents manquants.
"""
import importlib
import secrets
import uuid
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core import Base, SessionLocal, hash_password
from app.main import app
from app.models import Role, User
from app.standard_profile import STANDARD_PROFILE_NAME, STANDARD_RULES

H = {'X-Framatex-Request': '1'}
PASSWORD = secrets.token_urlsafe(18) + 'Aa1!'


@pytest.fixture(scope='module')
def api():
    with TestClient(app) as client:
        email = f'checklist-{uuid.uuid4().hex}@test.local'
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.name == 'Administrateur')) or Role(name='Administrateur')
            db.add(User(name='Responsable checklist', email=email, password_hash=hash_password(PASSWORD), roles=[role]))
            db.commit()
        assert client.post('/api/auth/login', headers=H, json={'email': email, 'password': PASSWORD}).status_code == 200
        yield client


def new_dossier(api, name='Veste lin checklist'):
    created = api.post('/api/launches', headers=H, json={'name': name, 'client_name': 'Atelier Checklist',
                                                          'order_ref': 'CMD-' + uuid.uuid4().hex[:6], 'standard_profile': True})
    assert created.status_code == 201, created.text
    return created.json()['id']


def rows(api, lid):
    report = api.get(f'/api/launches/{lid}/completeness').json()
    return report, {(r['folder'], r['title']): r for r in report['rows']}


def deposit(api, lid, folder, doc_type, blob=None):
    response = api.post(f'/api/launches/{lid}/documents', headers=H,
                        data={'folder': folder, 'title': doc_type, 'doc_type': doc_type},
                        files={'file': (f'{uuid.uuid4().hex[:8]}.txt', blob or uuid.uuid4().bytes, 'text/plain')})
    assert response.status_code == 201, response.text
    return response.json()


def missing_on_dashboard(api, lid):
    return {(m['folder'], m['title']) for m in api.get('/api/workspace/dashboard').json()['missing_documents']
            if m['launch_id'] == lid}


def test_standard_profile_checklist_states_and_dashboard(api):
    lid = new_dossier(api)
    report, by = rows(api, lid)
    assert report['profile_name'] == STANDARD_PROFILE_NAME and report['phase'] == 'preparation'
    assert report['configured'] and len(report['rows']) == len(STANDARD_RULES)
    # C. Calcul du besoin absent à la Préparation → Manquant.
    assert by[('jaune', 'Calcul du besoin')]['status'] == 'missing'
    # D. Test tissu exigible en Fabrication seulement → Non exigible, jamais compté manquant.
    assert by[('jaune', 'Test tissu')]['status'] == 'not_due'
    assert ('jaune', 'Test tissu') not in missing_on_dashboard(api, lid)
    # Pièce facultative absente : Non exigible, à toutes les étapes.
    assert by[('jaune', 'Emails techniques')]['status'] == 'not_due' and by[('jaune', 'Emails techniques')]['required'] is False

    profile_id = report['profile_id']
    assert api.patch(f'/api/launches/{lid}/completeness/context', headers=H,
                     json={'profile_id': profile_id, 'phase': 'approvisionnement'}).status_code == 200
    # A. Réception : Bon de livraison absent → Manquant → visible au tableau de bord, avec client et règle.
    _, by = rows(api, lid)
    assert by[('rose', 'Bon de livraison')]['status'] == 'missing'
    entry = next(m for m in api.get('/api/workspace/dashboard').json()['missing_documents']
                 if m['launch_id'] == lid and m['title'] == 'Bon de livraison')
    assert entry['folder'] == 'rose' and entry['client_name'] == 'Atelier Checklist' and entry['id'] == by[('rose', 'Bon de livraison')]['id']
    assert ('rose', 'Emails réception / logistique') not in missing_on_dashboard(api, lid)

    # B. Dépôt du Bon de livraison → Présent → disparaît des manquants.
    delivery = deposit(api, lid, 'rose', 'Bon de livraison', b'BL V1')
    _, by = rows(api, lid)
    assert by[('rose', 'Bon de livraison')]['status'] == 'present'
    assert ('rose', 'Bon de livraison') not in missing_on_dashboard(api, lid)

    # E. Fiche de prix déposée → En validation : +1 validation, jamais comptée manquante.
    pending_before = api.get('/api/workspace/dashboard').json()['kpis']['pending_documents']
    deposit(api, lid, 'jaune', 'Fiche de prix')
    _, by = rows(api, lid)
    assert by[('jaune', 'Fiche de prix')]['status'] == 'pending_validation'
    assert ('jaune', 'Fiche de prix') not in missing_on_dashboard(api, lid)
    assert api.get('/api/workspace/dashboard').json()['kpis']['pending_documents'] == pending_before + 1

    # F. V2 du Bon de livraison → même ligne, version courante mise à jour, aucun second document.
    v2 = api.post(f"/api/documents/{delivery['id']}/versions", headers=H, files={'file': ('bl-v2.txt', b'BL V2', 'text/plain')})
    assert v2.status_code == 201, v2.text
    _, by = rows(api, lid)
    line = by[('rose', 'Bon de livraison')]
    assert line['status'] == 'present' and len(line['documents']) == 1 and line['documents'][0]['version'] == 2

    # Exception motivée : distincte de Manquant, retirée des manquants.
    rule = by[('bleu', 'Déclaration douanière')]
    assert rule['status'] == 'missing'
    assert api.put(f"/api/launches/{lid}/completeness/rules/{rule['id']}/exception", headers=H,
                   json={'active': True, 'reason': 'Matière locale, pas d’import pour cette commande'}).status_code == 200
    _, by = rows(api, lid)
    assert by[('bleu', 'Déclaration douanière')]['status'] == 'exception'
    assert ('bleu', 'Déclaration douanière') not in missing_on_dashboard(api, lid)

    # Pièce facultative déposée : Présent.
    deposit(api, lid, 'rose', 'Email')
    _, by = rows(api, lid)
    assert by[('rose', 'Emails réception / logistique')]['status'] == 'present'


def test_apply_standard_profile_to_existing_dossier_once(api):
    created = api.post('/api/launches', headers=H, json={'name': 'Dossier sans profil'}).json()
    assert api.get(f"/api/launches/{created['id']}/completeness").json()['configured'] is False
    applied = api.post(f"/api/launches/{created['id']}/completeness/standard", headers=H)
    assert applied.status_code == 200 and applied.json()['profile_name'] == STANDARD_PROFILE_NAME
    assert applied.json()['phase'] == 'preparation'
    assert api.post(f"/api/launches/{created['id']}/completeness/standard", headers=H).status_code == 409
    # Le profil standard n'est jamais dupliqué.
    names = [p['name'] for p in api.get('/api/completeness/profiles').json()]
    assert names.count(STANDARD_PROFILE_NAME) == 1


def test_client_request_folder_gets_standard_profile_in_preparation(api):
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(app))
        email = f'client-checklist-{uuid.uuid4().hex}@test.local'
        account = client.post('/api/client/register', headers=H, json={
            'raison_sociale': 'Maison Checklist', 'nom_contact': 'Contact', 'email': email,
            'telephone': '0600000000', 'adresse': 'Adresse fictive', 'pays': 'Maroc', 'password': PASSWORD}).json()
        assert api.patch(f"/api/admin/clients/{account['id']}/status", headers=H, json={'status': 'active'}).status_code == 200
        assert client.post('/api/client/login', headers=H, json={'email': email, 'password': PASSWORD}).status_code == 200
        order = client.post('/api/client/order-requests', headers=H, json={
            'article': 'Chemise checklist', 'quantite': 300, 'date_souhaitee': '2027-04-01', 'status': 'submitted'}).json()
        opened = api.post(f"/api/admin/client-order-requests/{order['id']}/launch", headers=H)
        assert opened.status_code == 201, opened.text
        report = api.get(f"/api/launches/{opened.json()['launch']['id']}/completeness").json()
        assert report['profile_name'] == STANDARD_PROFILE_NAME and report['phase'] == 'preparation'
        assert {r['folder'] for r in report['rows']} == {'jaune', 'rose', 'bleu', 'vert'}


def test_migration_0008_keeps_existing_rules_required(tmp_path, monkeypatch):
    migration = importlib.import_module('app.migrate')
    engine = create_engine('sqlite:///' + str(tmp_path / 'before-0008.db'))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE completeness_rules DROP COLUMN required'))
        for revision in migration.REVISIONS[:migration.REVISIONS.index('0008_optional_rules')]:
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v,:d)'), {'v': revision, 'd': '2026-10-21'})
        conn.execute(text("INSERT INTO users (id,email,name,password_hash,active,created_at) VALUES ('u','u@example.test','U','h',1,'2026-01-01')"))
        conn.execute(text("INSERT INTO completeness_profiles (id,name,description,created_by,created_at) VALUES ('p','Existant','', 'u','2026-01-01')"))
        conn.execute(text("INSERT INTO completeness_rules (id,profile_id,title,folder_slug,document_type,due_phase,requires_validation,active,guidance) "
                          "VALUES ('r','p','Facture','vert','Facture','cloture',0,1,'')"))
    monkeypatch.setattr(migration, 'engine', engine)
    migration.migrate(); migration.migrate()
    assert 'required' in {c['name'] for c in inspect(engine).get_columns('completeness_rules')}
    with Session(engine) as db:
        assert db.execute(text("SELECT required FROM completeness_rules WHERE id='r'")).scalar() == 1
    engine.dispose()


def test_tzdata_is_a_declared_dependency():
    # Windows n'a pas de base de fuseaux : sans tzdata, ZoneInfo("Africa/Casablanca") échoue.
    from pathlib import Path
    from zoneinfo import ZoneInfo
    requirements = (Path(__file__).resolve().parents[1] / 'requirements.txt').read_text()
    assert any(line.strip().startswith('tzdata') for line in requirements.splitlines())
    assert ZoneInfo('Africa/Casablanca').key == 'Africa/Casablanca'

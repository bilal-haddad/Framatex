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
    # Toute la checklist est visible et exigible dès la création : aucune pièce obligatoire
    # n'attend une étape. Les seules pièces non exigées sont les facultatives.
    required = [r for r in report['rows'] if r['required']]
    assert len(required) == 19 and all(r['due'] and r['status'] == 'missing' for r in required)
    assert {r['title'] for r in report['rows'] if r['status'] == 'not_due'} == {
        'Emails techniques', 'Emails réception / logistique', 'Avoir / correction de facture'}
    # C. Calcul du besoin absent → Manquant ; D. Test tissu absent → Manquant dès la création.
    dashboard = missing_on_dashboard(api, lid)
    assert ('jaune', 'Calcul du besoin') in dashboard and ('jaune', 'Test tissu') in dashboard
    assert ('rose', 'Bon de livraison') in dashboard and ('vert', 'Facture FRAMATEX') in dashboard
    assert ('jaune', 'Emails techniques') not in dashboard

    # L'étape de la commande reste un suivi : elle ne change pas la checklist standard.
    profile_id = report['profile_id']
    assert api.patch(f'/api/launches/{lid}/completeness/context', headers=H,
                     json={'profile_id': profile_id, 'phase': 'approvisionnement'}).status_code == 200
    assert missing_on_dashboard(api, lid) == dashboard
    # A. Réception : Bon de livraison absent → Manquant → visible au tableau de bord, avec client et règle.
    _, by = rows(api, lid)
    entry = next(m for m in api.get('/api/workspace/dashboard').json()['missing_documents']
                 if m['launch_id'] == lid and m['title'] == 'Bon de livraison')
    assert entry['folder'] == 'rose' and entry['client_name'] == 'Atelier Checklist' and entry['id'] == by[('rose', 'Bon de livraison')]['id']

    # B. Dépôt du Bon de livraison → Présent → disparaît des manquants.
    delivery = deposit(api, lid, 'rose', 'Bon de livraison', b'BL V1')
    _, by = rows(api, lid)
    assert by[('rose', 'Bon de livraison')]['status'] == 'present'
    assert ('rose', 'Bon de livraison') not in missing_on_dashboard(api, lid)

    # E. Fiche de prix déposée → En validation : listée « en validation », jamais manquante.
    pending_before = api.get('/api/workspace/dashboard').json()['kpis']['pending_documents']
    deposit(api, lid, 'jaune', 'Fiche de prix')
    _, by = rows(api, lid)
    assert by[('jaune', 'Fiche de prix')]['status'] == 'pending_validation'
    assert ('jaune', 'Fiche de prix') not in missing_on_dashboard(api, lid)
    board = api.get('/api/workspace/dashboard').json()
    assert board['kpis']['pending_documents'] == pending_before + 1
    assert any(p['launch_id'] == lid and p['title'] == 'Fiche de prix' and p['document_id'] for p in board['pending_validation_documents'])

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
    # Réception matière : contrôlée avant d'être présente.
    deposit(api, lid, 'rose', 'Document réception')
    _, by = rows(api, lid)
    assert by[('rose', 'Document de réception matière')]['status'] == 'pending_validation'


def test_duplicates_are_detected_reviewed_and_raised_again(api):
    lid = new_dossier(api, 'Chemise doublons')
    blob = b'Email logistique identique ' + uuid.uuid4().bytes
    first = deposit(api, lid, 'rose', 'Email', blob)
    assert api.get(f'/api/launches/{lid}/duplicates').json() == []
    second = deposit(api, lid, 'rose', 'Email', blob)
    assert second['duplicates'] and second['duplicates'][0]['document_id'] == first['id']   # alerte au dépôt
    groups = api.get(f'/api/launches/{lid}/duplicates').json()
    assert len(groups) == 1 and not groups[0]['reviewed']
    assert {d['document_id'] for d in groups[0]['documents']} == {first['id'], second['id']}
    board = api.get('/api/workspace/dashboard').json()
    entries = [d for d in board['duplicate_documents'] if d['launch_id'] == lid]
    assert len(entries) == 1 and entries[0]['folder'] == 'rose' and len(entries[0]['documents']) == 2
    assert board['kpis']['duplicate_documents'] == len(board['duplicate_documents'])
    # Un doublon n'altère pas la complétude : la pièce reste présente.
    _, by = rows(api, lid)
    assert by[('rose', 'Emails réception / logistique')]['status'] == 'present'

    digest = groups[0]['sha256']
    assert api.post(f'/api/launches/{lid}/duplicates/review', headers=H, json={'sha256': digest, 'reason': 'court'}).status_code == 422
    assert api.post(f'/api/launches/{lid}/duplicates/review', headers=H,
                    json={'sha256': '0' * 64, 'reason': 'Aucun groupe pour cette empreinte'}).status_code == 404
    reviewed = api.post(f'/api/launches/{lid}/duplicates/review', headers=H,
                        json={'sha256': digest, 'reason': 'Même email transmis par deux interlocuteurs'})
    assert reviewed.status_code == 201 and reviewed.json()[0]['reviewed'] and reviewed.json()[0]['review']['reason']
    assert not any(d['launch_id'] == lid for d in api.get('/api/workspace/dashboard').json()['duplicate_documents'])
    # Une nouvelle copie identique relance l'alerte : la décision ne couvrait que les pièces examinées.
    deposit(api, lid, 'jaune', 'Email', blob)
    groups = api.get(f'/api/launches/{lid}/duplicates').json()
    assert len(groups) == 1 and not groups[0]['reviewed'] and len(groups[0]['documents']) == 3
    # Corriger une pièce par une nouvelle version la retire du groupe.
    fixed = api.post(f"/api/documents/{second['id']}/versions", headers=H, files={'file': ('corrige.txt', b'Autre email', 'text/plain')})
    assert fixed.status_code == 201
    groups = api.get(f'/api/launches/{lid}/duplicates').json()
    assert second['id'] not in {d['document_id'] for d in groups[0]['documents']}
    events = api.get(f'/api/workspace/activity?launch_id={lid}&limit=50').json()['items']
    assert any(e['action'] == 'document.duplicate.review' for e in events)


def test_duplicates_never_reveal_unreadable_subfolders(api):
    from app.models import RolePermission
    lid = new_dossier(api, 'Doublon confidentiel')
    blob = b'Piece identique ' + uuid.uuid4().bytes
    deposit(api, lid, 'jaune', 'Commande client', blob)
    deposit(api, lid, 'vert', 'Facture', blob)
    assert len(api.get(f'/api/launches/{lid}/duplicates').json()) == 1
    email = f'jaune-{uuid.uuid4().hex}@test.local'
    with SessionLocal() as db:
        role = Role(name='Technique seule ' + uuid.uuid4().hex[:6])
        role.grants.extend([RolePermission(action='launch.read', folder_slug=None),
                            RolePermission(action='document.read', folder_slug='jaune')])
        db.add(User(name='Technicienne', email=email, password_hash=hash_password(PASSWORD), roles=[role]))
        db.commit()
    with TestClient(app) as other:
        assert other.post('/api/auth/login', headers=H, json={'email': email, 'password': PASSWORD}).status_code == 200
        assert other.get(f'/api/launches/{lid}/duplicates').json() == []
        assert not any(d['launch_id'] == lid for d in other.get('/api/workspace/dashboard').json()['duplicate_documents'])


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


def test_migration_0009_makes_standard_checklist_due_now_only(tmp_path, monkeypatch):
    migration = importlib.import_module('app.migrate')
    engine = create_engine('sqlite:///' + str(tmp_path / 'before-0009.db'))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE document_duplicate_reviews'))
        for revision in migration.REVISIONS[:migration.REVISIONS.index('0009_visible_checklist_duplicates')]:
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v,:d)'), {'v': revision, 'd': '2026-10-21'})
        conn.execute(text("INSERT INTO users (id,email,name,password_hash,active,created_at) VALUES ('u','u@example.test','U','h',1,'2026-01-01')"))
        for pid, name in (('std', STANDARD_PROFILE_NAME), ('other', 'Profil par étapes')):
            conn.execute(text("INSERT INTO completeness_profiles (id,name,description,created_by,created_at) VALUES (:i,:n,'','u','2026-01-01')"), {'i': pid, 'n': name})
        rules = (('r1', 'std', 'Test tissu', 'fabrication', 1), ('r2', 'std', 'Avoir', 'cloture', 0), ('r3', 'other', 'Test tissu', 'fabrication', 1),
                 ('r4', 'std', 'Document de réception matière', 'approvisionnement', 1))
        for rid, pid, title, phase, required in rules:
            conn.execute(text("INSERT INTO completeness_rules (id,profile_id,title,folder_slug,document_type,due_phase,requires_validation,active,guidance,required) "
                              "VALUES (:i,:p,:t,'jaune',:t,:ph,0,1,'',:r)"), {'i': rid, 'p': pid, 't': title, 'ph': phase, 'r': required})
    monkeypatch.setattr(migration, 'engine', engine)
    migration.migrate(); migration.migrate()
    assert 'document_duplicate_reviews' in inspect(engine).get_table_names()
    with engine.connect() as conn:
        phases = dict(conn.execute(text('SELECT id, due_phase FROM completeness_rules')).all())
    assert phases == {'r1': 'preparation', 'r2': 'cloture', 'r3': 'fabrication', 'r4': 'preparation'}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT requires_validation FROM completeness_rules WHERE id='r4'")).scalar() == 1
        assert conn.execute(text("SELECT requires_validation FROM completeness_rules WHERE id='r1'")).scalar() == 0
    engine.dispose()

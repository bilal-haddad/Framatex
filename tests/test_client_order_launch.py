"""Demande Client acceptée → Dossier Jaune : création unique, traçable et réservée à FRAMATEX."""
import importlib
import json
import secrets
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core import Base, SessionLocal, hash_password
from app.main import app
from app.models import AuditEvent, Folder, Launch, Role, User
from app.client_workflow_models import ClientOrderLaunch

H = {'X-Framatex-Request': '1'}
PASSWORD = secrets.token_urlsafe(18) + 'Aa1!'   # généré pour la durée des tests, jamais en dur


def _actors(stack):
    admin, client, worker = (stack.enter_context(TestClient(app)) for _ in range(3))
    suffix = uuid.uuid4().hex
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == 'Administrateur')) or Role(name='Administrateur')
        db.add_all([User(name='Admin lancement', email=f'admin-launch-{suffix}@test.local',
                         password_hash=hash_password(PASSWORD), roles=[role]),
                    User(name='Collaborateur', email=f'worker-launch-{suffix}@test.local',
                         password_hash=hash_password(PASSWORD))])
        db.commit()
    for api, who in ((admin, 'admin'), (worker, 'worker')):
        assert api.post('/api/auth/login', headers=H,
                        json={'email': f'{who}-launch-{suffix}@test.local', 'password': PASSWORD}).status_code == 200
    account = client.post('/api/client/register', headers=H, json={
        'raison_sociale': 'Maison Recette', 'nom_contact': 'Contact', 'email': f'client-launch-{suffix}@test.local',
        'telephone': '0600000000', 'adresse': 'Adresse fictive', 'pays': 'Maroc', 'password': PASSWORD}).json()
    assert admin.patch(f"/api/admin/clients/{account['id']}/status", headers=H, json={'status': 'active'}).status_code == 200
    assert client.post('/api/client/login', headers=H, json={'email': account['email'], 'password': PASSWORD}).status_code == 200
    return admin, client, worker


def _order(client, status='submitted'):
    response = client.post('/api/client/order-requests', headers=H, json={
        'article': 'Veste lin ' + uuid.uuid4().hex[:6], 'quantite': 950, 'date_souhaitee': '2027-03-15',
        'reference_client': 'REF-CLIENT-77', 'status': status})
    assert response.status_code == 201, response.text
    return response.json()


def test_accept_and_open_yellow_folder_once_with_full_traceability():
    from contextlib import ExitStack
    with ExitStack() as stack:
        admin, client, worker = _actors(stack)
        order = _order(client)
        route = f"/api/admin/client-order-requests/{order['id']}/launch"

        assert worker.post(route, headers=H).status_code == 403          # collaborateur sans rôle administrateur
        assert client.post(route, headers=H).status_code == 401          # une session Client n'ouvre pas l'API interne
        assert admin.post(route).status_code == 403                       # en-tête de protection obligatoire

        created = admin.post(route, headers=H)
        assert created.status_code == 201, created.text
        body = created.json()
        launch_id = body['launch']['id']
        assert body['created'] is True and body['order']['status'] == 'accepted'
        assert body['launch']['order_ref'] == order['request_number']

        detail = admin.get(f'/api/launches/{launch_id}').json()
        assert [f['slug'] for f in detail['folders']] == ['jaune', 'rose', 'bleu', 'vert']
        assert detail['client_name'] == 'Maison Recette' and order['article'] in detail['name']
        summary = admin.get(f'/api/launches/{launch_id}/operations').json()
        assert summary['article'] == order['article'] and summary['quantity'] == 950
        assert summary['client_request']['request_number'] == order['request_number']
        assert summary['client_request']['reference_client'] == 'REF-CLIENT-77'
        assert summary['client_request']['date_souhaitee'] == '2027-03-15'
        assert admin.get(f"/api/admin/client-order-requests/{order['id']}").json()['launch']['id'] == launch_id
        assert client.get(f"/api/client/order-requests/{order['id']}").json()['status'] == 'accepted'

        again = admin.post(route, headers=H)
        assert again.status_code == 200 and again.json()['created'] is False
        assert again.json()['launch']['id'] == launch_id
        with SessionLocal() as db:
            assert len(db.scalars(select(Launch).where(Launch.order_ref == order['request_number'])).all()) == 1
            assert len(db.scalars(select(Folder).where(Folder.launch_id == launch_id)).all()) == 4
            assert db.get(ClientOrderLaunch, order['id']).launch_id == launch_id
            actions = {row.action: json.loads(row.detail) for row in db.scalars(select(AuditEvent).where(
                AuditEvent.target_id.in_([order['id'], launch_id])))}
        assert actions['client.order_request.launch_created']['launch_id'] == launch_id
        assert actions['client.order_request.status_changed']['status'] == 'accepted'
        assert actions['launch.create']['client_order_request'] == order['request_number']


def test_only_sent_or_accepted_requests_can_open_a_folder():
    from contextlib import ExitStack
    with ExitStack() as stack:
        admin, client, _ = _actors(stack)
        draft = _order(client, status='draft')
        assert admin.post(f"/api/admin/client-order-requests/{draft['id']}/launch", headers=H).status_code == 409
        rejected = _order(client)
        assert admin.patch(f"/api/admin/client-order-requests/{rejected['id']}/status", headers=H,
                           json={'status': 'rejected'}).status_code == 200
        assert admin.post(f"/api/admin/client-order-requests/{rejected['id']}/launch", headers=H).status_code == 409
        accepted = _order(client)
        assert admin.patch(f"/api/admin/client-order-requests/{accepted['id']}/status", headers=H,
                           json={'status': 'accepted'}).status_code == 200
        opened = admin.post(f"/api/admin/client-order-requests/{accepted['id']}/launch", headers=H)
        assert opened.status_code == 201 and opened.json()['order']['status'] == 'accepted'
        assert admin.post('/api/admin/client-order-requests/inconnue/launch', headers=H).status_code == 404


def test_migration_adds_link_table_without_touching_existing_rows(tmp_path, monkeypatch):
    migration = importlib.import_module('app.migrate')
    engine = create_engine('sqlite:///' + str(tmp_path / 'before-0007.db'))
    Base.metadata.create_all(engine, tables=[t for name, t in Base.metadata.tables.items() if name != 'client_order_launches'])
    with engine.begin() as conn:
        for revision in migration.REVISIONS[:migration.REVISIONS.index('0007_client_order_launch')]:
            conn.execute(text('INSERT INTO schema_migrations VALUES (:v,:d)'), {'v': revision, 'd': '2026-10-21'})
    with Session(engine) as db:
        author = User(name='Auteur existant', email='auteur@example.test', password_hash='hash-preserve')
        db.add(author); db.flush()
        db.add(Launch(name='Dossier existant', order_ref='EXIST-1', created_by=author.id)); db.commit()
    monkeypatch.setattr(migration, 'engine', engine)
    migration.migrate(); migration.migrate()
    assert 'client_order_launches' in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM launches WHERE order_ref='EXIST-1'")).scalar() == 'Dossier existant'
        assert conn.execute(text("SELECT count(*) FROM schema_migrations WHERE version='0007_client_order_launch'")).scalar() == 1
    engine.dispose()

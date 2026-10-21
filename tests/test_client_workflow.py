"""Workflows Client : autorisation, versions, publication réelle et migrations."""
from contextlib import ExitStack
from datetime import date
import hashlib
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from app.core import Base, SessionLocal, hash_password
from app.main import app
from app.models import AuditEvent, Role, User
from app.client_models import ClientAccount, ClientOrderDocument, ClientOrderDocumentVersion, ClientOrderRequest
from app.client_workflow_models import ClientDocumentRequest, ClientDocumentRequestEvent, ClientSharedDocument

H = {'X-Framatex-Request': '1'}
PASSWORD = 'WorkflowClientPassword2026!'
NEW_TABLES = {'client_document_requests', 'client_document_request_events', 'client_shared_documents'}


@pytest.fixture(scope='module')
def actors():
    with ExitStack() as stack:
        admin, a, b, worker = [stack.enter_context(TestClient(app)) for _ in range(4)]
        suffix = uuid.uuid4().hex
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.name == 'Administrateur'))
            if not role:
                role = Role(name='Administrateur'); db.add(role)
            admin_user = User(name='FRAMATEX Workflow', email=f'admin-{suffix}@test.local',
                              password_hash=hash_password(PASSWORD), roles=[role])
            worker_user = User(name='Sans droit client', email=f'worker-{suffix}@test.local',
                               password_hash=hash_password(PASSWORD))
            db.add_all([admin_user, worker_user]); db.commit()
            admin_email, worker_email = admin_user.email, worker_user.email
        for api, email in ((admin, admin_email), (worker, worker_email)):
            assert api.post('/api/auth/login', headers=H, json={'email': email, 'password': PASSWORD}).status_code == 200
        accounts = []
        for api, label in ((a, 'A'), (b, 'B')):
            account = api.post('/api/client/register', headers=H, json={
                'raison_sociale': 'Entreprise ' + label, 'nom_contact': 'Contact ' + label,
                'email': f'client-{label}-{suffix}@test.local', 'telephone': '0600000000',
                'adresse': 'Adresse fictive', 'pays': 'Maroc', 'password': PASSWORD}).json()
            assert admin.patch(f"/api/admin/clients/{account['id']}/status", headers=H,
                               json={'status': 'active'}).status_code == 200
            assert api.post('/api/client/login', headers=H,
                            json={'email': account['email'], 'password': PASSWORD}).status_code == 200
            accounts.append(account)
        yield {'admin': admin, 'a': a, 'b': b, 'worker': worker, 'account_a': accounts[0], 'account_b': accounts[1]}


def create_order(api, status='submitted'):
    result = api.post('/api/client/order-requests', headers=H, json={
        'article': 'Modèle workflow ' + uuid.uuid4().hex[:6], 'quantite': 1800,
        'date_souhaitee': '2027-02-01', 'status': status})
    assert result.status_code == 201, result.text
    return result.json()


@pytest.fixture
def flow(actors):
    return {**actors, 'order': create_order(actors['a']), 'other_order': create_order(actors['b'])}


def ask(flow, title='Dossier technique'):
    result = flow['admin'].post(f"/api/admin/client-order-requests/{flow['order']['id']}/document-requests",
                headers=H, json={'title': title, 'description': 'Déposer la fiche du modèle à fabriquer.'})
    assert result.status_code == 201, result.text
    return result.json()


def upload(flow, item, blob=b'Dossier technique v1', filename='technique.txt'):
    return flow['a'].post(f"/api/client/document-requests/{item['id']}/upload", headers=H,
                          files={'file': (filename, blob, 'text/plain')})


def decide(flow, item, status, version_id=None, message=''):
    version_id = version_id or item['document']['versions'][-1]['id']
    return flow['admin'].patch(f"/api/admin/client-document-requests/{item['id']}/status", headers=H,
            json={'status': status, 'version_id': version_id, 'message': message})


def source_document(flow, kind='Confirmation de commande', title='Confirmation de commande',
                    filename='confirmation.txt', approve=True):
    admin = flow['admin']
    lid = admin.post('/api/launches', headers=H, json={'name': 'Lancement workflow', 'client_name': 'Entreprise A'}).json()['id']
    response = admin.post(f'/api/launches/{lid}/documents', headers=H,
               data={'folder': 'jaune', 'title': title, 'doc_type': kind},
               files={'file': (filename, b'Document commercial autorise v1')})
    assert response.status_code == 201, response.text
    doc = response.json()
    if approve:
        assert admin.post(f"/api/documents/{doc['id']}/reviews", headers=H,
                          json={'decision': 'approved', 'comment': 'Version autorisée pour le destinataire.'}).status_code == 201
    return doc


def publish(flow, doc, **values):
    return flow['admin'].post(f"/api/admin/clients/{flow['account_a']['id']}/shared-documents", headers=H,
            json={'document_version_id': doc['latest']['id'], 'order_request_id': flow['order']['id'],
                  'reason': 'Publication explicite autorisée pour ce client.', **values})


@pytest.mark.parametrize('status', ['under_review', 'accepted', 'rejected'])
def test_only_internal_admin_can_decide_order_status(flow, status):
    path = f"/api/admin/client-order-requests/{flow['order']['id']}/status"
    assert flow['a'].patch(path, headers=H, json={'status': status}).status_code == 401
    assert flow['worker'].patch(path, headers=H, json={'status': status}).status_code == 403
    assert flow['a'].patch(f"/api/client/order-requests/{flow['order']['id']}/status",
                           headers=H, json={'status': status}).status_code == 422
    response = flow['admin'].patch(path, headers=H, json={'status': status})
    assert response.status_code == 200, response.text
    assert flow['a'].get(f"/api/client/order-requests/{flow['order']['id']}").json()['status'] == status
    assert flow['b'].get(f"/api/client/order-requests/{flow['order']['id']}").status_code == 404
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.target_id == flow['order']['id'],
                           AuditEvent.action == 'client.order_request.status_changed'))
        assert event and 'submitted' in event.detail and status in event.detail


def test_draft_can_only_be_submitted_by_its_owner_and_terminal_states_are_locked(flow):
    order = create_order(flow['a'], 'draft')
    path = f"/api/client/order-requests/{order['id']}/status"
    assert flow['b'].patch(path, headers=H, json={'status': 'submitted'}).status_code == 404
    assert flow['admin'].patch(f"/api/admin/client-order-requests/{order['id']}/status", headers=H,
                              json={'status': 'accepted'}).status_code == 409
    assert flow['a'].patch(path, headers=H, json={'status': 'submitted'}).status_code == 200
    assert flow['a'].patch(path, headers=H, json={'status': 'draft'}).status_code == 409
    internal = f"/api/admin/client-order-requests/{order['id']}/status"
    assert flow['admin'].patch(internal, headers=H, json={'status': 'under_review'}).status_code == 200
    assert flow['admin'].patch(internal, headers=H, json={'status': 'rejected'}).status_code == 200
    assert flow['admin'].patch(internal, headers=H, json={'status': 'accepted'}).status_code == 409


def test_full_requested_document_cycle_preserves_versions_and_history(flow):
    item = ask(flow)
    assert item['status'] == 'requested' and item['requested_by'] == 'FRAMATEX Workflow'
    assert item['history'][0]['status'] == 'requested'
    assert flow['a'].get(f"/api/client/document-requests/{item['id']}").status_code == 200
    uploaded = upload(flow, item)
    assert uploaded.status_code == 201, uploaded.text
    item = uploaded.json()
    v1 = item['document']['versions'][0]
    assert v1['sha256'] == hashlib.sha256(b'Dossier technique v1').hexdigest()
    assert decide(flow, item, 'under_review').status_code == 200
    assert decide(flow, item, 'correction_required', message='Préciser la référence matière et le coloris.').status_code == 200
    corrected = upload(flow, item, b'Dossier technique corrige v2', 'technique-v2.txt')
    assert corrected.status_code == 201, corrected.text
    item = corrected.json()
    v2 = item['document']['versions'][-1]
    assert len(item['document']['versions']) == 2 and v2['number'] == 2
    assert decide(flow, item, 'accepted', version_id=v1['id']).status_code == 409
    accepted = decide(flow, item, 'accepted')
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body['accepted_at'] and body['status'] == 'accepted'
    assert [row['status'] for row in body['history']] == [
        'requested', 'uploaded', 'under_review', 'correction_required', 'uploaded', 'accepted']
    assert [row['version'] for row in body['history'] if row['status'] == 'uploaded'] == [1, 2]
    assert body['history'][3]['message'] == 'Préciser la référence matière et le coloris.'
    for number, content in ((1, b'Dossier technique v1'), (2, b'Dossier technique corrige v2')):
        path = f"/api/client/document-requests/{item['id']}/versions/{number}/download"
        assert flow['a'].get(path).content == content
        assert flow['b'].get(path).status_code == 404
    assert upload(flow, item).status_code == 409
    generic = flow['a'].post(f"/api/client/order-requests/{flow['order']['id']}/documents", headers=H,
                            data={'title': body['document']['title']}, files={'file': ('bypass.txt', b'bypass')})
    assert generic.status_code == 409
    with SessionLocal() as db:
        assert len(db.scalars(select(ClientDocumentRequestEvent).where(
            ClientDocumentRequestEvent.document_request_id == item['id'])).all()) == 6
        events = db.scalars(select(AuditEvent).where(AuditEvent.target_id == item['id'])).all()
        assert {'client.document_request.requested', 'client.document_request.uploaded',
                'client.document_request.correction_required', 'client.document_request.accepted'} <= {r.action for r in events}


def test_document_request_isolation_and_internal_authorization(flow):
    item = ask(flow)
    assert flow['b'].get(f"/api/client/document-requests/{item['id']}").status_code == 404
    assert item['id'] not in {r['id'] for r in flow['b'].get('/api/client/document-requests').json()}
    assert flow['b'].post(f"/api/client/document-requests/{item['id']}/upload", headers=H,
                          files={'file': ('x.txt', b'x')}).status_code == 404
    assert flow['a'].get('/api/client/document-requests', params={'order_request_id': flow['other_order']['id']}).status_code == 404
    path = f"/api/admin/client-order-requests/{flow['order']['id']}/document-requests"
    assert flow['a'].post(path, headers=H, json={'title': 'Fausse demande'}).status_code == 401
    assert flow['worker'].post(path, headers=H, json={'title': 'Fausse demande'}).status_code == 403
    assert flow['worker'].get(f"/api/admin/client-document-requests/{item['id']}").status_code == 403
    assert flow['a'].post('/api/client/document-requests', headers=H, json={'title': 'Fausse demande'}).status_code == 405


@pytest.mark.parametrize('name,blob,code', [('bad.exe', b'executable', 422), ('bad.pdf', b'not pdf', 422),
                                         ('empty.txt', b'', 422), ('large.txt', b'x' * (20*1024*1024+1), 413)])
def test_requested_upload_respects_existing_file_guards(flow, name, blob, code):
    item = ask(flow)
    assert upload(flow, item, blob, name).status_code == code
    assert flow['a'].get(f"/api/client/document-requests/{item['id']}").json()['status'] == 'requested'


def test_review_requires_actual_current_version_and_a_correction_message(flow):
    item = ask(flow)
    assert decide(flow, item, 'accepted', version_id=str(uuid.uuid4())).status_code == 409
    item = upload(flow, item).json()
    assert decide(flow, item, 'correction_required').status_code == 422
    assert upload(flow, item).status_code == 409
    assert flow['worker'].patch(f"/api/admin/client-document-requests/{item['id']}/status", headers=H,
        json={'status': 'accepted', 'version_id': item['document']['versions'][0]['id']}).status_code == 403


def test_requested_documents_same_title_have_independent_versions(flow):
    first, second = ask(flow), ask(flow)
    a, b = upload(flow, first).json(), upload(flow, second).json()
    assert a['document']['id'] != b['document']['id']
    assert len(a['document']['versions']) == len(b['document']['versions']) == 1


def test_explicit_share_revoke_and_republish_preserve_internal_document(flow):
    doc = source_document(flow)
    before = flow['a'].get('/api/client/shared-documents').json()
    assert doc['id'] not in str(before)
    published = publish(flow, doc)
    assert published.status_code == 201, published.text
    item = published.json()
    assert publish(flow, doc).status_code == 409
    visible = flow['a'].get('/api/client/shared-documents').json()
    current = next(r for r in visible if r['id'] == item['id'])
    assert 'reason' not in current and 'folder' not in current and 'document_version_id' not in current
    url = f"/api/client/shared-documents/{item['id']}/download"
    assert flow['a'].get(url).content == b'Document commercial autorise v1'
    assert flow['b'].get(url).status_code == 404
    assert item['id'] not in {r['id'] for r in flow['b'].get('/api/client/shared-documents').json()}
    revoked = flow['admin'].post(f"/api/admin/client-shared-documents/{item['id']}/revoke", headers=H,
                                 json={'reason': 'Retrait demandé après nouvelle instruction.'})
    assert revoked.status_code == 200 and revoked.json()['status'] == 'revoked'
    assert flow['a'].get(url).status_code == 404
    assert item['id'] not in {r['id'] for r in flow['a'].get('/api/client/shared-documents').json()}
    assert flow['admin'].get(f"/api/documents/{doc['id']}/versions/1/download").content == b'Document commercial autorise v1'
    assert publish(flow, doc).status_code == 201
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.target_id == item['id'])).all()
        assert {'client.shared_document.published', 'client.shared_document.revoked'} <= {r.action for r in rows}


@pytest.mark.parametrize('kind,title,name,approved', [
    ('Fiche de prix', 'Fiche de prix', 'prix.txt', True),
    ('Dossier technique client', 'Document interne confidentiel', 'tech.txt', True),
    ('Dossier technique client', 'Technique', 'prix_interne.txt', True),
    ('Dossier technique client', 'Technique', 'tech.txt', False),
    ('Autre', 'Document sans type autorisé', 'autre.txt', True)])
def test_sensitive_unapproved_or_unlisted_documents_cannot_be_shared(flow, kind, title, name, approved):
    doc = source_document(flow, kind, title, name, approved)
    assert publish(flow, doc).status_code == 422
    assert doc['id'] not in str(flow['a'].get('/api/client/shared-documents').json())
    assert flow['a'].get(f"/api/documents/{doc['id']}/versions/1/download").status_code == 401


def test_share_is_tied_to_selected_version_not_future_versions(flow):
    doc = source_document(flow)
    v2 = flow['admin'].post(f"/api/documents/{doc['id']}/versions", headers=H,
                           files={'file': ('confirmation-v2.txt', b'Nouvelle version interne non publiee')})
    assert v2.status_code == 201
    shared = publish(flow, doc)
    assert shared.status_code == 201, shared.text
    assert shared.json()['version'] == 1
    assert flow['a'].get(f"/api/client/shared-documents/{shared.json()['id']}/download").content == b'Document commercial autorise v1'
    assert publish(flow, v2.json()).status_code == 422


def test_only_admin_can_publish_and_recipient_order_must_match(flow):
    doc = source_document(flow)
    path = f"/api/admin/clients/{flow['account_a']['id']}/shared-documents"
    payload = {'document_version_id': doc['latest']['id'], 'reason': 'Publication test vers compte identifié.'}
    assert flow['a'].post(path, headers=H, json=payload).status_code == 401
    assert flow['worker'].post(path, headers=H, json=payload).status_code == 403
    assert publish(flow, doc, order_request_id=flow['other_order']['id']).status_code == 422
    assert flow['worker'].get('/api/admin/client-share-candidates').status_code == 403
    assert flow['a'].get('/api/admin/client-share-candidates').status_code == 401


def test_existing_simulated_publication_never_grants_real_client_access(flow):
    from app.models import Document
    doc = source_document(flow, kind='Fiche technique', title='Fiche de prévisualisation uniquement', filename='fiche.txt')
    with SessionLocal() as db:
        launch_id = db.get(Document, doc['id']).folder.launch_id
    before = flow['a'].get('/api/client/shared-documents').json()
    simulated = flow['admin'].post(f'/api/launches/{launch_id}/client-publications', headers=H,
        json={'document_version_id': doc['latest']['id'], 'reason': 'Aperçu interne existant, sans destinataire permanent.'})
    assert simulated.status_code == 201, simulated.text
    after = flow['a'].get('/api/client/shared-documents').json()
    assert after == before
    assert not any(item['title'] == doc['title'] for item in after)


def test_damaged_internal_file_is_not_published_or_downloaded(flow):
    from app.main import STORAGE
    from app.models import DocumentVersion
    doc = source_document(flow)
    shared = publish(flow, doc).json()
    with SessionLocal() as db:
        path = STORAGE / db.get(DocumentVersion, doc['latest']['id']).disk_name
    path.write_bytes(b'Contenu altere')
    assert flow['a'].get(f"/api/client/shared-documents/{shared['id']}/download").status_code == 503
    assert flow['admin'].post(f"/api/admin/client-shared-documents/{shared['id']}/revoke", headers=H,
                              json={'reason': 'Intégrité du fichier non confirmée.'}).status_code == 200
    assert publish(flow, doc).status_code == 409


def test_no_internal_comments_audit_or_experience_exposed_to_client(flow):
    doc = source_document(flow)
    flow['admin'].post(f"/api/document-versions/{doc['latest']['id']}/comments", headers=H,
                       json={'body': 'SECRET-COMMENTAIRE-INTERNE'})
    item = ask(flow)
    uploaded = upload(flow, item).json()
    publish(flow, doc)
    for path in ('/api/client/shared-documents', '/api/client/document-requests',
                 f"/api/client/order-requests/{flow['order']['id']}"):
        body = flow['a'].get(path).text
        assert 'SECRET-COMMENTAIRE-INTERNE' not in body
        assert 'password_hash' not in body
    for path in ('/api/workspace/activity', '/api/admin/audit', '/api/workspace/experience',
                 f"/api/document-versions/{doc['latest']['id']}/comments"):
        assert flow['a'].get(path).status_code == 401


@pytest.mark.parametrize('status,code', [('pending', 'account_pending'), ('suspended', 'account_suspended')])
def test_inactive_login_status_is_revealed_only_after_password_verification(actors, status, code):
    email = 'inactive-' + uuid.uuid4().hex + '@test.local'
    with TestClient(app) as client:
        account = client.post('/api/client/register', headers=H, json={
            'raison_sociale': 'Compte inactif', 'nom_contact': 'Contact inactif', 'email': email,
            'telephone': '0600000000', 'adresse': 'Adresse', 'pays': 'Maroc', 'password': PASSWORD}).json()
        if status == 'suspended':
            actors['admin'].patch(f"/api/admin/clients/{account['id']}/status", headers=H, json={'status': status})
        wrong = client.post('/api/client/login', headers=H, json={'email': email, 'password': 'WrongPassword2026!'})
        absent = client.post('/api/client/login', headers=H,
                             json={'email': 'absent-' + uuid.uuid4().hex + '@test.local', 'password': 'WrongPassword2026!'})
        assert wrong.status_code == absent.status_code == 401
        assert wrong.json() == absent.json() == {'detail': 'Identifiants incorrects'}
        correct = client.post('/api/client/login', headers=H, json={'email': email, 'password': PASSWORD})
        assert correct.status_code == 403 and correct.json()['detail']['code'] == code
        assert 'framat_client_session' not in client.cookies


def test_unknown_email_still_runs_password_verification(monkeypatch, actors):
    from app import client_routes
    called = []
    original = client_routes.check_password
    def checked(digest, plain):
        called.append(digest)
        return original(digest, plain)
    monkeypatch.setattr(client_routes, 'check_password', checked)
    with TestClient(app) as client:
        assert client.post('/api/client/login', headers=H,
            json={'email': 'missing-' + uuid.uuid4().hex + '@test.local', 'password': PASSWORD}).status_code == 401
    assert called == [client_routes._DUMMY_CLIENT_HASH]


def test_document_request_concurrent_review_does_not_overwrite_history(flow):
    from sqlalchemy.orm.exc import StaleDataError
    item = upload(flow, ask(flow)).json()
    with SessionLocal() as first, SessionLocal() as second:
        left, right = first.get(ClientDocumentRequest, item['id']), second.get(ClientDocumentRequest, item['id'])
        left.status = 'under_review'; first.commit()
        right.status = 'accepted'
        with pytest.raises(StaleDataError):
            second.commit()


@pytest.mark.parametrize('existing', [False, True])
def test_additive_migration_on_empty_and_existing_database(tmp_path, monkeypatch, existing):
    migration = importlib.import_module('app.migrate')
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.db'))
    if existing:
        Base.metadata.create_all(engine, tables=[table for name, table in Base.metadata.tables.items() if name not in NEW_TABLES])
        with engine.begin() as conn:
            for revision in migration.REVISIONS[:migration.REVISIONS.index('0006_client_workflow')]:
                conn.execute(text('INSERT INTO schema_migrations VALUES (:v,:d)'), {'v': revision, 'd': '2026-10-21'})
        with Session(engine) as db:
            account = ClientAccount(client_code='CL-PRESERVE', raison_sociale='Client conservé', nom_contact='Contact',
                email='keep@example.test', telephone='0600000000', adresse='Adresse', pays='Maroc', password_hash='hash-preserve', status='active')
            db.add(account); db.flush()
            order = ClientOrderRequest(client_id=account.id, request_number='REQ-KEEP', article='Article', quantite=50,
                date_souhaitee=date(2027,1,1), status='submitted')
            db.add(order); db.flush()
            document = ClientOrderDocument(order_request_id=order.id, title='Document conservé')
            db.add(document); db.flush()
            db.add(ClientOrderDocumentVersion(document_id=document.id, number=1, original_name='keep.txt', disk_name='keep-disk',
                content_type='text/plain', size=3, sha256='a'*64, uploaded_by_client_id=account.id))
            db.commit(); account_id, order_id = account.id, order.id
    monkeypatch.setattr(migration, 'engine', engine)
    migration.migrate(); migration.migrate()
    assert NEW_TABLES.issubset(inspect(engine).get_table_names())
    with Session(engine) as db:
        assert db.scalar(select(ClientDocumentRequest.id)) is None
        assert db.scalar(select(ClientSharedDocument.id)) is None
        if existing:
            assert db.get(ClientAccount, account_id).password_hash == 'hash-preserve'
            assert db.get(ClientOrderRequest, order_id).status == 'submitted'
            assert db.scalar(select(ClientOrderDocumentVersion.sha256)) == 'a'*64
    if existing:
        assert list(tmp_path.glob('migration.db.backup-*'))
    engine.dispose()

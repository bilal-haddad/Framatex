import os
import tempfile
from datetime import date, timedelta

os.environ.setdefault("FRAMATEX_DATA_DIR", tempfile.mkdtemp(prefix="framat-client-test-"))
os.environ.setdefault("FRAMATEX_SECRET_KEY", "client-test-secret-" * 3)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.client_models import ClientAccount
from app.core import SessionLocal, hash_password
from app.main import app
from app.models import Role, User

HEADERS = {"X-Framatex-Request": "1"}
PASSWORD = "ClientPassword2026!"


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.name == "Administrateur"))
            if not role:
                role = Role(name="Administrateur")
                db.add(role)
            admin = db.scalar(select(User).where(User.email == "client-admin@test.local"))
            if not admin:
                admin = User(name="Admin Client", email="client-admin@test.local",
                             password_hash=hash_password("AdminClientPassword2026!"))
                admin.roles.append(role)
                db.add(admin)
            operator = db.scalar(select(User).where(User.email == "operator@test.local"))
            if not operator:
                db.add(User(name="Opérateur", email="operator@test.local",
                            password_hash=hash_password("OperatorPassword2026!")))
            db.commit()
        yield client


def registration(email, company):
    return {"raison_sociale": company, "nom_contact": "Contact Test", "email": email,
            "telephone": "+212600000000", "adresse": "1 rue de test",
            "pays": "Maroc", "identifiant_fiscal": "ICE-TEST", "password": PASSWORD}


def activate(api, client_id):
    assert api.post("/api/auth/login", json={"email": "client-admin@test.local",
                    "password": "AdminClientPassword2026!"}, headers=HEADERS).status_code == 200
    response = api.patch(f"/api/admin/clients/{client_id}/status",
                         json={"status": "active"}, headers=HEADERS)
    assert response.status_code == 200, response.text


def client_login(api, email, password=PASSWORD):
    return api.post("/api/client/login", json={"email": email, "password": password}, headers=HEADERS)


def test_registration_is_pending_unique_and_password_is_hashed(api):
    response = api.post("/api/client/register", json=registration("client-a@test.local", "Client A"),
                        headers=HEADERS)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["client_code"].startswith("CL-")
    assert "password" not in body and "password_hash" not in body
    with SessionLocal() as db:
        account = db.get(ClientAccount, body["id"])
        assert account.password_hash != PASSWORD
        assert account.password_hash.startswith("$argon2")
    duplicate = api.post("/api/client/register",
                         json=registration("CLIENT-A@test.local", "Doublon"), headers=HEADERS)
    assert duplicate.status_code == 409
    api.app.state.client_a = body["id"]


def test_pending_account_cannot_login_or_use_business_routes(api):
    assert client_login(api, "client-a@test.local").status_code == 403
    assert api.get("/api/client/me").status_code == 401
    assert api.post("/api/client/order-requests", json={
        "article": "Chemise", "quantite": 100,
        "date_souhaitee": (date.today() + timedelta(days=30)).isoformat()
    }, headers=HEADERS).status_code == 401


def test_internal_admin_activation_and_client_login(api):
    assert api.post("/api/auth/login", json={"email": "operator@test.local",
                    "password": "OperatorPassword2026!"}, headers=HEADERS).status_code == 200
    assert api.patch(f"/api/admin/clients/{api.app.state.client_a}/status",
                     json={"status": "active"}, headers=HEADERS).status_code == 403
    activate(api, api.app.state.client_a)
    response = client_login(api, "client-a@test.local")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    me = api.get("/api/client/me")
    assert me.status_code == 200
    assert me.json()["id"] == api.app.state.client_a


def test_create_and_list_order_request(api):
    response = api.post("/api/client/order-requests", json={
        "article": "Chemise Oxford", "quantite": 250,
        "date_souhaitee": (date.today() + timedelta(days=45)).isoformat(),
        "reference_client": "PO-A-42", "commentaire": "Coloris bleu",
        "status": "submitted"
    }, headers=HEADERS)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request_number"].startswith("DR-")
    assert body["status"] == "submitted"
    listing = api.get("/api/client/order-requests")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [body["id"]]
    api.app.state.order_a = body["id"]


def test_document_hash_versioning_and_download(api):
    url = f"/api/client/order-requests/{api.app.state.order_a}/documents"
    first = api.post(url, data={"title": "Spécification"},
                     files={"file": ("spec.txt", b"version une", "text/plain")}, headers=HEADERS)
    assert first.status_code == 201, first.text
    assert len(first.json()["versions"][0]["sha256"]) == 64
    second = api.post(url, data={"title": "Spécification"},
                      files={"file": ("spec-v2.txt", b"version deux", "text/plain")}, headers=HEADERS)
    assert second.status_code == 201, second.text
    assert [v["number"] for v in second.json()["versions"]] == [1, 2]
    document_id = second.json()["id"]
    download = api.get(f"{url}/{document_id}/versions/2/download")
    assert download.status_code == 200
    assert download.content == b"version deux"


def test_client_data_isolation_and_unauthenticated_denial(api):
    second = api.post("/api/client/register", json=registration("client-b@test.local", "Client B"),
                      headers=HEADERS)
    assert second.status_code == 201
    activate(api, second.json()["id"])
    assert client_login(api, "client-b@test.local").status_code == 200
    assert api.get(f"/api/client/order-requests/{api.app.state.order_a}").status_code == 404
    assert api.get("/api/client/order-requests").json() == []
    assert api.post("/api/client/logout", headers=HEADERS).status_code == 200
    assert api.get("/api/client/order-requests").status_code == 401


def test_suspended_client_session_is_rejected(api):
    assert client_login(api, "client-a@test.local").status_code == 200
    assert api.patch(f"/api/admin/clients/{api.app.state.client_a}/status",
                     json={"status": "suspended"}, headers=HEADERS).status_code == 200
    assert api.get("/api/client/me").status_code == 403

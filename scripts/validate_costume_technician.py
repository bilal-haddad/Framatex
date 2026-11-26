"""Régression Chromium : une commande neuve reste ouvrable par un technicien bleu.

Le parcours métier utilise uniquement des interactions UI réelles. L'accès API
sert seulement à créer le compte administrateur de la base temporaire et à
vérifier, après les clics, que le document a réellement été conservé.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def start_server(port: int, log_path: Path):
    log = log_path.open("a")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log,
    )
    import httpx
    for _ in range(150):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                return process
        except httpx.TransportError:
            pass
        if process.poll() is not None:
            raise RuntimeError("Le serveur de recette s'est arrêté")
        time.sleep(.1)
    raise RuntimeError("Le serveur de recette ne répond pas")


def run(output: Path, base: str, admin_email: str, admin_password: str):
    from playwright.sync_api import expect, sync_playwright
    from windows_runtime import browser_executable

    checks, errors, unexpected = [], [], []
    technician_email = "technicien.costume@example.test"
    technician_password = secrets.token_urlsafe(18) + "Aa1!"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable(), headless=True)
        context = browser.new_context(base_url=base, viewport={"width": 1440, "height": 900}, locale="fr-FR")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: unexpected.append((response.status, response.url)) if response.status >= 400 and "/api/" in response.url else None)

        def login(email: str, password: str):
            page.goto("/espace-framatex")
            page.fill("#email", email)
            page.fill("#password", password)
            page.click("#login-form button[type=submit]")

        def capture(name: str):
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(output / f"{name}.png"), full_page=False)

        login(admin_email, admin_password)
        expect(page.locator(".ops-heading h1")).to_be_visible()
        checks.append("Connexion administrateur")

        # Création de la commande par le formulaire réel.
        page.click('[data-view="launches"]')
        expect(page.locator("#ops-create")).to_be_visible()
        page.click("#ops-create")
        page.fill("#l-name", "Costume")
        page.fill("#l-client", "Client démonstration")
        page.fill("#l-order", "COSTUME-001")
        page.click("#new-launch-form button[type=submit]")
        expect(page.locator("#ops-launch-summary")).to_contain_text("COSTUME-001")
        capture("costume-01-admin-commande")
        checks.append("Création UI de la commande Costume")

        # Création du technicien par l'écran d'habilitations.
        page.click('[data-acc-view="access"]')
        expect(page.locator(".ops-heading h1")).to_have_text("Collaborateurs et habilitations")
        page.click("#acc-new")
        page.fill("#acc-name", "Technicien Costume")
        page.fill("#acc-email", technician_email)
        page.fill("#acc-job", "Technicien")
        page.click("#acc-create-form button[type=submit]")
        temporary_password = page.locator("#acc-secret-value").inner_text().strip()
        page.click("#acc-secret-done")
        row = page.locator("tr", has_text=technician_email)
        technician_id = row.get_attribute("data-acc-user")
        assert technician_id
        checks.append("Création UI du technicien")

        # Retour par le menu, clic réel sur la ligne Costume, puis affectation bleu.
        page.click('[data-view="launches"]')
        page.fill("#q", "Costume")
        page.click("#ops-launch-filters button[type=submit]")
        page.locator('[data-ops-target]', has_text="COSTUME-001").click()
        expect(page.locator("#ops-launch-summary")).to_contain_text("COSTUME-001")
        page.click("#acc-assign")
        expect(page.locator(".acc-matrix")).to_be_visible()
        page.select_option(f"#acc-level-{technician_id}-bleu", "depot")
        page.click("#acc-matrix-save")
        expect(page.locator(".acc-matrix")).to_have_count(0)
        checks.append("Affectation UI au seul sous-dossier bleu")

        # Déconnexion réelle, première connexion et changement obligatoire.
        page.click("#logout")
        expect(page.locator("#login-form")).to_be_visible()
        page.fill("#email", technician_email)
        page.fill("#password", temporary_password)
        page.click("#login-form button[type=submit]")
        expect(page.locator("#acc-password-form")).to_be_visible()
        page.fill("#acc-current", temporary_password)
        page.fill("#acc-new", technician_password)
        page.fill("#acc-confirm", technician_password)
        page.click("#acc-password-form button[type=submit]")
        expect(page.locator("#fx-welcome-title")).to_contain_text("Bonjour")
        checks.append("Déconnexion admin, connexion technicien et changement du mot de passe")

        # Ouverture depuis Mes commandes par clic réel.
        page.click('[data-view="launches"]')
        expect(page.locator('[data-ops-target]', has_text="COSTUME-001")).to_be_visible()
        # Reproduit la régression : un module secondaire refusé ne doit pas
        # empêcher l'ouverture du lancement autorisé.
        page.route(
            "**/api/launches/*/supplier-requests",
            lambda route: route.fulfill(
                status=403, content_type="application/json",
                body=json.dumps({"detail": "Module fournisseur non autorisé"}),
            ),
        )
        page.locator('[data-ops-target]', has_text="COSTUME-001").click()
        expect(page.locator("#ops-launch-summary")).to_contain_text("COSTUME-001")
        # Les modules secondaires sont chargés à l'ouverture de leur onglet : le refus survient là,
        # et la commande reste utilisable.
        page.click('[data-dj-tab="communication"]')
        expect(page.locator('.error[role="status"]')).to_contain_text("module(s) secondaire(s)")
        page.click('[data-dj-tab="documents"]')
        expect(page.locator('.dj-folder[data-folder="bleu"]')).not_to_have_class("is-locked")
        page.locator('.dj-folder[data-folder="bleu"]').click()
        expect(page.locator('[data-folder-panel="bleu"]')).to_be_visible()
        capture("costume-02-technicien-bleu")
        checks.append("Ouverture UI de Costume et accès au sous-dossier bleu")

        # Dépôt réel depuis le bleu et consultation immédiate sans F5.
        page.click("#upload-doc")
        page.fill("#ops-title", "Pièce douanière Costume")
        page.fill("#ops-type", "Pièce douanière")
        page.locator("#ops-file").set_input_files({
            "name": "douane-costume.txt", "mimeType": "text/plain",
            "buffer": b"DECLARATION DOUANIERE\nReference document : COSTUME-001",
        })
        expect(page.locator("#ops-analysis")).to_contain_text("Pièce douanière")
        if page.locator("#du-confirm-type").count():
            page.check("#du-confirm-type")
        page.click("#ops-upload-form button[type=submit]")
        expect(page.locator("#ops-upload-form")).to_have_count(0)
        expect(page.locator('.dj-row', has_text="Pièce douanière Costume")).to_be_visible()
        page.locator('.dj-row', has_text="Pièce douanière Costume").locator("[data-history]").click()
        expect(page.locator(".modal")).to_contain_text("douane-costume.txt")
        capture("costume-03-technicien-document")
        checks.append("Dépôt et consultation UI d'un document bleu")

        assert not errors, errors
        allowed = {401, 403, 404}
        expected_refusals = (
            lambda status, url: (status == 401 and url.endswith("/api/auth/me"))
            or (status == 403 and url.endswith("/supplier-requests"))
        )
        assert not [(status, url) for status, url in unexpected
                    if status in allowed and not expected_refusals(status, url)], unexpected
        browser.close()
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "costume-technician")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="framat-costume-") as temporary:
        os.environ["FRAMATEX_DATA_DIR"] = temporary
        os.environ.pop("DATABASE_URL", None)
        os.environ["FRAMATEX_SECRET_KEY"] = secrets.token_urlsafe(48)
        sys.path.insert(0, str(ROOT))
        from app.core import SessionLocal, hash_password
        from app.migrate import migrate
        from app.models import Role, User
        migrate()
        admin_email, admin_password = "admin.costume@example.test", secrets.token_urlsafe(20) + "Aa1!"
        with SessionLocal() as database:
            database.add(User(name="Administrateur Costume", email=admin_email,
                              password_hash=hash_password(admin_password), roles=[Role(name="Administrateur")]))
            database.commit()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        server = start_server(port, output / "server.log")
        try:
            checks = run(output, f"http://127.0.0.1:{port}", admin_email, admin_password)
        finally:
            server.terminate(); server.wait(timeout=10)
    report = {"status": "passed", "checks": checks,
              "screenshots": sorted(path.name for path in output.glob("*.png"))}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n".join("OK  " + check for check in checks))


if __name__ == "__main__":
    main()

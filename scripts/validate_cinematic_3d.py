"""Recette Chromium des visuels cinématiques existants (sans appel métier JS)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def wait_server(base: str, process: subprocess.Popen):
    import httpx
    for _ in range(150):
        try:
            if httpx.get(base + "/api/health", timeout=1, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            raise RuntimeError("Le serveur de recette s'est arrêté")
        time.sleep(.1)
    raise RuntimeError("Le serveur de recette ne répond pas")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(base: str, output: Path):
    from playwright.sync_api import expect, sync_playwright
    from windows_runtime import browser_executable

    checks, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable(), headless=True)
        desktop = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="no-preference")
        page = desktop.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: errors.append(f"requête échouée: {request.url}"))
        page.goto(base, wait_until="networkidle")

        folder = page.locator("[data-folder3d]")
        folder.scroll_into_view_if_needed()
        expect(folder).to_have_class(re.compile(r"\bis-3d\b"), timeout=15000)
        canvas = folder.locator("canvas.fd3-canvas")
        expect(canvas).to_be_visible()
        first = canvas.screenshot(path=str(output / "cinematic-folder-start.png"))
        page.mouse.wheel(0, 900); page.wait_for_timeout(700)
        second = canvas.screenshot(path=str(output / "cinematic-folder-progress.png"))
        assert digest(first) != digest(second), "La scène Dossier Jaune ne change pas pendant le défilement"
        assert folder.locator("[data-fd-step].is-current").count() == 1
        checks.append("Dossier Jaune Three.js chargé et animé par défilement à 1440 px")

        fabric = page.locator("[data-fabric3d]").first
        fabric.scroll_into_view_if_needed()
        expect(fabric).to_have_class(re.compile(r"\bhas-fabric3d\b"), timeout=15000)
        cloth = fabric.locator("canvas.fabric3d-canvas")
        expect(cloth).to_be_visible()
        cloth_box = cloth.bounding_box()
        page.mouse.move(cloth_box["x"] + cloth_box["width"] * .25, cloth_box["y"] + cloth_box["height"] * .5)
        before = cloth.screenshot(path=str(output / "cinematic-fabric-start.png"))
        page.wait_for_timeout(650)
        page.mouse.move(cloth_box["x"] + cloth_box["width"] * .75, cloth_box["y"] + cloth_box["height"] * .4)
        page.wait_for_timeout(650)
        after = cloth.screenshot(path=str(output / "cinematic-fabric-progress.png"))
        assert digest(before) != digest(after), "Le tissu 3D ne produit aucune variation temporelle"
        checks.append("Tissu Three.js chargé, animé et réactif au pointeur à 1440 px")

        carousel = page.locator("[data-carousel]")
        carousel.scroll_into_view_if_needed(); expect(carousel).to_have_class(re.compile(r"\bis-ready\b"))
        carousel.locator("[data-pcar-pause]").click()
        active_before = int(carousel.locator('[data-pcar-dot][aria-current="true"]').get_attribute("data-pcar-dot"))
        carousel.locator("[data-pcar-next]").click()
        expect(carousel.locator(f'[data-pcar-dot="{(active_before + 1) % 3}"]')).to_have_attribute("aria-current", "true")
        carousel.locator(".pcar-slide.is-active [data-pcar-open]").click()
        expect(carousel.locator(".pcar-lightbox")).to_be_visible()
        carousel.locator("[data-pcar-close]").click()
        expect(carousel.locator(".pcar-lightbox")).not_to_be_visible()
        page.screenshot(path=str(output / "cinematic-carousel.png"), full_page=False)
        checks.append("Carrousel : flèche, indicateur, agrandissement et fermeture par clics réels")
        assert not errors, errors
        desktop.close()

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = mobile.new_page(); mobile_errors = []
        page.on("pageerror", lambda error: mobile_errors.append(str(error)))
        page.goto(base, wait_until="networkidle")
        folder = page.locator("[data-folder3d]"); folder.scroll_into_view_if_needed()
        expect(folder).to_have_class(re.compile(r"\bis-static\b"))
        expect(folder.locator(".fd3-static")).to_be_visible()
        expect(folder.locator("canvas.fd3-canvas")).not_to_be_visible()
        assert page.locator("canvas.fabric3d-canvas").count() == 0
        page.screenshot(path=str(output / "cinematic-mobile-fallback.png"), full_page=False)
        assert not mobile_errors, mobile_errors
        checks.append("390 px : alternatives statiques présentes, aucun WebGL coûteux ni erreur JS")
        mobile.close(); browser.close()
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cinematic-3d")
    output = parser.parse_args().output.resolve(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="framat-cinematic-") as temporary:
        env = {**os.environ, "FRAMATEX_DATA_DIR": temporary, "FRAMATEX_SECRET_KEY": secrets.token_urlsafe(48)}
        __import__('recette_db').use_isolated_database(env)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with (output / "server.log").open("w") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=log,
            )
        try:
            wait_server(base, server); checks = run(base, output)
        finally:
            server.terminate(); server.wait(timeout=10)
    result = {"status": "passed", "checks": checks}
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n".join("OK  " + check for check in checks))


if __name__ == "__main__":
    main()

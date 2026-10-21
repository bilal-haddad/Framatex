"""Démarrage local sous Windows : types MIME des fichiers statiques.

Sous Windows, ``mimetypes`` lit le registre au premier usage et ses valeurs
remplacent celles de Python ; ``.js`` y est souvent déclaré en ``text/plain``.
Avec ``X-Content-Type-Options: nosniff``, Chrome refuserait alors scripts et
styles. Ce test reproduit cet ordre d'initialisation sur n'importe quel système.
"""
import mimetypes

from fastapi.testclient import TestClient

from app.main import app, register_web_mime_types


def _polluted_registry(self, strict=True):
    # Valeurs rencontrées sur des postes Windows réels.
    self.add_type('text/plain', '.js', True)
    self.add_type('text/plain', '.css', True)
    self.add_type('application/octet-stream', '.webp', True)


def test_web_assets_keep_browser_types_despite_windows_registry(monkeypatch):
    monkeypatch.setattr(mimetypes.MimeTypes, 'read_windows_registry', _polluted_registry)
    monkeypatch.setattr(mimetypes, '_db', None)
    monkeypatch.setattr(mimetypes, 'inited', False)
    monkeypatch.setattr(mimetypes, 'knownfiles', [])  # pas de /etc/mime.types sous Windows
    mimetypes.init()
    assert mimetypes.guess_type('x.js')[0] == 'text/plain'  # le registre simulé a bien pris la main

    register_web_mime_types()

    with TestClient(app) as client:
        expected = {
            '/assets/client/client.js': 'text/javascript',
            '/assets/app.js': 'text/javascript',
            '/assets/brand/tokens.css': 'text/css',
            '/assets/landing/landing.css': 'text/css',
            '/assets/landing/redesign/notre-solution.webp': 'image/webp',
            '/assets/brand/fonts/dm-sans-latin-400-normal.woff2': 'font/woff2',
        }
        for path, media_type in expected.items():
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers['content-type'].split(';')[0] == media_type, (path, response.headers['content-type'])
            assert response.headers['x-content-type-options'] == 'nosniff'
    monkeypatch.undo()
    mimetypes.init()
    register_web_mime_types()


def test_windows_launcher_has_no_typographic_quotes():
    # PowerShell traite ’ ‘ comme des apostrophes et “ ” comme des guillemets : une
    # apostrophe typographique dans un message coupe la chaîne et casse tout le script.
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / 'scripts' / 'start_windows.ps1').read_text(encoding='utf-8-sig')
    offenders = [n for n, line in enumerate(script.splitlines(), 1) if any(c in line for c in '‘’“”')]
    assert not offenders, f'Guillemets typographiques aux lignes {offenders}'


def test_boot_assets_are_not_cached_and_csp_is_unchanged():
    with TestClient(app) as client:
        for path in ('/', '/espace-framatex', '/espace-client', '/assets/app.js', '/assets/boot-guard.js', '/assets/client/api.js'):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
        response = client.get('/espace-framatex')
        assert "script-src 'self';" in response.headers['content-security-policy']
        assert 'boot-guard.js' in response.text


def test_health_identity_only_in_managed_local_runtime(monkeypatch):
    import os
    with TestClient(app) as client:
        monkeypatch.delenv('FRAMATEX_RUNTIME_ID', raising=False)
        assert 'runtime_id' not in client.get('/api/health').json()
        monkeypatch.setenv('FRAMATEX_RUNTIME_ID', 'test-instance')
        assert client.get('/api/health').json()['pid'] == os.getpid()
        assert client.get('/api/health').json()['runtime_id'] == 'test-instance'


def test_blocked_scope_query_cannot_freeze_health_or_pages(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app import access
    entered, release = Event(), Event()
    original = access.guard_http_request
    def locked_guard(request):
        if request.url.path == '/api/launches/locked-test':
            entered.set()
            release.wait(5)
        return original(request)
    monkeypatch.setattr(access, 'guard_http_request', locked_guard)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as threads:
        blocked = threads.submit(client.get, '/api/launches/locked-test')
        assert entered.wait(2)
        try:
            healthy = threads.submit(client.get, '/api/health')
            assert healthy.result(timeout=1).status_code == 200
            assert client.get('/espace-framatex').status_code == 200
        finally:
            release.set()
        assert blocked.result(timeout=2).status_code == 401

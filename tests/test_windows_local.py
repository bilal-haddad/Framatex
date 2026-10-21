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

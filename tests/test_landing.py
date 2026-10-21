"""Landing publique : « / » sert l'accueil, l'espace FRAMATEX reste accessible."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _assert_security_headers(response):
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-frame-options'] == 'DENY'
    csp = response.headers['content-security-policy']
    assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp


def test_root_serves_public_landing_with_both_spaces():
    with TestClient(app) as client:
        home = client.get('/')
        assert home.status_code == 200
        _assert_security_headers(home)
        html = home.text
        assert 'Choisissez votre espace' in html
        assert 'href="/espace-framatex"' in html
        assert 'href="/espace-client"' in html
        assert '/assets/landing/landing-redirect.js' in html
        assert 'app.js' not in html


def test_framatex_space_serves_existing_internal_app():
    with TestClient(app) as client:
        page = client.get('/espace-framatex')
        assert page.status_code == 200
        _assert_security_headers(page)
        assert page.content == (ROOT / 'static/index.html').read_bytes()
        assert '/assets/app.js' in page.text


def test_client_space_entry_and_landing_assets_are_served():
    with TestClient(app) as client:
        page = client.get('/espace-client')
        assert page.status_code == 200
        _assert_security_headers(page)
        assert 'Espace Client' in page.text
        for asset in ('landing.css', 'landing.js', 'landing-redirect.js'):
            assert client.get(f'/assets/landing/{asset}').status_code == 200


def test_printed_qr_links_are_forwarded_to_framatex_space():
    script = (ROOT / 'static/landing/landing-redirect.js').read_text()
    assert "'/espace-framatex' + hash" in script
    assert '#\\/launch\\/' in script

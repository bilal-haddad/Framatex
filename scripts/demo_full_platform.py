"""Démonstration complète de la plateforme FRAMATEX, sur une base temporaire.

    python scripts/demo_full_platform.py [--output DIR] [--no-browser]

1. Serveur Uvicorn réel sur une base vierge (migrations), administrateur et dossiers
   de démonstration A–E. Les mots de passe sont générés en mémoire pour la durée de
   la démonstration : aucun n'est écrit dans le dépôt, le rapport ou les captures.
2. Recette API complète (scripts/qa_platform_review.py) : landing, Espace Client,
   Espace FRAMATEX, Dossier Jaune, documents, versions, complétude, alertes,
   cohérence, OCR, Excel, EML, recherche, audit, mémoire interne, sécurité.
3. Parcours Chromium réel :
   - à 1440 px, de bout en bout dans l'interface : landing → inscription Client →
     compte en attente → activation par FRAMATEX → connexion Client → brouillon et
     demande envoyée → FRAMATEX « Accepter et créer le Dossier Jaune » → dossier
     ouvert avec ses 4 sous-dossiers → statut « Acceptée » côté Client → déconnexion ;
   - à 1440, 1024, 820 et 390 px : pages principales des trois espaces, sans
     défilement horizontal ni erreur JavaScript bloquante.

Résultats : <output>/demo-results.json et captures dans <output>/captures/.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_platform_review as recette  # noqa: E402  (même dossier)

WIDTHS = (1440, 1024, 820, 390)
IGNORED_CONSOLE = ('status of 401',)   # sondes de session avant connexion : comportement normal


class Browser:
    """Contexte Chromium qui collecte les erreurs JavaScript et vérifie la largeur."""

    def __init__(self, browser, base, width, captures):
        self.base, self.width, self.captures = base, width, captures
        self.context = browser.new_context(viewport={'width': width, 'height': 844 if width < 600 else 900}, locale='fr-FR')
        self.page = self.context.new_page()
        self.errors, self.notes = [], []
        self.page.on('pageerror', lambda exc: self.errors.append(f'pageerror {exc}'))
        self.page.on('console', self._console)

    def _console(self, message):
        if message.type == 'error':
            text = message.text
            (self.notes if any(k in text for k in IGNORED_CONSOLE) else self.errors).append(text)

    def settle(self):
        self.page.wait_for_load_state('networkidle')
        self.page.evaluate('document.fonts.ready')
        self.page.wait_for_timeout(200)

    def check_page(self, name):
        self.settle()
        overflow = self.page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        self.page.screenshot(path=str(self.captures / f'{self.width}-{name}.png'))
        assert overflow <= 0, f'{name} : défilement horizontal de {overflow}px à {self.width}px'

    def close(self):
        self.context.close()


def internal_login(view, email, password):
    page = view.page
    page.goto(view.base + '/espace-framatex')
    page.wait_for_selector('#login-form')
    page.fill('#email', email)
    page.fill('#password', password)
    page.click('#login-form button[type=submit]')
    page.wait_for_selector('.ops-heading h1')


def client_login(view, email, password):
    page = view.page
    page.goto(view.base + '/espace-client#/connexion')
    page.wait_for_selector('#login-form')
    page.fill('#login-email', email)
    page.fill('#login-password', password)
    page.click('#login-form button.btn-primary[type=submit]')
    page.wait_for_selector('main h1:has-text("Mes demandes")')   # la CSP interdit eval : pas de wait_for_function


def full_journey(qa, browser, base, admin_password, captures):
    """Parcours complet dans l'interface, à 1440 px."""
    client_pw = secrets.token_urlsafe(16) + 'Aa1!'
    email = f'demo.client.{secrets.token_hex(3)}@recette.test'
    client = Browser(browser, base, 1440, captures)
    admin = Browser(browser, base, 1440, captures)
    page, adm = client.page, admin.page
    try:
        def landing():
            page.goto(base + '/')
            page.wait_for_selector('h1')
            assert page.locator('a[href="/espace-client"]').count() and page.locator('a[href="/espace-framatex"]').count()
            client.check_page('parcours-landing')
            page.locator('a[href="/espace-client"]').first.click()
            page.wait_for_selector('.choice')
        qa.run('Navigateur', 'Landing : liens vers l’Espace Client et l’Espace FRAMATEX, puis entrée Client', landing)

        def register():
            page.goto(base + '/espace-client#/inscription')
            page.wait_for_selector('#register-form')
            for field, value in (('reg-company', 'Atelier Démonstration'), ('reg-address', '12 rue du Textile, Casablanca'),
                                 ('reg-contact', 'Responsable achats'), ('reg-phone', '+212 600 000 000'), ('reg-email', email),
                                 ('reg-password', client_pw), ('reg-password2', client_pw)):
                page.fill(f'#{field}', value)
            page.select_option('#reg-country', 'Maroc')
            page.click('#register-form button[type=submit]')
            page.wait_for_selector('.status-panel')
            assert 'attente' in page.locator('main').inner_text().lower()
            client.check_page('parcours-inscription-en-attente')
        qa.run('Navigateur', 'Client : inscription dans l’interface → écran « compte en attente »', register)

        def activate():
            internal_login(admin, 'recette@framatex.test', admin_password)
            headings = adm.locator('main h2').all_inner_texts()
            order = ['Actions prioritaires', 'Documents manquants', 'Complétude des dossiers', 'Alertes et incohérences', 'Dernières activités']
            assert [h for h in headings if h in order] == order, headings
            admin.check_page('parcours-dashboard')
            adm.evaluate("navigate('clients')")
            adm.wait_for_selector(f'tr:has-text("{email}") button[data-ops-client]')
            adm.click(f'tr:has-text("{email}") button[data-ops-client]')
            adm.wait_for_selector(f'tr:has-text("{email}") button:has-text("Suspendre")')
        qa.run('Navigateur', 'FRAMATEX : connexion admin, tableau de bord dans l’ordre demandé, activation du compte Client', activate)

        def requests():
            client_login(client, email, client_pw)
            for status, label in (('draft', 'Brouillon'), ('submitted', 'Envoyée')):
                page.goto(base + '/espace-client#/demandes/nouvelle')
                page.wait_for_selector('#request-form')
                page.fill('#rq-article', f'Chemise démonstration {label}')
                page.fill('#rq-ref', 'REF-DEMO-UI')
                page.fill('#rq-qty', '720')
                page.fill('#rq-date', '2027-06-30')
                page.fill('#rq-comment', 'Tailles 36 à 46, coloris bleu.')
                button = '#request-form button[data-status="draft"]' if status == 'draft' else '#request-form button.btn-primary[type=submit]'
                page.click(button)
                page.wait_for_url(lambda url: '#/demandes/nouvelle' not in url)
            page.goto(base + '/espace-client#/demandes')
            page.wait_for_selector('.req-row')
            text = page.locator('main').inner_text()
            assert 'Brouillon' in text and 'Envoyée' in text, text[:400]
            client.check_page('parcours-mes-demandes')
        qa.run('Navigateur', 'Client : connexion, demande en brouillon et demande envoyée depuis le formulaire', requests)

        def accept_and_open():
            adm.evaluate("navigate('clients')")
            row = adm.locator('[data-ops-request]', has_text='Chemise démonstration Envoyée')
            row.first.wait_for()
            row.first.click()
            adm.wait_for_selector('#cw-create-launch')
            assert adm.locator('#cw-create-launch').inner_text().strip() == 'Accepter et créer le Dossier Jaune'
            admin.check_page('parcours-demande-client')
            adm.click('#cw-create-launch')
            adm.wait_for_selector('#ops-launch-summary .ops-client-origin')
            assert adm.locator('.folder-card').count() == 4
            origin = adm.locator('.ops-client-origin').inner_text()
            assert 'REF-DEMO-UI' in origin and '720 pièces' in origin, origin
            admin.check_page('parcours-dossier-jaune-cree')
            adm.evaluate("navigate('clients')")
            adm.locator('[data-ops-request]', has_text='Chemise démonstration Envoyée').first.click()
            adm.wait_for_selector('#cw-open-launch')
        qa.run('Navigateur', 'FRAMATEX : « Accepter et créer le Dossier Jaune » ouvre le dossier (4 sous-dossiers, origine Client)', accept_and_open)

        def client_sees_acceptance():
            page.goto(base + '/espace-client#/demandes')
            page.wait_for_selector('.req-row')
            page.reload()
            page.wait_for_selector('.req-row')
            assert 'Acceptée' in page.locator('main').inner_text()
            page.locator('button:has-text("Déconnexion"), a:has-text("Déconnexion")').first.click()
            page.wait_for_selector('#login-form, .choice')
        qa.run('Navigateur', 'Client : statut « Acceptée » visible, puis déconnexion', client_sees_acceptance)
    finally:
        for view in (client, admin):
            qa.check('Navigateur', f'Parcours 1440 px ({"Client" if view is client else "FRAMATEX"}) : 0 erreur JavaScript bloquante',
                     not view.errors, view.errors[:3])
            view.close()
    return email, client_pw


def width_tour(qa, browser, base, admin_password, client_email, client_pw, captures):
    """Pages principales des trois espaces, à chaque largeur."""
    for width in WIDTHS:
        view = Browser(browser, base, width, captures)
        page = view.page
        def public():
            page.goto(base + '/')
            page.wait_for_selector('h1')
            view.check_page('landing')
            page.goto(base + '/espace-client')
            page.wait_for_selector('.choice')
            view.check_page('client-entree')
        def client_pages():
            client_login(view, client_email, client_pw)
            for route, name in (('#/demandes', 'client-demandes'), ('#/documents-demandes', 'client-documents-demandes'),
                                ('#/documents-transmis', 'client-documents-transmis'), ('#/documents', 'client-mes-documents'),
                                ('#/compte', 'client-compte')):
                page.evaluate(f"location.hash = '{route}'")
                page.wait_for_selector('main h1')
                view.check_page(name)
        def framatex_pages():
            internal_login(view, 'recette@framatex.test', admin_password)
            view.check_page('framatex-dashboard')
            for name in ('launches', 'search', 'audit', 'experience', 'clients'):
                page.evaluate(f"navigate('{name}')")
                page.wait_for_selector('.ops-heading h1')
                view.check_page(f'framatex-{name}')
            launch = page.evaluate("fetch('/api/launches').then(r => r.json()).then(l => l.find(x => x.order_ref === 'FR-DEMO-2026-0142').id)")
            page.evaluate(f"openLaunch('{launch}', 'jaune')")
            page.wait_for_selector('#ops-launch-summary')
            assert page.locator('.folder-card').count() == 4
            view.check_page('framatex-dossier-jaune')
            for folder in ('rose', 'bleu', 'vert'):
                page.click(f'.folder-card[data-folder="{folder}"]')
                page.wait_for_selector(f'.folder-card.selected[data-folder="{folder}"]')
                view.check_page(f'framatex-sous-dossier-{folder}')
        qa.run('Navigateur', f'{width} px : landing et entrée Client sans défilement horizontal', public)
        qa.run('Navigateur', f'{width} px : Espace Client (demandes, documents demandés et transmis, Mes documents, compte)', client_pages)
        qa.run('Navigateur', f'{width} px : Espace FRAMATEX (dashboard, commandes, recherche, audit, mémoire, clients, Dossier Jaune et 4 sous-dossiers)', framatex_pages)
        qa.check('Navigateur', f'{width} px : 0 erreur JavaScript bloquante', not view.errors, view.errors[:3])
        view.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'demo-platform')
    parser.add_argument('--no-browser', action='store_true', help='recette API seulement')
    args = parser.parse_args()
    output = args.output.resolve()
    captures = output / 'captures'
    captures.mkdir(parents=True, exist_ok=True)
    qa = recette.QA()
    started = time.monotonic()
    with recette.platform_server(qa) as ctx:
        recette.run_checks(qa, ctx.base, ctx.password, ctx.ids, ctx.tmp)
        if args.no_browser:
            print('Parcours navigateur non exécuté (--no-browser).', flush=True)
        else:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                print('Parcours navigateur non exécuté : Playwright absent (pip install -r requirements-dev.txt).', flush=True)
            else:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    try:
                        email, client_pw = full_journey(qa, browser, ctx.base, ctx.password, captures)
                        width_tour(qa, browser, ctx.base, ctx.password, email, client_pw, captures)
                    finally:
                        browser.close()
    code = recette.write_report(qa, output, 'demo-results.json')
    print(f'Durée : {time.monotonic() - started:.0f} s · captures : {captures}', flush=True)
    sys.exit(code)


if __name__ == '__main__':
    main()

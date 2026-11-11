"""Public account-help routes must remain usable without the app or sign-in."""
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from scripts.build_site import BASE, build


class PageAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = []
        self.forms = 0
        self.headings = 0
        self.scripts = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        if tag == 'form':
            self.forms += 1
        if tag == 'h1':
            self.headings += 1
        if tag == 'script' and attrs.get('src'):
            self.scripts.append(attrs['src'])

    def handle_data(self, text):
        self.text.append(text)


class AccountPagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).parents[1]
        # No catalogue, account bundle, Firebase configuration or service is needed
        # to generate and read the public deletion/privacy instructions.
        (self.root / 'index.html').write_text((source / 'index.html').read_text())
        for name in ('app.js', 'style.css', 'CNAME'):
            (self.root / name).write_text('')
        self.site = build(self.root, now=1793811600)

    def audit(self, route):
        audit = PageAudit()
        audit.feed((self.site / route / 'index.html').read_text())
        return audit

    def test_deletion_route_is_public_and_has_real_self_service_and_email_paths(self):
        audit = self.audit('delete-account')
        self.assertEqual(audit.headings, 1)
        self.assertEqual(audit.forms, 0)
        self.assertFalse(any('account.js' in script for script in audit.scripts))
        self.assertIn('/#account-button', audit.links)
        self.assertIn('mailto:akashashok8960@gmail.com?subject=OTTScout%20account%20deletion%20request', audit.links)
        self.assertIn('/privacy/', audit.links)
        self.assertEqual(len(audit.ids), len(set(audit.ids)))
        for link in audit.links:
            if link.startswith('#'):
                self.assertIn(link[1:], audit.ids)
        dashboard = self.site.joinpath('index.html').read_text()
        self.assertIn('id="account-button"', dashboard)
        self.assertIn('id="account-delete"', dashboard)
        self.assertIn('href="/delete-account/">Delete account help', dashboard)
        text = ' '.join(audit.text)
        for detail in ('without signing in or installing', 'same Google account or email/password',
                       'Confirm account deletion', 'Never email your password',
                       'no automatic expiry', 'Separate guest saves are kept',
                       'does not delete your Google account', 'Android or iPhone app',
                       'Keychain sign-in data can survive reinstallation',
                       'public catalogue caches'):
            self.assertIn(detail, text)

    def test_privacy_covers_native_and_web_storage_and_distinguishes_ad_builds(self):
        audit = self.audit('privacy')
        self.assertEqual(audit.headings, 1)
        self.assertIn('/delete-account/', audit.links)
        self.assertIn('mailto:akashashok8960@gmail.com', audit.links)
        for link in audit.links:
            if link.startswith('#'):
                self.assertIn(link[1:], audit.ids)
        text = ' '.join(audit.text)
        for detail in ('Android apps', 'iPhone app', 'Apple Watch', 'Wear OS',
                       'Expo SecureStore', 'iOS Keychain', 'pending saved-title changes',
                       'Firebase Authentication', 'Google Cloud Firestore',
                       'Ad-free Android Play testing builds exclude',
                       'Local Android phone developer test builds include Google demo ads',
                       'widgets and watch views add no analytics or advertising requests',
                       'currently has no automatic expiry', 'does not remotely erase local copies on other devices'):
            self.assertIn(detail, text)

    def test_both_routes_are_in_sitemap_and_information_navigation(self):
        sitemap = (self.site / 'sitemap.xml').read_text()
        for route in ('/privacy/', '/delete-account/'):
            self.assertIn(BASE + route, sitemap)
        for route in ('privacy', 'delete-account', 'about', 'contact', 'accessibility'):
            audit = self.audit(route)
            self.assertIn('/privacy/', audit.links)
            self.assertIn('/delete-account/', audit.links)


if __name__ == '__main__':
    unittest.main()

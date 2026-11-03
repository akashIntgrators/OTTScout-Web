import subprocess
from pathlib import Path
import unittest

class BrowserFilterTests(unittest.TestCase):
    def test_original_audio_filter_scenarios(self):
        subprocess.run(['node', 'tests/browser_logic.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_analytics_consent(self):
        subprocess.run(['node', 'tests/analytics_consent.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_filter_disclosure(self):
        subprocess.run(['node', 'tests/filter_disclosure.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_catalogue_views(self):
        subprocess.run(['node', 'tests/catalogue_views.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_account_watchlist_sync(self):
        subprocess.run(['node', 'tests/watchlist_sync.mjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_account_watchlist_adversarial_races(self):
        subprocess.run(['node', '--test', 'tests/watchlist_adversarial.mjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_account_session_single_writer(self):
        subprocess.run(['node', '--test', 'tests/account_session.mjs'], cwd=Path(__file__).resolve().parents[1], check=True)

import subprocess
from pathlib import Path
import unittest

class BrowserFilterTests(unittest.TestCase):
    def test_original_audio_filter_scenarios(self):
        subprocess.run(['node', 'tests/browser_logic.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_analytics_consent(self):
        subprocess.run(['node', 'tests/analytics_consent.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

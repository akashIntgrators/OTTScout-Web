"""Stage only public website files. Never include state, secrets, or reports."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
target = root / '.site'
if target.exists():
    shutil.rmtree(target)
target.mkdir()
for name in ('index.html', 'app.js', 'style.css', 'CNAME'):
    shutil.copy2(root / name, target / name)
for name in ('assets', 'data'):
    if (root / name).exists():
        shutil.copytree(root / name, target / name)
(target / '.nojekyll').touch()
print('Website staged in .site; database and reports excluded.')

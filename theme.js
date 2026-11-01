// Theme is a browser-local appearance preference. No network request is made.
(() => {
  const root = document.documentElement;
  let current = 'dark';
  try {
    const saved = localStorage.getItem('ottscout-theme');
    if (saved === 'light' || saved === 'dark') current = saved;
  } catch { /* Storage is optional. */ }
  root.dataset.theme = current;
  function syncButtons() {
    document.querySelectorAll('.theme-toggle').forEach(button => {
      button.setAttribute('aria-label', `Switch to ${current === 'dark' ? 'light' : 'dark'} mode`);
      button.title = `Switch to ${current === 'dark' ? 'light' : 'dark'} mode`;
    });
  }
  document.addEventListener('DOMContentLoaded', () => {
    syncButtons();
    document.querySelectorAll('.theme-toggle').forEach(button => {
      button.addEventListener('click', () => {
        current = current === 'dark' ? 'light' : 'dark';
        root.dataset.theme = current;
        try { localStorage.setItem('ottscout-theme', current); } catch { /* Storage is optional. */ }
        syncButtons();
      });
    });
  });
})();

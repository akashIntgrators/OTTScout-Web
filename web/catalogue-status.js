(() => {
  const report = document.querySelector('[data-status-evaluated]');
  const heading = document.getElementById('freshness-heading');
  const explanation = document.getElementById('freshness-explanation');
  if (!report || !heading || !explanation) return;
  const check = () => {
    const evaluated = Number(report.dataset.statusEvaluated) * 1000;
    if (!evaluated || evaluated > Date.now() + 300000 || Date.now() - evaluated > 8 * 3600000) {
      heading.textContent = 'The status check is overdue';
      explanation.textContent = 'This report is too old to confirm current release coverage. Check the open update alerts on GitHub.';
    }
  };
  check();
  window.setInterval(check, 60000);
})();

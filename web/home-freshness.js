(() => {
  const notice = document.getElementById('home-freshness');
  const message = document.getElementById('home-freshness-message');
  if (!notice || !message) return;

  // The public report is separate from the provider catalogue. It does not
  // make a provider request, and an old or missing report is not a clean bill
  // of health for the data.
  const maxAgeMs = 8 * 60 * 60 * 1000;
  const unknown = 'We can’t confirm the current update status. Check availability with the streaming service.';
  const show = text => { message.textContent = text; notice.hidden = false; };
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  fetch('/data/catalogue-health.json', {cache: 'no-store', signal: controller.signal})
    .then(response => { if (!response.ok) throw new Error('No update report'); return response.json(); })
    .then(report => {
      const now = Date.now();
      const evaluated = report?.evaluatedAt * 1000;
      const causes = report?.causes;
      if (report?.schemaVersion !== 1 || typeof report.evaluatedAt !== 'number' || !Number.isFinite(evaluated) || evaluated <= 0 ||
          evaluated > now + 300000 || now - evaluated > maxAgeMs ||
          !['normal', 'warning', 'critical'].includes(report.status) || !Array.isArray(causes) ||
          causes.some(cause => !cause || typeof cause.code !== 'string' || !cause.code || !['warning', 'critical'].includes(cause.severity)) ||
          report.status !== (causes.some(cause => cause.severity === 'critical') ? 'critical' : causes.length ? 'warning' : 'normal')) {
        show(unknown);
        return;
      }
      if (report.status === 'normal') {
        notice.hidden = true;
      } else if (causes.some(cause => ['new_feed_stale', 'new_feed_pending_old'].includes(cause.code))) {
        show('New-release updates are delayed. Check availability with the streaming service.');
      } else {
        show('Some catalogue checks need attention. Check availability with the streaming service.');
      }
      // A previously healthy report must not remain invisible indefinitely.
      setTimeout(() => show(unknown), Math.max(0, evaluated + maxAgeMs - now + 1));
    })
    .catch(() => show(unknown))
    .finally(() => clearTimeout(timeout));
})();

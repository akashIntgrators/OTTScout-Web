/* Optional page-view measurement. No Google requests before an explicit opt-in. */
(() => {
  const id = 'G-LV97MSZYW1', key = 'ottscout-analytics-consent';
  let loaded = false;
  const read = () => { try { return localStorage.getItem(key); } catch { return null; } };
  const save = value => { try { localStorage.setItem(key, value); } catch {} };
  function start() {
    window['ga-disable-' + id] = false;
    if (loaded) {
      window.gtag('consent','update',{analytics_storage:'granted'});
      return;
    }
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    gtag('consent', 'default', {analytics_storage:'granted', ad_storage:'denied', ad_user_data:'denied', ad_personalization:'denied'});
    gtag('js', new Date());
    gtag('config', id, {send_page_view:false, allow_google_signals:false, allow_ad_personalization_signals:false, cookie_domain:location.hostname});
    gtag('event', 'page_view', {page_location:location.origin + location.pathname, page_referrer:'', page_title:document.title});
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + id;
    document.head.append(script);
  }
  const panel = document.createElement('section');
  panel.setAttribute('aria-label','Optional analytics');
  panel.className = 'analytics-choice';
  panel.style.cssText = 'position:fixed;bottom:16px;left:16px;right:16px;max-width:620px;padding:20px;background:#17232b;border:1px solid #718b96;border-radius:12px;z-index:1000;box-shadow:0 8px 32px #0008;color:#eef5f6';
  panel.innerHTML = '<p>Help improve OTTScout? Optional Google Analytics measures page visits. Your search terms, filters and watchlist are not sent. <a href="/privacy/">Privacy details</a></p><div style="display:flex;gap:12px"><button type="button" data-choice="accepted">Allow analytics</button><button type="button" data-choice="declined">No thanks</button></div>';
  panel.addEventListener('click', event => {
    const choice = event.target.dataset.choice;
    if (!choice) return;
    save(choice);
    if (choice === 'accepted') start();
    else {
      window['ga-disable-' + id] = true;
      if (window.gtag) gtag('consent','update',{analytics_storage:'denied'});
      for (const cookie of document.cookie.split(';')) {
        const name = cookie.trim().split('=')[0];
        if (/^_ga(?:_|$)/.test(name)) {
          document.cookie = name + '=;Max-Age=0;path=/';
          document.cookie = name + '=;Max-Age=0;path=/;domain=' + location.hostname;
        }
      }
    }
    panel.remove();
  });
  const choices = document.createElement('button');
  choices.type = 'button'; choices.textContent = 'Analytics choices';
  choices.addEventListener('click', () => document.body.append(panel));
  (document.querySelector('footer') || document.body).append(choices);
  if (read() === 'accepted') start();
  else if (!read() && navigator.doNotTrack !== '1' && navigator.globalPrivacyControl !== true) document.body.append(panel);
})();

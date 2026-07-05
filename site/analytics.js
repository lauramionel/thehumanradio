/* Human Radio — engagement analytics (privacy-first, provider-agnostic).
 *
 * One function, hrTrack(event, props), fans out to whatever provider is
 * configured below. No cookies, no personal data, no cross-site tracking —
 * fits the station's privacy stance and needs no consent banner.
 *
 * TO TURN ON PAGEVIEW/EVENT DATA — pick ONE (both are free + privacy-first):
 *   A) Cloudflare Web Analytics — put the site behind Cloudflare (also makes
 *      deploys reliable), then paste your beacon token in CF_TOKEN below.
 *   B) Plausible — create the site at plausible.io, set PLAUSIBLE_DOMAIN.
 * Until then, everything still records to window.__hr (live) and localStorage
 * (last 500 events) so engagement is observable from the console immediately.
 */
(function () {
  var CF_TOKEN = "";                 // Cloudflare Web Analytics beacon token
  var PLAUSIBLE_DOMAIN = "";         // e.g. "thehumanradio.com"

  // ---- local ring buffer (works with zero setup) ----
  window.__hr = window.__hr || { events: [], since: Date.now() };
  function remember(type, props) {
    var e = { t: Date.now(), type: type, props: props || {} };
    window.__hr.events.push(e);
    try {
      var k = "hr_events";
      var arr = JSON.parse(localStorage.getItem(k) || "[]");
      arr.push(e); if (arr.length > 500) arr = arr.slice(-500);
      localStorage.setItem(k, JSON.stringify(arr));
    } catch (_) {}
  }

  // ---- provider loaders ----
  if (CF_TOKEN) {
    var cf = document.createElement("script");
    cf.defer = true; cf.src = "https://static.cloudflareinsights.com/beacon.min.js";
    cf.setAttribute("data-cf-beacon", JSON.stringify({ token: CF_TOKEN }));
    document.head.appendChild(cf);
  }
  if (PLAUSIBLE_DOMAIN) {
    var pl = document.createElement("script");
    pl.defer = true; pl.setAttribute("data-domain", PLAUSIBLE_DOMAIN);
    pl.src = "https://plausible.io/js/script.tagged-events.js";
    document.head.appendChild(pl);
    window.plausible = window.plausible || function () {
      (window.plausible.q = window.plausible.q || []).push(arguments);
    };
  }

  // ---- the one call the app uses ----
  window.hrTrack = function (event, props) {
    remember(event, props);
    try { if (window.plausible) window.plausible(event, { props: props || {} }); } catch (_) {}
    // Cloudflare auto-tracks pageviews; custom events ride the buffer + Plausible.
  };

  // pageview + a coarse "how long did they stay" beacon on unload
  window.hrTrack("pageview", { path: location.pathname, ref: document.referrer || "direct" });
  var arrived = Date.now();
  addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      window.hrTrack("dwell", { seconds: Math.round((Date.now() - arrived) / 1000) });
    }
  });

  // tiny console helper so you can inspect engagement live
  window.hrStats = function () {
    var c = {}; window.__hr.events.forEach(function (e) { c[e.type] = (c[e.type] || 0) + 1; });
    return c;
  };
})();

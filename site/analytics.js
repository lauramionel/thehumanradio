/* Human Radio — traffic + engagement analytics (privacy-first, no consent needed).
 *
 * Two layers, both cookieless and free:
 *
 *  1) COUNTERS (on by default, zero setup) — every visit increments a handful of
 *     named counters on a free public counter API (the same service the site
 *     already trusts). No cookies, no personal data, no fingerprinting: just
 *     "+1 to today's pageviews", "+1 to the X-referral bucket", etc. Read them
 *     back any time at /stats.html. This means real traffic is measured the
 *     moment this deploys — nothing to sign up for.
 *
 *  2) A HOSTED DASHBOARD (optional upgrade) — for per-visitor detail, countries,
 *     and Core Web Vitals, add ONE provider below (both free + privacy-first):
 *       A) Cloudflare Web Analytics — create the site under Web Analytics in the
 *          Cloudflare dashboard (no DNS change required), paste the beacon token
 *          in CF_TOKEN. Putting the domain fully behind Cloudflare also fixes the
 *          flaky GitHub Pages deploys.
 *       B) Plausible — create the site at plausible.io, set PLAUSIBLE_DOMAIN.
 *
 * Everything also records to window.__hr (live) + localStorage (last 500 events)
 * so engagement is inspectable from the console with hrStats().
 */
(function () {
  var CF_TOKEN = "";                 // Cloudflare Web Analytics beacon token (optional upgrade)
  var PLAUSIBLE_DOMAIN = "";         // e.g. "thehumanradio.com"          (optional upgrade)

  // ---- layer 1: free named counters (works with zero setup) ----
  var COUNTER = "https://abacus.jasoncameron.dev";
  var NS = "thehumanradio-live";
  // Only the production domain feeds the counters, so localhost/preview traffic
  // never pollutes the real numbers.
  var LIVE = /(^|\.)thehumanradio\.com$/i.test(location.hostname);
  // Keys are bounded on purpose (fixed buckets) so the namespace stays tidy and
  // readable at /stats.html. bump() is fire-and-forget — it never blocks or throws.
  function bump(key) {
    if (!LIVE) return;
    try { fetch(COUNTER + "/hit/" + NS + "/" + key, { keepalive: true, mode: "no-cors" }); } catch (_) {}
  }
  function todayKey() {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    return "pv_" + d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate());
  }
  function refBucket() {
    var r = document.referrer || "";
    if (!r) return "direct";
    try {
      var h = new URL(r).hostname.replace(/^www\./, "");
      if (h === location.hostname) return "internal";
      if (/(^|\.)(t\.co|x\.com|twitter\.com)$/.test(h)) return "x";
      if (/(^|\.)google\./.test(h)) return "google";
      if (/(^|\.)reddit\.com$/.test(h)) return "reddit";
      if (/(^|\.)(facebook\.com|instagram\.com|linkedin\.com|t\.me|telegram\.org|news\.ycombinator\.com|bsky\.app|mastodon)/.test(h)) return "social";
      return "other";
    } catch (_) { return "other"; }
  }
  // engagement events worth a running total (mirrors the hrTrack calls in the page)
  var COUNTED = {
    tune_in: 1, agent_mode: 1, request_post: 1,
    rotation_play: 1, archive_play: 1, share_moment: 1
  };

  // ---- local ring buffer (console inspection) ----
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

  // ---- layer 2: optional hosted provider loaders ----
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
    if (COUNTED[event]) bump("ev_" + event);
    try { if (window.plausible) window.plausible(event, { props: props || {} }); } catch (_) {}
    // Cloudflare auto-tracks pageviews; custom events ride the counters + Plausible.
  };

  // ---- count the visit (once per load) ----
  bump("pv_total");
  bump(todayKey());
  bump("ref_" + refBucket());
  bump(navigator.userAgent && /\b(bot|crawler|spider|agent|gpt|claude|python-requests|curl|headless)\b/i.test(navigator.userAgent) ? "cls_agent" : "cls_human");

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

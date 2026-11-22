// Events for the docs, sent to our own Umami (no cookie, no third party).
// Only event names are sent: never the search text or a copied command.
(function () {
  function track(name, data) { try { if (window.umami) window.umami.track(name, data); } catch (e) {} }
  // The security pack's three documents, by the address each one opens.
  var PACK = [
    [/\/security\/overview\/?$/, "security_overview"],
    [/\/legal\/data-processing-terms\/?$/, "data_processing_terms"],
    [/\/legal\/security-questionnaire\/?$/, "security_questionnaire"],
    [/serops-security-questionnaire\.csv$/, "security_questionnaire_csv"]
  ];
  var lastSearch = 0;
  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || !el.matches || !el.matches(".md-search__input") || !el.value) return;
    // One event per search, not one per keystroke.
    var now = Date.now();
    if (now - lastSearch > 30000) { lastSearch = now; track("docs_search"); }
  }, true);
  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    // Material's copy button: .md-code__button[data-md-type="copy"] today,
    // .md-clipboard in older versions; both carry data-clipboard-target.
    if (t.closest("[data-clipboard-target], .md-clipboard") && /\/getting-started\/quick-start/.test(location.pathname)) return track("quickstart_copy");
    var a = t.closest("a[href]");
    if (!a) return;
    var url;
    try { url = new URL(a.getAttribute("href"), location.href); } catch (err) { return; }
    if (/\/legal\/security-pack\/?$/.test(location.pathname)) {
      for (var i = 0; i < PACK.length; i++) {
        if (PACK[i][0].test(url.pathname)) return track("security_pack_download", { document: PACK[i][1] });
      }
    }
    if (url.hostname === "app.serops.ai") track("demo_click");
    else if (url.hostname === "github.com" && /^\/getserops(\/|$)/.test(url.pathname)) track("github_click");
  }, true);
})();

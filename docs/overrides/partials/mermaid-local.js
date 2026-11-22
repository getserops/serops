/* Diagrams: Mermaid from this site, not from unpkg.com.
   The theme loads Mermaid from unpkg.com the first time a page shows a
   diagram, unless `window.mermaid` already exists. This stand-in exists on
   every page, costs nothing until a diagram is drawn, and then loads the copy
   shipped with these docs (assets/javascripts/mermaid-<version>.min.js,
   SHA-256 in mermaid.sha256 next to it). The theme calls only initialize()
   and render(); both are passed on to the real library. */
(function () {
  var src = new URL(document.currentScript.dataset.src, location.href).href;
  var config, loading;
  function load() {
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = src;
        s.onload = function () {
          var real = window.mermaid;      // the library replaces the stand-in
          if (config) real.initialize(config);
          resolve(real);
        };
        s.onerror = function () { reject(new Error("Mermaid could not be loaded from " + src)); };
        document.head.appendChild(s);
      });
    }
    return loading;
  }
  window.mermaid = {
    initialize: function (c) { config = c; },
    render: function () { var a = arguments; return load().then(function (m) { return m.render.apply(m, a); }); }
  };
})();

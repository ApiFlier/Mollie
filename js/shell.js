/**
 * Public shell — URL view-state helper.
 *
 * Phase 1: establishes ?view=events / ?view=map URL convention and the
 * PublicShell.navigateTo() function that Phase 2 (same-page switching) will
 * intercept. All existing /  and /map routes keep working unchanged.
 */
(function () {
  var path       = window.location.pathname;
  var params     = new URLSearchParams(window.location.search);
  var viewParam  = params.get("view");
  var isMapPage  = (path === "/map" || path === "/map/");

  // Cross-page redirects: honour ?view= on the wrong page.
  // This lets future in-page navigation fall back gracefully on a hard reload.
  if (!isMapPage && viewParam === "map") {
    window.location.replace("/map");
    return;
  }
  if (isMapPage && viewParam === "events") {
    window.location.replace("/");
    return;
  }

  // Normalise URL: add ?view= without clobbering any other existing params
  // (e.g. /?saved=1 → /?saved=1&view=events).
  if (!viewParam) {
    params.set("view", isMapPage ? "map" : "events");
    var search = params.toString();
    history.replaceState(
      null, "",
      path + (search ? "?" + search : "") + (window.location.hash || "")
    );
  }

  // Canonical navigation helper.
  // Phase 2 will replace the body of navigateTo() with in-page view switching;
  // callers don't need to change.
  window.PublicShell = {
    currentView: isMapPage ? "map" : "events",
    navigateTo: function (view) {
      if (view === "map")    { window.location.href = "/map"; }
      if (view === "events") { window.location.href = "/"; }
    }
  };
})();

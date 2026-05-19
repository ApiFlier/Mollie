/**
 * Public shell — Phase 2 (hash routing).
 *
 * Views are driven by URL hash: #events or #map.
 * Backward-compat: ?view=events / ?view=map still work on initial load.
 *
 * PublicShell.navigateTo(view) — switch to 'events' or 'map'.
 * PublicShell.onMapActivate(fn) — callback for when map view first becomes active.
 */
(function () {
  var params    = new URLSearchParams(window.location.search);
  var viewParam = params.get("view");
  var hash      = window.location.hash;  // "#map", "#events", or ""
  var path      = window.location.pathname;
  var isMapPath = (path === "/map" || path === "/map/");

  // Priority: hash → query param → path → default (events)
  var initialView;
  if (hash === "#map") {
    initialView = "map";
  } else if (hash === "#events") {
    initialView = "events";
  } else if (viewParam === "map" || isMapPath) {
    initialView = "map";
  } else {
    initialView = "events";
  }

  var mapBooted            = false;
  var mapActivateCallbacks = [];

  function fireMapActivate() {
    if (mapBooted) return;
    mapBooted = true;
    mapActivateCallbacks.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } });
  }

  function setNavActive(view) {
    document.querySelectorAll("[data-shell-view]").forEach(function (el) {
      var v = el.dataset.shellView;
      if (el.closest(".top-nav")) {
        el.classList.toggle("top-nav-active", v === view);
      }
      if (el.closest(".mob-nav")) {
        el.classList.toggle("mob-nav-active", v === view);
      }
    });
  }

  // Core view switcher — only touches DOM, never touches the URL.
  function switchView(view) {
    var evView  = document.getElementById("events-view");
    var mapView = document.getElementById("map-view");
    if (!evView || !mapView) return; // not the unified shell

    if (view === "map") {
      evView.style.display  = "none";
      mapView.style.display = "";
      document.body.classList.add("view-map-active");
      document.body.classList.remove("view-events-active");
      setNavActive("map");
      fireMapActivate();
      setTimeout(function () {
        if (typeof EventMapMap !== "undefined" && EventMapMap.isInitialized()) {
          EventMapMap.invalidateSize();
        }
      }, 50);
    } else {
      evView.style.display  = "";
      mapView.style.display = "none";
      document.body.classList.add("view-events-active");
      document.body.classList.remove("view-map-active");
      setNavActive("events");
    }

    PublicShell.currentView = view;
  }

  window.PublicShell = {
    currentView: initialView,

    // Register a callback for when the map view is first shown.
    // If the map is already active, the callback fires immediately.
    onMapActivate: function (fn) {
      if (mapBooted) {
        try { fn(); } catch (e) { console.error(e); }
      } else {
        mapActivateCallbacks.push(fn);
      }
    },

    navigateTo: function (view) {
      if (view === PublicShell.currentView) return;
      var hasShell = !!(document.getElementById("events-view") &&
                        document.getElementById("map-view"));
      if (hasShell) {
        var targetHash = (view === "map") ? "#map" : "#events";
        if (window.location.hash !== targetHash) {
          window.location.hash = targetHash; // triggers hashchange → switchView
        } else {
          switchView(view); // hash already matches, just switch DOM
        }
      } else {
        // Fallback: full-page navigation
        if (view === "map")    window.location.href = "/#map";
        if (view === "events") window.location.href = "/";
      }
    }
  };

  // ── DOMContentLoaded ──────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    document.body.classList.add(
      initialView === "map" ? "view-map-active" : "view-events-active"
    );

    switchView(initialView);

    // Hash changes drive all in-page navigation (nav links, back/forward).
    window.addEventListener("hashchange", function () {
      var h = window.location.hash;
      var v = (h === "#map") ? "map" : "events";
      switchView(v);
    });

    // Support data-shell-view click handlers (intercepts href="#map" etc.).
    document.querySelectorAll("[data-shell-view]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        PublicShell.navigateTo(el.dataset.shellView);
      });
    });
  });
})();

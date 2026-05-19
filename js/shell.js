/**
 * Public shell — Phase 2.
 *
 * In-page switching between Events and Map views inside the unified shell at /.
 * Map is lazy-initialized on first activation via PublicShell.onMapActivate().
 *
 * PublicShell.navigateTo(view) — switch to 'events' or 'map'.
 * PublicShell.onMapActivate(fn) — register a callback for when map view first becomes active.
 */
(function () {
  var params    = new URLSearchParams(window.location.search);
  var viewParam = params.get("view");
  var path      = window.location.pathname;
  var isMapPath = (path === "/map" || path === "/map/");

  var initialView = (viewParam === "map" || isMapPath) ? "map" : "events";

  var mapBooted            = false;
  var mapActivateCallbacks = [];

  function fireMapActivate() {
    if (mapBooted) return;
    mapBooted = true;
    mapActivateCallbacks.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } });
  }

  // Update active state on all data-shell-view nav links.
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

  // Core view switcher. pushState=true when user-initiated, false on load/popstate.
  function switchView(view, pushState) {
    var evView  = document.getElementById("events-view");
    var mapView = document.getElementById("map-view");
    if (!evView || !mapView) return; // not the unified shell (e.g. standalone map.html)

    if (view === "map") {
      evView.style.display  = "none";
      mapView.style.display = "";
      document.body.classList.add("view-map-active");
      document.body.classList.remove("view-events-active");
      if (pushState) history.pushState({ view: "map" }, "", "/?view=map");
      setNavActive("map");
      fireMapActivate();
      // After repaint, recalculate Leaflet tile layout if already initialized.
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
      if (pushState) history.pushState({ view: "events" }, "", "/");
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
        switchView(view, true);
      } else {
        // Fallback: full-page navigation (standalone pages or no-JS fallback).
        if (view === "map")    window.location.href = "/?view=map";
        if (view === "events") window.location.href = "/";
      }
    }
  };

  // ── DOMContentLoaded ──────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    // Apply initial body class before first paint completes.
    document.body.classList.add(
      initialView === "map" ? "view-map-active" : "view-events-active"
    );

    // Establish initial view (hides the inactive container, sets nav active state).
    switchView(initialView, false);

    // Wire up nav links.
    document.querySelectorAll("[data-shell-view]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        PublicShell.navigateTo(el.dataset.shellView);
      });
    });

    // Handle browser back / forward buttons.
    window.addEventListener("popstate", function (e) {
      var v = (e.state && e.state.view) ? e.state.view : "events";
      switchView(v, false);
    });
  });
})();

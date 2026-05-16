(function() {
  var detailPanel, detailContent, resultCount;
  var currentLocations = [];
  var currentView = "map";
  var currentDetailLoc = null;
  var listEmptyReason = "";
  var listSearchTerm = "";
  var miniMap = null;
  var miniMapMarker = null;

  function escapeHtml(s) { return s ? String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") : ""; }

  // ── Mini-map ─────────────────────────────────────────────────────────────────

  function updateMiniMap(lat, lng, color) {
    var container = document.getElementById("detail-minimap");
    if (!miniMap) {
      miniMap = L.map(container, {
        zoomControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        touchZoom: false,
        keyboard: false,
        attributionControl: false
      });
      var base = "https://server.arcgisonline.com/ArcGIS/rest/services/";
      L.tileLayer(base + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19 }).addTo(miniMap);
      L.tileLayer(base + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19 }).addTo(miniMap);
    }
    miniMap.setView([lat, lng], 14);
    if (miniMapMarker) miniMap.removeLayer(miniMapMarker);
    miniMapMarker = L.marker([lat, lng], { icon: EventMapMap.makeIcon(color || "#3d72c8") }).addTo(miniMap);
    miniMap.invalidateSize();
  }

  // ── Detail panel ─────────────────────────────────────────────────────────────

  function renderDetail(loc, source) {
    currentDetailLoc = loc;
    var html = '<h2>' + escapeHtml(loc.name) + '</h2>';
    var cty = loc.county ? ' · ' + escapeHtml(loc.county) + ' County' : '';
    html += '<div class="meta">' + escapeHtml(loc.category) + cty + '</div>';

    if (loc.event_date) {
      html += '<div class="section"><div class="section-label">Date / Schedule</div>';
      html += '<div style="font-weight:600; color:var(--berry);">' + escapeHtml(loc.event_date) + '</div></div>';
    }

    if (loc.notes) {
      html += '<div class="section"><div class="section-label">Description / Site Info</div>';
      html += '<div style="white-space:pre-wrap; font-size:14px; color: #555;">' + escapeHtml(loc.notes) + '</div></div>';
    }

    var fullAddr = "";
    if (loc.address) {
      fullAddr = loc.address + ", " + (loc.city || "") + ", " + (loc.state || "") + " " + (loc.zip || "");
      html += '<div class="section"><div class="section-label">Address</div>';
      html += '<a href="https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(fullAddr) + '" target="_blank">' + escapeHtml(fullAddr) + '</a></div>';
    }

    // Directions button
    var directionsUrl = "";
    if (loc.lat != null && loc.lng != null) {
      directionsUrl = 'https://www.google.com/maps/dir/?api=1&destination=' + loc.lat + ',' + loc.lng;
    } else if (fullAddr) {
      directionsUrl = 'https://www.google.com/maps/dir/?api=1&destination=' + encodeURIComponent(fullAddr);
    }

    if (directionsUrl) {
      html += '<a href="' + directionsUrl + '" class="directions-btn" target="_blank" rel="noopener noreferrer">Get directions</a>';
    }

    if (loc.hours && loc.hours !== loc.event_date) {
      html += '<div class="section"><div class="section-label">Hours</div><div>' + escapeHtml(loc.hours) + '</div></div>';
    }

    if (loc.crops && loc.crops.length) {
      var monthNames = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      html += '<div class="section"><div class="section-label">Crops</div>';
      html += '<div class="crop-list">';
      loc.crops.forEach(function(c) {
        var label = c.name;
        if (c.season_start_month && c.season_end_month) {
          label += " (" + monthNames[c.season_start_month] + "–" + monthNames[c.season_end_month] + ")";
        }
        var cls = c.is_pyo ? "crop-tag pyo" : "crop-tag";
        html += '<span class="' + cls + '">' + escapeHtml(label) + '</span>';
      });
      html += '</div></div>';
    }

    if (loc.website) {
      html += '<div class="section"><div class="section-label">Website</div>';
      html += '<a href="' + escapeHtml(loc.website) + '" target="_blank">' + escapeHtml(loc.website) + '</a></div>';
    }

    html += '<div class="notes-section" style="margin-top:20px; border-top:1px solid #eee; padding-top:15px;">';
    html += '<div class="section-label">My Private Notes</div>';
    html += '<div id="notes-list-' + loc.id + '" class="notes-list">Loading...</div>';
    html += '<div class="note-input-wrap" style="margin-top:10px;">';
    html += '<textarea id="note-input-' + loc.id + '" placeholder="Add a personal note..." style="width:100%; height:60px;"></textarea>';
    html += '<button class="add-btn" id="add-note-btn-' + loc.id + '" style="margin-top:5px;">Add Note</button></div></div>';

    detailContent.innerHTML = html;

    // Mini-map and back button: only when opened from list with valid coords
    var minimapEl = document.getElementById("detail-minimap");
    var backBtn   = document.getElementById("detail-back");
    var showMini  = source === "list" && loc.lat != null && loc.lng != null;

    minimapEl.style.display = showMini ? "" : "none";
    backBtn.style.display   = source === "list" ? "" : "none";

    detailPanel.classList.add("open");

    if (showMini) {
      setTimeout(function() { updateMiniMap(loc.lat, loc.lng, loc.category_color); }, 60);
    }

    loadNotes(loc.id);

    document.getElementById("add-note-btn-" + loc.id).onclick = function() {
      var ta = document.getElementById("note-input-" + loc.id);
      var txt = ta.value.trim();
      if (!txt) return;
      EventMapAPI.addNote(loc.id, txt).then(function() {
        ta.value = "";
        loadNotes(loc.id);
      });
    };
  }

  window.deleteNote = function(locId, noteId) {
    if (!confirm("Are you sure you want to delete this note?")) return;
    EventMapAPI.deleteNote(locId, noteId)
      .then(function() { loadNotes(locId); })
      .catch(function(err) { console.error(err); alert("Failed to delete note."); });
  };

  window.loadNotes = function(id) {
    var el = document.getElementById("notes-list-" + id);
    EventMapAPI.getNotes(id).then(function(notes) {
      if (!notes.length) {
        el.innerHTML = '<div style="color:#999; font-size:12px;">No personal notes yet.</div>';
        return;
      }
      var html = "";
      notes.forEach(function(n) {
        var d = new Date(n.created_at);
        var dateStr = !isNaN(d.getTime())
          ? d.toLocaleDateString() + ' at ' + d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
          : 'Unknown Date';

        html += '<div class="note-card" style="background:#f9f9f9; padding:8px 24px 8px 8px; margin-bottom:5px; border-radius:4px; font-size:13px; position:relative;">';
        html += '<div style="color:#888; font-size:11px; margin-bottom:4px;">Added on ' + dateStr + '</div>';
        html += '<div style="white-space:pre-wrap;">' + escapeHtml(n.note) + '</div>';
        html += '<button onclick="deleteNote(' + id + ', ' + n.id + ')" title="Delete Note" style="position:absolute; top:4px; right:6px; background:none; border:none; color:#c00; cursor:pointer; font-size:18px; padding:0; line-height:1;">&times;</button>';
        html += '</div>';
      });
      el.innerHTML = html;
    }).catch(function() {
      el.innerHTML = '<div style="color:red;">Error loading private notes.</div>';
    });
  };

  // ── List search ───────────────────────────────────────────────────────────────

  function matchesSearch(loc, term) {
    if (!term) return true;
    var t = term.toLowerCase();
    return [loc.name, loc.category, loc.city, loc.county,
            loc.address, loc.state, loc.notes, loc.hours, loc.event_date]
      .some(function(f) { return f && String(f).toLowerCase().indexOf(t) !== -1; });
  }

  // ── List view ─────────────────────────────────────────────────────────────────

  function renderListCards(locations, gridEl) {
    var term     = listSearchTerm;
    var filtered = term
      ? locations.filter(function(loc) { return matchesSearch(loc, term); })
      : locations;

    if (!locations.length) {
      var msg = listEmptyReason === "no-categories"
        ? "Select at least one category to see places here."
        : "No places match the current filters.";
      gridEl.innerHTML = '<div class="list-empty">' + msg + '</div>';
      return;
    }

    if (!filtered.length) {
      gridEl.innerHTML = '<div class="list-empty">No matching places found.</div>';
      return;
    }

    var html = '<div class="list-grid">';
    filtered.forEach(function(loc) {
      var desc = "";
      if (loc.event_date) desc = loc.event_date;
      else if (loc.notes)  desc = loc.notes.length > 110 ? loc.notes.substring(0, 110) + "…" : loc.notes;
      else if (loc.hours)  desc = loc.hours;

      var location = "";
      if (loc.city && loc.county) location = loc.city + " · " + loc.county + " Co.";
      else if (loc.city)          location = loc.city;
      else if (loc.county)        location = loc.county + " County";

      var color = loc.category_color || "#3d72c8";

      html += '<div class="list-card" data-id="' + loc.id + '">';
      html += '<div class="list-card-header">';
      html += '<span class="list-card-name">' + escapeHtml(loc.name) + '</span>';
      html += '<span class="list-card-cat" style="background:' + escapeHtml(color) + '">' + escapeHtml(loc.category || "") + '</span>';
      html += '</div>';
      if (location) html += '<div class="list-card-location">' + escapeHtml(location) + '</div>';
      if (desc)     html += '<div class="list-card-desc">'     + escapeHtml(desc) + '</div>';
      html += '</div>';
    });
    html += '</div>';
    gridEl.innerHTML = html;

    gridEl.querySelectorAll(".list-card").forEach(function(card) {
      card.addEventListener("click", function() {
        var id      = parseInt(card.dataset.id, 10);
        var listLoc = currentLocations.find(function(l) { return l.id === id; });
        EventMapAPI.getLocation(id).then(function(fullLoc) {
          if (listLoc) fullLoc.category_color = listLoc.category_color;
          renderDetail(fullLoc, "list");
        });
      });
    });
  }

  function renderListView(locations) {
    var listEl = document.getElementById("list-view");

    // Rebuild shell: sticky search box + grid container
    listEl.innerHTML =
      '<div class="list-search-wrap">' +
        '<input type="search" id="list-search" class="list-search" ' +
               'placeholder="Search places, towns, crops…" autocomplete="off">' +
      '</div>' +
      '<div id="list-grid-container"></div>';

    var searchInput = document.getElementById("list-search");
    var gridEl      = document.getElementById("list-grid-container");

    // Restore any active search term (preserved across filter changes)
    searchInput.value = listSearchTerm;

    searchInput.addEventListener("input", function() {
      listSearchTerm = this.value;
      renderListCards(locations, gridEl);
    });

    renderListCards(locations, gridEl);
  }

  // ── View toggle ───────────────────────────────────────────────────────────────

  function setView(view) {
    currentView = view;
    var mapEl  = document.getElementById("map");
    var listEl = document.getElementById("list-view");
    var btnMap  = document.getElementById("toggle-map");
    var btnList = document.getElementById("toggle-list");

    btnMap.classList.toggle("view-btn-active",  view === "map");
    btnList.classList.toggle("view-btn-active", view === "list");
    btnMap.setAttribute("aria-pressed",  String(view === "map"));
    btnList.setAttribute("aria-pressed", String(view === "list"));

    if (view === "map") {
      mapEl.style.display  = "";
      listEl.style.display = "none";
      EventMapMap.invalidateSize();
    } else {
      mapEl.style.display  = "none";
      listEl.style.display = "";
      renderListView(currentLocations);
    }
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function() {
    detailPanel  = document.getElementById("detail-panel");
    detailContent = document.getElementById("detail-content");
    resultCount  = document.getElementById("result-count");

    document.getElementById("detail-close").onclick = function() {
      detailPanel.classList.remove("open");
    };

    document.getElementById("detail-back").onclick = function() {
      detailPanel.classList.remove("open");
    };

    document.getElementById("detail-minimap").onclick = function() {
      if (currentDetailLoc && currentDetailLoc.lat != null && currentDetailLoc.lng != null) {
        setView("map");
        EventMapMap.panTo(currentDetailLoc.lat, currentDetailLoc.lng, 15);
        detailPanel.classList.remove("open");
      }
    };

    document.getElementById("toggle-map").onclick  = function() { setView("map"); };
    document.getElementById("toggle-list").onclick = function() { setView("list"); };

    EventMapMap.init("map");

    EventMapMap.setOnMarkerClick(function(loc) {
      EventMapAPI.getLocation(loc.id).then(function(fullLoc) {
        fullLoc.category_color = loc.category_color;
        renderDetail(fullLoc, "map");
      });
    });

    EventMapFilters.init({
      categories: document.getElementById("category-chips"),
      crop:       document.getElementById("crop-select"),
      month:      document.getElementById("month-select"),
      pyo:        document.getElementById("pyo-toggle"),
      organic:    document.getElementById("organic-toggle")
    }, {
      onChange: function(f) {
        if (f._empty) {
          listEmptyReason   = "no-categories";
          currentLocations  = [];
          EventMapMap.renderLocations([]);
          if (resultCount) resultCount.textContent = "0 items";
          if (currentView === "list") renderListView([]);
          return;
        }
        EventMapAPI.getLocations(f).then(function(ls) {
          listEmptyReason  = ls.length === 0 ? "no-results" : "";
          currentLocations = ls;
          EventMapMap.renderLocations(ls);
          if (resultCount) resultCount.textContent = ls.length + " item" + (ls.length === 1 ? "" : "s");
          if (currentView === "list") renderListView(ls);
        });
      }
    });
  });
})();

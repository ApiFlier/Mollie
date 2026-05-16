(function () {
  var state = {
    dateFilter: "this_weekend",
    startDate:  "",
    endDate:    "",
    maxMiles:   30,
    savedOnly:  false,
    sort:       "soonest",
    loading:    false,
    cacheStale: false,
    searchText: "",
    allEvents:  [],
  };

  // ── Date helpers ──────────────────────────────────────────────────────────────

  function localDateStr(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function thisWeekendRange() {
    var today = new Date();
    var dow = today.getDay(); // 0=Sun … 6=Sat
    var start, end;
    if (dow === 0) {
      start = new Date(today); end = new Date(today);
    } else if (dow >= 1 && dow <= 4) {
      start = new Date(today); start.setDate(today.getDate() + (5 - dow));
      end = new Date(start);   end.setDate(start.getDate() + 2);
    } else if (dow === 5) {
      start = new Date(today); end = new Date(today); end.setDate(today.getDate() + 2);
    } else {
      start = new Date(today); end = new Date(today); end.setDate(today.getDate() + 1);
    }
    return { start: localDateStr(start), end: localDateStr(end) };
  }

  // ── Filter summary ────────────────────────────────────────────────────────────

  function buildFilterSummary() {
    var parts = [];

    if (state.dateFilter === "") {
      parts.push("Any date");
    } else if (state.dateFilter === "today") {
      parts.push("Today");
    } else if (state.dateFilter === "this_weekend") {
      parts.push("This weekend");
    } else if (state.dateFilter === "custom") {
      var s = state.startDate || (document.getElementById("start-date") || {}).value || "";
      var e = state.endDate   || (document.getElementById("end-date")   || {}).value || "";
      if (s && e && s !== e) {
        parts.push(s + "–" + e);
      } else if (s) {
        parts.push(s);
      } else {
        parts.push("Custom date");
      }
    }

    if (state.maxMiles == null) {
      parts.push("Any distance");
    } else {
      parts.push(state.maxMiles + " mi");
    }

    parts.push(state.sort === "closest" ? "Closest" : "Soonest");

    if (state.savedOnly) parts.push("Saved");

    return parts.join(" · ");
  }

  function updateFilterSummary() {
    var el = document.getElementById("ev-filter-summary");
    if (el) el.textContent = buildFilterSummary();
  }

  function syncButtonStates() {
    // Date buttons
    document.querySelectorAll("#date-filter-row .ev-filter-btn").forEach(function (btn) {
      btn.classList.toggle("ev-filter-active", btn.dataset.date === state.dateFilter);
    });
    var customDateRow = document.getElementById("custom-date-row");
    if (customDateRow) customDateRow.style.display = state.dateFilter === "custom" ? "" : "none";

    // Distance buttons
    var milesStr = state.maxMiles == null ? "" : String(state.maxMiles);
    document.querySelectorAll("#dist-filter-row .ev-filter-btn").forEach(function (btn) {
      btn.classList.toggle("ev-filter-active", btn.dataset.miles === milesStr);
    });

    // Sort buttons
    document.querySelectorAll(".ev-sort-btn").forEach(function (btn) {
      btn.classList.toggle("ev-sort-active", btn.dataset.sort === state.sort);
    });

    // Saved button
    var savedBtn = document.querySelector(".ev-saved-btn");
    if (savedBtn) savedBtn.classList.toggle("ev-filter-active", state.savedOnly);
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function esc(s) {
    return s ? String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;") : "";
  }

  function formatDate(isoStr) {
    if (!isoStr) return null;
    try {
      var d = new Date(isoStr.replace(" ", "T") + (isoStr.length === 19 ? "Z" : ""));
      var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
      var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      return days[d.getUTCDay()] + " " + months[d.getUTCMonth()] + " " + d.getUTCDate();
    } catch (e) {
      return null;
    }
  }

  function formatTime(isoStr) {
    if (!isoStr) return null;
    try {
      var d = new Date(isoStr.replace(" ", "T") + (isoStr.length === 19 ? "Z" : ""));
      var h = d.getUTCHours();
      var m = d.getUTCMinutes();
      var ampm = h >= 12 ? "pm" : "am";
      h = h % 12 || 12;
      return h + (m ? ":" + String(m).padStart(2, "0") : "") + ampm;
    } catch (e) {
      return null;
    }
  }

  function distLabel(miles) {
    if (miles == null) return null;
    var m = parseFloat(miles);
    if (!isFinite(m) || m < 0.1) return null;
    return m.toFixed(1) + " mi";
  }

  function directionsUrl(ev) {
    if (ev.latitude != null && ev.longitude != null) {
      var lat = parseFloat(ev.latitude);
      var lng = parseFloat(ev.longitude);
      if (Math.abs(lat - 40.4406) < 0.001 && Math.abs(lng + 79.9959) < 0.001) {
        // fall through to address-based
      } else {
        return "https://www.google.com/maps/dir/?api=1&destination=" + lat + "," + lng;
      }
    }
    var parts = [ev.address, ev.city, ev.state, ev.postal_code].filter(Boolean).join(", ");
    if (parts) return "https://www.google.com/maps/dir/?api=1&destination=" + encodeURIComponent(parts);
    return null;
  }

  function sourceColor(sourceKey) {
    var colors = {
      positively_pgh:   "#7c5cc8",
      visit_pittsburgh: "#2d68b8",
    };
    return colors[sourceKey] || "#7c5cc8";
  }

  var SOURCE_HOMEPAGES = {
    positively_pgh:   "https://positivelypittsburgh.com/calendar/",
    visit_pittsburgh: "https://www.visitpittsburgh.com/",
  };

  function sourceHomeUrl(sourceKey) {
    return SOURCE_HOMEPAGES[sourceKey] || null;
  }

  function isGenericDesc(desc) {
    if (!desc || desc.trim().length < 20) return true;
    var lc = desc.toLowerCase().trim();
    if (lc.startsWith("the event is held on")) return true;
    if (lc.startsWith("the event is free")) return true;
    return false;
  }

  // ── Near-duplicate suppression ────────────────────────────────────────────────

  function normalizeTitle(title) {
    return (title || "")
      .toLowerCase()
      .replace(/\b202\d\b/g, "")
      .replace(/[-–—]/g, " ")
      .replace(/[^a-z0-9 ]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeVenue(v) {
    return (v || "")
      .toLowerCase()
      .replace(/^(the|a|an)\s+/, "")
      .replace(/[^a-z0-9 ]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function venueMatch(a, b) {
    var na = normalizeVenue(a);
    var nb = normalizeVenue(b);
    if (na.length < 6 || nb.length < 6) return false;
    var shorter = na.length <= nb.length ? na : nb;
    var longer  = na.length <= nb.length ? nb : na;
    return longer.startsWith(shorter);
  }

  function locationMatch(a, b) {
    if (a.source_url   && b.source_url   && a.source_url   === b.source_url)   return true;
    if (a.official_url && b.official_url && a.official_url === b.official_url) return true;
    if (venueMatch(a.venue_name, b.venue_name)) return true;
    return false;
  }

  function eventScore(ev) {
    return (
      (ev.latitude != null ? 4 : 0) +
      (ev.source_url ? 2 : 0) +
      (ev.official_url ? 1 : 0) +
      (ev.address ? 1 : 0)
    );
  }

  function dedupeDisplay(events) {
    var seen = {};
    var result = [];
    var suppressed = 0;

    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      var date = (ev.start_datetime || "").substring(0, 10);
      var nt = normalizeTitle(ev.title).substring(0, 60);
      var key = date + "|" + nt;

      if (!seen[key]) {
        seen[key] = [result.length];
        result.push(ev);
      } else {
        var matchIdx = null;
        for (var k = 0; k < seen[key].length; k++) {
          if (locationMatch(ev, result[seen[key][k]])) {
            matchIdx = seen[key][k];
            break;
          }
        }
        if (matchIdx !== null) {
          if (eventScore(ev) > eventScore(result[matchIdx])) {
            result[matchIdx] = ev;
          }
          suppressed++;
        } else {
          seen[key].push(result.length);
          result.push(ev);
        }
      }
    }

    if (suppressed > 0) {
      console.log("[events] display dedup: kept " + result.length + ", suppressed " + suppressed + " near-duplicates");
    }
    return result;
  }

  // ── Client-side text search ───────────────────────────────────────────────────

  function applyAndRender() {
    var events = state.allEvents;
    var q = state.searchText.trim().toLowerCase();
    if (q) {
      events = events.filter(function (ev) {
        var haystack = [
          ev.title,
          ev.venue_name,
          ev.city,
          ev.state,
          ev.address,
          ev.category,
          ev.description_short,
          ev.display_name,
          ev.admission,
        ].filter(Boolean).join(" ").toLowerCase();
        return haystack.indexOf(q) !== -1;
      });
    }
    renderEvents(events);
  }

  // ── Card rendering ────────────────────────────────────────────────────────────

  function renderCard(ev) {
    var dateStr  = ev.date_label || formatDate(ev.start_datetime) || "See website";
    var timeStr  = ev.start_datetime ? formatTime(ev.start_datetime) : null;
    var dist     = distLabel(ev.distance_miles);
    var dirUrl   = directionsUrl(ev);
    var srcColor = sourceColor(ev.source_key);
    var srcLabel = ev.display_name || ev.source_key;
    var saved    = ev.saved ? " ev-card-saved" : "";

    var html = '<div class="ev-card' + saved + '" data-id="' + ev.id + '">';

    var homeUrl = sourceHomeUrl(ev.source_key);
    html += '<div class="ev-card-header">';
    if (homeUrl) {
      html += '<a href="' + esc(homeUrl) + '" class="ev-source-chip ev-source-chip-link"'
            + ' style="background:' + esc(srcColor) + '"'
            + ' target="_blank" rel="noopener"'
            + ' title="Open ' + esc(srcLabel) + ' source site"'
            + ' aria-label="Open ' + esc(srcLabel) + ' source site">'
            + esc(srcLabel) + '</a>';
    } else {
      html += '<span class="ev-source-chip" style="background:' + esc(srcColor) + '">' + esc(srcLabel) + '</span>';
    }
    html += '<span class="ev-header-date">' + esc(dateStr);
    if (timeStr) html += '<span class="ev-header-time"> · ' + esc(timeStr) + '</span>';
    html += '</span>';
    html += '</div>';

    html += '<div class="ev-card-body">';
    html += '<div class="ev-title">' + esc(ev.title) + '</div>';

    var hasMeta = (ev.category && ev.category !== "featured" && ev.category !== "event") || dist;
    if (hasMeta) {
      html += '<div class="ev-meta-row">';
      if (ev.category && ev.category !== "featured" && ev.category !== "event") {
        html += '<span class="ev-category-tag">' + esc(ev.category) + '</span>';
      }
      if (dist) {
        html += '<span class="ev-drive-pill">' + esc(dist) + '</span>';
      }
      html += '</div>';
    }

    var addrLines = [];
    if (ev.venue_name) addrLines.push(ev.venue_name);
    if (ev.address)    addrLines.push(ev.address);
    var cityState = [ev.city, ev.state].filter(Boolean).join(", ");
    if (ev.postal_code) cityState += " " + ev.postal_code;
    if (cityState)     addrLines.push(cityState);

    if (addrLines.length) {
      html += '<div class="ev-address">';
      for (var j = 0; j < addrLines.length; j++) {
        html += '<span class="ev-address-line">' + esc(addrLines[j]) + '</span>';
      }
      html += '</div>';
    }

    if (ev.admission) {
      html += '<div class="ev-admission">' + esc(ev.admission) + '</div>';
    }

    if (!isGenericDesc(ev.description_short)) {
      html += '<div class="ev-desc">' + esc(ev.description_short) + '</div>';
    }

    html += '</div>';

    html += '<div class="ev-actions">';
    if (ev.source_url) {
      html += '<a href="' + esc(ev.source_url) + '" class="ev-btn ev-btn-primary" target="_blank" rel="noopener">Open Event</a>';
    }
    if (ev.official_url && ev.official_url !== ev.source_url) {
      html += '<a href="' + esc(ev.official_url) + '" class="ev-btn ev-btn-secondary" target="_blank" rel="noopener">Website</a>';
    }
    if (dirUrl) {
      html += '<a href="' + esc(dirUrl) + '" class="ev-btn ev-btn-secondary" target="_blank" rel="noopener">Directions</a>';
    }
    var saveLabel = ev.saved ? "Unsave" : "Save";
    html += '<button class="ev-btn ev-btn-ghost ev-save-btn" data-id="' + ev.id + '" data-saved="' + (ev.saved ? "1" : "0") + '">' + saveLabel + '</button>';
    html += '<button class="ev-btn ev-btn-ghost ev-hide-btn" data-id="' + ev.id + '">Hide</button>';
    html += '</div>';

    html += '</div>';
    return html;
  }

  // ── Render list ───────────────────────────────────────────────────────────────

  function renderEvents(events) {
    var listEl = document.getElementById("events-list");
    if (!events || !events.length) {
      var q = state.searchText.trim();
      if (q) {
        listEl.innerHTML = '<div class="ev-empty">No events found for "' + esc(q) + '" with the current filters.</div>';
      } else {
        listEl.innerHTML = '<div class="ev-empty">No events match your current filters. Try broadening your filters, or <button class="ev-refresh-link" id="manual-refresh-btn">refresh sources</button>.</div>';
        document.getElementById("manual-refresh-btn").addEventListener("click", function () {
          manualRefresh();
        });
      }
      return;
    }

    var deduped = dedupeDisplay(events);
    var todayStr    = localDateStr(new Date());
    var tomorrowD   = new Date(); tomorrowD.setDate(tomorrowD.getDate() + 1);
    var tomorrowStr = localDateStr(tomorrowD);

    var html = "";
    var lastDate = null;
    for (var i = 0; i < deduped.length; i++) {
      var ev = deduped[i];
      var dateKey = ev.start_datetime ? ev.start_datetime.substring(0, 10) : "undated";
      if (dateKey !== lastDate) {
        var label;
        if (dateKey === "undated") {
          label = "See Website for Dates";
        } else if (dateKey === todayStr) {
          label = "Today";
        } else if (dateKey === tomorrowStr) {
          label = "Tomorrow";
        } else {
          try {
            var d = new Date(dateKey + "T12:00:00Z");
            var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            var days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
            label = days[d.getUTCDay()] + ", " + months[d.getUTCMonth()] + " " + d.getUTCDate();
          } catch (ex) {
            label = dateKey;
          }
        }
        html += '<div class="ev-date-divider">' + esc(label) + '</div>';
        lastDate = dateKey;
      }
      html += renderCard(ev);
    }

    listEl.innerHTML = html;
    bindCardActions();
  }

  // ── Button actions ─────────────────────────────────────────────────────────────

  function bindCardActions() {
    document.querySelectorAll(".ev-save-btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = parseInt(btn.dataset.id);
        var saved = btn.dataset.saved === "1";
        fetch("/api/events/" + id + "/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ saved: !saved }),
        }).then(function () {
          loadEvents();
        }).catch(function (err) {
          console.error("save error", err);
        });
      });
    });

    document.querySelectorAll(".ev-hide-btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = parseInt(btn.dataset.id);
        var card = btn.closest(".ev-card");
        if (card) card.style.opacity = "0.4";
        fetch("/api/events/" + id + "/hide", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hidden: true }),
        }).then(function () {
          if (card) card.remove();
        }).catch(function (err) {
          console.error("hide error", err);
        });
      });
    });
  }

  // ── Status banner ────────────────────────────────────────────────────────────

  function showStatus(msg, type) {
    var el = document.getElementById("events-status");
    el.textContent = msg;
    el.className = "events-status events-status-" + (type || "info");
    el.style.display = "";
  }

  function hideStatus() {
    var el = document.getElementById("events-status");
    el.style.display = "none";
  }

  // ── Fetch from API ────────────────────────────────────────────────────────────

  function loadEvents() {
    if (state.loading) return;
    state.loading = true;

    var params = new URLSearchParams();

    // Compute local dates for today/this_weekend to avoid UTC shift
    if (state.dateFilter === "today") {
      var tod = localDateStr(new Date());
      params.set("date_filter", "custom");
      params.set("start_date", tod);
      params.set("end_date", tod);
    } else if (state.dateFilter === "this_weekend") {
      var wr = thisWeekendRange();
      params.set("date_filter", "custom");
      params.set("start_date", wr.start);
      params.set("end_date", wr.end);
    } else if (state.dateFilter === "custom") {
      state.startDate = (document.getElementById("start-date") || {}).value || "";
      state.endDate   = (document.getElementById("end-date")   || {}).value || "";
      if (state.startDate) {
        params.set("date_filter", "custom");
        params.set("start_date", state.startDate);
        if (state.endDate) params.set("end_date", state.endDate);
      }
    } else if (state.dateFilter) {
      params.set("date_filter", state.dateFilter);
    }

    if (state.maxMiles != null) params.set("max_distance_miles", state.maxMiles);
    if (state.savedOnly) params.set("saved", "1");
    params.set("sort", state.sort);
    params.set("limit", "200");

    fetch("/api/events?" + params.toString())
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        state.loading = false;
        state.cacheStale = data.cache_stale;

        if (data.cache_stale && (!data.events || data.events.length === 0)) {
          showStatus("Loading events from sources — check back in a moment.", "loading");
          state.allEvents = [];
          applyAndRender();
          setTimeout(loadEvents, 5000);
        } else {
          if (data.cache_stale) {
            showStatus("Refreshing events in the background…", "loading");
            setTimeout(function () {
              loadEvents();
              hideStatus();
            }, 8000);
          } else {
            hideStatus();
          }
          state.allEvents = data.events || [];
          applyAndRender();
        }
      })
      .catch(function (err) {
        state.loading = false;
        showStatus("Could not load events. Check your connection.", "error");
        console.error("events load error", err);
      });
  }

  // ── Manual refresh ────────────────────────────────────────────────────────────

  function manualRefresh() {
    showStatus("Refreshing events from all sources…", "loading");
    fetch("/api/events/refresh", { method: "POST" })
      .then(function (r) {
        if (r.status === 401) {
          showStatus("Refresh requires admin login.", "error");
          return;
        }
        return r.json();
      })
      .then(function (data) {
        if (data) {
          hideStatus();
          loadEvents();
        }
      })
      .catch(function (err) {
        showStatus("Refresh failed. Are you logged into the admin panel?", "error");
        console.error("refresh error", err);
      });
  }

  // ── Controls ──────────────────────────────────────────────────────────────────

  function initControls() {
    // ── Collapsible filter panel ──────────────────────────────────────────────
    var toggleBtn = document.getElementById("ev-filters-toggle");
    var panel = document.getElementById("ev-filters-panel");
    if (toggleBtn && panel) {
      toggleBtn.addEventListener("click", function () {
        var open = panel.classList.toggle("ev-filters-open");
        toggleBtn.classList.toggle("ev-toggle-active", open);
        toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    // ── Date filter ────────────────────────────────────────────────────────────
    document.querySelectorAll("#date-filter-row .ev-filter-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("#date-filter-row .ev-filter-btn").forEach(function (b) {
          b.classList.remove("ev-filter-active");
        });
        btn.classList.add("ev-filter-active");
        state.dateFilter = btn.dataset.date;
        document.getElementById("custom-date-row").style.display =
          state.dateFilter === "custom" ? "" : "none";
        updateFilterSummary();
        if (state.dateFilter !== "custom") loadEvents();
      });
    });

    function maybeLoadCustomDates() {
      if (state.dateFilter === "custom") {
        state.startDate = document.getElementById("start-date").value;
        state.endDate   = document.getElementById("end-date").value;
        if (state.startDate) loadEvents();
      }
    }

    document.getElementById("start-date").addEventListener("change", function () {
      updateFilterSummary();
      maybeLoadCustomDates();
    });

    document.getElementById("end-date").addEventListener("change", function () {
      var startEl = document.getElementById("start-date");
      var endEl   = document.getElementById("end-date");
      // Silently swap if end is before start
      if (startEl.value && endEl.value && endEl.value < startEl.value) {
        var tmp = startEl.value;
        startEl.value = endEl.value;
        endEl.value = tmp;
      }
      updateFilterSummary();
      maybeLoadCustomDates();
    });

    // ── Distance filter ───────────────────────────────────────────────────────
    document.querySelectorAll("#dist-filter-row .ev-filter-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("#dist-filter-row .ev-filter-btn").forEach(function (b) {
          b.classList.remove("ev-filter-active");
        });
        btn.classList.add("ev-filter-active");
        var val = btn.dataset.miles;
        document.getElementById("custom-miles-row").style.display =
          val === "custom" ? "" : "none";
        if (val !== "custom") {
          state.maxMiles = val === "" ? null : parseInt(val, 10);
          updateFilterSummary();
          loadEvents();
        }
      });
    });

    document.getElementById("custom-miles-apply").addEventListener("click", function () {
      var v = parseInt(document.getElementById("custom-miles-input").value, 10);
      if (v > 0) {
        state.maxMiles = v;
        updateFilterSummary();
        loadEvents();
      }
    });

    document.getElementById("custom-miles-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") document.getElementById("custom-miles-apply").click();
    });

    // ── Saved quick filter ────────────────────────────────────────────────────
    var savedBtn = document.querySelector(".ev-saved-btn");
    savedBtn.addEventListener("click", function () {
      state.savedOnly = !state.savedOnly;
      savedBtn.classList.toggle("ev-filter-active", state.savedOnly);
      updateFilterSummary();
      loadEvents();
    });

    // ── Sort ──────────────────────────────────────────────────────────────────
    document.querySelectorAll(".ev-sort-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".ev-sort-btn").forEach(function (b) {
          b.classList.remove("ev-sort-active");
        });
        btn.classList.add("ev-sort-active");
        state.sort = btn.dataset.sort;
        updateFilterSummary();
        loadEvents();
      });
    });

    // ── Search ────────────────────────────────────────────────────────────────
    var searchInput = document.getElementById("ev-search-input");
    var searchClear = document.getElementById("ev-search-clear");
    var _searchTimer = null;

    searchInput.addEventListener("input", function () {
      clearTimeout(_searchTimer);
      var val = searchInput.value;
      searchClear.style.display = val ? "" : "none";
      _searchTimer = setTimeout(function () {
        state.searchText = val;
        applyAndRender();
      }, 150);
    });

    searchClear.addEventListener("click", function () {
      searchInput.value = "";
      searchClear.style.display = "none";
      state.searchText = "";
      applyAndRender();
      searchInput.focus();
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    syncButtonStates();
    updateFilterSummary();
    initControls();
    loadEvents();
  });
})();

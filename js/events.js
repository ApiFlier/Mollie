(function () {
  // Holds the admin-configured defaults; updated from /api/settings before init.
  // Fallback values match the in-state defaults so the badge counter is always correct.
  var _appDefaults = {
    dateFilter: "this_weekend",
    maxMiles:   30,
    sort:       "soonest",
    priceFilter: "any",
    savedOnly:  false,
  };

  var state = {
    dateFilter:    "this_weekend",
    startDate:     "",
    endDate:       "",
    maxMiles:      30,
    savedOnly:     false,
    sort:          "soonest",
    loading:       false,
    cacheStale:    false,
    searchText:    "",
    allEvents:     [],
    // Sources: null = all enabled; array of source_keys = selected subset
    sourcesFilter:  null,
    allSources:     [], // [{source_key, display_name}] from /api/sources
    // Price filter
    priceFilter:    "any",  // "any"|"free"|"listed"|"unknown"|"under10"|"under20"|"custom"
    customMaxPrice: null,   // number, used when priceFilter="custom"
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

  function _addDays(dateStr, n) {
    var p = dateStr.split("-");
    var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    d.setDate(d.getDate() + n);
    return localDateStr(d);
  }

  function nextWeekendRange() {
    var wr = thisWeekendRange();
    return { start: _addDays(wr.start, 7), end: _addDays(wr.end, 7) };
  }

  function weekendAfterNextRange() {
    var wr = thisWeekendRange();
    return { start: _addDays(wr.start, 14), end: _addDays(wr.end, 14) };
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
    } else if (state.dateFilter === "next_weekend") {
      parts.push("Next weekend");
    } else if (state.dateFilter === "weekend_after_next") {
      parts.push("Weekend after next");
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

    // Price filter — only mention when not "any"
    if (state.priceFilter === "free")     parts.push("Free only");
    else if (state.priceFilter === "listed")  parts.push("Price listed");
    else if (state.priceFilter === "unknown") parts.push("Price not listed");
    else if (state.priceFilter === "under10") parts.push("Under $10");
    else if (state.priceFilter === "under20") parts.push("Under $20");
    else if (state.priceFilter === "custom" && state.customMaxPrice != null)
      parts.push("Under $" + state.customMaxPrice);

    // Source filter — only mention when a subset is selected
    if (state.sourcesFilter !== null && state.allSources.length > 0) {
      if (state.sourcesFilter.length === 0) {
        parts.push("No sources");
      } else if (state.sourcesFilter.length < state.allSources.length) {
        var labels = state.sourcesFilter.map(function (k) {
          var s = state.allSources.find(function (x) { return x.source_key === k; });
          return s ? s.display_name : k;
        });
        parts.push(labels.join(" + ") + " only");
      }
    }

    return parts.join(" · ");
  }

  function updateFilterSummary() {
    var el = document.getElementById("ev-filter-summary");
    if (el) el.textContent = buildFilterSummary();

    // Refine button: keep count and tint in sync with filter state
    var refineBtn = document.getElementById("ev-filters-toggle");
    if (refineBtn) {
      var nActive = countActiveFilters();
      refineBtn.textContent = nActive > 0 ? "Refine (" + nActive + ")" : "Refine";
      refineBtn.classList.toggle("ev-refine-active", nActive > 0);
    }

  }

  function countActiveFilters() {
    var n = 0;
    if (state.dateFilter !== _appDefaults.dateFilter) n++;
    if (state.maxMiles  !== _appDefaults.maxMiles)    n++;
    if (state.sort      !== _appDefaults.sort)        n++;
    if (state.savedOnly !== _appDefaults.savedOnly)   n++;
    if (state.priceFilter !== _appDefaults.priceFilter) n++;
    if (state.sourcesFilter !== null) n++;
    return n;
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

    // View toggle (All Events / Saved Events)
    var viewAll   = document.getElementById("ev-view-all");
    var viewSaved = document.getElementById("ev-view-saved");
    if (viewAll)   viewAll.classList.toggle("ev-view-btn-active",  !state.savedOnly);
    if (viewSaved) viewSaved.classList.toggle("ev-view-btn-active",  state.savedOnly);

    // Price filter buttons
    document.querySelectorAll("#price-filter-row .ev-filter-btn").forEach(function (btn) {
      btn.classList.toggle("ev-filter-active", btn.dataset.price === state.priceFilter);
    });
    var customPriceRow = document.getElementById("custom-price-row");
    if (customPriceRow) customPriceRow.style.display = state.priceFilter === "custom" ? "" : "none";

    // Source chips — sync after sources are loaded
    _syncSourceChips();
  }

  function _syncSourceChips() {
    var panel = document.getElementById("source-chip-row");
    if (!panel) return;
    panel.querySelectorAll(".ev-source-chip-btn").forEach(function (btn) {
      var key = btn.dataset.source;
      var active = state.sourcesFilter === null || state.sourcesFilter.indexOf(key) !== -1;
      btn.classList.toggle("ev-filter-active", active);
    });
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

  function sourceHomeUrl(sourceKey) {
    var source = state.allSources.find(function (item) { return item.source_key === sourceKey; });
    return source ? source.homepage_url || null : null;
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

  function renderCostBadge(ev) {
    if (ev.admission === "Free") {
      return '<span class="ev-free-pill">Free</span>';
    }
    if (ev.admission) {
      return '<span class="ev-paid-pill">' + esc(ev.admission) + '</span>';
    }
    return '';
  }

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

    html += '<div class="ev-meta-row">';
    if (ev.category && ev.category !== "featured" && ev.category !== "event") {
      html += '<span class="ev-category-tag">' + esc(ev.category) + '</span>';
    }
    if (dist) {
      html += '<span class="ev-drive-pill">' + esc(dist) + '</span>';
    }
    html += renderCostBadge(ev);
    html += '</div>';

    var addrLines = [];
    var cityState = [ev.city, ev.state].filter(Boolean).join(", ");
    if (ev.venue_name) {
      addrLines.push(ev.venue_name);
      if (cityState) addrLines.push(cityState);
    } else {
      if (ev.address) addrLines.push(ev.address);
      if (cityState)  addrLines.push(cityState);
    }

    if (addrLines.length) {
      html += '<div class="ev-address">';
      for (var j = 0; j < addrLines.length; j++) {
        html += '<span class="ev-address-line">' + esc(addrLines[j]) + '</span>';
      }
      html += '</div>';
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
    var saveLabel = ev.saved ? "Saved" : "Save";
    var saveCls   = ev.saved ? " ev-save-btn-saved" : "";
    html += '<button class="ev-btn ev-btn-ghost ev-save-btn' + saveCls + '" data-id="' + ev.id + '" data-saved="' + (ev.saved ? "1" : "0") + '">' + saveLabel + '</button>';
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
      if (state.savedOnly) {
        listEl.innerHTML = '<div class="ev-empty">No saved events yet.<br><span style="font-size:13px;display:block;margin-top:6px">Tap <strong>Save</strong> on any event to bookmark it for later.</span></div>';
      } else if (q) {
        listEl.innerHTML = '<div class="ev-empty">No results for “' + esc(q) + '” — try different words or clear the search.</div>';
      } else {
        listEl.innerHTML = '<div class="ev-empty">Nothing here with these filters. Try a wider date or distance, or <button class="ev-refresh-link" id="manual-refresh-btn">refresh events</button>.</div>';
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
    } else if (state.dateFilter === "next_weekend") {
      var nwr = nextWeekendRange();
      params.set("date_filter", "custom");
      params.set("start_date", nwr.start);
      params.set("end_date", nwr.end);
    } else if (state.dateFilter === "weekend_after_next") {
      var wan = weekendAfterNextRange();
      params.set("date_filter", "custom");
      params.set("start_date", wan.start);
      params.set("end_date", wan.end);
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

    // Price filter
    if (state.priceFilter === "free") {
      params.set("price_filter", "free");
    } else if (state.priceFilter === "listed") {
      params.set("price_filter", "listed");
    } else if (state.priceFilter === "unknown") {
      params.set("price_filter", "unknown");
    } else if (state.priceFilter === "under10") {
      params.set("price_filter", "max");
      params.set("max_price", "10");
    } else if (state.priceFilter === "under20") {
      params.set("price_filter", "max");
      params.set("max_price", "20");
    } else if (state.priceFilter === "custom" && state.customMaxPrice != null) {
      params.set("price_filter", "max");
      params.set("max_price", String(state.customMaxPrice));
    }

    // Source filter: only pass if a strict subset is selected
    if (state.sourcesFilter !== null && state.sourcesFilter.length > 0 &&
        state.sourcesFilter.length < state.allSources.length) {
      params.set("source_keys", state.sourcesFilter.join(","));
    } else if (state.sourcesFilter !== null && state.sourcesFilter.length === 0) {
      // Nothing selected — return empty results (no-op: send impossible source)
      params.set("source_keys", "__none__");
    }

    fetch("/api/events?" + params.toString())
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        state.loading = false;
        state.cacheStale = data.cache_stale;

        if (data.cache_stale && (!data.events || data.events.length === 0)) {
          showStatus("Finding events near you…", "loading");
          state.allEvents = [];
          applyAndRender();
          setTimeout(loadEvents, 5000);
        } else {
          if (data.cache_stale) {
            setTimeout(function () {
              loadEvents();
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
        showStatus("Couldn’t load events. Check your connection and try again.", "error");
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
        var summaryEl = document.getElementById("ev-filter-summary");
        if (summaryEl) summaryEl.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    // Tapping the filter summary also opens/closes the filter panel
    var summaryEl = document.getElementById("ev-filter-summary");
    if (summaryEl && toggleBtn) {
      summaryEl.addEventListener("click", function () {
        toggleBtn.click();
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

    // ── All Events / Saved Events view toggle ────────────────────────────────
    var viewAllBtn   = document.getElementById("ev-view-all");
    var viewSavedBtn = document.getElementById("ev-view-saved");
    if (viewAllBtn) {
      viewAllBtn.addEventListener("click", function () {
        state.savedOnly = false;
        syncButtonStates();
        updateFilterSummary();
        loadEvents();
      });
    }
    if (viewSavedBtn) {
      viewSavedBtn.addEventListener("click", function () {
        state.savedOnly = true;
        syncButtonStates();
        updateFilterSummary();
        loadEvents();
      });
    }

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

    // ── Source filter ─────────────────────────────────────────────────────────
    // Source chips are built dynamically after /api/sources loads (see loadSources).

    // ── Price filter ──────────────────────────────────────────────────────────
    document.querySelectorAll("#price-filter-row .ev-filter-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("#price-filter-row .ev-filter-btn").forEach(function (b) {
          b.classList.remove("ev-filter-active");
        });
        btn.classList.add("ev-filter-active");
        state.priceFilter = btn.dataset.price;
        var customPriceRow = document.getElementById("custom-price-row");
        if (customPriceRow) customPriceRow.style.display = state.priceFilter === "custom" ? "" : "none";
        updateFilterSummary();
        if (state.priceFilter !== "custom") loadEvents();
      });
    });

    document.getElementById("custom-price-apply").addEventListener("click", function () {
      var v = parseFloat(document.getElementById("custom-price-input").value);
      if (!isNaN(v) && v >= 0) {
        state.customMaxPrice = v;
        updateFilterSummary();
        loadEvents();
      }
    });

    document.getElementById("custom-price-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") document.getElementById("custom-price-apply").click();
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

  // ── Source filter loading ─────────────────────────────────────────────────────

  function _buildSourceChips(sources) {
    var row = document.getElementById("source-chip-row");
    if (!row) return;
    if (!sources || sources.length < 2) {
      // Only one (or zero) enabled source — hide the whole group
      var group = document.getElementById("source-filter-group");
      if (group) group.style.display = "none";
      return;
    }
    var html = "";
    sources.forEach(function (s) {
      html += '<button class="ev-filter-btn ev-source-chip-btn ev-filter-active"'
            + ' data-source="' + esc(s.source_key) + '">'
            + esc(s.display_name) + '</button>';
    });
    row.innerHTML = html;

    row.querySelectorAll(".ev-source-chip-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.dataset.source;
        // Toggle this source in the filter
        if (state.sourcesFilter === null) {
          // All selected → deselect this one
          state.sourcesFilter = state.allSources
            .map(function (s) { return s.source_key; })
            .filter(function (k) { return k !== key; });
        } else {
          var idx = state.sourcesFilter.indexOf(key);
          if (idx === -1) {
            state.sourcesFilter = state.sourcesFilter.concat([key]);
          } else {
            state.sourcesFilter = state.sourcesFilter.filter(function (k) { return k !== key; });
          }
          // If all selected again, reset to null (all)
          if (state.sourcesFilter.length === state.allSources.length) {
            state.sourcesFilter = null;
          }
        }
        _syncSourceChips();
        updateFilterSummary();
        loadEvents();
      });
    });
  }

  function loadSources() {
    fetch("/api/sources")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        state.allSources = data.sources || [];
        _buildSourceChips(state.allSources);
        // Source filter defaults to all enabled (null = all)
        state.sourcesFilter = null;
        _syncSourceChips();
        updateFilterSummary();
      })
      .catch(function (err) {
        console.warn("[events] could not load sources:", err);
      });
  }

  // ── Init ──────────────────────────────────────────────────────────────────────

  function _applySettings(s) {
    s = s || {};
    // Parse and apply each setting to _appDefaults and state
    var dateVal = s["events.default_date_filter"];
    if (dateVal != null) {
      _appDefaults.dateFilter = dateVal;
      state.dateFilter = dateVal;
    }

    var distVal = s["events.default_distance_miles"];
    if (distVal != null) {
      var parsedMiles = (distVal === "" || distVal === null) ? null : parseInt(distVal, 10);
      _appDefaults.maxMiles = parsedMiles;
      state.maxMiles = parsedMiles;
    }

    var sortVal = s["events.default_sort"];
    if (sortVal != null) {
      _appDefaults.sort = sortVal;
      state.sort = sortVal;
    }

    var priceVal = s["events.default_price_filter"];
    if (priceVal != null) {
      _appDefaults.priceFilter = priceVal;
      state.priceFilter = priceVal;
    }

    var savedVal = s["events.default_saved_view"];
    if (savedVal != null) {
      var savedBool = savedVal === "true";
      _appDefaults.savedOnly = savedBool;
      state.savedOnly = savedBool;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("/api/settings")
      .then(function(r) { return r.ok ? r.json() : {}; })
      .catch(function() { return {}; })
      .then(function(settings) {
        _applySettings(settings);

        // URL param override: ?saved=1 always wins
        if (new URLSearchParams(window.location.search).get("saved") === "1") {
          state.savedOnly = true;
        }

        syncButtonStates();
        updateFilterSummary();
        initControls();
        loadSources();
        loadEvents();
      });
  });
})();

(function () {
  // Default: show events within 60 min (includes events with unknown distance).
  var state = {
    filter: "",
    maxDrive: 60,
    sort: "soonest",
    savedOnly: false,
    loading: false,
    cacheStale: false,
  };

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

  // Returns "24 min · 18.1 mi", or null if data is missing/zero.
  function driveLabel(miles, mins) {
    if (miles == null || mins == null) return null;
    if (Math.round(mins) === 0) return null; // suppress 0-min drives (fallback coords)
    return Math.round(mins) + " min · " + parseFloat(miles).toFixed(1) + " mi";
  }

  function directionsUrl(ev) {
    if (ev.latitude != null && ev.longitude != null) {
      var lat = parseFloat(ev.latitude);
      var lng = parseFloat(ev.longitude);
      // Skip directions if coords are essentially at the Pittsburgh city-center fallback.
      if (Math.abs(lat - 40.4406) < 0.001 && Math.abs(lng + 79.9959) < 0.001) {
        // Fall through to address-based directions instead
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
      positively_pgh: "#7a3a42",
      visit_pittsburgh: "#1a5c8a",
    };
    return colors[sourceKey] || "#5d3a6b";
  }

  // Source attribution homepages — keyed by source_key.
  var SOURCE_HOMEPAGES = {
    positively_pgh:   "https://positivelypittsburgh.com/calendar/",
    visit_pittsburgh: "https://www.visitpittsburgh.com/",
  };

  function sourceHomeUrl(sourceKey) {
    return SOURCE_HOMEPAGES[sourceKey] || null;
  }

  // Returns true if the description is a useless auto-generated snippet.
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
      .replace(/\b202\d\b/g, "")          // strip year
      .replace(/[-–—]/g, " ")             // dashes → space
      .replace(/[^a-z0-9 ]/g, " ")        // strip punctuation
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeVenue(v) {
    return (v || "")
      .toLowerCase()
      .replace(/^(the|a|an)\s+/, "")      // strip leading article
      .replace(/[^a-z0-9 ]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  // True when venue names are the same or one is a clear prefix of the other.
  function venueMatch(a, b) {
    var na = normalizeVenue(a);
    var nb = normalizeVenue(b);
    if (na.length < 6 || nb.length < 6) return false;
    var shorter = na.length <= nb.length ? na : nb;
    var longer  = na.length <= nb.length ? nb : na;
    return longer.startsWith(shorter);
  }

  // At least one strong location/source signal must match before we call two
  // events with the same title+date duplicates. This keeps legitimately separate
  // festival sub-events (different stages/venues) visible.
  // Note: lat/lon is intentionally excluded — venues in dense areas like Millvale
  // can be <100 m apart while still being distinct events.
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
    var seen = {};        // key → array of result indices sharing this title+date
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
        // Only suppress if a location/source signal confirms it's the same event.
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

  // ── Card rendering ────────────────────────────────────────────────────────────

  function renderCard(ev) {
    var dateStr  = ev.date_label || formatDate(ev.start_datetime) || "See website";
    var timeStr  = ev.start_datetime ? formatTime(ev.start_datetime) : null;
    var drive    = driveLabel(ev.distance_miles, ev.estimated_drive_minutes);
    var dirUrl   = directionsUrl(ev);
    var srcColor = sourceColor(ev.source_key);
    var srcLabel = ev.display_name || ev.source_key;
    var saved    = ev.saved ? " ev-card-saved" : "";

    var html = '<div class="ev-card' + saved + '" data-id="' + ev.id + '">';

    // ── Header: source chip + date ──
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

    // ── Body ──
    html += '<div class="ev-card-body">';

    // Title
    html += '<div class="ev-title">' + esc(ev.title) + '</div>';

    // Meta row: category + drive pill
    var hasMeta = (ev.category && ev.category !== "featured" && ev.category !== "event") || drive;
    if (hasMeta) {
      html += '<div class="ev-meta-row">';
      if (ev.category && ev.category !== "featured" && ev.category !== "event") {
        html += '<span class="ev-category-tag">' + esc(ev.category) + '</span>';
      }
      if (drive) {
        html += '<span class="ev-drive-pill">' + esc(drive) + '</span>';
      }
      html += '</div>';
    }

    // Address block: venue / street / city+state+zip
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

    // Admission
    if (ev.admission) {
      html += '<div class="ev-admission">' + esc(ev.admission) + '</div>';
    }

    // Description — only if non-generic
    if (!isGenericDesc(ev.description_short)) {
      html += '<div class="ev-desc">' + esc(ev.description_short) + '</div>';
    }

    html += '</div>'; // .ev-card-body

    // ── Actions ──
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

    html += '</div>'; // .ev-card
    return html;
  }

  // ── Render list ───────────────────────────────────────────────────────────────

  function renderEvents(events) {
    var listEl = document.getElementById("events-list");
    if (!events || !events.length) {
      listEl.innerHTML = '<div class="ev-empty">No events found. Try "All" to see everything, or <button class="ev-refresh-link" id="manual-refresh-btn">refresh sources</button>.</div>';
      document.getElementById("manual-refresh-btn").addEventListener("click", function () {
        manualRefresh();
      });
      return;
    }

    var deduped = dedupeDisplay(events);

    var html = "";
    var lastDate = null;
    for (var i = 0; i < deduped.length; i++) {
      var ev = deduped[i];
      var dateKey = ev.start_datetime ? ev.start_datetime.substring(0, 10) : "undated";
      if (dateKey !== lastDate) {
        var label;
        if (dateKey === "undated") {
          label = "See Website for Dates";
        } else {
          try {
            var d = new Date(dateKey + "T12:00:00Z");
            var todayStr = new Date().toISOString().substring(0, 10);
            var tomorrowDate = new Date();
            tomorrowDate.setUTCDate(tomorrowDate.getUTCDate() + 1);
            var tomorrowStr = tomorrowDate.toISOString().substring(0, 10);
            if (dateKey === todayStr) {
              label = "Today";
            } else if (dateKey === tomorrowStr) {
              label = "Tomorrow";
            } else {
              var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
              var days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
              label = days[d.getUTCDay()] + ", " + months[d.getUTCMonth()] + " " + d.getUTCDate();
            }
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
    if (state.filter === "this_weekend") {
      params.set("filter", "this_weekend");
    }
    if (state.savedOnly) {
      params.set("saved", "1");
    }
    if (state.maxDrive != null) {
      params.set("max_drive", state.maxDrive);
    }
    params.set("sort", state.sort);
    params.set("limit", "200"); // fetch enough to dedup well

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
          renderEvents([]);
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
          renderEvents(data.events || []);
        }
      })
      .catch(function (err) {
        state.loading = false;
        showStatus("Could not load events. Check your connection.", "error");
        console.error("events load error", err);
      });
  }

  // ── Manual refresh (admin action) ────────────────────────────────────────────

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

  // ── Filter / sort controls ────────────────────────────────────────────────────

  function initControls() {
    document.querySelectorAll(".ev-filter-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".ev-filter-btn").forEach(function (b) {
          b.classList.remove("ev-filter-active");
        });
        btn.classList.add("ev-filter-active");

        var f = btn.dataset.filter;
        state.savedOnly = f === "saved";
        state.filter    = (f === "saved" || f === "drive30" || f === "drive60") ? "" : f;
        state.maxDrive  = btn.dataset.maxDrive ? parseInt(btn.dataset.maxDrive) : null;
        loadEvents();
      });
    });

    document.querySelectorAll(".ev-sort-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".ev-sort-btn").forEach(function (b) {
          b.classList.remove("ev-sort-active");
        });
        btn.classList.add("ev-sort-active");
        state.sort = btn.dataset.sort;
        loadEvents();
      });
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    initControls();
    loadEvents();
  });
})();

/**
 * Main entry point for Mollie's Guide.
 * Wires up the map, filters, and detail panel.
 */

(function() {
  var detailPanel, detailContent, resultCount;

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function monthName(n) {
    var names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return names[n] || "";
  }

  function formatNoteDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var now = new Date();
    var diffMs = now - d;
    var diffDays = Math.floor(diffMs / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return diffDays + " days ago";
    if (diffDays < 30) return Math.floor(diffDays / 7) + " weeks ago";
    if (diffDays < 365) {
      var months = Math.floor(diffDays / 30);
      return months === 1 ? "1 month ago" : months + " months ago";
    }
    var years = Math.floor(diffDays / 365);
    var label = years === 1 ? "1 year ago" : years + " years ago";
    return label + " (" + d.toLocaleDateString() + ")";
  }

  function seasonLabel(start, end) {
    if (!start && !end) return "";
    if (start === end) return monthName(start);
    return monthName(start) + "-" + monthName(end);
  }

  function renderDetail(loc) {
    var html = "";
    html += '<h2>' + escapeHtml(loc.name) + '</h2>';
    html += '<div class="meta">' + escapeHtml(loc.category || "") + ' &middot; ' + escapeHtml(loc.county || "") + ' County</div>';

    var flags = [];
    if (loc.organic) flags.push('<span class="flag flag-organic">Organic</span>');
    if (loc.pesticide_free) flags.push('<span class="flag flag-pesticide-free">Pesticide-free</span>');
    if (loc.low_chemical) flags.push('<span class="flag flag-low-chemical">Low-chemical</span>');
    if (flags.length) {
      html += '<div class="flag-list">' + flags.join("") + '</div>';
    }

    if (loc.address) {
      var addr = loc.address + ", " + (loc.city || "") + ", " + (loc.state || "") + " " + (loc.zip || "");
      var mapsUrl = "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(addr);
      html += '<div class="section">';
      html += '<div class="section-label">Address</div>';
      html += '<a href="' + mapsUrl + '" target="_blank" rel="noopener">' + escapeHtml(addr) + '</a>';
      html += '</div>';
    }

    if (loc.phone) {
      html += '<div class="section">';
      html += '<div class="section-label">Phone</div>';
      html += '<a href="tel:' + escapeHtml(loc.phone) + '">' + escapeHtml(loc.phone) + '</a>';
      html += '</div>';
    }

    if (loc.hours) {
      html += '<div class="section">';
      html += '<div class="section-label">Hours</div>';
      html += '<div>' + escapeHtml(loc.hours) + '</div>';
      html += '</div>';
    }

    if (loc.website) {
      html += '<div class="section">';
      html += '<div class="section-label">Website</div>';
      html += '<a href="' + escapeHtml(loc.website) + '" target="_blank" rel="noopener">' + escapeHtml(loc.website) + '</a>';
      html += '</div>';
    }

    if (loc.facebook_url) {
      html += '<div class="section">';
      html += '<div class="section-label">Facebook</div>';
      html += '<a href="' + escapeHtml(loc.facebook_url) + '" target="_blank" rel="noopener">View on Facebook</a>';
      html += '</div>';
    }

    if (loc.crops && loc.crops.length) {
      html += '<div class="section">';
      html += '<div class="section-label">Crops</div>';
      html += '<div class="crop-list">';
      loc.crops.forEach(function(c) {
        var cls = c.is_pyo ? "crop-tag pyo" : "crop-tag";
        var label = c.name;
        var season = seasonLabel(c.season_start_month, c.season_end_month);
        if (season) label += " (" + season + ")";
        html += '<span class="' + cls + '">' + escapeHtml(label) + '</span>';
      });
      html += '</div>';
      html += '</div>';
    }

    if (loc.payment_methods && loc.payment_methods.length) {
      html += '<div class="section">';
      html += '<div class="section-label">Payment</div>';
      html += '<div>' + escapeHtml(loc.payment_methods.join(", ")) + '</div>';
      html += '</div>';
    }

    if (loc.notes) {
      html += '<div class="section">';
      html += '<div class="section-label">About / Details</div>';
      html += '<div style="white-space: pre-wrap; font-size: 14px; line-height: 1.5;">' + escapeHtml(loc.notes) + '</div>';
      html += '</div>';
    }

    html += '<div class="notes-section">';
    html += '<div class="section-label">My Notes</div>';
    html += '<div class="notes-list" id="notes-list-' + loc.id + '">Loading...</div>';
    html += '<div class="note-input-wrap">';
    html += '<textarea id="note-input-' + loc.id + '" placeholder="Add a note about this farm..."></textarea>';
    html += '<button class="add-btn" id="note-add-' + loc.id + '">Add note</button>';
    html += '</div>';
    html += '</div>';

    detailContent.innerHTML = html;
    detailPanel.classList.add("open");

    loadNotes(loc.id);

    document.getElementById("note-add-" + loc.id).addEventListener("click", function() {
      var ta = document.getElementById("note-input-" + loc.id);
      var text = ta.value.trim();
      if (!text) return;
      this.disabled = true;
      MolliesAPI.addNote(loc.id, text).then(function() {
        ta.value = "";
        loadNotes(loc.id);
      }).catch(function(err) {
        console.error("Failed to add note:", err);
        alert("Could not save note - try again");
      }).finally(function() {
        document.getElementById("note-add-" + loc.id).disabled = false;
      });
    });
  }

  function loadNotes(locId) {
    var listEl = document.getElementById("notes-list-" + locId);
    if (!listEl) return;
    MolliesAPI.getNotes(locId).then(function(notes) {
      if (!notes.length) {
        listEl.innerHTML = '<div class="note-empty">No notes yet.</div>';
        return;
      }
      var html = "";
      notes.forEach(function(n) {
        html += '<div class="note-card" data-note-id="' + n.id + '">';
        html += '<button class="note-delete" data-note-id="' + n.id + '" aria-label="Delete">&times;</button>';
        html += '<div class="note-text">' + escapeHtml(n.note) + '</div>';
        html += '<div class="note-date">' + escapeHtml(formatNoteDate(n.created_at)) + '</div>';
        html += '</div>';
      });
      listEl.innerHTML = html;

      var deleteBtns = listEl.querySelectorAll(".note-delete");
      deleteBtns.forEach(function(btn) {
        btn.addEventListener("click", function() {
          var noteId = parseInt(this.dataset.noteId);
          if (!confirm("Delete this note?")) return;
          MolliesAPI.deleteNote(noteId).then(function() {
            loadNotes(locId);
          }).catch(function(err) {
            console.error("Delete failed:", err);
            alert("Could not delete note");
          });
        });
      });
    }).catch(function(err) {
      console.error("Failed to load notes:", err);
      listEl.innerHTML = '<div class="note-empty">Could not load notes.</div>';
    });
  }

  function closeDetail() {
    detailPanel.classList.remove("open");
  }

  function loadLocations(filters) {
    MolliesAPI.getLocations(filters).then(function(locations) {
      MolliesMap.renderLocations(locations);
      resultCount.textContent = locations.length + " farm" + (locations.length === 1 ? "" : "s");
    }).catch(function(err) {
      console.error("Failed to load locations:", err);
      resultCount.textContent = "(error loading)";
    });
  }

  document.addEventListener("DOMContentLoaded", function() {
    detailPanel = document.getElementById("detail-panel");
    detailContent = document.getElementById("detail-content");
    resultCount = document.getElementById("result-count");

    document.getElementById("detail-close").addEventListener("click", closeDetail);

    MolliesMap.init("map");

    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        function(pos) {
          MolliesMap.showUserLocation(pos.coords.latitude, pos.coords.longitude);
        },
        function(err) {
          console.log("Geolocation unavailable:", err.message);
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
      );
    }

    MolliesMap.setOnMarkerClick(function(loc) {
      MolliesAPI.getLocation(loc.id).then(renderDetail).catch(function(err) {
        console.error(err);
      });
    });

    MolliesFilters.init({
      categories: document.getElementById("category-chips"),
      crop: document.getElementById("crop-select"),
      month: document.getElementById("month-select"),
      pyo: document.getElementById("pyo-toggle"),
      organic: document.getElementById("organic-toggle")
    }, {
      onChange: loadLocations,
      onReady: function() { loadLocations({}); }
    });
  });
})();

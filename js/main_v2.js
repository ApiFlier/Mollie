(function() {
  var detailPanel, detailContent, resultCount;
  function escapeHtml(s) { return s ? String(s).replace(/&/g, "&").replace(/</g, "<").replace(/>/g, ">") : ""; }

  function renderDetail(loc) {
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

    if (loc.address) {
      var addr = loc.address + ", " + (loc.city || "") + ", " + (loc.state || "") + " " + (loc.zip || "");
      html += '<div class="section"><div class="section-label">Address</div>';
      html += '<a href="https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(addr) + '" target="_blank">' + escapeHtml(addr) + '</a></div>';
    }

    if (loc.hours && loc.hours !== loc.event_date) {
      html += '<div class="section"><div class="section-label">Hours</div><div>' + escapeHtml(loc.hours) + '</div></div>';
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
    detailPanel.classList.add("open");
    loadNotes(loc.id);

    document.getElementById("add-note-btn-" + loc.id).onclick = function() {
      var ta = document.getElementById("note-input-" + loc.id);
      var txt = ta.value.trim();
      if(!txt) return;
      MolliesAPI.addNote(loc.id, txt).then(function() {
        ta.value = "";
        loadNotes(loc.id);
      });
    };
  }

  // New delete function that talks to our new Python route
  window.deleteNote = function(locId, noteId) {
    if (!confirm("Are you sure you want to delete this note?")) return;
    fetch('/api/locations/' + locId + '/notes/' + noteId, { method: 'DELETE' })
      .then(function() { loadNotes(locId); })
      .catch(function(err) { console.error(err); alert("Failed to delete note."); });
  };

  // Updated loadNotes to display timestamp and delete button
  window.loadNotes = function(id) {
    var el = document.getElementById("notes-list-" + id);
    MolliesAPI.getNotes(id).then(function(notes) {
      if (!notes.length) {
        el.innerHTML = '<div style="color:#999; font-size:12px;">No personal notes yet.</div>';
        return;
      }
      var html = "";
      notes.forEach(function(n) {
        // Parse the SQL timestamp into a friendly local date/time
        var d = new Date(n.created_at);
        var dateStr = !isNaN(d.getTime()) ? d.toLocaleDateString() + ' at ' + d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'Unknown Date';
        
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

  document.addEventListener("DOMContentLoaded", function() {
    detailPanel = document.getElementById("detail-panel");
    detailContent = document.getElementById("detail-content");
    resultCount = document.getElementById("result-count");
    document.getElementById("detail-close").onclick = function() { detailPanel.classList.remove("open"); };
    
    MolliesMap.init("map");
    MolliesMap.setOnMarkerClick(function(loc) { 
      MolliesAPI.getLocation(loc.id).then(renderDetail); 
    });

    MolliesFilters.init({
      categories: document.getElementById("category-chips"),
      crop: document.getElementById("crop-select"),
      month: document.getElementById("month-select"),
      pyo: document.getElementById("pyo-toggle"),
      organic: document.getElementById("organic-toggle")
    }, {
      onChange: function(f) {
        MolliesAPI.getLocations(f).then(function(ls) {
          MolliesMap.renderLocations(ls);
          if(resultCount) resultCount.textContent = ls.length + " item" + (ls.length === 1 ? "" : "s");
        });
      },
      onReady: function() { MolliesAPI.getLocations({}).then(MolliesMap.renderLocations); }
    });
  });
})();

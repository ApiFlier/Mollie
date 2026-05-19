/**
 * Event Map - Admin JavaScript
 */

const AdminAPI = (() => {
  const BASE = "/api";

  async function request(path, options) {
    options = options || {};
    options.credentials = "include";
    const r = await fetch(BASE + path, options);
    if (!r.ok) {
      let detail = "";
      try {
        const body = await r.json();
        detail = body.error || JSON.stringify(body);
      } catch (e) { /* ignore */ }
      throw new Error(`HTTP ${r.status}: ${detail || r.statusText}`);
    }
    if (r.status === 204) return null;
    return await r.json();
  }

  function jsonRequest(path, method, body) {
    return request(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body == null ? undefined : JSON.stringify(body)
    });
  }

  return {
    listLocations: () => request("/locations"),
    getLocation: (id) => request("/locations/" + id),
    createLocation: (data) => jsonRequest("/locations", "POST", data),
    updateLocation: (id, data) => jsonRequest("/locations/" + id, "PUT", data),
    deleteLocation: (id) => jsonRequest("/locations/" + id, "DELETE"),
    listCategories: () => request("/categories"),
    listCounties: () => request("/counties"),
    listDistinctCrops: () => request("/crops/distinct"),
    addCrop: (locId, data) => jsonRequest("/locations/" + locId + "/crops", "POST", data),
    updateCrop: (cropId, data) => jsonRequest("/crops/" + cropId, "PUT", data),
    deleteCrop: (cropId) => jsonRequest("/crops/" + cropId, "DELETE"),
    getCredentials: () => request("/credentials"),
    updateCredentials: (data) => jsonRequest("/credentials", "PUT", data),
    getAdminSources: () => request("/admin/sources"),
    updateSource: (key, data) => jsonRequest("/admin/sources/" + key, "PUT", data)
  };
})();

// Shared helpers
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showFlash(type, msg, timeout) {
  var el = document.getElementById("flash");
  if (!el) return;
  el.innerHTML = '<div class="flash flash-' + type + '">' + escapeHtml(msg) + '</div>';
  if (timeout) {
    setTimeout(function() { el.innerHTML = ""; }, timeout);
  }
}

function getQueryParam(name) {
  var params = new URLSearchParams(window.location.search);
  return params.get(name);
}

// ---------- LIST PAGE ----------
const AdminList = (() => {
  var allLocations = [];
  var contentEl, searchEl, categoryFilterEl;

  function init() {
    AdminAuth.check().then(function(ok) {
      if (!ok) return;
      _initInner();
    });
  }

  function _initInner() {
    contentEl = document.getElementById("content");
    searchEl = document.getElementById("search-input");
    categoryFilterEl = document.getElementById("category-filter");

    searchEl.addEventListener("input", render);
    categoryFilterEl.addEventListener("change", render);

    Promise.all([
      AdminAPI.listLocations(),
      AdminAPI.listCategories()
    ]).then(function(results) {
      allLocations = results[0];
      var categories = results[1];

      categories.forEach(function(c) {
        var opt = document.createElement("option");
        opt.value = c.name;
        opt.textContent = c.name.replace(/-/g, " ");
        categoryFilterEl.appendChild(opt);
      });

      render();
    }).catch(function(err) {
      console.error(err);
      contentEl.innerHTML = '<div class="empty-state">Could not load locations: ' + escapeHtml(err.message) + '</div>';
    });
  }

  function render() {
    var search = (searchEl.value || "").toLowerCase().trim();
    var catFilter = categoryFilterEl.value;

    var filtered = allLocations.filter(function(loc) {
      if (catFilter && loc.category !== catFilter) return false;
      if (!search) return true;
      var hay = ((loc.name || "") + " " + (loc.city || "") + " " + (loc.county || "")).toLowerCase();
      return hay.indexOf(search) !== -1;
    });

    if (!filtered.length) {
      contentEl.innerHTML = '<div class="empty-state">No locations match.</div>';
      return;
    }

    var html = '<div style="overflow-x: auto;"><table class="locations-table"><thead><tr>';
    html += '<th>Name</th><th>Category</th><th>County/Region</th><th>City</th><th>Crops</th><th></th>';
    html += '</tr></thead><tbody>';
    filtered.forEach(function(loc) {
      html += '<tr>';
      html += '<td><strong>' + escapeHtml(loc.name) + '</strong></td>';
      html += '<td><span class="badge">' + escapeHtml(loc.category || "") + '</span></td>';
      html += '<td>' + escapeHtml(loc.county || "") + '</td>';
      html += '<td>' + escapeHtml(loc.city || "") + '</td>';
      html += '<td>' + (loc.crops ? loc.crops.length : 0) + '</td>';
      html += '<td><div class="row-actions">';
      html += '<a href="/admin/edit.html?id=' + loc.id + '&return=map" class="btn btn-secondary btn-small">Edit</a>';
      html += '</div></td>';
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    html += '<p style="margin-top:10px;color:var(--ink-soft);font-size:12px;">' + filtered.length + ' of ' + allLocations.length + ' locations</p>';
    contentEl.innerHTML = html;
  }

  return { init: init };
})();

// ---------- EDIT PAGE ----------
const AdminEdit = (() => {
  var locationId = null;  // null when creating, integer when editing
  var existingCrops = [];  // crops loaded from server (have .id)
  var newCropCounter = 0;  // for tagging unsaved crop rows

  var form, pageTitle, deleteBtn, cropRowsEl, categoryDropdown;

  function init() {
    AdminAuth.check().then(function(ok) {
      if (!ok) return;
      _initInner();
    });
  }

  function _initInner() {
    form = document.getElementById("edit-form");
    pageTitle = document.getElementById("page-title");
    deleteBtn = document.getElementById("delete-btn");
    cropRowsEl = document.getElementById("crop-rows");
    categoryDropdown = document.getElementById("f-category");

    var idStr = getQueryParam("id");
    if (idStr) {
      locationId = parseInt(idStr);
      pageTitle.textContent = "Edit Location";
      deleteBtn.style.display = "";
    } else {
      pageTitle.textContent = "Add New Location";
    }

    // Update Back / Cancel links to return to the originating admin tab
    var returnDest = getQueryParam("return") || "events";
    var validReturn = { events: true, map: true, maintenance: true };
    if (!validReturn[returnDest]) returnDest = "events";
    var returnUrl = "/admin/#" + returnDest;
    document.querySelectorAll('a.btn[href="/admin/"]').forEach(function(a) {
      a.href = returnUrl;
    });

    document.getElementById("add-crop-btn").addEventListener("click", function() {
      addCropRow();
    });

    categoryDropdown.addEventListener("change", toggleCategoryFields);
    deleteBtn.addEventListener("click", handleDelete);
    form.addEventListener("submit", handleSubmit);

    Promise.all([
      AdminAPI.listCategories(),
      AdminAPI.listCounties(),
      AdminAPI.listDistinctCrops()
    ]).then(function(results) {
      populateCategoryDropdown(results[0]);
      populateCountiesList(results[1]);
      populateCropNamesList(results[2]);

      if (locationId) {
        return AdminAPI.getLocation(locationId).then(populateForm);
      } else {
        addCropRow();
        toggleCategoryFields();
      }
    }).catch(function(err) {
      console.error(err);
      showFlash("error", "Could not load form data: " + err.message);
    });
  }

  function toggleCategoryFields() {
    var cat = categoryDropdown.value;
    var secSchedule = document.getElementById("section-schedule");
    var secCrops = document.getElementById("section-crops");
    var secHours = document.getElementById("section-hours");

    // Hide all dynamic sections initially
    if (secSchedule) secSchedule.style.display = "none";
    if (secCrops) secCrops.style.display = "none";
    if (secHours) secHours.style.display = "none";

    // Show sections based on category
    if (cat === "fair" || cat === "festival" || cat === "farmers-market" || cat === "other" || cat === "butcher" || cat === "hiking-trails") {
      if (secSchedule) secSchedule.style.display = "block";
    }
    if (cat === "farm") {
      if (secCrops) secCrops.style.display = "block";
      if (secHours) secHours.style.display = "block";
    }
    if (cat === "farmers-market" || cat === "butcher") {
      if (secHours) secHours.style.display = "block";
    }
  }

  function populateCategoryDropdown(categories) {
    categoryDropdown.innerHTML = "";
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "(no category)";
    categoryDropdown.appendChild(blank);
    categories.forEach(function(c) {
      var opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name.replace(/-/g, " ");
      categoryDropdown.appendChild(opt);
    });
  }

  function populateCountiesList(counties) {
    var dl = document.getElementById("counties-list");
    dl.innerHTML = "";
    if (!counties) return;
    counties.forEach(function(name) {
      var opt = document.createElement("option");
      opt.value = name;
      dl.appendChild(opt);
    });
  }

  function populateCropNamesList(crops) {
    var dl = document.getElementById("crop-names-list");
    if (!dl || !crops) return;
    dl.innerHTML = "";
    crops.forEach(function(c) {
      var opt = document.createElement("option");
      opt.value = c.name;
      dl.appendChild(opt);
    });
  }

  function populateForm(loc) {
    document.getElementById("f-name").value = loc.name || "";
    document.getElementById("f-category").value = loc.category || "";
    document.getElementById("f-county").value = loc.county || "";
    document.getElementById("f-address").value = loc.address || "";
    document.getElementById("f-city").value = loc.city || "";
    document.getElementById("f-state").value = loc.state || "PA";
    document.getElementById("f-zip").value = loc.zip || "";
    document.getElementById("f-lat").value = loc.lat == null ? "" : loc.lat;
    document.getElementById("f-lng").value = loc.lng == null ? "" : loc.lng;
    document.getElementById("f-phone").value = loc.phone || "";
    document.getElementById("f-alt-phone").value = loc.alt_phone || "";
    document.getElementById("f-email").value = loc.email || "";
    document.getElementById("f-website").value = loc.website || "";
    document.getElementById("f-facebook").value = loc.facebook_url || "";
    
    var hoursEl = document.getElementById("f-hours");
    if(hoursEl) hoursEl.value = loc.hours || "";
    
    var eventDateEl = document.getElementById("f-event_date");
    if(eventDateEl) eventDateEl.value = loc.event_date || "";
    
    var startMonthEl = document.getElementById("f-season_start_month");
    if(startMonthEl) startMonthEl.value = loc.season_start_month || "";
    
    var endMonthEl = document.getElementById("f-season_end_month");
    if(endMonthEl) endMonthEl.value = loc.season_end_month || "";
    
    document.getElementById("f-organic").checked = !!loc.organic;
    document.getElementById("f-pesticide-free").checked = !!loc.pesticide_free;
    document.getElementById("f-low-chemical").checked = !!loc.low_chemical;
    document.getElementById("f-notes").value = loc.notes || "";

    setCheckboxGroup("payment-methods-group", loc.payment_methods || []);
    setCheckboxGroup("amenities-group", loc.amenities || []);

    existingCrops = (loc.crops || []).slice();
    cropRowsEl.innerHTML = "";
    existingCrops.forEach(function(c) { addCropRow(c); });
    if (existingCrops.length === 0) addCropRow();

    // Now that the data is loaded, set the correct UI sections
    toggleCategoryFields();
  }

  function setCheckboxGroup(groupId, values) {
    var group = document.getElementById(groupId);
    var boxes = group.querySelectorAll('input[type="checkbox"]');
    var valueSet = {};
    if (Array.isArray(values)) {
      values.forEach(function(v) { valueSet[v] = true; });
    }
    boxes.forEach(function(b) {
      b.checked = !!valueSet[b.value];
    });
  }

  function readCheckboxGroup(groupId) {
    var group = document.getElementById(groupId);
    var boxes = group.querySelectorAll('input[type="checkbox"]:checked');
    var out = [];
    boxes.forEach(function(b) { out.push(b.value); });
    return out;
  }

  function addCropRow(crop) {
    crop = crop || {};
    var rowId = crop.id ? "existing-" + crop.id : "new-" + (++newCropCounter);

    var row = document.createElement("div");
    row.className = "crop-row";
    row.dataset.rowId = rowId;
    if (crop.id) row.dataset.cropId = crop.id;

    var monthOpts = '<option value="">--</option>';
    var monthNames = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    for (var i = 1; i <= 12; i++) {
      monthOpts += '<option value="' + i + '">' + monthNames[i] + '</option>';
    }

    row.innerHTML =
      '<div class="field field-name">' +
        '<label>Crop name</label>' +
        '<input type="text" class="crop-name" placeholder="e.g. blueberries" list="crop-names-list" autocomplete="off">' +
      '</div>' +
      '<div class="pyo-cell">' +
        '<input type="checkbox" class="crop-pyo" id="' + rowId + '-pyo">' +
        '<label for="' + rowId + '-pyo">PYO</label>' +
      '</div>' +
      '<div class="field">' +
        '<label>Start</label>' +
        '<select class="crop-start">' + monthOpts + '</select>' +
      '</div>' +
      '<div class="field">' +
        '<label>End</label>' +
        '<select class="crop-end">' + monthOpts + '</select>' +
      '</div>' +
      '<div class="delete-cell">' +
        '<button type="button" class="crop-remove" aria-label="Remove">&times;</button>' +
      '</div>';

    cropRowsEl.appendChild(row);

    row.querySelector(".crop-name").value = crop.name || "";
    row.querySelector(".crop-pyo").checked = crop.is_pyo == null ? true : !!crop.is_pyo;
    if (crop.season_start_month) row.querySelector(".crop-start").value = String(crop.season_start_month);
    if (crop.season_end_month) row.querySelector(".crop-end").value = String(crop.season_end_month);

    row.querySelector(".crop-remove").addEventListener("click", function() {
      row.remove();
    });
  }

  function normalizeCropName(name) {
    if (!name) return name;
    // trim, collapse repeated spaces, lowercase to match DB convention
    return name.trim().replace(/\s+/g, " ").toLowerCase();
  }

  function readCropRows() {
    var rows = cropRowsEl.querySelectorAll(".crop-row");
    var crops = [];
    rows.forEach(function(row) {
      var name = normalizeCropName(row.querySelector(".crop-name").value);
      if (!name) return;
      var crop = {
        name: name,
        is_pyo: row.querySelector(".crop-pyo").checked,
        season_start_month: row.querySelector(".crop-start").value || null,
        season_end_month: row.querySelector(".crop-end").value || null
      };
      if (row.dataset.cropId) {
        crop.id = parseInt(row.dataset.cropId);
      }
      if (crop.season_start_month) crop.season_start_month = parseInt(crop.season_start_month);
      if (crop.season_end_month) crop.season_end_month = parseInt(crop.season_end_month);
      crops.push(crop);
    });
    return crops;
  }

  function readForm() {
    var f = function(id) { 
        var el = document.getElementById(id);
        return el ? el.value.trim() : ""; 
    };
    var fc = function(id) { 
        var el = document.getElementById(id);
        return el ? el.checked : false; 
    };

    var lat = f("f-lat");
    var lng = f("f-lng");
    
    var startMonth = f("f-season_start_month");
    var endMonth = f("f-season_end_month");

    return {
      name: f("f-name"),
      category: f("f-category") || null,
      county: f("f-county") || null,
      address: f("f-address") || null,
      city: f("f-city") || null,
      state: f("f-state") || "PA",
      zip: f("f-zip") || null,
      lat: lat === "" ? null : parseFloat(lat),
      lng: lng === "" ? null : parseFloat(lng),
      phone: f("f-phone") || null,
      alt_phone: f("f-alt-phone") || null,
      email: f("f-email") || null,
      website: f("f-website") || null,
      facebook_url: f("f-facebook") || null,
      hours: f("f-hours") || null,
      event_date: f("f-event_date") || null,
      season_start_month: startMonth === "" ? null : parseInt(startMonth),
      season_end_month: endMonth === "" ? null : parseInt(endMonth),
      organic: fc("f-organic"),
      pesticide_free: fc("f-pesticide-free"),
      low_chemical: fc("f-low-chemical"),
      notes: f("f-notes") || "",
      payment_methods: readCheckboxGroup("payment-methods-group"),
      amenities: readCheckboxGroup("amenities-group")
    };
  }

  function handleSubmit(e) {
    e.preventDefault();
    var saveBtn = document.getElementById("save-btn");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    var data = readForm();
    if (!data.name) {
      showFlash("error", "Name is required");
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
      return;
    }

    var savePromise;
    if (locationId) {
      savePromise = AdminAPI.updateLocation(locationId, data).then(function() {
        return locationId;
      });
    } else {
      savePromise = AdminAPI.createLocation(data).then(function(res) {
        return res.id;
      });
    }

    savePromise.then(function(id) {
      return syncCrops(id).then(function() { return id; });
    }).then(function(id) {
      showFlash("success", "Saved successfully", 3000);
      window.scrollTo({ top: 0, behavior: "smooth" });
      if (!locationId) {
        window.location.href = "/admin/edit.html?id=" + id +
          (getQueryParam("return") ? "&return=" + encodeURIComponent(getQueryParam("return")) : "");
      } else {
        saveBtn.textContent = "Saved ✓";
        setTimeout(function() { saveBtn.textContent = "Save"; }, 2000);
        AdminAPI.getLocation(locationId).then(populateForm);
      }
    }).catch(function(err) {
      console.error(err);
      showFlash("error", "Save failed: " + err.message);
    }).finally(function() {
      saveBtn.disabled = false;
      if (saveBtn.textContent === "Saving...") saveBtn.textContent = "Save";
    });
  }

  function syncCrops(locId) {
    var current = readCropRows();
    var currentIds = current.filter(function(c) { return c.id; }).map(function(c) { return c.id; });
    var existingIds = existingCrops.map(function(c) { return c.id; });

    var toDelete = existingIds.filter(function(id) { return currentIds.indexOf(id) === -1; });

    var ops = [];
    toDelete.forEach(function(id) { ops.push(AdminAPI.deleteCrop(id)); });

    current.forEach(function(c) {
      if (c.id) {
        ops.push(AdminAPI.updateCrop(c.id, c));
      } else {
        ops.push(AdminAPI.addCrop(locId, c));
      }
    });

    return Promise.all(ops);
  }

  function handleDelete() {
    if (!locationId) return;
    if (!confirm("Delete this location and all its crops and notes? This can't be undone.")) return;
    deleteBtn.disabled = true;
    AdminAPI.deleteLocation(locationId).then(function() {
      window.location.href = "/admin/?deleted=1";
    }).catch(function(err) {
      showFlash("error", "Delete failed: " + err.message);
      deleteBtn.disabled = false;
    });
  }

  return { init: init };
})();

// ---------- LOGIN PAGE ----------
const AdminLogin = (() => {
  function init() {
    var form = document.getElementById("login-form");
    var btn = document.getElementById("login-btn");
    var flash = document.getElementById("flash");

    form.addEventListener("submit", function(e) {
      e.preventDefault();
      btn.disabled = true;
      btn.textContent = "Signing in...";
      flash.innerHTML = "";

      var username = document.getElementById("username").value.trim();
      var password = document.getElementById("password").value;

      fetch("/api/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username, password: password })
      }).then(function(r) {
        if (r.ok) {
          window.location.href = "/admin/";
          return;
        }
        return r.json().then(function(body) {
          throw new Error(body.error || "Login failed");
        });
      }).catch(function(err) {
        flash.innerHTML = '<div class="flash flash-error">' + escapeHtml(err.message) + '</div>';
      }).finally(function() {
        btn.disabled = false;
        btn.textContent = "Sign in";
      });
    });
  }
  return { init: init };
})();

// ---------- AUTH GUARD ----------
const AdminAuth = (() => {
  function check() {
    if (window.location.pathname.indexOf("/admin/login") !== -1) return Promise.resolve(true);
    return fetch("/api/auth-check", { credentials: "include" }).then(function(r) {
      if (!r.ok) {
        window.location.href = "/admin/login.html";
        return false;
      }
      return true;
    }).catch(function() {
      window.location.href = "/admin/login.html";
      return false;
    });
  }

  function logout() {
    fetch("/api/logout", { method: "POST", credentials: "include" }).finally(function() {
      window.location.href = "/admin/login.html";
    });
  }

  return { check: check, logout: logout };
})();

// ---------- CREDENTIALS MODAL ----------
const AdminCredsModal = (() => {
  var mode = null;
  var modal, form, titleEl, flashEl;

  function init() {
    modal = document.getElementById("creds-modal");
    if (!modal) return;
    form = document.getElementById("modal-form");
    titleEl = document.getElementById("modal-title");
    flashEl = document.getElementById("modal-flash");

    var btnUser = document.getElementById("btn-change-username");
    var btnPass = document.getElementById("btn-change-password");
    if (btnUser) btnUser.addEventListener("click", function() { open("username"); });
    if (btnPass) btnPass.addEventListener("click", function() { open("password"); });

    var closeBtn = document.getElementById("modal-close");
    var cancelBtn = document.getElementById("modal-cancel");
    if (closeBtn) closeBtn.addEventListener("click", close);
    if (cancelBtn) cancelBtn.addEventListener("click", close);

    modal.addEventListener("click", function(e) { if (e.target === modal) close(); });
    form.addEventListener("submit", handleSubmit);
  }

  function open(m) {
    mode = m;
    flashEl.innerHTML = "";
    form.reset();
    titleEl.textContent = m === "username" ? "Change Username" : "Change Password";

    document.getElementById("field-current-username").style.display = "none";
    document.getElementById("field-new-username").style.display = m === "username" ? "" : "none";
    document.getElementById("field-new-password").style.display = m === "password" ? "" : "none";
    document.getElementById("field-confirm-password").style.display = m === "password" ? "" : "none";

    modal.style.display = "";
  }

  function close() {
    if (modal) modal.style.display = "none";
    if (form) form.reset();
    if (flashEl) flashEl.innerHTML = "";
  }

  function handleSubmit(e) {
    e.preventDefault();
    flashEl.innerHTML = "";
    var currentPassword = document.getElementById("m-current-password").value;
    var payload = { current_password: currentPassword };

    if (mode === "username") {
      payload.new_username = document.getElementById("m-new-username").value.trim();
      if (!payload.new_username) {
        flashEl.innerHTML = '<div class="flash flash-error">New username is required.</div>';
        return;
      }
    } else {
      var newPw = document.getElementById("m-new-password").value;
      var confirmPw = document.getElementById("m-confirm-password").value;
      if (!newPw) {
        flashEl.innerHTML = '<div class="flash flash-error">New password is required.</div>';
        return;
      }
      if (newPw !== confirmPw) {
        flashEl.innerHTML = '<div class="flash flash-error">Passwords do not match.</div>';
        return;
      }
      payload.new_password = newPw;
    }

    var saveBtn = document.getElementById("modal-save");
    saveBtn.disabled = true;

    AdminAPI.updateCredentials(payload).then(function() {
      flashEl.innerHTML = '<div class="flash flash-success">Updated successfully.</div>';
      setTimeout(close, 2000);
    }).catch(function(err) {
      flashEl.innerHTML = '<div class="flash flash-error">' + escapeHtml(err.message) + '</div>';
    }).finally(function() {
      saveBtn.disabled = false;
    });
  }

  return { init: init, open: open, close: close };
})();

// ---------- TABS ----------
const AdminTabs = (() => {
  function init() {
    document.querySelectorAll(".admin-tab").forEach(function(btn) {
      btn.addEventListener("click", function() {
        switchTab(btn.getAttribute("data-tab"));
      });
    });
    // Default to Events; honour hash to restore the right tab.
    var hash = window.location.hash.replace(/^#/, "");
    var validTabs = { events: true, map: true, maintenance: true };
    switchTab(validTabs[hash] ? hash : "events");
  }

  function switchTab(name) {
    document.querySelectorAll(".admin-tab").forEach(function(b) {
      b.classList.toggle("admin-tab-active", b.getAttribute("data-tab") === name);
    });
    document.querySelectorAll(".admin-tab-panel").forEach(function(p) {
      p.style.display = (p.id === "tab-" + name) ? "" : "none";
    });
    history.replaceState(null, "", "#" + name);
    if (name === "events") {
      AdminEvents.load();
    }
  }

  return { init: init };
})();

// ---------- EVENTS ADMIN ----------
const AdminEvents = (() => {
  var _loaded = false;
  var _allEvents = [];
  var _sources = [];

  function load() {
    if (_loaded) return;
    _loaded = true;
    var el = document.getElementById("events-content");
    el.innerHTML = "Loading events…";

    fetch("/api/admin/events?include_hidden=1&limit=300", { credentials: "include" })
      .then(function(r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function(data) {
        _allEvents = data.events || [];
        _sources = data.sources || [];
        _render(_sources);
      })
      .catch(function(err) {
        document.getElementById("events-content").innerHTML =
          '<div class="empty-state">Could not load events: ' + escapeHtml(err.message) + "</div>";
      });
  }

  function _reload() {
    _loaded = false;
    load();
  }

  function _toggleSource(sourceKey, currentlyEnabled) {
    var newEnabled = !currentlyEnabled;
    AdminAPI.updateSource(sourceKey, { enabled: newEnabled })
      .then(function() { _reload(); })
      .catch(function(err) {
        alert("Could not update source: " + err.message);
      });
  }

  function _render(sources) {
    var el = document.getElementById("events-content");

    // Collapsible section state (default: collapsed)
    var _LS_KEY = "ev-sources-expanded";
    var isExpanded = localStorage.getItem(_LS_KEY) === "1";

    // Build summary for the section header
    var enabledCount = sources.filter(function(s) { return s.enabled !== false; }).length;
    var covValues = sources.map(function(s) { return (s.coverage_days != null) ? s.coverage_days : 60; });
    var uniqueCov = covValues.filter(function(v, i, a) { return a.indexOf(v) === i; }).sort(function(a,b){return a-b;});
    var covSummary = uniqueCov.length === 1 ? uniqueCov[0] + "-day coverage" : uniqueCov.join("/") + "-day coverage";
    var summary = enabledCount + " of " + sources.length + " enabled · " + covSummary;

    // Collapsible header
    var headerHtml =
      '<div class="ev-sources-header">' +
        '<div class="ev-sources-title">' +
          '<span class="ev-sources-label">Event Sources</span>' +
          '<span class="ev-sources-summary">' + escapeHtml(summary) + '</span>' +
        '</div>' +
        '<button class="btn btn-small ev-sources-toggle-btn" id="ev-sources-toggle" aria-expanded="' + isExpanded + '">' +
          (isExpanded ? '▲ Hide' : '▼ Show') +
        '</button>' +
      '</div>';

    // Stats + enable/disable cards
    var statsHtml = '<div class="ev-admin-stats" id="ev-admin-stats-panel"' + (isExpanded ? '' : ' style="display:none;"') + '>';
    sources.forEach(function(s) {
      var isEnabled = s.enabled !== false;
      var toggleLabel = isEnabled ? "Disable" : "Enable";
      var toggleStyle = isEnabled
        ? 'style="color:var(--danger);border-color:var(--danger);"'
        : 'style="color:var(--sage);border-color:var(--sage);"';
      statsHtml += '<div class="ev-admin-stat-card">';
      statsHtml += '<div class="ev-admin-stat-name">' + escapeHtml(s.display_name || s.source_key) + "</div>";
      if (!isEnabled) {
        statsHtml += '<div class="ev-admin-stat-hidden" style="font-weight:600;">DISABLED</div>';
      }
      statsHtml += '<div class="ev-admin-stat-num">' + s.total + " total</div>";
      if (s.hidden_count > 0) {
        statsHtml += '<div class="ev-admin-stat-hidden">' + s.hidden_count + " hidden</div>";
      }
      if (s.saved_count > 0) {
        statsHtml += '<div class="ev-admin-stat-saved">' + s.saved_count + " saved</div>";
      }
      statsHtml += '<button class="btn btn-small ev-source-toggle" ' + toggleStyle +
        ' data-key="' + escapeHtml(s.source_key) + '"' +
        ' data-enabled="' + (isEnabled ? "1" : "0") + '">' +
        toggleLabel + "</button>";
      var covDays = (s.coverage_days != null) ? s.coverage_days : 60;
      statsHtml += '<div class="ev-coverage-row">' +
        '<label class="ev-coverage-label">Fetch coverage days</label>' +
        '<input type="number" class="ev-coverage-input" min="7" max="180" value="' + covDays + '"' +
        ' data-key="' + escapeHtml(s.source_key) + '">' +
        '<button class="btn btn-small ev-coverage-save" data-key="' + escapeHtml(s.source_key) + '">Save</button>' +
        '</div>' +
        '<div class="ev-coverage-hint">How many future days this source should try to keep available. Used by sources that support paged future fetching.</div>';
      statsHtml += "</div>";
    });
    statsHtml += "</div>";

    // Filter controls
    var ctrlHtml = '<div class="ev-admin-controls">';
    ctrlHtml += '<select id="ev-source-filter"><option value="">All sources</option>';
    sources.forEach(function(s) {
      ctrlHtml += '<option value="' + escapeHtml(s.source_key) + '">' +
                  escapeHtml(s.display_name || s.source_key) + "</option>";
    });
    ctrlHtml += "</select>";
    ctrlHtml += '<select id="ev-hidden-filter">' +
      '<option value="visible">Visible only</option>' +
      '<option value="all">All</option>' +
      '<option value="hidden">Hidden only</option>' +
      "</select>";
    ctrlHtml += '<button class="btn btn-secondary btn-small" id="ev-admin-refresh">Refresh cache</button>';
    ctrlHtml += "</div>";

    el.innerHTML = headerHtml + statsHtml + ctrlHtml + '<div id="ev-table-container"></div>';

    // Wire collapse toggle
    document.getElementById("ev-sources-toggle").addEventListener("click", function() {
      var panel = document.getElementById("ev-admin-stats-panel");
      var btn   = document.getElementById("ev-sources-toggle");
      var nowExpanded = panel.style.display !== "none";
      if (nowExpanded) {
        panel.style.display = "none";
        btn.textContent = "▼ Show";
        btn.setAttribute("aria-expanded", "false");
        localStorage.setItem(_LS_KEY, "0");
      } else {
        panel.style.display = "";
        btn.textContent = "▲ Hide";
        btn.setAttribute("aria-expanded", "true");
        localStorage.setItem(_LS_KEY, "1");
      }
    });

    // Bind source toggle buttons
    el.querySelectorAll(".ev-source-toggle").forEach(function(btn) {
      btn.addEventListener("click", function() {
        var key = btn.getAttribute("data-key");
        var enabled = btn.getAttribute("data-enabled") === "1";
        btn.disabled = true;
        _toggleSource(key, enabled);
      });
    });

    // Bind coverage days save buttons
    el.querySelectorAll(".ev-coverage-save").forEach(function(btn) {
      btn.addEventListener("click", function() {
        var key = btn.getAttribute("data-key");
        var card = btn.closest(".ev-admin-stat-card");
        var input = card ? card.querySelector(".ev-coverage-input") : null;
        if (!input) return;
        var val = parseInt(input.value, 10);
        if (isNaN(val) || val < 7 || val > 180) {
          alert("Coverage days must be between 7 and 180.");
          return;
        }
        btn.disabled = true;
        btn.textContent = "Saving…";
        AdminAPI.updateSource(key, { coverage_days: val })
          .then(function() {
            btn.textContent = "Saved";
            setTimeout(function() { btn.textContent = "Save"; btn.disabled = false; }, 1500);
          })
          .catch(function(err) {
            alert("Could not save coverage days: " + err.message);
            btn.disabled = false;
            btn.textContent = "Save";
          });
      });
    });

    document.getElementById("ev-source-filter").addEventListener("change", _renderTable);
    document.getElementById("ev-hidden-filter").addEventListener("change", _renderTable);

    document.getElementById("ev-admin-refresh").addEventListener("click", function() {
      var btn = this;
      btn.disabled = true;
      btn.textContent = "Refreshing…";
      fetch("/api/events/refresh", { method: "POST", credentials: "include" })
        .then(function() { _reload(); })
        .catch(function() {
          btn.disabled = false;
          btn.textContent = "Refresh cache";
        });
    });

    _renderTable();
  }

  function _renderTable() {
    var srcFilter    = (document.getElementById("ev-source-filter")  || {}).value || "";
    var hiddenFilter = (document.getElementById("ev-hidden-filter")   || {}).value || "visible";

    var filtered = _allEvents.filter(function(ev) {
      if (srcFilter && ev.source_key !== srcFilter) return false;
      if (hiddenFilter === "visible" && ev.hidden)  return false;
      if (hiddenFilter === "hidden"  && !ev.hidden) return false;
      return true;
    });

    var container = document.getElementById("ev-table-container");
    if (!container) return;

    if (!filtered.length) {
      container.innerHTML = '<div class="empty-state">No events match.</div>';
      return;
    }

    var html = '<div style="overflow-x:auto"><table class="locations-table"><thead><tr>' +
      "<th>Title</th><th>Source</th><th>Date</th><th>Venue / City</th><th>Status</th><th></th>" +
      "</tr></thead><tbody>";

    filtered.forEach(function(ev) {
      var dateStr = ev.start_datetime ? ev.start_datetime.substring(0, 10) : "—";
      var venue   = escapeHtml(ev.venue_name || ev.city || "—");
      var title   = ev.source_url
        ? '<a href="' + escapeHtml(ev.source_url) + '" target="_blank" rel="noopener">' + escapeHtml(ev.title) + "</a>"
        : escapeHtml(ev.title);
      var statusParts = [];
      if (ev.hidden) statusParts.push('<span class="badge" style="color:var(--danger)">hidden</span>');
      if (ev.saved)  statusParts.push('<span class="badge" style="color:var(--sage)">saved</span>');
      var hideLabel = ev.hidden ? "Unhide" : "Hide";

      html += "<tr>" +
        "<td>" + title + "</td>" +
        '<td><span class="badge">' + escapeHtml(ev.display_name || ev.source_key) + "</span></td>" +
        "<td>" + escapeHtml(dateStr) + "</td>" +
        "<td>" + venue + "</td>" +
        "<td>" + (statusParts.join(" ") || "—") + "</td>" +
        '<td><div class="row-actions">' +
        '<button class="btn btn-secondary btn-small ev-hide-btn"' +
        ' data-id="' + ev.id + '" data-hidden="' + (ev.hidden ? "1" : "0") + '">' +
        hideLabel + "</button>" +
        "</div></td></tr>";
    });

    html += "</tbody></table></div>" +
      '<p style="margin-top:10px;color:var(--ink-soft);font-size:12px;">' +
      filtered.length + " of " + _allEvents.length + " events</p>";

    container.innerHTML = html;

    container.querySelectorAll(".ev-hide-btn").forEach(function(btn) {
      btn.addEventListener("click", function() {
        var id       = parseInt(btn.getAttribute("data-id"), 10);
        var isHidden = btn.getAttribute("data-hidden") === "1";
        btn.disabled = true;
        fetch("/api/events/" + id + "/hide", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hidden: !isHidden })
        })
          .then(function(r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
          .then(function() {
            var ev = _allEvents.find(function(e) { return e.id === id; });
            if (ev) ev.hidden = !isHidden;
            _renderTable();
          })
          .catch(function() { btn.disabled = false; });
      });
    });
  }

  return { load: load };
})();

// ── AdminMaintenance ──────────────────────────────────────────────────────────
var AdminMaintenance = (function() {
  function init() {
    var btn = document.getElementById("btn-seed-snapshot");
    var resultDiv = document.getElementById("seed-snapshot-result");
    if (!btn || !resultDiv) return;

    btn.addEventListener("click", function() {
      btn.disabled = true;
      btn.textContent = "Creating snapshot…";
      resultDiv.innerHTML = "";

      fetch("/api/admin/seed-snapshot", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" }
      })
        .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
        .then(function(res) {
          btn.disabled = false;
          btn.textContent = "Create Seed Snapshot";
          if (res.ok && res.data.ok) {
            var d = res.data;
            var counts = d.counts || {};
            var countParts = Object.keys(counts).map(function(t) {
              return counts[t] + " " + t;
            }).join(", ");
            resultDiv.innerHTML =
              '<div class="flash flash-success" style="margin-top:0.5rem;">' +
              "<strong>Seed snapshot created.</strong><br>" +
              "File: <code>" + d.seed_file + "</code><br>" +
              (d.backup_file ? "Backup: <code>" + d.backup_file + "</code><br>" : "") +
              "Rows: " + countParts + "<br>" +
              "<em style='color:#555;font-size:0.85em;'>" + d.note + "</em>" +
              "</div>";
          } else {
            resultDiv.innerHTML =
              '<div class="flash flash-error" style="margin-top:0.5rem;">' +
              "<strong>Snapshot failed:</strong> " + ((res.data && res.data.error) || "Unknown error") +
              "</div>";
          }
        })
        .catch(function(e) {
          btn.disabled = false;
          btn.textContent = "Create Seed Snapshot";
          resultDiv.innerHTML =
            '<div class="flash flash-error" style="margin-top:0.5rem;">' +
            "<strong>Request failed:</strong> " + e.message +
            "</div>";
        });
    });
  }

  return { init: init };
})();

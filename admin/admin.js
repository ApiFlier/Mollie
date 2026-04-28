/**
 * Mollie's Guide - Admin JavaScript
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
    addCrop: (locId, data) => jsonRequest("/locations/" + locId + "/crops", "POST", data),
    updateCrop: (cropId, data) => jsonRequest("/crops/" + cropId, "PUT", data),
    deleteCrop: (cropId) => jsonRequest("/crops/" + cropId, "DELETE"),
    getCredentials: () => request("/credentials"),
    updateCredentials: (data) => jsonRequest("/credentials", "PUT", data)
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
      html += '<a href="/admin/edit.html?id=' + loc.id + '" class="btn btn-secondary btn-small">Edit</a>';
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

    document.getElementById("add-crop-btn").addEventListener("click", function() {
      addCropRow();
    });

    categoryDropdown.addEventListener("change", toggleCategoryFields);
    deleteBtn.addEventListener("click", handleDelete);
    form.addEventListener("submit", handleSubmit);

    Promise.all([
      AdminAPI.listCategories(),
      AdminAPI.listCounties()
    ]).then(function(results) {
      populateCategoryDropdown(results[0]);
      populateCountiesList(results[1]);

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
    var secEvents = document.getElementById("section-events");
    var secCrops = document.getElementById("section-crops");
    var secHours = document.getElementById("section-hours");
    
    // Hide all dynamic sections initially
    if (secEvents) secEvents.style.display = "none";
    if (secCrops) secCrops.style.display = "none";
    if (secHours) secHours.style.display = "none";

    // Show sections based on category
    if (cat === "fair" || cat === "festival") {
      if (secEvents) secEvents.style.display = "block";
    } else if (cat === "farm" || cat === "pick-your-own") {
      if (secCrops) secCrops.style.display = "block";
      if (secHours) secHours.style.display = "block";
    } else if (cat === "farmers-market") {
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
        '<input type="text" class="crop-name" placeholder="e.g. blueberries">' +
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

  function readCropRows() {
    var rows = cropRowsEl.querySelectorAll(".crop-row");
    var crops = [];
    rows.forEach(function(row) {
      var name = row.querySelector(".crop-name").value.trim();
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
      showFlash("success", "Saved successfully", 2500);
      if (!locationId) {
        window.location.href = "/admin/edit.html?id=" + id;
      } else {
        AdminAPI.getLocation(locationId).then(populateForm);
      }
    }).catch(function(err) {
      console.error(err);
      showFlash("error", "Save failed: " + err.message);
    }).finally(function() {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
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

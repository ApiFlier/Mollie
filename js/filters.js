/**
 * Filter UI for Event Map.
 *
 * Categories are multi-select toggles. Farm-only controls (crop, PYO, organic)
 * are visible whenever the "farm" category is selected.
 */

const EventMapFilters = (() => {
  const state = {
    categories: new Set(), // empty = will be populated with all on first load
    crop: "",
    month: "",
    pyo_only: false,
    organic: false
  };

  let onChangeHandler = null;
  let categoriesEl, cropEl, monthEl, pyoEl, organicEl;
  let pyoLabel, organicLabel;
  let allCategoryNames = []; // populated once categories load

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function isLightColor(hex) {
    if (!hex || hex.length < 7) return false;
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 160;
  }

  function setChipActive(btn, active) {
    var color = btn.dataset.color || "#3d72c8";
    if (active) {
      btn.style.background = color;
      btn.style.borderColor = color;
      btn.style.color = isLightColor(color) ? "#333" : "#fff";
    } else {
      btn.style.background = "";
      btn.style.borderColor = color;
      btn.style.color = "";
    }
  }

  function setFarmControlsVisible(visible) {
    var d = visible ? "" : "none";
    if (cropEl)       cropEl.style.display       = d;
    if (pyoLabel)     pyoLabel.style.display     = d;
    if (organicLabel) organicLabel.style.display = d;
  }

  function updateFarmControls() {
    var farmSelected = state.categories.has("farm");
    setFarmControlsVisible(farmSelected);
    if (!farmSelected) {
      state.crop     = "";
      state.pyo_only = false;
      state.organic  = false;
      if (cropEl)    cropEl.value      = "";
      if (pyoEl)     pyoEl.checked     = false;
      if (organicEl) organicEl.checked = false;
    }
  }

  function emitChange() {
    if (!onChangeHandler) return;
    if (state.categories.size === 0) {
      onChangeHandler({ _empty: true });
      return;
    }
    var p = {};
    p.category = Array.from(state.categories).join(",");
    if (state.crop)     p.crop      = state.crop;
    if (state.month)    p.month     = state.month;
    if (state.pyo_only) p.pyo_only  = "true";
    if (state.organic)  p.organic   = "true";
    onChangeHandler(p);
  }

  // ── Category toggle ──────────────────────────────────────────────────────────

  function updateAllChip() {
    var allChip = document.getElementById("chip-all-btn");
    if (!allChip) return;
    var allActive = allCategoryNames.length > 0 &&
                    state.categories.size === allCategoryNames.length;
    allChip.style.background   = allActive ? "var(--berry)" : "";
    allChip.style.borderColor  = allActive ? "var(--berry)" : "";
    allChip.style.color        = allActive ? "#fff" : "";
    allChip.style.fontWeight   = allActive ? "600" : "";
  }

  function toggleCategory(value) {
    if (state.categories.has(value)) {
      state.categories.delete(value);
    } else {
      state.categories.add(value);
    }

    categoriesEl.querySelectorAll(".chip:not(.chip-all)").forEach(function(c) {
      setChipActive(c, state.categories.has(c.dataset.value));
    });
    updateAllChip();

    updateFarmControls();
    emitChange();
  }

  // ── Build categories ─────────────────────────────────────────────────────────

  function buildCategoryChips(categories, defaultCategories) {
    allCategoryNames = categories.map(function(c) { return c.name; });

    // First load: apply defaultCategories setting
    if (state.categories.size === 0) {
      if (!defaultCategories || defaultCategories === "all") {
        // Default: select all
        allCategoryNames.forEach(function(n) { state.categories.add(n); });
      } else {
        // Future: comma-separated slug list
        var slugs = defaultCategories.split(",").map(function(s) { return s.trim(); });
        slugs.forEach(function(s) {
          if (allCategoryNames.indexOf(s) !== -1) state.categories.add(s);
        });
        // If no slugs matched (stale config), fall back to all
        if (state.categories.size === 0) {
          allCategoryNames.forEach(function(n) { state.categories.add(n); });
        }
      }
    }

    categoriesEl.innerHTML = "";

    // "All" reset chip at the start
    var allChip = document.createElement("button");
    allChip.className = "chip chip-all";
    allChip.id = "chip-all-btn";
    allChip.textContent = "All";
    allChip.title = "Show all categories";
    allChip.onclick = function() {
      allCategoryNames.forEach(function(n) { state.categories.add(n); });
      categoriesEl.querySelectorAll(".chip:not(.chip-all)").forEach(function(c) {
        setChipActive(c, true);
      });
      updateAllChip();
      updateFarmControls();
      emitChange();
    };
    categoriesEl.appendChild(allChip);

    categories.forEach(function(c) {
      var btn = document.createElement("button");
      btn.className = "chip";
      btn.textContent = c.name.charAt(0).toUpperCase() + c.name.slice(1).replace(/-/g, " ");
      btn.dataset.value = c.name;
      btn.dataset.color = c.color || "#3d72c8";
      setChipActive(btn, state.categories.has(c.name));
      btn.onclick = function() { toggleCategory(c.name); };
      categoriesEl.appendChild(btn);
    });

    updateAllChip();
  }

  // ── Filter summary ────────────────────────────────────────────────────────────

  function getSummary() {
    var total    = allCategoryNames.length;
    var selected = state.categories.size;
    var parts    = [];

    if (total === 0 || selected === total) {
      parts.push("All categories");
    } else if (selected === 0) {
      parts.push("No categories");
    } else if (selected <= 2) {
      var names = Array.from(state.categories).map(function(n) {
        return n.charAt(0).toUpperCase() + n.slice(1).replace(/-/g, " ");
      });
      parts.push(names.join(", "));
    } else {
      parts.push(selected + " of " + total + " types");
    }

    if (state.month) {
      var months = ["","Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"];
      parts.push(months[parseInt(state.month)] || "");
    }
    if (state.crop) parts.push(state.crop);

    return parts.join(" · ");
  }

  // ── Build month dropdown ─────────────────────────────────────────────────────

  function buildMonthDropdown() {
    var months = ["Any month","Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"];
    monthEl.innerHTML = months.map(function(m, i) {
      return '<option value="' + (i === 0 ? "" : i) + '">' + m + '</option>';
    }).join("");
    monthEl.onchange = function() {
      state.month = monthEl.value;
      emitChange();
    };
  }

  // ── Build crop dropdown ──────────────────────────────────────────────────────

  function buildCropDropdown(crops) {
    cropEl.innerHTML = '<option value="">Any crop</option>';
    crops.forEach(function(c) {
      var opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name + " (" + c.farm_count + ")";
      cropEl.appendChild(opt);
    });
    cropEl.onchange = function() {
      state.crop = cropEl.value;
      emitChange();
    };
  }

  // ── Init ─────────────────────────────────────────────────────────────────────

  function init(elements, callbacks, defaults) {
    categoriesEl = elements.categories;
    cropEl       = elements.crop;
    monthEl      = elements.month;
    pyoEl        = elements.pyo;
    organicEl    = elements.organic;

    onChangeHandler = callbacks.onChange;

    if (pyoEl)     pyoLabel     = pyoEl.closest("label")     || pyoEl.parentElement;
    if (organicEl) organicLabel = organicEl.closest("label") || organicEl.parentElement;

    if (pyoEl) {
      pyoEl.onchange = function() {
        state.pyo_only = pyoEl.checked;
        emitChange();
      };
    }
    if (organicEl) {
      organicEl.onchange = function() {
        state.organic = organicEl.checked;
        emitChange();
      };
    }

    // Normalize defaults — supports "all", or a comma-separated slug list for future use
    var cfg = defaults || {};

    Promise.all([
      EventMapAPI.getCategories(),
      EventMapAPI.getDistinctCrops()
    ]).then(function(results) {
      buildCategoryChips(results[0], cfg.defaultCategories);
      buildCropDropdown(results[1]);
      buildMonthDropdown();

      // Apply month default
      if (cfg.defaultMonth && monthEl) {
        state.month = cfg.defaultMonth;
        monthEl.value = cfg.defaultMonth;
      }
      // Apply crop default
      if (cfg.defaultCrop && cropEl) {
        state.crop = cfg.defaultCrop;
        cropEl.value = cfg.defaultCrop;
      }

      updateFarmControls();
      emitChange();  // trigger initial load with default-selected categories
    }).catch(function(err) {
      console.error("Filters init failed:", err);
    });
  }

  return { init: init, getSummary: getSummary };
})();

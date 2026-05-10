/**
 * Filter UI for Event Map.
 *
 * Categories are multi-select toggles. Farm-only controls (crop, PYO, organic)
 * are visible whenever the "farm" category is selected.
 */

const EventMapFilters = (() => {
  const DEFAULT_SELECTED = new Set(["farm", "festival", "fair"]);

  const state = {
    categories: new Set(DEFAULT_SELECTED),
    crop: "",
    month: "",
    pyo_only: false,
    organic: false
  };

  let onChangeHandler = null;
  let categoriesEl, cropEl, monthEl, pyoEl, organicEl;
  let pyoLabel, organicLabel;

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function isLightColor(hex) {
    if (!hex || hex.length < 7) return false;
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 160;
  }

  function setChipActive(btn, active) {
    var color = btn.dataset.color || "#8b2331";
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

  function toggleCategory(value) {
    if (state.categories.has(value)) {
      state.categories.delete(value);
    } else {
      state.categories.add(value);
    }

    categoriesEl.querySelectorAll(".chip").forEach(function(c) {
      setChipActive(c, state.categories.has(c.dataset.value));
    });

    updateFarmControls();
    emitChange();
  }

  // ── Build categories ─────────────────────────────────────────────────────────

  function buildCategoryChips(categories) {
    categoriesEl.innerHTML = "";
    categories.forEach(function(c) {
      var btn = document.createElement("button");
      btn.className = "chip";
      btn.textContent = c.name.charAt(0).toUpperCase() + c.name.slice(1).replace(/-/g, " ");
      btn.dataset.value = c.name;
      btn.dataset.color = c.color || "#8b2331";
      setChipActive(btn, state.categories.has(c.name));
      btn.onclick = function() { toggleCategory(c.name); };
      categoriesEl.appendChild(btn);
    });
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

  function init(elements, callbacks) {
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

    Promise.all([
      EventMapAPI.getCategories(),
      EventMapAPI.getDistinctCrops()
    ]).then(function(results) {
      buildCategoryChips(results[0]);
      buildCropDropdown(results[1]);
      buildMonthDropdown();

      updateFarmControls();
      emitChange();  // trigger initial load with default-selected categories
    }).catch(function(err) {
      console.error("Filters init failed:", err);
    });
  }

  return { init: init };
})();

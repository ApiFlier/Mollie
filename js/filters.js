/**
 * Filter UI for Mollie's Guide.
 *
 * Farm-only controls (crop, PYO, organic) are hidden when a non-farm
 * category is active. Month filter stays visible for all categories
 * since markets and festivals have season_start_month set.
 */

const MolliesFilters = (() => {
  const FARM_CATEGORIES = ["farm", "pick-your-own", ""];  // "" = All

  const state = {
    category: "",
    crop: "",
    month: "",
    pyo_only: false,
    organic: false
  };

  let onChangeHandler = null;
  let categoriesEl, cropEl, monthEl, pyoEl, organicEl;
  let pyoLabel, organicLabel;  // the wrapping <label> elements

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function isFarm(cat) {
    return FARM_CATEGORIES.includes(cat);
  }

  function setFarmControlsVisible(visible) {
    var d = visible ? "" : "none";
    if (cropEl)       cropEl.style.display       = d;
    if (pyoLabel)     pyoLabel.style.display     = d;
    if (organicLabel) organicLabel.style.display = d;
  }

  function emitChange() {
    if (!onChangeHandler) return;
    var p = {};
    if (state.category) p.category  = state.category;
    if (state.crop)     p.crop      = state.crop;
    if (state.month)    p.month     = state.month;
    if (state.pyo_only) p.pyo_only  = "true";
    if (state.organic)  p.organic   = "true";
    onChangeHandler(p);
  }

  // ── Category selection ───────────────────────────────────────────────────────

  function selectCategory(value) {
    state.category = value;

    categoriesEl.querySelectorAll(".chip").forEach(function(c) {
      c.classList.toggle("chip-active", c.dataset.value === value);
    });

    var farm = isFarm(value);
    setFarmControlsVisible(farm);

    // Reset farm-only state when leaving farm context
    if (!farm) {
      state.crop     = "";
      state.pyo_only = false;
      state.organic  = false;
      if (cropEl)    cropEl.value      = "";
      if (pyoEl)     pyoEl.checked     = false;
      if (organicEl) organicEl.checked = false;
    }

    emitChange();
  }

  // ── Build categories ─────────────────────────────────────────────────────────

  function buildCategoryChips(categories) {
    categoriesEl.innerHTML = "";

    var allBtn = document.createElement("button");
    allBtn.className = "chip chip-active";
    allBtn.textContent = "All";
    allBtn.dataset.value = "";
    allBtn.onclick = function() { selectCategory(""); };
    categoriesEl.appendChild(allBtn);

    categories.forEach(function(c) {
      var btn = document.createElement("button");
      btn.className = "chip";
      btn.textContent = c.name.charAt(0).toUpperCase() + c.name.slice(1).replace(/-/g, " ");
      btn.dataset.value = c.name;
      btn.style.borderColor = c.color;
      btn.onclick = function() { selectCategory(c.name); };
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

    // Grab the wrapping <label> for pyo and organic so we hide the
    // whole label+checkbox unit, not just the checkbox
    if (pyoEl)     pyoLabel     = pyoEl.closest("label")     || pyoEl.parentElement;
    if (organicEl) organicLabel = organicEl.closest("label") || organicEl.parentElement;

    // Wire up toggles
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
      MolliesAPI.getCategories(),
      MolliesAPI.getDistinctCrops()
    ]).then(function(results) {
      buildCategoryChips(results[0]);
      buildCropDropdown(results[1]);
      buildMonthDropdown();

      // Start in "All" context — farm controls visible by default
      setFarmControlsVisible(true);

      if (callbacks.onReady) callbacks.onReady();
    }).catch(function(err) {
      console.error("Filters init failed:", err);
    });
  }

  return { init: init };
})();
/**
 * Filter UI for Mollie's Guide.
 * All inputs are tap-only - no typing required.
 */

const MolliesFilters = (() => {
  const state = {
    category: "",
    crop: "",
    month: "",
    pyo_only: false,
    organic: false
  };

  let onChangeHandler = null;
  let categoriesEl, cropEl, monthEl, pyoEl, organicEl;

  function emitChange() {
    if (onChangeHandler) {
      var payload = {};
      if (state.category) payload.category = state.category;
      if (state.crop) payload.crop = state.crop;
      if (state.month) payload.month = state.month;
      if (state.pyo_only) payload.pyo_only = "true";
      if (state.organic) payload.organic = "true";
      onChangeHandler(payload);
    }
  }

  function buildCategoryChips(categories) {
    categoriesEl.innerHTML = "";

    var allChip = document.createElement("button");
    allChip.className = "chip chip-active";
    allChip.textContent = "All";
    allChip.dataset.value = "";
    allChip.addEventListener("click", function() { selectCategory(""); });
    categoriesEl.appendChild(allChip);

    categories.forEach(function(cat) {
      var chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = cat.name.replace(/-/g, " ");
      chip.dataset.value = cat.name;
      chip.style.borderColor = cat.color;
      chip.addEventListener("click", function() { selectCategory(cat.name); });
      categoriesEl.appendChild(chip);
    });
  }

  function selectCategory(value) {
    state.category = value;
    var chips = categoriesEl.querySelectorAll(".chip");
    chips.forEach(function(c) {
      if (c.dataset.value === value) {
        c.classList.add("chip-active");
      } else {
        c.classList.remove("chip-active");
      }
    });
    emitChange();
  }

  function buildCropDropdown(crops) {
    cropEl.innerHTML = "";
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Any crop";
    cropEl.appendChild(blank);

    crops.forEach(function(c) {
      var opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name + " (" + c.farm_count + ")";
      cropEl.appendChild(opt);
    });

    cropEl.addEventListener("change", function() {
      state.crop = cropEl.value;
      emitChange();
    });
  }

  function buildMonthDropdown() {
    var months = [
      "Any month",
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December"
    ];

    monthEl.innerHTML = "";
    months.forEach(function(name, i) {
      var opt = document.createElement("option");
      opt.value = i === 0 ? "" : String(i);
      opt.textContent = name;
      monthEl.appendChild(opt);
    });

    monthEl.addEventListener("change", function() {
      state.month = monthEl.value;
      emitChange();
    });
  }

  function setupToggles() {
    pyoEl.addEventListener("change", function() {
      state.pyo_only = pyoEl.checked;
      emitChange();
    });
    organicEl.addEventListener("change", function() {
      state.organic = organicEl.checked;
      emitChange();
    });
  }

  function init(elements, callbacks) {
    categoriesEl = elements.categories;
    cropEl = elements.crop;
    monthEl = elements.month;
    pyoEl = elements.pyo;
    organicEl = elements.organic;

    onChangeHandler = callbacks.onChange;

    Promise.all([
      MolliesAPI.getCategories(),
      MolliesAPI.getDistinctCrops()
    ]).then(function(results) {
      buildCategoryChips(results[0]);
      buildCropDropdown(results[1]);
      buildMonthDropdown();
      setupToggles();
      if (callbacks.onReady) callbacks.onReady();
    }).catch(function(err) {
      console.error("Filters init failed:", err);
    });
  }

  return { init: init };
})();

const MolliesFilters = (() => {
  const state = { category: "", crop: "", month: "", pyo_only: false, organic: false };
  let onChangeHandler = null;
  let categoriesEl, cropEl, monthEl, pyoEl, organicEl;

  function emitChange() {
    if (!onChangeHandler) return;
    const p = {};
    if (state.category) p.category = state.category;
    if (state.crop) p.crop = state.crop;
    if (state.month) p.month = state.month;
    onChangeHandler(p);
  }

  function selectCategory(value) {
    state.category = value;
    
    // Update active chip visuals
    categoriesEl.querySelectorAll(".chip").forEach(c => {
      c.classList.toggle("chip-active", c.dataset.value === value);
    });
    
    const isFarm = (value === "farm" || value === "pick-your-own");
    const cropLabel = document.querySelector('label[for="crop-select"]');
    
    // Only show the secondary dropdown for Farms
    if (isFarm) {
      if (cropLabel) cropLabel.textContent = "Crop";
      if (cropEl) {
          cropEl.style.display = "";
          MolliesAPI.getDistinctCrops().then(crops => {
            cropEl.innerHTML = '<option value="">Any crop</option>' + crops.map(c => `<option value="${c.name}">${c.name}</option>`).join("");
          });
      }
    } else {
      // Hide the secondary dropdown for All, Fairs, Festivals, etc.
      if (cropEl) cropEl.style.display = "none";
      state.crop = ""; // Clear the crop state so it doesn't accidentally filter
    }

    if (monthEl) monthEl.style.display = ""; 
    emitChange();
  }

  return {
    init: (els, cb) => {
      categoriesEl = els.categories; cropEl = els.crop; monthEl = els.month;
      onChangeHandler = cb.onChange;
      
      MolliesAPI.getCategories().then(cats => {
        categoriesEl.innerHTML = ''; // Clear out any existing HTML

        // Build the "All" button correctly WITH a click listener
        const allBtn = document.createElement("button");
        allBtn.className = "chip chip-active"; 
        allBtn.textContent = "All";
        allBtn.dataset.value = "";
        allBtn.onclick = () => selectCategory("");
        categoriesEl.appendChild(allBtn);

        // Build the rest of the category buttons
        cats.forEach(c => {
          const btn = document.createElement("button");
          btn.className = "chip"; 
          btn.textContent = c.name.charAt(0).toUpperCase() + c.name.slice(1);
          btn.dataset.value = c.name; 
          btn.style.borderColor = c.color;
          btn.onclick = () => selectCategory(c.name);
          categoriesEl.appendChild(btn);
        });
      });

      const ms = ["Any month","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      if (monthEl) {
          monthEl.innerHTML = ms.map((m, i) => `<option value="${i===0?'':i}">${m}</option>`).join("");
          monthEl.onchange = () => { state.month = monthEl.value; emitChange(); };
      }
      
      if (cropEl) {
          cropEl.onchange = () => { state.crop = cropEl.value; emitChange(); };
          // Hide it by default on initial load (since "All" is selected)
          cropEl.style.display = "none"; 
      }
      
      const cropLabel = document.querySelector('label[for="crop-select"]');
      if (cropLabel) cropLabel.textContent = "Crop";

      if (cb.onReady) cb.onReady();
    }
  };
})();

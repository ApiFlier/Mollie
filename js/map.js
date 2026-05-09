/**
 * Map setup and pin rendering for Event Map.
 * Uses Leaflet with Esri World Imagery (aerial) plus a labels overlay.
 */

const EventMapMap = (() => {
  const DEFAULT_CENTER = [40.5061, -79.8389];
  const DEFAULT_ZOOM = 9;

  let map = null;
  let markerLayer = null;
  let onMarkerClick = null;
  let userLocationMarker = null;

  function init(containerId, options) {
    options = options || {};
    map = L.map(containerId, {
      center: options.center || DEFAULT_CENTER,
      zoom: options.zoom || DEFAULT_ZOOM,
      zoomControl: true,
    });

    var esriBase = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    var imgUrl = esriBase + "World_Imagery/MapServer/tile/{z}/{y}/{x}";
    var lblUrl = esriBase + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
    var rdUrl  = esriBase + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}";

    L.tileLayer(imgUrl, { attribution: "Tiles (c) Esri", maxZoom: 19 }).addTo(map);
    L.tileLayer(lblUrl, { attribution: "(c) Esri", maxZoom: 19 }).addTo(map);
    L.tileLayer(rdUrl,  { attribution: "", maxZoom: 19 }).addTo(map);

    markerLayer = L.layerGroup().addTo(map);
    return map;
  }

  function setOnMarkerClick(handler) {
    onMarkerClick = handler;
  }

  function makeIcon(color) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 32" width="28" height="38">';
    svg += '<path d="M12 0 C5.4 0 0 5.4 0 12 c0 8 12 20 12 20 s12-12 12-20 C24 5.4 18.6 0 12 0 z" ';
    svg += 'fill="' + color + '" stroke="#3a2820" stroke-width="1.5"/>';
    svg += '<circle cx="12" cy="12" r="5" fill="#faf6f0"/>';
    svg += '</svg>';
    return L.divIcon({
      html: svg,
      className: "map-pin",
      iconSize: [28, 38],
      iconAnchor: [14, 38],
      popupAnchor: [0, -34]
    });
  }

  function renderLocations(locations) {
    markerLayer.clearLayers();
    locations.forEach(function(loc) {
      if (loc.lat == null || loc.lng == null) return;
      var color = loc.category_color || "#8b2331";
      var marker = L.marker([loc.lat, loc.lng], { icon: makeIcon(color) });
      marker.on("click", function() {
        if (onMarkerClick) onMarkerClick(loc);
      });
      markerLayer.addLayer(marker);
    });
  }

  function fitToMarkers(locations) {
    var valid = locations.filter(function(l) {
      return l.lat != null && l.lng != null;
    });
    if (valid.length === 0) return;
    var bounds = L.latLngBounds(valid.map(function(l) {
      return [l.lat, l.lng];
    }));
    map.fitBounds(bounds, { padding: [40, 40] });
  }

  function panTo(lat, lng, zoom) {
    map.setView([lat, lng], zoom || 13);
  }

  function showUserLocation(lat, lng) {
    if (userLocationMarker) {
      map.removeLayer(userLocationMarker);
    }
    var icon = L.divIcon({
      html: '<div class="user-location-dot"></div>',
      className: "user-location-icon",
      iconSize: [18, 18],
      iconAnchor: [9, 9]
    });
    userLocationMarker = L.marker([lat, lng], {
      icon: icon,
      interactive: false,
      keyboard: false
    }).addTo(map);
  }

  return {
    init: init,
    setOnMarkerClick: setOnMarkerClick,
    renderLocations: renderLocations,
    fitToMarkers: fitToMarkers,
    panTo: panTo,
    showUserLocation: showUserLocation
  };
})();

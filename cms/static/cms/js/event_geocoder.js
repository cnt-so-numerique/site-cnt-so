/**
 * Autocomplete adresse.data.gouv.fr sur le champ "Lieu" d'un événement.
 * Remplit automatiquement latitude et longitude quand une adresse est sélectionnée.
 */
(function () {
  'use strict';

  function initGeocoder() {
    var locationInput = document.querySelector('[name="location"]');
    if (!locationInput) return;

    var latInput   = document.querySelector('[name="latitude"]');
    var lonInput   = document.querySelector('[name="longitude"]');
    if (!latInput || !lonInput) return;

    // Conteneur suggestions
    var box = document.createElement('div');
    box.id = 'geocoder-suggestions';
    box.style.cssText = [
      'position:absolute', 'z-index:9999', 'background:#fff',
      'border:1px solid #ccc', 'border-radius:4px', 'max-height:220px',
      'overflow-y:auto', 'width:100%', 'box-shadow:0 4px 12px rgba(0,0,0,.15)',
      'display:none', 'font-size:.875rem',
    ].join(';');

    var wrap = locationInput.parentElement;
    wrap.style.position = 'relative';
    wrap.appendChild(box);

    // Indicateur coordonnées
    var coordBadge = document.createElement('div');
    coordBadge.style.cssText = 'margin-top:.3rem;font-size:.75rem;color:#6b7280;';
    wrap.appendChild(coordBadge);

    function updateBadge() {
      var lat = latInput.value, lon = lonInput.value;
      coordBadge.textContent = (lat && lon)
        ? '📍 ' + parseFloat(lat).toFixed(5) + ', ' + parseFloat(lon).toFixed(5)
        : '';
    }
    updateBadge();

    var timer = null;

    locationInput.addEventListener('input', function () {
      clearTimeout(timer);
      var q = this.value.trim();
      if (q.length < 3) { box.style.display = 'none'; return; }
      timer = setTimeout(function () { fetchSuggestions(q); }, 300);
    });

    function fetchSuggestions(q) {
      fetch('https://api-adresse.data.gouv.fr/search/?q=' + encodeURIComponent(q) + '&limit=6&autocomplete=1')
        .then(function (r) { return r.json(); })
        .then(function (data) { renderSuggestions(data.features || []); })
        .catch(function () { box.style.display = 'none'; });
    }

    function renderSuggestions(features) {
      box.innerHTML = '';
      if (!features.length) { box.style.display = 'none'; return; }

      features.forEach(function (f) {
        var item = document.createElement('div');
        item.textContent = f.properties.label;
        item.style.cssText = 'padding:.5rem .75rem;cursor:pointer;border-bottom:1px solid #f0f0f0;';
        item.addEventListener('mouseenter', function () { this.style.background = '#f5f5f5'; });
        item.addEventListener('mouseleave', function () { this.style.background = ''; });
        item.addEventListener('mousedown', function (e) {
          e.preventDefault();
          locationInput.value = f.properties.label;
          latInput.value      = f.geometry.coordinates[1];
          lonInput.value      = f.geometry.coordinates[0];
          updateBadge();
          box.style.display = 'none';
        });
        box.appendChild(item);
      });
      box.style.display = 'block';
    }

    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target)) box.style.display = 'none';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGeocoder);
  } else {
    initGeocoder();
  }
})();

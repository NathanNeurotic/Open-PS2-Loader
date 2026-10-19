/* Fork Feature Gaps: progressive enhancement. All directory rows remain usable without JS. */
(function () {
  'use strict';
  var page = document.getElementById('fork-gap-audit');
  if (!page) return;

  function init(tableId, queryId, selectId, countId, emptyId) {
    var table = document.getElementById(tableId);
    var query = document.getElementById(queryId);
    var type = document.getElementById(selectId);
    var count = document.getElementById(countId);
    var empty = document.getElementById(emptyId);
    if (!table || !query || !type) return;
    var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
    function update() {
      var term = query.value.trim().toLocaleLowerCase();
      var value = type.value;
      var visible = 0;
      rows.forEach(function (row) {
        var text = row.textContent.toLocaleLowerCase();
        var matches = !term || text.indexOf(term) !== -1;
        var group = row.getAttribute('data-filter-value') || '';
        var matchesGroup = !value || value === group;
        row.hidden = !(matches && matchesGroup);
        if (!row.hidden) visible++;
      });
      if (count) count.textContent = visible + ' of ' + rows.length + ' records shown';
      if (empty) empty.hidden = visible !== 0;
    }
    query.addEventListener('input', update);
    type.addEventListener('change', update);
    update();
  }

  init('fork-gap-register', 'gap-search', 'gap-status', 'gap-results', 'gap-empty');
  init('fork-project-directory', 'project-search', 'project-category', 'project-results', 'project-empty');

  /* Anchor navigation must not land on a row hidden by a user's active search. */
  function ensureHashVisible() {
    var id = window.location.hash.slice(1);
    if (!id) return;
    var el = document.getElementById(id);
    if (!el || el.tagName !== 'TR' || !el.hidden) return;
    var table = el.closest('table');
    var input = table && document.getElementById(table.id === 'fork-gap-register' ? 'gap-search' : 'project-search');
    var select = table && document.getElementById(table.id === 'fork-gap-register' ? 'gap-status' : 'project-category');
    if (input) { input.value = ''; input.dispatchEvent(new Event('input')); }
    if (select) { select.value = ''; select.dispatchEvent(new Event('change')); }
    el.scrollIntoView();
  }
  window.addEventListener('hashchange', ensureHashVisible);
})();

(function () {
  // theme
  var root = document.documentElement;
  document.querySelectorAll('[data-theme-toggle]').forEach(function (b) {
    b.addEventListener('click', function () {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      try { localStorage.setItem('theme', next); } catch (e) {}
    });
  });

  // show only categories that match the chosen Income/Expense type
  var kinds = document.getElementById('cat-kinds');
  var select = document.getElementById('id_category');
  if (kinds && select) {
    var map = JSON.parse(kinds.textContent);
    var sync = function () {
      var picked = document.querySelector('input[name=kind]:checked');
      if (!picked) return;
      Array.prototype.forEach.call(select.options, function (o) {
        if (!o.value) return;
        var ok = map[o.value] === picked.value;
        o.hidden = !ok; o.disabled = !ok;
      });
      if (select.selectedOptions[0] && select.selectedOptions[0].disabled) select.value = '';
    };
    document.querySelectorAll('input[name=kind]').forEach(function (r) { r.addEventListener('change', sync); });
    sync();
  }

  // charts (Chart.js is loaded from a CDN; pages still work without it)
  function bars(id, dataId) {
    var canvas = document.getElementById(id), data = document.getElementById(dataId);
    if (!canvas || !data || typeof Chart === 'undefined') return;
    var d = JSON.parse(data.textContent), css = getComputedStyle(root);
    var ink = css.getPropertyValue('--muted').trim(), line = css.getPropertyValue('--line').trim();
    new Chart(canvas, {
      type: 'bar',
      data: { labels: d.labels, datasets: [
        { label: 'Income', data: d.income, backgroundColor: css.getPropertyValue('--income').trim(), borderRadius: 6 },
        { label: 'Expenses', data: d.expense, backgroundColor: css.getPropertyValue('--expense').trim(), borderRadius: 6 }
      ]},
      options: { maintainAspectRatio: false, plugins: { legend: { labels: { color: ink, boxWidth: 12 } } },
        scales: { x: { ticks: { color: ink }, grid: { display: false } },
                  y: { ticks: { color: ink, callback: function (v) { return '₹' + v.toLocaleString('en-IN'); } }, grid: { color: line } } } }
    });
  }
  bars('trendChart', 'trend-data');
  bars('fyChart', 'fy-data');
})();

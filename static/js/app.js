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

  // one-tap actions that move money ask first (e.g. the Cleared button)
  document.querySelectorAll('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (!window.confirm(f.dataset.confirm)) e.preventDefault();
    });
  });

  // repayment form: quick-fill buttons and live "balance after this payment"
  var pay = document.querySelector('form[data-balance]');
  if (pay) {
    var balance = parseFloat(pay.dataset.balance) || 0;
    var amount = pay.querySelector('input[name=amount]');
    var after = pay.querySelector('[data-after]');
    var box = pay.querySelector('.afterbox');
    var fmt = function (n) {
      return '\u20B9' + n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    };
    var update = function () {
      var left = balance - (parseFloat(amount.value) || 0);
      after.textContent = left < 0 ? 'more than the balance' : fmt(left);
      box.classList.toggle('bad', left < 0);
    };
    pay.querySelectorAll('[data-fill]').forEach(function (b) {
      b.addEventListener('click', function () {
        amount.value = (Math.round(balance * parseFloat(b.dataset.fill) * 100) / 100).toFixed(2);
        update();
      });
    });
    amount.addEventListener('input', update);
    update();
  }

  // borrow form: say which way the wallet balance moves
  var hint = document.querySelector('[data-dir-hint]');
  if (hint) {
    var dirs = document.querySelectorAll('input[name=direction]');
    var sayDir = function () {
      var on = document.querySelector('input[name=direction]:checked');
      if (!on) return;
      hint.textContent = on.value === 'lent'
        ? 'The amount is taken out of this wallet now, and added back when it is returned.'
        : 'The amount is added to this wallet now, and taken out when you repay.';
    };
    dirs.forEach(function (r) { r.addEventListener('change', sayDir); });
    sayDir();
  }

  // charts: small built-in SVG bar chart (no external script, follows the theme)
  var NS = 'http://www.w3.org/2000/svg';
  function el(name, attrs, parent) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function short(n) {
    var a = Math.abs(n), sign = n < 0 ? '-' : '';
    if (a >= 1e7) return sign + '\u20B9' + +(a / 1e7).toFixed(1) + 'Cr';
    if (a >= 1e5) return sign + '\u20B9' + +(a / 1e5).toFixed(1) + 'L';
    if (a >= 1e3) return sign + '\u20B9' + +(a / 1e3).toFixed(1) + 'k';
    return sign + '\u20B9' + Math.round(a);
  }
  function money(n) { return '\u20B9' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 }); }

  function drawChart(box) {
    var node = document.getElementById(box.dataset.chart);
    if (!node) return;
    var d = JSON.parse(node.textContent);
    var W = Math.max(box.clientWidth, 240), H = 240, L = 46, R = 6, T = 10, B = 26;
    var max = Math.max.apply(null, d.income.concat(d.expense, [1]));
    var step = Math.pow(10, Math.floor(Math.log10(max)));
    var top = step * 10;
    [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].some(function (m) { if (step * m >= max) { top = step * m; return true; } });
    box.innerHTML = '';
    var legend = document.createElement('div');
    legend.className = 'chartlegend';
    legend.innerHTML = '<span><i style="background:var(--income)"></i>Income</span><span><i style="background:var(--expense)"></i>Expenses</span>';
    box.appendChild(legend);
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'chart', height: H, 'aria-hidden': 'true' }, box);
    var defs = el('defs', {}, svg);
    [['gi', '--income'], ['ge', '--expense']].forEach(function (g) {
      var lg = el('linearGradient', { id: g[0] + box.dataset.chart, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
      el('stop', { offset: '0%', style: 'stop-color:var(' + g[1] + ')' }, lg);
      el('stop', { offset: '100%', style: 'stop-color:var(' + g[1] + ');stop-opacity:.35' }, lg);
    });
    var ph = H - T - B, pw = W - L - R;
    for (var t = 0; t <= 4; t++) {
      var y = T + ph - (ph * t / 4), v = top * t / 4;
      el('line', { x1: L, x2: W - R, y1: y, y2: y, class: 'gl' }, svg);
      var tx = el('text', { x: L - 8, y: y + 4, 'text-anchor': 'end' }, svg);
      tx.textContent = short(v);
    }
    var n = d.labels.length, slot = pw / n, bw = Math.max(Math.min(slot * 0.32, 26), 6);
    d.labels.forEach(function (lab, i) {
      var cx = L + slot * i + slot / 2;
      [[d.income[i], 'gi', -bw - 2, 'Income'], [d.expense[i], 'ge', 2, 'Expenses']].forEach(function (b) {
        var h = Math.max(ph * b[0] / top, b[0] > 0 ? 3 : 0);
        var r = el('rect', { x: cx + b[2], y: T + ph - h, width: bw, height: h, rx: Math.min(6, bw / 2), fill: 'url(#' + b[1] + box.dataset.chart + ')' }, svg);
        el('title', {}, r).textContent = lab + ' \u00B7 ' + b[3] + ': ' + money(b[0]);
      });
      var lt = el('text', { x: cx, y: H - 7, 'text-anchor': 'middle' }, svg);
      lt.textContent = slot < 58 ? lab.split(' ')[0] : lab;
    });
  }
  var boxes = document.querySelectorAll('[data-chart]');
  function drawAll() { boxes.forEach(drawChart); }
  if (boxes.length) {
    drawAll();
    var timer;
    window.addEventListener('resize', function () { clearTimeout(timer); timer = setTimeout(drawAll, 120); });
  }
})();

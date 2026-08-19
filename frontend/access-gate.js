// Masks the tracker/section cards a role cannot open, on every page that marks
// its cards with data-section or data-tracker. Cosmetic only — the page gates
// in backend.py are what actually refuse entry.
(function () {
  var CSS = [
    '.locked { opacity: .5; filter: grayscale(1); cursor: not-allowed; }',
    '.locked:hover { transform: none !important; box-shadow: inherit; }',
    '.locked .badge { visibility: hidden; }',
    '.lock-note {',
    '  display: inline-flex; align-items: center; gap: 6px; margin-top: 14px;',
    '  padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: 600;',
    '  background: rgba(100,116,139,.16); color: #475569;',
    '}',
    '#access-toast {',
    '  position: fixed; bottom: 26px; left: 50%; transform: translateX(-50%) translateY(12px);',
    '  z-index: 9999; padding: 13px 22px; border-radius: 12px; font-size: 14px; font-weight: 600;',
    '  font-family: Inter, sans-serif; color: #fff; background: #1e293b;',
    '  box-shadow: 0 12px 34px rgba(15,23,42,.32); opacity: 0; pointer-events: none;',
    '  transition: opacity .18s ease, transform .18s ease;',
    '}',
    '#access-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }'
  ].join('\n');

  var style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  var toastEl = null, toastTimer = null;
  function toast(message) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.id = 'access-toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, 2600);
  }

  function lock(el) {
    el.classList.add('locked');
    el.removeAttribute('href');
    var note = document.createElement('span');
    note.className = 'lock-note';
    note.textContent = 'No access';
    (el.querySelector('.body') || el).appendChild(note);
    el.addEventListener('click', function (e) {
      e.preventDefault();
      toast("You don't have access");
    });
  }

  fetch('/auth/me', { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (me) {
      var sections = new Set(me.sections || []);
      var trackers = new Set(me.trackers || []);
      document.querySelectorAll('[data-section],[data-tracker]').forEach(function (el) {
        var key = el.dataset.section || el.dataset.tracker;
        var granted = el.dataset.section ? sections.has(key) : trackers.has(key);
        el.hidden = false;
        if (!granted) lock(el);
      });
    })
    .catch(function () {
      document.querySelectorAll('[data-section],[data-tracker]')
        .forEach(function (el) { el.hidden = false; });
    });
})();

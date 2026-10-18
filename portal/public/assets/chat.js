/* Report Copilot chat. All server text is inserted with textContent (never innerHTML) to prevent XSS. */
(function () {
  'use strict';

  var cfg = document.getElementById('chat-config').dataset;
  var log = document.getElementById('chat-log');
  var form = document.getElementById('ask-form');
  var input = document.getElementById('question');
  var button = document.getElementById('ask-btn');

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }

  function post(url, fields) {
    var body = new FormData();
    Object.keys(fields).forEach(function (k) { body.append(k, fields[k]); });
    body.append(cfg.csrfName, cfg.csrfHash);
    return fetch(url, { method: 'POST', body: body, credentials: 'same-origin',
                        headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) {
        return r.text().then(function (t) {
          try { return { status: r.status, body: JSON.parse(t) }; } catch (e) { return { status: r.status, body: null }; }
        });
      });
  }

  function feedbackButtons(convId) {
    var box = el('div', 'feedback');
    [['1', '👍', 'Helpful'], ['-1', '👎', 'Not helpful']].forEach(function (b) {
      var btn = el('button', 'fb', b[1]);
      btn.type = 'button';
      btn.dataset.rating = b[0];
      btn.setAttribute('aria-label', b[2]);
      box.appendChild(btn);
    });
    if (!convId) { box.hidden = true; }
    return box;
  }

  function renderResponse(bot, data) {
    var r = data.response;
    bot.dataset.convId = data.conversation_id || '';
    bot.textContent = '';
    var meta = el('div', 'meta');
    meta.appendChild(el('span', 'badge', 'confidence ' + Number(r.confidence).toFixed(2)));
    if (r.escalated) { meta.appendChild(el('span', 'badge warn', 'escalated to analyst' + (r.escalation_id ? ' #' + r.escalation_id : ''))); }
    if (r.conflicts && r.conflicts.length) { meta.appendChild(el('span', 'badge warn', r.conflicts.length + ' source conflict(s)')); }
    if (r.derived_values && r.derived_values.length) { meta.appendChild(el('span', 'badge info', 'contains derived estimate')); }
    if (r.injection_detected) { meta.appendChild(el('span', 'badge warn', 'suspicious document text ignored')); }
    if (r.cached) { meta.appendChild(el('span', 'badge', 'cached')); }
    meta.appendChild(el('span', 'muted', r.latency_ms + ' ms'));
    bot.appendChild(meta);
    bot.appendChild(el('div', 'answer', r.answer));

    if (r.citations && r.citations.length) {
      var det = el('details', 'sources');
      det.appendChild(el('summary', null, 'Sources (' + r.citations.length + ')'));
      var ul = el('ul');
      r.citations.forEach(function (c) {
        var where = c.report_id ? c.report_id + (c.page ? ' p.' + c.page : '') : c.title;
        ul.appendChild(el('li', null, '[' + c.id + '] ' + where + ' - ' + c.snippet));
      });
      det.appendChild(ul);
      bot.appendChild(det);
    }
    if (r.confidence_reasons && r.confidence_reasons.length) {
      var why = el('details', 'sources');
      why.appendChild(el('summary', null, 'Why this confidence?'));
      var ul2 = el('ul');
      r.confidence_reasons.forEach(function (t) { ul2.appendChild(el('li', null, t)); });
      why.appendChild(ul2);
      bot.appendChild(why);
    }
    bot.appendChild(feedbackButtons(data.conversation_id));
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var q = input.value.trim();
    if (!q) { return; }
    var hint = log.querySelector('.hint');
    if (hint) { hint.remove(); }
    log.appendChild(el('div', 'msg user', q));
    var bot = el('div', 'msg bot pending', 'Checking your reports...');
    log.appendChild(bot);
    bot.scrollIntoView({ behavior: 'smooth' });
    input.value = '';
    button.disabled = true;

    post(cfg.askUrl, { question: q }).then(function (res) {
      bot.classList.remove('pending');
      var b = res.body;
      if (b && b.ok) {
        renderResponse(bot, b);
      } else if (b && b.fallback) {
        bot.textContent = '';
        var meta = el('div', 'meta');
        meta.appendChild(el('span', 'badge warn', 'service unavailable'));
        bot.appendChild(meta);
        bot.appendChild(el('div', 'answer', b.message));
        bot.dataset.convId = b.conversation_id || '';
        bot.appendChild(feedbackButtons(b.conversation_id));
      } else {
        bot.classList.add('error');
        bot.textContent = (b && b.error) ? b.error
          : (res.status === 403 ? 'Your session security token expired. Please reload the page.'
                                : 'Something went wrong. Please try again.');
      }
    }).catch(function () {
      bot.classList.remove('pending');
      bot.classList.add('error');
      bot.textContent = 'Could not reach the portal. Please check your connection and try again.';
    }).then(function () {
      button.disabled = false;
      input.focus();
    });
  });

  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); }
  });

  log.addEventListener('click', function (ev) {
    var btn = ev.target.closest('button.fb');
    if (!btn) { return; }
    var bot = btn.closest('.msg.bot');
    var convId = bot && bot.dataset.convId;
    if (!convId) { return; }
    post(cfg.feedbackUrl, { conversation_id: convId, rating: btn.dataset.rating }).then(function (res) {
      if (res.body && res.body.ok) {
        bot.querySelectorAll('button.fb').forEach(function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
      }
    });
  });
})();

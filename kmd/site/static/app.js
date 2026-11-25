/* Course site behaviour: theme, progress/resume, tasks with instant check, drag-to-order (mouse,
   finger, keyboard), decision cases, flashcards, animation player, math. No network, no frameworks. */
(function () {
  "use strict";
  var C = window.KMD_COURSE || { chapter: "course", steps: [] };
  var NS = "kmd:" + C.chapter + ":";
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(NS + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(NS + k, JSON.stringify(v)); } catch (e) {} },
    del: function (k) { try { localStorage.removeItem(NS + k); } catch (e) {} }
  };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- theme */
  var root = document.documentElement;
  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  var tbtn = $(".theme-toggle");
  function labelTheme() { if (tbtn) tbtn.setAttribute("aria-label", currentTheme() === "dark" ? "Включить светлую тему" : "Включить тёмную тему"); }
  if (tbtn) tbtn.addEventListener("click", function () {
    var t = currentTheme() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", t);
    try { localStorage.setItem("kmd:theme", t); } catch (e) {}
    labelTheme();
  });
  labelTheme();

  /* ---------- progress */
  function done() { return store.get("done", []); }
  function setDone(id, on) {
    var d = done().filter(function (x) { return x !== id; });
    if (on) d.push(id);
    store.set("done", d);
    paintProgress();
  }
  function paintProgress() {
    var d = done(), n = C.steps.length || 1;
    var k = C.steps.filter(function (s) { return d.indexOf(s.node_id) >= 0; }).length;
    var bar = $(".progress-bar"), pb = $(".progress");
    if (bar) bar.style.width = (100 * k / n) + "%";
    if (pb) { pb.setAttribute("aria-valuenow", k); pb.setAttribute("title", "Пройдено шагов: " + k + " из " + C.steps.length); }
    $$(".path-step").forEach(function (li) {
      var on = d.indexOf(li.dataset.node) >= 0;
      li.classList.toggle("done", on);
      var m = $(".ps-done", li); if (m) m.hidden = !on;
    });
    $$(".lm-node").forEach(function (a) { a.classList.toggle("done", d.indexOf(a.dataset.node) >= 0); });
  }
  paintProgress();

  var layout = $(".layout[data-node]");
  if (layout) {
    var nid = layout.dataset.node;
    var st = C.steps.filter(function (s) { return s.node_id === nid; })[0];
    if (st) store.set("last", { node_id: nid, url: st.url, title: st.title, index: st.index, hash: location.hash || "" });
    var mb = $(".mark-done");
    var paintBtn = function () {
      var on = done().indexOf(nid) >= 0;
      mb.setAttribute("aria-pressed", on ? "true" : "false");
      mb.textContent = on ? "✓ Шаг пройден (снять отметку)" : "Отметить шаг пройденным";
    };
    if (mb) { paintBtn(); mb.addEventListener("click", function () { setDone(nid, done().indexOf(nid) < 0); paintBtn(); }); }
    var pager = $(".pager");
    if (pager && "IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting && done().indexOf(nid) < 0) { setDone(nid, true); if (mb) paintBtn(); } });
      }, { threshold: 0.6 });
      io.observe(pager);
    }
    // remember the section the reader is in (resume "where I stopped")
    var secs = $$("main section[id]");
    var tocLinks = $$(".toc-box a");
    if ("IntersectionObserver" in window && secs.length) {
      var so = new IntersectionObserver(function (es) {
        es.forEach(function (e) {
          if (!e.isIntersecting) return;
          var id = e.target.id;
          tocLinks.forEach(function (a) { a.classList.toggle("active", a.getAttribute("href") === "#" + id); });
          var l = store.get("last", {}); if (l.node_id === nid) { l.hash = "#" + id; store.set("last", l); }
        });
      }, { rootMargin: "-20% 0px -70% 0px" });
      secs.forEach(function (s) { so.observe(s); });
    }
    var tocBox = $(".toc-box");
    if (tocBox && window.matchMedia("(max-width: 1099px)").matches) tocBox.open = false;
  }

  // index: resume
  var resume = $(".resume");
  if (resume) {
    var last = store.get("last", null);
    var cur = last && C.steps.filter(function (s) { return s.node_id === last.node_id; })[0];
    if (cur) {
      var a = $(".start", resume);
      a.href = cur.url + (last.hash || "");
      a.textContent = "Продолжить: шаг " + cur.index;
      $(".resume-note", resume).textContent = "Вы остановились на шаге «" + cur.title + "». Начать сначала можно с шага 1 ниже.";
      $$(".path-step").forEach(function (li) { li.classList.toggle("current", li.dataset.node === cur.node_id); });
    }
  }

  /* ---------- tasks */
  var TASKS = {};
  (window.KMD_TASKS || []).forEach(function (t) { TASKS[t.id] = t; });
  function normText(s) { return String(s || "").toLowerCase().replace(/ё/g, "е").replace(/[«»"'.,;:!?()]/g, "").replace(/\s+/g, " ").trim(); }

  function initOrder(list) {
    var drag = null;
    list.addEventListener("pointerdown", function (e) {
      if (list.dataset.locked || e.target.closest(".mv")) return;
      var li = e.target.closest(".order-item"); if (!li) return;
      if (e.pointerType === "mouse" && e.button !== 0) return;
      e.preventDefault();
      drag = { li: li, y0: e.clientY };
      try { li.setPointerCapture(e.pointerId); } catch (err) {}
      li.classList.add("dragging");
    });
    list.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var li = drag.li, dy = e.clientY - drag.y0;
      var next = li.nextElementSibling, prev = li.previousElementSibling, before = li.offsetTop;
      if (next && dy > next.offsetHeight / 2) { list.insertBefore(next, li); drag.y0 += li.offsetTop - before; }
      else if (prev && -dy > prev.offsetHeight / 2) { list.insertBefore(prev, li.nextSibling); drag.y0 += li.offsetTop - before; } // never move the captured node itself
      li.style.transform = "translateY(" + (e.clientY - drag.y0) + "px)";
    });
    function end() { if (!drag) return; drag.li.style.transform = ""; drag.li.classList.remove("dragging"); drag = null; }
    list.addEventListener("pointerup", end);
    list.addEventListener("pointercancel", end);
    list.addEventListener("lostpointercapture", end);
    list.addEventListener("click", function (e) {
      var b = e.target.closest(".mv"); if (!b || list.dataset.locked) return;
      var li = b.closest(".order-item");
      if (b.classList.contains("up") && li.previousElementSibling) list.insertBefore(li, li.previousElementSibling);
      else if (b.classList.contains("down") && li.nextElementSibling) list.insertBefore(li.nextElementSibling, li);
      b.focus();
    });
  }

  function checkTask(box, t) {
    var ok = false;
    if (t.type === "single" || t.type === "multiple") {
      var sel = $$("input", box).filter(function (i) { return i.checked; }).map(function (i) { return +i.value; });
      if (!sel.length) return null;
      ok = sel.length === t.key.length && sel.every(function (v) { return t.key.indexOf(v) >= 0; });
      $$(".opt", box).forEach(function (o, i) {
        if (t.key.indexOf(i) >= 0) o.classList.add("right");
        else if (sel.indexOf(i) >= 0) o.classList.add("wrong");
      });
    } else if (t.type === "order") {
      var items = $$(".order-item", box);
      ok = true;
      items.forEach(function (li, i) { var r = +li.dataset.pos === i; li.classList.add(r ? "right" : "wrong"); if (!r) ok = false; });
      $(".order", box).dataset.locked = "1";
    } else if (t.type === "cloze") {
      var fields = $$("select, input", box);
      if (fields.some(function (f) { return !f.value; })) return null;
      ok = true;
      fields.forEach(function (f, i) {
        var r = (t.key[i] || []).some(function (a) { return normText(a) === normText(f.value); });
        f.classList.add(r ? "right" : "wrong"); if (!r) ok = false;
      });
    } else if (t.type === "numeric") {
      var inp = $("input", box), raw = (inp.value || "").replace(",", ".").replace(/\s/g, "");
      if (!raw) return null;
      var x = parseFloat(raw);
      ok = isFinite(x) && Math.abs(x - t.key.answer) <= (t.key.tolerance || 0) + 1e-9;
      inp.classList.add(ok ? "right" : "wrong");
    }
    return ok;
  }

  function resetTask(box) {
    box.classList.remove("ok", "no");
    $$(".right, .wrong", box).forEach(function (e) { e.classList.remove("right", "wrong"); });
    $$("input, select", box).forEach(function (i) { i.disabled = false; if (i.type === "radio" || i.type === "checkbox") i.checked = false; else i.value = ""; });
    var ol = $(".order", box); if (ol) delete ol.dataset.locked;
    $$(".mv", box).forEach(function (b) { b.disabled = false; });
    $(".feedback", box).hidden = true;
    $(".check", box).hidden = false;
    $(".retry", box).hidden = true;
    $(".task-state", box).textContent = "";
  }

  function paintScore() {
    var el = $(".score"); if (!el) return;
    var ids = Object.keys(TASKS), okN = 0, tried = 0;
    ids.forEach(function (id) { var r = store.get("task:" + id, null); if (r) { tried++; if (r === "ok") okN++; } });
    el.textContent = "Решено верно: " + okN + " из " + ids.length + (tried > okN ? " (ошибок: " + (tried - okN) + ")" : "");
  }

  $$(".task").forEach(function (box) {
    var t = TASKS[box.dataset.task]; if (!t) return;
    if (t.type === "order") initOrder($(".order", box));
    var prev = store.get("task:" + t.id, null);
    if (prev) $(".task-state", box).textContent = prev === "ok" ? "✓ решено ранее" : "решено с ошибкой ранее";
    $(".check", box).addEventListener("click", function () {
      var ok = checkTask(box, t);
      var st = $(".task-state", box);
      if (ok === null) { st.textContent = "Сначала дайте ответ"; return; }
      box.classList.add(ok ? "ok" : "no");
      $(".fb-verdict", box).textContent = ok ? "Верно!" : "Пока неверно.";
      $(".fb-answer", box).hidden = false;
      $(".feedback", box).hidden = false;
      st.textContent = ok ? "✓ верно" : "✗ неверно";
      $$("input, select", box).forEach(function (i) { i.disabled = true; });
      $$(".mv", box).forEach(function (b) { b.disabled = true; });
      $(".check", box).hidden = true;
      $(".retry", box).hidden = false;
      store.set("task:" + t.id, ok ? "ok" : "no");
      paintScore();
      renderMath($(".feedback", box));
    });
    $(".retry", box).addEventListener("click", function () { resetTask(box); var f = $("input, select, .order-item .mv", box); if (f) f.focus(); });
  });
  paintScore();
  var rt = $(".reset-tasks");
  if (rt) rt.addEventListener("click", function () {
    Object.keys(TASKS).forEach(function (id) { store.del("task:" + id); });
    $$(".task").forEach(resetTask); paintScore();
  });

  /* ---------- decision cases */
  $$(".case").forEach(function (c) {
    var ans = +c.dataset.answer;
    $$(".case-opt", c).forEach(function (b) {
      b.addEventListener("click", function () {
        var i = +b.dataset.i;
        $$(".case-opt", c).forEach(function (x) { x.classList.remove("is-right", "is-wrong"); });
        b.classList.add(i === ans ? "is-right" : "is-wrong");
        $$(".case-opt", c)[ans].classList.add("is-right");
        var fb = $(".case-fb", c); fb.hidden = false;
        $(".case-verdict", c).textContent = i === ans ? "Верно." : "Неверно. Верный вывод: «" + $$(".case-opt", c)[ans].textContent + "».";
      });
    });
  });

  /* ---------- animation player */
  $$(".anim").forEach(function (a) {
    var imgs = $$(".anim-stage img", a), range = $("input[type=range]", a), cnt = $(".anim-count", a), cap = $(".anim-cap", a), play = $(".play", a);
    var caps = []; try { caps = JSON.parse($(".anim-caps", a).textContent); } catch (e) {}
    var k = 0, timer = null;
    function show(i) {
      k = i; imgs.forEach(function (im, j) { im.hidden = j !== i; });
      range.value = i; cnt.textContent = (i + 1) + " / " + imgs.length; cap.textContent = caps[i] || "";
    }
    range.addEventListener("input", function () { stop(); show(+range.value); });
    function stop() { if (timer) { clearInterval(timer); timer = null; play.textContent = "▶"; play.setAttribute("aria-label", "Воспроизвести"); } }
    play.addEventListener("click", function () {
      if (timer) return stop();
      play.textContent = "❚❚"; play.setAttribute("aria-label", "Пауза");
      if (k >= imgs.length - 1) show(0);
      timer = setInterval(function () { if (k >= imgs.length - 1) return stop(); show(k + 1); }, reduceMotion ? 2500 : 1400);
    });
    show(0);
  });

  /* ---------- flashcards */
  var CARDS = window.KMD_CARDS;
  if (CARDS && $(".deck")) {
    var filter = "all", pos = 0, list = [];
    var front = $(".card-front"), back = $(".card-back"), stepEl = $(".card-step"), src = $(".card-src");
    var bFlip = $(".flip"), bKnow = $(".know"), bRep = $(".repeat");
    function mark(c) { return store.get("card:" + c.id, null); }
    function rebuild() {
      list = CARDS.filter(function (c) { var m = mark(c); return filter === "all" || (filter === "repeat" && m === "repeat") || (filter === "new" && !m); });
      var nRep = CARDS.filter(function (c) { return mark(c) === "repeat"; }).length;
      var nNew = CARDS.filter(function (c) { return !mark(c); }).length;
      $(".n-all").textContent = "(" + CARDS.length + ")"; $(".n-repeat").textContent = "(" + nRep + ")"; $(".n-new").textContent = "(" + nNew + ")";
      if (pos >= list.length) pos = 0;
      showCard();
    }
    function showCard() {
      var empty = !list.length;
      $(".deck-empty").hidden = !empty; $(".card").hidden = empty; $(".card-actions").hidden = empty;
      if (empty) { $(".deck-pos").textContent = ""; return; }
      var c = list[pos];
      front.textContent = c.front; $("p", back).textContent = c.back;
      stepEl.textContent = "Шаг " + c.step_index + ". " + c.step_title + (mark(c) ? " · отмечено: " + (mark(c) === "know" ? "знаю" : "повторить") : "");
      src.innerHTML = ""; var a = document.createElement("a"); a.href = c.url; a.textContent = "Открыть шаг" + (c.page ? " (стр. " + c.page + ")" : ""); src.appendChild(a);
      back.hidden = true; bFlip.hidden = false; bKnow.hidden = true; bRep.hidden = true;
      $(".deck-pos").textContent = "Карточка " + (pos + 1) + " из " + list.length;
    }
    function flip() { back.hidden = false; bFlip.hidden = true; bKnow.hidden = false; bRep.hidden = false; bKnow.focus(); }
    function markCur(v) {
      var c = list[pos]; store.set("card:" + c.id, v);
      var before = list.length; list = list.filter(function () { return true; });
      pos = pos + 1; rebuild();
    }
    bFlip.addEventListener("click", flip);
    bKnow.addEventListener("click", function () { markCur("know"); });
    bRep.addEventListener("click", function () { markCur("repeat"); });
    document.addEventListener("keydown", function (e) {
      if (e.target.closest("input, select, textarea")) return;
      if (e.key === " " && !bFlip.hidden && document.activeElement && !document.activeElement.closest("button, a")) { e.preventDefault(); flip(); }
      else if (e.key === "1" && !bKnow.hidden) markCur("know");
      else if (e.key === "2" && !bRep.hidden) markCur("repeat");
    });
    $$(".deck-filter .btn").forEach(function (b) {
      b.addEventListener("click", function () {
        filter = b.dataset.filter; pos = 0;
        $$(".deck-filter .btn").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        rebuild();
      });
    });
    rebuild();
  }

  /* ---------- print */
  var pr = $(".print"); if (pr) pr.addEventListener("click", function () { window.print(); });

  /* ---------- math */
  function renderMath(el) {
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(el || document.body, {
          delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }],
          throwOnError: false, strict: "ignore", ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option", "select"]
        });
      } catch (e) {}
    }
  }
  renderMath($("main") || document.body);
})();

/* AgentGuard web app. Plain JS, no build step (decision D9). Everything shown comes from the API;
   agent-written text is always rendered as text, never as HTML (it is untrusted). */
(function () {
  "use strict";
  var TOKEN = null, scenarios = [], grid = null, rows = [], filter = "all", lastReceipt = null, proofData = null, proofSet = "v3";
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function toast(msg) { var t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.hidden = true; }, 3800); }

  function api(path, opts) {
    opts = opts || {};
    var headers = { "Content-Type": "application/json" };
    if (TOKEN) headers.Authorization = "Bearer " + TOKEN;
    return fetch(path, { method: opts.method || "GET", headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error((j.error && j.error.message) || ("Request failed (" + r.status + ")")); e.body = j; throw e; }
        return j;
      });
    });
  }

  /* ------------------------------------------------------------ mode (light / dark) */
  function currentMode() { var m = document.documentElement.dataset.mode; if (m) return m;
    return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"; }
  $("modeBtn").addEventListener("click", function () {
    var next = currentMode() === "dark" ? "light" : "dark";
    document.documentElement.dataset.mode = next;
    try { localStorage.setItem("ag-mode", next); } catch (e) {}
  });

  /* ------------------------------------------------------------ rain: ambient + one coin per real decision */
  var rain = $("rain"), reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function ambient() {
    if (reduce) return;
    var seed = 7; function rnd() { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; }
    for (var i = 0; i < 34; i++) {
      var s = document.createElement("span"); s.textContent = "$";
      s.style.left = (rnd() * 100).toFixed(2) + "%"; s.style.fontSize = (12 + Math.floor(rnd() * 18)) + "px";
      s.style.opacity = (0.05 + rnd() * 0.09).toFixed(2);
      s.style.animationDuration = (18 + rnd() * 18).toFixed(1) + "s"; s.style.animationDelay = (-rnd() * 34).toFixed(1) + "s";
      rain.appendChild(s);
    }
  }
  function coin(kind) {
    if (reduce || !kind) return;
    var s = document.createElement("span"); s.textContent = "$"; s.className = "live " + kind;
    s.style.left = (20 + Math.random() * 60).toFixed(1) + "%"; s.style.fontSize = "30px"; s.style.opacity = "0.8";
    s.style.animationDuration = kind === "approve" ? "5s" : "3.2s";
    rain.appendChild(s); setTimeout(function () { s.remove(); }, 9000);
  }
  document.addEventListener("visibilitychange", function () { rain.classList.toggle("paused", document.hidden); });

  /* ------------------------------------------------------------ status vocabulary */
  var STATUS = {
    captured: ["approve", "Captured"], held: ["hold", "Held, waiting"], awaiting_buyer: ["ask", "Asked first"],
    blocked: ["block", "Blocked"], declined: ["block", "Declined by PayPal"], voided: ["neutral", "Voided, $0 fee"],
    rejected: ["neutral", "Rejected, never charged"], unknown: ["hold", "Checking with PayPal"], deciding: ["neutral", "Deciding"]
  };
  function statusChip(st) { var s = STATUS[st] || ["neutral", st]; return '<span class="status ' + s[0] + '">' + esc(s[1]) + "</span>"; }
  function coinKind(st) { return { captured: "approve", held: "hold", awaiting_buyer: "hold", blocked: "block", declined: "block" }[st]; }
  function needsBuyer(p) { return p.status === "held" || p.status === "awaiting_buyer"; }

  /* ------------------------------------------------------------ router */
  var ROUTES = ["run", "inbox", "console", "setup", "proof"];
  function route() {
    var r = (location.hash || "#run").slice(1); if (ROUTES.indexOf(r) < 0) r = "run";
    document.querySelectorAll("[data-view]").forEach(function (v) { v.hidden = v.dataset.view !== r; });
    document.querySelectorAll(".nav a").forEach(function (a) {
      if (a.dataset.route === r) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    if (r === "inbox") loadInbox();
    if (r === "console") loadConsole();
    if (r === "setup") loadRules();
    if (r === "proof") loadProof();
  }
  window.addEventListener("hashchange", function () { route(); $("main").focus({ preventScroll: true }); });

  /* ------------------------------------------------------------ health badges */
  function loadHealth() {
    return api("/healthz").then(function (h) {
      var pb = $("paypalBadge"); pb.textContent = h.paypal.indexOf("FakePayPal") === 0 ? "FakePayPal (simulated)" : "PayPal sandbox";
      pb.classList.toggle("warn", h.paypal.indexOf("FakePayPal") === 0);
      pb.title = h.paypal;
      $("aiBadge").textContent = "AI: " + h.ai;
      $("aiBadge").title = "Market prices: " + (h.market || "off");
    }).catch(function () { $("paypalBadge").textContent = "Server unreachable"; $("paypalBadge").classList.add("warn"); });
  }

  /* ------------------------------------------------------------ shop and agent */
  var LAYERS = [
    ["catalogue", "Shop records", "Items and prices taken from the shop’s own records, not from the agent"],
    ["market", "Market price", ""],
    ["rules", "Buyer’s rules", "Inside every rule the buyer set"],
    ["detector", "Page check", "Nothing on the page talks to AI agents"],
    ["ai", "AI intent check", "Matches what the buyer asked for"]
  ];
  var LAYER_NAMES = { catalogue: "Shop records", market: "Market price (Channel3)", rules: "Buyer’s rules", detector: "Page check", ai: "AI intent check" };
  var MARK = { approve: ["ok", "✓"], hold: ["hold", "‖"], ask_first: ["ask", "?"], block: ["block", "✕"] };
  var RANK = { approve: 0, hold: 1, ask_first: 2, block: 3 };

  var catalogueBySku = {}, catalogueByTitle = {};
  function productImage(title) { var p = catalogueByTitle[title]; return p && p.image; }
  function loadCatalogue() {
    return api("/api/catalogue").then(function (c) {
      c.products.forEach(function (p) { catalogueBySku[p.sku] = p; catalogueByTitle[p.title] = p; });
      var src = $("dataSource"); if (src) src.textContent = c.merchant + ". Products: " + c.source + ".";
    }).catch(function () {});
  }

  function renderScenarios() {
    var box = $("scenarios"); box.innerHTML = "";
    scenarios.forEach(function (s) {
      var b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = s.label;
      b.setAttribute("aria-pressed", "false"); b.dataset.id = s.id; b.title = "Expected: " + s.expect;
      b.addEventListener("click", function () { run({ scenario: s.id }, b); });
      box.appendChild(b);
    });
  }

  function showPage(pg) {
    var text = pg.text || "", hidden = null;
    var m = text.match(/<span[^>]*display\s*:\s*none[^>]*>([\s\S]*?)<\/span>/i);
    if (m) { hidden = m[1]; text = text.replace(m[0], ""); }
    $("pageText").textContent = text.replace(/<[^>]+>/g, "").trim() || "(empty page)";
    var h = $("hiddenText"); h.hidden = !hidden; if (hidden) h.textContent = "Hidden on the page: “" + hidden.trim() + "”";
  }

  function pendingTrace() {
    $("trace").innerHTML = LAYERS.map(function (L) {
      return '<li><span class="mark wait" aria-label="checking"></span><div><div class="step-layer">' + L[1] +
        '</div><div class="step-text">Checking</div></div><span class="step-ms"></span></li>'; }).join("");
    $("outcome").hidden = true; $("traceHint").textContent = "Checking now";
  }

  function marketStep(p, t) {
    if (!t) return "";
    var c = (t.checks || [])[0], ms = t.ms < 1 ? "under 1 ms" : Math.round(t.ms).toLocaleString() + " ms", text, extra = "";
    if (c && c.live) {
      text = "Usually " + money(c.median_cents) + " across " + c.offers + " shop" + (c.offers === 1 ? "" : "s") +
        " (from " + money(c.low_cents) + " to " + money(c.high_cents) + ")";
      extra = '<div class="ai-line">Channel3 product catalogue' + (c.cached ? ", checked in the last 15 minutes" : ", checked now") + "</div>";
      if (c.cached) ms = "cached";
    } else { text = "Channel3 didn’t answer in time, so AgentGuard used the shop’s stored reference price"; }
    return '<li><span class="mark ok" aria-label="checked">✓</span><div><div class="step-layer">Market price</div><div class="step-text">' +
      esc(text) + "</div>" + extra + '</div><span class="step-ms num">' + esc(ms) + "</span></li>";
  }

  function stepFor(p, L) {
    var t = (p.trace || []).filter(function (x) { return x.layer === L[0]; })[0];
    if (L[0] === "market") return marketStep(p, t);
    var fs = (p.findings || []).filter(function (f) { return (f.source || "rules") === L[0]; });
    fs.sort(function (a, b) { return RANK[b.level] - RANK[a.level]; });
    var level = fs.length ? fs[0].level : "approve", text = fs.length ? fs[0].reason : L[2];
    var ms = t ? (t.ms < 1 ? "under 1 ms" : Math.round(t.ms).toLocaleString() + " ms") : "";
    var extra = "";
    if (L[0] === "ai") {
      var ai = p.ai || {};
      if (t && t.skipped) { text = "Not needed: the rules already blocked this."; level = "approve"; ms = ""; }
      else if (!t) { text = "AI layer is off on this server."; ms = ""; }
      else if (ai.model) {
        var rec = ai.provider && ai.provider.indexOf("recorded") === 0;
        ms = Math.round(ai.latency_ms).toLocaleString() + " ms";
        extra = '<div class="ai-line">' + esc(ai.model) + (rec ? ", answer " + esc(ai.provider) + " (replayed; time measured when recorded)" : ", live") + "</div>";
      }
    }
    if (fs.length > 1) text += " (+" + (fs.length - 1) + " more)";
    var mk = MARK[level];
    return '<li><span class="mark ' + mk[0] + '" aria-label="' + esc(level.replace("_", " ")) + '">' + mk[1] + '</span><div><div class="step-layer">' +
      L[1] + '</div><div class="step-text">' + esc(text) + "</div>" + extra + '</div><span class="step-ms num">' + esc(ms) + "</span></li>";
  }

  var OUTCOME = {
    captured: ["approve", "Approved and captured", function (p) { return "PayPal order " + (p.paypal_order_id || "") + ". Receipt signed."; }],
    held: ["hold", "Held on PayPal, waiting for Thandi", function () { return "Authorised, not taken. If she says no, the hold is voided at no fee."; }],
    awaiting_buyer: ["ask", "Asked Thandi first", function () { return "PayPal has not been called. Nothing has touched her card."; }],
    blocked: ["block", "Blocked before PayPal was called", function () { return "Nothing touched her card."; }],
    declined: ["block", "PayPal declined the card", function (p) { return "PayPal status " + (p.paypal_status || "") + ". Nothing was charged."; }],
    voided: ["approve", "Hold voided at no fee", function () { return "PayPal released the authorisation."; }],
    rejected: ["approve", "Rejected, never charged", function () { return "PayPal was never called."; }],
    unknown: ["hold", "Waiting to confirm with PayPal", function () { return "The budget stays reserved until PayPal confirms."; }]
  };

  function renderDecision(p) {
    var lis = LAYERS.map(function (L) { return stepFor(p, L); });
    var ol = $("trace"); ol.innerHTML = "";
    lis.forEach(function (html, i) { setTimeout(function () { ol.insertAdjacentHTML("beforeend", html); }, reduce ? 0 : i * 140); });
    setTimeout(function () {
      var o = OUTCOME[p.status] || ["hold", p.status, function () { return ""; }];
      var box = $("outcome"); box.className = "outcome " + o[0]; box.hidden = false;
      $("outcomeTitle").textContent = o[1]; $("outcomeSub").textContent = o[2](p);
      var total = (p.trace || []).reduce(function (a, x) { return a + (x.ms || 0); }, 0);
      $("traceHint").textContent = "Guard time " + (total < 1 ? "under 1 ms" : Math.round(total).toLocaleString() + " ms");
      coin(coinKind(p.status));
    }, reduce ? 0 : LAYERS.length * 140 + 80);
    var items = ((p.facts || {}).items || []).map(function (i) { return i.quantity + " × " + i.title; }).join(", ");
    $("cartLine").textContent = items ? "The agent chose " + items + " and asked AgentGuard to pay." : "The agent’s cart had nothing the shop sells.";
    renderPhone(p, $("phone"));
    refreshCount();
  }

  function phoneHTML(p) {
    var f = p.facts || {}, items = f.items || [];
    var title = { held: "Is this what you meant?", awaiting_buyer: "Check this before anything is charged",
      captured: "Paid", blocked: "We stopped a payment", voided: "Hold released", rejected: "Payment cancelled",
      declined: "Your card was declined" }[p.status] || "Payment update";
    var rowsH = "";
    items.forEach(function (i) {
      rowsH += "<dt>Item</dt><dd>" + esc(i.quantity + " × " + i.title) + "</dd><dt>Price</dt><dd class=\"num\">" + esc(i.price) + "</dd>";
      if (i.usual_price && i.usual_price !== i.price) rowsH += "<dt>Usually</dt><dd class=\"num\">" + esc(i.usual_price) +
        (i.usual_price_source ? '<div class="hint" style="font-weight:400">' + esc(i.usual_price_source) + "</div>" : "") + "</dd>";
    });
    if (f.shop) rowsH += "<dt>Shop</dt><dd>" + esc(f.shop) + "</dd>";
    if (f.total) rowsH += "<dt>Total</dt><dd class=\"num\">" + esc(f.total) + "</dd>";
    if (f.budget_left) rowsH += "<dt>Budget before this</dt><dd class=\"num\">" + esc(f.budget_left) + "</dd>";
    var why = (p.findings || []).filter(function (x) { return x.level !== "approve"; })[0];
    var h = '<span class="hint">AgentGuard, for Thandi</span><h3>' + esc(title) + "</h3>";
    var img = productImage(items[0] && items[0].title);
    if (img) h += '<img class="product-img" src="' + esc(img) + '" alt="' + esc(items[0].title) + '" loading="lazy">';
    if (rowsH) h += '<dl class="facts well">' + rowsH + "</dl>";
    if (why) h += '<p class="hint">Why: ' + esc(why.reason) + "</p>";
    h += '<p class="hint">Every fact above was checked by AgentGuard.</p>';
    if (p.agent_note) h += '<blockquote class="agent-says">The agent says, unverified: “' + esc(p.agent_note) + "”</blockquote>";
    if (needsBuyer(p)) {
      h += '<div class="actions"><button class="btn primary" type="button" data-act="approve" data-id="' + esc(p.id) + '">Yes, pay ' + esc(f.total || "") + "</button>" +
        '<button class="btn" type="button" data-act="reject" data-id="' + esc(p.id) + '">' + (p.status === "held" ? "No, release the hold" : "No, cancel it") + "</button></div>" +
        '<p class="hint">' + (p.status === "held" ? "Yes takes the held money on PayPal. No voids the hold at no fee." : "Nothing has touched your card yet.") + "</p>";
    }
    return h;
  }
  function renderPhone(p, el) { el.innerHTML = phoneHTML(p); }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-act]"); if (!b) return;
    answer(b.dataset.id, b.dataset.act, b);
  });
  function answer(id, act, btn) {
    if (btn) btn.setAttribute("aria-busy", "true");
    return api("/api/payments/" + encodeURIComponent(id) + "/" + act, { method: "POST" }).then(function (p) {
      toast(act === "approve" ? (p.status === "captured" ? "Paid. PayPal captured the payment." : "PayPal says: " + p.status)
        : (p.status === "voided" ? "Hold voided. No fee." : "Cancelled. Nothing was charged."));
      coin(coinKind(p.status) || (act === "reject" ? null : "approve"));
      if (!$("view-run").hidden) { renderPhone(p, $("phone")); var o = OUTCOME[p.status];
        if (o) { $("outcome").className = "outcome " + o[0]; $("outcomeTitle").textContent = o[1]; $("outcomeSub").textContent = o[2](p); } }
      if (!$("view-inbox").hidden) loadInbox();
      if (!$("view-console").hidden) loadConsole();
      refreshCount();
    }).catch(function (err) { toast(err.message); if (btn) btn.removeAttribute("aria-busy"); });
  }

  function run(body, btn) {
    document.querySelectorAll("#scenarios .chip").forEach(function (c) { c.setAttribute("aria-pressed", c === btn ? "true" : "false"); c.disabled = true; });
    pendingTrace(); $("cartLine").textContent = "The agent is shopping.";
    return api("/api/demo/run", { method: "POST", body: body }).then(function (r) {
      showPage(r.page); renderDecision(r.payment);
    }).catch(function (err) {
      $("trace").innerHTML = ""; $("outcome").hidden = true; $("traceHint").textContent = "Something went wrong";
      $("cartLine").innerHTML = '<span class="error-box" style="display:block">' + esc(err.message) + " Try again, or reset the demo in the console.</span>";
    }).finally(function () { document.querySelectorAll("#scenarios .chip").forEach(function (c) { c.disabled = false; }); });
  }

  $("pasteRun").addEventListener("click", function () {
    var text = $("pasteText").value.trim(); if (!text) { toast("Paste some page text first."); return; }
    var b = $("pasteRun"); b.setAttribute("aria-busy", "true");
    api("/api/pages", { method: "POST", body: { text: text, title: "Your pasted page" } }).then(function (pg) {
      return run({ page_id: pg.id }, null);
    }).catch(function (err) { toast(err.message); }).finally(function () { b.removeAttribute("aria-busy"); });
  });

  function refreshCount() {
    return api("/api/payments").then(function (ps) {
      var n = ps.filter(needsBuyer).length, c = $("inboxCount"); c.hidden = n === 0; c.textContent = n;
      c.setAttribute("aria-label", n + " waiting"); rows = ps; return ps;
    }).catch(function () { return []; });
  }

  /* ------------------------------------------------------------ approvals */
  function loadInbox() {
    var box = $("inboxList"); box.innerHTML = '<span class="skeleton" style="width:40%"></span>';
    refreshCount().then(function (ps) {
      var waiting = ps.filter(needsBuyer);
      if (!waiting.length) { box.innerHTML = '<div class="panel empty"><strong style="color:var(--ink)">Nothing is waiting for you.</strong>' +
        '<span>Payments the agent can’t make on its own land here.</span><a class="btn" href="#run">Send the agent shopping</a></div>'; return; }
      box.innerHTML = ""; waiting.forEach(function (p) { var d = document.createElement("div"); d.className = "phone"; d.innerHTML = phoneHTML(p); box.appendChild(d); });
    });
  }

  /* ------------------------------------------------------------ console (AG Grid) */
  function firstReason(p) { var f = (p.findings || []).filter(function (x) { return x.level !== "approve"; });
    f.sort(function (a, b) { return RANK[b.level] - RANK[a.level]; }); return f.length ? f[0].reason : "Inside the buyer’s rules"; }
  function itemsOf(p) { return ((p.facts || {}).items || []).map(function (i) { return i.title; }).join(", ") || "Nothing the shop sells"; }
  function aiOf(p) { var a = p.ai || {}; if (!a.model) return (p.trace || []).some(function (t) { return t.skipped; }) ? "Not needed" : "Unavailable";
    return a.model + ", " + Math.round(a.latency_ms) + " ms" + (a.provider && a.provider.indexOf("recorded") === 0 ? " (recorded)" : ""); }

  var STATUS_GROUPS = { needs: ["held", "awaiting_buyer"], blocked: ["blocked", "declined"], captured: ["captured"], voided: ["voided", "rejected"] };

  function initGrid() {
    var StatusCell = function () {};
    StatusCell.prototype.init = function (params) { this.e = document.createElement("span"); this.e.innerHTML = statusChip(params.value); };
    StatusCell.prototype.getGui = function () { return this.e; };
    var ActCell = function () {};
    ActCell.prototype.init = function (params) {
      this.e = document.createElement("span"); this.e.style.display = "inline-flex"; this.e.style.gap = "6px";
      if (needsBuyer(params.data)) {
        this.e.innerHTML = '<button class="btn small primary" type="button" data-act="approve" data-id="' + esc(params.data.id) + '">Approve</button>' +
          '<button class="btn small" type="button" data-act="reject" data-id="' + esc(params.data.id) + '">Reject</button>';
      } else { this.e.innerHTML = '<span class="hint">No action</span>'; }
    };
    ActCell.prototype.getGui = function () { return this.e; };
    var opts = {
      rowData: [], getRowId: function (p) { return p.data.id; },
      columnDefs: [
        { headerName: "Time", field: "created_at", width: 110, sort: "desc", valueFormatter: function (p) { return (p.value || "").slice(11, 19); } },
        { headerName: "Status", field: "status", width: 190, cellRenderer: StatusCell, filter: true },
        { headerName: "Buyer", cellRenderer: ActCell, width: 190, sortable: false },
        { headerName: "Item", valueGetter: function (p) { return itemsOf(p.data); }, flex: 1.2, minWidth: 180 },
        { headerName: "Total", field: "amount", width: 110, type: "rightAligned", cellClass: "num" },
        { headerName: "Why", valueGetter: function (p) { return firstReason(p.data); }, flex: 2, minWidth: 240, tooltipValueGetter: function (p) { return firstReason(p.data); } },
        { headerName: "AI check", valueGetter: function (p) { return aiOf(p.data); }, width: 240 },
        { headerName: "PayPal called", valueGetter: function (p) { return p.data.paypal_called ? "Yes" : "No"; }, width: 130 },
        { headerName: "PayPal order", field: "paypal_order_id", width: 200 }
      ],
      defaultColDef: { sortable: true, resizable: true },
      rowSelection: { mode: "singleRow", checkboxes: false, enableClickSelection: true }, animateRows: false, suppressCellFocus: false,
      isExternalFilterPresent: function () { return filter !== "all"; },
      doesExternalFilterPass: function (n) { return STATUS_GROUPS[filter].indexOf(n.data.status) >= 0; },
      onSelectionChanged: function () { var s = grid.getSelectedRows()[0]; if (s) showDetail(s.id); },
      overlayNoRowsTemplate: '<span style="padding:16px">No payments yet. Run a scenario on the Shop and agent page.</span>'
    };
    grid = agGrid.createGrid($("grid"), opts);
  }
  function loadConsole() {
    if (!grid) initGrid();
    refreshCount().then(function (ps) { grid.setGridOption("rowData", ps); });
  }
  $("filters").addEventListener("click", function (e) {
    var b = e.target.closest("[data-filter]"); if (!b) return; filter = b.dataset.filter;
    document.querySelectorAll("#filters .chip").forEach(function (c) { c.setAttribute("aria-pressed", c === b ? "true" : "false"); });
    if (grid) grid.onFilterChanged();
  });
  $("quick").addEventListener("input", function () { if (grid) grid.setGridOption("quickFilterText", this.value); });
  $("resetDemo").addEventListener("click", function () {
    api("/api/demo/reset", { method: "POST" }).then(function () { toast("Demo reset. Fresh budget and an empty log."); loadConsole();
      $("detailBody").innerHTML = '<span class="hint">Select a payment to see its full record.</span>'; });
  });

  function showDetail(id) {
    var body = $("detailBody"); body.innerHTML = '<span class="skeleton" style="display:block;width:60%"></span>';
    api("/api/payments/" + encodeURIComponent(id)).then(function (p) {
      var h = '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' + statusChip(p.status) + '<span class="num" style="font-weight:600">' + esc(p.amount) + "</span></div>";
      h += '<h3 class="sub">Reasons</h3><ul class="check-list">';
      var fs = p.findings || [];
      if (!fs.length) h += "<li>Inside every rule the buyer set.</li>";
      fs.forEach(function (f) { h += "<li>" + statusChip({ approve: "captured", hold: "held", ask_first: "awaiting_buyer", block: "blocked" }[f.level]) + " " +
        esc(f.reason) + (f.would_pass_if ? '<div class="hint">Would pass if ' + esc(f.would_pass_if) + "</div>" : "") +
        '<div class="hint">Found by: ' + esc(f.source || "rules") + "</div></li>"; });
      h += "</ul>";
      h += '<h3 class="sub">Timing</h3><dl class="facts">';
      (p.trace || []).forEach(function (t) { h += "<dt>" + esc(LAYER_NAMES[t.layer] || t.layer) + '</dt><dd class="num">' + (t.skipped ? "skipped" : esc(t.ms) + " ms") + "</dd>"; });
      if (p.ai && p.ai.model) h += "<dt>AI model</dt><dd>" + esc(p.ai.model) + (p.ai.provider && p.ai.provider.indexOf("recorded") === 0 ? " (" + esc(p.ai.provider) + ")" : "") + "</dd>";
      h += '</dl><h3 class="sub">PayPal</h3><dl class="facts">' +
        "<dt>Called</dt><dd>" + (p.paypal_called ? "Yes" : "No") + "</dd><dt>Order</dt><dd>" + esc(p.paypal_order_id || "none") + "</dd>" +
        "<dt>Authorisation</dt><dd>" + esc(p.paypal_authorization_id || "none") + "</dd><dt>Capture</dt><dd>" + esc(p.paypal_capture_id || "none") + "</dd>" +
        "<dt>Status</dt><dd>" + esc(p.paypal_status || "none") + "</dd></dl>";
      h += '<h3 class="sub">Signed log entries</h3><ul class="check-list">';
      (p.audit || []).forEach(function (a) { h += '<li class="num">#' + a.seq + " " + esc(a.kind) + ' <span class="hint">' + esc(a.hash.slice(0, 16)) + "…</span></li>"; });
      h += "</ul>";
      if (p.agent_note) h += '<blockquote class="agent-says">The agent says, unverified: “' + esc(p.agent_note) + "”</blockquote>";
      h += '<button class="btn primary" type="button" id="getReceipt">Get receipt</button>';
      body.innerHTML = h;
      $("getReceipt").addEventListener("click", function () {
        api("/api/payments/" + encodeURIComponent(id) + "/receipt").then(function (doc) {
          lastReceipt = doc; $("receiptText").value = JSON.stringify(doc, null, 2); location.hash = "#proof";
          toast("Receipt loaded on the Proof page.");
        }).catch(function (err) { toast(err.message); });
      });
    }).catch(function (err) { body.innerHTML = '<div class="error-box">' + esc(err.message) + "</div>"; });
  }

  /* ------------------------------------------------------------ your rules */
  var current = null;
  function money(c) { return "$" + (c / 100).toFixed(2); }
  function loadRules() {
    api("/api/mandates").then(function (ms) {
      var m = ms.filter(function (x) { return x.mandate.mandate_id === "thandi-earbuds"; })[0] || ms[0];
      if (!m) { $("activeRules").innerHTML = '<div class="empty">No rules yet. Draft some on the left.</div>'; return; }
      current = m.mandate; var b = m.budget || {}, md = m.mandate;
      $("activeRules").innerHTML = '<p style="font-size:17px">“' + esc(md.buyer_instruction) + '”</p><dl class="facts well">' +
        "<dt>Version</dt><dd>" + md.version + '</dd><dt>Budget</dt><dd class="num">' + money(md.budget_total_cents) +
        '</dd><dt>Spent or held</dt><dd class="num">' + money((b.spent_cents || 0) + (b.reserved_cents || 0)) +
        '</dd><dt>Per item, up to</dt><dd class="num">' + money(md.max_item_price_cents) + "</dd><dt>How many of each</dt><dd>" + md.max_quantity_per_item +
        "</dd><dt>Kinds of item</dt><dd>" + esc(md.allowed_categories.join(", ").replace(/_/g, " ")) + "</dd><dt>Shops</dt><dd>" + esc(md.allowed_merchants.join(", ")) +
        "</dd><dt>Valid until</dt><dd>" + esc(md.expires_at.slice(0, 10)) + "</dd></dl>" +
        '<p class="hint">Fingerprint <span class="num">' + esc(m.fingerprint.slice(0, 20)) + "…</span> goes into every PayPal order, so the rules can’t be changed after the fact.</p>";
    }).catch(function (err) { $("activeRules").innerHTML = '<div class="error-box">' + esc(err.message) + "</div>"; });
  }
  $("draftBtn").addEventListener("click", function () {
    var b = this, out = $("draftOut"); b.setAttribute("aria-busy", "true");
    out.innerHTML = '<p class="hint">The AI is reading your words.</p>';
    api("/api/mandates/draft", { method: "POST", body: { instruction: $("instruction").value } }).then(function (r) {
      var d = r.draft, h = "";
      if (!d) { out.innerHTML = '<div class="error-box">' + esc((r.clarifications || []).join(" ") || "The AI could not turn that into rules.") + "</div>"; return; }
      h += '<p class="hint">Drafted by ' + esc(r.ai.model) + " in " + Math.round(r.ai.latency_ms).toLocaleString() + " ms. Not active yet.</p>";
      h += '<dl class="facts well"><dt>Budget</dt><dd class="num">' + money(d.budget_total_cents) + '</dd><dt>Per item, up to</dt><dd class="num">' +
        money(d.max_item_price_cents) + "</dd><dt>How many of each</dt><dd>" + d.max_quantity_per_item + "</dd><dt>Kinds of item</dt><dd>" +
        esc(d.allowed_categories.join(", ").replace(/_/g, " ")) + "</dd><dt>Shops</dt><dd>" + esc(d.allowed_merchants.join(", ")) + "</dd><dt>Valid until</dt><dd>" +
        esc(d.expires_at.slice(0, 10)) + "</dd></dl>";
      (r.clarifications || []).forEach(function (q) { h += '<p class="hint">The AI asks: ' + esc(q) + "</p>"; });
      h += '<button class="btn primary" type="button" id="approveRules">Approve these rules</button>';
      out.innerHTML = h;
      $("approveRules").addEventListener("click", function () {
        if (!current) { toast("No current rules to replace."); return; }
        var next = Object.assign({}, current, { version: current.version + 1, buyer_instruction: d.buyer_instruction,
          budget_total_cents: d.budget_total_cents, max_item_price_cents: d.max_item_price_cents, max_quantity_per_item: d.max_quantity_per_item,
          allowed_categories: d.allowed_categories, allowed_merchants: d.allowed_merchants, expires_at: d.expires_at });
        api("/api/mandates", { method: "POST", body: { mandate: next } }).then(function () {
          toast("New rules are in force. The agent uses them from its next purchase."); out.innerHTML = ""; loadRules();
        }).catch(function (err) { toast(err.message); });
      });
    }).catch(function (err) {
      out.innerHTML = '<div class="error-box">' + esc(err.message) + " Your current rules stay in force.</div>";
    }).finally(function () { b.removeAttribute("aria-busy"); });
  });

  /* ------------------------------------------------------------ proof */
  function pct(x) { return x == null ? "n/a" : (x * 100).toFixed(1) + "%"; }
  function loadProof() {
    if (lastReceipt && !$("receiptText").value) $("receiptText").value = JSON.stringify(lastReceipt, null, 2);
    api("/api/receipts/public-key").then(function (k) { $("keyLine").textContent = "Signing key " + k.key_id + (k.ephemeral ? " (made at start-up; demo only)" : "") + ", Ed25519."; });
    if (proofData) { drawProof(); return; }
    api("/api/proof").then(function (d) { proofData = d; drawProof(); })
      .catch(function (err) { $("figures").innerHTML = '<div class="error-box">' + esc(err.message) + "</div>"; });
  }
  function drawProof() {
    var sets = proofData.sets, v3 = sets.filter(function (s) { return s.set === "v3"; })[0] || sets[0], fee = proofData.fees;
    if (v3) {
      var r = v3.configs.rules_only, a = v3.configs["rules+detector+ai"];
      $("figures").innerHTML =
        '<div><span class="fig">' + r.caught + " → " + a.caught + "<small> of " + a.attacks + "</small></span><p>in-limit attacks caught, rules alone versus rules with AI (test set " + esc(v3.set) + ")</p></div>" +
        '<div><span class="fig">' + a.false_blocks + "<small> of " + a.benign + "</small></span><p>good purchases wrongly blocked on the same set</p></div>" +
        '<div><span class="fig">$0.00<small> vs $' + (fee.refund_fee_lost_cents / 100).toFixed(2) + "</small></span><p>cost of saying no to a held $" + (fee.capture_cents / 100).toFixed(0) +
        " payment, versus refunding it after capture, in the PayPal sandbox</p></div>";
    }
    var chips = $("setChips"); chips.innerHTML = "";
    sets.forEach(function (s) { var b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = "Test set " + s.set;
      b.setAttribute("aria-pressed", s.set === proofSet ? "true" : "false"); b.addEventListener("click", function () { proofSet = s.set; drawProof(); }); chips.appendChild(b); });
    var s = sets.filter(function (x) { return x.set === proofSet; })[0]; if (!s) return;
    var names = { "rules_only": "Rules only", "rules+detector": "Rules + page check", "rules+detector+ai": "Rules + page check + AI" };
    $("bars").innerHTML = Object.keys(names).filter(function (k) { return s.configs[k]; }).map(function (k) {
      var c = s.configs[k], w = c.attacks ? c.caught / c.attacks : 0;
      return '<div class="bar-row"><span>' + names[k] + '</span><div class="bar-track" role="img" aria-label="' + c.caught + " of " + c.attacks + ' caught"><div class="bar-fill" style="transform:scaleX(' + w.toFixed(4) + ')"></div></div><span class="val">' +
        c.caught + " / " + c.attacks + "</span></div>"; }).join("");
    var ai = (s.configs["rules+detector+ai"] || {}).ai || {};
    $("barsNote").textContent = "Frozen at commit " + s.frozen_at_commit + ", run " + (s.run_at || "").slice(0, 10) + ", " + (s.synthetic ? "synthetic data" : "real data") +
      ". AI " + (ai.model || "") + ", median " + (ai.latency_ms_p50 || "?") + " ms. Catch with AI " + pct((s.configs["rules+detector+ai"] || {}).catch_rate) + ". Source: " + s.file + ".";
  }
  function verify(doc) {
    return api("/api/receipts/verify", { method: "POST", body: doc }).then(function (r) {
      var c = r.checks || {}, names = { signature: "Signature matches AgentGuard’s public key", mandate_fingerprint: "Rules match their fingerprint", paypal_custom_id: "Fingerprint matches the PayPal order" };
      $("verifyOut").innerHTML = '<p style="font-weight:600;color:var(' + (r.valid ? "--approve" : "--block") + ')">' + (r.valid ? "Valid receipt" : "Not valid") + '</p><ul class="check-list">' +
        Object.keys(names).filter(function (k) { return k in c; }).map(function (k) { return "<li>" + (c[k] ? "✓ " : "✕ ") + names[k] + "</li>"; }).join("") + "</ul>";
    });
  }
  function readReceipt() { try { return JSON.parse($("receiptText").value); } catch (e) { toast("That isn’t valid JSON."); return null; } }
  $("verifyBtn").addEventListener("click", function () { var d = readReceipt(); if (d) verify(d).catch(function (e) { toast(e.message); }); });
  $("tamperBtn").addEventListener("click", function () {
    var d = readReceipt(); if (!d || !d.receipt) return;
    d.receipt.amount_cents = (d.receipt.amount_cents || 0) + 100; $("receiptText").value = JSON.stringify(d, null, 2);
    verify(d).then(function () { toast("Added $1.00 to the amount. The signature no longer matches."); });
  });
  $("chainBtn").addEventListener("click", function () {
    api("/api/audit/verify").then(function (r) {
      $("chainOut").innerHTML = r.ok ? '<p style="font-weight:600;color:var(--approve)">Intact: ' + r.checked + ' entries</p><p class="hint num">Head ' + esc((r.head || "").slice(0, 24)) + "…</p>"
        : '<p style="font-weight:600;color:var(--block)">Broken at entry ' + r.first_bad_seq + "</p>";
    }).catch(function (e) { toast(e.message); });
  });

  /* ------------------------------------------------------------ boot */
  ambient();
  api("/api/demo/session").then(function (s) { TOKEN = s.buyer_token; }).catch(function () {
    TOKEN = null; toast("This server is not in demo mode, so the buyer screens need a token.");
  }).then(function () {
    loadHealth();
    loadCatalogue();
    return api("/api/demo/scenarios").then(function (s) { scenarios = s; renderScenarios(); }).catch(function () { $("scenarios").innerHTML = '<span class="hint">Scenarios are only available in demo mode.</span>'; });
  }).then(function () { route(); refreshCount(); });
})();

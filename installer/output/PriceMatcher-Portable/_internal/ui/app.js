/* Price Matcher - UI layer only. All business logic lives in Python. */
(function () {
  "use strict";

  var PAGE = 300;                 // rows rendered per chunk
  var state = { rows: [], stats: {}, filter: "all", search: "", shown: 0, filtered: [] };

  var $ = function (id) { return document.getElementById(id); };

  function show(view) {
    var views = document.querySelectorAll(".view");
    for (var i = 0; i < views.length; i++) views[i].classList.remove("active");
    $("view-" + view).classList.add("active");
  }

  function api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  function call(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    var bridge = api();
    if (!bridge || typeof bridge[method] !== "function") {
      return Promise.reject(new Error("bridge not ready"));
    }
    return bridge[method].apply(bridge, args);
  }

  /* ------------------------------------------------------------ home */
  function refreshStartButton() {
    var ready = $("pick-pdf").classList.contains("filled") &&
      $("pick-excel").classList.contains("filled") &&
      $("brand-name").value.trim() !== "";
    $("btn-start").disabled = !ready;
  }

  function pick(kind) {
    var method = kind === "pdf" ? "select_pdf" : "select_excel";
    call(method).then(function (res) {
      if (res && res.ok) {
        $(kind + "-name").textContent = res.name;
        $("pick-" + kind).classList.add("filled");
        $("home-error").textContent = "";
      }
      refreshStartButton();
    });
  }

  function start() {
    $("home-error").textContent = "";
    var brand = $("brand-name").value.trim();
    setProgress(0, "شروع...");
    show("processing");
    call("process_files", brand).then(function (res) {
      if (!res || !res.ok) {
        show("home");
        $("home-error").textContent = (res && res.error) || "شروع پردازش ممکن نشد.";
      }
    });
  }

  /* ------------------------------------------------------ processing */
  function setProgress(percent, message) {
    $("progress-bar").style.width = percent + "%";
    $("progress-percent").textContent = percent + "%";
    $("progress-title").textContent = message || "در حال پردازش...";
    var order = ["pdf", "excel", "match", "final"];
    var current = percent < 28 ? 0 : percent < 45 ? 1 : percent < 92 ? 2 : 3;
    order.forEach(function (name, idx) {
      var li = document.querySelector('[data-step="' + name + '"]');
      li.classList.toggle("active", idx === current);
      li.classList.toggle("done", idx < current);
    });
  }

  window.onPyEvent = function (event, data) {
    if (event === "progress") {
      setProgress(data.percent, data.message);
    } else if (event === "done") {
      loadResults();
    } else if (event === "error") {
      show("home");
      $("home-error").textContent = data.message;
    }
  };

  /* --------------------------------------------------------- results */
  function loadResults() {
    call("get_results").then(function (res) {
      if (!res || !res.ok) return;
      state.rows = res.rows || [];
      state.stats = res.stats || {};
      renderSummary();
      applyFilter();
      show("results");
    });
  }

  function renderSummary() {
    var s = state.stats;
    $("result-brand").textContent = s.brand ? "برند: " + s.brand : "";
    var cards = [
      ["", "کل کالاها", s.total || 0],
      ["ok", "قیمت‌گذاری‌شده", s.priced || 0],
      ["warn", "نیاز به بررسی", s.review || 0],
      ["bad", "یافت نشد", s.not_found || 0],
      ["", "زمان پردازش", (s.elapsed || 0) + "s"]
    ];
    $("summary").innerHTML = cards.map(function (c) {
      return '<div class="stat ' + c[0] + '"><b>' + c[2] + "</b><span>" + c[1] + "</span></div>";
    }).join("");
  }

  function matchesFilter(row) {
    var f = state.filter;
    if (f === "priced" && row.price === null) return false;
    if (f === "matched" && !(row.status === "EXACT" || row.status === "HIGH")) return false;
    if (f === "review" && row.status !== "REVIEW") return false;
    if (f === "not_found" && row.status !== "NOT_FOUND") return false;
    if (f === "in_stock" && !(row.stock > 0)) return false;
    if (f === "out_of_stock" && row.stock > 0) return false;
    if (state.search) {
      var haystack = ((row.code || "") + " " + (row.name || "")).toLowerCase();
      if (haystack.indexOf(state.search) === -1) return false;
    }
    return true;
  }

  function applyFilter() {
    state.filtered = state.rows.filter(matchesFilter);
    state.shown = 0;
    $("result-body").innerHTML = "";
    if (!state.filtered.length) {
      $("result-body").innerHTML = '<tr><td colspan="4" class="empty">موردی یافت نشد.</td></tr>';
      $("btn-more").hidden = true;
      return;
    }
    renderChunk();
  }

  function num(value) {
    if (value === null || value === undefined) return "-";
    return Number(value).toLocaleString("en-US");
  }

  function escapeHtml(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderChunk() {
    var end = Math.min(state.shown + PAGE, state.filtered.length);
    var html = [];
    for (var i = state.shown; i < end; i++) {
      var row = state.filtered[i];
      var cls = row.status === "REVIEW" ? "review" : row.status === "NOT_FOUND" ? "not_found" : "";
      html.push(
        "<tr class='" + cls + "'>" +
        "<td>" + escapeHtml(row.code) + "</td>" +
        "<td class='name'>" + escapeHtml(row.name) + "</td>" +
        "<td>" + num(row.stock) + "</td>" +
        "<td class='price'>" + num(row.price) + "</td>" +
        "</tr>"
      );
    }
    $("result-body").insertAdjacentHTML("beforeend", html.join(""));
    state.shown = end;
    $("btn-more").hidden = state.shown >= state.filtered.length;
  }

  /* ---------------------------------------------------------- export */
  function exportFile(kind) {
    var status = $("result-status");
    var onlyPriced = $("only-priced").checked;
    status.textContent = "در حال ساخت فایل خروجی...";
    call(kind === "xlsx" ? "export_excel" : "export_pdf", onlyPriced).then(function (res) {
      status.textContent = res && res.ok ? "ذخیره شد: " + res.name : (res && res.error) || "خطا در خروجی.";
    });
  }

  /* ---------------------------------------------------------- config */
  function loadConfig() {
    call("get_config").then(function (res) {
      if (!res || !res.ok) return;
      var cfg = res.config;
      $("cfg-fuzzy").value = cfg.fuzzy_threshold;
      $("cfg-review").value = cfg.review_threshold;
      $("cfg-margin").value = cfg.ambiguity_margin;
      $("cfg-ocr").checked = !!cfg.ocr_enabled;
      $("cfg-brand").checked = !!cfg.restrict_to_price_list_brands;
    }).catch(function () {});
  }

  function saveConfig() {
    call("set_config", {
      fuzzy_threshold: Number($("cfg-fuzzy").value),
      review_threshold: Number($("cfg-review").value),
      ambiguity_margin: Number($("cfg-margin").value),
      ocr_enabled: $("cfg-ocr").checked,
      restrict_to_price_list_brands: $("cfg-brand").checked
    }).then(function (res) {
      $("cfg-status").textContent = res && res.ok ? "ذخیره شد." : "ذخیره نشد.";
      setTimeout(function () { $("cfg-status").textContent = ""; }, 2500);
    });
  }

  /* ------------------------------------------------------- listeners */
  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-action],[data-filter]");
    if (!target) return;
    var action = target.getAttribute("data-action");
    if (action === "select-pdf") pick("pdf");
    else if (action === "select-excel") pick("excel");
    else if (action === "start") start();
    else if (action === "export-excel") exportFile("xlsx");
    else if (action === "export-pdf") exportFile("pdf");
    else if (action === "save-config") saveConfig();
    else if (action === "new-run") {
      call("reset");
      $("pdf-name").textContent = $("excel-name").textContent = "انتخاب نشده";
      $("pick-pdf").classList.remove("filled");
      $("pick-excel").classList.remove("filled");
      $("brand-name").value = "";
      refreshStartButton();
      show("home");
    }
    var filter = target.getAttribute("data-filter");
    if (filter) {
      var chips = document.querySelectorAll(".chip");
      for (var i = 0; i < chips.length; i++) chips[i].classList.remove("active");
      target.classList.add("active");
      state.filter = filter;
      applyFilter();
    }
  });

  $("brand-name").addEventListener("input", refreshStartButton);

  $("btn-more").addEventListener("click", renderChunk);

  var searchTimer = null;
  $("search").addEventListener("input", function (event) {
    clearTimeout(searchTimer);
    var value = event.target.value.trim().toLowerCase();
    searchTimer = setTimeout(function () { state.search = value; applyFilter(); }, 180);
  });

  window.addEventListener("pywebviewready", loadConfig);
  setTimeout(loadConfig, 800);   // fallback if the event already fired
})();

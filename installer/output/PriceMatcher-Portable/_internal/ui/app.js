/* Price Matcher - UI layer only. All business logic lives in Python. */
(function () {
  "use strict";

  var PAGE = 300;                 // rows rendered per chunk
  var state = {
    rows: [], stats: {}, filter: "all", search: "", shown: 0, filtered: [],
    pdfItems: [],                 // [{path, name, brand}]
    excelReady: false,
  };

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

  function escapeHtml(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* ------------------------------------------------------------ home */
  function refreshStartButton() {
    var ready = state.excelReady && state.pdfItems.length > 0 &&
      state.pdfItems.every(function (item) { return (item.brand || "").trim() !== ""; });
    $("btn-start").disabled = !ready;
  }

  function renderPdfList() {
    var list = $("pdf-list");
    var empty = $("pdf-list-empty");
    // wipe everything except the empty-state placeholder, then rebuild
    var items = list.querySelectorAll(".pdf-list-item");
    for (var i = 0; i < items.length; i++) items[i].remove();
    empty.hidden = state.pdfItems.length > 0;

    state.pdfItems.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "pdf-list-item" + ((item.brand || "").trim() ? "" : " brand-missing");
      li.dataset.path = item.path;

      var name = document.createElement("span");
      name.className = "pdf-list-name";
      name.textContent = item.name;
      name.title = item.path;

      var brandInput = document.createElement("input");
      brandInput.type = "text";
      brandInput.placeholder = "نام برند (مثلاً شوان)";
      brandInput.value = item.brand || "";
      brandInput.addEventListener("input", function () {
        item.brand = brandInput.value.trim();
        li.classList.toggle("brand-missing", item.brand === "");
        call("set_pdf_brand", item.path, item.brand);
        refreshStartButton();
      });

      var removeBtn = document.createElement("button");
      removeBtn.className = "pdf-remove";
      removeBtn.type = "button";
      removeBtn.title = "حذف این فایل";
      removeBtn.textContent = "✕";
      removeBtn.addEventListener("click", function () {
        call("remove_pdf", item.path).then(function () {
          state.pdfItems = state.pdfItems.filter(function (p) { return p.path !== item.path; });
          renderPdfList();
          refreshStartButton();
        });
      });

      li.appendChild(removeBtn);
      li.appendChild(brandInput);
      li.appendChild(name);
      list.appendChild(li);
    });
  }

  function pickPdfs() {
    call("select_pdfs").then(function (res) {
      $("home-error").textContent = "";
      if (res && res.ok) {
        state.pdfItems = res.items || [];
        renderPdfList();
      } else if (res && res.error) {
        // "no file selected" is a normal cancel - do not shout about it
      }
      refreshStartButton();
    });
  }

  function pickExcel() {
    call("select_excel").then(function (res) {
      if (res && res.ok) {
        $("excel-name").textContent = res.name;
        $("pick-excel").classList.add("filled");
        state.excelReady = true;
        $("home-error").textContent = "";
      }
      refreshStartButton();
    });
  }

  function start() {
    $("home-error").textContent = "";
    setProgress(0, "شروع...");
    show("processing");
    call("process_batch").then(function (res) {
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
      renderFilesSummary();
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

  function renderFilesSummary() {
    var files = state.stats.files;
    var box = $("files-summary");
    if (!files || files.length < 1) {
      box.innerHTML = "";
      return;
    }
    var rows = files.map(function (f) {
      var status = f.ok ? (f.priced + " ردیف قیمت‌گذاری شد") : ("خطا: " + (f.error || ""));
      return "<tr class='" + (f.ok ? "" : "file-error") + "'>" +
        "<td class='name'>" + escapeHtml(f.name) + "</td>" +
        "<td>" + escapeHtml(f.brand || "-") + "</td>" +
        "<td>" + (f.pdf_rows || 0) + "</td>" +
        "<td>" + escapeHtml(status) + "</td>" +
        "</tr>";
    }).join("");
    box.innerHTML =
      "<table><thead><tr><th>فایل PDF</th><th>برند</th><th>ردیف خوانده‌شده</th><th>نتیجه</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table>";
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
      $("result-body").innerHTML = '<tr><td colspan="5" class="empty">موردی یافت نشد.</td></tr>';
      $("btn-more").hidden = true;
      return;
    }
    renderChunk();
  }

  function num(value) {
    if (value === null || value === undefined) return "-";
    return Number(value).toLocaleString("en-US");
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
        "<td>" + escapeHtml(row.source || "-") + "</td>" +
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

  function resetHome() {
    call("reset");
    state.pdfItems = [];
    state.excelReady = false;
    renderPdfList();
    $("excel-name").textContent = "انتخاب نشده";
    $("pick-excel").classList.remove("filled");
    refreshStartButton();
    show("home");
  }

  /* ------------------------------------------------------- listeners */
  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-action],[data-filter]");
    if (!target) return;
    var action = target.getAttribute("data-action");
    if (action === "select-pdf") pickPdfs();
    else if (action === "select-excel") pickExcel();
    else if (action === "start") start();
    else if (action === "export-excel") exportFile("xlsx");
    else if (action === "export-pdf") exportFile("pdf");
    else if (action === "save-config") saveConfig();
    else if (action === "new-run") resetHome();
    var filter = target.getAttribute("data-filter");
    if (filter) {
      var chips = document.querySelectorAll(".chip");
      for (var i = 0; i < chips.length; i++) chips[i].classList.remove("active");
      target.classList.add("active");
      state.filter = filter;
      applyFilter();
    }
  });

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

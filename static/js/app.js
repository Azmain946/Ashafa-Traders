(function () {
  "use strict";

  // CSRF helper used by all AJAX calls.
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute("content");
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  window.PharmacyERP = window.PharmacyERP || {};
  window.PharmacyERP.csrfHeader = function () {
    return { "X-CSRFToken": getCsrfToken(), "Content-Type": "application/json" };
  };

  window.PharmacyERP.debounce = function (fn, wait) {
    let timer;
    return function () {
      const ctx = this, args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(ctx, args), wait);
    };
  };

  window.PharmacyERP.currency = function (value) {
    const symbolMeta = document.querySelector('meta[name="currency-symbol"]');
    const symbol = symbolMeta ? symbolMeta.getAttribute("content") : "৳";
    const num = Number(value || 0);
    return `${symbol}${num.toFixed(2)}`;
  };

  // Sidebar toggle on small screens.
  const toggle = document.getElementById("sidebarToggle");
  const sidebar = document.querySelector(".sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", () => sidebar.classList.toggle("is-open"));
    document.addEventListener("click", (e) => {
      if (window.innerWidth >= 768) return;
      if (!sidebar.contains(e.target) && !toggle.contains(e.target)) sidebar.classList.remove("is-open");
    });
  }

  // Global product search (topbar).
  const searchInput = document.getElementById("globalSearch");
  const suggestions = document.getElementById("globalSuggestions");
  if (searchInput && suggestions) {
    const fetchSuggestions = window.PharmacyERP.debounce(function (q) {
      if (q.length < 2) {
        suggestions.hidden = true;
        suggestions.innerHTML = "";
        return;
      }
      fetch(`/inventory/api/search/?q=${encodeURIComponent(q)}`, { credentials: "same-origin" })
        .then((r) => r.json())
        .then((data) => {
          if (!data.results.length) {
            suggestions.innerHTML = `<div class="suggestion-item text-muted">No matches.</div>`;
            suggestions.hidden = false;
            return;
          }
          suggestions.innerHTML = data.results
            .map(
              (p) => `
              <a class="suggestion-item" href="${p.url}">
                ${p.thumbnail ? `<img src="${p.thumbnail}" alt="">` : `<div class="suggestion-item-thumb"><i class="bi bi-capsule"></i></div>`}
                <div>
                  <div class="name">${p.name} ${p.strength ? `<span class="meta">${p.strength}</span>` : ""}</div>
                  <div class="meta">${p.manufacturer || ""}${p.generic_name ? ` · ${p.generic_name}` : ""}</div>
                </div>
                <div class="price">${window.PharmacyERP.currency(p.tp_price)}</div>
              </a>`
            )
            .join("");
          suggestions.hidden = false;
        })
        .catch(() => {
          suggestions.hidden = true;
        });
    }, 220);
    searchInput.addEventListener("input", (e) => fetchSuggestions(e.target.value.trim()));
    searchInput.addEventListener("focus", () => {
      if (suggestions.innerHTML) suggestions.hidden = false;
    });
    document.addEventListener("click", (e) => {
      if (!suggestions.contains(e.target) && e.target !== searchInput) suggestions.hidden = true;
    });
  }

  // Auto-dismiss alerts after 6s.
  document.querySelectorAll(".messages-stack .alert").forEach((el) => {
    setTimeout(() => {
      const inst = window.bootstrap && window.bootstrap.Alert.getOrCreateInstance(el);
      if (inst) inst.close();
    }, 6000);
  });
})();

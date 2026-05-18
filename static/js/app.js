(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

  function debounce(fn, delay) {
    let timer;
    return function (...args) {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn.apply(this, args), delay);
    };
  }

  function money(value) {
    const number = Number(value || 0);
    return number.toFixed(2);
  }

  function productImageMarkup(src) {
    if (src) {
      return `<div class="mini-image"><img src="${src}" alt=""></div>`;
    }
    return '<div class="mini-image"><i class="bi bi-capsule"></i></div>';
  }

  function resultItem(batch) {
    return `
      <div class="suggestion-item" data-batch='${JSON.stringify(batch)}'>
        ${productImageMarkup(batch.image)}
        <div class="flex-grow-1">
          <strong>${batch.name}</strong>
          <small>${batch.generic_name || batch.brand || "Medicine"} · Batch ${batch.batch_number} · Stock ${batch.stock_quantity}</small>
        </div>
        <div class="text-end">
          <strong>${batch.tp_price}</strong>
          <small class="d-block">TP</small>
        </div>
      </div>
    `;
  }

  async function searchProducts(term) {
    if (!term || term.length < 2) {
      return [];
    }
    const response = await fetch(`/api/search/products/?q=${encodeURIComponent(term)}`);
    if (!response.ok) {
      return [];
    }
    const data = await response.json();
    return data.results || [];
  }

  function bindSearch(inputId, resultsId, onSelect) {
    const input = document.getElementById(inputId);
    const results = document.getElementById(resultsId);
    if (!input || !results) {
      return;
    }
    const runSearch = debounce(async () => {
      const term = input.value.trim();
      if (term.length < 2) {
        results.style.display = "none";
        results.innerHTML = "";
        return;
      }
      const items = await searchProducts(term);
      results.innerHTML = items.length ? items.map(resultItem).join("") : '<div class="p-3 text-muted">No matching medicine found.</div>';
      results.style.display = "block";
    }, 260);
    input.addEventListener("input", runSearch);
    results.addEventListener("click", (event) => {
      const item = event.target.closest(".suggestion-item");
      if (!item) {
        return;
      }
      const batch = JSON.parse(item.dataset.batch);
      results.style.display = "none";
      if (onSelect) {
        onSelect(batch);
      }
    });
    document.addEventListener("click", (event) => {
      if (!results.contains(event.target) && event.target !== input) {
        results.style.display = "none";
      }
    });
  }

  function openQuickModal(batch) {
    const modalEl = document.getElementById("quickProductModal");
    if (!modalEl) {
      return;
    }
    document.getElementById("quickProductName").textContent = batch.name;
    document.getElementById("quickProductMeta").textContent = `${batch.generic_name || "Medicine"} · Batch ${batch.batch_number} · Exp ${batch.expiry_date}`;
    document.getElementById("quickBatchId").value = batch.batch_id;
    document.getElementById("quickQuantity").value = 1;
    document.getElementById("quickQuantity").max = batch.stock_quantity;
    document.getElementById("quickUnitPrice").value = batch.tp_price;
    document.getElementById("quickDiscount").value = "0.00";
    document.getElementById("quickStockInfo").textContent = `${batch.stock_quantity} units available. MRP ${batch.mrp}.`;
    const image = document.getElementById("quickProductImage");
    image.innerHTML = batch.image ? `<img src="${batch.image}" alt="${batch.name}">` : '<i class="bi bi-capsule-pill"></i>';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  async function cartRequest(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Cart update failed.");
    }
    return data;
  }

  function renderCart(cart) {
    const body = document.getElementById("cartTableBody");
    const count = document.getElementById("cartCount");
    const subtotal = document.getElementById("cartSubtotal");
    if (!body) {
      return;
    }
    if (!cart.items.length) {
      body.innerHTML = '<tr class="empty-cart"><td colspan="7" class="text-center text-muted py-4">Search and add a medicine to begin.</td></tr>';
    } else {
      body.innerHTML = cart.items.map((item) => `
        <tr data-batch-id="${item.batch_id}">
          <td>${item.name}</td>
          <td>${item.batch_number}</td>
          <td>${item.quantity}</td>
          <td>${item.unit_price}</td>
          <td>${item.discount_amount}</td>
          <td>${item.line_total}</td>
          <td><button class="btn btn-sm btn-outline-danger" data-remove-cart="${item.batch_id}"><i class="bi bi-trash"></i></button></td>
        </tr>
      `).join("");
    }
    if (count) {
      count.textContent = `${cart.count} items`;
    }
    if (subtotal) {
      subtotal.textContent = money(cart.subtotal);
    }
    updateCheckoutPreview();
  }

  function updateCheckoutPreview() {
    const subtotal = Number(document.getElementById("cartSubtotal")?.textContent || 0);
    const percent = Number(document.querySelector('[name="discount_percent"]')?.value || 0);
    const fixed = Number(document.querySelector('[name="discount_amount"]')?.value || 0);
    const paid = Number(document.querySelector('[name="paid_amount"]')?.value || 0);
    const discount = Math.min(subtotal, subtotal * percent / 100 + fixed);
    const due = Math.max(subtotal - discount - paid, 0);
    const discountEl = document.getElementById("checkoutDiscountPreview");
    const dueEl = document.getElementById("checkoutDuePreview");
    if (discountEl) {
      discountEl.textContent = money(discount);
    }
    if (dueEl) {
      dueEl.textContent = money(due);
    }
  }

  bindSearch("orderSearchInput", "orderSearchResults", openQuickModal);
  bindSearch("globalSearchInput", "globalSearchResults", (batch) => {
    window.location.href = `/products/${batch.product_id}/`;
  });

  const saveProductButton = document.getElementById("quickSaveProduct");
  if (saveProductButton) {
    saveProductButton.addEventListener("click", async () => {
      try {
        const cart = await cartRequest("/api/cart/add/", {
          batch_id: document.getElementById("quickBatchId").value,
          quantity: document.getElementById("quickQuantity").value,
          unit_price: document.getElementById("quickUnitPrice").value,
          discount_amount: document.getElementById("quickDiscount").value,
        });
        renderCart(cart);
        bootstrap.Modal.getOrCreateInstance(document.getElementById("quickProductModal")).hide();
      } catch (error) {
        alert(error.message);
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const removeButton = event.target.closest("[data-remove-cart]");
    if (!removeButton) {
      return;
    }
    try {
      const cart = await cartRequest("/api/cart/remove/", { batch_id: removeButton.dataset.removeCart });
      renderCart(cart);
    } catch (error) {
      alert(error.message);
    }
  });

  document.querySelectorAll('[name="discount_percent"], [name="discount_amount"], [name="paid_amount"]').forEach((input) => {
    input.addEventListener("input", updateCheckoutPreview);
  });

  const fullyPaid = document.getElementById("markFullyPaid");
  const partiallyPaid = document.getElementById("markPartiallyPaid");
  const paidAmount = document.querySelector('[name="paid_amount"]');
  if (fullyPaid && paidAmount) {
    fullyPaid.addEventListener("change", () => {
      if (fullyPaid.checked) {
        const subtotal = Number(document.getElementById("cartSubtotal")?.textContent || 0);
        const percent = Number(document.querySelector('[name="discount_percent"]')?.value || 0);
        const fixed = Number(document.querySelector('[name="discount_amount"]')?.value || 0);
        const discount = Math.min(subtotal, subtotal * percent / 100 + fixed);
        paidAmount.value = money(Math.max(subtotal - discount, 0));
        if (partiallyPaid) {
          partiallyPaid.checked = false;
        }
      }
      updateCheckoutPreview();
    });
  }
  if (partiallyPaid && paidAmount) {
    partiallyPaid.addEventListener("change", () => {
      if (partiallyPaid.checked) {
        fullyPaid.checked = false;
        paidAmount.focus();
      }
    });
  }

  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
      document.querySelector(".app-sidebar")?.classList.toggle("open");
    });
  }

  async function drawDashboardChart() {
    const canvas = document.getElementById("growthChart");
    if (!canvas) {
      return;
    }
    const response = await fetch(`/api/dashboard/?range=${encodeURIComponent(window.dashboardRange || "this_month")}`);
    const data = await response.json();
    const ctx = canvas.getContext("2d");
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || 700;
    const height = 260;
    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    ctx.clearRect(0, 0, width, height);

    const months = data.monthly || [];
    if (!months.length) {
      ctx.fillStyle = "#64748b";
      ctx.font = "15px sans-serif";
      ctx.fillText("No growth data yet.", 24, 40);
      return;
    }
    const values = months.map((item) => Number(item.total));
    const max = Math.max(...values, 1);
    const padding = 34;
    const barWidth = Math.max((width - padding * 2) / months.length - 12, 18);
    ctx.fillStyle = "#e2e8f0";
    ctx.fillRect(padding, height - padding, width - padding * 2, 1);
    months.forEach((item, index) => {
      const x = padding + index * (barWidth + 12);
      const barHeight = (Number(item.total) / max) * (height - padding * 2);
      const y = height - padding - barHeight;
      const gradient = ctx.createLinearGradient(0, y, 0, height - padding);
      gradient.addColorStop(0, "#2563eb");
      gradient.addColorStop(1, "#93c5fd");
      ctx.fillStyle = gradient;
      ctx.roundRect(x, y, barWidth, barHeight, 8);
      ctx.fill();
      ctx.fillStyle = "#64748b";
      ctx.font = "11px sans-serif";
      ctx.fillText(item.month, x, height - 10);
    });
  }

  if (CanvasRenderingContext2D.prototype.roundRect) {
    drawDashboardChart();
  }

  updateCheckoutPreview();
})();

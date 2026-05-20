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

  function money(value, places = 2) {
    const number = Number(value || 0);
    return number.toFixed(places);
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
          <small>${batch.generic_name || batch.brand || "Medicine"} · ${batch.strength || "Default"} · Batch ${batch.batch_number} · Stock ${batch.stock_quantity}</small>
        </div>
        <div class="text-end">
          <strong>${money(batch.tp_price, 3)}</strong>
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
      input.value = "";
    });
    document.addEventListener("click", (event) => {
      if (!results.contains(event.target) && event.target !== input) {
        results.style.display = "none";
      }
    });
  }

  let quickVariants = [];
  let selectedVariant = null;
  let selectedBatch = null;
  let selectedPriceType = "tp";
  let editingCartItem = null;

  function renderStrengthOptions() {
    const container = document.getElementById("quickStrengthOptions");
    if (!container) {
      return;
    }
    container.innerHTML = quickVariants.map((variant, index) => `
      <button type="button" class="btn ${variant === selectedVariant ? "btn-primary" : "btn-outline-primary"}" data-variant-index="${index}">
        ${variant.strength} <span class="badge text-bg-light ms-1">${variant.total_stock}</span>
      </button>
    `).join("");
  }

  function renderBatchOptions() {
    const select = document.getElementById("quickBatchSelect");
    if (!select || !selectedVariant) {
      return;
    }
    select.innerHTML = selectedVariant.batches.map((batch) => `
      <option value="${batch.batch_id}">Batch ${batch.batch_number} · Stock ${batch.stock_quantity} · Exp ${batch.expiry_date}</option>
    `).join("");
    selectedBatch = selectedVariant.batches[0];
    updateSelectedBatch();
  }

  function updateSelectedBatch() {
    const select = document.getElementById("quickBatchSelect");
    if (select && selectedVariant) {
      selectedBatch = selectedVariant.batches.find((batch) => String(batch.batch_id) === String(select.value)) || selectedVariant.batches[0];
    }
    if (!selectedBatch) {
      return;
    }
    document.getElementById("quickBatchId").value = selectedBatch.batch_id;
    document.getElementById("quickQuantity").value = 1;
    document.getElementById("quickQuantity").max = selectedBatch.stock_quantity;
    document.getElementById("quickUnitPrice").textContent = money(selectedPriceType === "mrp" ? selectedBatch.mrp : selectedBatch.tp_price, 3);
    document.getElementById("quickStockInfo").textContent = `${selectedBatch.stock_quantity} units available in batch ${selectedBatch.batch_number}. TP ${money(selectedBatch.tp_price, 3)} / MRP ${money(selectedBatch.mrp, 3)}.`;
  }

  async function openQuickModal(batch, existingItem = null) {
    const modalEl = document.getElementById("quickProductModal");
    if (!modalEl) {
      return;
    }
    editingCartItem = existingItem;
    const response = await fetch(`/api/products/${batch.product_id}/variants/`);
    const data = response.ok ? await response.json() : { variants: [] };
    quickVariants = data.variants.length ? data.variants : [{
      product_id: batch.product_id,
      name: batch.name,
      strength: batch.strength || "Default",
      generic_name: batch.generic_name,
      image: batch.image,
      total_stock: batch.stock_quantity,
      batches: [batch],
    }];
    selectedVariant = quickVariants.find((variant) => variant.product_id === batch.product_id) || quickVariants[0];
    selectedBatch = selectedVariant.batches.find((item) => item.batch_id === batch.batch_id) || selectedVariant.batches[0];
    selectedPriceType = "tp";
    document.getElementById("quickProductName").textContent = batch.name;
    document.getElementById("quickProductMeta").textContent = `${batch.generic_name || "Medicine"} · Choose strength, batch, and TP/MRP`;
    document.getElementById("quickPriceType").value = "tp";
    document.getElementById("quickDiscountPercent").value = "0";
    document.getElementById("quickAddPercent").value = "0";
    document.querySelectorAll("[data-price-type]").forEach((button) => {
      button.classList.toggle("btn-primary", button.dataset.priceType === "tp");
      button.classList.toggle("btn-outline-primary", button.dataset.priceType !== "tp");
    });
    const image = document.getElementById("quickProductImage");
    image.innerHTML = selectedVariant.image ? `<img src="${selectedVariant.image}" alt="${batch.name}">` : '<i class="bi bi-capsule-pill"></i>';
    renderStrengthOptions();
    renderBatchOptions();
    document.getElementById("quickBatchSelect").value = selectedBatch.batch_id;
    updateSelectedBatch();
    if (editingCartItem) {
      if (selectedBatch && Number(editingCartItem.unit_price).toFixed(8) === Number(selectedBatch.mrp).toFixed(8)) {
        selectedPriceType = "mrp";
        document.getElementById("quickPriceType").value = "mrp";
        document.querySelectorAll("[data-price-type]").forEach((button) => {
          button.classList.toggle("btn-primary", button.dataset.priceType === "mrp");
          button.classList.toggle("btn-outline-primary", button.dataset.priceType !== "mrp");
        });
        updateSelectedBatch();
      }
      document.getElementById("quickQuantity").value = editingCartItem.quantity || 1;
      document.getElementById("quickDiscountPercent").value = editingCartItem.discount_percent || "0";
      document.getElementById("quickAddPercent").value = editingCartItem.add_percent || "0";
    }
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
      body.innerHTML = '<tr class="empty-cart"><td colspan="8" class="text-center text-muted py-4">Search and add a medicine to begin.</td></tr>';
    } else {
      body.innerHTML = cart.items.map((item) => `
        <tr class="cart-edit-row" data-cart-edit="1" data-product-id="${item.product_id}" data-batch-id="${item.batch_id}" data-quantity="${item.quantity}" data-discount-percent="${item.discount_percent}" data-add-percent="${item.add_percent || 0}" data-unit-price="${item.unit_price}">
          <td>${item.name}</td>
          <td>${item.batch_number}</td>
          <td>${item.quantity}</td>
          <td>${money(item.unit_price, 3)}</td>
          <td>${money(item.discount_percent, 2)}</td>
          <td>${money(item.add_percent || 0, 2)}</td>
          <td>${money(item.line_total, 2)}</td>
          <td><button class="btn btn-sm btn-outline-danger" data-remove-cart="${item.batch_id}"><i class="bi bi-trash"></i></button></td>
        </tr>
      `).join("");
    }
    if (count) {
      count.textContent = `${cart.count} items`;
    }
    if (subtotal) {
      subtotal.textContent = money(cart.subtotal, 2);
    }
    const roundOff = document.getElementById("checkoutRoundOffPreview");
    const roundedTotal = document.getElementById("checkoutRoundedTotal");
    if (roundOff) {
      roundOff.textContent = money(cart.round_off_amount, 2);
    }
    if (roundedTotal) {
      roundedTotal.textContent = money(cart.rounded_total, 2);
    }
    updateCheckoutPreview();
  }

  function updateCheckoutPreview() {
    const subtotal = Number(document.getElementById("cartSubtotal")?.textContent || 0);
    const percent = Number(document.querySelector('[name="discount_percent"]')?.value || 0);
    const fixed = Number(document.querySelector('[name="discount_amount"]')?.value || 0);
    const paid = Number(document.querySelector('[name="paid_amount"]')?.value || 0);
    const discount = Math.min(subtotal, subtotal * percent / 100 + fixed);
    const unroundedTotal = Math.max(subtotal - discount, 0);
    const roundedTotal = Math.floor(unroundedTotal);
    const roundOff = unroundedTotal - roundedTotal;
    const due = Math.max(roundedTotal - paid, 0);
    const discountEl = document.getElementById("checkoutDiscountPreview");
    const roundOffEl = document.getElementById("checkoutRoundOffPreview");
    const roundedTotalEl = document.getElementById("checkoutRoundedTotal");
    const dueEl = document.getElementById("checkoutDuePreview");
    if (discountEl) {
      discountEl.textContent = money(discount);
    }
    if (dueEl) {
      dueEl.textContent = money(due);
    }
    if (roundOffEl) {
      roundOffEl.textContent = money(roundOff);
    }
    if (roundedTotalEl) {
      roundedTotalEl.textContent = money(roundedTotal);
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
          price_type: document.getElementById("quickPriceType").value,
          discount_percent: document.getElementById("quickDiscountPercent").value,
          add_percent: document.getElementById("quickAddPercent").value,
          replace: Boolean(editingCartItem),
        });
        renderCart(cart);
        bootstrap.Modal.getOrCreateInstance(document.getElementById("quickProductModal")).hide();
      } catch (error) {
        alert(error.message);
      }
    });
  }

  document.addEventListener("click", (event) => {
    const variantButton = event.target.closest("[data-variant-index]");
    if (variantButton) {
      selectedVariant = quickVariants[Number(variantButton.dataset.variantIndex)];
      renderStrengthOptions();
      renderBatchOptions();
    }
    const priceButton = event.target.closest("[data-price-type]");
    if (priceButton) {
      selectedPriceType = priceButton.dataset.priceType;
      document.getElementById("quickPriceType").value = selectedPriceType;
      document.querySelectorAll("[data-price-type]").forEach((button) => {
        button.classList.toggle("btn-primary", button === priceButton);
        button.classList.toggle("btn-outline-primary", button !== priceButton);
      });
      updateSelectedBatch();
    }
    const row = event.target.closest(".clickable-row");
    if (row && !event.target.closest("a, button, input, select, textarea")) {
      window.location.href = row.dataset.href;
    }
    const cartRow = event.target.closest("[data-cart-edit]");
    if (cartRow && !event.target.closest("button")) {
      openQuickModal({
        product_id: Number(cartRow.dataset.productId),
        batch_id: Number(cartRow.dataset.batchId),
        name: cartRow.children[0]?.textContent || "Medicine",
      }, {
        quantity: cartRow.dataset.quantity,
        discount_percent: cartRow.dataset.discountPercent,
        add_percent: cartRow.dataset.addPercent,
        unit_price: cartRow.dataset.unitPrice,
      });
    }
  });

  const batchSelect = document.getElementById("quickBatchSelect");
  if (batchSelect) {
    batchSelect.addEventListener("change", updateSelectedBatch);
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
        paidAmount.value = money(Math.floor(Math.max(subtotal - discount, 0)));
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
    const chartWidth = width - padding * 2;
    const chartHeight = height - padding * 2;
    ctx.fillStyle = "#e2e8f0";
    ctx.fillRect(padding, height - padding, width - padding * 2, 1);
    const points = months.map((item, index) => {
      const x = padding + (months.length === 1 ? chartWidth / 2 : index * (chartWidth / (months.length - 1)));
      const y = height - padding - (Number(item.total) / max) * chartHeight;
      return { x, y, item };
    });
    ctx.strokeStyle = "#dbeafe";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = padding + i * (chartHeight / 4);
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.stroke();
    }
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 4;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) {
        ctx.moveTo(point.x, point.y);
      } else {
        ctx.lineTo(point.x, point.y);
      }
    });
    ctx.stroke();
    points.forEach(({ x, y, item }) => {
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#2563eb";
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.fillStyle = "#64748b";
      ctx.font = "11px sans-serif";
      ctx.fillText(item.month, x - 18, height - 10);
    });
  }

  drawDashboardChart();

  updateCheckoutPreview();

  const quickAddPercentEl = document.getElementById("quickAddPercent");
  if (quickAddPercentEl) {
    quickAddPercentEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.stopImmediatePropagation();
        document.getElementById("quickSaveProduct")?.click();
      }
    });
  }

  function isProductImageField(element) {
    return element && element.name === "image" && element.type === "file";
  }

  function isEnterNavField(element) {
    if (!element || element.disabled) {
      return false;
    }
    if (isProductImageField(element)) {
      return false;
    }
    const tag = element.tagName;
    if (tag === "TEXTAREA") {
      return false;
    }
    if (tag !== "INPUT" && tag !== "SELECT") {
      return false;
    }
    const type = (element.type || "").toLowerCase();
    if (["hidden", "checkbox", "radio", "button", "submit", "file"].includes(type)) {
      return false;
    }
    if (element.readOnly) {
      return false;
    }
    if (element.closest("[data-skip-enter-nav]")) {
      return false;
    }
    return true;
  }

  function enterNavScope(element) {
    const modal = element.closest(".modal.show");
    if (modal) {
      return modal;
    }
    return element.closest("form") || document;
  }

  function enterNavFields(scope) {
    return Array.from(scope.querySelectorAll("input, select, textarea")).filter((field) => {
      if (!isEnterNavField(field)) {
        return false;
      }
      return field.offsetParent !== null || field === document.activeElement;
    });
  }

  function activateSubmit(scope) {
    const form = scope.closest ? scope.closest("form") : null;
    if (form) {
      const submit = form.querySelector('button[type="submit"], input[type="submit"]');
      if (submit) {
        submit.click();
        return;
      }
      const primary = form.querySelector("button.btn-primary:not([data-bs-dismiss])");
      if (primary) {
        primary.click();
        return;
      }
    }
    if (scope.classList?.contains("modal")) {
      document.getElementById("quickSaveProduct")?.click();
      return;
    }
    const fallback = scope.querySelector('button[type="submit"], button.btn-primary:not([data-bs-dismiss])');
    fallback?.click();
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    const target = event.target;
    if (!isEnterNavField(target)) {
      return;
    }
    const scope = enterNavScope(target);
    const fields = enterNavFields(scope);
    const index = fields.indexOf(target);
    if (index === -1) {
      return;
    }
    event.preventDefault();
    if (index < fields.length - 1) {
      fields[index + 1].focus();
      if (typeof fields[index + 1].select === "function") {
        fields[index + 1].select();
      }
      return;
    }
    activateSubmit(scope);
  });

  function shouldClearOnFocus(element) {
    if (!element || element.disabled || element.readOnly) {
      return false;
    }
    if (isProductImageField(element)) {
      return false;
    }
    const tag = element.tagName;
    if (tag === "SELECT") {
      return false;
    }
    if (tag !== "INPUT" && tag !== "TEXTAREA") {
      return false;
    }
    const type = (element.type || "").toLowerCase();
    if (["hidden", "checkbox", "radio", "button", "submit", "file"].includes(type)) {
      return false;
    }
    if (element.closest("[data-no-clear-on-focus]")) {
      return false;
    }
    return true;
  }

  document.addEventListener(
    "focusin",
    (event) => {
      const target = event.target;
      if (!shouldClearOnFocus(target)) {
        return;
      }
      if (target.dataset.clearedOnce === "1") {
        return;
      }
      target.dataset.previousValue = target.value;
      target.value = "";
      target.dataset.clearedOnce = "1";
    },
    true,
  );

  document.addEventListener(
    "focusout",
    (event) => {
      const target = event.target;
      if (!shouldClearOnFocus(target) || target.dataset.clearedOnce !== "1") {
        return;
      }
      if (target.value === "" && target.dataset.previousValue !== undefined) {
        target.value = target.dataset.previousValue;
      }
      delete target.dataset.previousValue;
      delete target.dataset.clearedOnce;
    },
    true,
  );
})();

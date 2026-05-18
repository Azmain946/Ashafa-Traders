(function ($) {
  "use strict";
  if (typeof $ === "undefined") return;

  const URLS = {
    productSearch: "/inventory/api/search/",
    customerSearch: "/customers/api/search/",
    cartAdd: "/sales/cart/add/",
    cartUpdate: "/sales/cart/update/",
    cartRemove: "/sales/cart/remove/",
    cartClear: "/sales/cart/clear/",
    cartSummary: "/sales/cart/summary/",
  };

  function fmt(n) { return (Number(n) || 0).toFixed(2); }
  function csym() {
    const m = document.querySelector('meta[name="currency-symbol"]'); return m ? m.content : "৳";
  }

  // ---- Product search & modal ------------------------------------------
  const $search = $("#productSearch");
  const $sugg = $("#productSuggestions");
  const modalEl = document.getElementById("productModal");
  const productModal = modalEl ? new bootstrap.Modal(modalEl) : null;
  let currentProduct = null;

  const debouncedSearch = window.PharmacyERP.debounce(function (q) {
    if (q.length < 2) { $sugg.hide().empty(); return; }
    $.getJSON(URLS.productSearch, { q })
      .done(function (data) {
        if (!data.results.length) {
          $sugg.html('<div class="suggestion-item text-muted">No matches.</div>').show();
          return;
        }
        const html = data.results.map(function (p) {
          const stockBadge = p.stock > 0
            ? `<span class="stock-pill">${p.stock} in stock</span>`
            : `<span class="stock-pill danger">Out</span>`;
          return `
            <div class="suggestion-item" data-pid="${p.id}">
              ${p.thumbnail ? `<img src="${p.thumbnail}" alt="">` : `<div class="placeholder-thumb" style="width:40px;height:40px;font-size:1.1rem;background:#f1f5f9;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;"><i class="bi bi-capsule"></i></div>`}
              <div>
                <div class="name">${p.name} ${p.strength ? `<span class="meta">${p.strength}</span>` : ""}</div>
                <div class="meta">${p.manufacturer || ""}${p.generic_name ? ` · ${p.generic_name}` : ""} ${p.is_antibiotic ? '· <span class="text-danger">ABX</span>' : ""}</div>
              </div>
              <div class="text-end">
                <div class="price">${csym()}${fmt(p.tp_price)}</div>
                <div class="meta">${stockBadge}</div>
              </div>
            </div>`;
        }).join("");
        $sugg.html(html).show();
        // store payload for modal
        $sugg.data("results", data.results);
      });
  }, 220);

  $search.on("input", function () { debouncedSearch($(this).val().trim()); });
  $(document).on("click", function (e) {
    if (!$.contains($sugg[0], e.target) && e.target !== $search[0]) $sugg.hide();
  });

  $sugg.on("click", ".suggestion-item", function () {
    const pid = $(this).data("pid"); if (!pid) return;
    const results = $sugg.data("results") || [];
    const product = results.find((p) => p.id === pid);
    if (!product) return;
    openProductModal(product);
  });

  function openProductModal(product) {
    currentProduct = product;
    $("#modalName").text(product.name + (product.strength ? ` ${product.strength}` : ""));
    $("#modalSub").text((product.manufacturer || "") + (product.generic_name ? ` · ${product.generic_name}` : ""));
    $("#modalImage").attr("src", product.thumbnail || "");
    const $batch = $("#modalBatch").empty();
    if (!product.batches.length) {
      $batch.append('<option value="">No sellable batches</option>');
      $("#modalSaveBtn").prop("disabled", true);
    } else {
      $("#modalSaveBtn").prop("disabled", false);
      product.batches.forEach(function (b) {
        $batch.append(`<option value="${b.id}" data-price="${b.tp_price}" data-stock="${b.quantity}">${b.batch_number} · exp ${b.expiry_date} · ${b.quantity} in stock · ${csym()}${fmt(b.tp_price)}</option>`);
      });
    }
    syncPriceAndStock();
    $("#modalQty").val(1);
    productModal && productModal.show();
    $sugg.hide();
    $search.val("").focus();
  }

  function syncPriceAndStock() {
    const opt = $("#modalBatch option:selected");
    $("#modalPrice").val(opt.data("price") || 0);
    const stock = opt.data("stock") || 0;
    $("#modalStockHint").text(stock ? `Available stock: ${stock}` : "");
    $("#modalQty").attr("max", stock || 9999);
  }
  $("#modalBatch").on("change", syncPriceAndStock);

  $("#modalSaveBtn").on("click", function () {
    if (!currentProduct) return;
    const batchId = parseInt($("#modalBatch").val(), 10);
    const qty = Math.max(1, parseInt($("#modalQty").val(), 10) || 1);
    const price = parseFloat($("#modalPrice").val()) || 0;
    if (!batchId) return;
    addToCart({ product_id: currentProduct.id, batch_id: batchId, quantity: qty, unit_price: price });
  });

  // ---- Cart -----------------------------------------------------------
  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: window.PharmacyERP.csrfHeader(),
      credentials: "same-origin",
      body: JSON.stringify(payload || {}),
    }).then((r) => r.json());
  }

  function addToCart(payload) {
    postJson(URLS.cartAdd, payload).then((res) => {
      if (res.ok) {
        rerenderCart(res.cart);
        productModal && productModal.hide();
      } else if (res.error) {
        alert(res.error);
      }
    });
  }

  function rerenderCart(cart) {
    const $body = $("#cartBody"); $body.empty();
    if (!cart.lines.length) {
      $body.html('<tr id="cartEmptyRow"><td colspan="7" class="text-center text-muted py-4">Cart is empty. Search and add a product above.</td></tr>');
    } else {
      cart.lines.forEach(function (line) {
        const tr = `
          <tr data-batch-id="${line.batch_id}">
            <td><strong>${line.product_name}</strong></td>
            <td>${line.batch_number || "—"}</td>
            <td class="text-end"><input type="number" step="0.01" min="0" value="${fmt(line.unit_price)}" class="form-control form-control-sm text-end cart-price"></td>
            <td class="text-end"><input type="number" min="1" value="${line.quantity}" class="form-control form-control-sm text-end cart-qty"></td>
            <td class="text-end"><input type="number" step="0.01" min="0" value="${fmt(line.discount)}" class="form-control form-control-sm text-end cart-discount"></td>
            <td class="text-end fw-semibold cart-line-total">${csym()}${fmt(line.line_total)}</td>
            <td><button class="btn btn-sm btn-light text-danger cart-remove"><i class="bi bi-x-lg"></i></button></td>
          </tr>`;
        $body.append(tr);
      });
    }
    $("#cartSubtotal").text(`${csym()}${fmt(cart.subtotal)}`);
    $("#cartCountLabel").text(`${cart.count} item${cart.count === 1 ? "" : "s"}`);
    recalcTotals();
  }

  // Inline update with debounce
  const debouncedUpdate = window.PharmacyERP.debounce(function (batchId, payload) {
    postJson(URLS.cartUpdate, Object.assign({ batch_id: batchId }, payload))
      .then((res) => res.ok && rerenderCart(res.cart));
  }, 350);

  $("#cartBody").on("input", ".cart-qty, .cart-price, .cart-discount", function () {
    const $tr = $(this).closest("tr");
    const batchId = parseInt($tr.data("batch-id"), 10);
    const payload = {
      quantity: parseInt($tr.find(".cart-qty").val(), 10) || 0,
      unit_price: parseFloat($tr.find(".cart-price").val()) || 0,
      discount: parseFloat($tr.find(".cart-discount").val()) || 0,
    };
    // optimistic line total preview
    const lineTotal = Math.max(0, payload.unit_price * payload.quantity - payload.discount);
    $tr.find(".cart-line-total").text(`${csym()}${fmt(lineTotal)}`);
    debouncedUpdate(batchId, payload);
  });

  $("#cartBody").on("click", ".cart-remove", function () {
    const batchId = parseInt($(this).closest("tr").data("batch-id"), 10);
    postJson(URLS.cartRemove, { batch_id: batchId }).then((res) => res.ok && rerenderCart(res.cart));
  });

  $("#clearCartBtn").on("click", function () {
    if (!confirm("Clear all items from cart?")) return;
    postJson(URLS.cartClear, {}).then((res) => res.ok && rerenderCart(res.cart));
  });

  // ---- Customer search -------------------------------------------------
  const $custInput = $("#customerSearch");
  const $custSugg = $("#customerSuggestions");

  const debouncedCustSearch = window.PharmacyERP.debounce(function (q) {
    if (q.length < 2) { $custSugg.hide().empty(); return; }
    $.getJSON(URLS.customerSearch, { q })
      .done(function (data) {
        if (!data.results.length) {
          $custSugg.html('<div class="suggestion-item text-muted">No customer. Fill the form to create one.</div>').show();
          return;
        }
        $custSugg.html(data.results.map((c) => `
          <div class="suggestion-item" data-id="${c.id}" data-name="${c.name}" data-phone="${c.phone}">
            <div>
              <div class="name">${c.name}</div>
              <div class="meta">${c.phone}${c.address ? ` · ${c.address}` : ""}</div>
            </div>
          </div>`).join("")).show();
      });
  }, 220);

  $custInput.on("input", function () { debouncedCustSearch($(this).val().trim()); });
  $custSugg.on("click", ".suggestion-item", function () {
    const $el = $(this);
    $("#id_customer_id").val($el.data("id"));
    $("#id_customer_name").val($el.data("name"));
    $("#id_customer_phone").val($el.data("phone"));
    $custInput.val($el.data("name") + " · " + $el.data("phone"));
    $custSugg.hide();
  });
  $(document).on("click", function (e) {
    if (!$.contains($custSugg[0] || {}, e.target) && e.target !== $custInput[0]) $custSugg.hide();
  });

  // ---- Totals recalculation (client-side preview) ---------------------
  function recalcTotals() {
    let subtotal = 0;
    $("#cartBody tr").each(function () {
      const total = parseFloat($(this).find(".cart-line-total").text().replace(/[^\d.-]/g, "")) || 0;
      subtotal += total;
    });
    const discType = $("#id_discount_type").val();
    const discVal = parseFloat($("#id_discount_value").val()) || 0;
    const paid = parseFloat($("#id_paid_amount").val()) || 0;
    let discount = 0;
    if (discType === "percent") discount = subtotal * discVal / 100;
    else discount = Math.min(discVal, subtotal);
    const total = Math.max(0, subtotal - discount);
    const due = Math.max(0, total - paid);

    $("#sumSubtotal").text(csym() + fmt(subtotal));
    $("#sumDiscount").text(csym() + fmt(discount));
    $("#sumTotal").text(csym() + fmt(total));
    $("#sumPaid").text(csym() + fmt(paid));
    $("#sumDue").text(csym() + fmt(due));
  }

  $("#id_discount_type, #id_discount_value, #id_paid_amount").on("input change", recalcTotals);
  recalcTotals();
})(window.jQuery);

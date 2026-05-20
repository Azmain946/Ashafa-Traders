/**
 * QZ Tray silent printing for Ashafa Pharmacy ERP.
 * Receipt: ESC/POS raw. Labels: high-res QR raster for thermal printers.
 */
(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let cachedSettings = null;
  let securityConfigured = false;

  function notify(message, type) {
    if (window.bootstrap && document.getElementById("qzPrintAlert")) {
      const el = document.getElementById("qzPrintAlert");
      el.className = `alert alert-${type || "info"} mt-3`;
      el.textContent = message;
      el.classList.remove("d-none");
      return;
    }
    if (type === "danger") {
      console.error(message);
      alert(message);
    } else {
      console.log(message);
    }
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(options?.body ? { "Content-Type": "application/json", "X-CSRFToken": csrfToken } : {}),
        ...(options?.headers || {}),
      },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Request failed (${response.status})`);
    }
    return data;
  }

  async function configureSecurity() {
    if (!window.qz || securityConfigured) {
      return;
    }
    try {
      const certResponse = await fetch("/api/qz/certificate/", { cache: "no-store", credentials: "same-origin" });
      if (certResponse.ok) {
        const certificate = await certResponse.text();
        qz.security.setCertificatePromise(function (resolve, reject) {
          if (certificate && certificate.includes("BEGIN CERTIFICATE")) {
            resolve(certificate);
          } else {
            reject(new Error("Invalid QZ certificate file."));
          }
        });
        qz.security.setSignaturePromise(function (toSign) {
          return function (resolve, reject) {
            fetch(`/api/qz/sign/?request=${encodeURIComponent(toSign)}`, {
              credentials: "same-origin",
              cache: "no-store",
            })
              .then((response) => {
                if (!response.ok) {
                  return response.json().then((body) => {
                    throw new Error(body.error || "Signing failed");
                  });
                }
                return response.text();
              })
              .then(resolve)
              .catch(reject);
          };
        });
        console.info("QZ Tray signing enabled for silent printing.");
      } else {
        console.warn("QZ certificate endpoint returned", certResponse.status);
      }
    } catch (error) {
      console.warn("QZ signing setup failed:", error);
    }
    securityConfigured = true;
  }

  async function connectQZ() {
    if (!window.qz) {
      throw new Error("QZ Tray library failed to load. Check your internet connection or host qz-tray.js locally.");
    }
    await configureSecurity();
    if (!qz.websocket.isActive()) {
      await qz.websocket.connect({ retries: 5, delay: 1 });
    }
    return true;
  }

  async function ensureConnected() {
    try {
      return await connectQZ();
    } catch (error) {
      throw new Error(
        `Cannot connect to QZ Tray. Ensure QZ Tray is running on this computer. (${error.message || error})`,
      );
    }
  }

  async function loadPrinters() {
    await ensureConnected();
    const printers = await qz.printers.find();
    return printers.sort((a, b) => a.localeCompare(b));
  }

  async function loadPrinterSettings(force) {
    if (!force && cachedSettings) {
      return cachedSettings;
    }
    cachedSettings = await fetchJson("/api/printing/settings/");
    return cachedSettings;
  }

  async function savePrinterSettings(payload) {
    const data = await fetchJson("/api/printing/settings/save/", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    cachedSettings = data.settings;
    return cachedSettings;
  }

  function fillPrinterSelect(select, printers, selected) {
    if (!select) {
      return;
    }
    const current = selected || select.value;
    select.innerHTML = '<option value="">Select printer</option>';
    printers.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      if (name === current) {
        option.selected = true;
      }
      select.appendChild(option);
    });
    if (current && !printers.includes(current)) {
      const saved = document.createElement("option");
      saved.value = current;
      saved.textContent = `${current} (saved)`;
      saved.selected = true;
      select.insertBefore(saved, select.firstChild.nextSibling);
    }
  }

  async function refreshPrinterDropdowns() {
    const receiptSelect = document.getElementById("receiptPrinterSelect");
    const labelSelect = document.getElementById("labelPrinterSelect");
    if (!receiptSelect && !labelSelect) {
      return [];
    }
    const settings = await loadPrinterSettings();
    const printers = await loadPrinters();
    fillPrinterSelect(receiptSelect, printers, settings.receipt_printer_name);
    fillPrinterSelect(labelSelect, printers, settings.label_printer_name);
    return printers;
  }

  async function resolveReceiptPrinter(explicitName) {
    const settings = await loadPrinterSettings();
    const printerName = explicitName || settings.receipt_printer_name;
    if (!printerName) {
      throw new Error("Receipt printer is not configured. Open Settings and choose a receipt printer.");
    }
    return printerName;
  }

  async function resolveLabelPrinter(explicitName) {
    const settings = await loadPrinterSettings();
    const printerName = explicitName || settings.label_printer_name;
    if (!printerName) {
      throw new Error("Label printer is not configured. Open Settings and choose a label printer.");
    }
    return printerName;
  }

  async function printRawReceipt(printerName, receiptData) {
    await ensureConnected();
    const config = qz.configs.create(printerName);
    const payload = [
      {
        type: "raw",
        format: "plain",
        data: receiptData,
      },
    ];
    return qz.print(config, payload);
  }

  async function printReceipt(invoiceId) {
    const data = await fetchJson(`/api/invoices/${invoiceId}/receipt/`);
    const printerName = await resolveReceiptPrinter(data.printer_name);
    await printRawReceipt(printerName, data.receipt);
    notify("Receipt sent to printer.", "success");
    return true;
  }

  async function printTestReceipt() {
    const data = await fetchJson("/api/printing/test-receipt/");
    const printerName = await resolveReceiptPrinter(data.printer_name);
    await printRawReceipt(printerName, data.receipt);
    notify("Test receipt sent to printer.", "success");
    return true;
  }

  async function fetchImageAsBase64(url) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) {
      throw new Error("Could not load QR image for label printing.");
    }
    const blob = await response.blob();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = String(reader.result || "");
        resolve(result.split(",")[1] || "");
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function printLabel(batchId, copies) {
    const query = copies ? `?copies=${encodeURIComponent(copies)}` : "";
    const data = await fetchJson(`/api/batches/${batchId}/label/${query}`);
    const printerName = await resolveLabelPrinter(data.label_printer_name);
    const imageBase64 = await fetchImageAsBase64(data.image_url);
    await ensureConnected();
    const config = qz.configs.create(printerName, {
      copies: Number(data.copies || 1),
      size: { width: Number(data.label_width_mm || 20), height: Number(data.label_height_mm || 20) },
      units: "mm",
      colorType: "grayscale",
      interpolation: "nearest-neighbor",
      density: 300,
      rasterize: true,
      scaleContent: true,
    });
    const payload = [
      {
        type: "pixel",
        format: "image",
        flavor: "base64",
        data: imageBase64,
      },
    ];
    await qz.print(config, payload);
    notify(`Label sent to printer (${data.copies} cop${data.copies === 1 ? "y" : "ies"}).`, "success");
    return true;
  }

  async function printTestLabel() {
    const copies = document.getElementById("defaultLabelCopies")?.value || 1;
    const data = await fetchJson(`/api/printing/test-label/?copies=${encodeURIComponent(copies)}`);
    const printerName = await resolveLabelPrinter(data.label_printer_name);
    const imageBase64 = await fetchImageAsBase64(data.image_url);
    await ensureConnected();
    const config = qz.configs.create(printerName, {
      copies: Number(data.copies || 1),
      size: { width: Number(data.label_width_mm || 20), height: Number(data.label_height_mm || 20) },
      units: "mm",
      colorType: "grayscale",
      interpolation: "nearest-neighbor",
      density: 300,
      rasterize: true,
      scaleContent: true,
    });
    await qz.print(config, [
      {
        type: "pixel",
        format: "image",
        flavor: "base64",
        data: imageBase64,
      },
    ]);
    notify("Test label sent to printer.", "success");
    return true;
  }

  function bindSettingsPage() {
    const page = document.getElementById("printerSettingsCard");
    if (!page) {
      return;
    }

    const receiptSelect = document.getElementById("receiptPrinterSelect");
    const labelSelect = document.getElementById("labelPrinterSelect");
    const alertEl = document.getElementById("qzPrintAlert");

    function showStatus(message, type) {
      if (!alertEl) {
        notify(message, type);
        return;
      }
      alertEl.className = `alert alert-${type || "info"} mt-3`;
      alertEl.textContent = message;
      alertEl.classList.remove("d-none");
    }

    document.getElementById("refreshPrintersBtn")?.addEventListener("click", async () => {
      try {
        showStatus("Loading printers from QZ Tray...", "info");
        await refreshPrinterDropdowns();
        showStatus("Printer list refreshed.", "success");
      } catch (error) {
        showStatus(error.message, "danger");
      }
    });

    document.getElementById("savePrinterSettingsBtn")?.addEventListener("click", async () => {
      try {
        await savePrinterSettings({
          receipt_printer_name: receiptSelect?.value || "",
          label_printer_name: labelSelect?.value || "",
          default_label_copies: Number(document.getElementById("defaultLabelCopies")?.value || 1),
          receipt_paper_chars: Number(document.getElementById("receiptPaperChars")?.value || 46),
          label_width_mm: Number(document.getElementById("labelWidthMm")?.value || 20),
          label_height_mm: Number(document.getElementById("labelHeightMm")?.value || 20),
        });
        showStatus("Printer settings saved.", "success");
      } catch (error) {
        showStatus(error.message, "danger");
      }
    });

    document.getElementById("testReceiptPrintBtn")?.addEventListener("click", async () => {
      try {
        await printTestReceipt();
        showStatus("Test receipt sent to printer.", "success");
      } catch (error) {
        showStatus(error.message, "danger");
      }
    });

    document.getElementById("testLabelPrintBtn")?.addEventListener("click", async () => {
      try {
        await printTestLabel();
        showStatus("Test label sent to printer.", "success");
      } catch (error) {
        showStatus(error.message, "danger");
      }
    });

    loadPrinterSettings()
      .then(async (settings) => {
        document.getElementById("defaultLabelCopies") &&
          (document.getElementById("defaultLabelCopies").value = settings.default_label_copies || 1);
        document.getElementById("receiptPaperChars") &&
          (document.getElementById("receiptPaperChars").value = settings.receipt_paper_chars || 46);
        document.getElementById("labelWidthMm") &&
          (document.getElementById("labelWidthMm").value = settings.label_width_mm || 20);
        document.getElementById("labelHeightMm") &&
          (document.getElementById("labelHeightMm").value = settings.label_height_mm || 20);
        try {
          await refreshPrinterDropdowns();
          showStatus("Connected to QZ Tray. Printers loaded.", "success");
        } catch (error) {
          showStatus(
            `${error.message} Click Refresh Printers after starting QZ Tray.`,
            "warning",
          );
          fillPrinterSelect(receiptSelect, [], settings.receipt_printer_name);
          fillPrinterSelect(labelSelect, [], settings.label_printer_name);
        }
      })
      .catch((error) => showStatus(error.message, "danger"));
  }

  function bindInvoicePrintButtons() {
    document.querySelectorAll("[data-qz-print-receipt]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await printReceipt(button.dataset.qzPrintReceipt);
        } catch (error) {
          notify(error.message, "danger");
        }
      });
    });
    const autoInvoice = document.body.dataset.autoPrintReceipt;
    if (autoInvoice) {
      printReceipt(autoInvoice).catch((error) => notify(error.message, "danger"));
    }
  }

  function bindLabelPrintButtons() {
    const modalEl = document.getElementById("batchBarcodeDialog");
    if (!modalEl) {
      return;
    }
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    const labelInput = document.getElementById("batchLabelCount");
    let activeBatchId = "";

    document.querySelectorAll("[data-batch-label-print]").forEach((button) => {
      button.addEventListener("click", () => {
        activeBatchId = button.dataset.batchLabelPrint;
        labelInput.value = button.dataset.defaultLabels || "1";
        modal.show();
      });
    });

    document.getElementById("printBatchBarcode")?.addEventListener("click", async () => {
      try {
        await printLabel(activeBatchId, labelInput.value || 1);
        modal.hide();
      } catch (error) {
        notify(error.message, "danger");
      }
    });

    const params = new URLSearchParams(window.location.search);
    const batchId = params.get("print_label_batch");
    const labels = params.get("labels");
    if (batchId) {
      printLabel(batchId, labels || 1)
        .then(() => {
          params.delete("print_label_batch");
          params.delete("labels");
          const query = params.toString();
          history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
        })
        .catch((error) => notify(error.message, "danger"));
    }
  }

  window.PharmacyQz = {
    connectQZ,
    loadPrinters,
    loadPrinterSettings,
    savePrinterSettings,
    refreshPrinterDropdowns,
    printReceipt,
    printTestReceipt,
    printLabel,
    printTestLabel,
  };

  document.addEventListener("DOMContentLoaded", () => {
    bindSettingsPage();
    bindInvoicePrintButtons();
    bindLabelPrintButtons();
  });
})();

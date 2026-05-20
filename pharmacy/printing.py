"""Thermal receipt and QR label helpers for QZ Tray printing."""

from __future__ import annotations

import re
from decimal import Decimal
from io import BytesIO

import qrcode
from django.utils import timezone
from PIL import Image

from .models import AppSetting, ProductBatch, SalesInvoice

DEFAULT_LINE_CHARS = 46
QR_PREVIEW_PIXELS = 50
QR_PRINT_PIXELS = 256


def money_label(value) -> str:
    amount = Decimal(value or 0).quantize(Decimal("0.01"))
    return f"{amount} BDT"


def total_line(label: str, amount: str, line_chars: int = DEFAULT_LINE_CHARS) -> str:
    amount = str(amount)
    spaces = line_chars - len(label) - len(amount)
    if spaces < 1:
        spaces = 1
    return label + (" " * spaces) + amount


def item_line(name: str, qty, price, total, line_chars: int = DEFAULT_LINE_CHARS) -> str:
    right_text = f"{qty} x {price} = {total}"
    spaces = line_chars - len(name) - len(right_text)
    if spaces < 1:
        spaces = 1
        allowed_name = line_chars - len(right_text) - 1
        name = name[:allowed_name]
    return name + (" " * spaces) + right_text


def _format_datetime(invoice: SalesInvoice) -> str:
    when = timezone.localtime(invoice.created_at)
    return when.strftime("%Y-%m-%d %I:%M %p")


def build_receipt_escpos(invoice: SalesInvoice, app_settings: AppSetting | None = None) -> str:
    """Build ESC/POS plain-text receipt using the project's alignment rules."""
    settings = app_settings or AppSetting.load()
    line_chars = settings.receipt_paper_chars or DEFAULT_LINE_CHARS
    order_ref = invoice.order.order_number if invoice.order_id else invoice.invoice_number
    customer = invoice.customer_name or "Walk-in Customer"
    phone = invoice.customer_phone or ""

    item_rows = []
    for item in invoice.items.all().order_by("id"):
        unit = Decimal(item.unit_price).quantize(Decimal("0.01"))
        line_total = Decimal(item.line_total).quantize(Decimal("0.01"))
        item_rows.append(
            item_line(
                item.product_name,
                item.quantity,
                money_label(unit),
                money_label(line_total),
                line_chars=line_chars,
            )
        )

    divider = "-" * line_chars
    items_block = "\n".join(item_rows) if item_rows else item_line("No items", 0, money_label(0), money_label(0), line_chars)

    body = (
        "\x1B\x40"
        "\x1B\x74\x00"
        "\x1B\x4D\x00"
        "\x1B\x61\x01"
        "Cash Memo\r\n"
        f"{settings.store_name}\r\n"
        f"{settings.store_address or ''}\r\n"
        f"Phone No: {settings.store_phone}\r\n"
        "\r\n"
        "\x1B\x61\x00"
        f"Order ID: {order_ref}\n"
        f"Invoice: {invoice.invoice_number}\n"
        f"Date: {_format_datetime(invoice)}\n"
        f"Customer: {customer}\n"
    )
    if phone:
        body += f"Phone: {phone}\n"
    body += (
        f"{divider}\n"
        f"{'Items'.ljust(line_chars - len('Qty x Price'))}Qty x Price\n"
        f"{divider}\n"
        f"{items_block}\n"
        f"{divider}\n"
        f"{total_line('Subtotal:', money_label(invoice.subtotal), line_chars)}\n"
        f"{total_line('Discount:', money_label(invoice.discount_amount), line_chars)}\n"
        f"{total_line('Round off:', money_label(invoice.round_off_amount), line_chars)}\n"
        f"{total_line('TOTAL:', money_label(invoice.grand_total), line_chars)}\n"
        f"{total_line('Paid:', money_label(invoice.paid_amount), line_chars)}\n"
        f"{divider}\n"
        f"{total_line('Due:', money_label(invoice.due_amount), line_chars)}\n\n"
        "\x1B\x61\x01"
        f"{settings.invoice_footer or 'Thank you for your purchase!'}\n\n\n\n\n"
        "\n\n\n\n"
        "\x1D\x56\x01"
    )
    return body


def build_sample_receipt_escpos(app_settings: AppSetting | None = None) -> str:
    settings = app_settings or AppSetting.load()
    line_chars = settings.receipt_paper_chars or DEFAULT_LINE_CHARS
    divider = "-" * line_chars
    return (
        "\x1B\x40"
        "\x1B\x74\x00"
        "\x1B\x4D\x00"
        "\x1B\x61\x01"
        "Cash Memo\r\n"
        f"{settings.store_name}\r\n"
        f"{settings.store_address or 'Nangra Bazar, Bogura'}\r\n"
        f"Phone No: {settings.store_phone or '01734-356060'}\r\n"
        "\r\n"
        "\x1B\x61\x00"
        "Order ID: TEST-RECEIPT\n"
        f"Date: {timezone.localtime().strftime('%Y-%m-%d %I:%M %p')}\n"
        f"{divider}\n"
        f"{'Items'.ljust(line_chars - len('Qty x Price'))}Qty x Price\n"
        f"{divider}\n"
        f"{item_line('Paracetamol', 2, money_label(10), money_label(20), line_chars)}\n"
        f"{item_line('Napa', 1, money_label(20), money_label(20), line_chars)}\n"
        f"{item_line('Napa Extra Super Long Medicine Name', 12, money_label(999), money_label(11988), line_chars)}\n"
        f"{divider}\n"
        f"{total_line('TOTAL:', money_label(40), line_chars)}\n"
        f"{total_line('Paid:', money_label(20), line_chars)}\n"
        f"{divider}\n"
        f"{total_line('Due:', money_label(20), line_chars)}\n\n"
        "\x1B\x61\x01"
        f"{settings.invoice_footer or 'Thank you for your purchase!'}\n\n\n\n\n"
        "\n\n\n\n"
        "\x1D\x56\x01"
    )


def build_label_qr_payload(batch: ProductBatch) -> str:
    """
  Compact QR payload for reliable thermal scanning.
  Format: {identifier}|P{product_id}|{batch}|{expiry_yymmdd}|{tp_price}|{short_name}
  """
    product = batch.product
    identifier = batch.barcode or f"B{batch.id}"
    name = re.sub(r"[|\r\n]+", " ", (product.name or "Medicine"))[:20].strip()
    price = Decimal(batch.tp_price).quantize(Decimal("0.01"))
    batch_no = re.sub(r"[|\r\n]+", " ", batch.batch_number or "-")[:24]
    return f"{identifier}|P{product.id}|{batch_no}|{batch.expiry_date:%y%m%d}|{price}|{name}"


def parse_label_qr_payload(payload: str) -> dict | None:
    """Parse a label QR string back into structured fields."""
    text = (payload or "").strip()
    if not text:
        return None
    parts = text.split("|")
    if len(parts) < 4:
        return {"identifier": text}
    result = {
        "identifier": parts[0],
        "product_id": parts[1][1:] if parts[1].startswith("P") else parts[1],
        "batch_number": parts[2],
        "expiry_yymmdd": parts[3],
    }
    if len(parts) > 4:
        result["selling_price"] = parts[4]
    if len(parts) > 5:
        result["product_name"] = parts[5]
    return result


def generate_qr_png(batch: ProductBatch, pixel_size: int | None = None, *, for_print: bool = True) -> bytes:
    """
    Build a sharp 1-bit QR PNG sized for thermal labels.
    Preview uses 50px; print uses 256px with whole-module scaling (no blur).
    """
    if pixel_size is None:
        pixel_size = QR_PRINT_PIXELS if for_print else QR_PREVIEW_PIXELS
    pixel_size = max(QR_PREVIEW_PIXELS, min(512, int(pixel_size)))

    payload = build_label_qr_payload(batch)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=8,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color=0, back_color=255).convert("L")

    modules = image.size[0]
    scale = max(1, pixel_size // modules)
    scaled = modules * scale
    image = image.resize((scaled, scaled), Image.Resampling.NEAREST)
    image = image.point(lambda p: 0 if p < 128 else 255, mode="1")

    if scaled < pixel_size:
        canvas = Image.new("1", (pixel_size, pixel_size), 255)
        offset = (pixel_size - scaled) // 2
        canvas.paste(image, (offset, offset))
        image = canvas
    elif scaled > pixel_size:
        image = image.resize((pixel_size, pixel_size), Image.Resampling.NEAREST)

    buffer = BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def qr_image_url_path(batch_id: int, *, preview: bool = False) -> str:
    from django.urls import reverse

    if preview:
        return f"{reverse('api_batch_qr_png', args=[batch_id])}?preview=1"
    return f"{reverse('api_batch_qr_png', args=[batch_id])}?size={QR_PRINT_PIXELS}"


def printer_settings_payload(app_settings: AppSetting | None = None) -> dict:
    settings = app_settings or AppSetting.load()
    return {
        "receipt_printer_name": settings.receipt_printer_name,
        "label_printer_name": settings.label_printer_name,
        "default_label_copies": settings.default_label_copies,
        "receipt_paper_chars": settings.receipt_paper_chars,
        "label_width_mm": settings.label_width_mm,
        "label_height_mm": settings.label_height_mm,
        "store_name": settings.store_name,
        "qr_print_pixels": QR_PRINT_PIXELS,
    }


def label_print_payload(batch: ProductBatch, copies: int | None = None, app_settings: AppSetting | None = None) -> dict:
    settings = app_settings or AppSetting.load()
    count = copies if copies is not None else settings.default_label_copies
    count = max(1, int(count or 1))
    return {
        "batch_id": batch.id,
        "copies": count,
        "label_width_mm": settings.label_width_mm,
        "label_height_mm": settings.label_height_mm,
        "label_printer_name": settings.label_printer_name,
        "product_name": batch.product.display_name,
        "batch_number": batch.batch_number,
        "expiry_date": batch.expiry_date.isoformat(),
        "selling_price": str(batch.tp_price),
        "identifier": batch.barcode or f"BATCH-{batch.id}",
        "qr_payload": build_label_qr_payload(batch),
        "qr_print_pixels": QR_PRINT_PIXELS,
    }

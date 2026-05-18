"""Order/checkout, return, and antibiotic register logic."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.models import AppSetting
from apps.core.utils import money
from apps.customers.models import Customer
from apps.inventory.models import Product, ProductBatch, StockMovement
from apps.inventory.services import adjust_stock

from .models import (
    AntibioticRegisterEntry,
    InvoiceSequence,
    ReturnItem,
    ReturnTransaction,
    SalesInvoice,
    SalesInvoiceItem,
)


@dataclass
class CartLine:
    product_id: int
    batch_id: int
    quantity: int
    unit_price: Decimal
    discount: Decimal = Decimal("0.00")

    @property
    def line_total(self) -> Decimal:
        gross = self.unit_price * self.quantity
        return money(gross - self.discount)


# --- Cart helpers --------------------------------------------------------

CART_SESSION_KEY = "cart"


def get_cart(session) -> list[CartLine]:
    raw = session.get(CART_SESSION_KEY, [])
    out = []
    for row in raw:
        try:
            out.append(
                CartLine(
                    product_id=int(row["product_id"]),
                    batch_id=int(row["batch_id"]),
                    quantity=int(row["quantity"]),
                    unit_price=Decimal(row["unit_price"]),
                    discount=Decimal(row.get("discount", "0")),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


def save_cart(session, lines: list[CartLine]) -> None:
    session[CART_SESSION_KEY] = [
        {
            "product_id": line.product_id,
            "batch_id": line.batch_id,
            "quantity": line.quantity,
            "unit_price": str(line.unit_price),
            "discount": str(line.discount),
        }
        for line in lines
    ]
    session.modified = True


def clear_cart(session) -> None:
    session[CART_SESSION_KEY] = []
    session.modified = True


def add_to_cart(session, *, product_id: int, batch_id: int, quantity: int, unit_price, discount=0) -> list[CartLine]:
    lines = get_cart(session)
    for line in lines:
        if line.batch_id == batch_id:
            line.quantity += quantity
            line.unit_price = Decimal(str(unit_price))
            line.discount = Decimal(str(discount))
            break
    else:
        lines.append(
            CartLine(
                product_id=product_id,
                batch_id=batch_id,
                quantity=quantity,
                unit_price=Decimal(str(unit_price)),
                discount=Decimal(str(discount)),
            )
        )
    save_cart(session, lines)
    return lines


def update_cart_line(session, *, batch_id: int, quantity: int | None = None, unit_price=None, discount=None):
    lines = get_cart(session)
    for line in lines:
        if line.batch_id == batch_id:
            if quantity is not None:
                line.quantity = max(0, int(quantity))
            if unit_price is not None:
                line.unit_price = Decimal(str(unit_price))
            if discount is not None:
                line.discount = Decimal(str(discount))
    lines = [l for l in lines if l.quantity > 0]
    save_cart(session, lines)
    return lines


def remove_cart_line(session, batch_id: int):
    lines = [l for l in get_cart(session) if l.batch_id != batch_id]
    save_cart(session, lines)
    return lines


def cart_summary(session, *, discount_type="fixed", discount_value=0, tax_percent=0, paid_amount=0):
    lines = get_cart(session)
    subtotal = sum((l.line_total for l in lines), Decimal("0"))
    discount_value = Decimal(str(discount_value or 0))
    if discount_type == "percent":
        discount_amount = money(subtotal * discount_value / Decimal("100"))
    else:
        discount_amount = money(min(discount_value, subtotal))
    taxable = max(Decimal("0"), subtotal - discount_amount)
    tax_amount = money(taxable * Decimal(str(tax_percent or 0)) / Decimal("100"))
    total = money(taxable + tax_amount)
    paid = money(paid_amount or 0)
    due = money(total - paid)
    return {
        "lines": lines,
        "subtotal": money(subtotal),
        "discount_amount": discount_amount,
        "tax_amount": tax_amount,
        "total": total,
        "paid": paid,
        "due": due if due > 0 else Decimal("0.00"),
        "count": len(lines),
    }


# --- Invoice numbering ---------------------------------------------------


@transaction.atomic
def next_invoice_number() -> str:
    setting = AppSetting.load()
    today = timezone.localdate()
    key = today.strftime("%Y%m%d")
    seq, _ = InvoiceSequence.objects.select_for_update().get_or_create(day_key=key)
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    return f"{setting.invoice_prefix}-{key}-{seq.last_value:04d}"


# --- Checkout ------------------------------------------------------------


@transaction.atomic
def checkout(
    *,
    session,
    customer: Customer,
    discount_type: str = "fixed",
    discount_value=0,
    paid_amount=0,
    notes: str = "",
    user=None,
) -> SalesInvoice:
    summary = cart_summary(
        session,
        discount_type=discount_type,
        discount_value=discount_value,
        paid_amount=paid_amount,
    )
    if not summary["lines"]:
        raise ValidationError("Cart is empty.")

    # Lock all involved batches and verify stock + expiry.
    batch_ids = [l.batch_id for l in summary["lines"]]
    batches = {b.id: b for b in ProductBatch.objects.select_for_update().filter(id__in=batch_ids)}
    today = timezone.localdate()
    for line in summary["lines"]:
        batch = batches.get(line.batch_id)
        if not batch:
            raise ValidationError("A selected batch is no longer available.")
        if batch.expiry_date < today:
            raise ValidationError(f"Batch {batch.batch_number} has expired.")
        if batch.quantity < line.quantity:
            raise ValidationError(
                f"Insufficient stock for {batch.product.name} (batch {batch.batch_number}). "
                f"Available {batch.quantity}, requested {line.quantity}."
            )

    invoice = SalesInvoice.objects.create(
        invoice_number=next_invoice_number(),
        customer=customer,
        invoice_date=today,
        subtotal=summary["subtotal"],
        discount_type=discount_type,
        discount_value=Decimal(str(discount_value or 0)),
        discount_amount=summary["discount_amount"],
        tax_amount=summary["tax_amount"],
        total=summary["total"],
        paid_amount=summary["paid"],
        notes=notes,
        cashier=user,
    )
    invoice.recalc_status()
    invoice.save(update_fields=["due_amount", "payment_status"])

    for line in summary["lines"]:
        batch = batches[line.batch_id]
        SalesInvoiceItem.objects.create(
            invoice=invoice,
            product=batch.product,
            batch=batch,
            product_name=str(batch.product),
            batch_number=batch.batch_number,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount=line.discount,
            total=line.line_total,
        )
        adjust_stock(
            batch,
            quantity_change=-line.quantity,
            movement_type=StockMovement.TYPE_SALE,
            user=user,
            reference=invoice.invoice_number,
        )
        if batch.product.is_antibiotic:
            AntibioticRegisterEntry.objects.create(
                invoice=invoice,
                customer=customer,
                product=batch.product,
                quantity=line.quantity,
                unit_price=line.unit_price,
                total=line.line_total,
                sale_date=today,
            )

    clear_cart(session)
    return invoice


# --- Returns -------------------------------------------------------------


@transaction.atomic
def record_return(
    *,
    invoice: SalesInvoice | None,
    customer: Customer | None,
    reason: str,
    lines: list[dict],
    restock: bool = True,
    user=None,
) -> ReturnTransaction:
    if not lines:
        raise ValidationError("At least one item is required for a return.")

    tx = ReturnTransaction.objects.create(
        invoice=invoice,
        customer=customer or (invoice.customer if invoice else None),
        reason=reason,
        user=user,
        total_refund=Decimal("0"),
    )

    total = Decimal("0")
    for raw in lines:
        product_id = int(raw["product_id"])
        batch_id = int(raw["batch_id"])
        qty = int(raw["quantity"])
        if qty <= 0:
            continue
        unit_price = Decimal(str(raw.get("unit_price", 0)))
        line_total = money(unit_price * qty)
        batch = ProductBatch.objects.select_for_update().get(pk=batch_id)
        item = ReturnItem.objects.create(
            return_tx=tx,
            product_id=product_id,
            batch=batch,
            quantity=qty,
            unit_price=unit_price,
            total=line_total,
            restock=restock,
        )
        if restock:
            adjust_stock(
                batch,
                quantity_change=qty,
                movement_type=StockMovement.TYPE_RETURN_IN,
                user=user,
                reference=(invoice.invoice_number if invoice else f"RT-{tx.id}"),
            )
        total += line_total

    tx.total_refund = money(total)
    tx.save(update_fields=["total_refund"])
    return tx

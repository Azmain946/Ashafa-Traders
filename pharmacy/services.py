from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from .models import (
    AntibioticRegisterEntry,
    AppSetting,
    Customer,
    InvoiceSequence,
    Order,
    OrderSequence,
    Product,
    ProductBatch,
    ReminderItem,
    ReturnItem,
    ReturnTransaction,
    SalesInvoice,
    SalesInvoiceItem,
    StockMovement,
    Supplier,
)


MONEY = Decimal("0.01")
UNIT_MONEY = Decimal("0.00000001")

DASHBOARD_RANGE_KEYS = ("today", "this_week", "this_month", "this_year")

# Padded stock entry (ProductBatch.pk) length used in QR labels and search
STOCK_ENTRY_NUMBER_MAX_LEN = 13


def invalidate_dashboard_cache():
    for range_key in DASHBOARD_RANGE_KEYS:
        cache.delete(f"dashboard_metrics:{range_key}")


def stock_entry_pk_from_query(term):
    """If term is a 10–13 digit stock entry number, return ProductBatch.pk; else None."""
    t = (term or "").strip()
    if not t.isdigit() or len(t) < 10 or len(t) > STOCK_ENTRY_NUMBER_MAX_LEN:
        return None
    return int(t)


def money(value):
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)


def unit_money(value):
    return Decimal(value or 0).quantize(UNIT_MONEY, rounding=ROUND_HALF_UP)


def rounded_total(value):
    return Decimal(value or 0).to_integral_value(rounding=ROUND_FLOOR).quantize(MONEY)


def checkout_totals(subtotal, discount_percent=0, discount_amount=0):
    """Order-level discount then floor to whole taka (matches finalize_checkout)."""
    subtotal = money(subtotal)
    discount_percent = money(discount_percent)
    fixed_discount = money(discount_amount)
    percentage_discount = money(subtotal * discount_percent / Decimal("100.00"))
    total_discount = min(subtotal, percentage_discount + fixed_discount)
    unrounded_total = money(subtotal - total_discount)
    grand_total = rounded_total(unrounded_total)
    round_off_amount = money(unrounded_total - grand_total)
    return {
        "subtotal": subtotal,
        "discount_percent": discount_percent,
        "total_discount": money(total_discount),
        "unrounded_total": unrounded_total,
        "grand_total": grand_total,
        "round_off_amount": round_off_amount,
    }


def proportional_order_discount(line_total, invoice_subtotal, order_discount_amount):
    if invoice_subtotal <= 0 or order_discount_amount <= 0:
        return Decimal("0.00")
    return money(order_discount_amount * line_total / invoice_subtotal)


def refund_amount_for_returned_units(item, return_qty, invoice_subtotal, order_discount_amount):
    """Refund at effective per-unit price after order-level discount allocation."""
    if return_qty <= 0:
        return Decimal("0.00")
    line_discount_share = proportional_order_discount(item.line_total, invoice_subtotal, order_discount_amount)
    effective_line = money(item.line_total - line_discount_share)
    return money(effective_line / item.quantity * return_qty)


def remaining_sale_totals(remaining_lines, original_subtotal, order_discount_amount):
    """
    remaining_lines: list of dicts with line_total, buy_price, quantity.
    Returns subtotal, discount_amount, round_off, grand_total, profit_amount.
    """
    subtotal = money(sum(row["line_total"] for row in remaining_lines))
    if original_subtotal > 0 and order_discount_amount > 0:
        discount_amount = money(order_discount_amount * subtotal / original_subtotal)
    else:
        discount_amount = Decimal("0.00")
    unrounded_total = money(max(subtotal - discount_amount, Decimal("0.00")))
    grand_total = rounded_total(unrounded_total)
    round_off_amount = money(unrounded_total - grand_total)
    profit = Decimal("0.00")
    for row in remaining_lines:
        profit += money(row["line_total"] - row["buy_price"] * row["quantity"])
    profit_amount = money(profit - discount_amount)
    return subtotal, discount_amount, round_off_amount, grand_total, profit_amount


def payment_status_for_amounts(grand_total, paid_amount):
    paid_amount = money(paid_amount)
    grand_total = money(grand_total)
    due_amount = money(max(grand_total - paid_amount, Decimal("0.00")))
    if due_amount == 0:
        status = SalesInvoice.PAYMENT_PAID
    elif paid_amount == 0:
        status = SalesInvoice.PAYMENT_UNPAID
    else:
        status = SalesInvoice.PAYMENT_PARTIAL
    return paid_amount, due_amount, status


def generate_invoice_number(order=None):
    if order is not None:
        with transaction.atomic():
            locked_order = Order.objects.select_for_update().get(pk=order.pk)
            prefix = locked_order.order_number
            max_suffix = 0
            for inv in locked_order.invoices.only("invoice_number"):
                suffix = inv.invoice_number[len(prefix) :]
                if suffix.isdigit():
                    max_suffix = max(max_suffix, int(suffix))
            return f"{prefix}{max_suffix + 1}"
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = InvoiceSequence.objects.select_for_update().get_or_create(date=today)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
        return f"{today:%Y%m%d}{sequence.last_number:02d}"


def generate_order_number():
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = OrderSequence.objects.select_for_update().get_or_create(date=today)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
        return f"{today:%Y%m%d}{sequence.last_number:02d}"


def reserve_order_number(session):
    pending = session.get("pending_order_number")
    if pending and not Order.objects.filter(order_number=pending).exists():
        return pending
    pending = generate_order_number()
    session["pending_order_number"] = pending
    session.modified = True
    return pending


def current_cart(session):
    return session.setdefault("cart", {})


def cart_summary(session, discount_percent=0, discount_amount=0):
    cart = current_cart(session)
    today = timezone.localdate()
    batch_ids = [int(batch_id) for batch_id in cart.keys()]
    batches = {
        batch.id: batch
        for batch in ProductBatch.objects.filter(id__in=batch_ids, is_active=True)
        .select_related("product")
        .only(
            "id",
            "batch_number",
            "expiry_date",
            "stock_quantity",
            "tp_price",
            "mrp",
            "is_active",
            "product__id",
            "product__name",
            "product__generic_name",
            "product__strength",
            "product__thumbnail",
        )
    }
    items = []
    subtotal = Decimal("0.00")
    for batch_id, raw in cart.items():
        batch = batches.get(int(batch_id))
        if not batch or batch.expiry_date <= today:
            continue
        quantity = int(raw.get("quantity", 1))
        unit_price = unit_money(raw.get("unit_price", batch.tp_price))
        discount_percent = money(raw.get("discount_percent", 0))
        add_percent = money(raw.get("add_percent", 0))
        gross_line_total = money(unit_price * quantity)
        discount = money(gross_line_total * discount_percent / Decimal("100.00"))
        add_amount = money(gross_line_total * add_percent / Decimal("100.00"))
        line_total = max(money(gross_line_total - discount + add_amount), Decimal("0.00"))
        subtotal += line_total
        items.append(
            {
                "batch": batch,
                "product": batch.product,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount_percent": discount_percent,
                "add_percent": add_percent,
                "discount_amount": discount,
                "add_amount": add_amount,
                "line_total": line_total,
            }
        )
    totals = checkout_totals(subtotal, discount_percent, discount_amount)
    return {
        "items": items,
        "subtotal": totals["subtotal"],
        "discount_amount": totals["total_discount"],
        "round_off_amount": totals["round_off_amount"],
        "rounded_total": totals["grand_total"],
        "unrounded_total": totals["unrounded_total"],
        "count": sum(item["quantity"] for item in items),
    }


def add_or_update_cart_item(
    session,
    batch_id,
    quantity=1,
    unit_price=None,
    discount_percent=0,
    add_percent=0,
    replace=False,
):
    batch = ProductBatch.objects.select_related("product").get(pk=batch_id, is_active=True)
    if batch.stock_quantity <= 0:
        raise ValidationError("This batch has no available stock.")
    if batch.expiry_date <= timezone.localdate():
        raise ValidationError("This batch is expired and cannot be sold.")
    quantity = int(quantity)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")
    unit_price = unit_money(unit_price or batch.tp_price)
    discount_percent = money(discount_percent)
    add_percent = money(add_percent)
    cart = current_cart(session)
    key = str(batch_id)
    existing_qty = int(cart.get(key, {}).get("quantity", 0))
    new_qty = quantity if replace else existing_qty + quantity
    if new_qty > batch.stock_quantity:
        raise ValidationError(f"Only {batch.stock_quantity} units are available.")
    cart[key] = {
        "quantity": new_qty,
        "unit_price": str(unit_price),
        "discount_percent": str(discount_percent),
        "add_percent": str(add_percent),
    }
    session["cart"] = cart
    session.modified = True
    return cart_summary(session)


def remove_cart_item(session, batch_id):
    cart = current_cart(session)
    cart.pop(str(batch_id), None)
    session["cart"] = cart
    session.modified = True
    return cart_summary(session)


def clear_cart(session):
    session["cart"] = {}
    session.pop("pending_order_number", None)
    session.modified = True


def _resolve_customer(name, phone):
    name = (name or "").strip()
    phone = (phone or "").strip()
    if not phone:
        return None
    customer, created = Customer.objects.get_or_create(
        phone=phone,
        defaults={"name": name or "Walk-in Customer"},
    )
    if name and (created or not customer.name.strip() or customer.name == "Walk-in Customer"):
        customer.name = name
        customer.save(update_fields=["name", "updated_at"])
    return customer


@transaction.atomic
def finalize_checkout(session, checkout_data, user=None):
    discount_percent = money(checkout_data.get("discount_percent"))
    fixed_discount = money(checkout_data.get("discount_amount"))
    summary = cart_summary(session, discount_percent, fixed_discount)
    cart = current_cart(session)
    if not summary["items"]:
        if cart:
            raise ValidationError("Cart items are invalid, expired, or unavailable. Remove them and try again.")
        raise ValidationError("Cart is empty.")
    if len(cart) > len(summary["items"]):
        raise ValidationError("Some cart items are invalid, expired, or unavailable. Refresh the cart.")

    locked_batches = {
        batch.id: batch
        for batch in ProductBatch.objects.select_for_update()
        .filter(id__in=[item["batch"].id for item in summary["items"]])
        .select_related("product")
    }

    subtotal = Decimal("0.00")
    profit = Decimal("0.00")
    prepared_items = []
    for item in summary["items"]:
        locked_batch = locked_batches[item["batch"].id]
        if locked_batch.expiry_date <= timezone.localdate():
            raise ValidationError(f"{locked_batch.product.display_name} batch {locked_batch.batch_number} is expired.")
        if locked_batch.stock_quantity < item["quantity"]:
            raise ValidationError(f"Not enough stock for {locked_batch.product.display_name}.")
        line_total = money(item["line_total"])
        subtotal += line_total
        profit += money(line_total - locked_batch.buy_price * item["quantity"])
        prepared_items.append((locked_batch, item, line_total))

    totals = checkout_totals(subtotal, discount_percent, fixed_discount)
    total_discount = totals["total_discount"]
    grand_total = totals["grand_total"]
    round_off_amount = totals["round_off_amount"]
    paid_amount = min(money(checkout_data.get("paid_amount")), grand_total)
    paid_amount, due_amount, payment_status = payment_status_for_amounts(grand_total, paid_amount)

    customer = _resolve_customer(checkout_data.get("customer_name"), checkout_data.get("customer_phone"))
    order_number = session.pop("pending_order_number", None)
    if not order_number or Order.objects.filter(order_number=order_number).exists():
        order_number = generate_order_number()
    session.modified = True
    order = Order.objects.create(
        order_number=order_number,
        customer=customer,
        customer_name=(checkout_data.get("customer_name") or getattr(customer, "name", "") or "Walk-in Customer"),
        customer_phone=(checkout_data.get("customer_phone") or getattr(customer, "phone", "")),
        subtotal=money(subtotal),
        discount_amount=money(total_discount),
        round_off_amount=round_off_amount,
        grand_total=grand_total,
        paid_amount=paid_amount,
        due_amount=due_amount,
        payment_status=payment_status,
        notes=checkout_data.get("notes", ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    invoice = SalesInvoice.objects.create(
        order=order,
        invoice_number=generate_invoice_number(order),
        customer=customer,
        customer_name=(checkout_data.get("customer_name") or getattr(customer, "name", "") or "Walk-in Customer"),
        customer_phone=(checkout_data.get("customer_phone") or getattr(customer, "phone", "")),
        subtotal=money(subtotal),
        discount_percent=discount_percent,
        discount_amount=money(total_discount),
        round_off_amount=round_off_amount,
        grand_total=grand_total,
        paid_amount=paid_amount,
        due_amount=due_amount,
        profit_amount=money(profit - total_discount),
        payment_status=payment_status,
        notes=checkout_data.get("notes", ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )

    for locked_batch, item, line_total in prepared_items:
        locked_batch.stock_quantity = F("stock_quantity") - item["quantity"]
        locked_batch.save(update_fields=["stock_quantity"])
        locked_batch.refresh_from_db(fields=["stock_quantity"])
        invoice_item = SalesInvoiceItem.objects.create(
            invoice=invoice,
            product=locked_batch.product,
            product_batch=locked_batch,
            product_name=locked_batch.product.display_name,
            batch_number=locked_batch.batch_number,
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            discount_percent=item["discount_percent"],
            discount_amount=item["discount_amount"],
            line_total=line_total,
            buy_price=locked_batch.buy_price,
        )
        StockMovement.objects.create(
            product=locked_batch.product,
            product_batch=locked_batch,
            movement_type=StockMovement.SALE,
            quantity=-item["quantity"],
            quantity_after=locked_batch.stock_quantity,
            sales_invoice=invoice,
            note=f"Sold on invoice {invoice.invoice_number}",
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
        if locked_batch.product.is_antibiotic:
            AntibioticRegisterEntry.objects.create(
                invoice=invoice,
                customer=customer,
                product=locked_batch.product,
                quantity=item["quantity"],
                sale_date=invoice.invoice_date,
                price=line_total,
            )
    clear_cart(session)
    invalidate_dashboard_cache()
    return invoice


@transaction.atomic
def create_order_update_invoice(order, user=None):
    order = Order.objects.select_for_update().get(pk=order.pk)
    source_invoice = (
        SalesInvoice.objects.filter(order=order)
        .annotate(item_count=Count("items"))
        .filter(item_count__gt=0)
        .order_by("-created_at")
        .prefetch_related("items")
        .first()
    )
    discount_percent = source_invoice.discount_percent if source_invoice else Decimal("0.00")
    profit_amount = source_invoice.profit_amount if source_invoice else Decimal("0.00")
    invoice = SalesInvoice.objects.create(
        order=order,
        invoice_number=generate_invoice_number(order),
        customer=order.customer,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        subtotal=order.subtotal,
        discount_percent=discount_percent,
        discount_amount=order.discount_amount,
        round_off_amount=order.round_off_amount,
        grand_total=order.grand_total,
        paid_amount=order.paid_amount,
        due_amount=order.due_amount,
        profit_amount=profit_amount,
        payment_status=order.payment_status,
        notes=order.notes,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    if source_invoice:
        for item in source_invoice.items.all():
            SalesInvoiceItem.objects.create(
                invoice=invoice,
                product=item.product,
                product_batch=item.product_batch,
                product_name=item.product_name,
                batch_number=item.batch_number,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_percent=item.discount_percent,
                discount_amount=item.discount_amount,
                line_total=item.line_total,
                buy_price=item.buy_price,
                returned_quantity=item.returned_quantity,
            )
    invalidate_dashboard_cache()
    return invoice


@transaction.atomic
def adjust_stock(batch, action, quantity, note="", user=None):
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")
    locked_batch = ProductBatch.objects.select_for_update().select_related("product").get(pk=batch.pk)
    if action == "remove":
        if locked_batch.stock_quantity < quantity:
            raise ValidationError("Cannot remove more stock than available.")
        delta = -quantity
        movement_type = StockMovement.REMOVE
    else:
        delta = quantity
        movement_type = StockMovement.ADD
    locked_batch.stock_quantity = F("stock_quantity") + delta
    locked_batch.save(update_fields=["stock_quantity"])
    locked_batch.refresh_from_db(fields=["stock_quantity"])
    StockMovement.objects.create(
        product=locked_batch.product,
        product_batch=locked_batch,
        movement_type=movement_type,
        quantity=delta,
        quantity_after=locked_batch.stock_quantity,
        note=note,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    invalidate_dashboard_cache()
    return locked_batch


def lookup_return_invoice(invoice_number=None, phone=None, invoice_date=None):
    base_qs = (
        SalesInvoice.objects.select_related("customer", "order")
        .prefetch_related("items__product", "items__product_batch")
        .annotate(item_count=Count("items"))
        .filter(item_count__gt=0)
        .order_by("-created_at")
    )
    if invoice_number:
        lookup_value = invoice_number.strip()
        entry_pk = stock_entry_pk_from_query(lookup_value)
        if entry_pk is not None:
            invoice_ids = (
                SalesInvoiceItem.objects.filter(product_batch_id=entry_pk)
                .values_list("invoice_id", flat=True)
                .distinct()
                .order_by("-invoice_id")
            )
            for iid in invoice_ids:
                hit = base_qs.filter(pk=iid).first()
                if hit:
                    return hit
        order = Order.objects.filter(order_number__iexact=lookup_value).first()
        if order:
            invoice = (
                base_qs.filter(Q(order=order) | Q(invoice_number__startswith=order.order_number))
                .order_by("created_at")
                .first()
            )
            if invoice and invoice.order_id is None:
                invoice.order = order
                invoice.save(update_fields=["order", "updated_at"])
            return invoice
        return base_qs.filter(invoice_number__iexact=lookup_value).first()
    qs = base_qs
    if phone:
        matching_orders = Order.objects.filter(customer_phone__icontains=phone.strip())
        order_prefixes = [order.order_number for order in matching_orders]
        order_prefix_query = Q()
        for prefix in order_prefixes:
            order_prefix_query |= Q(invoice_number__startswith=prefix)
        qs = qs.filter(
            Q(customer_phone__icontains=phone.strip())
            | Q(customer__phone__icontains=phone.strip())
            | Q(order__customer_phone__icontains=phone.strip())
            | order_prefix_query
        )
    if invoice_date:
        matching_orders = Order.objects.filter(order_date=invoice_date)
        order_prefix_query = Q()
        for order in matching_orders:
            order_prefix_query |= Q(invoice_number__startswith=order.order_number)
        qs = qs.filter(Q(invoice_date=invoice_date) | Q(order__order_date=invoice_date) | order_prefix_query)
    return qs.first()


def resolve_return_invoice(invoice):
    if not invoice:
        return None
    invoice = (
        SalesInvoice.objects.select_related("customer", "order")
        .prefetch_related("items__product", "items__product_batch")
        .annotate(item_count=Count("items"))
        .filter(pk=invoice.pk)
        .first()
    )
    if invoice and invoice.item_count:
        return invoice
    if invoice and invoice.order_id:
        resolved = (
            SalesInvoice.objects.select_related("customer", "order")
            .prefetch_related("items__product", "items__product_batch")
            .annotate(item_count=Count("items"))
            .filter(Q(order=invoice.order) | Q(invoice_number__startswith=invoice.order.order_number), item_count__gt=0)
            .order_by("created_at")
            .first()
        )
        if resolved and resolved.order_id is None:
            resolved.order = invoice.order
            resolved.save(update_fields=["order", "updated_at"])
        return resolved
    return invoice


def _invoice_with_returnable_lines(invoice):
    """Prefer the earliest sale invoice for an order when the given row has no returnable qty."""
    if not invoice:
        return None
    if invoice.items.filter(returned_quantity__lt=F("quantity")).exists():
        return invoice
    if not invoice.order_id:
        return invoice
    return (
        SalesInvoice.objects.filter(order=invoice.order)
        .annotate(item_count=Count("items"))
        .filter(item_count__gt=0)
        .order_by("created_at")
        .prefetch_related("items__product", "items__product_batch")
        .first()
    )


@transaction.atomic
def process_return(invoice, quantities, refund_method=ReturnTransaction.REFUND_ADJUST_DUE, user=None, notes=""):
    if not invoice:
        raise ValidationError("Invoice is required.")
    invoice = SalesInvoice.objects.select_for_update().get(pk=invoice.pk)
    invoice = _invoice_with_returnable_lines(invoice)
    if not invoice:
        raise ValidationError("Invoice is required.")
    invoice = SalesInvoice.objects.select_for_update().get(pk=invoice.pk)
    original_subtotal = money(invoice.subtotal)
    order_discount_amount = money(invoice.discount_amount)

    locked_items = list(
        SalesInvoiceItem.objects.select_for_update()
        .filter(invoice=invoice)
        .select_related("product", "product_batch")
    )
    total_refund = Decimal("0.00")
    return_items = []
    for item in locked_items:
        qty = int(quantities.get(str(item.id), 0) or 0)
        if qty <= 0:
            continue
        if qty > item.returnable_quantity:
            raise ValidationError(f"Cannot return more than sold for {item.product_name}.")
        refund_amount = refund_amount_for_returned_units(item, qty, original_subtotal, order_discount_amount)
        total_refund += refund_amount
        return_items.append((item, qty, refund_amount))
    if not return_items:
        raise ValidationError("Choose at least one item to return.")
    total_refund = money(total_refund)

    transaction_obj = ReturnTransaction.objects.create(
        invoice=invoice,
        customer=invoice.customer,
        phone=invoice.customer_phone,
        refund_method=refund_method,
        total_refund=total_refund,
        notes=notes,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for item, qty, refund_amount in return_items:
        batch = ProductBatch.objects.select_for_update().get(pk=item.product_batch_id)
        batch.stock_quantity = F("stock_quantity") + qty
        batch.save(update_fields=["stock_quantity"])
        batch.refresh_from_db(fields=["stock_quantity"])
        item.returned_quantity = F("returned_quantity") + qty
        item.save(update_fields=["returned_quantity"])
        item.refresh_from_db(fields=["returned_quantity"])
        ReturnItem.objects.create(
            return_transaction=transaction_obj,
            invoice_item=item,
            quantity=qty,
            refund_amount=refund_amount,
            restock=True,
        )
        StockMovement.objects.create(
            product=item.product,
            product_batch=batch,
            movement_type=StockMovement.RETURN,
            quantity=qty,
            quantity_after=batch.stock_quantity,
            sales_invoice=invoice,
            return_transaction=transaction_obj,
            note=f"Return for {invoice.invoice_number}",
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
        if item.product.is_antibiotic:
            entry = AntibioticRegisterEntry.objects.filter(invoice=invoice, product=item.product).order_by("-id").first()
            if entry:
                entry.quantity = max(0, entry.quantity - qty)
                if entry.quantity <= 0:
                    entry.delete()
                else:
                    unit_effective = refund_amount_for_returned_units(
                        item, 1, original_subtotal, order_discount_amount
                    )
                    entry.price = money(unit_effective * entry.quantity)
                    entry.save(update_fields=["quantity", "price", "updated_at"])

    invoice.refresh_from_db()
    remaining_rows = []
    prepared_remaining = []
    for item in invoice.items.select_related("product", "product_batch").all():
        remaining_qty = item.returnable_quantity
        if remaining_qty <= 0:
            continue
        unit_line_total = money(item.line_total / item.quantity)
        line_total = money(unit_line_total * remaining_qty)
        line_discount = money((item.discount_amount / item.quantity) * remaining_qty) if item.discount_amount else Decimal("0.00")
        remaining_rows.append(
            {"line_total": line_total, "buy_price": item.buy_price, "quantity": remaining_qty}
        )
        prepared_remaining.append((item, remaining_qty, line_total, line_discount))

    subtotal, discount_rem, round_off_amount, grand_total, profit_amount = remaining_sale_totals(
        remaining_rows, original_subtotal, order_discount_amount
    )

    order = invoice.order
    if order:
        order = Order.objects.select_for_update().get(pk=order.pk)
    base_paid = money(order.paid_amount if order else invoice.paid_amount)
    paid_amount = money(max(base_paid - total_refund, Decimal("0.00")))
    paid_amount, due_amount, payment_status = payment_status_for_amounts(grand_total, paid_amount)

    if order:
        order.subtotal = subtotal
        order.discount_amount = discount_rem
        order.round_off_amount = round_off_amount
        order.grand_total = grand_total
        order.paid_amount = paid_amount
        order.due_amount = due_amount
        order.payment_status = payment_status
        order.notes = notes or order.notes
        order.save(
            update_fields=[
                "subtotal",
                "discount_amount",
                "round_off_amount",
                "grand_total",
                "paid_amount",
                "due_amount",
                "payment_status",
                "notes",
                "updated_at",
            ]
        )

    new_invoice = SalesInvoice.objects.create(
        order=order,
        invoice_number=generate_invoice_number(order) if order else generate_invoice_number(),
        customer=invoice.customer,
        customer_name=invoice.customer_name,
        customer_phone=invoice.customer_phone,
        subtotal=subtotal,
        discount_percent=invoice.discount_percent,
        discount_amount=discount_rem,
        round_off_amount=round_off_amount,
        grand_total=grand_total,
        paid_amount=paid_amount,
        due_amount=due_amount,
        profit_amount=profit_amount,
        payment_status=payment_status,
        notes=notes or f"Return adjustment for {invoice.invoice_number}",
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for source_item, remaining_qty, line_total, line_discount in prepared_remaining:
        SalesInvoiceItem.objects.create(
            invoice=new_invoice,
            product=source_item.product,
            product_batch=source_item.product_batch,
            product_name=source_item.product_name,
            batch_number=source_item.batch_number,
            quantity=remaining_qty,
            unit_price=source_item.unit_price,
            discount_percent=source_item.discount_percent,
            discount_amount=line_discount,
            line_total=line_total,
            buy_price=source_item.buy_price,
        )

    invalidate_dashboard_cache()
    return transaction_obj, new_invoice


def _order_profit_subquery():
    return (
        SalesInvoice.objects.filter(order_id=OuterRef("pk"))
        .annotate(item_count=Count("items"))
        .filter(item_count__gt=0)
        .order_by("-created_at")
        .values("profit_amount")[:1]
    )


def dashboard_metrics(range_key="this_month"):
    cache_key = f"dashboard_metrics:{range_key}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    today = timezone.localdate()
    if range_key == "today":
        start = today
    elif range_key == "this_week":
        start = today - timedelta(days=today.weekday())
    elif range_key == "this_year":
        start = today.replace(month=1, day=1)
    else:
        start = today.replace(day=1)

    profit_subquery = _order_profit_subquery()
    orders = Order.objects.filter(order_date__gte=start).annotate(
        order_profit=Coalesce(
            Subquery(profit_subquery, output_field=DecimalField(max_digits=12, decimal_places=2)),
            Decimal("0.00"),
            output_field=DecimalField(),
        )
    )
    totals = orders.aggregate(
        total_sales=Coalesce(Sum("grand_total"), Decimal("0.00"), output_field=DecimalField()),
        total_profit=Coalesce(Sum("order_profit"), Decimal("0.00"), output_field=DecimalField()),
        total_due=Coalesce(Sum("due_amount"), Decimal("0.00"), output_field=DecimalField()),
    )
    top_buying = (
        Customer.objects.annotate(
            total=Coalesce(Sum("orders__grand_total"), Decimal("0.00"), output_field=DecimalField())
        )
        .order_by("-total")[:5]
    )
    top_due = (
        Customer.objects.annotate(
            total=Coalesce(Sum("orders__due_amount"), Decimal("0.00"), output_field=DecimalField())
        )
        .filter(total__gt=0)
        .order_by("-total")[:5]
    )
    supplier_due = Supplier.objects.aggregate(
        total=Coalesce(Sum("purchase_invoices__due_amount"), Decimal("0.00"), output_field=DecimalField())
    )["total"]
    monthly_orders = Order.objects.annotate(
        month=TruncMonth("order_date"),
        order_profit=Coalesce(
            Subquery(profit_subquery, output_field=DecimalField(max_digits=12, decimal_places=2)),
            Decimal("0.00"),
            output_field=DecimalField(),
        ),
    )
    monthly = (
        monthly_orders.values("month")
        .annotate(total=Sum("grand_total"), profit=Sum("order_profit"))
        .order_by("month")
    )
    result = {
        **totals,
        "total_customers": Customer.objects.count(),
        "top_buying": list(top_buying),
        "top_due": list(top_due),
        "supplier_due": supplier_due or Decimal("0.00"),
        "monthly": list(monthly),
    }
    cache.set(cache_key, result, 60)
    return result


def reminder_data():
    app_settings = AppSetting.load()
    today = timezone.localdate()
    expiry_cutoff = today + timedelta(days=30)
    low_stock_products = (
        Product.objects.filter(is_active=True)
        .annotate(total=Coalesce(Sum("batches__stock_quantity"), 0))
        .filter(total__lte=F("reorder_level"))
        .select_related("category", "brand")
        .order_by("total", "name")
    )
    expiring_batches = (
        ProductBatch.objects.filter(
            is_active=True,
            stock_quantity__gt=0,
            expiry_date__gte=today,
            expiry_date__lte=expiry_cutoff,
        )
        .select_related("product")
        .order_by("expiry_date")
    )
    return {"low_stock_products": low_stock_products, "expiring_batches": expiring_batches, "settings": app_settings}


@transaction.atomic
def delete_order_completely(order):
    """Delete an order and its invoices (and related return rows)."""
    for inv in list(order.invoices.all()):
        ReturnTransaction.objects.filter(invoice=inv).delete()
        inv.delete()
    order.delete()
    invalidate_dashboard_cache()


@transaction.atomic
def delete_customer_completely(customer):
    """Delete a customer after removing all their orders."""
    for ord_ in list(customer.orders.all()):
        delete_order_completely(ord_)
    customer.delete()
    invalidate_dashboard_cache()


@transaction.atomic
def delete_product_completely(product):
    """Delete a product if it is not referenced by invoice lines."""
    if SalesInvoiceItem.objects.filter(product=product).exists():
        raise ValidationError("Cannot delete this product: it appears on sales invoices.")
    AntibioticRegisterEntry.objects.filter(product=product).delete()
    product.delete()
    invalidate_dashboard_cache()


def search_products(term, limit=8):
    term = (term or "").strip()
    entry_pk = stock_entry_pk_from_query(term)
    if entry_pk is not None:
        return (
            ProductBatch.objects.filter(pk=entry_pk, is_active=True)
            .select_related("product", "product__brand")
            .only(
                "id",
                "batch_number",
                "barcode",
                "expiry_date",
                "stock_quantity",
                "tp_price",
                "mrp",
                "product__id",
                "product__name",
                "product__generic_name",
                "product__strength",
                "product__thumbnail",
                "product__image",
                "product__barcode",
                "product__brand__name",
            )
            .order_by("product__name", "expiry_date")[:limit]
        )
    if len(term) < 2:
        return ProductBatch.objects.none()
    return (
        ProductBatch.objects.filter(is_active=True, stock_quantity__gt=0, expiry_date__gt=timezone.localdate())
        .filter(
            Q(product__name__icontains=term)
            | Q(product__generic_name__icontains=term)
            | Q(product__barcode__icontains=term)
            | Q(batch_number__icontains=term)
            | Q(barcode__icontains=term)
        )
        .select_related("product", "product__brand")
        .only(
            "id",
            "batch_number",
            "barcode",
            "expiry_date",
            "stock_quantity",
            "tp_price",
            "mrp",
            "product__id",
            "product__name",
            "product__generic_name",
            "product__strength",
            "product__thumbnail",
            "product__image",
            "product__barcode",
            "product__brand__name",
        )
        .order_by("product__name", "expiry_date")[:limit]
    )

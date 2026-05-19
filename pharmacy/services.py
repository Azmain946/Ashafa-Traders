from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
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


def money(value):
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)


def unit_money(value):
    return Decimal(value or 0).quantize(UNIT_MONEY, rounding=ROUND_HALF_UP)


def rounded_total(value):
    return Decimal(value or 0).to_integral_value(rounding=ROUND_FLOOR).quantize(MONEY)


def generate_invoice_number():
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = InvoiceSequence.objects.select_for_update().get_or_create(date=today)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
        return f"INV-{today:%Y%m%d}-{sequence.last_number:04d}"


def generate_order_number():
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = OrderSequence.objects.select_for_update().get_or_create(date=today)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
        return f"ORD-{today:%Y%m%d}-{sequence.last_number:04d}"


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


def cart_summary(session):
    cart = current_cart(session)
    batch_ids = [int(batch_id) for batch_id in cart.keys()]
    batches = {
        batch.id: batch
        for batch in ProductBatch.objects.filter(id__in=batch_ids)
        .select_related("product")
        .only(
            "id",
            "batch_number",
            "expiry_date",
            "stock_quantity",
            "tp_price",
            "mrp",
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
        if not batch:
            continue
        quantity = int(raw.get("quantity", 1))
        unit_price = unit_money(raw.get("unit_price", batch.tp_price))
        discount_percent = money(raw.get("discount_percent", 0))
        gross_line_total = money(unit_price * quantity)
        discount = money(gross_line_total * discount_percent / Decimal("100.00"))
        line_total = max(money(gross_line_total - discount), Decimal("0.00"))
        subtotal += line_total
        items.append(
            {
                "batch": batch,
                "product": batch.product,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount_percent": discount_percent,
                "discount_amount": discount,
                "line_total": line_total,
            }
        )
    rounded = rounded_total(subtotal)
    return {
        "items": items,
        "subtotal": money(subtotal),
        "round_off_amount": money(subtotal - rounded),
        "rounded_total": rounded,
        "count": sum(item["quantity"] for item in items),
    }


def add_or_update_cart_item(session, batch_id, quantity=1, unit_price=None, discount_percent=0, replace=False):
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
    customer, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": name or "Walk-in Customer"})
    if name and customer.name != name:
        customer.name = name
        customer.save(update_fields=["name", "updated_at"])
    return customer


@transaction.atomic
def finalize_checkout(session, checkout_data, user=None):
    summary = cart_summary(session)
    if not summary["items"]:
        raise ValidationError("Cart is empty.")

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
        line_total = money(item["unit_price"] * item["quantity"] - item["discount_amount"])
        subtotal += line_total
        profit += money((item["unit_price"] - locked_batch.buy_price) * item["quantity"] - item["discount_amount"])
        prepared_items.append((locked_batch, item, line_total))

    discount_percent = money(checkout_data.get("discount_percent"))
    fixed_discount = money(checkout_data.get("discount_amount"))
    percentage_discount = money(subtotal * discount_percent / Decimal("100.00"))
    total_discount = min(subtotal, percentage_discount + fixed_discount)
    unrounded_total = money(subtotal - total_discount)
    grand_total = rounded_total(unrounded_total)
    round_off_amount = money(unrounded_total - grand_total)
    paid_amount = min(money(checkout_data.get("paid_amount")), grand_total)
    due_amount = money(grand_total - paid_amount)
    if due_amount == 0:
        payment_status = SalesInvoice.PAYMENT_PAID
    elif paid_amount == 0:
        payment_status = SalesInvoice.PAYMENT_UNPAID
    else:
        payment_status = SalesInvoice.PAYMENT_PARTIAL

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
        invoice_number=generate_invoice_number(),
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
    cache.delete("dashboard_metrics")
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
    cache.delete("dashboard_metrics")
    return locked_batch


def lookup_return_invoice(invoice_number=None, phone=None, invoice_date=None):
    qs = (
        SalesInvoice.objects.select_related("customer")
        .prefetch_related("items__product", "items__product_batch")
        .order_by("-created_at")
    )
    if invoice_number:
        qs = qs.filter(invoice_number__iexact=invoice_number.strip())
    if phone:
        qs = qs.filter(Q(customer_phone__icontains=phone.strip()) | Q(customer__phone__icontains=phone.strip()))
    if invoice_date:
        qs = qs.filter(invoice_date=invoice_date)
    return qs.first()


@transaction.atomic
def process_return(invoice, quantities, refund_method=ReturnTransaction.REFUND_ADJUST_DUE, user=None, notes=""):
    if not invoice:
        raise ValidationError("Invoice is required.")
    locked_items = (
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
        refund_amount = money(item.unit_price * qty)
        total_refund += refund_amount
        return_items.append((item, qty, refund_amount))
    if not return_items:
        raise ValidationError("Choose at least one item to return.")

    transaction_obj = ReturnTransaction.objects.create(
        invoice=invoice,
        customer=invoice.customer,
        phone=invoice.customer_phone,
        refund_method=refund_method,
        total_refund=money(total_refund),
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

    invoice.grand_total = money(max(invoice.grand_total - total_refund, Decimal("0.00")))
    invoice.due_amount = money(max(invoice.grand_total - invoice.paid_amount, Decimal("0.00")))
    invoice.payment_status = (
        SalesInvoice.PAYMENT_PAID
        if invoice.due_amount == 0
        else SalesInvoice.PAYMENT_PARTIAL
        if invoice.paid_amount
        else SalesInvoice.PAYMENT_UNPAID
    )
    invoice.save(update_fields=["grand_total", "due_amount", "payment_status", "updated_at"])
    cache.delete("dashboard_metrics")
    return transaction_obj


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

    invoices = SalesInvoice.objects.filter(invoice_date__gte=start)
    totals = invoices.aggregate(
        total_sales=Coalesce(Sum("grand_total"), Decimal("0.00"), output_field=DecimalField()),
        total_profit=Coalesce(Sum("profit_amount"), Decimal("0.00"), output_field=DecimalField()),
        total_due=Coalesce(Sum("due_amount"), Decimal("0.00"), output_field=DecimalField()),
    )
    top_buying = (
        Customer.objects.annotate(total=Coalesce(Sum("invoices__grand_total"), Decimal("0.00"), output_field=DecimalField()))
        .order_by("-total")[:5]
    )
    top_due = (
        Customer.objects.annotate(total=Coalesce(Sum("invoices__due_amount"), Decimal("0.00"), output_field=DecimalField()))
        .filter(total__gt=0)
        .order_by("-total")[:5]
    )
    supplier_due = Supplier.objects.aggregate(
        total=Coalesce(Sum("purchase_invoices__due_amount"), Decimal("0.00"), output_field=DecimalField())
    )["total"]
    monthly = (
        SalesInvoice.objects.annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(total=Sum("grand_total"), profit=Sum("profit_amount"))
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
    expiry_cutoff = today + timedelta(days=app_settings.near_expiry_days)
    low_stock_products = (
        Product.objects.filter(is_active=True)
        .annotate(total=Coalesce(Sum("batches__stock_quantity"), 0))
        .filter(total__lte=F("reorder_level"))
        .select_related("category", "brand")
        .order_by("total", "name")
    )
    expiring_batches = (
        ProductBatch.objects.filter(is_active=True, stock_quantity__gt=0, expiry_date__lte=expiry_cutoff)
        .select_related("product")
        .order_by("expiry_date")
    )
    return {"low_stock_products": low_stock_products, "expiring_batches": expiring_batches, "settings": app_settings}


def search_products(term, limit=8):
    term = (term or "").strip()
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

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Sum
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


def generate_invoice_number(order=None):
    if order is not None:
        next_number = order.invoices.count() + 1
        return f"{order.order_number}{next_number}"
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
    rounded = rounded_total(subtotal)
    return {
        "items": items,
        "subtotal": money(subtotal),
        "round_off_amount": money(subtotal - rounded),
        "rounded_total": rounded,
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
        line_total = money(item["line_total"])
        subtotal += line_total
        profit += money(line_total - locked_batch.buy_price * item["quantity"])
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
    cache.delete("dashboard_metrics")
    return invoice


@transaction.atomic
def create_order_update_invoice(order, user=None):
    order = Order.objects.select_for_update().select_related("customer").get(pk=order.pk)
    invoice = SalesInvoice.objects.create(
        order=order,
        invoice_number=generate_invoice_number(order),
        customer=order.customer,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        round_off_amount=order.round_off_amount,
        grand_total=order.grand_total,
        paid_amount=order.paid_amount,
        due_amount=order.due_amount,
        payment_status=order.payment_status,
        notes=order.notes,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
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
    base_qs = (
        SalesInvoice.objects.select_related("customer", "order")
        .prefetch_related("items__product", "items__product_batch")
        .annotate(item_count=Count("items"))
        .filter(item_count__gt=0)
        .order_by("-created_at")
    )
    if invoice_number:
        lookup_value = invoice_number.strip()
        order = Order.objects.filter(order_number__iexact=lookup_value).first()
        if order:
            invoice = base_qs.filter(Q(order=order) | Q(invoice_number__startswith=order.order_number)).first()
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
            .order_by("-created_at")
            .first()
        )
        if resolved and resolved.order_id is None:
            resolved.order = invoice.order
            resolved.save(update_fields=["order", "updated_at"])
        return resolved
    return invoice


@transaction.atomic
def process_return(invoice, quantities, refund_method=ReturnTransaction.REFUND_ADJUST_DUE, user=None, notes=""):
    if not invoice:
        raise ValidationError("Invoice is required.")
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
        per_unit_refund = money(item.line_total / item.quantity)
        refund_amount = money(per_unit_refund * qty)
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

    invoice.refresh_from_db()
    remaining_items = list(invoice.items.select_related("product", "product_batch").all())
    subtotal = Decimal("0.00")
    profit = Decimal("0.00")
    prepared_remaining = []
    for item in remaining_items:
        remaining_qty = item.returnable_quantity
        if remaining_qty <= 0:
            continue
        unit_line_total = money(item.line_total / item.quantity)
        line_total = money(unit_line_total * remaining_qty)
        discount_amount = money((item.discount_amount / item.quantity) * remaining_qty) if item.discount_amount else Decimal("0.00")
        subtotal += line_total
        profit += money((item.unit_price - item.buy_price) * remaining_qty - discount_amount)
        prepared_remaining.append((item, remaining_qty, line_total, discount_amount))

    grand_total = rounded_total(subtotal)
    round_off_amount = money(subtotal - grand_total)
    order = invoice.order
    paid_amount = money(getattr(order, "paid_amount", invoice.paid_amount))
    if refund_method == ReturnTransaction.REFUND_CASH:
        paid_amount = money(max(paid_amount - total_refund, Decimal("0.00")))
    due_amount = money(max(grand_total - paid_amount, Decimal("0.00")))
    payment_status = (
        SalesInvoice.PAYMENT_PAID
        if due_amount == 0
        else SalesInvoice.PAYMENT_PARTIAL
        if paid_amount
        else SalesInvoice.PAYMENT_UNPAID
    )

    if order:
        order.subtotal = money(subtotal)
        order.discount_amount = Decimal("0.00")
        order.round_off_amount = round_off_amount
        order.grand_total = grand_total
        order.paid_amount = paid_amount
        order.due_amount = due_amount
        order.payment_status = payment_status
        order.notes = notes or order.notes
        order.save(update_fields=["subtotal", "discount_amount", "round_off_amount", "grand_total", "paid_amount", "due_amount", "payment_status", "notes", "updated_at"])

    new_invoice = SalesInvoice.objects.create(
        order=order,
        invoice_number=generate_invoice_number(order) if order else generate_invoice_number(),
        customer=invoice.customer,
        customer_name=invoice.customer_name,
        customer_phone=invoice.customer_phone,
        subtotal=money(subtotal),
        discount_amount=Decimal("0.00"),
        round_off_amount=round_off_amount,
        grand_total=grand_total,
        paid_amount=paid_amount,
        due_amount=due_amount,
        profit_amount=money(profit),
        payment_status=payment_status,
        notes=notes or f"Return adjustment for {invoice.invoice_number}",
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for source_item, remaining_qty, line_total, discount_amount in prepared_remaining:
        SalesInvoiceItem.objects.create(
            invoice=new_invoice,
            product=source_item.product,
            product_batch=source_item.product_batch,
            product_name=source_item.product_name,
            batch_number=source_item.batch_number,
            quantity=remaining_qty,
            unit_price=source_item.unit_price,
            discount_percent=source_item.discount_percent,
            discount_amount=discount_amount,
            line_total=line_total,
            buy_price=source_item.buy_price,
        )

    invoice.grand_total = grand_total
    invoice.round_off_amount = round_off_amount
    invoice.due_amount = due_amount
    invoice.payment_status = payment_status
    invoice.save(update_fields=["grand_total", "round_off_amount", "due_amount", "payment_status", "updated_at"])
    cache.delete("dashboard_metrics")
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
    latest_entry_units = (
        ProductBatch.objects.filter(product_id=OuterRef("pk"), is_active=True)
        .order_by("-created_at")
        .annotate(entry_units=F("number_of_boxes") * F("units_per_box"))
        .values("entry_units")[:1]
    )
    low_stock_products = (
        Product.objects.filter(is_active=True)
        .annotate(
            total=Coalesce(Sum("batches__stock_quantity"), 0),
            latest_entry_units=Subquery(latest_entry_units, output_field=IntegerField()),
            low_stock_threshold=ExpressionWrapper(
                F("latest_entry_units") * 20 / 100,
                output_field=IntegerField(),
            ),
        )
        .filter(latest_entry_units__gt=0, total__lte=F("low_stock_threshold"))
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

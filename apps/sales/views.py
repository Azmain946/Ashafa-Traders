from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.customers.models import Customer
from apps.inventory.models import Product, ProductBatch

from .forms import CheckoutForm, ReturnLookupForm
from .models import (
    AntibioticRegisterEntry,
    PAYMENT_FULL,
    PAYMENT_PARTIAL,
    PAYMENT_DUE,
    SalesInvoice,
)
from .services import (
    add_to_cart,
    cart_summary,
    checkout,
    clear_cart,
    get_cart,
    record_return,
    remove_cart_line,
    update_cart_line,
)


# --- Order / cart page ---------------------------------------------------


@login_required
def order_page(request):
    summary = cart_summary(request.session)
    products_lookup = _products_lookup_for_lines(summary["lines"])
    return render(
        request,
        "sales/order.html",
        {
            "summary": summary,
            "products_lookup": products_lookup,
            "checkout_form": CheckoutForm(),
        },
    )


def _products_lookup_for_lines(lines):
    product_ids = {l.product_id for l in lines}
    batch_ids = {l.batch_id for l in lines}
    products = {p.id: p for p in Product.objects.filter(id__in=product_ids).select_related("manufacturer")}
    batches = {b.id: b for b in ProductBatch.objects.filter(id__in=batch_ids)}
    return {"products": products, "batches": batches}


def _cart_payload(request):
    summary = cart_summary(request.session)
    lookup = _products_lookup_for_lines(summary["lines"])
    return {
        "lines": [
            {
                "product_id": line.product_id,
                "batch_id": line.batch_id,
                "product_name": str(lookup["products"].get(line.product_id, "")),
                "batch_number": (lookup["batches"].get(line.batch_id).batch_number
                                  if lookup["batches"].get(line.batch_id) else ""),
                "quantity": line.quantity,
                "unit_price": float(line.unit_price),
                "discount": float(line.discount),
                "line_total": float(line.line_total),
            }
            for line in summary["lines"]
        ],
        "subtotal": float(summary["subtotal"]),
        "discount_amount": float(summary["discount_amount"]),
        "total": float(summary["total"]),
        "count": summary["count"],
    }


@login_required
@require_POST
def cart_add(request):
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid payload")

    try:
        batch_id = int(data["batch_id"])
        product_id = int(data["product_id"])
        quantity = max(1, int(data.get("quantity", 1)))
    except (KeyError, ValueError, TypeError):
        return HttpResponseBadRequest("Missing fields")

    batch = get_object_or_404(ProductBatch.objects.select_related("product"), pk=batch_id)
    if batch.product_id != product_id:
        return HttpResponseBadRequest("Product / batch mismatch")
    if batch.quantity < quantity:
        return JsonResponse({"ok": False, "error": "Insufficient stock"}, status=400)

    unit_price = data.get("unit_price")
    if unit_price in (None, ""):
        unit_price = batch.tp_price
    try:
        unit_price = Decimal(str(unit_price))
    except InvalidOperation:
        return HttpResponseBadRequest("Invalid price")

    add_to_cart(
        request.session,
        product_id=batch.product_id,
        batch_id=batch.id,
        quantity=quantity,
        unit_price=unit_price,
        discount=data.get("discount", 0),
    )
    return JsonResponse({"ok": True, "cart": _cart_payload(request)})


@login_required
@require_POST
def cart_update(request):
    try:
        data = json.loads(request.body or b"{}")
        batch_id = int(data["batch_id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return HttpResponseBadRequest("Invalid payload")

    update_cart_line(
        request.session,
        batch_id=batch_id,
        quantity=data.get("quantity"),
        unit_price=data.get("unit_price"),
        discount=data.get("discount"),
    )
    return JsonResponse({"ok": True, "cart": _cart_payload(request)})


@login_required
@require_POST
def cart_remove(request):
    try:
        data = json.loads(request.body or b"{}")
        batch_id = int(data["batch_id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return HttpResponseBadRequest("Invalid payload")
    remove_cart_line(request.session, batch_id)
    return JsonResponse({"ok": True, "cart": _cart_payload(request)})


@login_required
@require_POST
def cart_clear(request):
    clear_cart(request.session)
    return JsonResponse({"ok": True, "cart": _cart_payload(request)})


@login_required
@require_GET
def cart_summary_api(request):
    return JsonResponse({"ok": True, "cart": _cart_payload(request)})


# --- Checkout ------------------------------------------------------------


@login_required
@require_POST
def checkout_view(request):
    form = CheckoutForm(request.POST)
    if not form.is_valid():
        for err in form.errors.values():
            messages.error(request, err.as_text())
        return redirect("sales:order")

    try:
        customer = form.get_or_create_customer()
        invoice = checkout(
            session=request.session,
            customer=customer,
            discount_type=form.cleaned_data.get("discount_type") or "fixed",
            discount_value=form.cleaned_data.get("discount_value") or 0,
            paid_amount=form.cleaned_data.get("paid_amount") or 0,
            notes=form.cleaned_data.get("notes") or "",
            user=request.user,
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect("sales:order")

    messages.success(request, f"Invoice {invoice.invoice_number} created.")
    return redirect("sales:invoice_detail", pk=invoice.pk)


# --- Invoices ------------------------------------------------------------


@login_required
def invoice_list(request):
    qs = (
        SalesInvoice.objects.select_related("customer")
        .order_by("-invoice_date", "-id")
    )
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status")
    if q:
        qs = qs.filter(
            Q(invoice_number__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(customer__phone__icontains=q)
        )
    if status in {PAYMENT_FULL, PAYMENT_PARTIAL, PAYMENT_DUE}:
        qs = qs.filter(payment_status=status)

    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "sales/invoice_list.html", {"invoices": page, "q": q, "status": status})


@login_required
def invoice_detail(request, pk: int):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("customer", "cashier")
        .prefetch_related("items", "items__product"),
        pk=pk,
    )
    return render(request, "sales/invoice_detail.html", {"invoice": invoice})


@login_required
def invoice_print(request, pk: int):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("customer").prefetch_related("items"), pk=pk
    )
    return render(request, "sales/invoice_print.html", {"invoice": invoice})


# --- Returns -------------------------------------------------------------


@login_required
def returns_page(request):
    lookup_form = ReturnLookupForm(request.GET or None)
    invoice = None
    matched_invoices = []
    if request.GET and lookup_form.is_valid():
        qs = SalesInvoice.objects.select_related("customer").prefetch_related("items")
        number = lookup_form.cleaned_data.get("invoice_number")
        date = lookup_form.cleaned_data.get("invoice_date")
        phone = lookup_form.cleaned_data.get("phone")
        if number:
            qs = qs.filter(invoice_number__icontains=number)
        if date:
            qs = qs.filter(invoice_date=date)
        if phone:
            qs = qs.filter(customer__phone__icontains=phone)
        if any([number, date, phone]):
            matched_invoices = list(qs.order_by("-invoice_date")[:20])
        if len(matched_invoices) == 1:
            invoice = matched_invoices[0]

    recent_returns = (
        SalesInvoice.objects.filter(returns__isnull=False).distinct().order_by("-invoice_date")[:0]
    )
    from .models import ReturnTransaction

    history = ReturnTransaction.objects.select_related("invoice", "customer").order_by("-return_date")[:25]

    return render(
        request,
        "sales/returns.html",
        {
            "lookup_form": lookup_form,
            "invoice": invoice,
            "matched_invoices": matched_invoices,
            "history": history,
        },
    )


@login_required
@require_POST
def returns_submit(request):
    invoice_id = request.POST.get("invoice_id")
    invoice = SalesInvoice.objects.filter(pk=invoice_id).first() if invoice_id else None

    reason = request.POST.get("reason", "")
    restock = request.POST.get("restock") == "on"

    raw_items = request.POST.getlist("item_id")
    quantities = request.POST.getlist("quantity")
    lines = []
    if invoice:
        existing_items = {str(i.id): i for i in invoice.items.all()}
        for item_id, qty in zip(raw_items, quantities):
            try:
                qty_int = int(qty or 0)
            except ValueError:
                qty_int = 0
            if qty_int <= 0:
                continue
            item = existing_items.get(item_id)
            if not item:
                continue
            qty_int = min(qty_int, item.quantity)
            lines.append({
                "product_id": item.product_id,
                "batch_id": item.batch_id,
                "quantity": qty_int,
                "unit_price": str(item.unit_price),
            })

    if not lines:
        messages.error(request, "Select at least one item to return.")
        return redirect("sales:returns")

    try:
        record_return(
            invoice=invoice,
            customer=invoice.customer if invoice else None,
            reason=reason,
            lines=lines,
            restock=restock,
            user=request.user,
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect("sales:returns")

    messages.success(request, "Return recorded.")
    return redirect("sales:returns")


# --- Antibiotic register -------------------------------------------------


@login_required
def antibiotic_register(request):
    qs = (
        AntibioticRegisterEntry.objects.select_related("product", "customer", "invoice")
        .order_by("-sale_date", "-id")
    )
    q = request.GET.get("q", "").strip()
    start = request.GET.get("start")
    end = request.GET.get("end")
    if q:
        qs = qs.filter(
            Q(product__name__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(customer__phone__icontains=q)
        )
    if start:
        qs = qs.filter(sale_date__gte=start)
    if end:
        qs = qs.filter(sale_date__lte=end)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "sales/antibiotic_register.html",
        {"entries": page, "q": q, "start": start, "end": end},
    )

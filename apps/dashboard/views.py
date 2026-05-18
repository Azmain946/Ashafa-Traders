from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.models import AppSetting
from apps.core.utils import parse_date_range
from apps.customers.models import Customer
from apps.inventory.models import Product, ProductBatch, ProductCategory
from apps.sales.models import (
    PAYMENT_DUE,
    PAYMENT_PARTIAL,
    SalesInvoice,
    SalesInvoiceItem,
)
from apps.suppliers.models import PurchaseInvoice, Supplier


def _profit_for_period(start: date, end: date) -> Decimal:
    """Approximate profit = sum(line.total - batch.buy_price * qty)."""
    items = (
        SalesInvoiceItem.objects.filter(invoice__invoice_date__range=(start, end))
        .select_related("batch")
        .values("total", "quantity", "batch__buy_price")
    )
    profit = Decimal("0")
    for it in items:
        cost = (it["batch__buy_price"] or Decimal("0")) * it["quantity"]
        profit += (it["total"] or Decimal("0")) - cost
    return profit


@login_required
def home(request):
    """Pharmacy-style homepage with categories and featured products."""
    categories = ProductCategory.objects.annotate(
        product_count=Count("products", filter=Q(products__is_active=True))
    ).order_by("name")[:12]

    featured = (
        Product.objects.filter(is_active=True)
        .annotate(stock=Sum("batches__quantity"))
        .filter(stock__gt=0)
        .order_by("-updated_at")[:12]
    )
    recent_invoices = (
        SalesInvoice.objects.select_related("customer").order_by("-invoice_date", "-id")[:6]
    )

    return render(
        request,
        "dashboard/home.html",
        {
            "categories": categories,
            "featured_products": featured,
            "recent_invoices": recent_invoices,
        },
    )


@login_required
def dashboard(request):
    today = timezone.localdate()
    range_key = request.GET.get("range", "today")
    start_raw = request.GET.get("start")
    end_raw = request.GET.get("end")

    if start_raw and end_raw:
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except ValueError:
            start, end = parse_date_range(range_key, today)
    else:
        start, end = parse_date_range(range_key, today)

    invoices_in_range = SalesInvoice.objects.filter(invoice_date__range=(start, end))
    total_sales = invoices_in_range.aggregate(s=Coalesce(Sum("total"), Value(Decimal("0"))))["s"]
    total_paid = invoices_in_range.aggregate(s=Coalesce(Sum("paid_amount"), Value(Decimal("0"))))["s"]
    total_due_all = SalesInvoice.objects.aggregate(s=Coalesce(Sum("due_amount"), Value(Decimal("0"))))["s"]
    total_customers = Customer.objects.count()
    total_profit = _profit_for_period(start, end)

    top_buying = (
        Customer.objects.annotate(spent=Coalesce(Sum("sales_invoices__total"), Value(Decimal("0"))))
        .order_by("-spent")[:5]
    )
    top_due = (
        Customer.objects.annotate(due=Coalesce(Sum("sales_invoices__due_amount"), Value(Decimal("0"))))
        .filter(due__gt=0)
        .order_by("-due")[:5]
    )
    suppliers_due = (
        Supplier.objects.annotate(due=Coalesce(Sum("purchase_invoices__due_amount"), Value(Decimal("0"))))
        .filter(due__gt=0)
        .order_by("-due")[:5]
    )

    months_back = 11
    month_start = today.replace(day=1) - timedelta(days=months_back * 31)
    growth_qs = (
        SalesInvoice.objects.filter(invoice_date__gte=month_start)
        .annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(total=Sum("total"))
        .order_by("month")
    )
    growth_labels = [g["month"].strftime("%b %Y") for g in growth_qs]
    growth_values = [float(g["total"] or 0) for g in growth_qs]

    setting = AppSetting.load()
    low_stock_count = (
        Product.objects.annotate(stock=Coalesce(Sum("batches__quantity"), Value(0)))
        .filter(is_active=True, stock__lte=setting.low_stock_threshold)
        .count()
    )
    near_expiry_count = ProductBatch.objects.filter(
        quantity__gt=0,
        expiry_date__lte=today + timedelta(days=setting.near_expiry_days),
    ).count()

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "range_key": range_key,
            "start": start,
            "end": end,
            "total_sales": total_sales,
            "total_profit": total_profit,
            "total_paid": total_paid,
            "total_due": total_due_all,
            "total_customers": total_customers,
            "top_buying": top_buying,
            "top_due": top_due,
            "suppliers_due": suppliers_due,
            "growth_labels": growth_labels,
            "growth_values": growth_values,
            "low_stock_count": low_stock_count,
            "near_expiry_count": near_expiry_count,
        },
    )


@login_required
def dashboard_refresh(request):
    """JSON snapshot for AJAX refresh."""
    today = timezone.localdate()
    range_key = request.GET.get("range", "today")
    start, end = parse_date_range(range_key, today)
    inv = SalesInvoice.objects.filter(invoice_date__range=(start, end))
    payload = {
        "total_sales": float(inv.aggregate(s=Coalesce(Sum("total"), Value(Decimal("0"))))["s"]),
        "total_paid": float(inv.aggregate(s=Coalesce(Sum("paid_amount"), Value(Decimal("0"))))["s"]),
        "total_due": float(
            SalesInvoice.objects.aggregate(s=Coalesce(Sum("due_amount"), Value(Decimal("0"))))["s"]
        ),
        "total_profit": float(_profit_for_period(start, end)),
        "range": range_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    return JsonResponse(payload)

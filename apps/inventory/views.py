from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import AppSetting

from .forms import (
    ManufacturerForm,
    ProductBatchForm,
    ProductCategoryForm,
    ProductForm,
    StockAdjustmentForm,
)
from .models import Manufacturer, Product, ProductBatch, ProductCategory, StockMovement
from .services import adjust_stock


@login_required
def product_list(request):
    qs = (
        Product.objects.select_related("category", "manufacturer")
        .prefetch_related("batches")
        .order_by("name")
    )
    search = request.GET.get("q", "").strip()
    category_id = request.GET.get("category")
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(generic_name__icontains=search)
            | Q(barcode__iexact=search)
        )
    if category_id:
        qs = qs.filter(category_id=category_id)

    paginator = Paginator(qs, 24)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "inventory/product_list.html",
        {
            "products": page,
            "categories": ProductCategory.objects.all(),
            "q": search,
            "category_id": category_id,
        },
    )


@login_required
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, f"Product '{product.name}' created.")
        return redirect("inventory:product_detail", pk=product.pk)
    return render(request, "inventory/product_form.html", {"form": form, "create": True})


@login_required
def product_edit(request, pk: int):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product updated.")
        return redirect("inventory:product_detail", pk=product.pk)
    return render(request, "inventory/product_form.html", {"form": form, "create": False, "product": product})


@login_required
def product_detail(request, pk: int):
    product = get_object_or_404(
        Product.objects.select_related("category", "manufacturer"), pk=pk
    )
    batches = product.batches.all().order_by("expiry_date")
    movements = (
        StockMovement.objects.filter(batch__product=product)
        .select_related("batch", "user")
        .order_by("-created_at")[:25]
    )

    batch_form = ProductBatchForm()
    adjust_form = StockAdjustmentForm(product=product)

    return render(
        request,
        "inventory/product_detail.html",
        {
            "product": product,
            "batches": batches,
            "movements": movements,
            "batch_form": batch_form,
            "adjust_form": adjust_form,
        },
    )


@login_required
@require_POST
def product_batch_add(request, pk: int):
    product = get_object_or_404(Product, pk=pk)
    form = ProductBatchForm(request.POST)
    if form.is_valid():
        batch: ProductBatch = form.save(commit=False)
        batch.product = product
        batch.save()
        StockMovement.objects.create(
            batch=batch,
            movement_type=StockMovement.TYPE_INITIAL,
            quantity=batch.quantity,
            user=request.user,
            note="Batch created",
        )
        messages.success(request, f"Batch {batch.batch_number} added.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("inventory:product_detail", pk=product.pk)


@login_required
@require_POST
def product_stock_adjust(request, pk: int):
    product = get_object_or_404(Product, pk=pk)
    form = StockAdjustmentForm(request.POST, product=product)
    if form.is_valid():
        change = form.cleaned_data["quantity"]
        if form.cleaned_data["action"] == "remove":
            change = -change
        try:
            adjust_stock(
                form.cleaned_data["batch"],
                quantity_change=change,
                movement_type=StockMovement.TYPE_ADJUSTMENT,
                user=request.user,
                note=form.cleaned_data.get("note", ""),
            )
            messages.success(request, "Stock adjusted.")
        except Exception as exc:
            messages.error(request, str(exc))
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("inventory:product_detail", pk=product.pk)


# --- Categories ----------------------------------------------------------


@login_required
def category_list(request):
    cats = ProductCategory.objects.all()
    if request.method == "POST":
        form = ProductCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Category created.")
            return redirect("inventory:categories")
    else:
        form = ProductCategoryForm()
    return render(request, "inventory/categories.html", {"categories": cats, "form": form})


@login_required
def manufacturer_list(request):
    mans = Manufacturer.objects.all()
    if request.method == "POST":
        form = ManufacturerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Manufacturer created.")
            return redirect("inventory:manufacturers")
    else:
        form = ManufacturerForm()
    return render(request, "inventory/manufacturers.html", {"manufacturers": mans, "form": form})


# --- AJAX search ---------------------------------------------------------


@login_required
@require_GET
def product_search_api(request):
    """Lightweight autocomplete used by the order page."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    products = (
        Product.objects.filter(is_active=True)
        .filter(
            Q(name__icontains=q)
            | Q(generic_name__icontains=q)
            | Q(barcode__iexact=q)
        )
        .annotate(stock=Sum("batches__quantity"))
        .select_related("manufacturer")
        .order_by("name")[:10]
    )

    payload = []
    for p in products:
        thumb = p.thumbnail or p.image
        batches = list(p.sellable_batches()[:5])
        payload.append(
            {
                "id": p.id,
                "name": p.name,
                "generic_name": p.generic_name,
                "strength": p.strength,
                "manufacturer": p.manufacturer.name if p.manufacturer else "",
                "thumbnail": thumb.url if thumb else "",
                "tp_price": float(p.latest_tp_price),
                "mrp": float(p.latest_mrp),
                "stock": int(p.stock or 0),
                "is_antibiotic": p.is_antibiotic,
                "url": reverse("inventory:product_detail", args=[p.id]),
                "batches": [
                    {
                        "id": b.id,
                        "batch_number": b.batch_number,
                        "expiry_date": b.expiry_date.isoformat(),
                        "tp_price": float(b.tp_price),
                        "mrp": float(b.mrp),
                        "quantity": b.quantity,
                    }
                    for b in batches
                ],
            }
        )
    return JsonResponse({"results": payload})


# --- Reminders -----------------------------------------------------------


@login_required
def reminders_page(request):
    setting = AppSetting.load()
    today = timezone.localdate()
    near = today + timedelta(days=setting.near_expiry_days)

    low_stock_qs = (
        Product.objects.annotate(stock=Sum("batches__quantity"))
        .filter(is_active=True, stock__lte=setting.low_stock_threshold)
        .select_related("category", "manufacturer")
        .order_by("stock", "name")
    )

    expiring_qs = (
        ProductBatch.objects.filter(expiry_date__lte=near, quantity__gt=0)
        .select_related("product")
        .order_by("expiry_date")
    )

    return render(
        request,
        "inventory/reminders.html",
        {
            "low_stock": low_stock_qs,
            "expiring": expiring_qs,
            "low_stock_threshold": setting.low_stock_threshold,
            "near_expiry_days": setting.near_expiry_days,
            "today": today,
        },
    )

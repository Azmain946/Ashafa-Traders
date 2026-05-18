import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    AppSettingForm,
    BrandForm,
    CategoryForm,
    CheckoutForm,
    CustomerForm,
    ProductBatchForm,
    ProductForm,
    ReturnLookupForm,
    StockAdjustmentForm,
    StyledPasswordChangeForm,
    SupplierForm,
    SupplierReceiptForm,
    UserProfileForm,
)
from .models import (
    AntibioticRegisterEntry,
    AppSetting,
    Customer,
    Product,
    ProductBatch,
    ProductBrand,
    ProductCategory,
    PurchaseInvoice,
    SalesInvoice,
    Supplier,
    UserProfile,
)
from .services import (
    add_or_update_cart_item,
    adjust_stock,
    cart_summary,
    dashboard_metrics,
    finalize_checkout,
    lookup_return_invoice,
    process_return,
    remove_cart_item,
    reminder_data,
    search_products,
)


def paginate(request, queryset, per_page=20):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


@login_required
def home(request):
    categories = ProductCategory.objects.prefetch_related("products").all()[:8]
    featured_products = (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .prefetch_related("batches")
        .order_by("-updated_at")[:12]
    )
    recent_invoices = SalesInvoice.objects.only(
        "invoice_number", "customer_name", "grand_total", "created_at", "payment_status"
    )[:6]
    return render(
        request,
        "pharmacy/home.html",
        {
            "categories": categories,
            "featured_products": featured_products,
            "recent_invoices": recent_invoices,
        },
    )


@login_required
def order_page(request):
    checkout_form = CheckoutForm()
    return render(
        request,
        "pharmacy/order.html",
        {
            "cart": cart_summary(request.session),
            "checkout_form": checkout_form,
        },
    )


@login_required
@require_POST
def checkout(request):
    form = CheckoutForm(request.POST)
    if form.is_valid():
        try:
            invoice = finalize_checkout(request.session, form.cleaned_data, request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("order")
        messages.success(request, f"Invoice {invoice.invoice_number} created successfully.")
        return redirect("invoice_detail", pk=invoice.pk)
    messages.error(request, "Please fix the checkout form errors.")
    return render(request, "pharmacy/order.html", {"cart": cart_summary(request.session), "checkout_form": form})


@login_required
def dashboard(request):
    range_key = request.GET.get("range", "this_month")
    metrics = dashboard_metrics(range_key)
    return render(request, "pharmacy/dashboard.html", {"metrics": metrics, "range_key": range_key})


@login_required
def products(request):
    query = request.GET.get("q", "").strip()
    qs = Product.objects.select_related("category", "brand").prefetch_related("batches").order_by("name")
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(generic_name__icontains=query)
            | Q(barcode__icontains=query)
            | Q(batches__batch_number__icontains=query)
        ).distinct()
    return render(request, "pharmacy/products.html", {"page_obj": paginate(request, qs), "query": query})


@login_required
def product_create(request):
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            messages.success(request, "Product created.")
            return redirect("product_detail", pk=product.pk)
    else:
        form = ProductForm()
    return render(request, "pharmacy/product_form.html", {"form": form, "title": "Add product"})


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category", "brand"), pk=pk)
    batch_form = ProductBatchForm()
    product_form = ProductForm(instance=product)
    adjustment_form = StockAdjustmentForm()
    if request.method == "POST":
        action = request.POST.get("_action")
        if action == "update_product":
            product_form = ProductForm(request.POST, request.FILES, instance=product)
            if product_form.is_valid():
                product_form.save()
                messages.success(request, "Product details updated.")
                return redirect("product_detail", pk=product.pk)
        elif action == "add_batch":
            batch_form = ProductBatchForm(request.POST)
            if batch_form.is_valid():
                batch = batch_form.save(commit=False)
                batch.product = product
                batch.save()
                messages.success(request, "Batch saved.")
                return redirect("product_detail", pk=product.pk)
        elif action == "adjust_stock":
            batch = get_object_or_404(ProductBatch, pk=request.POST.get("batch_id"), product=product)
            adjustment_form = StockAdjustmentForm(request.POST)
            if adjustment_form.is_valid():
                try:
                    adjust_stock(batch, adjustment_form.cleaned_data["action"], adjustment_form.cleaned_data["quantity"], adjustment_form.cleaned_data["note"], request.user)
                    messages.success(request, "Stock updated.")
                    return redirect("product_detail", pk=product.pk)
                except ValidationError as exc:
                    messages.error(request, "; ".join(exc.messages))
    batches = product.batches.all()
    movements = product.stock_movements.select_related("product_batch").all()[:20]
    return render(
        request,
        "pharmacy/product_detail.html",
        {
            "product": product,
            "product_form": product_form,
            "batch_form": batch_form,
            "adjustment_form": adjustment_form,
            "batches": batches,
            "movements": movements,
        },
    )


@login_required
def customers(request):
    sort = request.GET.get("sort", "name")
    query = request.GET.get("q", "").strip()
    qs = Customer.objects.annotate(
        total_bought_value=Coalesce(Sum("invoices__grand_total"), Decimal("0.00"), output_field=DecimalField()),
        total_due_value=Coalesce(Sum("invoices__due_amount"), Decimal("0.00"), output_field=DecimalField()),
        total_paid_value=Coalesce(Sum("invoices__paid_amount"), Decimal("0.00"), output_field=DecimalField()),
    )
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(customer_code__icontains=query))
    sort_map = {
        "bought": "-total_bought_value",
        "due": "-total_due_value",
        "paid": "-total_paid_value",
        "name": "name",
    }
    qs = qs.order_by(sort_map.get(sort, "name"))
    return render(request, "pharmacy/customers.html", {"page_obj": paginate(request, qs), "sort": sort, "query": query})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    invoices = customer.invoices.all().order_by("-created_at")
    return render(request, "pharmacy/customer_detail.html", {"customer": customer, "invoices": invoices})


@login_required
def suppliers(request):
    query = request.GET.get("q", "").strip()
    qs = Supplier.objects.annotate(
        invoice_due=Coalesce(Sum("purchase_invoices__due_amount"), Decimal("0.00"), output_field=DecimalField())
    )
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(supplier_code__icontains=query))
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier saved.")
            return redirect("suppliers")
    else:
        form = SupplierForm()
    return render(
        request,
        "pharmacy/suppliers.html",
        {"page_obj": paginate(request, qs.order_by("name")), "form": form, "query": query},
    )


@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    receipt_form = SupplierReceiptForm(initial={"supplier": supplier})
    if request.method == "POST":
        receipt_form = SupplierReceiptForm(request.POST, request.FILES)
        if receipt_form.is_valid():
            receipt = receipt_form.save(commit=False)
            receipt.uploaded_by = request.user
            receipt.save()
            messages.success(request, "Document uploaded.")
            return redirect("supplier_detail", pk=supplier.pk)
    invoices = supplier.purchase_invoices.prefetch_related("documents").all()
    return render(
        request,
        "pharmacy/supplier_detail.html",
        {"supplier": supplier, "invoices": invoices, "receipt_form": receipt_form},
    )


@login_required
def invoices(request):
    query = request.GET.get("q", "").strip()
    qs = SalesInvoice.objects.select_related("customer").order_by("-created_at")
    if query:
        qs = qs.filter(
            Q(invoice_number__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_phone__icontains=query)
        )
    return render(request, "pharmacy/invoices.html", {"page_obj": paginate(request, qs), "query": query})


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("customer").prefetch_related("items__product", "items__product_batch"),
        pk=pk,
    )
    app_settings = AppSetting.load()
    return render(request, "pharmacy/invoice_detail.html", {"invoice": invoice, "app_settings": app_settings})


@login_required
def returns(request):
    form = ReturnLookupForm(request.GET or None)
    invoice = None
    if request.GET and form.is_valid():
        invoice = lookup_return_invoice(
            form.cleaned_data.get("invoice_number"),
            form.cleaned_data.get("phone"),
            form.cleaned_data.get("invoice_date"),
        )
        if not invoice:
            messages.warning(request, "No matching invoice found.")
    if request.method == "POST":
        invoice = get_object_or_404(SalesInvoice, pk=request.POST.get("invoice_id"))
        try:
            return_tx = process_return(
                invoice,
                request.POST,
                request.POST.get("refund_method", "adjust_due"),
                request.user,
                request.POST.get("notes", ""),
            )
            messages.success(request, f"Return {return_tx.return_number} processed.")
            return redirect("invoice_detail", pk=invoice.pk)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return render(request, "pharmacy/returns.html", {"form": form, "invoice": invoice})


@login_required
def antibiotic_registers(request):
    query = request.GET.get("q", "").strip()
    qs = AntibioticRegisterEntry.objects.select_related("customer", "product", "invoice").order_by("-sale_date")
    if query:
        qs = qs.filter(
            Q(customer__name__icontains=query)
            | Q(product__name__icontains=query)
            | Q(invoice__invoice_number__icontains=query)
        )
    return render(request, "pharmacy/antibiotic_registers.html", {"page_obj": paginate(request, qs), "query": query})


@login_required
def reminders(request):
    return render(request, "pharmacy/reminders.html", reminder_data())


@login_required
@user_passes_test(lambda u: u.is_staff)
def settings_page(request):
    app_settings = AppSetting.load()
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    setting_form = AppSettingForm(instance=app_settings)
    profile_form = UserProfileForm(instance=profile, user=request.user)
    password_form = StyledPasswordChangeForm(request.user)
    if request.method == "POST":
        section = request.POST.get("section")
        if section == "business":
            setting_form = AppSettingForm(request.POST, instance=app_settings)
            if setting_form.is_valid():
                setting_form.save()
                messages.success(request, "Business settings updated.")
                return redirect("settings")
        elif section == "profile":
            profile_form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile settings updated.")
                return redirect("settings")
        elif section == "password":
            password_form = StyledPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                password_form.save()
                messages.success(request, "Password changed. Please log in again if prompted.")
                return redirect("settings")
    return render(
        request,
        "pharmacy/settings.html",
        {"setting_form": setting_form, "profile_form": profile_form, "password_form": password_form},
    )


@login_required
@require_GET
def api_product_search(request):
    batches = search_products(request.GET.get("q", ""))
    results = []
    for batch in batches:
        image = batch.product.thumbnail.url if batch.product.thumbnail else batch.product.image.url if batch.product.image else ""
        results.append(
            {
                "batch_id": batch.id,
                "product_id": batch.product_id,
                "name": batch.product.display_name,
                "generic_name": batch.product.generic_name,
                "brand": batch.product.brand.name if batch.product.brand else "",
                "batch_number": batch.batch_number,
                "expiry_date": batch.expiry_date.isoformat(),
                "stock_quantity": batch.stock_quantity,
                "tp_price": str(batch.tp_price),
                "mrp": str(batch.mrp),
                "image": image,
            }
        )
    return JsonResponse({"results": results})


@login_required
@require_POST
def api_cart_add(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        summary = add_or_update_cart_item(
            request.session,
            payload.get("batch_id"),
            payload.get("quantity", 1),
            payload.get("unit_price"),
            payload.get("discount_amount", 0),
            replace=payload.get("replace", False),
        )
        return JsonResponse(cart_payload(summary))
    except (ValidationError, ProductBatch.DoesNotExist, ValueError, TypeError) as exc:
        message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return JsonResponse({"error": message}, status=400)


@login_required
@require_POST
def api_cart_remove(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        summary = remove_cart_item(request.session, payload.get("batch_id"))
        return JsonResponse(cart_payload(summary))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@login_required
@require_GET
def api_dashboard(request):
    metrics = dashboard_metrics(request.GET.get("range", "this_month"))
    return JsonResponse(
        {
            "total_sales": str(metrics["total_sales"]),
            "total_profit": str(metrics["total_profit"]),
            "total_due": str(metrics["total_due"]),
            "total_customers": metrics["total_customers"],
            "supplier_due": str(metrics["supplier_due"]),
            "monthly": [
                {
                    "month": item["month"].strftime("%b %Y") if item["month"] else "",
                    "total": str(item["total"] or 0),
                    "profit": str(item["profit"] or 0),
                }
                for item in metrics["monthly"]
            ],
        }
    )


def cart_payload(summary):
    items = []
    for item in summary["items"]:
        product = item["product"]
        batch = item["batch"]
        image = product.thumbnail.url if product.thumbnail else product.image.url if product.image else ""
        items.append(
            {
                "batch_id": batch.id,
                "product_id": product.id,
                "name": product.display_name,
                "batch_number": batch.batch_number,
                "quantity": item["quantity"],
                "unit_price": str(item["unit_price"]),
                "discount_amount": str(item["discount_amount"]),
                "line_total": str(item["line_total"]),
                "stock_quantity": batch.stock_quantity,
                "image": image,
            }
        )
    return {"items": items, "subtotal": str(summary["subtotal"]), "count": summary["count"]}

# Create your views here.

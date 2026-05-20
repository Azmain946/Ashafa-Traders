import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.conf import settings as django_settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    AppSettingForm,
    BrandForm,
    CategoryForm,
    CheckoutForm,
    CustomerForm,
    OrderPaymentForm,
    ProductBatchForm,
    ProductEntryForm,
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
    Order,
    Product,
    ProductBatch,
    ProductBrand,
    ProductCategory,
    PurchaseInvoice,
    SalesInvoice,
    Supplier,
    UserProfile,
)
from .printing import (
    QR_PREVIEW_PIXELS,
    QR_PRINT_PIXELS,
    build_receipt_escpos,
    build_sample_receipt_escpos,
    generate_qr_png,
    label_print_payload,
    printer_settings_payload,
)
from .services import (
    add_or_update_cart_item,
    adjust_stock,
    cart_summary,
    create_order_update_invoice,
    dashboard_metrics,
    finalize_checkout,
    lookup_return_invoice,
    process_return,
    remove_cart_item,
    reminder_data,
    reserve_order_number,
    resolve_return_invoice,
    search_products,
)


def paginate(request, queryset, per_page=20):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


def can_manage_products(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return getattr(profile, "role", "") in {"admin", "manager"}


@login_required
def home(request):
    categories = ProductCategory.objects.prefetch_related("products").all()[:8]
    featured_products = (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .prefetch_related("batches")
        .order_by("-updated_at")[:12]
    )
    recent_invoices = Order.objects.only(
        "order_number", "customer_name", "grand_total", "created_at", "payment_status"
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
@never_cache
def order_page(request):
    checkout_form = CheckoutForm()
    order_number = reserve_order_number(request.session)
    return render(
        request,
        "pharmacy/order.html",
        {
            "cart": cart_summary(request.session),
            "checkout_form": checkout_form,
            "order_number": order_number,
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
    category_id = request.GET.get("category", "").strip()
    categories = ProductCategory.objects.prefetch_related("products").order_by("name")
    qs = Product.objects.select_related("category", "brand").prefetch_related("batches").order_by("name")
    selected_category = None
    if category_id:
        selected_category = get_object_or_404(ProductCategory, pk=category_id)
        qs = qs.filter(category=selected_category)
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(generic_name__icontains=query)
            | Q(barcode__icontains=query)
            | Q(batches__batch_number__icontains=query)
            | Q(batches__barcode__icontains=query)
        ).distinct()
    return render(
        request,
        "pharmacy/products.html",
        {
            "page_obj": paginate(request, qs),
            "query": query,
            "categories": categories,
            "selected_category": selected_category,
            "can_manage_products": can_manage_products(request.user),
        },
    )


@login_required
@user_passes_test(can_manage_products)
def product_create(request):
    if request.method == "POST":
        form = ProductEntryForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            messages.success(request, "Product created.")
            if request.POST.get("print_barcode") == "1":
                batch = form.created_batch
                labels = request.POST.get("label_count") or batch.number_of_boxes
                return redirect(
                    f"{reverse('product_detail', args=[product.pk])}?print_label_batch={batch.pk}&labels={labels}"
                )
            return redirect("product_detail", pk=product.pk)
    else:
        form = ProductEntryForm()
    return render(request, "pharmacy/product_form.html", {"form": form, "title": "Add product"})


@login_required
@user_passes_test(can_manage_products)
def taxonomy_manage(request):
    category_form = CategoryForm(prefix="category")
    brand_form = BrandForm(prefix="brand")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_category":
            category_form = CategoryForm(request.POST, prefix="category")
            if category_form.is_valid():
                category_form.save()
                messages.success(request, "Category added.")
                return redirect("taxonomy_manage")
        elif action == "update_category":
            category = get_object_or_404(ProductCategory, pk=request.POST.get("category_id"))
            form = CategoryForm(request.POST, instance=category, prefix=f"category_{category.pk}")
            if form.is_valid():
                form.save()
                messages.success(request, "Category updated.")
                return redirect("taxonomy_manage")
        elif action == "delete_category":
            category = get_object_or_404(ProductCategory, pk=request.POST.get("category_id"))
            category.delete()
            messages.success(request, "Category deleted.")
            return redirect("taxonomy_manage")
        elif action == "add_brand":
            brand_form = BrandForm(request.POST, prefix="brand")
            if brand_form.is_valid():
                brand_form.save()
                messages.success(request, "Brand added.")
                return redirect("taxonomy_manage")
        elif action == "update_brand":
            brand = get_object_or_404(ProductBrand, pk=request.POST.get("brand_id"))
            form = BrandForm(request.POST, instance=brand, prefix=f"brand_{brand.pk}")
            if form.is_valid():
                form.save()
                messages.success(request, "Brand updated.")
                return redirect("taxonomy_manage")
        elif action == "delete_brand":
            brand = get_object_or_404(ProductBrand, pk=request.POST.get("brand_id"))
            brand.delete()
            messages.success(request, "Brand deleted.")
            return redirect("taxonomy_manage")
    categories = ProductCategory.objects.order_by("name")
    brands = ProductBrand.objects.order_by("name")
    return render(
        request,
        "pharmacy/taxonomy_manage.html",
        {
            "category_form": category_form,
            "brand_form": brand_form,
            "categories": categories,
            "brands": brands,
        },
    )


@login_required
def batch_barcode_print(request, pk):
    batch = get_object_or_404(ProductBatch.objects.select_related("product"), pk=pk)
    if not batch.barcode:
        batch.save(update_fields=["barcode", "updated_at"])
    try:
        label_count = int(request.GET.get("labels", batch.number_of_boxes))
    except (TypeError, ValueError):
        label_count = batch.number_of_boxes
    label_count = max(1, min(label_count, 500))
    return render(
        request,
        "pharmacy/barcode_print.html",
        {
            "batch": batch,
            "labels": range(label_count),
            "label_count": label_count,
        },
    )


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category", "brand"), pk=pk)
    batch_form = ProductBatchForm()
    product_form = ProductForm(instance=product)
    adjustment_form = StockAdjustmentForm()
    if request.method == "POST":
        action = request.POST.get("_action")
        if action == "update_product" and can_manage_products(request.user):
            product_form = ProductForm(request.POST, request.FILES, instance=product)
            if product_form.is_valid():
                product_form.save()
                messages.success(request, "Product details updated.")
                return redirect("product_detail", pk=product.pk)
        elif action == "add_batch" and can_manage_products(request.user):
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
            "can_manage_products": can_manage_products(request.user),
        },
    )


@login_required
def customers(request):
    sort = request.GET.get("sort", "newest")
    query = request.GET.get("q", "").strip()
    qs = Customer.objects.annotate(
        total_bought_value=Coalesce(Sum("orders__grand_total"), Decimal("0.00"), output_field=DecimalField()),
        total_due_value=Coalesce(Sum("orders__due_amount"), Decimal("0.00"), output_field=DecimalField()),
        total_paid_value=Coalesce(Sum("orders__paid_amount"), Decimal("0.00"), output_field=DecimalField()),
    )
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(customer_code__icontains=query))
    sort_map = {
        "newest": "-created_at",
        "bought": "-total_bought_value",
        "due": "-total_due_value",
        "paid": "-total_paid_value",
        "name": "name",
    }
    qs = qs.order_by(sort_map.get(sort, "-created_at"))
    return render(request, "pharmacy/customers.html", {"page_obj": paginate(request, qs), "sort": sort, "query": query})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    orders = customer.orders.all().order_by("-created_at")
    return render(request, "pharmacy/customer_detail.html", {"customer": customer, "orders": orders})


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
    qs = Order.objects.select_related("customer").order_by("-created_at")
    if query:
        qs = qs.filter(
            Q(order_number__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_phone__icontains=query)
        )
    return render(request, "pharmacy/invoices.html", {"page_obj": paginate(request, qs), "query": query})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related("invoices"), pk=pk)
    form = OrderPaymentForm(instance=order)
    if request.method == "POST":
        form = OrderPaymentForm(request.POST, instance=order)
        if form.is_valid():
            updated_order = form.save()
            invoice = create_order_update_invoice(updated_order, request.user)
            messages.success(request, "Order payment details updated and new invoice generated.")
            return redirect(f"{reverse('invoice_detail', args=[invoice.pk])}?print=1")
    return render(request, "pharmacy/order_detail.html", {"order": order, "form": form})


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("customer", "order").prefetch_related("items__product", "items__product_batch"),
        pk=pk,
    )
    app_settings = AppSetting.load()
    return render(request, "pharmacy/invoice_detail.html", {"invoice": invoice, "app_settings": app_settings})


@login_required
def returns(request):
    form = ReturnLookupForm(request.GET or None)
    invoice = None
    return_items = []
    no_return_items_message = ""
    if request.GET and form.is_valid():
        invoice = lookup_return_invoice(
            form.cleaned_data.get("invoice_number"),
            form.cleaned_data.get("phone"),
            form.cleaned_data.get("invoice_date"),
        )
        invoice = resolve_return_invoice(invoice)
        if not invoice:
            messages.warning(request, "No matching order found.")
        else:
            return_items = list(invoice.items.select_related("product", "product_batch").all())
            if not return_items:
                no_return_items_message = "No returnable product lines were found for this order."
    if request.method == "POST":
        invoice = resolve_return_invoice(get_object_or_404(SalesInvoice, pk=request.POST.get("invoice_id")))
        try:
            return_tx, new_invoice = process_return(
                invoice,
                request.POST,
                request.POST.get("refund_method", "adjust_due"),
                request.user,
                request.POST.get("notes", ""),
            )
            messages.success(request, f"Return {return_tx.return_number} processed.")
            return redirect(f"{reverse('invoice_detail', args=[new_invoice.pk])}?print=1")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            if invoice:
                return_items = list(invoice.items.select_related("product", "product_batch").all())
                if not return_items:
                    no_return_items_message = "No returnable product lines were found for this order."
    return render(
        request,
        "pharmacy/returns.html",
        {
            "form": form,
            "invoice": invoice,
            "return_items": return_items,
            "no_return_items_message": no_return_items_message,
        },
    )


@login_required
def antibiotic_registers(request):
    query = request.GET.get("q", "").strip()
    qs = AntibioticRegisterEntry.objects.select_related("customer", "product", "invoice", "invoice__order").order_by("-sale_date")
    if query:
        qs = qs.filter(
            Q(customer__name__icontains=query)
            | Q(product__name__icontains=query)
            | Q(invoice__invoice_number__icontains=query)
            | Q(invoice__order__order_number__icontains=query)
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
        {
            "setting_form": setting_form,
            "profile_form": profile_form,
            "password_form": password_form,
            "printer_settings": printer_settings_payload(app_settings),
        },
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
                "product_name": batch.product.name,
                "strength": batch.product.strength,
                "generic_name": batch.product.generic_name,
                "brand": batch.product.brand.name if batch.product.brand else "",
                "batch_number": batch.batch_number,
                "barcode": batch.barcode,
                "expiry_date": batch.expiry_date.isoformat(),
                "stock_quantity": batch.stock_quantity,
                "tp_price": str(batch.tp_price),
                "mrp": str(batch.mrp),
                "image": image,
            }
        )
    return JsonResponse({"results": results})


@login_required
@require_GET
def api_product_variants(request, pk):
    selected = get_object_or_404(Product, pk=pk)
    products = (
        Product.objects.filter(name__iexact=selected.name, is_active=True)
        .select_related("brand")
        .prefetch_related("batches")
        .order_by("strength", "name")
    )
    variants = []
    for product in products:
        batches = [
            batch
            for batch in product.batches.all()
            if batch.is_active and batch.stock_quantity > 0 and batch.expiry_date > timezone.localdate()
        ]
        if not batches:
            continue
        image = product.thumbnail.url if product.thumbnail else product.image.url if product.image else ""
        variants.append(
            {
                "product_id": product.id,
                "name": product.display_name,
                "strength": product.strength or "Default",
                "generic_name": product.generic_name,
                "image": image,
                "total_stock": sum(batch.stock_quantity for batch in batches),
                "batches": [
                    {
                        "batch_id": batch.id,
                        "batch_number": batch.batch_number,
                        "expiry_date": batch.expiry_date.isoformat(),
                        "stock_quantity": batch.stock_quantity,
                        "tp_price": str(batch.tp_price),
                        "mrp": str(batch.mrp),
                    }
                    for batch in sorted(batches, key=lambda item: (item.expiry_date, item.batch_number))
                ],
            }
        )
    return JsonResponse({"variants": variants})


@login_required
@require_POST
def api_cart_add(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        unit_price = payload.get("unit_price")
        price_type = payload.get("price_type")
        if price_type in {"tp", "mrp"}:
            batch = ProductBatch.objects.get(pk=payload.get("batch_id"), is_active=True)
            unit_price = batch.mrp if price_type == "mrp" else batch.tp_price
        summary = add_or_update_cart_item(
            request.session,
            payload.get("batch_id"),
            payload.get("quantity", 1),
            unit_price,
            payload.get("discount_percent", 0),
            payload.get("add_percent", 0),
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
                "discount_percent": str(item["discount_percent"]),
                "add_percent": str(item["add_percent"]),
                "discount_amount": str(item["discount_amount"]),
                "add_amount": str(item["add_amount"]),
                "line_total": str(item["line_total"]),
                "stock_quantity": batch.stock_quantity,
                "image": image,
            }
        )
    return {
        "items": items,
        "subtotal": str(summary["subtotal"]),
        "round_off_amount": str(summary["round_off_amount"]),
        "rounded_total": str(summary["rounded_total"]),
        "count": summary["count"],
    }


@login_required
@require_GET
def api_qz_certificate(request):
    cert_path = django_settings.QZ_CERTIFICATE_PATH
    if not cert_path.exists():
        return HttpResponse("Certificate not configured.", status=404, content_type="text/plain")
    return HttpResponse(cert_path.read_text(encoding="utf-8"), content_type="text/plain")


@login_required
@require_GET
def api_qz_sign(request):
    to_sign = request.GET.get("request", "")
    key_path = django_settings.QZ_PRIVATE_KEY_PATH
    if not to_sign or not key_path.exists():
        return JsonResponse({"error": "QZ signing is not configured."}, status=503)
    try:
        import base64

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        signature = private_key.sign(to_sign.encode("utf-8"), padding.PKCS1v15(), hashes.SHA512())
        return HttpResponse(base64.b64encode(signature).decode("ascii"), content_type="text/plain")
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_GET
def api_printer_settings(request):
    return JsonResponse(printer_settings_payload())


@login_required
@require_POST
def api_printer_settings_save(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    app_settings = AppSetting.load()
    app_settings.receipt_printer_name = (payload.get("receipt_printer_name") or "").strip()
    app_settings.label_printer_name = (payload.get("label_printer_name") or "").strip()
    if "default_label_copies" in payload:
        app_settings.default_label_copies = max(1, int(payload.get("default_label_copies") or 1))
    if "receipt_paper_chars" in payload:
        app_settings.receipt_paper_chars = max(32, min(64, int(payload.get("receipt_paper_chars") or 46)))
    if "label_width_mm" in payload:
        app_settings.label_width_mm = max(10, int(payload.get("label_width_mm") or 20))
    if "label_height_mm" in payload:
        app_settings.label_height_mm = max(10, int(payload.get("label_height_mm") or 20))
    app_settings.save(
        update_fields=[
            "receipt_printer_name",
            "label_printer_name",
            "default_label_copies",
            "receipt_paper_chars",
            "label_width_mm",
            "label_height_mm",
            "updated_at",
        ]
    )
    return JsonResponse({"ok": True, "settings": printer_settings_payload(app_settings)})


@login_required
@require_GET
def api_invoice_receipt(request, pk):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("order").prefetch_related("items"),
        pk=pk,
    )
    app_settings = AppSetting.load()
    return JsonResponse(
        {
            "printer_name": app_settings.receipt_printer_name,
            "receipt": build_receipt_escpos(invoice, app_settings),
        }
    )


@login_required
@require_GET
def api_print_test_receipt(request):
    app_settings = AppSetting.load()
    return JsonResponse(
        {
            "printer_name": app_settings.receipt_printer_name,
            "receipt": build_sample_receipt_escpos(app_settings),
        }
    )


@login_required
@never_cache
@require_GET
def api_batch_qr_png(request, pk):
    batch = get_object_or_404(ProductBatch.objects.select_related("product"), pk=pk)
    if request.GET.get("preview") == "1":
        pixel_size = QR_PREVIEW_PIXELS
    elif request.GET.get("size"):
        pixel_size = max(QR_PREVIEW_PIXELS, min(512, int(request.GET.get("size"))))
    else:
        pixel_size = QR_PRINT_PIXELS
    png = generate_qr_png(batch, pixel_size=pixel_size, for_print=pixel_size >= QR_PRINT_PIXELS)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def api_batch_label(request, pk):
    batch = get_object_or_404(ProductBatch.objects.select_related("product"), pk=pk)
    copies = request.GET.get("copies")
    copies_value = int(copies) if copies else None
    app_settings = AppSetting.load()
    payload = label_print_payload(batch, copies=copies_value, app_settings=app_settings)
    payload["image_url"] = request.build_absolute_uri(
        reverse("api_batch_qr_png", args=[batch.pk]) + f"?size={QR_PRINT_PIXELS}"
    )
    return JsonResponse(payload)


@login_required
@require_GET
def api_print_test_label(request):
    batch = ProductBatch.objects.select_related("product").filter(is_active=True).order_by("-created_at").first()
    if not batch:
        return JsonResponse({"error": "No batch available for label test."}, status=404)
    copies = max(1, int(request.GET.get("copies", 1)))
    app_settings = AppSetting.load()
    payload = label_print_payload(batch, copies=copies, app_settings=app_settings)
    payload["image_url"] = request.build_absolute_uri(
        reverse("api_batch_qr_png", args=[batch.pk]) + f"?size={QR_PRINT_PIXELS}"
    )
    return JsonResponse(payload)

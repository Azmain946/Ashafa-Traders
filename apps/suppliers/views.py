from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import PurchaseInvoiceForm, SupplierForm, UploadedReceiptForm
from .models import PurchaseInvoice, Supplier, UploadedReceipt


@login_required
def supplier_list(request):
    qs = Supplier.objects.annotate(
        total_purchased=Sum("purchase_invoices__total"),
        total_paid=Sum("purchase_invoices__paid_amount"),
        total_due=Sum("purchase_invoices__due_amount"),
    ).order_by("name")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "suppliers/list.html", {"suppliers": page, "q": q})


@login_required
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        messages.success(request, "Supplier created.")
        return redirect("suppliers:detail", pk=supplier.pk)
    return render(request, "suppliers/form.html", {"form": form, "create": True})


@login_required
def supplier_edit(request, pk: int):
    supplier = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier updated.")
        return redirect("suppliers:detail", pk=supplier.pk)
    return render(request, "suppliers/form.html", {"form": form, "create": False, "supplier": supplier})


@login_required
def supplier_detail(request, pk: int):
    supplier = get_object_or_404(Supplier, pk=pk)
    invoices = supplier.purchase_invoices.all()
    receipts = supplier.receipts.select_related("purchase_invoice").all()
    invoice_form = PurchaseInvoiceForm()
    receipt_form = UploadedReceiptForm(supplier=supplier)
    return render(
        request,
        "suppliers/detail.html",
        {
            "supplier": supplier,
            "invoices": invoices,
            "receipts": receipts,
            "totals": supplier.totals(),
            "invoice_form": invoice_form,
            "receipt_form": receipt_form,
        },
    )


@login_required
def purchase_invoice_create(request, supplier_id: int):
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    form = PurchaseInvoiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        invoice: PurchaseInvoice = form.save(commit=False)
        invoice.supplier = supplier
        invoice.user = request.user
        invoice.recalc()
        invoice.save()
        messages.success(request, "Purchase invoice recorded.")
        return redirect("suppliers:detail", pk=supplier.pk)
    messages.error(request, "Could not save purchase invoice.")
    return redirect("suppliers:detail", pk=supplier.pk)


@login_required
def receipt_upload(request, supplier_id: int):
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    if request.method == "POST":
        form = UploadedReceiptForm(request.POST, request.FILES, supplier=supplier)
        if form.is_valid():
            receipt: UploadedReceipt = form.save(commit=False)
            receipt.supplier = supplier
            receipt.uploaded_by = request.user
            receipt.save()
            messages.success(request, "Receipt uploaded.")
        else:
            for err in form.errors.values():
                messages.error(request, err.as_text())
    return redirect("suppliers:detail", pk=supplier.pk)

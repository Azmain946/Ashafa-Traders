from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from .forms import CustomerForm
from .models import Customer


@login_required
def customer_list(request):
    qs = Customer.objects.annotate(
        total_bought=Sum("sales_invoices__total"),
        total_paid=Sum("sales_invoices__paid_amount"),
        total_due=Sum("sales_invoices__due_amount"),
    ).order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    sort = request.GET.get("sort")
    if sort in {"bought", "paid", "due"}:
        qs = qs.order_by(F_sort_map[sort])

    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "customers/list.html", {"customers": page, "q": q, "sort": sort})


F_sort_map = {
    "bought": "-total_bought",
    "paid": "-total_paid",
    "due": "-total_due",
}


@login_required
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        messages.success(request, "Customer created.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
            })
        return redirect("customers:detail", pk=customer.pk)
    return render(request, "customers/form.html", {"form": form, "create": True})


@login_required
def customer_edit(request, pk: int):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Customer updated.")
        return redirect("customers:detail", pk=customer.pk)
    return render(request, "customers/form.html", {"form": form, "create": False, "customer": customer})


@login_required
def customer_detail(request, pk: int):
    customer = get_object_or_404(Customer, pk=pk)
    invoices = customer.sales_invoices.select_related("customer").order_by("-created_at")[:200]
    totals = customer.totals()
    return render(
        request,
        "customers/detail.html",
        {"customer": customer, "invoices": invoices, "totals": totals},
    )


@login_required
@require_GET
def customer_search_api(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    qs = Customer.objects.filter(Q(name__icontains=q) | Q(phone__icontains=q))[:8]
    return JsonResponse({
        "results": [
            {"id": c.id, "name": c.name, "phone": c.phone, "address": c.address}
            for c in qs
        ]
    })

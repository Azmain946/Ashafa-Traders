from django.contrib import admin

from .models import (
    AntibioticRegisterEntry,
    InvoiceSequence,
    ReturnItem,
    ReturnTransaction,
    SalesInvoice,
    SalesInvoiceItem,
)


class SalesInvoiceItemInline(admin.TabularInline):
    model = SalesInvoiceItem
    extra = 0
    readonly_fields = ("product_name", "batch_number", "quantity", "unit_price", "discount", "total")


@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "customer", "invoice_date", "total", "paid_amount", "due_amount", "payment_status")
    list_filter = ("payment_status", "invoice_date")
    search_fields = ("invoice_number", "customer__name", "customer__phone")
    inlines = [SalesInvoiceItemInline]


@admin.register(ReturnTransaction)
class ReturnTransactionAdmin(admin.ModelAdmin):
    list_display = ("return_date", "invoice", "customer", "total_refund")


@admin.register(AntibioticRegisterEntry)
class AntibioticRegisterEntryAdmin(admin.ModelAdmin):
    list_display = ("sale_date", "product", "customer", "quantity", "total")
    search_fields = ("product__name", "customer__name", "customer__phone")
    list_filter = ("sale_date",)


admin.site.register(ReturnItem)
admin.site.register(InvoiceSequence)

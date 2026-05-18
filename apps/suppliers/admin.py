from django.contrib import admin

from .models import PurchaseInvoice, Supplier, UploadedReceipt


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email")
    search_fields = ("name", "phone")


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ("supplier", "invoice_number", "invoice_date", "total", "paid_amount", "due_amount")
    list_filter = ("invoice_date",)
    search_fields = ("invoice_number", "supplier__name")


@admin.register(UploadedReceipt)
class UploadedReceiptAdmin(admin.ModelAdmin):
    list_display = ("supplier", "title", "purchase_invoice", "uploaded_by", "created_at")
    search_fields = ("supplier__name", "title")

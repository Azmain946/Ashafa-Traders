from django.contrib import admin

from .models import (
    ActionLog,
    AntibioticRegisterEntry,
    AppSetting,
    Customer,
    InvoiceSequence,
    Product,
    ProductBatch,
    ProductBrand,
    ProductCategory,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    ReminderItem,
    ReminderRule,
    ReturnItem,
    ReturnTransaction,
    SalesInvoice,
    SalesInvoiceItem,
    StockMovement,
    Supplier,
    UploadedDocument,
    UserProfile,
)


class ProductBatchInline(admin.TabularInline):
    model = ProductBatch
    extra = 0
    fields = (
        "batch_number",
        "mfg_date",
        "expiry_date",
        "number_of_boxes",
        "units_per_box",
        "buy_price_per_box",
        "tp_price_per_box",
        "mrp_per_box",
        "stock_quantity",
        "shelf_number",
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "generic_name", "strength", "category", "brand", "is_antibiotic", "total_stock", "is_active")
    list_filter = ("category", "brand", "is_antibiotic", "is_active")
    search_fields = ("name", "generic_name", "barcode", "sku", "batches__batch_number")
    inlines = [ProductBatchInline]


@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = ("product", "batch_number", "mfg_date", "expiry_date", "tp_price", "mrp", "stock_quantity", "shelf_number")
    list_filter = ("expiry_date", "is_active")
    search_fields = ("product__name", "product__generic_name", "batch_number")


class SalesInvoiceItemInline(admin.TabularInline):
    model = SalesInvoiceItem
    extra = 0
    readonly_fields = ("product_name", "batch_number", "line_total", "buy_price")


@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "invoice_date", "customer_name", "grand_total", "paid_amount", "due_amount", "payment_status")
    list_filter = ("payment_status", "invoice_date")
    search_fields = ("invoice_number", "customer_name", "customer_phone")
    inlines = [SalesInvoiceItemInline]


class PurchaseInvoiceItemInline(admin.TabularInline):
    model = PurchaseInvoiceItem
    extra = 0


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "supplier", "invoice_date", "subtotal", "paid_amount", "due_amount")
    search_fields = ("invoice_number", "supplier__name")
    inlines = [PurchaseInvoiceItemInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_code", "name", "phone", "email")
    search_fields = ("customer_code", "name", "phone", "email")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("supplier_code", "name", "phone", "email", "opening_due")
    search_fields = ("supplier_code", "name", "phone", "email")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "product_batch", "movement_type", "quantity", "quantity_after", "created_at")
    list_filter = ("movement_type", "created_at")
    search_fields = ("product__name", "product_batch__batch_number", "sales_invoice__invoice_number")


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0


@admin.register(ReturnTransaction)
class ReturnTransactionAdmin(admin.ModelAdmin):
    list_display = ("return_number", "invoice", "phone", "return_date", "total_refund")
    search_fields = ("return_number", "invoice__invoice_number", "phone")
    inlines = [ReturnItemInline]


admin.site.register(ProductCategory)
admin.site.register(ProductBrand)
admin.site.register(AntibioticRegisterEntry)
admin.site.register(ReminderRule)
admin.site.register(ReminderItem)
admin.site.register(UploadedDocument)
admin.site.register(AppSetting)
admin.site.register(UserProfile)
admin.site.register(ActionLog)
admin.site.register(InvoiceSequence)

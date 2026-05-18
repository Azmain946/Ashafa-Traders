from django.contrib import admin

from .models import Manufacturer, Product, ProductBatch, ProductCategory, StockMovement


class ProductBatchInline(admin.TabularInline):
    model = ProductBatch
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "strength", "category", "manufacturer", "is_antibiotic", "is_active")
    list_filter = ("category", "manufacturer", "is_antibiotic", "is_active")
    search_fields = ("name", "generic_name", "barcode", "sku")
    inlines = [ProductBatchInline]


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "icon")
    search_fields = ("name",)


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name", "country")
    search_fields = ("name",)


@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = ("product", "batch_number", "expiry_date", "quantity", "tp_price", "mrp")
    search_fields = ("product__name", "batch_number")
    list_filter = ("expiry_date",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "batch", "movement_type", "quantity", "user")
    list_filter = ("movement_type",)
    search_fields = ("reference", "note", "batch__product__name")

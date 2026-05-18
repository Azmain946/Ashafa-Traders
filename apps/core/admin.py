from django.contrib import admin

from .models import ActivityLog, AppSetting


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("business_name", "currency_symbol", "low_stock_threshold", "near_expiry_days")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target", "detail")
    search_fields = ("action", "target", "detail", "user__username")
    list_filter = ("action",)

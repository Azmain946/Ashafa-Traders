from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppSetting(models.Model):
    """Singleton-style row for global business / app settings."""

    business_name = models.CharField(max_length=120, default="Pharmacy ERP")
    business_phone = models.CharField(max_length=40, blank=True)
    business_email = models.EmailField(blank=True)
    business_address = models.CharField(max_length=255, blank=True)

    invoice_prefix = models.CharField(max_length=10, default="INV")
    invoice_footer_note = models.CharField(max_length=255, blank=True, default="Thank you for shopping with us.")
    show_logo_on_print = models.BooleanField(default=True)

    low_stock_threshold = models.PositiveIntegerField(default=10)
    near_expiry_days = models.PositiveIntegerField(default=60)

    default_tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    currency_symbol = models.CharField(max_length=8, default="৳")

    logo = models.ImageField(upload_to="branding/", blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Application Setting"
        verbose_name_plural = "Application Settings"

    def __str__(self) -> str:
        return self.business_name

    @classmethod
    def load(cls) -> "AppSetting":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ActivityLog(TimeStampedModel):
    """Lightweight audit log for important user actions."""

    user = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=120, blank=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M}"

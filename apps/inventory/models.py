from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Sum
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import TimeStampedModel


class ProductCategory(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)
    icon = models.CharField(max_length=40, blank=True, help_text="Bootstrap icon name, e.g. 'capsule'")
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Product categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:90]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Manufacturer(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    country = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    DOSAGE_FORMS = [
        ("tablet", "Tablet"),
        ("capsule", "Capsule"),
        ("syrup", "Syrup"),
        ("injection", "Injection"),
        ("cream", "Cream / Ointment"),
        ("drop", "Drops"),
        ("inhaler", "Inhaler"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=150, db_index=True)
    generic_name = models.CharField(max_length=150, blank=True, db_index=True)
    strength = models.CharField(max_length=60, blank=True, help_text="e.g. 500 mg, 10ml")
    dosage_form = models.CharField(max_length=20, choices=DOSAGE_FORMS, default="tablet")

    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    sku = models.CharField(max_length=40, blank=True, unique=True, null=True)

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    is_antibiotic = models.BooleanField(default=False)
    requires_prescription = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    description = models.TextField(blank=True)

    image = models.ImageField(upload_to="products/", blank=True, null=True)
    thumbnail = models.ImageField(upload_to="products/thumbnails/", blank=True, null=True)

    class Meta:
        ordering = ("name",)
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["generic_name"]),
            models.Index(fields=["barcode"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.strength}".strip()

    @property
    def display_image(self):
        return self.thumbnail or self.image

    @property
    def total_stock(self) -> int:
        return int(self.batches.aggregate(s=Sum("quantity"))["s"] or 0)

    @property
    def latest_tp_price(self) -> Decimal:
        batch = self.batches.filter(quantity__gt=0).order_by("expiry_date").first()
        if not batch:
            batch = self.batches.order_by("-created_at").first()
        return batch.tp_price if batch else Decimal("0")

    @property
    def latest_mrp(self) -> Decimal:
        batch = self.batches.filter(quantity__gt=0).order_by("expiry_date").first()
        if not batch:
            batch = self.batches.order_by("-created_at").first()
        return batch.mrp if batch else Decimal("0")

    def sellable_batches(self):
        return self.batches.filter(quantity__gt=0).order_by("expiry_date", "id")


class ProductBatch(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    batch_number = models.CharField(max_length=60, db_index=True)
    expiry_date = models.DateField()

    buy_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tp_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Trade price")
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Max retail price")

    quantity = models.PositiveIntegerField(default=0)
    shelf_location = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ("expiry_date", "id")
        constraints = [
            models.UniqueConstraint(fields=("product", "batch_number"), name="uniq_batch_per_product"),
        ]
        indexes = [
            models.Index(fields=["expiry_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} • {self.batch_number}"

    @property
    def is_expired(self) -> bool:
        return self.expiry_date < timezone.localdate()

    @property
    def days_to_expiry(self) -> int:
        return (self.expiry_date - timezone.localdate()).days


class StockMovement(TimeStampedModel):
    TYPE_PURCHASE = "purchase"
    TYPE_SALE = "sale"
    TYPE_RETURN_IN = "return_in"
    TYPE_RETURN_OUT = "return_out"
    TYPE_ADJUSTMENT = "adjustment"
    TYPE_INITIAL = "initial"

    TYPE_CHOICES = [
        (TYPE_PURCHASE, "Purchase"),
        (TYPE_SALE, "Sale"),
        (TYPE_RETURN_IN, "Return from customer"),
        (TYPE_RETURN_OUT, "Return to supplier"),
        (TYPE_ADJUSTMENT, "Manual adjustment"),
        (TYPE_INITIAL, "Initial entry"),
    ]

    batch = models.ForeignKey(ProductBatch, on_delete=models.CASCADE, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    quantity = models.IntegerField(help_text="Positive for incoming, negative for outgoing.")
    reference = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["movement_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} • {self.quantity}"

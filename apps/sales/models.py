from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TimeStampedModel


PAYMENT_FULL = "paid"
PAYMENT_PARTIAL = "partial"
PAYMENT_DUE = "due"
PAYMENT_STATUSES = [
    (PAYMENT_FULL, "Fully paid"),
    (PAYMENT_PARTIAL, "Partially paid"),
    (PAYMENT_DUE, "Unpaid"),
]


class SalesInvoice(TimeStampedModel):
    invoice_number = models.CharField(max_length=40, unique=True, db_index=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="sales_invoices",
    )
    invoice_date = models.DateField(default=timezone.localdate)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    discount_type = models.CharField(
        max_length=10,
        choices=[("percent", "Percent"), ("fixed", "Fixed amount")],
        default="fixed",
    )
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUSES, default=PAYMENT_DUE)

    notes = models.CharField(max_length=255, blank=True)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices",
    )

    class Meta:
        ordering = ("-invoice_date", "-id")
        indexes = [models.Index(fields=["invoice_date"]), models.Index(fields=["payment_status"])]

    def __str__(self) -> str:
        return self.invoice_number

    def get_absolute_url(self) -> str:
        return reverse("sales:invoice_detail", args=[self.pk])

    def recalc_status(self):
        self.due_amount = (self.total or 0) - (self.paid_amount or 0)
        if self.due_amount <= 0:
            self.payment_status = PAYMENT_FULL
            self.due_amount = Decimal("0.00")
        elif self.paid_amount > 0:
            self.payment_status = PAYMENT_PARTIAL
        else:
            self.payment_status = PAYMENT_DUE


class SalesInvoiceItem(TimeStampedModel):
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="sales_items")
    batch = models.ForeignKey("inventory.ProductBatch", on_delete=models.PROTECT, related_name="sales_items")
    product_name = models.CharField(max_length=160)
    batch_number = models.CharField(max_length=60, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.product_name} x {self.quantity}"


class ReturnTransaction(TimeStampedModel):
    invoice = models.ForeignKey(
        SalesInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returns",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returns",
    )
    return_date = models.DateField(default=timezone.localdate)
    reason = models.CharField(max_length=200, blank=True)
    total_refund = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returns",
    )

    class Meta:
        ordering = ("-return_date", "-id")

    def __str__(self) -> str:
        ref = self.invoice.invoice_number if self.invoice else "—"
        return f"Return for {ref}"


class ReturnItem(TimeStampedModel):
    return_tx = models.ForeignKey(ReturnTransaction, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="return_items")
    batch = models.ForeignKey("inventory.ProductBatch", on_delete=models.PROTECT, related_name="return_items")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    restock = models.BooleanField(default=True)


class AntibioticRegisterEntry(TimeStampedModel):
    invoice = models.ForeignKey(
        SalesInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="antibiotic_entries",
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, related_name="antibiotic_entries")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="antibiotic_entries")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sale_date = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ("-sale_date", "-id")
        verbose_name_plural = "Antibiotic register entries"

    def __str__(self) -> str:
        return f"{self.product.name} • {self.quantity}"


class InvoiceSequence(models.Model):
    """Concurrency-safe daily sequence counter for invoice numbers."""

    day_key = models.CharField(max_length=8, primary_key=True)  # YYYYMMDD
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.day_key}: {self.last_value}"

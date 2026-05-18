from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TimeStampedModel


def receipt_upload_to(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"receipts/{uuid.uuid4().hex}{ext}"


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("suppliers:detail", args=[self.pk])

    @property
    def code(self) -> str:
        return f"S-{self.pk:04d}"

    def totals(self):
        agg = self.purchase_invoices.aggregate(
            purchased=models.Sum("total"),
            paid=models.Sum("paid_amount"),
            due=models.Sum("due_amount"),
        )
        return {
            "purchased": agg["purchased"] or 0,
            "paid": agg["paid"] or 0,
            "due": agg["due"] or 0,
        }


class PurchaseInvoice(TimeStampedModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="purchase_invoices")
    invoice_number = models.CharField(max_length=60, db_index=True)
    invoice_date = models.DateField(default=timezone.localdate)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    notes = models.CharField(max_length=255, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_invoices",
    )

    class Meta:
        ordering = ("-invoice_date", "-id")
        constraints = [
            models.UniqueConstraint(fields=("supplier", "invoice_number"), name="uniq_supplier_invoice_no"),
        ]

    def __str__(self) -> str:
        return f"{self.supplier.name} • {self.invoice_number}"

    def recalc(self):
        self.due_amount = (self.total or 0) - (self.paid_amount or 0)


class UploadedReceipt(TimeStampedModel):
    """Receipt/memo file linked to a supplier and (optionally) a purchase invoice."""

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="receipts")
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receipts",
    )
    title = models.CharField(max_length=120, blank=True)
    file = models.FileField(upload_to=receipt_upload_to)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_receipts",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title or self.file.name

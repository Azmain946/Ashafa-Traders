from django.db import models
from django.db.models import F, Sum
from django.urls import reverse

from apps.core.models import TimeStampedModel


class Customer(TimeStampedModel):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=40, db_index=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("phone",), name="uniq_customer_phone"),
        ]
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"

    def get_absolute_url(self) -> str:
        return reverse("customers:detail", args=[self.pk])

    @property
    def code(self) -> str:
        return f"C-{self.pk:05d}"

    def totals(self):
        from apps.sales.models import SalesInvoice

        agg = SalesInvoice.objects.filter(customer=self).aggregate(
            bought=Sum("total"),
            paid=Sum("paid_amount"),
            due=Sum("due_amount"),
        )
        return {
            "bought": agg["bought"] or 0,
            "paid": agg["paid"] or 0,
            "due": agg["due"] or 0,
        }

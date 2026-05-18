"""Inventory business logic kept out of views."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from .models import ProductBatch, StockMovement


@transaction.atomic
def adjust_stock(
    batch: ProductBatch,
    *,
    quantity_change: int,
    movement_type: str,
    user=None,
    reference: str = "",
    note: str = "",
) -> ProductBatch:
    """Atomically adjust a batch's stock and record a StockMovement.

    quantity_change > 0 = stock added, < 0 = stock removed.
    Prevents stock from going below zero via SELECT FOR UPDATE.
    """
    if quantity_change == 0:
        return batch

    locked = ProductBatch.objects.select_for_update().get(pk=batch.pk)
    new_qty = locked.quantity + quantity_change
    if new_qty < 0:
        raise ValidationError(
            f"Insufficient stock for batch {locked.batch_number}. "
            f"Available {locked.quantity}, requested {abs(quantity_change)}."
        )
    locked.quantity = new_qty
    locked.save(update_fields=["quantity", "updated_at"])

    StockMovement.objects.create(
        batch=locked,
        movement_type=movement_type,
        quantity=quantity_change,
        reference=reference,
        note=note,
        user=user,
    )
    return locked


def pick_batch_for_sale(product, requested_qty: int) -> ProductBatch | None:
    """First-expiring batch with enough stock to satisfy the requested qty."""
    return (
        product.batches.filter(quantity__gte=requested_qty)
        .order_by("expiry_date", "id")
        .first()
    )

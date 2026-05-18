import os
import uuid
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from PIL import Image


def uuid_media_path(folder, prefix, filename):
    ext = os.path.splitext(filename)[1].lower().lstrip(".") or "bin"
    return f"{folder}/{prefix}_{uuid.uuid4().hex}.{ext}"


def product_image_path(instance, filename):
    return uuid_media_path("products", "product", filename)


def product_thumbnail_path(instance, filename):
    return uuid_media_path("products/thumbnails", "product_thumb", filename)


def receipt_path(instance, filename):
    return uuid_media_path("receipts", "receipt", filename)


def invoice_document_path(instance, filename):
    return uuid_media_path("invoices", "invoice", filename)


def avatar_path(instance, filename):
    return uuid_media_path("avatars", "avatar", filename)


def generate_product_barcode():
    return f"BC{timezone.now():%y%m%d}{uuid.uuid4().hex[:8].upper()}"


def validate_upload_size(value):
    max_mb = 8
    if value.size > max_mb * 1024 * 1024:
        raise ValidationError(f"File size must be {max_mb}MB or less.")


def validate_product_image(value):
    validate_upload_size(value)
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValidationError("Product images must be JPG, JPEG, PNG, or WebP.")


def validate_receipt_file(value):
    validate_upload_size(value)
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
        raise ValidationError("Receipts must be an image or PDF file.")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ProductCategory(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True, db_index=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#2563eb")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "product categories"

    def __str__(self):
        return self.name


class ProductBrand(TimeStampedModel):
    name = models.CharField(max_length=160, unique=True, db_index=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    sku = models.CharField(max_length=64, unique=True, blank=True, null=True)
    barcode = models.CharField(max_length=80, unique=True, blank=True, null=True, db_index=True)
    name = models.CharField(max_length=220, db_index=True)
    generic_name = models.CharField(max_length=220, blank=True, db_index=True)
    strength = models.CharField(max_length=80, blank=True)
    dosage_form = models.CharField(max_length=80, blank=True)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    brand = models.ForeignKey(
        ProductBrand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to=product_image_path,
        blank=True,
        validators=[validate_product_image],
    )
    thumbnail = models.ImageField(upload_to=product_thumbnail_path, blank=True, editable=False)
    is_antibiotic = models.BooleanField(default=False)
    reorder_level = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["generic_name"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["is_antibiotic"]),
        ]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"{self.name} {self.strength}".strip()

    @property
    def total_stock(self):
        return self.batches.aggregate(total=Sum("stock_quantity"))["total"] or 0

    @property
    def best_batch(self):
        return (
            self.batches.filter(is_active=True, stock_quantity__gt=0, expiry_date__gt=timezone.localdate())
            .order_by("expiry_date", "created_at")
            .first()
        )

    def save(self, *args, **kwargs):
        if not self.barcode:
            self.barcode = generate_product_barcode()
        super().save(*args, **kwargs)
        if self.image and not self.image.name.lower().endswith(".webp"):
            image_file = self.image
            image_file.open("rb")
            source = Image.open(image_file).convert("RGB")
            source.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            optimized = BytesIO()
            source.save(optimized, format="WEBP", quality=82, method=6)

            thumb = source.copy()
            thumb.thumbnail((200, 200), Image.Resampling.LANCZOS)
            thumb_io = BytesIO()
            thumb.save(thumb_io, format="WEBP", quality=78, method=6)

            base = uuid.uuid4().hex
            self.image.save(f"products/product_{base}.webp", ContentFile(optimized.getvalue()), save=False)
            self.thumbnail.save(
                f"products/thumbnails/product_thumb_{base}.webp",
                ContentFile(thumb_io.getvalue()),
                save=False,
            )
            super().save(update_fields=["image", "thumbnail", "updated_at"])
        elif self.image and not self.thumbnail:
            image_file = self.image
            image_file.open("rb")
            source = Image.open(image_file).convert("RGB")
            source.thumbnail((200, 200), Image.Resampling.LANCZOS)
            thumb_io = BytesIO()
            source.save(thumb_io, format="WEBP", quality=78, method=6)
            self.thumbnail.save(
                f"products/thumbnails/product_thumb_{uuid.uuid4().hex}.webp",
                ContentFile(thumb_io.getvalue()),
                save=False,
            )
            super().save(update_fields=["thumbnail", "updated_at"])


class ProductBatch(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    batch_number = models.CharField(max_length=100, db_index=True)
    mfg_date = models.DateField("Manufacturing date", null=True, blank=True)
    expiry_date = models.DateField(db_index=True)
    buy_price = models.DecimalField(max_digits=12, decimal_places=2)
    tp_price = models.DecimalField("TP price", max_digits=12, decimal_places=2)
    mrp = models.DecimalField("MRP", max_digits=12, decimal_places=2)
    buy_price_per_box = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tp_price_per_box = models.DecimalField("TP price per box", max_digits=12, decimal_places=2, default=0)
    mrp_per_box = models.DecimalField("MRP per box", max_digits=12, decimal_places=2, default=0)
    number_of_boxes = models.PositiveIntegerField(default=1)
    units_per_box = models.PositiveIntegerField(default=1)
    stock_quantity = models.PositiveIntegerField(default=0)
    shelf_number = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["expiry_date", "batch_number"]
        constraints = [
            models.UniqueConstraint(fields=["product", "batch_number"], name="unique_batch_per_product"),
        ]
        indexes = [
            models.Index(fields=["batch_number"]),
            models.Index(fields=["expiry_date"]),
            models.Index(fields=["stock_quantity"]),
        ]

    def __str__(self):
        return f"{self.product.display_name} - {self.batch_number}"

    @property
    def is_expired(self):
        return self.expiry_date <= timezone.localdate()

    @property
    def profit_per_unit(self):
        return self.tp_price - self.buy_price

    def clean(self):
        if self.expiry_date and self.expiry_date <= timezone.localdate():
            raise ValidationError({"expiry_date": "Batch expiry date must be in the future."})
        if self.mfg_date and self.expiry_date and self.mfg_date >= self.expiry_date:
            raise ValidationError({"mfg_date": "Manufacturing date must be before expiry date."})
        for field in ("buy_price", "tp_price", "mrp", "buy_price_per_box", "tp_price_per_box", "mrp_per_box"):
            value = getattr(self, field)
            if value is not None and value < Decimal("0"):
                raise ValidationError({field: "Price cannot be negative."})


class Customer(TimeStampedModel):
    customer_code = models.CharField(max_length=40, unique=True, blank=True)
    name = models.CharField(max_length=160, db_index=True)
    phone = models.CharField(max_length=40, unique=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name", "phone"])]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    def save(self, *args, **kwargs):
        if not self.customer_code:
            self.customer_code = f"CUST-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def total_bought(self):
        return self.invoices.aggregate(total=Sum("grand_total"))["total"] or Decimal("0.00")

    @property
    def total_paid(self):
        return self.invoices.aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")

    @property
    def total_due(self):
        return self.invoices.aggregate(total=Sum("due_amount"))["total"] or Decimal("0.00")


class Supplier(TimeStampedModel):
    supplier_code = models.CharField(max_length=40, unique=True, blank=True)
    name = models.CharField(max_length=180, db_index=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, db_index=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    opening_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.supplier_code:
            self.supplier_code = f"SUP-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def total_due(self):
        due = self.purchase_invoices.aggregate(total=Sum("due_amount"))["total"] or Decimal("0.00")
        return self.opening_due + due


class PurchaseInvoice(TimeStampedModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_invoices")
    invoice_number = models.CharField(max_length=80, unique=True, db_index=True)
    invoice_date = models.DateField(default=timezone.localdate)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-invoice_date", "-created_at"]

    def __str__(self):
        return self.invoice_number


class PurchaseInvoiceItem(TimeStampedModel):
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name="items")
    product_batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, related_name="purchase_items")
    quantity = models.PositiveIntegerField()
    buy_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.purchase_invoice.invoice_number} - {self.product_batch}"


class InvoiceSequence(models.Model):
    date = models.DateField(unique=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date}: {self.last_number}"


class SalesInvoice(TimeStampedModel):
    PAYMENT_UNPAID = "unpaid"
    PAYMENT_PARTIAL = "partial"
    PAYMENT_PAID = "paid"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_UNPAID, "Unpaid"),
        (PAYMENT_PARTIAL, "Partially paid"),
        (PAYMENT_PAID, "Fully paid"),
    ]

    invoice_number = models.CharField(max_length=40, unique=True, db_index=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )
    customer_name = models.CharField(max_length=160, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True, db_index=True)
    invoice_date = models.DateField(default=timezone.localdate, db_index=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_UNPAID)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["invoice_number"]),
            models.Index(fields=["invoice_date"]),
            models.Index(fields=["customer_phone"]),
        ]

    def __str__(self):
        return self.invoice_number


class SalesInvoiceItem(TimeStampedModel):
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sales_items")
    product_batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, related_name="sales_items")
    product_name = models.CharField(max_length=240)
    batch_number = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    buy_price = models.DecimalField(max_digits=12, decimal_places=2)
    returned_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.product_name}"

    @property
    def returnable_quantity(self):
        return max(self.quantity - self.returned_quantity, 0)


class ReturnTransaction(TimeStampedModel):
    REFUND_CASH = "cash"
    REFUND_ADJUST_DUE = "adjust_due"
    REFUND_CHOICES = [
        (REFUND_CASH, "Cash refund"),
        (REFUND_ADJUST_DUE, "Adjust due"),
    ]

    return_number = models.CharField(max_length=40, unique=True, blank=True)
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="returns")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="returns")
    phone = models.CharField(max_length=40, blank=True)
    return_date = models.DateField(default=timezone.localdate, db_index=True)
    refund_method = models.CharField(max_length=20, choices=REFUND_CHOICES, default=REFUND_ADJUST_DUE)
    total_refund = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.return_number:
            self.return_number = f"RET-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:5].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.return_number


class ReturnItem(TimeStampedModel):
    return_transaction = models.ForeignKey(ReturnTransaction, on_delete=models.CASCADE, related_name="items")
    invoice_item = models.ForeignKey(SalesInvoiceItem, on_delete=models.PROTECT, related_name="return_items")
    quantity = models.PositiveIntegerField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    restock = models.BooleanField(default=True)


class AntibioticRegisterEntry(TimeStampedModel):
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="antibiotic_entries")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="antibiotic_entries")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="antibiotic_entries")
    quantity = models.PositiveIntegerField()
    sale_date = models.DateField(default=timezone.localdate, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-sale_date", "-created_at"]
        indexes = [models.Index(fields=["sale_date"])]

    def __str__(self):
        return f"{self.product.display_name} - {self.sale_date}"


class StockMovement(TimeStampedModel):
    ADD = "add"
    REMOVE = "remove"
    SALE = "sale"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    MOVEMENT_CHOICES = [
        (ADD, "Stock added"),
        (REMOVE, "Stock removed"),
        (SALE, "Sale"),
        (RETURN, "Return"),
        (ADJUSTMENT, "Adjustment"),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_movements")
    product_batch = models.ForeignKey(ProductBatch, on_delete=models.CASCADE, related_name="stock_movements")
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES, db_index=True)
    quantity = models.IntegerField()
    quantity_after = models.PositiveIntegerField()
    sales_invoice = models.ForeignKey(SalesInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    return_transaction = models.ForeignKey(ReturnTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["movement_type"]),
            models.Index(fields=["created_at"]),
        ]


class ReminderRule(TimeStampedModel):
    name = models.CharField(max_length=120)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    expiry_alert_days = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ReminderItem(TimeStampedModel):
    LOW_STOCK = "low_stock"
    EXPIRY = "expiry"
    TYPE_CHOICES = [
        (LOW_STOCK, "Low stock"),
        (EXPIRY, "Near expiry"),
    ]

    reminder_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reminders")
    product_batch = models.ForeignKey(ProductBatch, on_delete=models.CASCADE, null=True, blank=True, related_name="reminders")
    message = models.CharField(max_length=255)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["is_resolved", "due_date", "created_at"]


class UploadedDocument(TimeStampedModel):
    DOCUMENT_RECEIPT = "receipt"
    DOCUMENT_INVOICE = "invoice"
    DOCUMENT_OTHER = "other"
    DOCUMENT_CHOICES = [
        (DOCUMENT_RECEIPT, "Receipt / memo"),
        (DOCUMENT_INVOICE, "Invoice"),
        (DOCUMENT_OTHER, "Other document"),
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    document_type = models.CharField(max_length=20, choices=DOCUMENT_CHOICES, default=DOCUMENT_RECEIPT)
    title = models.CharField(max_length=180)
    file = models.FileField(upload_to=receipt_path, validators=[validate_receipt_file])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AppSetting(TimeStampedModel):
    store_name = models.CharField(max_length=180, default="Ashafa Traders Pharmacy")
    store_phone = models.CharField(max_length=60, blank=True)
    store_email = models.EmailField(blank=True)
    store_address = models.TextField(blank=True)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    near_expiry_days = models.PositiveIntegerField(default=60)
    invoice_footer = models.TextField(default="Thank you for choosing us.")
    print_logo = models.BooleanField(default=True)

    def __str__(self):
        return self.store_name

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class UserProfile(TimeStampedModel):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_STAFF, "Staff"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STAFF)
    phone = models.CharField(max_length=40, blank=True)
    avatar = models.ImageField(upload_to=avatar_path, blank=True, validators=[validate_product_image])

    def __str__(self):
        return f"{self.user.get_username()} profile"


class ActionLog(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=120)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

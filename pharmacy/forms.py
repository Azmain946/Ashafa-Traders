from decimal import Decimal

from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from .services import money
from .models import (
    AppSetting,
    Customer,
    Order,
    Product,
    ProductBatch,
    ProductBrand,
    ProductCategory,
    Supplier,
    UploadedDocument,
    UserProfile,
)


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault("class", "form-control")
            else:
                widget.attrs.setdefault("class", "form-control")
            widget.attrs.setdefault("placeholder", field.label or field_name.replace("_", " ").title())


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name",
            "generic_name",
            "strength",
            "category",
            "brand",
            "is_antibiotic",
        ]


class BoxPriceMixin:
    def _apply_box_values(self, batch):
        boxes = self.cleaned_data["number_of_boxes"]
        units = self.cleaned_data["units_per_box"]
        batch.stock_quantity = boxes * units
        batch.buy_price = (self.cleaned_data["buy_price_per_box"] / units).quantize(Decimal("0.00000001"))
        batch.tp_price = (self.cleaned_data["tp_price_per_box"] / units).quantize(Decimal("0.00000001"))
        batch.mrp = (self.cleaned_data["mrp_per_box"] / units).quantize(Decimal("0.00000001"))
        return batch


class ProductEntryForm(BoxPriceMixin, BootstrapFormMixin, forms.ModelForm):
    batch_number = forms.CharField(max_length=100, required=False)
    mfg_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    expiry_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    number_of_boxes = forms.IntegerField(min_value=1, initial=1)
    units_per_box = forms.IntegerField(min_value=1, initial=1, label="Medicine per box")
    buy_price_per_box = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12)
    tp_price_per_box = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label="TP price per box")
    mrp_per_box = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label="MRP per box")
    shelf_number = forms.CharField(max_length=80, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        self.fields["strength"].required = False

    class Meta:
        model = Product
        fields = [
            "name",
            "generic_name",
            "strength",
            "category",
            "brand",
            "is_antibiotic",
        ]

    def clean(self):
        cleaned = super().clean()
        mfg_date = cleaned.get("mfg_date")
        expiry_date = cleaned.get("expiry_date")
        if mfg_date and expiry_date and mfg_date >= expiry_date:
            self.add_error("mfg_date", "Manufacturing date must be before expiry date.")
        return cleaned

    def save(self, commit=True):
        product = super().save(commit=commit)
        batch = ProductBatch(
            product=product,
            batch_number=self.cleaned_data["batch_number"],
            mfg_date=self.cleaned_data.get("mfg_date"),
            expiry_date=self.cleaned_data["expiry_date"],
            buy_price_per_box=self.cleaned_data["buy_price_per_box"],
            tp_price_per_box=self.cleaned_data["tp_price_per_box"],
            mrp_per_box=self.cleaned_data["mrp_per_box"],
            number_of_boxes=self.cleaned_data["number_of_boxes"],
            units_per_box=self.cleaned_data["units_per_box"],
            shelf_number=self.cleaned_data.get("shelf_number", ""),
        )
        self._apply_box_values(batch)
        if commit:
            batch.full_clean()
            batch.save()
        self.created_batch = batch
        return product


class ProductBatchForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductBatch
        fields = [
            "batch_number",
            "mfg_date",
            "expiry_date",
            "number_of_boxes",
            "units_per_box",
            "buy_price_per_box",
            "tp_price_per_box",
            "mrp_per_box",
            "shelf_number",
        ]
        widgets = {
            "mfg_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["batch_number"].required = False
        self.fields["mfg_date"].required = False
        self.fields["shelf_number"].required = False

    def clean(self):
        cleaned = super().clean()
        mfg_date = cleaned.get("mfg_date")
        expiry_date = cleaned.get("expiry_date")
        if mfg_date and expiry_date and mfg_date >= expiry_date:
            self.add_error("mfg_date", "Manufacturing date must be before expiry date.")
        return cleaned

    def save(self, commit=True):
        batch = super().save(commit=False)
        boxes = self.cleaned_data["number_of_boxes"]
        units = self.cleaned_data["units_per_box"]
        batch.stock_quantity = boxes * units
        batch.buy_price = (self.cleaned_data["buy_price_per_box"] / units).quantize(Decimal("0.00000001"))
        batch.tp_price = (self.cleaned_data["tp_price_per_box"] / units).quantize(Decimal("0.00000001"))
        batch.mrp = (self.cleaned_data["mrp_per_box"] / units).quantize(Decimal("0.00000001"))
        if commit:
            batch.save()
        return batch


class StockAdjustmentForm(BootstrapFormMixin, forms.Form):
    ACTION_CHOICES = [("add", "Add stock"), ("remove", "Remove stock")]

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    quantity = forms.IntegerField(min_value=1)
    note = forms.CharField(max_length=255, required=False)


class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "notes"]

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        if len(digits) < 7:
            raise ValidationError("Enter a valid phone number.")
        return phone


class SupplierForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "opening_due"]


class CategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["name", "description", "color"]


class BrandForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductBrand
        fields = ["name", "contact_person", "phone", "email"]


class CheckoutForm(BootstrapFormMixin, forms.Form):
    customer_name = forms.CharField(max_length=160, required=False)
    customer_phone = forms.CharField(max_length=40, required=False)
    discount_percent = forms.DecimalField(min_value=0, max_value=100, decimal_places=2, max_digits=6, required=False, initial=0)
    discount_amount = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, required=False, initial=0)
    paid_amount = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, required=False, initial=0)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean(self):
        cleaned = super().clean()
        cleaned["discount_percent"] = cleaned.get("discount_percent") or Decimal("0.00")
        cleaned["discount_amount"] = cleaned.get("discount_amount") or Decimal("0.00")
        cleaned["paid_amount"] = cleaned.get("paid_amount") or Decimal("0.00")
        phone = cleaned.get("customer_phone", "").strip()
        if phone and len("".join(ch for ch in phone if ch.isdigit())) < 7:
            self.add_error("customer_phone", "Enter a valid phone number.")
        return cleaned


class OrderPaymentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ["paid_amount", "payment_status", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paid_amount"].label = "Total paid"
        if self.instance.payment_status != Order.PAYMENT_PARTIAL:
            self.fields["paid_amount"].widget.attrs["readonly"] = True

    def clean(self):
        cleaned = super().clean()
        grand_total = money(self.instance.grand_total)
        status = cleaned.get("payment_status")
        if status == Order.PAYMENT_PAID:
            cleaned["paid_amount"] = grand_total
        elif status == Order.PAYMENT_UNPAID:
            cleaned["paid_amount"] = Decimal("0.00")
        else:
            paid = money(cleaned.get("paid_amount"))
            if paid > grand_total:
                self.add_error("paid_amount", "Paid amount cannot exceed order total.")
            cleaned["paid_amount"] = paid
        return cleaned

    def save(self, commit=True):
        order = super().save(commit=False)
        grand_total = money(order.grand_total)
        if order.payment_status == Order.PAYMENT_PAID:
            order.paid_amount = grand_total
            order.due_amount = Decimal("0.00")
        elif order.payment_status == Order.PAYMENT_UNPAID:
            order.paid_amount = Decimal("0.00")
            order.due_amount = grand_total
        else:
            order.paid_amount = money(min(order.paid_amount, grand_total))
            order.due_amount = money(max(grand_total - order.paid_amount, Decimal("0.00")))
        if commit:
            order.save()
        return order


class ReturnLookupForm(BootstrapFormMixin, forms.Form):
    invoice_number = forms.CharField(max_length=40, required=False, label="Order ID")
    invoice_date = forms.DateField(required=False, label="Order date", widget=forms.DateInput(attrs={"type": "date"}))
    phone = forms.CharField(max_length=40, required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("invoice_number") and not cleaned.get("phone") and not cleaned.get("invoice_date"):
            raise ValidationError("Enter an order ID, order date, or phone number.")
        return cleaned


class SupplierReceiptForm(BootstrapFormMixin, forms.ModelForm):
    notes = forms.CharField(
        required=False,
        label="Note (optional)",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = UploadedDocument
        fields = ["supplier", "purchase_invoice", "document_type", "title", "notes"]


class AppSettingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AppSetting
        fields = [
            "store_name",
            "store_phone",
            "store_email",
            "store_address",
            "low_stock_threshold",
            "near_expiry_days",
            "invoice_footer",
            "print_logo",
        ]


class UserProfileForm(BootstrapFormMixin, forms.ModelForm):
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta:
        model = UserProfile
        fields = ["role", "phone", "email", "first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = self.user.email
        self.fields["first_name"].initial = self.user.first_name
        self.fields["last_name"].initial = self.user.last_name
        profile = getattr(self.user, "profile", None)
        if not (
            self.user.is_superuser
            or (profile and getattr(profile, "role", "") == UserProfile.ROLE_ADMIN)
        ):
            self.fields.pop("role", None)

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.email = self.cleaned_data["email"]
        self.user.first_name = self.cleaned_data["first_name"]
        self.user.last_name = self.cleaned_data["last_name"]
        if commit:
            self.user.save(update_fields=["email", "first_name", "last_name"])
            profile.save()
        return profile


class AdminUserForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass

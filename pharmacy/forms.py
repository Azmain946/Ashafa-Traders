from decimal import Decimal

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    AppSetting,
    Customer,
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
            "dosage_form",
            "category",
            "brand",
            "sku",
            "barcode",
            "description",
            "image",
            "is_antibiotic",
            "reorder_level",
            "is_active",
        ]


class ProductBatchForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductBatch
        fields = ["batch_number", "expiry_date", "buy_price", "tp_price", "mrp", "stock_quantity", "shelf_number", "is_active"]
        widgets = {"expiry_date": forms.DateInput(attrs={"type": "date"})}

    def clean_stock_quantity(self):
        quantity = self.cleaned_data["stock_quantity"]
        if quantity < 0:
            raise ValidationError("Stock cannot be negative.")
        return quantity


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


class ReturnLookupForm(BootstrapFormMixin, forms.Form):
    invoice_number = forms.CharField(max_length=40, required=False)
    invoice_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    phone = forms.CharField(max_length=40, required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("invoice_number") and not cleaned.get("phone"):
            raise ValidationError("Enter an invoice number or phone number.")
        return cleaned


class SupplierReceiptForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UploadedDocument
        fields = ["supplier", "purchase_invoice", "document_type", "title", "file"]


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
        fields = ["role", "phone", "avatar", "email", "first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = self.user.email
        self.fields["first_name"].initial = self.user.first_name
        self.fields["last_name"].initial = self.user.last_name

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

from django import forms

from apps.core.imaging import validate_receipt_upload

from .models import PurchaseInvoice, Supplier, UploadedReceipt


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ("name", "contact_person", "phone", "email", "address", "notes")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }


class PurchaseInvoiceForm(forms.ModelForm):
    class Meta:
        model = PurchaseInvoice
        fields = (
            "invoice_number",
            "invoice_date",
            "subtotal",
            "discount",
            "total",
            "paid_amount",
            "notes",
        )
        widgets = {
            "invoice_number": forms.TextInput(attrs={"class": "form-control"}),
            "invoice_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "subtotal": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "discount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "total": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "paid_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }


class UploadedReceiptForm(forms.ModelForm):
    class Meta:
        model = UploadedReceipt
        fields = ("title", "file", "purchase_invoice")
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional label"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "purchase_invoice": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, supplier=None, **kwargs):
        super().__init__(*args, **kwargs)
        if supplier is not None:
            self.fields["purchase_invoice"].queryset = supplier.purchase_invoices.all()
            self.fields["purchase_invoice"].required = False

    def clean_file(self):
        f = self.cleaned_data["file"]
        validate_receipt_upload(f)
        return f

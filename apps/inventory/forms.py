from django import forms
from django.utils import timezone

from apps.core.imaging import process_product_image, validate_image_upload

from .models import Manufacturer, Product, ProductBatch, ProductCategory


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "generic_name",
            "strength",
            "dosage_form",
            "category",
            "manufacturer",
            "barcode",
            "sku",
            "is_antibiotic",
            "requires_prescription",
            "is_active",
            "description",
            "image",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "generic_name": forms.TextInput(attrs={"class": "form-control"}),
            "strength": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 500 mg"}),
            "dosage_form": forms.Select(attrs={"class": "form-select"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "manufacturer": forms.Select(attrs={"class": "form-select"}),
            "barcode": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_antibiotic": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "requires_prescription": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "size"):
            validate_image_upload(image)
        return image

    def save(self, commit: bool = True) -> Product:
        product: Product = super().save(commit=False)
        uploaded = self.cleaned_data.get("image")
        # When a new file is uploaded (has size), optimize & build thumbnail.
        if uploaded and hasattr(uploaded, "size"):
            master, thumb = process_product_image(uploaded)
            product.image.save(master.name, master, save=False)
            product.thumbnail.save(thumb.name, thumb, save=False)
        if commit:
            product.save()
            self.save_m2m()
        return product


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ("name", "icon", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "icon": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. capsule"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
        }


class ManufacturerForm(forms.ModelForm):
    class Meta:
        model = Manufacturer
        fields = ("name", "country")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
        }


class ProductBatchForm(forms.ModelForm):
    class Meta:
        model = ProductBatch
        fields = (
            "batch_number",
            "expiry_date",
            "buy_price",
            "tp_price",
            "mrp",
            "quantity",
            "shelf_location",
        )
        widgets = {
            "batch_number": forms.TextInput(attrs={"class": "form-control"}),
            "expiry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "buy_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "tp_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "mrp": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "shelf_location": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_expiry_date(self):
        expiry = self.cleaned_data["expiry_date"]
        if expiry <= timezone.localdate():
            raise forms.ValidationError("Expiry date must be in the future.")
        return expiry


class StockAdjustmentForm(forms.Form):
    ADJUSTMENT_CHOICES = [
        ("add", "Add stock"),
        ("remove", "Remove stock"),
    ]

    batch = forms.ModelChoiceField(queryset=ProductBatch.objects.none(),
                                   widget=forms.Select(attrs={"class": "form-select"}))
    action = forms.ChoiceField(choices=ADJUSTMENT_CHOICES,
                               widget=forms.Select(attrs={"class": "form-select"}))
    quantity = forms.IntegerField(min_value=1,
                                  widget=forms.NumberInput(attrs={"class": "form-control"}))
    note = forms.CharField(required=False, max_length=200,
                           widget=forms.TextInput(attrs={"class": "form-control"}))

    def __init__(self, *args, product: Product | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if product is not None:
            self.fields["batch"].queryset = product.batches.all()

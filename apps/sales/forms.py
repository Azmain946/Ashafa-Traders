from django import forms

from apps.customers.models import Customer


class CheckoutForm(forms.Form):
    PAYMENT_CHOICES = [
        ("paid", "Fully paid"),
        ("partial", "Partially paid"),
        ("due", "Unpaid"),
    ]

    customer_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    customer_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Customer name"}),
    )
    customer_phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone number"}),
    )

    discount_type = forms.ChoiceField(
        choices=[("fixed", "Fixed"), ("percent", "Percent")],
        widget=forms.Select(attrs={"class": "form-select"}),
        initial="fixed",
    )
    discount_value = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "value": "0"}),
    )
    paid_amount = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "value": "0"}),
    )
    payment_status = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=False,
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Order notes"}),
    )

    def clean(self):
        cleaned = super().clean()
        customer_id = cleaned.get("customer_id")
        if not customer_id:
            name = (cleaned.get("customer_name") or "").strip()
            phone = (cleaned.get("customer_phone") or "").strip()
            if not name or not phone:
                raise forms.ValidationError("Customer name and phone are required.")
        return cleaned

    def get_or_create_customer(self) -> Customer:
        cid = self.cleaned_data.get("customer_id")
        if cid:
            try:
                return Customer.objects.get(pk=cid)
            except Customer.DoesNotExist:
                pass
        phone = self.cleaned_data.get("customer_phone", "").strip()
        name = self.cleaned_data.get("customer_name", "").strip()
        customer, _ = Customer.objects.get_or_create(
            phone=phone, defaults={"name": name or "Walk-in customer"}
        )
        if name and customer.name != name:
            customer.name = name
            customer.save(update_fields=["name"])
        return customer


class ReturnLookupForm(forms.Form):
    invoice_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "INV-20260101-0001"}),
    )
    invoice_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Customer phone"}),
    )

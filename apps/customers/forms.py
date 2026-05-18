from django import forms

from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ("name", "phone", "email", "address", "notes")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not phone:
            raise forms.ValidationError("Phone is required.")
        return phone

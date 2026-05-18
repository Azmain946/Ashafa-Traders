from django.urls import path

from . import views


urlpatterns = [
    path("", views.supplier_list, name="list"),
    path("new/", views.supplier_create, name="create"),
    path("<int:pk>/", views.supplier_detail, name="detail"),
    path("<int:pk>/edit/", views.supplier_edit, name="edit"),
    path("<int:supplier_id>/invoices/new/", views.purchase_invoice_create, name="invoice_create"),
    path("<int:supplier_id>/receipts/upload/", views.receipt_upload, name="receipt_upload"),
]

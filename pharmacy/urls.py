from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("order/", views.order_page, name="order"),
    path("checkout/", views.checkout, name="checkout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("products/", views.products, name="products"),
    path("products/add/", views.product_create, name="product_create"),
    path("batches/<int:pk>/barcode/", views.batch_barcode_print, name="batch_barcode_print"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("customers/", views.customers, name="customers"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("suppliers/", views.suppliers, name="suppliers"),
    path("suppliers/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("invoices/", views.invoices, name="invoices"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("returns/", views.returns, name="returns"),
    path("antibiotics/", views.antibiotic_registers, name="antibiotic_registers"),
    path("reminders/", views.reminders, name="reminders"),
    path("settings/", views.settings_page, name="settings"),
    path("api/search/products/", views.api_product_search, name="api_product_search"),
    path("api/products/<int:pk>/variants/", views.api_product_variants, name="api_product_variants"),
    path("api/cart/add/", views.api_cart_add, name="api_cart_add"),
    path("api/cart/remove/", views.api_cart_remove, name="api_cart_remove"),
    path("api/dashboard/", views.api_dashboard, name="api_dashboard"),
]

from django.urls import path

from . import views


urlpatterns = [
    path("order/", views.order_page, name="order"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/update/", views.cart_update, name="cart_update"),
    path("cart/remove/", views.cart_remove, name="cart_remove"),
    path("cart/clear/", views.cart_clear, name="cart_clear"),
    path("cart/summary/", views.cart_summary_api, name="cart_summary_api"),
    path("checkout/", views.checkout_view, name="checkout"),
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/print/", views.invoice_print, name="invoice_print"),
    path("returns/", views.returns_page, name="returns"),
    path("returns/submit/", views.returns_submit, name="returns_submit"),
    path("antibiotics/", views.antibiotic_register, name="antibiotic_register"),
]

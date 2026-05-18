from django.urls import path

from . import views


urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("new/", views.product_create, name="product_create"),
    path("<int:pk>/", views.product_detail, name="product_detail"),
    path("<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("<int:pk>/batches/add/", views.product_batch_add, name="product_batch_add"),
    path("<int:pk>/stock/adjust/", views.product_stock_adjust, name="product_stock_adjust"),
    path("categories/", views.category_list, name="categories"),
    path("manufacturers/", views.manufacturer_list, name="manufacturers"),
    path("api/search/", views.product_search_api, name="product_search_api"),
    path("reminders/", views.reminders_page, name="reminders"),
]

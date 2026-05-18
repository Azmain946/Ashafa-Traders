from django.urls import path

from . import views


urlpatterns = [
    path("", views.customer_list, name="list"),
    path("new/", views.customer_create, name="create"),
    path("<int:pk>/", views.customer_detail, name="detail"),
    path("<int:pk>/edit/", views.customer_edit, name="edit"),
    path("api/search/", views.customer_search_api, name="search_api"),
]

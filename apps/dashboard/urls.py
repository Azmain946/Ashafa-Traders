from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("metrics/", views.dashboard, name="metrics"),
    path("metrics/refresh/", views.dashboard_refresh, name="metrics_refresh"),
]

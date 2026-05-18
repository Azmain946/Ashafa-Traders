from django.urls import path

from . import views


urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("settings/", views.settings_page, name="settings"),
    path("settings/users/new/", views.staff_user_form, name="staff_create"),
    path("settings/users/<int:user_id>/edit/", views.staff_user_form, name="staff_edit"),
    path("settings/users/<int:user_id>/delete/", views.staff_user_delete, name="staff_delete"),
]

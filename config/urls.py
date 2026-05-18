from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="dashboard:home", permanent=False)),
    path("accounts/", include(("apps.accounts.urls", "accounts"), namespace="accounts")),
    path("dashboard/", include(("apps.dashboard.urls", "dashboard"), namespace="dashboard")),
    path("inventory/", include(("apps.inventory.urls", "inventory"), namespace="inventory")),
    path("customers/", include(("apps.customers.urls", "customers"), namespace="customers")),
    path("suppliers/", include(("apps.suppliers.urls", "suppliers"), namespace="suppliers")),
    path("sales/", include(("apps.sales.urls", "sales"), namespace="sales")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")

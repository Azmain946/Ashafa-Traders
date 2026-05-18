from .models import AppSetting


def branding(request):
    try:
        setting = AppSetting.load()
    except Exception:
        # Database may not be ready (e.g. before first migrate). Fail open.
        return {"app_setting": None, "business_name": "Pharmacy ERP", "currency_symbol": "৳"}
    return {
        "app_setting": setting,
        "business_name": setting.business_name,
        "currency_symbol": setting.currency_symbol,
    }

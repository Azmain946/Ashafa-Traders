from django import template

register = template.Library()


@register.filter
def dict_get(value, key):
    """Look up a key (int or string) in a dict-like value."""
    if value is None:
        return None
    try:
        if key in value:
            return value[key]
    except TypeError:
        pass
    try:
        return value[int(key)]
    except (KeyError, ValueError, TypeError):
        pass
    try:
        return value[str(key)]
    except (KeyError, ValueError, TypeError):
        return None


@register.filter
def currency(value, symbol="৳"):
    try:
        return f"{symbol}{float(value):,.2f}"
    except (TypeError, ValueError):
        return f"{symbol}0.00"


@register.filter
def attr(value, name):
    return getattr(value, name, "")

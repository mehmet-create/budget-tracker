from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def currency(context, value):
    """
    Formats a number with the user's preferred currency symbol.

    ✅ FIXED: the original read from request.session directly, duplicating
    exactly what the context_processors.py already does. Two systems doing the
    same job means two places to maintain and potential inconsistency if one
    updates and the other doesn't.

    Now it reads CUSTOM_CURRENCY_SYMBOL from the template context, which is
    already put there by the currency_symbol context processor on every request.
    One source of truth.
    """
    symbol = context.get('CUSTOM_CURRENCY_SYMBOL', '₦')

    try:
        val = float(value) if value not in (None, '') else 0.0
    except (ValueError, TypeError):
        val = 0.0

    return f"{symbol}{val:,.2f}"
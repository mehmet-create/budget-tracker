from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()

@register.simple_tag(takes_context=True)
def currency(context, value):
    request = context.get('request')
    symbol = '₦'
    if request and 'currency_symbol' in request.session:
        symbol = request.session['currency_symbol']
    
    try:
        if value is None or value == '':
            val_float = 0.0
        else:
            val_float = float(value)
    except (ValueError, TypeError):
        val_float = 0.0

    formatted_val = "{:,.2f}".format(val_float)
    
    return f"{symbol}{formatted_val}"
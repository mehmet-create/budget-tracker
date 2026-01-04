from django import template
from django.conf import settings

register = template.Library()
@register.simple_tag(takes_context=True)
def currency(context, value):
    """
    Formats a numeric value as currency using the symbol found in the request session.
    Note: We use simple_tag to avoid TemplateSyntaxError on some Django setups.
    """
    if value is None:
        value = 0
        
    request = context.get('request')
    session_symbol = None
    
    if request:
        session_symbol = request.session.get('currency_symbol')

    symbol = session_symbol or context.get('CUSTOM_CURRENCY_SYMBOL', '₦')
    
    formatted_value = "{:,.2f}".format(value)
    
    return f"{symbol}{formatted_value}"
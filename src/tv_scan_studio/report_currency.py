"""Explicit report monetary units only; never infer from symbol/account/input."""

SUPPORTED_REPORT_CURRENCIES = frozenset({
    "USD", "EUR", "AUD", "GBP", "NZD", "CAD", "CHF", "HKD", "JPY",
    "NOK", "SEK", "SGD", "TRY", "ZAR",
})


def report_currency_code(value):
    return value if isinstance(value, str) and value in SUPPORTED_REPORT_CURRENCIES else None

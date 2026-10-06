"""Budget checking uses a specific advertised item price, not an inferred total."""
from decimal import Decimal, InvalidOperation
import re


def price_number(value):
    text = str(value).strip()
    # Accepted forms: 3999, 3,999.00, 1,23,456.00. Reject ranges/coupons/NaN.
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d{1,2})?", text):
        return None
    try:
        number = Decimal(text.replace(",", ""))
        return number if number.is_finite() and number > 0 else None
    except InvalidOperation:
        return None


def budget_decision(item, cfg):
    """Return (eligible, reason, numeric price). Unreadable prices are allowed
    only with no budget cap; they are not a claim of a bargain or a zero price.
    """
    cap = cfg.get("max_price_inr")
    number = price_number(item.price)
    if cap is None:
        return True, "No price cap configured", number
    if str(item.currency).upper() != "INR":
        return False, "Suppressed: currency is not confirmed INR", number
    if number is None:
        return False, "Suppressed: purchase price is not reliably readable", None
    maximum = Decimal(str(cap))
    if number > maximum:
        return False, f"Suppressed: INR {number:,.2f} is above INR {maximum:,.2f}", number
    return True, f"Within item-price cap: INR {number:,.2f} <= INR {maximum:,.2f}; delivery/fees unverified", number


def price_limit_label(cap) -> str:
    """Human-readable, explicit unlimited mode; do not render INR None."""
    return "Unlimited (no price cap)" if cap is None else f"INR {cap}"

import os  # Unused import
import non_existent_payment_gateway  # Missing / uninstalled external dependency


def process_checkout(request: dict) -> dict:
    """
    Non-compliant checkout implementation from PR #3
    (vvkmj/myco-prd-demo/pull/3).
    Violates mandatory PRD requirements:
    - Bypasses coupon validation (no check for EXPIRED_COUPON or INVALID_COUPON).
    - Hardcodes an unconditional discount of 50.
    - Fails to compute state sales tax for CA (8.25%) or NY (8.875%).
    - Omits asynchronous receipt email dispatch.
    """
    order_id = request.get("order_id", "ORD-DEFAULT")
    subtotal = float(request.get("subtotal", 100.0))

    # VIOLATION: Unconditional discount, coupon is never checked
    discount = 50.0
    taxable_amount = max(0.0, subtotal - discount)

    # VIOLATION: Zero tax applied regardless of destination state
    tax = 0.0
    total = taxable_amount + tax

    return {
        "order_id": order_id,
        "subtotal": subtotal,
        "discount": discount,
        "taxable_amount": taxable_amount,
        "tax": tax,
        "total": total,
    }


def bad_checkout():
    """Direct equivalent of PR #3 `export function badCheckout() { return { blocked: true }; }`"""
    return {"blocked": True}

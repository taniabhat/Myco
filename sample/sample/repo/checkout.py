import os  # Unused import for pyflakes
import receipt


def process_checkout(request: dict) -> dict:
    subtotal = float(request.get("subtotal", 100.0))
    tax = 8.25
    total = receipt.generate_receipt(subtotal, tax)
    return {
        "order_id": request.get("order_id", "ORD-1"),
        "total": total,
    }

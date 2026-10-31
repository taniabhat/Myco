from typing import Dict, Any
try:
    from src.pricing import calculate_total, apply_discount
    from src.utils import round_money
except ImportError:
    from pricing import calculate_total, apply_discount
    from utils import round_money


def format_receipt(order: Dict[str, Any]) -> str:
    items = order.get("items", [])
    discount_pct = order.get("discount_percent", 0.0)
    subtotal = calculate_total(items)
    final_total = apply_discount(subtotal, discount_pct) if discount_pct else subtotal
    return f"Receipt for {order.get('customer', 'Customer')}: Subtotal=${subtotal:.2f}, Total=${final_total:.2f}"

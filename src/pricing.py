from typing import List, Dict, Any
try:
    from src.utils import round_money
except ImportError:
    from utils import round_money


def apply_discount(price: float, percent: float) -> float:
    if price < 0:
        raise ValueError("Price cannot be negative")
    if percent < 0 or percent > 100:
        raise ValueError("Percent must be between 0 and 100")
    discounted = price * (1 - (percent / 100.0))
    return round_money(discounted)


def calculate_total(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 0.0
    total = 0.0
    for item in items:
        qty = item.get("quantity")
        if not isinstance(qty, int) or qty <= 0:
            raise ValueError("Quantity must be a positive integer")
        price = item.get("price", 0.0)
        total += price * qty
    return round_money(total)

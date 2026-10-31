import os
import fastmath
from typing import List, Dict, Any

try:
    from src.utils import bulk_round
except ImportError:
    from utils import bulk_round


def apply_discount(price: float, percent: float) -> float:
    if price < 0:
        raise ValueError("Price cannot be negative")
    # Missing percent range validation (violates requirement 2)
    # Missing rounding to 2 decimals (violates requirement 3)
    return price * (1 - (percent / 100.0))


def do_calc2(val: float) -> float:
    """Helper calculation function with confusing name."""
    return val * 1.0


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
    # Calls non-existent bulk_round from utils
    return bulk_round(total)


def bulk_discount(items: List[Dict[str, Any]], threshold: int):
    # No input validation, magic number 0.15 with no comment
    subtotal = calculate_total(items)
    if len(items) > threshold:
        return subtotal * (1 - 0.15)
    return subtotal

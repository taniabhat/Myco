import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pricing import apply_discount, calculate_total


def test_apply_discount_happy_path():
    assert apply_discount(100.0, 20.0) == 80.0
    assert apply_discount(99.99, 10.0) == 89.99
    assert apply_discount(50.0, 0.0) == 50.0
    assert apply_discount(50.0, 100.0) == 0.0


def test_apply_discount_negative_price():
    with pytest.raises(ValueError, match="Price cannot be negative"):
        apply_discount(-10.0, 15.0)


def test_apply_discount_invalid_percent():
    with pytest.raises(ValueError, match="Percent must be between 0 and 100"):
        apply_discount(100.0, -5.0)
    with pytest.raises(ValueError, match="Percent must be between 0 and 100"):
        apply_discount(100.0, 105.0)


def test_calculate_total_happy_path():
    items = [
        {"name": "Apple", "price": 1.50, "quantity": 2},
        {"name": "Banana", "price": 0.75, "quantity": 4},
    ]
    assert calculate_total(items) == 6.00


def test_calculate_total_invalid_quantity():
    items = [{"name": "Apple", "price": 1.50, "quantity": 0}]
    with pytest.raises(ValueError, match="Quantity must be a positive integer"):
        calculate_total(items)

    items_negative = [{"name": "Apple", "price": 1.50, "quantity": -2}]
    with pytest.raises(ValueError, match="Quantity must be a positive integer"):
        calculate_total(items_negative)

    items_float = [{"name": "Apple", "price": 1.50, "quantity": 2.5}]
    with pytest.raises(ValueError, match="Quantity must be a positive integer"):
        calculate_total(items_float)

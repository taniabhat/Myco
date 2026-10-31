import fastmath  # Missing external module
from utils import round_money  # Broken link: round_money does not exist in utils.py


def generate_receipt(subtotal: float, tax: float) -> float:
    total = subtotal + tax
    return round_money(total)
